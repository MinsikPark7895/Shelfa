#!/usr/bin/env bash
set -eo pipefail

echo "========================================="
echo "Shelfa 책 감지-집기 실행 전 필수 노드 시작"
echo "========================================="

# 스크립트가 실행되는 현재 디렉토리를 절대 경로로 자동 추출 (어떤 컴퓨터든 호환 가능)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHELFA_ROOT="${SHELFA_ROOT:-${SCRIPT_DIR}}"
ROS_WS="${ROS_WS:-${SHELFA_ROOT}/ros2_ws}"
ROBOT_HOST="${ROBOT_HOST:-110.120.1.56}"
ROBOT_PORT="${ROBOT_PORT:-12345}"
ROBOT_MODEL="${ROBOT_MODEL:-e0509}"
ROBOT_NAMESPACE="${ROBOT_NAMESPACE:-dsr01}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-26}"
ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-0}"

source /opt/ros/humble/setup.bash
if [ -f "${ROS_WS}/install/setup.bash" ]; then
  source "${ROS_WS}/install/setup.bash"
else
  echo "오류: ${ROS_WS}/install/setup.bash 파일을 찾을 수 없습니다."
  echo "먼저 아래 명령으로 빌드하세요:"
  echo "  cd ${ROS_WS}"
  echo "  colcon build --symlink-install"
  exit 1
fi

export ROS_DOMAIN_ID
export ROS_LOCALHOST_ONLY

PIDS=()

start_node() {
  local name="$1"
  shift
  echo
  echo "[$name] 실행 중:"
  printf '  %q' "$@"
  echo
  "$@" &
  PIDS+=("$!")
  sleep 2
}

cleanup() {
  echo
  echo "Shelfa 필수 노드를 종료합니다..."
  for pid in "${PIDS[@]}"; do
    kill "${pid}" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

cd "${ROS_WS}"

start_node "두산 로봇 bringup + RViz" \
  ros2 launch doosan_realsense_handeye dsr_bringup2_rviz_gripper_camera.launch.py \
    mode:=real \
    host:="${ROBOT_HOST}" \
    port:="${ROBOT_PORT}" \
    model:="${ROBOT_MODEL}"

echo "로봇 bringup 초기화를 기다립니다..."
sleep 8

start_node "RealSense 카메라" \
  ros2 launch realsense2_camera rs_launch.py \
    enable_color:=true \
    enable_depth:=true \
    align_depth.enable:=true \
    publish_tf:=true

start_node "그리퍼 서비스" \
  ros2 launch dsr_gripper_tcp gripper_service_node.launch.py \
    controller_host:="${ROBOT_HOST}" \
    namespace:="${ROBOT_NAMESPACE}"

start_node "ArUco marker 0 TF 발행기" \
  ros2 run doosan_realsense_handeye simple_aruco_marker_tf_publisher \
    --ros-args \
    -p marker_id:=0 \
    -p child_frame:=aruco_marker_0 \
    -p parent_frame:=camera_color_optical_frame \
    -p image_topic:=/camera/camera/color/image_raw \
    -p camera_info_topic:=/camera/camera/color/camera_info

start_node "ArUco marker 2 TF 발행기" \
  ros2 run doosan_realsense_handeye simple_aruco_marker2_tf_publisher \
    --ros-args \
    -p marker_id:=2 \
    -p child_frame:=aruco_marker_2 \
    -p parent_frame:=camera_color_optical_frame \
    -p image_topic:=/camera/camera/color/image_raw \
    -p camera_info_topic:=/camera/camera/color/camera_info

echo
echo "========================================="
echo "하드웨어 노드 실행이 완료되었습니다."
echo "이제 서비스 콜을 받을 '미션 서버'를 백그라운드에서 실행합니다."
echo "========================================="

start_node "미션 서비스 서버" \
  ros2 launch doosan_realsense_handeye book_mission_service_server.launch.py \
    dry_run:=false \
    dry_run_contract_mode:=false \
    auto_run:=true

echo
echo "========================================="
echo "✅ 모든 시스템과 미션 서버가 정상적으로 실행 중입니다!"
echo "이제 다른 터미널에서 쉘 스크립트를 통해 서비스 콜 명령을 내릴 수 있습니다."
echo "종료하려면 이 터미널에서 Ctrl+C를 누르세요."
echo "========================================="

wait
