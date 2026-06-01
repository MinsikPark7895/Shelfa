import paho.mqtt.client as mqtt
import json
from core.config import settings

class MQTTService:
    def __init__(self):
        self.client = mqtt.Client("fastapi_publisher")
        # Docker 환경에서는 "mosquitto"를 호스트명으로 사용하지만,
        # 로컬(Host) 네트워크 모드에서는 localhost 사용 가능
        self.broker_host = "localhost" 
        self.broker_port = 1883
        
        # 인스턴스 생성 시 즉시 브로커에 연결
        self.connect()
        
    def connect(self):
        try:
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start()
            print("✅ MQTT 브로커에 성공적으로 연결되었습니다.")
        except Exception as e:
            print(f"❌ MQTT 연결 실패: {e}")

    def publish_pickup_command(self, task_id: str, book_id: str, location: str):
        """로봇에게 책 픽업 명령을 내리는 함수"""
        topic = "shelfa/robot/command"
        payload = {
            "task_id": task_id,
            "command": "PICKUP",
            "target_book": {
                "book_id": book_id,
                "location_name": location,
                # 두산 E0509 로봇이 닿을 수 있는 안전한 좌표(mm 단위)
                "coordinates": {"x": 400.0, "y": 0.0, "z": 300.0} 
            }
        }
        
        try:
            self.client.publish(topic, json.dumps(payload))
            print(f"🚀 로봇에게 명령 전송 완료: {topic} -> {payload}")
        except Exception as e:
            print(f"❌ MQTT 퍼블리시 에러: {e}")

mqtt_service = MQTTService()
