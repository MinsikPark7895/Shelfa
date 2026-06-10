import os
from dotenv import load_dotenv
import json

# 현재 경로 또는 상위 경로에서 .env 파일을 찾아 환경변수로 로드합니다.
load_dotenv(os.path.join(os.path.expanduser("~"), "Desktop", "Shelfa", ".env"))
import asyncio
import threading
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
from nav2_msgs.srv import SetInitialPose
import paho.mqtt.client as mqtt
from geometry_msgs.msg import Quaternion, PoseWithCovarianceStamped
import math

# 구역별 목적지 및 홈 위치 좌표 (새 SLAM 지도 기준 - Publish Point로 직접 측정)
SEMANTIC_MAP = {
    "ZONE_1": {"x": 3.900, "y": -1.240, "yaw": 0.0},
    "ZONE_2": {"x": 2.298, "y": 0.377,  "yaw": 0.0},
    "ZONE_3": {"x": 6.274, "y": 2.474,  "yaw": 0.0},
    "HOME":   {"x": 2.0, "y": -4.0, "yaw": 0.0}
}

def euler_to_quaternion(yaw):
    """간단한 Yaw -> Quaternion 변환 헬퍼 함수"""
    q = Quaternion()
    q.z = math.sin(yaw / 2.0)
    q.w = math.cos(yaw / 2.0)
    return q

class MasterOrchestratorNode(Node):
    def __init__(self, loop):
        super().__init__('master_orchestrator_node')
        self.loop = loop
        
        # 1. Nav2 자율주행 액션 클라이언트 생성
        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')

        # 2. MQTT 설정
        # 환경 변수 SHELFA_MQTT_BROKER가 있으면 그 값을 사용하고, 없으면 로컬(127.0.0.1) 사용
        self.mqtt_broker = os.environ.get("SHELFA_MQTT_BROKER", "127.0.0.1")
        self.mqtt_port = 1883
        self.topic_command = "shelfa/robot/command"
        self.topic_status = "shelfa/robot/status"
        
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.on_mqtt_message
        
        try:
            self.mqtt_client.connect(self.mqtt_broker, self.mqtt_port, 60)
            self.mqtt_client.loop_start() 
            self.get_logger().info(f"✅ MQTT 및 마스터 오케스트라 준비 완료!")
        except Exception as e:
            self.get_logger().error(f"❌ MQTT 연결 실패: {e}")

        # 3. AMCL 초기 위치 자동 설정 (Service 방식)
        self.initial_pose_client = self.create_client(SetInitialPose, '/set_initial_pose')
        # 백그라운드 태스크로 서비스 호출을 스케줄링
        asyncio.run_coroutine_threadsafe(self.call_set_initial_pose(), self.loop)

    async def call_set_initial_pose(self):
        self.get_logger().info("⏳ AMCL 초기화 서비스(/set_initial_pose) 대기 중...")
        while not self.initial_pose_client.wait_for_service(timeout_sec=1.0):
            pass
            
        req = SetInitialPose.Request()
        req.pose.header.frame_id = 'map'
        # 파이썬 get_clock()은 동기식이므로 asyncio 환경에서 주의해서 사용해야 하나, 이 노드에서는 가능
        req.pose.header.stamp = self.get_clock().now().to_msg()
        req.pose.pose.pose.position.x = 2.0
        req.pose.pose.pose.position.y = -4.0
        req.pose.pose.pose.position.z = 0.01
        req.pose.pose.pose.orientation = euler_to_quaternion(0.0)
        
        req.pose.pose.covariance[0] = 0.25
        req.pose.pose.covariance[7] = 0.25
        req.pose.pose.covariance[35] = 0.068
        
        future = self.initial_pose_client.call_async(req)
        await self.wait_for_ros_future(future)
        self.get_logger().info("🎯 AMCL /set_initial_pose 서비스 호출 완료! (로봇 초기 위치 확정)")

    def on_mqtt_connect(self, client, userdata, flags, rc):
        self.get_logger().info(f"MQTT Connected with result code {rc}")
        client.subscribe(self.topic_command)

    def on_mqtt_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            command = payload.get("command")
            
            if command == "PICKUP":
                book_info = payload.get("target_book", {})
                # 메인 스레드에서 생성한 asyncio 루프에 작업을 넘김
                asyncio.run_coroutine_threadsafe(
                    self.execute_pickup_workflow(book_info),
                    self.loop
                )
        except Exception as e:
            self.get_logger().error(f"메시지 파싱 에러: {e}")

    async def wait_for_ros_future(self, future):
        """ROS 2의 Future 객체를 파이썬의 asyncio에서 대기할 수 있게 해주는 브릿지 함수"""
        loop = asyncio.get_event_loop()
        event = asyncio.Event()
        def callback(f):
            loop.call_soon_threadsafe(event.set)
        future.add_done_callback(callback)
        await event.wait()
        return future.result()

    async def send_nav_goal(self, x, y, yaw):
        """Nav2 서버로 실제 좌표를 쏘고 도착할 때까지 대기하는 함수"""
        self.get_logger().info(f"Nav2 목적지 설정 (X:{x}, Y:{y}, Yaw:{yaw})")
        if not self.nav_client.wait_for_server(timeout_sec=3.0):
            self.get_logger().error("Nav2 Action Server를 찾을 수 없습니다!")
            return False
            
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = 'map'
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = float(x)
        goal_msg.pose.pose.position.y = float(y)
        goal_msg.pose.pose.orientation = euler_to_quaternion(yaw)
        
        # 1. 목표 전송 및 접수 확인
        send_goal_future = self.nav_client.send_goal_async(goal_msg)
        goal_handle = await self.wait_for_ros_future(send_goal_future)
        
        if not goal_handle.accepted:
            self.get_logger().error("Nav2에서 목적지를 거부했습니다.")
            return False
            
        # 2. 이동 완료 대기
        self.get_logger().info("Nav2 목표 승인됨. 로봇 이동 시작...")
        result_future = goal_handle.get_result_async()
        result = await self.wait_for_ros_future(result_future)
        
        # status == 4 는 SUCCEEDED(성공)을 의미
        return result.status == 4

    async def execute_pickup_workflow(self, book_info):
        book_id = book_info.get("book_id", "Unknown")
        # 백엔드에서 넘겨주는 구역명 (기본값 ZONE_1)
        location_name = book_info.get("location_name", "ZONE_1") 
        
        self.get_logger().info("="*50)
        self.get_logger().info(f"📡 '{book_id}' (위치: {location_name}) 대출 미션 수신!")
        
        coords = SEMANTIC_MAP.get(location_name)
        if not coords:
            self.get_logger().error(f"❌ 주소록에 '{location_name}'이 없습니다!")
            return
            
        # ======================================================
        # [Phase 1] 대기 위치 -> 책장 구역으로 주행
        # ======================================================
        self.get_logger().info(f"🚗 [Phase 1] {location_name} 으로 이동을 시작합니다.")
        nav_success = await self.send_nav_goal(coords['x'], coords['y'], coords['yaw'])
        if not nav_success:
            self.get_logger().error("이동 실패! 미션 취소.")
            return
        self.get_logger().info(f"🚗 [Phase 1] {location_name} 책장 앞에 무사히 도착했습니다.")
        
        # ======================================================
        # [Phase 2] 팀원 코드: 비전 & 로봇팔 제어 (현재는 대기 시뮬레이션)
        # ======================================================
        self.get_logger().info(f"🦾 [Phase 2] 동료의 비전 및 E0509 로봇팔 제어 시작 대기...")
        # TODO: 추후 여기에 팀원의 ROS 2 서비스/액션 호출 코드가 들어갑니다.
        await asyncio.sleep(5.0) 
        self.get_logger().info(f"🦾 [Phase 2] (가상) 비전 인식 및 로봇팔 픽업 완료!")
        
        # ======================================================
        # [Phase 3] 책장 구역 -> 다시 대기 위치(HOME)로 복귀
        # ======================================================
        self.get_logger().info(f"🏠 [Phase 3] 임무 완수. 홈 위치(HOME)로 복귀합니다.")
        home_coords = SEMANTIC_MAP["HOME"]
        return_success = await self.send_nav_goal(home_coords['x'], home_coords['y'], home_coords['yaw'])
        if not return_success:
            self.get_logger().error("홈 복귀 중 문제 발생!")
            return
            
        self.get_logger().info(f"✅ 모든 미션 완벽하게 종료!")
        self.get_logger().info("="*50)
        
        # 백엔드에 성공 보고 전송
        report = json.dumps({"status": "SUCCESS", "message": f"{book_id} 픽업 완료"})
        self.mqtt_client.publish(self.topic_status, report)

def main(args=None):
    rclpy.init(args=args)
    
    # 1. 메인 asyncio 이벤트 루프 생성
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # 2. 노드 생성 시 루프 전달
    node = MasterOrchestratorNode(loop)
    
    # 3. asyncio 이벤트 루프를 백그라운드 스레드에서 무한 실행 (워크플로우 처리용)
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    
    # 4. ROS 2 메인 스핀 (메시지 콜백 등 처리)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=1.0)
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
