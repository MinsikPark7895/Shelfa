#!/usr/bin/env python3
# Required before running this node:
#   ros2 launch realsense2_camera rs_launch.py enable_color:=true enable_depth:=true align_depth.enable:=true publish_tf:=true rgb_camera.color_profile:=1280x720x30 depth_module.depth_profile:=1280x720x30
#   ros2 run tf2_ros static_transform_publisher --x 0.047696284489303686 --y -0.04076754872954019 --z 0.06633768863669905 --qx 0.5047148772454931 --qy 0.5057702861100585 --qz 0.4949917689883712 --qw -0.49441122459849096 --frame-id link_6 --child-frame-id camera_link
#   ros2 run doosan_realsense_handeye simple_aruco_marker_tf_publisher --ros-args -p marker_id:=0 -p child_frame:=aruco_marker_0 -p parent_frame:=camera_color_optical_frame -p image_topic:=/camera/camera/color/image_raw -p camera_info_topic:=/camera/camera/color/camera_info
#   ros2 run doosan_realsense_handeye simple_aruco_marker2_tf_publisher --ros-args -p marker_id:=2 -p child_frame:=aruco_marker_2 -p parent_frame:=camera_color_optical_frame -p image_topic:=/camera/camera/color/image_raw -p camera_info_topic:=/camera/camera/color/camera_info
#   ros2 launch dsr_gripper_tcp gripper_service_node.launch.py
"""Home -> align -> detect -> pick -> place -> home mission state machine."""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import cv2
import rclpy
from dsr_msgs2.srv import GetCurrentPosx, MoveJoint, MoveLine
from rclpy.node import Node
from visualization_msgs.msg import MarkerArray

try:
    from dsr_gripper_tcp_interfaces.srv import GetState, SetPosition, SetTorque
except ImportError:
    GetState = None
    SetPosition = None
    SetTorque = None

try:
    from . import realtime_yolo_paddle_ocr as vision
    from .book_pick_sequence import BookPickSequenceConfig, BookPickSequenceExecutor
    from . import book_scan_after_alignment as scan
except ImportError:
    import realtime_yolo_paddle_ocr as vision
    from book_pick_sequence import BookPickSequenceConfig, BookPickSequenceExecutor
    import book_scan_after_alignment as scan


DEFAULT_HOME_JOINT_POSE_DEG = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
DEFAULT_PLACE_JOINT_POSE_DEG = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
DEFAULT_ALIGNMENT_TARGET_MARKER_ID = 0
DEFAULT_STATE_TRACE_JSON = "realtime_results/mission_state_trace.json"
DEFAULT_RESULT_JSON = "realtime_results/mission_result.json"
DEFAULT_MOVE_HOME_VEL_DEG = 30.0
DEFAULT_MOVE_HOME_ACC_DEG = 60.0
DEFAULT_MOVE_PLACE_VEL_DEG = 30.0
DEFAULT_MOVE_PLACE_ACC_DEG = 60.0


MISSION_STATES = [
    "START",
    "MOVE_HOME",
    "PREPARE_GRIPPER_VIEW",
    "ALIGN_MARKER",
    "DETECT_BOOK",
    "PREPARE_GRIPPER_PICK_OPEN",
    "MOVE_TO_BOOK_20CM_OFFSET",
    "LOWER_CAMERA_FOR_VERIFY",
    "VERIFY_BOOK_AGAIN",
    "ALIGN_BOOK_LATERAL",
    "MOVE_LEFT_1CM",
    "SET_GRIPPER_600_AFTER_ALIGN",
    "EXPERIMENTAL_PICK_CYCLES",
    "LOWER_TO_PLACE_BOOK",
    "ALIGN_MARKER2_AFTER_TEMP_PLACE",
    "REGRIP_TEMP_BOOK",
    "PLACE_BOOK_AT_MARKER2",
    "PICK_BOOK",
    "MOVE_TO_PLACE_POSE",
    "RELEASE_BOOK",
    "RETURN_HOME",
    "DONE",
    "ABORT",
]


class BookMissionStateMachine(Node):
    def __init__(self):
        super().__init__("book_mission_state_machine")
        self._declare_parameters()
        self._read_parameters()

        self.move_joint_client = self.create_client(MoveJoint, self.move_joint_service)
        self.move_line_client = self.create_client(MoveLine, self.move_line_service)
        self.current_posx_client = self.create_client(GetCurrentPosx, self.current_posx_service)
        if GetState is not None:
            self.gripper_state_client = self.create_client(GetState, self.gripper_state_service)
        else:
            self.gripper_state_client = None
        self.gripper_set_torque_client = None
        if SetTorque is not None:
            self.gripper_set_torque_client = self.create_client(
                SetTorque, self.gripper_set_torque_service
            )
        self.gripper_set_position_client = None
        if SetPosition is not None:
            self.gripper_set_position_client = self.create_client(
                SetPosition, self.gripper_set_position_service
            )
        self.last_gripper_state = None

        self.vision_node = vision.BookVisionRobotNode()
        self.pick_executor = BookPickSequenceExecutor(
            node=self,
            config=self.pick_config,
            move_joint_client=self.move_joint_client,
            move_joint_service=self.move_joint_service,
            move_line_client=self.move_line_client,
            move_line_service=self.move_line_service,
            gripper_state_client=self.gripper_state_client,
            gripper_state_service=self.gripper_state_service,
            gripper_set_torque_client=self.gripper_set_torque_client,
            gripper_set_torque_service=self.gripper_set_torque_service,
            gripper_set_position_client=self.gripper_set_position_client,
            gripper_set_position_service=self.gripper_set_position_service,
            start_tcp_posx_mm_deg=None,
        )

        self.state = "START"
        self.trace = []
        self.result = {
            "timestamp": datetime.now().isoformat(),
            "mode": "book_mission_state_machine",
            "status": "started",
            "state": self.state,
            "trace": self.trace,
            "alignment_payload": None,
            "book_scan_pose": None,
            "book_scan_result": None,
            "initial_book_scan_result": None,
            "verified_book_scan_result": None,
            "selected_book_candidate": None,
            "verified_selected_book_candidate": None,
            "book_pre_approach_result": None,
            "book_pre_verify_lower_result": None,
            "book_lateral_align_result": None,
            "book_left_shift_result": None,
            "gripper_after_lateral_result": None,
            "experimental_pick_cycles_result": None,
            "place_lower_result": None,
            "marker2_alignment_payload": None,
            "marker2_alignment_result": None,
            "regrip_temp_book_result": None,
            "marker2_place_result": None,
            "pick_result": None,
            "place_result": None,
            "home_result": None,
        }

    def _declare_parameters(self):
        self.declare_parameter("dry_run", True)
        self.declare_parameter("auto_run", False)
        self.declare_parameter("state_trace_json", DEFAULT_STATE_TRACE_JSON)
        self.declare_parameter("result_json", DEFAULT_RESULT_JSON)

        self.declare_parameter("alignment_payload_json", "./realtime_results/alignment_payload.json")
        self.declare_parameter("alignment_target_marker_id", DEFAULT_ALIGNMENT_TARGET_MARKER_ID)
        self.declare_parameter("alignment_dry_run", True)
        self.declare_parameter("alignment_auto_run", True)
        self.declare_parameter("alignment_run_post_pipeline", False)
        self.declare_parameter("alignment_timeout_sec", 180.0)
        self.declare_parameter("alignment_use_mock", False)
        self.declare_parameter("alignment_post_alignment_no_display", True)
        self.declare_parameter("alignment_enable_initial_translation_jump", True)
        self.declare_parameter("alignment_initial_translation_jump_axis_mode", "all")
        self.declare_parameter("alignment_initial_translation_jump_scale", 1.0)
        self.declare_parameter("alignment_initial_translation_jump_max_mm", 120.0)

        self.declare_parameter("target_title", "제3인류")
        self.declare_parameter("use_ocr_title_match", True)
        self.declare_parameter("allow_fallback_lock", True)
        self.declare_parameter("book_index", -1)
        self.declare_parameter("lock_book_index", -1)
        self.declare_parameter("no_display", True)
        self.declare_parameter("disable_ocr", False)
        self.declare_parameter("no_save_ocr_debug_crops", False)
        self.declare_parameter("ocr_target_long_side", 960)
        self.declare_parameter("ocr_crop_padding", 25)
        self.declare_parameter("disable_ocr_multi_input", False)
        self.declare_parameter("ocr_include_upright_rotations", False)
        self.declare_parameter("ocr_max_variants_per_book", 2)
        self.declare_parameter("ocr_max_books", 0)
        self.declare_parameter("ocr_early_stop_on_match", True)
        self.declare_parameter("ocr_early_stop_reasons", "title_match,title_fuzzy_match")
        self.declare_parameter("ocr_early_stop_on_partial", False)
        self.declare_parameter("yolo_conf", 0.75)
        self.declare_parameter("scan_width", 1280)
        self.declare_parameter("scan_height", 720)
        self.declare_parameter("scan_fps", 30)
        self.declare_parameter("scan_move_line_service", "/dsr01/motion/move_line")
        self.declare_parameter("scan_move_vel_linear", 20.0)
        self.declare_parameter("scan_move_vel_angular", 10.0)
        self.declare_parameter("scan_move_acc_linear", 40.0)
        self.declare_parameter("scan_move_acc_angular", 20.0)
        self.declare_parameter("scan_move_settle_sec", 1.0)
        self.declare_parameter("scan_move_timeout_sec", 30.0)
        self.declare_parameter("skip_scan_move", False)
        self.declare_parameter("require_depth_for_scan", True)

        self.declare_parameter("book_pre_approach_target_distance_m", 0.20)
        self.declare_parameter("book_pre_approach_max_step_m", 0.35)
        self.declare_parameter("book_pre_approach_axis", "z")
        self.declare_parameter("book_pre_approach_axis_sign", 1.0)
        self.declare_parameter("book_pre_approach_vel_linear", 20.0)
        self.declare_parameter("book_pre_approach_vel_angular", 10.0)
        self.declare_parameter("book_pre_approach_acc_linear", 40.0)
        self.declare_parameter("book_pre_approach_acc_angular", 20.0)
        self.declare_parameter("book_pre_approach_settle_sec", 0.7)
        self.declare_parameter("book_pre_verify_lower_enabled", True)
        self.declare_parameter("book_pre_verify_lower_z_mm", 70.0)
        self.declare_parameter("book_lateral_align_enabled", True)
        self.declare_parameter("book_lateral_target_pixel_x", -1.0)
        self.declare_parameter("book_lateral_pixel_tolerance_px", 12.0)
        self.declare_parameter("book_lateral_max_steps", 7)
        self.declare_parameter("book_lateral_max_step_mm", 15.0)
        self.declare_parameter("book_lateral_pixel_gain_mm_per_px", 0.15)
        self.declare_parameter("book_lateral_axis", "x")
        self.declare_parameter("book_lateral_axis_sign", -1.0)
        self.declare_parameter("book_lateral_settle_sec", 0.5)
        self.declare_parameter("book_left_shift_enabled", True)
        self.declare_parameter("book_left_shift_mm", 10.0)
        self.declare_parameter("book_left_shift_axis", "x")
        self.declare_parameter("book_left_shift_axis_sign", -1.0)
        self.declare_parameter("gripper_after_lateral_enabled", True)
        self.declare_parameter("gripper_after_lateral_position", 600)
        self.declare_parameter("experimental_pick_cycles_enabled", True)
        self.declare_parameter("experimental_pick_cycle_count", 3)
        self.declare_parameter("experimental_pick_cycle_distance_mm", 70.0)
        self.declare_parameter("experimental_pick_pre_approach_mm", 120.0)
        self.declare_parameter("experimental_pick_open_position", 600)
        self.declare_parameter("experimental_pick_soft_grip_position", 650)
        self.declare_parameter("experimental_pick_final_grip_position", 660)
        self.declare_parameter("experimental_pick_final_pull_mm", 400.0)
        self.declare_parameter("stop_after_experimental_pick_cycles", True)
        self.declare_parameter("place_after_experimental_pick_cycles", False)
        self.declare_parameter("place_lower_before_release_mm", 170.0)
        self.declare_parameter("marker2_alignment_enabled", False)
        self.declare_parameter(
            "marker2_alignment_payload_json",
            "./realtime_results/marker2_alignment_payload.json",
        )
        self.declare_parameter("marker2_alignment_dry_run", True)
        self.declare_parameter("marker2_alignment_auto_run", False)
        self.declare_parameter("marker2_alignment_timeout_sec", 240.0)
        self.declare_parameter("marker2_alignment_target_distance_m", 0.30)
        self.declare_parameter("marker2_alignment_enable_initial_translation_jump", True)
        self.declare_parameter("marker2_alignment_initial_translation_jump_axis_mode", "all")
        self.declare_parameter("marker2_alignment_initial_translation_jump_scale", 1.0)
        self.declare_parameter("marker2_alignment_initial_translation_jump_max_mm", 120.0)
        self.declare_parameter("regrip_after_marker2_alignment", False)
        self.declare_parameter("regrip_move_to_place_pose_first", True)
        self.declare_parameter("regrip_down_mm", 200.0)
        self.declare_parameter("regrip_open_position", 500)
        self.declare_parameter("regrip_close_position", 660)
        self.declare_parameter("marker2_place_after_regrip_enabled", False)
        self.declare_parameter("marker2_place_insert_z_mm", 400.0)
        self.declare_parameter("marker2_place_pre_insert_z_mm", 0.0)
        self.declare_parameter("marker2_place_drop_y_mm", 150.0)
        self.declare_parameter("marker2_place_open_position", 500)
        self.declare_parameter("marker2_place_return_home", True)
        self.declare_parameter("stop_after_gripper_after_lateral", False)
        self.declare_parameter("stop_after_book_verify_again", False)

        self.declare_parameter("home_joint_pose_deg", DEFAULT_HOME_JOINT_POSE_DEG)
        self.declare_parameter("place_joint_pose_deg", DEFAULT_PLACE_JOINT_POSE_DEG)
        self.declare_parameter("move_home_vel_deg", DEFAULT_MOVE_HOME_VEL_DEG)
        self.declare_parameter("move_home_acc_deg", DEFAULT_MOVE_HOME_ACC_DEG)
        self.declare_parameter("move_place_vel_deg", DEFAULT_MOVE_PLACE_VEL_DEG)
        self.declare_parameter("move_place_acc_deg", DEFAULT_MOVE_PLACE_ACC_DEG)

        self.declare_parameter("move_joint_service", "/dsr01/motion/move_joint")
        self.declare_parameter("move_line_service", "/dsr01/motion/move_line")
        self.declare_parameter("current_posx_service", "/dsr01/aux_control/get_current_posx")
        self.declare_parameter("current_posx_ref", 0)
        self.declare_parameter("service_call_timeout_sec", 60.0)
        self.declare_parameter("current_posx_timeout_sec", 10.0)
        self.declare_parameter("enable_gripper_control", True)
        self.declare_parameter("prepare_gripper_for_view", True)
        self.declare_parameter("prepare_gripper_for_pick_open", False)
        self.declare_parameter("gripper_state_service", "/gripper_service/get_state")
        self.declare_parameter("gripper_set_torque_service", "/gripper_service/set_torque")
        self.declare_parameter("gripper_set_position_service", "/gripper_service/set_position")
        self.declare_parameter("gripper_view_position", 0)
        self.declare_parameter("gripper_open_position", 600)
        self.declare_parameter("gripper_open_position_2", 630)
        self.declare_parameter("gripper_soft_grip_position", 650)
        self.declare_parameter("gripper_hard_grip_position", 660)
        self.declare_parameter("gripper_timeout_sec", 5.0)
        self.declare_parameter("gripper_require_ready", True)
        self.declare_parameter("gripper_require_torque_enabled", True)

        self.declare_parameter("pick_axis", "z")
        self.declare_parameter("pick_axis_sign", 1.0)
        self.declare_parameter("insert1_mm", 310.0)
        self.declare_parameter("pull1_mm", 310.0)
        self.declare_parameter("insert2_mm", 360.0)
        self.declare_parameter("pull_final_mm", 360.0)
        self.declare_parameter("pick_step_max_mm", 10.0)
        self.declare_parameter("pick_vel_linear", 60.0)
        self.declare_parameter("pick_vel_angular", 10.0)
        self.declare_parameter("pick_acc_linear", 120.0)
        self.declare_parameter("pick_acc_angular", 20.0)
        self.declare_parameter("place_box_joint_pose_deg", DEFAULT_PLACE_JOINT_POSE_DEG)
        self.declare_parameter("place_movej_vel", 30.0)
        self.declare_parameter("place_movej_acc", 60.0)

    def _read_parameters(self):
        self.dry_run = bool(self.get_parameter("dry_run").value)
        self.auto_run = bool(self.get_parameter("auto_run").value)
        self.state_trace_json = str(self.get_parameter("state_trace_json").value)
        self.result_json = str(self.get_parameter("result_json").value)

        self.alignment_payload_json = str(self.get_parameter("alignment_payload_json").value)
        self.alignment_target_marker_id = int(self.get_parameter("alignment_target_marker_id").value)
        self.alignment_dry_run = bool(self.get_parameter("alignment_dry_run").value)
        self.alignment_auto_run = bool(self.get_parameter("alignment_auto_run").value)
        self.alignment_run_post_pipeline = bool(
            self.get_parameter("alignment_run_post_pipeline").value
        )
        self.alignment_timeout_sec = float(self.get_parameter("alignment_timeout_sec").value)
        self.alignment_use_mock = bool(self.get_parameter("alignment_use_mock").value)
        self.alignment_post_alignment_no_display = bool(
            self.get_parameter("alignment_post_alignment_no_display").value
        )
        self.alignment_enable_initial_translation_jump = bool(
            self.get_parameter("alignment_enable_initial_translation_jump").value
        )
        self.alignment_initial_translation_jump_axis_mode = str(
            self.get_parameter("alignment_initial_translation_jump_axis_mode").value
        )
        self.alignment_initial_translation_jump_scale = float(
            self.get_parameter("alignment_initial_translation_jump_scale").value
        )
        self.alignment_initial_translation_jump_max_mm = float(
            self.get_parameter("alignment_initial_translation_jump_max_mm").value
        )

        self.target_title = str(self.get_parameter("target_title").value)
        self.use_ocr_title_match = bool(self.get_parameter("use_ocr_title_match").value)
        self.allow_fallback_lock = bool(self.get_parameter("allow_fallback_lock").value)
        self.book_index = int(self.get_parameter("book_index").value)
        self.lock_book_index = int(self.get_parameter("lock_book_index").value)
        self.no_display = bool(self.get_parameter("no_display").value)
        self.disable_ocr = bool(self.get_parameter("disable_ocr").value)
        self.no_save_ocr_debug_crops = bool(self.get_parameter("no_save_ocr_debug_crops").value)
        self.ocr_target_long_side = int(self.get_parameter("ocr_target_long_side").value)
        self.ocr_crop_padding = int(self.get_parameter("ocr_crop_padding").value)
        self.disable_ocr_multi_input = bool(self.get_parameter("disable_ocr_multi_input").value)
        self.ocr_include_upright_rotations = bool(
            self.get_parameter("ocr_include_upright_rotations").value
        )
        self.ocr_max_variants_per_book = int(self.get_parameter("ocr_max_variants_per_book").value)
        self.ocr_max_books = int(self.get_parameter("ocr_max_books").value)
        self.ocr_early_stop_on_match = bool(self.get_parameter("ocr_early_stop_on_match").value)
        self.ocr_early_stop_reasons = str(self.get_parameter("ocr_early_stop_reasons").value)
        self.ocr_early_stop_on_partial = bool(self.get_parameter("ocr_early_stop_on_partial").value)
        self.yolo_conf = float(self.get_parameter("yolo_conf").value)
        self.scan_width = int(self.get_parameter("scan_width").value)
        self.scan_height = int(self.get_parameter("scan_height").value)
        self.scan_fps = int(self.get_parameter("scan_fps").value)
        self.scan_move_line_service = str(self.get_parameter("scan_move_line_service").value)
        self.scan_move_vel_linear = float(self.get_parameter("scan_move_vel_linear").value)
        self.scan_move_vel_angular = float(self.get_parameter("scan_move_vel_angular").value)
        self.scan_move_acc_linear = float(self.get_parameter("scan_move_acc_linear").value)
        self.scan_move_acc_angular = float(self.get_parameter("scan_move_acc_angular").value)
        self.scan_move_settle_sec = float(self.get_parameter("scan_move_settle_sec").value)
        self.scan_move_timeout_sec = float(self.get_parameter("scan_move_timeout_sec").value)
        self.skip_scan_move = bool(self.get_parameter("skip_scan_move").value)
        self.require_depth_for_scan = bool(self.get_parameter("require_depth_for_scan").value)

        self.book_pre_approach_target_distance_m = float(
            self.get_parameter("book_pre_approach_target_distance_m").value
        )
        self.book_pre_approach_max_step_m = float(
            self.get_parameter("book_pre_approach_max_step_m").value
        )
        self.book_pre_approach_axis = str(
            self.get_parameter("book_pre_approach_axis").value
        ).lower()
        self.book_pre_approach_axis_sign = float(
            self.get_parameter("book_pre_approach_axis_sign").value
        )
        self.book_pre_approach_vel_linear = float(
            self.get_parameter("book_pre_approach_vel_linear").value
        )
        self.book_pre_approach_vel_angular = float(
            self.get_parameter("book_pre_approach_vel_angular").value
        )
        self.book_pre_approach_acc_linear = float(
            self.get_parameter("book_pre_approach_acc_linear").value
        )
        self.book_pre_approach_acc_angular = float(
            self.get_parameter("book_pre_approach_acc_angular").value
        )
        self.book_pre_approach_settle_sec = float(
            self.get_parameter("book_pre_approach_settle_sec").value
        )
        self.book_pre_verify_lower_enabled = bool(
            self.get_parameter("book_pre_verify_lower_enabled").value
        )
        self.book_pre_verify_lower_z_mm = float(
            self.get_parameter("book_pre_verify_lower_z_mm").value
        )
        self.book_lateral_align_enabled = bool(
            self.get_parameter("book_lateral_align_enabled").value
        )
        self.book_lateral_target_pixel_x = float(
            self.get_parameter("book_lateral_target_pixel_x").value
        )
        self.book_lateral_pixel_tolerance_px = float(
            self.get_parameter("book_lateral_pixel_tolerance_px").value
        )
        self.book_lateral_max_steps = int(
            self.get_parameter("book_lateral_max_steps").value
        )
        self.book_lateral_max_step_mm = float(
            self.get_parameter("book_lateral_max_step_mm").value
        )
        self.book_lateral_pixel_gain_mm_per_px = float(
            self.get_parameter("book_lateral_pixel_gain_mm_per_px").value
        )
        self.book_lateral_axis = str(
            self.get_parameter("book_lateral_axis").value
        ).lower()
        self.book_lateral_axis_sign = float(
            self.get_parameter("book_lateral_axis_sign").value
        )
        self.book_lateral_settle_sec = float(
            self.get_parameter("book_lateral_settle_sec").value
        )
        self.book_left_shift_enabled = bool(
            self.get_parameter("book_left_shift_enabled").value
        )
        self.book_left_shift_mm = float(
            self.get_parameter("book_left_shift_mm").value
        )
        self.book_left_shift_axis = str(
            self.get_parameter("book_left_shift_axis").value
        ).lower()
        self.book_left_shift_axis_sign = float(
            self.get_parameter("book_left_shift_axis_sign").value
        )
        self.gripper_after_lateral_enabled = bool(
            self.get_parameter("gripper_after_lateral_enabled").value
        )
        self.gripper_after_lateral_position = int(
            self.get_parameter("gripper_after_lateral_position").value
        )
        self.experimental_pick_cycles_enabled = bool(
            self.get_parameter("experimental_pick_cycles_enabled").value
        )
        self.experimental_pick_cycle_count = int(
            self.get_parameter("experimental_pick_cycle_count").value
        )
        self.experimental_pick_cycle_distance_mm = float(
            self.get_parameter("experimental_pick_cycle_distance_mm").value
        )
        self.experimental_pick_pre_approach_mm = float(
            self.get_parameter("experimental_pick_pre_approach_mm").value
        )
        self.experimental_pick_open_position = int(
            self.get_parameter("experimental_pick_open_position").value
        )
        self.experimental_pick_soft_grip_position = int(
            self.get_parameter("experimental_pick_soft_grip_position").value
        )
        self.experimental_pick_final_grip_position = int(
            self.get_parameter("experimental_pick_final_grip_position").value
        )
        self.experimental_pick_final_pull_mm = float(
            self.get_parameter("experimental_pick_final_pull_mm").value
        )
        self.stop_after_experimental_pick_cycles = bool(
            self.get_parameter("stop_after_experimental_pick_cycles").value
        )
        self.place_after_experimental_pick_cycles = bool(
            self.get_parameter("place_after_experimental_pick_cycles").value
        )
        self.place_lower_before_release_mm = float(
            self.get_parameter("place_lower_before_release_mm").value
        )
        self.marker2_alignment_enabled = bool(
            self.get_parameter("marker2_alignment_enabled").value
        )
        self.marker2_alignment_payload_json = str(
            self.get_parameter("marker2_alignment_payload_json").value
        )
        self.marker2_alignment_dry_run = bool(
            self.get_parameter("marker2_alignment_dry_run").value
        )
        self.marker2_alignment_auto_run = bool(
            self.get_parameter("marker2_alignment_auto_run").value
        )
        self.marker2_alignment_timeout_sec = float(
            self.get_parameter("marker2_alignment_timeout_sec").value
        )
        self.marker2_alignment_target_distance_m = float(
            self.get_parameter("marker2_alignment_target_distance_m").value
        )
        self.marker2_alignment_enable_initial_translation_jump = bool(
            self.get_parameter("marker2_alignment_enable_initial_translation_jump").value
        )
        self.marker2_alignment_initial_translation_jump_axis_mode = str(
            self.get_parameter("marker2_alignment_initial_translation_jump_axis_mode").value
        )
        self.marker2_alignment_initial_translation_jump_scale = float(
            self.get_parameter("marker2_alignment_initial_translation_jump_scale").value
        )
        self.marker2_alignment_initial_translation_jump_max_mm = float(
            self.get_parameter("marker2_alignment_initial_translation_jump_max_mm").value
        )
        self.regrip_after_marker2_alignment = bool(
            self.get_parameter("regrip_after_marker2_alignment").value
        )
        self.regrip_move_to_place_pose_first = bool(
            self.get_parameter("regrip_move_to_place_pose_first").value
        )
        self.regrip_down_mm = float(self.get_parameter("regrip_down_mm").value)
        self.regrip_open_position = int(self.get_parameter("regrip_open_position").value)
        self.regrip_close_position = int(self.get_parameter("regrip_close_position").value)
        self.marker2_place_after_regrip_enabled = bool(
            self.get_parameter("marker2_place_after_regrip_enabled").value
        )
        self.marker2_place_insert_z_mm = float(
            self.get_parameter("marker2_place_insert_z_mm").value
        )
        self.marker2_place_pre_insert_z_mm = float(
            self.get_parameter("marker2_place_pre_insert_z_mm").value
        )
        self.marker2_place_drop_y_mm = float(
            self.get_parameter("marker2_place_drop_y_mm").value
        )
        self.marker2_place_open_position = int(
            self.get_parameter("marker2_place_open_position").value
        )
        self.marker2_place_return_home = bool(
            self.get_parameter("marker2_place_return_home").value
        )
        self.stop_after_gripper_after_lateral = bool(
            self.get_parameter("stop_after_gripper_after_lateral").value
        )
        self.stop_after_book_verify_again = bool(
            self.get_parameter("stop_after_book_verify_again").value
        )

        self.home_joint_pose_deg = [float(v) for v in self.get_parameter("home_joint_pose_deg").value]
        self.place_joint_pose_deg = [
            float(v) for v in self.get_parameter("place_joint_pose_deg").value
        ]
        self.move_home_vel_deg = float(self.get_parameter("move_home_vel_deg").value)
        self.move_home_acc_deg = float(self.get_parameter("move_home_acc_deg").value)
        self.move_place_vel_deg = float(self.get_parameter("move_place_vel_deg").value)
        self.move_place_acc_deg = float(self.get_parameter("move_place_acc_deg").value)

        self.move_joint_service = str(self.get_parameter("move_joint_service").value)
        self.move_line_service = str(self.get_parameter("move_line_service").value)
        self.current_posx_service = str(self.get_parameter("current_posx_service").value)
        self.current_posx_ref = int(self.get_parameter("current_posx_ref").value)
        self.service_call_timeout_sec = float(self.get_parameter("service_call_timeout_sec").value)
        self.current_posx_timeout_sec = float(self.get_parameter("current_posx_timeout_sec").value)
        self.enable_gripper_control = bool(self.get_parameter("enable_gripper_control").value)
        self.prepare_gripper_for_view = bool(self.get_parameter("prepare_gripper_for_view").value)
        self.prepare_gripper_for_pick_open = bool(
            self.get_parameter("prepare_gripper_for_pick_open").value
        )
        self.gripper_state_service = str(self.get_parameter("gripper_state_service").value)
        self.gripper_set_torque_service = str(self.get_parameter("gripper_set_torque_service").value)
        self.gripper_set_position_service = str(
            self.get_parameter("gripper_set_position_service").value
        )
        self.gripper_view_position = int(self.get_parameter("gripper_view_position").value)
        self.gripper_open_position = int(self.get_parameter("gripper_open_position").value)
        self.gripper_open_position_2 = int(self.get_parameter("gripper_open_position_2").value)
        self.gripper_soft_grip_position = int(self.get_parameter("gripper_soft_grip_position").value)
        self.gripper_hard_grip_position = int(self.get_parameter("gripper_hard_grip_position").value)
        self.gripper_timeout_sec = float(self.get_parameter("gripper_timeout_sec").value)
        self.gripper_require_ready = bool(self.get_parameter("gripper_require_ready").value)
        self.gripper_require_torque_enabled = bool(
            self.get_parameter("gripper_require_torque_enabled").value
        )

        self.pick_axis = str(self.get_parameter("pick_axis").value).lower()
        self.pick_axis_sign = float(self.get_parameter("pick_axis_sign").value)
        self.insert1_mm = float(self.get_parameter("insert1_mm").value)
        self.pull1_mm = float(self.get_parameter("pull1_mm").value)
        self.insert2_mm = float(self.get_parameter("insert2_mm").value)
        self.pull_final_mm = float(self.get_parameter("pull_final_mm").value)
        self.pick_step_max_mm = float(self.get_parameter("pick_step_max_mm").value)
        self.pick_vel_linear = float(self.get_parameter("pick_vel_linear").value)
        self.pick_vel_angular = float(self.get_parameter("pick_vel_angular").value)
        self.pick_acc_linear = float(self.get_parameter("pick_acc_linear").value)
        self.pick_acc_angular = float(self.get_parameter("pick_acc_angular").value)

        self.pick_config = BookPickSequenceConfig(
            enable_gripper_control=self.enable_gripper_control,
            dry_run=self.dry_run,
            gripper_timeout_sec=self.gripper_timeout_sec,
            gripper_open_position=self.gripper_open_position,
            gripper_open_position_2=self.gripper_open_position_2,
            gripper_soft_grip_position=self.gripper_soft_grip_position,
            gripper_hard_grip_position=self.gripper_hard_grip_position,
            gripper_require_ready=self.gripper_require_ready,
            gripper_require_torque_enabled=self.gripper_require_torque_enabled,
            pick_axis=self.pick_axis,
            pick_axis_sign=self.pick_axis_sign,
            insert1_mm=self.insert1_mm,
            pull1_mm=self.pull1_mm,
            insert2_mm=self.insert2_mm,
            pull_final_mm=self.pull_final_mm,
            pick_step_max_mm=self.pick_step_max_mm,
            pick_vel_linear=self.pick_vel_linear,
            pick_vel_angular=self.pick_vel_angular,
            pick_acc_linear=self.pick_acc_linear,
            pick_acc_angular=self.pick_acc_angular,
            return_to_start_pose=False,
            return_vel_linear=self.move_home_vel_deg,
            return_vel_angular=10.0,
            return_acc_linear=self.move_home_acc_deg,
            return_acc_angular=20.0,
            enable_place_to_box=False,
            box_joint_pose_deg=self.place_joint_pose_deg,
            box_movej_vel=self.move_place_vel_deg,
            box_movej_acc=self.move_place_acc_deg,
            place_drop_distance_mm=0.0,
        )

        self.scan_args = SimpleNamespace(
            alignment_payload_json=self.alignment_payload_json,
            alignment_payload=None,
            use_mock_alignment=self.alignment_use_mock,
            target_title=self.target_title,
            yolo_conf=self.yolo_conf,
            use_ocr_title_match=self.use_ocr_title_match,
            book_index=None if self.book_index < 0 else self.book_index,
            lock_book_index=None if self.lock_book_index < 0 else self.lock_book_index,
            allow_fallback_lock=self.allow_fallback_lock,
            width=self.scan_width,
            height=self.scan_height,
            fps=self.scan_fps,
            no_display=self.no_display,
            disable_ocr=self.disable_ocr,
            no_save_ocr_debug_crops=self.no_save_ocr_debug_crops,
            ocr_target_long_side=self.ocr_target_long_side,
            ocr_crop_padding=self.ocr_crop_padding,
            disable_ocr_multi_input=self.disable_ocr_multi_input,
            ocr_include_upright_rotations=self.ocr_include_upright_rotations,
            ocr_max_variants_per_book=self.ocr_max_variants_per_book,
            ocr_max_books=self.ocr_max_books,
            ocr_early_stop_on_match=self.ocr_early_stop_on_match,
            ocr_early_stop_reasons=self.ocr_early_stop_reasons,
            ocr_early_stop_on_partial=self.ocr_early_stop_on_partial,
            move_line_service=self.scan_move_line_service,
            scan_move_vel_linear=self.scan_move_vel_linear,
            scan_move_vel_angular=self.scan_move_vel_angular,
            scan_move_acc_linear=self.scan_move_acc_linear,
            scan_move_acc_angular=self.scan_move_acc_angular,
            scan_move_settle_sec=self.scan_move_settle_sec,
            scan_move_timeout_sec=self.scan_move_timeout_sec,
            skip_scan_move=self.skip_scan_move,
            require_depth_for_scan=self.require_depth_for_scan,
        )

        if len(self.home_joint_pose_deg) != 6:
            raise ValueError("home_joint_pose_deg must contain exactly 6 joint values")
        if len(self.place_joint_pose_deg) != 6:
            raise ValueError("place_joint_pose_deg must contain exactly 6 joint values")
        if self.book_pre_approach_axis not in ("x", "y", "z"):
            raise ValueError("book_pre_approach_axis must be one of x, y, z")
        if self.book_lateral_axis not in ("x", "y", "z"):
            raise ValueError("book_lateral_axis must be one of x, y, z")
        if self.book_left_shift_axis not in ("x", "y", "z"):
            raise ValueError("book_left_shift_axis must be one of x, y, z")

    def log_info(self, message):
        logger = self.get_logger()
        if hasattr(logger, "info"):
            logger.info(message)
        else:
            logger.warn(message)

    def serialize_gripper_state(self, state):
        if state is None:
            return None
        return {
            "ready": bool(getattr(state, "ready", False)),
            "torque_enabled": bool(getattr(state, "torque_enabled", False)),
            "moving": bool(getattr(state, "moving", False)),
            "in_position": bool(getattr(state, "in_position", False)),
            "present_position": int(getattr(state, "present_position", 0)),
            "goal_position": int(getattr(state, "goal_position", 0)),
            "present_current": int(getattr(state, "present_current", 0)),
            "status_text": str(getattr(state, "status_text", "")),
        }

    def current_gripper_state_snapshot(self):
        return self.serialize_gripper_state(self.last_gripper_state)

    def record_stage(self, stage_name: str, **kwargs):
        self.result.setdefault("pick_stage_results", {})
        self.result["pick_stage_results"][stage_name] = scan.sanitize_for_json(kwargs)

    def call_service(self, client, service_name, request, label, timeout_sec=None):
        if not client.wait_for_service(timeout_sec=1.0):
            self.get_logger().error(f"Service not available: {service_name}")
            return False

        timeout_sec = (
            float(self.service_call_timeout_sec)
            if timeout_sec is None
            else float(timeout_sec)
        )
        future = client.call_async(request)
        start_time = time.monotonic()
        while rclpy.ok() and not future.done():
            if time.monotonic() - start_time > timeout_sec:
                self.get_logger().error(f"{label} timed out after {timeout_sec:.1f} seconds")
                return False
            rclpy.spin_once(self, timeout_sec=0.05)

        if future.result() is None:
            self.get_logger().error(f"{label} failed: {future.exception()}")
            return False

        response = future.result()
        if bool(getattr(response, "success", False)):
            return True

        detail = []
        for attr in ("message", "msg", "error", "ext_result"):
            if hasattr(response, attr):
                value = getattr(response, attr)
                if value not in (None, "", [], (), {}):
                    detail.append(f"{attr}={value}")
        if detail:
            self.get_logger().error(f"{label} returned success=false ({', '.join(detail)})")
        else:
            self.get_logger().error(f"{label} returned success=false")
        return False

    def fill_moveline_common(self, request):
        request.time = 0.0
        request.radius = 0.0
        request.ref = 1
        request.mode = 1
        request.blend_type = 0
        request.sync_type = 0

    def trace_state(self, state, status="ok", **details):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "state": state,
            "status": status,
        }
        if details:
            entry["details"] = scan.sanitize_for_json(details)
        self.trace.append(entry)
        self.result["state"] = state
        self.result["state_status"] = status
        self.save_state_trace()

    def save_state_trace(self):
        os.makedirs(os.path.dirname(self.state_trace_json) or ".", exist_ok=True)
        with open(self.state_trace_json, "w", encoding="utf-8") as stream:
            json.dump(scan.sanitize_for_json(self.result), stream, ensure_ascii=False, indent=2)

    def save_final_result(self):
        os.makedirs(os.path.dirname(self.result_json) or ".", exist_ok=True)
        with open(self.result_json, "w", encoding="utf-8") as stream:
            json.dump(scan.sanitize_for_json(self.result), stream, ensure_ascii=False, indent=2)

    def abort(self, reason, **details):
        self.result["status"] = "aborted"
        self.result["abort_reason"] = reason
        if details:
            self.result["abort_details"] = scan.sanitize_for_json(details)
        self.trace_state("ABORT", "failed", reason=reason, **details)
        self.save_final_result()
        return False

    def pause_between_states(self, next_state):
        if self.auto_run:
            return True
        if not sys.stdin.isatty():
            return True
        try:
            response = input(f"[{next_state}] press Enter to continue, q to abort > ").strip().lower()
        except EOFError:
            return True
        return response != "q"

    def move_home(self):
        request = MoveJoint.Request()
        request.pos = list(self.home_joint_pose_deg)
        request.vel = float(self.move_home_vel_deg)
        request.acc = float(self.move_home_acc_deg)
        request.time = 0.0
        request.radius = 0.0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 0
        if self.dry_run:
            return True
        return self.call_service(
            self.move_joint_client,
            self.move_joint_service,
            request,
            "MoveJoint[MOVE_HOME]",
        )

    def move_place_pose(self):
        request = MoveJoint.Request()
        request.pos = list(self.place_joint_pose_deg)
        request.vel = float(self.move_place_vel_deg)
        request.acc = float(self.move_place_acc_deg)
        request.time = 0.0
        request.radius = 0.0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 0
        if self.dry_run:
            return True
        return self.call_service(
            self.move_joint_client,
            self.move_joint_service,
            request,
            "MoveJoint[MOVE_TO_PLACE_POSE]",
        )

    def get_current_posx(self):
        if self.dry_run:
            return None
        if not self.current_posx_client.wait_for_service(timeout_sec=1.0):
            return None

        request = GetCurrentPosx.Request()
        request.ref = self.current_posx_ref
        future = self.current_posx_client.call_async(request)
        start_time = time.monotonic()
        while rclpy.ok() and not future.done():
            if time.monotonic() - start_time > self.current_posx_timeout_sec:
                return None
            rclpy.spin_once(self, timeout_sec=0.05)

        response = future.result()
        if response is None or not bool(getattr(response, "success", False)):
            return None
        if not getattr(response, "task_pos_info", None):
            return None

        current = list(response.task_pos_info[0].data[:6])
        if len(current) != 6:
            return None
        if not all(map(lambda value: float(value) == float(value), current)):
            return None
        return [float(value) for value in current]

    def move_home_return(self):
        return self.move_home()

    def prepare_gripper_view(self):
        if not self.prepare_gripper_for_view:
            self.result["gripper_view_result"] = {
                "enabled": False,
                "reason": "prepare_gripper_for_view=false",
            }
            return True
        if not self.enable_gripper_control and not self.dry_run:
            return self.abort("gripper_control_disabled")
        if not self.pick_executor.torque_on():
            return False
        if not self.pick_executor.set_gripper_position(
            self.gripper_view_position,
            "PREPARE_GRIPPER_VIEW",
        ):
            return False
        self.result["gripper_view_result"] = {
            "enabled": True,
            "gripper_view_position": int(self.gripper_view_position),
            "dry_run": bool(self.dry_run),
        }
        return True

    def prepare_gripper_pick_open(self):
        if not self.prepare_gripper_for_pick_open:
            self.result["gripper_pick_open_result"] = {
                "enabled": False,
                "reason": "prepare_gripper_for_pick_open=false",
            }
            return True
        if not self.enable_gripper_control and not self.dry_run:
            return self.abort("gripper_control_disabled")
        if not self.pick_executor.torque_on():
            return False
        if not self.pick_executor.set_gripper_position(
            self.gripper_open_position,
            "PREPARE_GRIPPER_PICK_OPEN",
        ):
            return False
        self.result["gripper_pick_open_result"] = {
            "enabled": True,
            "gripper_open_position": int(self.gripper_open_position),
            "dry_run": bool(self.dry_run),
        }
        return True

    def run_alignment_stage(self):
        if self.alignment_use_mock:
            payload = scan.get_mock_alignment_payload()
            self.result["alignment_payload"] = payload
            os.makedirs(os.path.dirname(self.alignment_payload_json) or ".", exist_ok=True)
            with open(self.alignment_payload_json, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
            return True

        command = [
            "ros2",
            "run",
            "doosan_realsense_handeye",
            "aruco_marker_proto_align",
            "--ros-args",
            "-p",
            f"dry_run:={'true' if self.alignment_dry_run else 'false'}",
            "-p",
            f"auto_run:={'true' if self.alignment_auto_run else 'false'}",
            "-p",
            f"alignment_payload_json:={self.alignment_payload_json}",
            "-p",
            f"target_marker_id:={int(self.alignment_target_marker_id)}",
            "-p",
            f"run_post_alignment_pipeline:={'true' if self.alignment_run_post_pipeline else 'false'}",
            "-p",
            f"post_alignment_no_display:={'true' if self.alignment_post_alignment_no_display else 'false'}",
            "-p",
            "enable_initial_translation_jump:="
            f"{'true' if self.alignment_enable_initial_translation_jump else 'false'}",
            "-p",
            "initial_translation_jump_axis_mode:="
            f"{self.alignment_initial_translation_jump_axis_mode}",
            "-p",
            "initial_translation_jump_scale:="
            f"{self.alignment_initial_translation_jump_scale}",
            "-p",
            "initial_translation_jump_max_mm:="
            f"{self.alignment_initial_translation_jump_max_mm}",
        ]
        if self.alignment_auto_run:
            command.extend(["-p", "auto_max_steps:=300"])

        baseline_mtime = 0.0
        payload_path = Path(self.alignment_payload_json)
        if payload_path.exists():
            baseline_mtime = float(payload_path.stat().st_mtime)

        self.log_info("[ALIGN_MARKER] launching alignment subprocess")
        self.log_info("  " + " ".join(command))
        try:
            subprocess.run(command, check=True, timeout=self.alignment_timeout_sec)
        except subprocess.TimeoutExpired:
            return self.abort("alignment_timeout")
        except subprocess.CalledProcessError as exc:
            return self.abort("alignment_failed", returncode=exc.returncode)

        if not payload_path.exists() or float(payload_path.stat().st_mtime) <= baseline_mtime:
            return self.abort("alignment_payload_missing")

        payload = scan.load_alignment_payload(
            SimpleNamespace(
                use_mock_alignment=False,
                alignment_payload_json=self.alignment_payload_json,
                alignment_payload=None,
            )
        )
        ok, error = scan.validate_alignment_payload(payload)
        if not ok:
            return self.abort("alignment_payload_invalid", error=error)

        self.result["alignment_payload"] = payload
        return True

    def run_book_scan_stage(self):
        if not vision.rclpy.ok():
            vision.rclpy.init(args=None)

        robot_node = self.vision_node
        reader = None

        try:
            marker_pub = robot_node.create_publisher(MarkerArray, scan.BOOK_SCAN_MARKER_TOPIC, 10)

            alignment_payload = self.result.get("alignment_payload")
            if alignment_payload is None:
                alignment_payload = scan.load_alignment_payload(
                    SimpleNamespace(
                        use_mock_alignment=False,
                        alignment_payload_json=self.alignment_payload_json,
                        alignment_payload=None,
                    )
                )
                ok, error = scan.validate_alignment_payload(alignment_payload)
                if not ok:
                    return self.abort("alignment_payload_invalid", error=error)
                self.result["alignment_payload"] = alignment_payload

            book_scan_pose = scan.compute_book_scan_pose(alignment_payload)
            self.result["book_scan_pose"] = book_scan_pose

            if not self.skip_scan_move:
                scan.move_robot_to_book_scan_pose(
                    robot_node,
                    book_scan_pose,
                    self.scan_move_line_service,
                    self.scan_move_vel_linear,
                    self.scan_move_vel_angular,
                    self.scan_move_acc_linear,
                    self.scan_move_acc_angular,
                    self.scan_move_timeout_sec,
                )
                if self.scan_move_settle_sec > 0.0:
                    time.sleep(float(self.scan_move_settle_sec))

            yolo_model = vision.YOLO(vision.MODEL_PATH)
            ocr = None
            if not self.disable_ocr:
                ocr = vision.PaddleOCR(
                    lang="korean",
                    use_textline_orientation=True,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    enable_mkldnn=False,
                )

            reader, _, color_intrinsics = vision.init_realsense(
                width=self.scan_width,
                height=self.scan_height,
                fps=self.scan_fps,
            )

            frame = None
            depth_frame = None
            for _ in range(10):
                vision.rclpy.spin_once(reader, timeout_sec=0.0)
                frame, depth_frame, _ = vision.get_realsense_frames(reader, None)
                if frame is not None and (
                    depth_frame is not None or not self.require_depth_for_scan
                ):
                    break
                time.sleep(0.05)
            if frame is None:
                return self.abort("capture_failed")
            if self.require_depth_for_scan and depth_frame is None:
                return self.abort(
                    "depth_capture_failed",
                    detail="Mission scan requires depth to compute base-frame book targets.",
                )
            if depth_frame is None:
                return self.abort(
                    "depth_required_for_book_target",
                    detail="RGB frame arrived, but depth is required before book approach.",
                )

            obb_data = scan.detect_books(
                yolo_model,
                frame,
                depth_frame,
                color_intrinsics,
                yolo_conf=self.yolo_conf,
            )
            if not obb_data:
                return self.abort("book_not_found")

            books, ocr_build_debug = scan.build_book_scan_entries(
                robot_node,
                frame.copy(),
                depth_frame,
                color_intrinsics,
                ocr,
                obb_data,
                self.scan_args,
            )
            selected_book_candidate = scan.select_target_book_candidate(
                books,
                self.target_title,
                override_book_index=self.book_index if self.book_index >= 0 else None,
                lock_book_index=self.lock_book_index if self.lock_book_index >= 0 else None,
                use_ocr_title_match=self.use_ocr_title_match,
            )
            if selected_book_candidate is None and getattr(
                self, "_allow_vision_only_selection", False
            ):
                selected_book_candidate = self.select_target_book_candidate_vision_only(books)
            if selected_book_candidate is not None:
                scan.save_target_book_lock(
                    books,
                    selected_book_candidate,
                    self.target_title,
                    allow_fallback_lock=self.allow_fallback_lock,
                )

            scan_result = {
                "timestamp": datetime.now().isoformat(),
                "mode": "book_mission_state_machine_scan",
                "target_title": self.target_title,
                "yolo_conf": float(self.yolo_conf),
                "states": scan.SCAN_STATES,
                "state_history": [
                    {"state": "DETECT_BOOK", "timestamp": datetime.now().isoformat()},
                    {"state": "COMPUTE_BOOK_LOCATIONS", "timestamp": datetime.now().isoformat()},
                    {"state": "SELECT_TARGET_BOOK_OPTIONAL", "timestamp": datetime.now().isoformat()},
                ],
                "alignment_payload": alignment_payload,
                "book_scan_pose": book_scan_pose,
                "books": books,
                "selected_book_candidate": selected_book_candidate,
                "ocr_early_stop_debug": ocr_build_debug,
                "status": "book_scan_done" if selected_book_candidate is not None else "no_valid_book_pose",
            }
            scan.save_book_scan_result(scan_result)
            scan.publish_book_scan_markers(
                robot_node,
                marker_pub,
                books,
                selected_book_candidate,
                book_scan_pose,
            )
            self.result["book_scan_result"] = scan_result
            self.result["selected_book_candidate"] = selected_book_candidate
            if selected_book_candidate is None:
                return self.abort("no_valid_book_pose")

            if not self.no_display:
                vis = scan.draw_scan_overlay(
                    frame,
                    obb_data,
                    selected_book_candidate,
                    self.target_title,
                    scan_result["status"],
                )
                cv2.imshow("Bookshelf Book Scan", vis)
                cv2.waitKey(1)
        except Exception as exc:
            return self.abort(
                "book_scan_exception",
                exception_type=type(exc).__name__,
                message=str(exc),
            )
        finally:
            if reader is not None:
                reader.destroy_node()

        return True

    def select_target_book_candidate_vision_only(self, books):
        if not books:
            return None

        manual_index = None
        manual_reason = None
        if self.book_index >= 0:
            manual_index = int(self.book_index)
            manual_reason = "manual_book_index"
        elif self.lock_book_index >= 0:
            manual_index = int(self.lock_book_index)
            manual_reason = "manual_lock_book_index"

        if manual_index is not None:
            for book in books:
                if int(book.get("book_index", -1)) == manual_index:
                    return {
                        "reason": manual_reason,
                        "book_index": int(book["book_index"]),
                        "matched_text": None,
                        "target_title": self.target_title,
                        "confidence": round(float(book.get("confidence", 0.0)), 3),
                        "selection_source": f"{manual_reason}_vision_only",
                    }

        candidate_pool = []
        if self.target_title and self.use_ocr_title_match:
            for book in books:
                for candidate in book.get("title_candidates", []):
                    reason = str(candidate.get("match_reason_candidate") or "none")
                    priority = scan.get_match_priority(reason)
                    if priority >= scan.get_match_priority("fallback_highest_confidence"):
                        continue
                    if not scan.candidate_text_is_useful(candidate):
                        continue
                    candidate_pool.append((
                        priority,
                        -float(candidate.get("adjusted_score", candidate.get("score", 0.0))),
                        -float(book.get("confidence", 0.0)),
                        -int(book.get("book_index", 0)),
                        book,
                        candidate,
                    ))

        if candidate_pool:
            candidate_pool.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
            _priority, _score, _conf, _index, book, candidate = candidate_pool[0]
            return {
                "reason": candidate.get("match_reason_candidate"),
                "book_index": int(book["book_index"]),
                "matched_text": candidate.get("text"),
                "target_title": self.target_title,
                "confidence": round(float(book.get("confidence", 0.0)), 3),
                "ocr_score": candidate.get("score"),
                "ocr_adjusted_score": candidate.get("adjusted_score"),
                "ocr_match_reason": candidate.get("match_reason_candidate"),
                "ocr_source": candidate.get("ocr_source"),
                "selection_source": "ocr_title_match_vision_only",
            }

        highest_conf_book = max(books, key=lambda item: float(item.get("confidence", 0.0)))
        return {
            "reason": "fallback_highest_confidence",
            "book_index": int(highest_conf_book["book_index"]),
            "matched_text": None,
            "target_title": self.target_title,
            "confidence": round(float(highest_conf_book.get("confidence", 0.0)), 3),
            "selection_source": "fallback_highest_confidence_vision_only",
        }

    def selected_book_from_latest_scan(self):
        selected = self.result.get("selected_book_candidate")
        books = (self.result.get("book_scan_result") or {}).get("books") or []
        selected_book = scan.find_book_by_candidate(books, selected)
        if selected_book is None:
            return None
        return selected_book

    def selected_book_camera_mid_depth_m(self, selected_book):
        camera_xyz = (selected_book or {}).get("camera_xyz_m") or {}
        mid_xyz = camera_xyz.get("mid")
        if not scan.is_finite_vector(mid_xyz, 3):
            return None
        depth_m = float(mid_xyz[2])
        if depth_m <= 0.0:
            return None
        return depth_m

    def selected_book_pixel_mid_x(self, selected_book):
        pixels = (selected_book or {}).get("pixels") or {}
        mid_px = pixels.get("mid") or pixels.get("center")
        if not scan.is_finite_vector(mid_px, 2):
            return None
        return float(mid_px[0])

    def move_relative_tool_axis_mm(self, axis, signed_mm, label):
        axis = str(axis).lower()
        if axis not in ("x", "y", "z"):
            return False, {
                "status": "invalid_axis",
                "axis": axis,
                "signed_mm": float(signed_mm),
            }

        axis_to_index = {"x": 0, "y": 1, "z": 2}
        pos = [0.0] * 6
        pos[axis_to_index[axis]] = float(signed_mm)

        request = MoveLine.Request()
        request.pos = pos
        request.vel = [
            float(self.book_pre_approach_vel_linear),
            float(self.book_pre_approach_vel_angular),
        ]
        request.acc = [
            float(self.book_pre_approach_acc_linear),
            float(self.book_pre_approach_acc_angular),
        ]
        self.fill_moveline_common(request)

        result = {
            "status": "dry_run" if self.dry_run else "requested",
            "axis": axis,
            "signed_mm": float(signed_mm),
            "request_pos_mm_deg": list(pos),
            "ref": int(request.ref),
            "mode": int(request.mode),
        }
        self.log_info(
            f"[{label}] tool {axis} relative move {float(signed_mm):.1f}mm"
        )

        if self.dry_run:
            return True, result

        ok = self.call_service(
            self.move_line_client,
            self.move_line_service,
            request,
            f"MoveLine[{label}]",
        )
        result["status"] = "moved" if ok else "move_failed"
        if ok and self.book_lateral_settle_sec > 0.0:
            time.sleep(float(self.book_lateral_settle_sec))
        return ok, result

    def move_relative_for_book_distance(
        self,
        selected_book,
        target_distance_m,
        max_step_m,
        label,
        tolerance_m=0.0,
    ):
        depth_m = self.selected_book_camera_mid_depth_m(selected_book)
        if depth_m is None:
            return False, {
                "status": "invalid_book_depth",
                "selected_book": scan.sanitize_for_json(selected_book),
            }

        remaining_m = float(depth_m) - float(target_distance_m)
        if remaining_m <= float(tolerance_m):
            return True, {
                "status": "already_within_target_distance",
                "depth_m": float(depth_m),
                "target_distance_m": float(target_distance_m),
                "tolerance_m": float(tolerance_m),
                "move_m": 0.0,
            }

        move_m = min(float(remaining_m), max(0.0, float(max_step_m)))
        move_mm = float(move_m) * 1000.0
        axis_to_index = {"x": 0, "y": 1, "z": 2}
        pos = [0.0] * 6
        pos[axis_to_index[self.book_pre_approach_axis]] = (
            self.book_pre_approach_axis_sign * move_mm
        )

        request = MoveLine.Request()
        request.pos = pos
        request.vel = [
            float(self.book_pre_approach_vel_linear),
            float(self.book_pre_approach_vel_angular),
        ]
        request.acc = [
            float(self.book_pre_approach_acc_linear),
            float(self.book_pre_approach_acc_angular),
        ]
        self.fill_moveline_common(request)

        result = {
            "status": "dry_run" if self.dry_run else "requested",
            "depth_m": float(depth_m),
            "target_distance_m": float(target_distance_m),
            "tolerance_m": float(tolerance_m),
            "remaining_m": float(remaining_m),
            "move_m": float(move_m),
            "max_step_m": float(max_step_m),
            "axis": self.book_pre_approach_axis,
            "axis_sign": float(self.book_pre_approach_axis_sign),
            "request_pos_mm_deg": list(pos),
            "selected_book": scan.sanitize_for_json(selected_book),
        }
        self.log_info(
            f"[{label}] depth={depth_m:.3f}m target={target_distance_m:.3f}m "
            f"move={move_m:.3f}m axis={self.book_pre_approach_axis} "
            f"sign={self.book_pre_approach_axis_sign:.1f}"
        )

        if self.dry_run:
            return True, result

        ok = self.call_service(
            self.move_line_client,
            self.move_line_service,
            request,
            f"MoveLine[{label}]",
        )
        result["status"] = "moved" if ok else "move_failed"
        if ok and self.book_pre_approach_settle_sec > 0.0:
            time.sleep(float(self.book_pre_approach_settle_sec))
        return ok, result

    def run_current_pose_book_scan_stage(self):
        old_skip_scan_move = self.skip_scan_move
        old_scan_args_skip_scan_move = self.scan_args.skip_scan_move
        old_allow_vision_only_selection = getattr(
            self,
            "_allow_vision_only_selection",
            False,
        )
        self.skip_scan_move = True
        self.scan_args.skip_scan_move = True
        self._allow_vision_only_selection = True
        try:
            return self.run_book_scan_stage()
        finally:
            self.skip_scan_move = old_skip_scan_move
            self.scan_args.skip_scan_move = old_scan_args_skip_scan_move
            self._allow_vision_only_selection = old_allow_vision_only_selection

    def run_book_pre_approach_stage(self):
        selected_book = self.selected_book_from_latest_scan()
        if selected_book is None:
            return self.abort("selected_book_not_found")

        ok, result = self.move_relative_for_book_distance(
            selected_book,
            self.book_pre_approach_target_distance_m,
            self.book_pre_approach_max_step_m,
            "MOVE_TO_BOOK_20CM_OFFSET",
        )
        self.result["book_pre_approach_result"] = result
        return ok

    def run_book_pre_verify_lower_stage(self):
        if not self.book_pre_verify_lower_enabled:
            self.result["book_pre_verify_lower_result"] = {
                "enabled": False,
                "reason": "book_pre_verify_lower_enabled=false",
            }
            return True

        lower_mm = abs(float(self.book_pre_verify_lower_z_mm))
        request = MoveLine.Request()
        # Base-frame relative Z down. Keep rotation unchanged.
        request.pos = [0.0, 0.0, -lower_mm, 0.0, 0.0, 0.0]
        request.vel = [
            float(self.book_pre_approach_vel_linear),
            float(self.book_pre_approach_vel_angular),
        ]
        request.acc = [
            float(self.book_pre_approach_acc_linear),
            float(self.book_pre_approach_acc_angular),
        ]
        request.time = 0.0
        request.radius = 0.0
        request.ref = 0
        request.mode = 1
        request.blend_type = 0
        request.sync_type = 0

        result = {
            "enabled": True,
            "status": "dry_run" if self.dry_run else "requested",
            "lower_z_mm": lower_mm,
            "ref": int(request.ref),
            "mode": int(request.mode),
            "request_pos_mm_deg": list(request.pos),
        }
        self.log_info(
            f"[LOWER_CAMERA_FOR_VERIFY] base Z down {lower_mm:.1f}mm before second OCR"
        )

        if self.dry_run:
            self.result["book_pre_verify_lower_result"] = result
            return True

        ok = self.call_service(
            self.move_line_client,
            self.move_line_service,
            request,
            "MoveLine[LOWER_CAMERA_FOR_VERIFY]",
        )
        result["status"] = "moved" if ok else "move_failed"
        if ok and self.book_pre_approach_settle_sec > 0.0:
            time.sleep(float(self.book_pre_approach_settle_sec))
        self.result["book_pre_verify_lower_result"] = result
        return ok

    def run_book_verify_again_stage(self):
        if not self.run_current_pose_book_scan_stage():
            return False
        self.result["verified_book_scan_result"] = self.result.get("book_scan_result")
        self.result["verified_selected_book_candidate"] = self.result.get(
            "selected_book_candidate"
        )
        return True

    def run_book_lateral_align_stage(self):
        if not self.book_lateral_align_enabled:
            self.result["book_lateral_align_result"] = {
                "enabled": False,
                "reason": "book_lateral_align_enabled=false",
            }
            return True

        steps = []
        max_steps = max(0, int(self.book_lateral_max_steps))
        tolerance_px = max(0.0, float(self.book_lateral_pixel_tolerance_px))
        target_pixel_x = float(self.book_lateral_target_pixel_x)
        if target_pixel_x < 0.0:
            target_pixel_x = float(self.scan_width) * 0.5
        max_step_mm = max(0.0, float(self.book_lateral_max_step_mm))
        gain_mm_per_px = max(0.0, float(self.book_lateral_pixel_gain_mm_per_px))

        for step_index in range(max_steps + 1):
            selected_book = self.selected_book_from_latest_scan()
            if selected_book is None:
                return self.abort("lateral_align_selected_book_not_found")
            pixel_x = self.selected_book_pixel_mid_x(selected_book)
            if pixel_x is None:
                return self.abort(
                    "lateral_align_book_pixel_x_invalid",
                    selected_book=scan.sanitize_for_json(selected_book),
                )

            error_px = float(pixel_x) - target_pixel_x
            step_info = {
                "step_index": int(step_index),
                "pixel_x": float(pixel_x),
                "target_pixel_x": float(target_pixel_x),
                "error_px": float(error_px),
                "tolerance_px": tolerance_px,
            }
            if abs(error_px) <= tolerance_px:
                step_info["status"] = "aligned"
                steps.append(step_info)
                self.result["book_lateral_align_result"] = {
                    "enabled": True,
                    "status": "aligned",
                    "steps": steps,
                }
                return True

            if step_index >= max_steps:
                step_info["status"] = "max_steps_reached"
                steps.append(step_info)
                self.result["book_lateral_align_result"] = {
                    "enabled": True,
                    "status": "max_steps_reached",
                    "steps": steps,
                }
                return True

            move_mm = min(abs(error_px) * gain_mm_per_px, max_step_mm)
            signed_mm = (
                self.book_lateral_axis_sign
                * (1.0 if error_px >= 0.0 else -1.0)
                * move_mm
            )
            ok, move_result = self.move_relative_tool_axis_mm(
                self.book_lateral_axis,
                signed_mm,
                "ALIGN_BOOK_LATERAL",
            )
            step_info["status"] = "moved" if ok else "move_failed"
            step_info["move_result"] = move_result
            steps.append(step_info)
            if not ok:
                self.result["book_lateral_align_result"] = {
                    "enabled": True,
                    "status": "move_failed",
                    "steps": steps,
                }
                return False

            if self.dry_run:
                self.result["book_lateral_align_result"] = {
                    "enabled": True,
                    "status": "dry_run_planned",
                    "steps": steps,
                }
                return True

            if not self.run_current_pose_book_scan_stage():
                self.result["book_lateral_align_result"] = {
                    "enabled": True,
                    "status": "rescan_failed",
                    "steps": steps,
                }
                return False

        self.result["book_lateral_align_result"] = {
            "enabled": True,
            "status": "unexpected_loop_exit",
            "steps": steps,
        }
        return True

    def run_book_left_shift_stage(self):
        if not self.book_left_shift_enabled:
            self.result["book_left_shift_result"] = {
                "enabled": False,
                "reason": "book_left_shift_enabled=false",
            }
            return True

        signed_mm = (
            float(self.book_left_shift_axis_sign)
            * abs(float(self.book_left_shift_mm))
        )
        ok, result = self.move_relative_tool_axis_mm(
            self.book_left_shift_axis,
            signed_mm,
            "MOVE_LEFT_1CM",
        )
        result["enabled"] = True
        result["left_shift_mm"] = abs(float(self.book_left_shift_mm))
        result["axis_sign"] = float(self.book_left_shift_axis_sign)
        self.result["book_left_shift_result"] = result
        return ok

    def run_gripper_after_lateral_stage(self):
        if not self.gripper_after_lateral_enabled:
            self.result["gripper_after_lateral_result"] = {
                "enabled": False,
                "reason": "gripper_after_lateral_enabled=false",
            }
            return True
        if not self.enable_gripper_control and not self.dry_run:
            return self.abort("gripper_control_disabled")
        if not self.pick_executor.torque_on():
            return False
        if not self.pick_executor.set_gripper_position(
            self.gripper_after_lateral_position,
            "SET_GRIPPER_600_AFTER_ALIGN",
        ):
            return False
        self.result["gripper_after_lateral_result"] = {
            "enabled": True,
            "gripper_position": int(self.gripper_after_lateral_position),
            "dry_run": bool(self.dry_run),
        }
        return True

    def run_experimental_pick_cycles_stage(self):
        if not self.experimental_pick_cycles_enabled:
            self.result["experimental_pick_cycles_result"] = {
                "enabled": False,
                "reason": "experimental_pick_cycles_enabled=false",
            }
            return True
        if not self.enable_gripper_control and not self.dry_run:
            return self.abort("gripper_control_disabled")

        cycle_count = max(0, int(self.experimental_pick_cycle_count))
        cycle_distance_mm = abs(float(self.experimental_pick_cycle_distance_mm))
        pre_approach_mm = abs(float(self.experimental_pick_pre_approach_mm))
        open_position = int(self.experimental_pick_open_position)
        soft_grip_position = int(self.experimental_pick_soft_grip_position)
        final_grip_position = int(self.experimental_pick_final_grip_position)
        final_pull_mm = abs(float(self.experimental_pick_final_pull_mm))
        stages = []

        if not self.pick_executor.check_gripper_ready():
            return False
        if not self.pick_executor.torque_on():
            return False

        if pre_approach_mm > 0.0:
            label = "EXPERIMENTAL_PICK_PRE_APPROACH_13CM"
            if not self.pick_executor.move_relative_axis(pre_approach_mm, label):
                return False
            stages.append({
                "stage": label,
                "move_mm": pre_approach_mm,
            })

        for index in range(cycle_count):
            cycle_no = index + 1
            grip_label = f"EXPERIMENTAL_PICK_{cycle_no}_SOFT_GRIP"
            pull_label = f"EXPERIMENTAL_PICK_{cycle_no}_PULL"
            open_label = f"EXPERIMENTAL_PICK_{cycle_no}_OPEN"
            push_label = f"EXPERIMENTAL_PICK_{cycle_no}_PUSH"

            if not self.pick_executor.set_gripper_position(
                soft_grip_position,
                grip_label,
            ):
                return False
            stages.append({
                "stage": grip_label,
                "gripper_position": soft_grip_position,
            })

            if not self.pick_executor.move_relative_axis(-cycle_distance_mm, pull_label):
                return False
            stages.append({
                "stage": pull_label,
                "move_mm": -cycle_distance_mm,
            })

            if not self.pick_executor.set_gripper_position(open_position, open_label):
                return False
            stages.append({
                "stage": open_label,
                "gripper_position": open_position,
            })

            if not self.pick_executor.move_relative_axis(cycle_distance_mm, push_label):
                return False
            stages.append({
                "stage": push_label,
                "move_mm": cycle_distance_mm,
            })

        if not self.pick_executor.set_gripper_position(
            final_grip_position,
            "EXPERIMENTAL_PICK_FINAL_GRIP",
        ):
            return False
        stages.append({
            "stage": "EXPERIMENTAL_PICK_FINAL_GRIP",
            "gripper_position": final_grip_position,
        })

        if final_pull_mm > 0.0:
            if not self.pick_executor.move_relative_axis(
                -final_pull_mm,
                "EXPERIMENTAL_PICK_FINAL_PULL",
            ):
                return False
            stages.append({
                "stage": "EXPERIMENTAL_PICK_FINAL_PULL",
                "move_mm": -final_pull_mm,
            })

        self.result["experimental_pick_cycles_result"] = {
            "enabled": True,
            "cycle_count": cycle_count,
            "cycle_distance_mm": cycle_distance_mm,
            "pre_approach_mm": pre_approach_mm,
            "open_position": open_position,
            "soft_grip_position": soft_grip_position,
            "final_grip_position": final_grip_position,
            "final_pull_mm": final_pull_mm,
            "stages": scan.sanitize_for_json(stages),
            "pick_executor_result": scan.sanitize_for_json(self.pick_executor.result),
            "dry_run": bool(self.dry_run),
        }
        return True

    def run_marker2_alignment_stage(self):
        if not self.marker2_alignment_enabled:
            self.result["marker2_alignment_result"] = {
                "enabled": False,
                "reason": "marker2_alignment_enabled=false",
            }
            return True

        command = [
            "ros2",
            "run",
            "doosan_realsense_handeye",
            "aruco_marker2_proto_align",
            "--ros-args",
            "-p",
            f"dry_run:={'true' if self.marker2_alignment_dry_run else 'false'}",
            "-p",
            f"auto_run:={'true' if self.marker2_alignment_auto_run else 'false'}",
            "-p",
            f"alignment_payload_json:={self.marker2_alignment_payload_json}",
            "-p",
            "run_post_alignment_pipeline:=false",
            "-p",
            f"target_distance_m:={self.marker2_alignment_target_distance_m}",
            "-p",
            "enable_initial_translation_jump:="
            f"{'true' if self.marker2_alignment_enable_initial_translation_jump else 'false'}",
            "-p",
            "initial_translation_jump_axis_mode:="
            f"{self.marker2_alignment_initial_translation_jump_axis_mode}",
            "-p",
            "initial_translation_jump_scale:="
            f"{self.marker2_alignment_initial_translation_jump_scale}",
            "-p",
            "initial_translation_jump_max_mm:="
            f"{self.marker2_alignment_initial_translation_jump_max_mm}",
        ]
        if self.marker2_alignment_auto_run:
            command.extend(["-p", "auto_max_steps:=300"])

        payload_path = Path(self.marker2_alignment_payload_json)
        baseline_mtime = 0.0
        if payload_path.exists():
            baseline_mtime = float(payload_path.stat().st_mtime)

        self.log_info("[ALIGN_MARKER2_AFTER_TEMP_PLACE] launching marker2 alignment subprocess")
        self.log_info("  " + " ".join(command))
        try:
            subprocess.run(command, check=True, timeout=self.marker2_alignment_timeout_sec)
        except subprocess.TimeoutExpired:
            return self.abort("marker2_alignment_timeout")
        except subprocess.CalledProcessError as exc:
            return self.abort("marker2_alignment_failed", returncode=exc.returncode)

        if self.marker2_alignment_dry_run:
            self.result["marker2_alignment_result"] = {
                "enabled": True,
                "dry_run": True,
                "command": command,
                "status": "dry_run_completed",
            }
            return True

        if not payload_path.exists() or float(payload_path.stat().st_mtime) <= baseline_mtime:
            return self.abort("marker2_alignment_payload_missing")

        payload = scan.load_alignment_payload(
            SimpleNamespace(
                use_mock_alignment=False,
                alignment_payload_json=self.marker2_alignment_payload_json,
                alignment_payload=None,
            )
        )
        ok, error = scan.validate_alignment_payload(payload)
        if not ok:
            return self.abort("marker2_alignment_payload_invalid", error=error)

        marker_id = payload.get("target_marker_id", payload.get("marker_id"))
        if marker_id is not None and int(marker_id) != 2:
            return self.abort("marker2_alignment_wrong_marker_id", marker_id=marker_id)

        self.result["marker2_alignment_payload"] = payload
        self.result["marker2_alignment_result"] = {
            "enabled": True,
            "dry_run": False,
            "command": command,
            "status": "payload_saved",
            "payload_json": self.marker2_alignment_payload_json,
            "aligned_tcp_pose": payload.get("aligned_tcp_pose"),
        }
        return True

    def run_place_lower_before_release_stage(self):
        lower_mm = abs(float(self.place_lower_before_release_mm))
        if lower_mm <= 0.0:
            self.result["place_lower_result"] = {
                "enabled": False,
                "reason": "place_lower_before_release_mm<=0",
            }
            return True

        ok, result = self.move_relative_tool_axis_mm(
            "z",
            lower_mm,
            "LOWER_TO_PLACE_BOOK_Z_PLUS",
        )
        result["enabled"] = True
        result["lower_mm"] = lower_mm
        self.result["place_lower_result"] = result
        return ok

    def run_regrip_temp_book_stage(self):
        if not self.regrip_after_marker2_alignment:
            self.result["regrip_temp_book_result"] = {
                "enabled": False,
                "reason": "regrip_after_marker2_alignment=false",
            }
            return True
        if not self.enable_gripper_control and not self.dry_run:
            return self.abort("gripper_control_disabled")

        stages = []
        down_mm = abs(float(self.regrip_down_mm))

        if self.regrip_move_to_place_pose_first:
            if not self.move_place_pose():
                return False
            stages.append({
                "stage": "MOVE_TO_TEMP_PLACE_POSE_FOR_REGRIP",
                "joint_pose_deg": list(self.place_joint_pose_deg),
            })

        if not self.pick_executor.check_gripper_ready():
            return False
        if not self.pick_executor.torque_on():
            return False
        stages.append({"stage": "REGRIP_TORQUE_ON"})

        if not self.pick_executor.set_gripper_position(
            int(self.regrip_open_position),
            "REGRIP_OPEN_GRIPPER",
        ):
            return False
        stages.append({
            "stage": "REGRIP_OPEN_GRIPPER",
            "gripper_position": int(self.regrip_open_position),
        })

        if down_mm > 0.0:
            ok, result = self.move_relative_tool_axis_mm(
                "z",
                down_mm,
                "REGRIP_DESCEND_TO_TEMP_BOOK_Z_PLUS",
            )
            if not ok:
                self.result["regrip_temp_book_result"] = {
                    "enabled": True,
                    "status": "descend_failed",
                    "stages": scan.sanitize_for_json(stages),
                    "descend_result": scan.sanitize_for_json(result),
                }
                return False
            stages.append({
                "stage": "REGRIP_DESCEND_TO_TEMP_BOOK_Z_PLUS",
                "move_mm": down_mm,
                "move_result": scan.sanitize_for_json(result),
            })

        if not self.pick_executor.set_gripper_position(
            int(self.regrip_close_position),
            "REGRIP_CLOSE_GRIPPER_ON_TEMP_BOOK",
        ):
            return False
        stages.append({
            "stage": "REGRIP_CLOSE_GRIPPER_ON_TEMP_BOOK",
            "gripper_position": int(self.regrip_close_position),
        })

        if down_mm > 0.0:
            ok, result = self.move_relative_tool_axis_mm(
                "z",
                -down_mm,
                "REGRIP_LIFT_FROM_TEMP_BOOK_Z_MINUS",
            )
            if not ok:
                self.result["regrip_temp_book_result"] = {
                    "enabled": True,
                    "status": "lift_failed",
                    "stages": scan.sanitize_for_json(stages),
                    "lift_result": scan.sanitize_for_json(result),
                }
                return False
            stages.append({
                "stage": "REGRIP_LIFT_FROM_TEMP_BOOK_Z_MINUS",
                "move_mm": -down_mm,
                "move_result": scan.sanitize_for_json(result),
            })

        self.result["regrip_temp_book_result"] = {
            "enabled": True,
            "status": "regripped",
            "move_to_place_pose_first": bool(self.regrip_move_to_place_pose_first),
            "down_mm": down_mm,
            "open_position": int(self.regrip_open_position),
            "close_position": int(self.regrip_close_position),
            "stages": scan.sanitize_for_json(stages),
        }
        return True

    def move_to_marker2_aligned_pose(self):
        payload = self.result.get("marker2_alignment_payload") or {}
        pose = payload.get("aligned_tcp_pose")
        if not scan.is_finite_vector(pose, 6):
            return False, {
                "status": "missing_aligned_tcp_pose",
                "payload": scan.sanitize_for_json(payload),
            }

        request = MoveLine.Request()
        request.pos = [float(v) for v in pose]
        request.vel = [
            float(self.book_pre_approach_vel_linear),
            float(self.book_pre_approach_vel_angular),
        ]
        request.acc = [
            float(self.book_pre_approach_acc_linear),
            float(self.book_pre_approach_acc_angular),
        ]
        request.time = 0.0
        request.radius = 0.0
        request.ref = 0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 0

        result = {
            "status": "dry_run" if self.dry_run else "requested",
            "aligned_tcp_pose": list(request.pos),
            "ref": int(request.ref),
            "mode": int(request.mode),
        }
        self.log_info(
            "[MOVE_TO_MARKER2_ALIGNED_POSE] MoveLine absolute pose "
            f"[mm,deg]={request.pos}"
        )

        if self.dry_run:
            return True, result

        ok = self.call_service(
            self.move_line_client,
            self.move_line_service,
            request,
            "MoveLine[MOVE_TO_MARKER2_ALIGNED_POSE]",
        )
        result["status"] = "moved" if ok else "move_failed"
        if ok and self.book_lateral_settle_sec > 0.0:
            time.sleep(float(self.book_lateral_settle_sec))
        return ok, result

    def run_marker2_place_book_stage(self):
        if not self.marker2_place_after_regrip_enabled:
            self.result["marker2_place_result"] = {
                "enabled": False,
                "reason": "marker2_place_after_regrip_enabled=false",
            }
            return True
        if not self.enable_gripper_control and not self.dry_run:
            return self.abort("gripper_control_disabled")

        insert_z_mm = abs(float(self.marker2_place_insert_z_mm))
        drop_y_mm = float(self.marker2_place_drop_y_mm)

        stages = []
        ok, result = self.move_to_marker2_aligned_pose()
        stages.append({
            "stage": "MOVE_TO_MARKER2_ALIGNED_POSE",
            "move_result": scan.sanitize_for_json(result),
        })
        if not ok:
            self.result["marker2_place_result"] = {
                "enabled": True,
                "status": "move_to_marker2_pose_failed",
                "stages": scan.sanitize_for_json(stages),
            }
            return False

        # Lower first, then insert past the marker2 alignment distance.
        # Marker2 is aligned at 300mm; default insert adds 100mm margin.
        for axis, signed_mm, label in (
            ("y", drop_y_mm, "MARKER2_DROP_Y"),
            ("z", insert_z_mm, "MARKER2_INSERT_Z_40CM"),
        ):
            if abs(float(signed_mm)) <= 0.0:
                stages.append({
                    "stage": label,
                    "status": "skipped_zero_move",
                    "axis": axis,
                    "signed_mm": float(signed_mm),
                })
                continue
            ok, move_result = self.move_relative_tool_axis_mm(axis, signed_mm, label)
            stages.append({
                "stage": label,
                "axis": axis,
                "signed_mm": float(signed_mm),
                "move_result": scan.sanitize_for_json(move_result),
            })
            if not ok:
                self.result["marker2_place_result"] = {
                    "enabled": True,
                    "status": "insert_move_failed",
                    "failed_stage": label,
                    "stages": scan.sanitize_for_json(stages),
                }
                return False

        if not self.pick_executor.set_gripper_position(
            int(self.marker2_place_open_position),
            "MARKER2_OPEN_GRIPPER_PLACE_BOOK",
        ):
            return False
        stages.append({
            "stage": "MARKER2_OPEN_GRIPPER_PLACE_BOOK",
            "gripper_position": int(self.marker2_place_open_position),
        })

        for axis, signed_mm, label in (
            ("z", -insert_z_mm, "MARKER2_RETREAT_Z_40CM"),
            ("y", -drop_y_mm, "MARKER2_RAISE_Y"),
        ):
            if abs(float(signed_mm)) <= 0.0:
                stages.append({
                    "stage": label,
                    "status": "skipped_zero_move",
                    "axis": axis,
                    "signed_mm": float(signed_mm),
                })
                continue
            ok, move_result = self.move_relative_tool_axis_mm(axis, signed_mm, label)
            stages.append({
                "stage": label,
                "axis": axis,
                "signed_mm": float(signed_mm),
                "move_result": scan.sanitize_for_json(move_result),
            })
            if not ok:
                self.result["marker2_place_result"] = {
                    "enabled": True,
                    "status": "retreat_move_failed",
                    "failed_stage": label,
                    "stages": scan.sanitize_for_json(stages),
                }
                return False

        if self.marker2_place_return_home:
            if not self.move_home_return():
                self.result["marker2_place_result"] = {
                    "enabled": True,
                    "status": "return_home_failed",
                    "stages": scan.sanitize_for_json(stages),
                }
                return False
            stages.append({
                "stage": "MARKER2_PLACE_RETURN_HOME",
                "home_joint_pose_deg": list(self.home_joint_pose_deg),
            })

        self.result["marker2_place_result"] = {
            "enabled": True,
            "status": "placed",
            "insert_z_mm": insert_z_mm,
            "drop_y_mm": drop_y_mm,
            "open_position": int(self.marker2_place_open_position),
            "return_home": bool(self.marker2_place_return_home),
            "stages": scan.sanitize_for_json(stages),
        }
        return True

    def run_pick_stage(self):
        if not self.enable_gripper_control and not self.dry_run:
            return self.abort("gripper_control_disabled")

        selected = self.result.get("selected_book_candidate")
        books = (self.result.get("book_scan_result") or {}).get("books") or []
        selected_book = scan.find_book_by_candidate(books, selected)
        if selected_book is None:
            return self.abort("selected_book_not_found")

        if not self.pick_executor.check_gripper_ready():
            return False
        if not self.pick_executor.torque_on():
            return False
        if not self.pick_executor.set_gripper_position(self.gripper_open_position, "PICK_OPEN_GRIPPER"):
            return False
        if not self.pick_executor.move_relative_axis(self.insert1_mm, "PICK_INSERT_1"):
            return False
        if not self.pick_executor.set_gripper_position(self.gripper_soft_grip_position, "PICK_SOFT_GRIP"):
            return False
        if not self.pick_executor.move_relative_axis(-self.pull1_mm, "PICK_PULL_1"):
            return False
        if not self.pick_executor.set_gripper_position(self.gripper_open_position_2, "PICK_OPEN_GRIPPER_2"):
            return False
        if not self.pick_executor.move_relative_axis(self.insert2_mm, "PICK_INSERT_2"):
            return False
        if not self.pick_executor.set_gripper_position(self.gripper_hard_grip_position, "PICK_HARD_GRIP"):
            return False
        if not self.pick_executor.move_relative_axis(-self.pull_final_mm, "PICK_PULL_FINAL"):
            return False

        self.result["pick_result"] = scan.sanitize_for_json(self.pick_executor.result)
        self.result["selected_book"] = scan.sanitize_for_json(selected_book)
        self.result["selected_book_source"] = "mid"
        return True

    def run_release_stage(self):
        if not self.pick_executor.set_gripper_position(self.gripper_open_position, "PLACE_OPEN_GRIPPER"):
            return False
        self.result["place_result"] = {
            "place_joint_pose_deg": list(self.place_joint_pose_deg),
            "gripper_open_position": int(self.gripper_open_position),
        }
        return True

    def run_return_home_stage(self):
        if not self.move_home_return():
            return False
        self.result["home_result"] = {
            "home_joint_pose_deg": list(self.home_joint_pose_deg),
        }
        return True

    def execute(self):
        self.trace_state("START", "ok")
        if not self.pause_between_states("MOVE_HOME"):
            return self.abort("user_cancelled")

        self.state = "MOVE_HOME"
        self.trace_state(self.state, "running")
        if not self.move_home():
            return self.abort("move_home_failed")
        self.trace_state(self.state, "ok", home_joint_pose_deg=list(self.home_joint_pose_deg))

        if not self.pause_between_states("PREPARE_GRIPPER_VIEW"):
            return self.abort("user_cancelled")
        self.state = "PREPARE_GRIPPER_VIEW"
        self.trace_state(self.state, "running")
        if not self.prepare_gripper_view():
            return self.abort("prepare_gripper_view_failed")
        self.trace_state(
            self.state,
            "ok",
            gripper_view_result=self.result.get("gripper_view_result"),
        )

        if not self.pause_between_states("ALIGN_MARKER"):
            return self.abort("user_cancelled")
        self.state = "ALIGN_MARKER"
        self.trace_state(self.state, "running")
        if not self.run_alignment_stage():
            return False
        self.trace_state(self.state, "ok", alignment_payload=self.result.get("alignment_payload"))

        if not self.pause_between_states("DETECT_BOOK"):
            return self.abort("user_cancelled")
        self.state = "DETECT_BOOK"
        self.trace_state(self.state, "running")
        if not self.run_book_scan_stage():
            return False
        self.result["initial_book_scan_result"] = self.result.get("book_scan_result")
        self.trace_state(
            self.state,
            "ok",
            book_scan_pose=self.result.get("book_scan_pose"),
            selected_book_candidate=self.result.get("selected_book_candidate"),
        )

        if not self.pause_between_states("PREPARE_GRIPPER_PICK_OPEN"):
            return self.abort("user_cancelled")
        self.state = "PREPARE_GRIPPER_PICK_OPEN"
        self.trace_state(self.state, "running")
        if not self.prepare_gripper_pick_open():
            return self.abort("prepare_gripper_pick_open_failed")
        self.trace_state(
            self.state,
            "ok",
            gripper_pick_open_result=self.result.get("gripper_pick_open_result"),
        )

        if not self.pause_between_states("MOVE_TO_BOOK_20CM_OFFSET"):
            return self.abort("user_cancelled")
        self.state = "MOVE_TO_BOOK_20CM_OFFSET"
        self.trace_state(self.state, "running")
        if not self.run_book_pre_approach_stage():
            return self.abort(
                "book_pre_approach_failed",
                book_pre_approach_result=self.result.get("book_pre_approach_result"),
            )
        self.trace_state(
            self.state,
            "ok",
            book_pre_approach_result=self.result.get("book_pre_approach_result"),
        )

        if not self.pause_between_states("LOWER_CAMERA_FOR_VERIFY"):
            return self.abort("user_cancelled")
        self.state = "LOWER_CAMERA_FOR_VERIFY"
        self.trace_state(self.state, "running")
        if not self.run_book_pre_verify_lower_stage():
            return self.abort(
                "book_pre_verify_lower_failed",
                book_pre_verify_lower_result=self.result.get(
                    "book_pre_verify_lower_result"
                ),
            )
        self.trace_state(
            self.state,
            "ok",
            book_pre_verify_lower_result=self.result.get(
                "book_pre_verify_lower_result"
            ),
        )

        if not self.pause_between_states("VERIFY_BOOK_AGAIN"):
            return self.abort("user_cancelled")
        self.state = "VERIFY_BOOK_AGAIN"
        self.trace_state(self.state, "running")
        if not self.run_book_verify_again_stage():
            return False
        self.trace_state(
            self.state,
            "ok",
            verified_selected_book_candidate=self.result.get(
                "verified_selected_book_candidate"
            ),
        )

        if self.stop_after_book_verify_again:
            self.state = "DONE"
            self.result["status"] = "book_verify_again_done"
            self.trace_state(self.state, "ok")
            self.save_final_result()
            return True

        if not self.pause_between_states("ALIGN_BOOK_LATERAL"):
            return self.abort("user_cancelled")
        self.state = "ALIGN_BOOK_LATERAL"
        self.trace_state(self.state, "running")
        if not self.run_book_lateral_align_stage():
            return self.abort(
                "book_lateral_align_failed",
                book_lateral_align_result=self.result.get("book_lateral_align_result"),
            )
        self.trace_state(
            self.state,
            "ok",
            book_lateral_align_result=self.result.get("book_lateral_align_result"),
        )

        if not self.pause_between_states("MOVE_LEFT_1CM"):
            return self.abort("user_cancelled")
        self.state = "MOVE_LEFT_1CM"
        self.trace_state(self.state, "running")
        if not self.run_book_left_shift_stage():
            return self.abort(
                "book_left_shift_failed",
                book_left_shift_result=self.result.get("book_left_shift_result"),
            )
        self.trace_state(
            self.state,
            "ok",
            book_left_shift_result=self.result.get("book_left_shift_result"),
        )

        if not self.pause_between_states("SET_GRIPPER_600_AFTER_ALIGN"):
            return self.abort("user_cancelled")
        self.state = "SET_GRIPPER_600_AFTER_ALIGN"
        self.trace_state(self.state, "running")
        if not self.run_gripper_after_lateral_stage():
            return self.abort(
                "gripper_after_lateral_failed",
                gripper_after_lateral_result=self.result.get(
                    "gripper_after_lateral_result"
                ),
            )
        self.trace_state(
            self.state,
            "ok",
            gripper_after_lateral_result=self.result.get(
                "gripper_after_lateral_result"
            ),
        )

        if self.stop_after_gripper_after_lateral:
            self.state = "DONE"
            self.result["status"] = "gripper_after_lateral_done"
            self.trace_state(self.state, "ok")
            self.save_final_result()
            return True

        if not self.pause_between_states("EXPERIMENTAL_PICK_CYCLES"):
            return self.abort("user_cancelled")
        self.state = "EXPERIMENTAL_PICK_CYCLES"
        self.trace_state(self.state, "running")
        if not self.run_experimental_pick_cycles_stage():
            return self.abort(
                "experimental_pick_cycles_failed",
                experimental_pick_cycles_result=self.result.get(
                    "experimental_pick_cycles_result"
                ),
            )
        self.trace_state(
            self.state,
            "ok",
            experimental_pick_cycles_result=self.result.get(
                "experimental_pick_cycles_result"
            ),
        )

        if self.stop_after_experimental_pick_cycles:
            should_temp_place = (
                self.place_after_experimental_pick_cycles
                or self.marker2_alignment_enabled
            )
            if should_temp_place:
                if not self.pause_between_states("MOVE_TO_PLACE_POSE"):
                    return self.abort("user_cancelled")
                self.state = "MOVE_TO_PLACE_POSE"
                self.trace_state(self.state, "running")
                if not self.move_place_pose():
                    return self.abort("move_to_place_pose_failed")
                self.trace_state(
                    self.state,
                    "ok",
                    place_joint_pose_deg=list(self.place_joint_pose_deg),
                )

                if not self.pause_between_states("LOWER_TO_PLACE_BOOK"):
                    return self.abort("user_cancelled")
                self.state = "LOWER_TO_PLACE_BOOK"
                self.trace_state(self.state, "running")
                if not self.run_place_lower_before_release_stage():
                    return self.abort(
                        "place_lower_before_release_failed",
                        place_lower_result=self.result.get("place_lower_result"),
                    )
                self.trace_state(
                    self.state,
                    "ok",
                    place_lower_result=self.result.get("place_lower_result"),
                )

                if not self.pause_between_states("RELEASE_BOOK"):
                    return self.abort("user_cancelled")
                self.state = "RELEASE_BOOK"
                self.trace_state(self.state, "running")
                if not self.run_release_stage():
                    return self.abort("release_failed")
                self.trace_state(
                    self.state,
                    "ok",
                    place_result=self.result.get("place_result"),
                )

                if not self.pause_between_states("RETURN_HOME"):
                    return self.abort("user_cancelled")
                self.state = "RETURN_HOME"
                self.trace_state(self.state, "running")
                if not self.run_return_home_stage():
                    return self.abort("return_home_failed")
                self.trace_state(
                    self.state,
                    "ok",
                    home_result=self.result.get("home_result"),
                )

            if self.marker2_alignment_enabled:
                if not self.pause_between_states("ALIGN_MARKER2_AFTER_TEMP_PLACE"):
                    return self.abort("user_cancelled")
                self.state = "ALIGN_MARKER2_AFTER_TEMP_PLACE"
                self.trace_state(self.state, "running")
                if not self.run_marker2_alignment_stage():
                    return self.abort(
                        "marker2_alignment_stage_failed",
                        marker2_alignment_result=self.result.get(
                            "marker2_alignment_result"
                        ),
                    )
                self.trace_state(
                    self.state,
                    "ok",
                    marker2_alignment_result=self.result.get(
                        "marker2_alignment_result"
                    ),
                )

                if self.regrip_after_marker2_alignment:
                    if not self.pause_between_states("REGRIP_TEMP_BOOK"):
                        return self.abort("user_cancelled")
                    self.state = "REGRIP_TEMP_BOOK"
                    self.trace_state(self.state, "running")
                    if not self.run_regrip_temp_book_stage():
                        return self.abort(
                            "regrip_temp_book_failed",
                            regrip_temp_book_result=self.result.get(
                                "regrip_temp_book_result"
                            ),
                        )
                    self.trace_state(
                        self.state,
                        "ok",
                        regrip_temp_book_result=self.result.get(
                            "regrip_temp_book_result"
                        ),
                    )

                    if self.marker2_place_after_regrip_enabled:
                        if not self.pause_between_states("PLACE_BOOK_AT_MARKER2"):
                            return self.abort("user_cancelled")
                        self.state = "PLACE_BOOK_AT_MARKER2"
                        self.trace_state(self.state, "running")
                        if not self.run_marker2_place_book_stage():
                            return self.abort(
                                "marker2_place_book_failed",
                                marker2_place_result=self.result.get(
                                    "marker2_place_result"
                                ),
                            )
                        self.trace_state(
                            self.state,
                            "ok",
                            marker2_place_result=self.result.get(
                                "marker2_place_result"
                            ),
                        )

            self.state = "DONE"
            if (
                self.marker2_alignment_enabled
                and self.regrip_after_marker2_alignment
                and self.marker2_place_after_regrip_enabled
            ):
                self.result["status"] = (
                    "experimental_pick_cycles_temp_placed_marker2_aligned_regripped_marker2_placed"
                )
            elif self.marker2_alignment_enabled and self.regrip_after_marker2_alignment:
                self.result["status"] = (
                    "experimental_pick_cycles_temp_placed_marker2_aligned_regripped"
                )
            elif self.marker2_alignment_enabled:
                self.result["status"] = "experimental_pick_cycles_temp_placed_marker2_aligned"
            elif should_temp_place:
                self.result["status"] = "experimental_pick_cycles_temp_placed"
            else:
                self.result["status"] = "experimental_pick_cycles_done"
            self.trace_state(self.state, "ok")
            self.save_final_result()
            return True

        if not self.pause_between_states("PICK_BOOK"):
            return self.abort("user_cancelled")
        self.state = "PICK_BOOK"
        self.trace_state(self.state, "running")
        if not self.run_pick_stage():
            return self.abort("pick_failed")
        self.trace_state(self.state, "ok", pick_result=self.result.get("pick_result"))

        if not self.pause_between_states("MOVE_TO_PLACE_POSE"):
            return self.abort("user_cancelled")
        self.state = "MOVE_TO_PLACE_POSE"
        self.trace_state(self.state, "running")
        if not self.move_place_pose():
            return self.abort("move_to_place_pose_failed")
        self.trace_state(self.state, "ok", place_joint_pose_deg=list(self.place_joint_pose_deg))

        if not self.pause_between_states("RELEASE_BOOK"):
            return self.abort("user_cancelled")
        self.state = "RELEASE_BOOK"
        self.trace_state(self.state, "running")
        if not self.run_release_stage():
            return self.abort("release_failed")
        self.trace_state(self.state, "ok", place_result=self.result.get("place_result"))

        if not self.pause_between_states("RETURN_HOME"):
            return self.abort("user_cancelled")
        self.state = "RETURN_HOME"
        self.trace_state(self.state, "running")
        if not self.run_return_home_stage():
            return self.abort("return_home_failed")
        self.trace_state(self.state, "ok", home_result=self.result.get("home_result"))

        self.state = "DONE"
        self.result["status"] = "done"
        self.trace_state(self.state, "ok")
        self.save_final_result()
        return True

    def shutdown(self):
        if self.vision_node is not None:
            self.vision_node.destroy_node()
        if self.pick_executor is not None and hasattr(self.pick_executor, "node"):
            # pick_executor.node is self
            pass
        if rclpy.ok():
            rclpy.shutdown()


def main(args=None):
    rclpy.init(args=args)
    node = BookMissionStateMachine()
    try:
        ok = node.execute()
        if ok:
            node.get_logger().info("Mission completed successfully.")
        else:
            node.get_logger().error(
                f"Mission finished in state {node.state} with status {node.result.get('status')}"
            )
    finally:
        node.shutdown()
        node.destroy_node()


if __name__ == "__main__":
    main()
