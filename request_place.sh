#!/bin/bash
# ==============================================================
# Shelfa: Request Place Book Service
# ==============================================================
# Usage: ./request_place.sh [storage_id]
# Example: ./request_place.sh 2
# ==============================================================

STORAGE_ID="${1:-2}"

echo "=============================================================="
echo "📦 보관함에 책 넣기 요청 (보관함 ID: $STORAGE_ID)"
echo "=============================================================="

# ROS2 환경변수 불러오기
cd /home/user/Shelfa/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=26

ros2 service call /shelfa/place_book_in_storage shelfa_msgs/srv/PlaceBookInStorage \
  "{storage_id: $STORAGE_ID}"
