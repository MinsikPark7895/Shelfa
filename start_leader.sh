#!/bin/bash

# Shelfa 통합 시스템 시작 스크립트 (단일 터미널 백그라운드 버전)
# Terminator 한 칸에서 실행하면 모든 시스템이 순서대로 백그라운드에서 돌아갑니다.

echo "========================================="
echo "🚀 Shelfa 통합 지휘 통제 시스템 시작"
echo "========================================="

# 환경 변수 설정
source /opt/ros/humble/setup.bash
source /home/minsik/Desktop/Shelfa/ros2_ws/install/setup.bash
export TURTLEBOT3_MODEL=waffle_pi
export ROS_LOCALHOST_ONLY=0
export ROS_DOMAIN_ID=30

# .env 환경 변수 불러오기 (MQTT 접속 및 암호)
if [ -f /home/minsik/Desktop/Shelfa/.env ]; then
  export $(grep -v '^#' /home/minsik/Desktop/Shelfa/.env | xargs)
fi

# ==========================================
# 1. Gazebo 실행
# ==========================================
echo "[1/3] 🌐 가상 세계(Gazebo)를 시작합니다..."
ros2 launch shelfa_gazebo shelfa_sim.launch.py &
GAZEBO_PID=$!

echo "⏳ 가제보 초기화 대기 중 (10초)..."
sleep 10

# ==========================================
# 2. Nav2 자율주행 실행
# ==========================================
echo "[2/3] 🗺️ Nav2 자율주행 알고리즘을 시작합니다..."
ros2 launch turtlebot3_navigation2 navigation2.launch.py use_sim_time:=true map:=/home/minsik/Desktop/Shelfa/worlds/maps/library_map.yaml &
NAV2_PID=$!

echo "⏳ Nav2 초기화 대기 중 (5초)..."
sleep 5

# ==========================================
# 3. 마스터 노드 실행
# ==========================================
echo "[3/3] 🧠 마스터 오케스트라 노드를 시작합니다..."
ros2 run master_orchestrator master_node &
MASTER_PID=$!

echo "========================================="
echo "✅ 모든 시스템이 성공적으로 가동되었습니다!"
echo "🛑 종료하시려면 이 터미널에서 [Ctrl + C]를 누르세요."
echo "========================================="

# Ctrl+C를 눌렀을 때 켜져있는 모든 프로세스와 좀비 프로세스까지 완벽하게 청소하는 로직
trap "echo -e '\n🛑 종료 신호 감지! 모든 시스템을 안전하게 종료합니다...'; killall -9 gzserver gzclient rviz2 component_container_isolated 2>/dev/null; kill $GAZEBO_PID $NAV2_PID $MASTER_PID 2>/dev/null; exit" SIGINT

wait
