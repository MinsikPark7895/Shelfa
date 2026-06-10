#!/bin/bash
# ==============================================================
# Shelfa Book Pickup Pipeline Script
# ==============================================================
# Usage: ./run_pickup.sh "Book Title"
# Description: Executes steps 4 to 7 of the Doosan E0509 pick pipeline.
# ==============================================================

TARGET_BOOK="${1:-제3인류}" # 첫 번째 인자가 없으면 기본값으로 "제3인류" 사용

echo "=============================================================="
echo "로봇팔 파지 파이프라인 시작 (목표 도서: $TARGET_BOOK)"
echo "=============================================================="

# ROS 2 환경 소싱 (백그라운드 터미널 환경이 아닐 경우를 대비)
source /opt/ros/humble/setup.bash
source /home/minsik/Desktop/Shelfa/ros2_ws/install/setup.bash

echo "▶️ [Step 4] ArUco 기준 로봇 정렬 시작..."
ros2 run doosan_realsense_handeye aruco_marker_proto_align --ros-args \
  -p dry_run:=true \
  -p auto_run:=true \
  -p target_joint_pose_deg:="[5.24, 9.99, 119.36, -86.67, 94.04, 39.46]" \
  -p target_distance_m:=0.30 \
  -p coarse_max_step_mm:=10.0 \
  -p max_step_mm:=5.0 \
  -p axis_mode:=all \
  -p max_rot_step_deg:=2.0 \
  -p rotation_tolerance_deg:=2.0 \
  -p trans_vel_linear:=10.0 \
  -p trans_acc_linear:=20.0 \
  -p auto_post_motion_wait_sec:=0.4

echo "▶️ [Step 5] OCR 스캔 시작..."
ros2 run doosan_realsense_handeye book_scan_after_alignment -- \
  --target-title "$TARGET_BOOK" \
  --use-ocr-title-match \
  --yolo-conf 0.75 \
  --width 640 \
  --height 480 \
  --fps 30

echo "▶️ [Step 6] 목표 책 앞으로 이동..."
ros2 run doosan_realsense_handeye book_visual_servo_align --ros-args \
  -p dry_run:=true \
  -p auto_run:=true \
  -p target_lock_json:=./realtime_results/target_book_lock.json \
  -p target_distance_m:=0.0 \
  -p enable_book_angle_align:=false \
  -p yolo_conf:=0.60 \
  -p display_conf_threshold:=0.60 \
  -p coarse_max_step_mm:=10.0 \
  -p max_step_mm:=3.0 \
  -p coarse_axis_mode:=largest \
  -p axis_mode:=largest \
  -p runtime_track_max_pixel_distance:=320.0 \
  -p runtime_track_max_step_px:=90.0 \
  -p auto_max_steps:=80 \
  -p auto_step_period_sec:=0.5 \
  -p auto_post_motion_wait_sec:=0.5

echo "▶️ [Step 7] 최종 책 뽑기 시퀀스 시작..."
ros2 run doosan_realsense_handeye book_pick_sequence_node --ros-args \
  -p dry_run:=true \
  -p enable_gripper_control:=true \
  -p enable_place_to_box:=true \
  -p box_joint_pose_deg:="[0.0, 0.0, 90.0, 0.0, 90.0, 0.0]" \
  -p place_drop_distance_mm:=150.0 \
  -p gripper_open_position:=600 \
  -p pick_axis:=z \
  -p pick_axis_sign:=1.0 \
  -p insert1_mm:=300.0 \
  -p pull1_mm:=200.0 \
  -p insert2_mm:=100.0 \
  -p pull_final_mm:=200.0 \
  -p gripper_open_position_2:=600 \
  -p gripper_soft_grip_position:=680 \
  -p gripper_hard_grip_position:=690 \
  -p pick_vel_linear:=70.0 \
  -p pick_acc_linear:=140.0 \
  -p return_to_start_pose:=true \
  -p gripper_timeout_sec:=10.0

echo "✅ 모든 파지 시퀀스 종료!"
