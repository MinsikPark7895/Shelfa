#!/bin/bash
# ==============================================================
# Shelfa: Request Pick Book Service
# ==============================================================
# Usage: ./request_pick.sh [shelf_id] [book_title]
# Example: ./request_pick.sh 0 "제3인류"
# ==============================================================

SHELF_ID="${1:-0}"
BOOK_TITLE="${2:-제3인류}"

echo "=============================================================="
echo "📚 책 뽑기 요청 (책장 ID: $SHELF_ID, 도서명: '$BOOK_TITLE')"
echo "=============================================================="

# ROS2 환경변수 불러오기
cd /home/user/Shelfa/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=26

ros2 service call /shelfa/pick_book_from_shelf shelfa_msgs/srv/PickBookFromShelf \
  "{shelf_id: $SHELF_ID, book_title: '$BOOK_TITLE'}"
