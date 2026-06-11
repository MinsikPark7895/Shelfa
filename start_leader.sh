#!/bin/bash

# Shelfa 통합 시스템 시작 스크립트 (팀장님 노트북 전용 - 멀티 터미널 버전)
# 그래픽/메모리 충돌을 방지하기 위해 3개의 새 터미널 창을 띄워 각각 안전하게 실행합니다.

echo "========================================="
echo "🚀 Shelfa 통합 지휘 통제 시스템 시작"
echo "========================================="

# 1. Gazebo 실행 (새 터미널 창)
echo "[1/3] 🌐 가상 세계(Gazebo)를 새 창에서 시작합니다..."
gnome-terminal --title="Shelfa_Gazebo" -- bash -c "source /opt/ros/humble/setup.bash; source /home/minsik/Desktop/Shelfa/ros2_ws/install/setup.bash; export TURTLEBOT3_MODEL=waffle_pi; export ROS_LOCALHOST_ONLY=0; ros2 launch turtlebot3_gazebo turtlebot3_world.launch.py; exec bash"

# 가제보가 완전히 켜져서 시계(time)가 돌기 시작할 때까지 10초 대기
echo "⏳ 가제보 초기화 대기 중 (10초)..."
sleep 10

# 2. Nav2 자율주행 실행 (새 터미널 창)
echo "[2/3] 🗺️ Nav2 자율주행 알고리즘을 새 창에서 시작합니다..."
gnome-terminal --title="Shelfa_Nav2" -- bash -c "source /opt/ros/humble/setup.bash; source /home/minsik/Desktop/Shelfa/ros2_ws/install/setup.bash; export TURTLEBOT3_MODEL=waffle_pi; export ROS_LOCALHOST_ONLY=0; ros2 launch turtlebot3_navigation2 navigation2.launch.py use_sim_time:=true map:=/home/minsik/Desktop/Shelfa/worlds/maps/library_map.yaml; exec bash"

# Nav2가 지도를 불러오고 AMCL 노드를 띄울 때까지 5초 대기
echo "⏳ Nav2 초기화 대기 중 (5초)..."
sleep 5

# 3. 마스터 노드 실행 (새 터미널 창)
echo "[3/3] 🧠 마스터 오케스트라 노드를 새 창에서 시작합니다..."
gnome-terminal --title="Shelfa_MasterNode" -- bash -c "source /opt/ros/humble/setup.bash; source /home/minsik/Desktop/Shelfa/ros2_ws/install/setup.bash; export ROS_LOCALHOST_ONLY=0; ros2 run master_orchestrator master_node; exec bash"

echo "========================================="
echo "✅ 모든 시스템 창이 성공적으로 열렸습니다!"
echo "새로 뜬 3개의 터미널 창에서 각각의 상황을 선명하게 확인하실 수 있습니다."
echo "🛑 끄실 때는 띄워진 터미널 3개의 창을 닫아주시거나 그 안에서 Ctrl+C를 누르시면 됩니다."
echo "========================================="
