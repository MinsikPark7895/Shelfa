#!/bin/bash

echo "========================================="
echo "🦾 Shelfa 두산 로봇팔 제어 시스템 시작"
echo "========================================="

# 환경 변수 설정 (경로는 팀원 컴퓨터 기준 ~/Shelfa)
source /opt/ros/humble/setup.bash
source ~/Shelfa/ros2_ws/install/setup.bash
export ROS_LOCALHOST_ONLY=0
export ROS_DOMAIN_ID=26

# ==========================================
# 1. 두산 로봇팔 본체 + RViz 실행
# ==========================================
echo "[1/3] 🦾 로봇팔 본체 및 RViz 실행 중..."
ros2 launch doosan_realsense_handeye dsr_bringup2_rviz_gripper_camera.launch.py mode:=real host:=110.120.1.56 port:=12345 model:=e0509 &
ROBOT_PID=$!

echo "⏳ 로봇팔 초기화 대기 (10초)..."
sleep 10

# ==========================================
# 2. 그리퍼 서비스 노드 실행
# ==========================================
echo "[2/3] 🖐️ 그리퍼 서비스 노드 실행 중..."
ros2 launch dsr_gripper_tcp gripper_service_node.launch.py controller_host:=110.120.1.56 namespace:=dsr01 &
GRIPPER_PID=$!

echo "⏳ 그리퍼 초기화 대기 (5초)..."
sleep 5

# ==========================================
# 3. 리얼센스 카메라 및 ArUco 마커 인식 실행
# ==========================================
echo "[3/3] 📷 리얼센스 카메라 및 ArUco 인식 실행 중..."
ros2 run doosan_realsense_handeye aruco_realsense_tf_publisher --ros-args -p target_id:=0 -p marker_length_m:=0.05 -p width:=640 -p height:=480 -p fps:=30 &
CAMERA_PID=$!

echo "========================================="
echo "✅ 모든 로봇팔 시스템 가동 완료! (마스터 노드 명령 대기 중)"
echo "🛑 종료하시려면 이 터미널에서 [Ctrl + C]를 누르세요."
echo "========================================="

# Ctrl+C를 눌렀을 때 모든 백그라운드 프로세스를 안전하게 종료
trap "echo -e '\n🛑 종료 신호 감지! 로봇팔 시스템을 안전하게 종료합니다...'; killall -9 rviz2 2>/dev/null; kill $ROBOT_PID $GRIPPER_PID $CAMERA_PID 2>/dev/null; exit" SIGINT

# 백그라운드 프로세스들이 계속 돌아가도록 스크립트를 대기 상태로 유지
wait
