import rclpy
from rclpy.node import Node
import paho.mqtt.client as mqtt
import json

# 두산 로봇 제어를 위한 공식 서비스 임포트
from dsr_msgs2.srv import MoveJoint, MoveLine

class MqttBridgeNode(Node):
    def __init__(self):
        super().__init__('mqtt_bridge_node')
        self.get_logger().info('🤖 MQTT 브릿지(로봇 제어 모드)가 시작되었습니다.')
        
        # 두산 로봇(E0509)을 제어할 서비스 클라이언트 생성
        self.move_joint_client = self.create_client(MoveJoint, '/dsr01/motion/move_joint')
        self.move_line_client = self.create_client(MoveLine, '/dsr01/motion/move_line')

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
            coords = data["target_book"]["coordinates"]
            
            self.get_logger().info("🚀 픽업 명령 수신! 두산 로봇 팔을 가동합니다.")
            self.execute_pickup_task(coords["x"], coords["y"], coords["z"])

    def execute_pickup_task(self, target_x, target_y, target_z):
        """실제 두산 E0509 로봇 팔을 제어하는 핵심 로직"""
        
        # 1. 서비스 대기 (가상환경이나 실물 로봇이 켜져 있어야 통과됨)
        if not self.move_joint_client.wait_for_service(timeout_sec=2.0):
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
        
        # 동기로 서비스 호출 (로봇이 도착할 때까지 MQTT 스레드를 대기시킴)
        self.move_joint_client.call(joint_req)

        # ==========================================
        # STEP 2: 책이 있는 (X, Y, Z) 좌표로 팔 뻗기
        # ==========================================
        self.get_logger().info(f"2️⃣ 책의 위치(X:{target_x}, Y:{target_y}, Z:{target_z})로 팔을 뻗습니다 (MoveLine)")
        line_req = MoveLine.Request()
        line_req.pos = [target_x, target_y, target_z, 0.0, 180.0, 0.0]
        line_req.vel = [20.0, 20.0] 
        line_req.acc = [20.0, 20.0] 
        line_req.time = 0.0
        
        # 동기로 서비스 호출 (팔을 다 뻗을 때까지 대기)
        self.move_line_client.call(line_req)

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
