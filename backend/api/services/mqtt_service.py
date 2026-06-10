import paho.mqtt.client as mqtt
import json
import os

class MQTTService:
    def __init__(self):
        self.client = mqtt.Client("fastapi_publisher")
        self.broker_host = os.environ.get("SHELFA_MQTT_BROKER", "localhost")
        self.broker_port = 1883
        
        # 환경변수에서 백엔드용 계정 정보 가져오기 (없으면 None)
        mqtt_user = os.environ.get("MQTT_BACKEND_USER")
        mqtt_pass = os.environ.get("MQTT_BACKEND_PASSWORD")
        
        # 값이 둘 다 존재할 때만 보안(비밀번호) 접속 모드로 설정
        if mqtt_user and mqtt_pass:
            self.client.username_pw_set(mqtt_user, mqtt_pass)
            
        self.connect()
        
    def connect(self):
        try:
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start()
            print("✅ MQTT 브로커에 성공적으로 연결되었습니다.")
        except Exception as e:
            print(f"❌ MQTT 연결 실패: {e}")

    def publish_pickup_command(self, task_id: str, book_id: str, location: str):
        """
        로봇 마스터 오케스트라 노드에게 책 픽업 명령을 발행합니다.
        
        [중요] location 값은 반드시 DB의 shelf_location 컬럼에
        "ZONE_1", "ZONE_2", "ZONE_3" 중 하나로 저장되어 있어야 합니다.
        """
        topic = "shelfa/robot/command"
        payload = {
            "command": "PICKUP",
            "target_book": {
                "book_id": book_id,
                "location_name": location  # DB의 shelf_location 값 (예: "ZONE_1")
            }
        }
        
        try:
            self.client.publish(topic, json.dumps(payload))
            print(f"🚀 [task:{task_id}] 로봇 출동 명령 전송: {location} → {book_id}")
        except Exception as e:
            print(f"❌ MQTT 퍼블리시 에러: {e}")
            # 연결이 끊겼을 경우 재연결 시도
            try:
                self.connect()
                self.client.publish(topic, json.dumps(payload))
            except Exception as retry_e:
                print(f"❌ MQTT 재연결 후에도 실패: {retry_e}")

mqtt_service = MQTTService()
