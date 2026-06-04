import json
import asyncio
import rclpy
from rclpy.node import Node
import paho.mqtt.client as mqtt

# 임시 주소록 (나중에는 DB 연동 또는 YAML 파일로 뺄 수 있음)
SEMANTIC_MAP = {
    "A-1": {"x": 1.5, "y": -2.3, "theta": 1.57},
    "B-2": {"x": 4.0, "y": 0.5, "theta": 0.0},
    "DISPENSER": {"x": 10.0, "y": 0.0, "theta": -1.57}
}

class MasterOrchestratorNode(Node):
    def __init__(self):
        super().__init__('master_orchestrator_node')
        
        # 1. MQTT 설정
        self.mqtt_broker = "127.0.0.1" # 도커 호스트 네트워크이므로 localhost
        self.mqtt_port = 1883
        self.topic_command = "shelfa/robot/command"
        self.topic_status = "shelfa/robot/status"
        
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.on_mqtt_message
        
        try:
            self.mqtt_client.connect(self.mqtt_broker, self.mqtt_port, 60)
            self.mqtt_client.loop_start() # 백그라운드 스레드에서 수신 대기
            self.get_logger().info(f"✅ MQTT 브로커({self.mqtt_broker})에 연결 성공! 마스터 노드 대기 중...")
        except Exception as e:
            self.get_logger().error(f"❌ MQTT 연결 실패: {e}")

    def on_mqtt_connect(self, client, userdata, flags, rc):
        self.get_logger().info(f"MQTT Connected with result code {rc}")
        client.subscribe(self.topic_command)

    def on_mqtt_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            command = payload.get("command")
            
            if command == "PICKUP":
                # 비동기 워크플로우를 ROS 2 이벤트 루프에서 실행
                book_info = payload.get("target_book", {})
                
                # create_task를 사용하여 메인 스레드를 블로킹하지 않음
                asyncio.run_coroutine_threadsafe(
                    self.execute_pickup_workflow(book_info),
                    asyncio.get_event_loop()
                )
        except Exception as e:
            self.get_logger().error(f"메시지 파싱 에러: {e}")

    async def execute_pickup_workflow(self, book_info):
        """가짜(Dummy) 픽업 워크플로우 시뮬레이션"""
        book_id = book_info.get("book_id", "Unknown")
        location_name = book_info.get("location_name", "A-1")
        
        self.get_logger().info("="*50)
        self.get_logger().info(f"📡 백엔드로부터 '{book_id}' (위치: {location_name}) 픽업 명령 수신!")
        
        # 1. 좌표 변환
        coords = SEMANTIC_MAP.get(location_name)
        if not coords:
            self.get_logger().error(f"❌ 주소록에 '{location_name}'이(가) 없습니다!")
            return
            
        self.get_logger().info(f"🗺️ 주소록 검색: {location_name}의 물리적 좌표는 (X: {coords['x']}, Y: {coords['y']}) 입니다.")
        
        # 2. SLAM 노드 주행 지시 시뮬레이션
        self.get_logger().info(f"🚗 [1단계: SLAM] Nav2 노드에게 주행 지시를 내렸습니다... (이동 중)")
        await asyncio.sleep(3) # 3초 대기
        self.get_logger().info(f"🚗 [1단계: SLAM] 주행 완료! 책장 앞에 도착했습니다.")
        
        # 3. Vision 노드 궤적 계산 지시 시뮬레이션
        self.get_logger().info(f"👁️ [2단계: Vision] 카메라 노드에게 '{book_id}' 위치 계산을 지시했습니다...")
        await asyncio.sleep(2) # 2초 대기
        self.get_logger().info(f"👁️ [2단계: Vision] 궤적 획득 완료! (waypoints 3개 수신)")
        
        # 4. Arm 노드 픽업 지시 시뮬레이션
        self.get_logger().info(f"🦾 [3단계: Arm] 로봇 팔 노드에게 궤적을 넘겨주고 픽업을 지시했습니다...")
        await asyncio.sleep(4) # 4초 대기
        self.get_logger().info(f"🦾 [3단계: Arm] 픽업 완료! 책을 트레이에 담았습니다.")
        
        # 5. 최종 완료 보고
        self.get_logger().info(f"✅ 모든 임무 완료! 백엔드에 성공 신호(MQTT)를 전송합니다.")
        self.get_logger().info("="*50)
        
        # 백엔드에 성공 보고 전송
        report = json.dumps({"status": "SUCCESS", "message": f"{book_id} 픽업 완료"})
        self.mqtt_client.publish(self.topic_status, report)

def main(args=None):
    rclpy.init(args=args)
    
    # asyncio의 메인 이벤트 루프를 생성
    loop = asyncio.get_event_loop()
    
    node = MasterOrchestratorNode()
    
    # ROS 2 스핀을 별도의 스레드처럼 작동하게 만들어서 asyncio와 충돌 방지
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
