import threading
import time
import socket
from flask import Flask, render_template_string
from flask_socketio import SocketIO
import rclpy
from rclpy.node import Node

from dsr_example.simple.gripper_tcp_bridge import DoosanGripperTcpBridge, BridgeConfig
from dsr_example.simple.example_gripper_tcp import set_robot_mode_autonomous

app = Flask(__name__)
# 💡 핵심: 웹소켓 서버 초기화 (eventlet 비동기 모드 사용 권장)
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

bridge = None
ros_node = None
tcp_lock = threading.Lock()
# 20fps (50ms) 간격 설정
POLL_INTERVAL = 0.05 

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Doosan Gripper Web Control (20 FPS)</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        body { font-family: sans-serif; background: #f4f4f9; padding: 20px; }
        .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }
        .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
        .stat-box { background: #eef2f5; padding: 15px; border-radius: 6px; text-align: center; }
        .stat-value { font-size: 24px; font-weight: bold; color: #2c3e50; font-variant-numeric: tabular-nums; }
        .stat-label { font-size: 12px; color: #7f8c8d; text-transform: uppercase; }
        button { background: #3498db; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; font-size: 16px; margin-right: 10px;}
        button:hover { background: #2980b9; }
        .btn-danger { background: #e74c3c; }
        .btn-danger:hover { background: #c0392b; }
        input { padding: 8px; font-size: 16px; width: 100px; }
    </style>
</head>
<body>
    <h2>🚀 Gripper Control Dashboard <span style="font-size: 14px; color: orange;">(20 FPS Live)</span></h2>
    
    <div class="card">
        <h3>Live Status <span id="conn-status" style="font-size:12px; color:gray;">(Connecting...)</span></h3>
        <div class="grid">
            <div class="stat-box"><div class="stat-value" id="pos">--</div><div class="stat-label">Position</div></div>
            <div class="stat-box"><div class="stat-value" id="cur">--</div><div class="stat-label">Current (Force)</div></div>
            <div class="stat-box"><div class="stat-value" id="temp">--</div><div class="stat-label">Temperature</div></div>
            <div class="stat-box"><div class="stat-value" id="moving">--</div><div class="stat-label">Is Moving?</div></div>
        </div>
    </div>

    <div class="card">
        <h3>Control</h3>
        <input type="number" id="goal_pos" value="700" placeholder="Target Pos">
        <button onclick="moveToPos()">Move To</button>
        <button onclick="initGripper()" class="btn-danger">Initialize (Torque ON)</button>
    </div>

    <script>
        // 💡 핵심: HTTP Polling 대신 WebSocket 연결 설정
        const socket = io();

        socket.on('connect', function() {
            document.getElementById('conn-status').innerText = "(Connected 🟢)";
            document.getElementById('conn-status').style.color = "green";
        });

        socket.on('disconnect', function() {
            document.getElementById('conn-status').innerText = "(Disconnected 🔴)";
            document.getElementById('conn-status').style.color = "red";
        });

        // 서버에서 20fps로 쏘는 데이터를 받아서 즉시 화면 갱신
        socket.on('state_update', function(data) {
            if (data.status === "error") {
                document.getElementById('conn-status').innerText = "(Reconnecting Bridge...)";
                document.getElementById('conn-status').style.color = "orange";
                return;
            }
            document.getElementById('pos').innerText = data.present_position;
            document.getElementById('cur').innerText = data.present_current;
            document.getElementById('temp').innerText = data.present_temperature + "°C";
            document.getElementById('moving').innerText = data.moving === 1 ? "Yes 🏃" : "No 🛑";
        });

        // 💡 제어 명령도 WebSocket으로 전송
        function moveToPos() {
            const pos = document.getElementById('goal_pos').value;
            socket.emit('move_cmd', { goal_position: parseInt(pos) });
        }

        function initGripper() {
            socket.emit('init_cmd');
        }
    </script>
</body>
</html>
"""

def reset_socket_on_error():
    global bridge
    if bridge and bridge._socket:
        try:
            bridge._socket.close()
        except:
            pass
        bridge._socket = None

# 💡 백그라운드 상태 모니터링 스레드 (20fps 주기)
def background_polling_thread():
    while True:
        if bridge is not None:
            try:
                # 명령이 실행 중일 때는 락을 피하기 위해 non-blocking으로 시도하거나 아주 짧게 대기
                if tcp_lock.acquire(timeout=0.01):
                    try:
                        state = bridge.read_state()
                        data = {
                            "status": "ok",
                            "present_position": state.present_position,
                            "present_current": state.present_current,
                            "present_temperature": state.present_temperature,
                            "moving": state.moving
                        }
                        socketio.emit('state_update', data)
                    finally:
                        tcp_lock.release()
            except (BrokenPipeError, ConnectionError, socket.error):
                reset_socket_on_error()
                socketio.emit('state_update', {"status": "error"})
            except Exception as e:
                pass # 기타 일시적 에러 무시
        
        # 50ms 대기 (20fps 달성)
        time.sleep(POLL_INTERVAL)

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

# 💡 클라이언트에서 웹소켓을 통해 들어온 명령 처리
@socketio.on('move_cmd')
def handle_move(data):
    if bridge and 'goal_position' in data:
        def bg_move():
            try:
                with tcp_lock:
                    bridge.move_to(data['goal_position'], 5.0)
            except Exception:
                reset_socket_on_error()
        threading.Thread(target=bg_move).start()

@socketio.on('init_cmd')
def handle_init():
    if bridge:
        def bg_init():
            try:
                with tcp_lock:
                    bridge.initialize()
            except Exception:
                reset_socket_on_error()
        threading.Thread(target=bg_init).start()

def ros_thread():
    global bridge, ros_node
    rclpy.init(args=None)
    ros_node = rclpy.create_node("gripper_web_backend")
    
    bridge = DoosanGripperTcpBridge(
        node=ros_node,
        config=BridgeConfig(
            controller_host="110.120.1.56",
            namespace="dsr01",
            service_prefix=""
        )
    )
    
    try:
        ros_node.get_logger().info("Setting autonomous mode...")
        set_robot_mode_autonomous(ros_node, "dsr01", "")
        
        ros_node.get_logger().info("Starting TCP Bridge...")
        bridge.start()
        
        with tcp_lock:
            bridge.initialize()
            
        # 브릿지 초기화 완료 후 20fps 폴링 스레드 시작
        threading.Thread(target=background_polling_thread, daemon=True).start()
            
        rclpy.spin(ros_node)
    except Exception as e:
        ros_node.get_logger().error(f"ROS thread error: {e}")
    finally:
        bridge.close()
        ros_node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    threading.Thread(target=ros_thread, daemon=True).start()
    time.sleep(3) 
    print("🚀 Web server started! Open http://localhost:5000 in your browser.")
    # 💡 Flask 내장 서버 대신 SocketIO 서버로 실행
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)