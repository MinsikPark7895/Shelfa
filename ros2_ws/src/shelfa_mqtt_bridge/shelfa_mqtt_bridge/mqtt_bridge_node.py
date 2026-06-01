import rclpy
from rclpy.node import Node
import paho.mqtt.client as mqtt
import json

class MqttBridgeNode(Node):
    def __init__(self):
        super().__init__('mqtt_bridge_node')
        self.get_logger().info('🤖 MQTT 브릿지 노드가 시작되었습니다. 명령 대기 중...')
        
        # MQTT 설정 (paho-mqtt 2.0+ 버전 호환성)
        try:
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "ros2_subscriber")
        except AttributeError:
            # paho-mqtt 1.x 버전을 사용하는 경우
            self.mqtt_client = mqtt.Client("ros2_subscriber")
            
        self.mqtt_client.on_message = self.on_message_received
        
        # 실제 서버/브로커의 주소로 연결 (기본값 localhost)
        try:
            self.mqtt_client.connect("localhost", 1883, 60)
            self.mqtt_client.subscribe("shelfa/robot/command")
            self.mqtt_client.loop_start()
            self.get_logger().info('✅ MQTT 브로커 연결 성공')
        except Exception as e:
            self.get_logger().error(f'❌ MQTT 브로커 연결 실패: {e}')

    def on_message_received(self, client, userdata, msg):
        """FastAPI 서버에서 예약 명령이 떨어졌을 때 실행되는 함수"""
        payload_str = msg.payload.decode("utf-8")
        self.get_logger().info(f"📩 서버로부터 명령 수신: {payload_str}")
        
        try:
            data = json.loads(payload_str)
            if data.get("command") == "PICKUP":
                coords = data["target_book"]["coordinates"]
                x = coords["x"]
                y = coords["y"]
                
                self.get_logger().info(f"🚀 목표 좌표 (X: {x}, Y: {y})로 로봇 이동을 시작합니다!")
                # TODO: 추후 여기에 Nav2 Action Client (NavigateToPose) 연동 로직 추가
                self.navigate_to_pose(x, y, data.get("task_id"))
        except json.JSONDecodeError:
            self.get_logger().error("잘못된 JSON 형식이 수신되었습니다.")
        except KeyError as e:
            self.get_logger().error(f"메시지에 필요한 키가 없습니다: {e}")

    def navigate_to_pose(self, x, y, task_id):
        """실제 Nav2 스택과 통신하여 로봇을 움직이는 가상 함수"""
        self.get_logger().info(f"이동 중... 윙윙 🤖 (Task: {task_id})")
        # 이동 성공 후, 서버에 완료 신호 쏘기 로직 등 추가 예정

def main(args=None):
    rclpy.init(args=args)
    node = MqttBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.mqtt_client.loop_stop()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
