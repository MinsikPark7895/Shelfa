import rclpy
from rclpy.node import Node
import paho.mqtt.client as mqtt
import json

from std_msgs.msg import Float64MultiArray
from dsr_msgs2.srv import MoveJoint, MoveLine, MoveSplineTask

class MqttBridgeNode(Node):
    def __init__(self):
        super().__init__('mqtt_bridge_node')
        self.get_logger().info('🤖 MQTT 브릿지(연속 궤적 모드)가 시작되었습니다.')
        
        self.move_joint_client = self.create_client(MoveJoint, '/dsr01/motion/move_joint')
        self.move_spline_client = self.create_client(MoveSplineTask, '/dsr01/motion/move_spline_task')

        # MQTT 설정 (paho-mqtt 2.0+ 호환성)
        try:
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "ros2_subscriber")
        except AttributeError:
            self.mqtt_client = mqtt.Client("ros2_subscriber")
            
        self.mqtt_client.on_message = self.on_message_received
        
        try:
            self.mqtt_client.connect("localhost", 1883, 60)
            self.mqtt_client.subscribe("shelfa/robot/command")
            self.mqtt_client.loop_start()
            self.get_logger().info('✅ MQTT 브로커 연결 성공')
        except Exception as e:
            self.get_logger().error(f'❌ MQTT 연결 실패: {e}')

    def on_message_received(self, client, userdata, msg):
        payload_str = msg.payload.decode("utf-8")
        data = json.loads(payload_str)
        self.get_logger().info(f"📩 서버로부터 명령 수신: {payload_str}")
        
        if data.get("command") == "PICKUP":
            waypoints = data["target_book"]["waypoints"]
            self.get_logger().info(f"🚀 총 {len(waypoints)}개의 연속 궤적 수신! 픽업 기동을 시작합니다.")
            self.execute_trajectory_task(waypoints)

    def execute_trajectory_task(self, waypoints):
        if not self.move_joint_client.wait_for_service(timeout_sec=2.0) or not self.move_spline_client.wait_for_service(timeout_sec=2.0):
            self.get_logger().error("❌ 로봇 제어 서비스(/dsr01/...)를 찾을 수 없습니다! 로봇이나 가상환경을 먼저 켜주세요.")
            return

        # ==========================================
        # STEP 1: 로봇 팔을 기본 대기 자세(Home)로 이동
        # ==========================================
        self.get_logger().info("1️⃣ 로봇 팔을 기본 자세로 이동합니다 (MoveJoint)")
        joint_req = MoveJoint.Request()
        joint_req.pos = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
        joint_req.vel = 30.0 
        joint_req.acc = 30.0 
        joint_req.time = 0.0
        
        # 동기로 대기
        self.move_joint_client.call(joint_req)

        # ==========================================
        # STEP 2: 연속 궤적(MoveSplineTask) 조립 및 전송
        # ==========================================
        self.get_logger().info("2️⃣ 끊김 없는 연속 궤적(MoveSplineTask) 기동을 시작합니다.")
        spline_req = MoveSplineTask.Request()
        
        # JSON의 waypoint 리스트를 ROS2의 Float64MultiArray 리스트로 변환
        for wp in waypoints:
            pos_array = Float64MultiArray()
            # [X, Y, Z, Rx, Ry, Rz]
            pos_array.data = [wp['x'], wp['y'], wp['z'], 0.0, 180.0, 0.0]
            spline_req.pos.append(pos_array)
            
        spline_req.pos_cnt = len(waypoints)
        spline_req.vel = [20.0, 20.0]
        spline_req.acc = [20.0, 20.0]
        spline_req.time = 0.0
        spline_req.ref = 0        # DR_BASE (로봇 베이스 기준)
        spline_req.mode = 0       # MOVE_MODE_ABSOLUTE (절대 좌표)
        spline_req.opt = 0        # SPLINE_VELOCITY_OPTION_DEFAULT
        spline_req.sync_type = 0  # SYNC (완전 도달 시까지 대기)

        # 통째로 전송 (두산 제어기가 알아서 큐에 넣고 부드럽게 이어줌)
        self.move_spline_client.call(spline_req)

        # ==========================================
        # STEP 3: 그리퍼 닫기 (TODO)
        # ==========================================
        self.get_logger().info("3️⃣ 그리퍼 작동 (책 픽업 완료!)")
        # TODO: 그리퍼 제어 로직 추가

def main(args=None):
    rclpy.init(args=args)
    node = MqttBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
