#!/usr/bin/env python3
"""
ArUco TF 정렬 대신, YOLO OBB로 검출한 target book의 pixel 위치를 기준으로
coarse/fine visual servo alignment를 수행하는 테스트 노드.

기본 흐름:
START -> DETECT_TARGET_BOOK -> COARSE_BOOK_ALIGN -> FINE_BOOK_ALIGN -> APPROACH_Z -> DONE

선택적으로 시작 자세 MoveJ를 사용할 때만:
START -> MOVEJ_READY -> WAIT_AFTER_MOVEJ -> DETECT_TARGET_BOOK
-> COARSE_BOOK_ALIGN -> FINE_BOOK_ALIGN -> APPROACH_Z -> DONE
"""

import json
import math
import os
import threading
import time
from datetime import datetime

import cv2
import numpy as np
import rclpy
import yaml
from dsr_msgs2.srv import GetCurrentPosx, MoveJoint, MoveLine
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from ultralytics import YOLO

try:
    from . import realtime_yolo_paddle_ocr as vision
    from .vision_pipeline_utils import detect_books
except ImportError:
    import realtime_yolo_paddle_ocr as vision
    from vision_pipeline_utils import detect_books

from .handeye_transform_utils import matrix_from_yaml_dict


DEFAULT_TARGET_JOINT_DEG = [45.72522, 14.837949, 112.757722, -57.964578, 124.563048, 47.803207]
DEFAULT_TARGET_LOCK_JSON = "./realtime_results/target_book_lock.json"
DEFAULT_PAYLOAD_JSON = "./realtime_results/book_visual_servo_payload.json"
DEFAULT_DESIRED_PIXEL_X = 210.0
DEFAULT_DESIRED_PIXEL_Y = 330.0
DEFAULT_PIXEL_TO_MM_X = 0.5
DEFAULT_PIXEL_TO_MM_Y = 0.5
DEFAULT_MAX_PIXEL_RELATIVE_MM = 80.0
DEFAULT_HAND_EYE_CALIBRATION = (
    "/home/user/Shelfa/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/"
    "T_tool_camera.yaml"
)


def is_finite_vector(v, n):
    if not isinstance(v, (list, tuple)) or len(v) != n:
        return False
    try:
        return all(math.isfinite(float(value)) for value in v)
    except (TypeError, ValueError):
        return False


def is_finite_number(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def clamp(value, max_abs):
    if max_abs <= 0.0:
        return 0.0
    return max(-max_abs, min(max_abs, float(value)))


def angle_wrap_deg(angle):
    value = float(angle)
    while value > 180.0:
        value -= 360.0
    while value < -180.0:
        value += 360.0
    return value


def pixel_distance(px_a, px_b):
    if not is_finite_vector(px_a, 2) or not is_finite_vector(px_b, 2):
        return None
    return float(np.linalg.norm(np.array(px_a, dtype=np.float64) - np.array(px_b, dtype=np.float64)))


def load_json_file(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[BookVisualServo] JSON load failed: {path}: {exc}")
        return None
    return payload if isinstance(payload, dict) else None


def load_tool_camera_transform(path):
    with open(path, "r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    if "T_tool_camera" not in data:
        raise ValueError(f"{path} does not contain T_tool_camera")
    return matrix_from_yaml_dict(data["T_tool_camera"])


def get_lock_focus_pixel(lock_payload):
    if not isinstance(lock_payload, dict):
        return None
    for key in ("pixels_mid", "pixels_center", "obb_center_px"):
        pixel = lock_payload.get(key)
        if is_finite_vector(pixel, 2):
            return [float(pixel[0]), float(pixel[1])]
    return None


def get_lock_size_px(lock_payload):
    if not isinstance(lock_payload, dict):
        return None
    size_px = lock_payload.get("obb_size_px")
    if is_finite_vector(size_px, 2):
        return [float(size_px[0]), float(size_px[1])]
    return None


def get_lock_angle_deg(lock_payload):
    if not isinstance(lock_payload, dict):
        return None
    angle = lock_payload.get("obb_angle_deg")
    if is_finite_number(angle):
        return float(angle)
    return None


class BookVisualServoAlign(Node):
    def __init__(self):
        super().__init__("book_visual_servo_align")

        self.declare_parameter("camera_frame", "camera_color_optical_frame")
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("move_joint_service", "/dsr01/motion/move_joint")
        self.declare_parameter("move_line_service", "/dsr01/motion/move_line")
        self.declare_parameter("current_posx_service", "/dsr01/aux_control/get_current_posx")
        self.declare_parameter("dry_run", True)
        self.declare_parameter("enable_pick_sequence", False)
        self.declare_parameter("enable_gripper_control", False)
        self.declare_parameter("gripper_open_position", 600)
        self.declare_parameter("gripper_soft_grip_position", 620)
        self.declare_parameter("gripper_hard_grip_position", 630)
        self.declare_parameter("gripper_timeout_sec", 5.0)
        self.declare_parameter("gripper_require_ready", True)
        self.declare_parameter("gripper_require_torque_enabled", True)
        self.declare_parameter("pick_axis", "z")
        self.declare_parameter("pick_axis_sign", 1.0)
        self.declare_parameter("insert1_mm", 10.0)
        self.declare_parameter("pull1_mm", 20.0)
        self.declare_parameter("insert2_mm", 30.0)
        self.declare_parameter("pull_final_mm", 80.0)
        self.declare_parameter("pick_step_max_mm", 10.0)
        self.declare_parameter("pick_vel_linear", 10.0)
        self.declare_parameter("pick_vel_angular", 10.0)
        self.declare_parameter("pick_acc_linear", 20.0)
        self.declare_parameter("pick_acc_angular", 20.0)
        self.declare_parameter("current_posx_ref", 0)
        self.declare_parameter("alignment_payload_json", DEFAULT_PAYLOAD_JSON)
        self.declare_parameter("save_alignment_payload_on_done", True)
        self.declare_parameter("auto_run", False)
        self.declare_parameter("auto_step_period_sec", 0.5)
        self.declare_parameter("auto_post_motion_wait_sec", 1.0)
        self.declare_parameter("auto_tf_retry_sec", 0.3)
        self.declare_parameter("auto_max_steps", 300)

        self.declare_parameter("width", 640)
        self.declare_parameter("height", 480)
        self.declare_parameter("fps", 30)
        self.declare_parameter("show_display", True)
        self.declare_parameter("window_name", "Book Visual Servo Align")
        self.declare_parameter("model_path", vision.MODEL_PATH)

        self.declare_parameter("enable_movej", False)
        self.declare_parameter("start_from_current_pose", True)
        self.declare_parameter("target_joint_pose_deg", DEFAULT_TARGET_JOINT_DEG)
        self.declare_parameter("movej_vel", 40.0)
        self.declare_parameter("movej_acc", 70.0)
        self.declare_parameter("movej_time", 0.0)
        self.declare_parameter("movej_radius", 0.0)
        self.declare_parameter("movej_mode", 0)
        self.declare_parameter("movej_blend_type", 0)
        self.declare_parameter("movej_sync_type", 0)

        self.declare_parameter("target_lock_json", DEFAULT_TARGET_LOCK_JSON)
        self.declare_parameter("book_index", -1)
        self.declare_parameter("allow_confidence_fallback", True)
        self.declare_parameter("lock_max_pixel_distance", 150.0)
        self.declare_parameter("freeze_target_during_run", True)
        self.declare_parameter("runtime_track_max_pixel_distance", 220.0)
        self.declare_parameter("runtime_track_use_previous_pixel", True)
        self.declare_parameter("runtime_track_max_step_px", 45.0)

        self.declare_parameter("desired_pixel_x", DEFAULT_DESIRED_PIXEL_X)
        self.declare_parameter("desired_pixel_y", DEFAULT_DESIRED_PIXEL_Y)
        self.declare_parameter("pixel_to_mm_x", DEFAULT_PIXEL_TO_MM_X)
        self.declare_parameter("pixel_to_mm_y", DEFAULT_PIXEL_TO_MM_Y)
        self.declare_parameter("max_pixel_relative_mm", DEFAULT_MAX_PIXEL_RELATIVE_MM)
        self.declare_parameter("translation_source", "handeye_tool")
        self.declare_parameter("allow_pixel_fallback", True)
        self.declare_parameter("calibration_result_path", DEFAULT_HAND_EYE_CALIBRATION)
        self.declare_parameter("desired_book_tool_x_m", 0.0)
        self.declare_parameter("desired_book_tool_y_m", 0.0)
        self.declare_parameter("desired_book_tool_z_m", 0.0)
        self.declare_parameter("sign_handeye_tool_x", 1.0)
        self.declare_parameter("sign_handeye_tool_y", 1.0)
        self.declare_parameter("sign_handeye_tool_z", 1.0)
        self.declare_parameter("handeye_tolerance_xy_m", 0.005)
        self.declare_parameter("handeye_coarse_tolerance_xy_m", 0.020)
        self.declare_parameter("pixel_tolerance_px", 5.0)
        self.declare_parameter("coarse_pixel_tolerance_px", 25.0)
        self.declare_parameter("coarse_translation_scale", 0.5)
        self.declare_parameter("coarse_max_step_mm", 30.0)
        self.declare_parameter("max_step_mm", 5.0)
        self.declare_parameter("axis_mode", "largest")
        self.declare_parameter("coarse_axis_mode", "all")
        self.declare_parameter("tool_axis_from_optical_x", "x")
        self.declare_parameter("tool_axis_from_optical_y", "y")
        self.declare_parameter("tool_axis_from_optical_z", "z")
        self.declare_parameter("sign_tool_from_optical_x", 1.0)
        self.declare_parameter("sign_tool_from_optical_y", -1.0)
        self.declare_parameter("sign_tool_from_optical_z", 1.0)
        self.declare_parameter("trans_vel_linear", 15.0)
        self.declare_parameter("trans_vel_angular", 10.0)
        self.declare_parameter("trans_acc_linear", 30.0)
        self.declare_parameter("trans_acc_angular", 20.0)

        self.declare_parameter("enable_book_angle_align", True)
        self.declare_parameter("book_angle_tolerance_deg", 2.0)
        self.declare_parameter("max_book_angle_step_deg", 1.0)
        self.declare_parameter("sign_tool_b_from_book_angle", 1.0)
        self.declare_parameter("rot_vel_linear", 10.0)
        self.declare_parameter("rot_vel_angular", 5.0)
        self.declare_parameter("rot_acc_linear", 20.0)
        self.declare_parameter("rot_acc_angular", 10.0)

        self.declare_parameter("target_distance_m", 0.0)
        self.declare_parameter("depth_tolerance_m", 0.01)

        self.declare_parameter("yolo_conf", 0.75)
        self.declare_parameter("display_conf_threshold", 0.75)

        self.camera_frame = str(self.get_parameter("camera_frame").value)
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.move_joint_service = str(self.get_parameter("move_joint_service").value)
        self.move_line_service = str(self.get_parameter("move_line_service").value)
        self.current_posx_service = str(self.get_parameter("current_posx_service").value)
        self.dry_run = bool(self.get_parameter("dry_run").value)
        self.enable_pick_sequence = bool(self.get_parameter("enable_pick_sequence").value)
        self.enable_gripper_control = bool(self.get_parameter("enable_gripper_control").value)
        self.gripper_open_position = int(self.get_parameter("gripper_open_position").value)
        self.gripper_soft_grip_position = int(
            self.get_parameter("gripper_soft_grip_position").value
        )
        self.gripper_hard_grip_position = int(
            self.get_parameter("gripper_hard_grip_position").value
        )
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
        self.current_posx_ref = int(self.get_parameter("current_posx_ref").value)
        self.alignment_payload_json = str(self.get_parameter("alignment_payload_json").value)
        self.save_alignment_payload_on_done = bool(
            self.get_parameter("save_alignment_payload_on_done").value
        )
        self.auto_run = bool(self.get_parameter("auto_run").value)
        self.auto_step_period_sec = float(self.get_parameter("auto_step_period_sec").value)
        self.auto_post_motion_wait_sec = float(self.get_parameter("auto_post_motion_wait_sec").value)
        self.auto_tf_retry_sec = float(self.get_parameter("auto_tf_retry_sec").value)
        self.auto_max_steps = int(self.get_parameter("auto_max_steps").value)

        self.width = int(self.get_parameter("width").value)
        self.height = int(self.get_parameter("height").value)
        self.fps = int(self.get_parameter("fps").value)
        self.show_display = bool(self.get_parameter("show_display").value)
        self.window_name = str(self.get_parameter("window_name").value)
        self.model_path = str(self.get_parameter("model_path").value)

        self.enable_movej = bool(self.get_parameter("enable_movej").value)
        self.start_from_current_pose = bool(self.get_parameter("start_from_current_pose").value)
        self.target_joint_pose_deg = [float(v) for v in self.get_parameter("target_joint_pose_deg").value]
        self.movej_vel = float(self.get_parameter("movej_vel").value)
        self.movej_acc = float(self.get_parameter("movej_acc").value)
        self.movej_time = float(self.get_parameter("movej_time").value)
        self.movej_radius = float(self.get_parameter("movej_radius").value)
        self.movej_mode = int(self.get_parameter("movej_mode").value)
        self.movej_blend_type = int(self.get_parameter("movej_blend_type").value)
        self.movej_sync_type = int(self.get_parameter("movej_sync_type").value)

        self.target_lock_json = str(self.get_parameter("target_lock_json").value)
        self.book_index = int(self.get_parameter("book_index").value)
        self.allow_confidence_fallback = bool(self.get_parameter("allow_confidence_fallback").value)
        self.lock_max_pixel_distance = float(self.get_parameter("lock_max_pixel_distance").value)
        self.freeze_target_during_run = bool(self.get_parameter("freeze_target_during_run").value)
        self.runtime_track_max_pixel_distance = float(
            self.get_parameter("runtime_track_max_pixel_distance").value
        )
        self.runtime_track_use_previous_pixel = bool(
            self.get_parameter("runtime_track_use_previous_pixel").value
        )
        self.runtime_track_max_step_px = float(self.get_parameter("runtime_track_max_step_px").value)

        self.desired_pixel_x = float(self.get_parameter("desired_pixel_x").value)
        self.desired_pixel_y = float(self.get_parameter("desired_pixel_y").value)
        self.pixel_to_mm_x = float(self.get_parameter("pixel_to_mm_x").value)
        self.pixel_to_mm_y = float(self.get_parameter("pixel_to_mm_y").value)
        self.max_pixel_relative_mm = float(self.get_parameter("max_pixel_relative_mm").value)
        self.translation_source = str(self.get_parameter("translation_source").value).lower()
        self.allow_pixel_fallback = bool(self.get_parameter("allow_pixel_fallback").value)
        self.calibration_result_path = str(self.get_parameter("calibration_result_path").value)
        self.desired_book_tool_x_m = float(self.get_parameter("desired_book_tool_x_m").value)
        self.desired_book_tool_y_m = float(self.get_parameter("desired_book_tool_y_m").value)
        self.desired_book_tool_z_m = float(self.get_parameter("desired_book_tool_z_m").value)
        self.sign_handeye_tool_x = float(self.get_parameter("sign_handeye_tool_x").value)
        self.sign_handeye_tool_y = float(self.get_parameter("sign_handeye_tool_y").value)
        self.sign_handeye_tool_z = float(self.get_parameter("sign_handeye_tool_z").value)
        self.handeye_tolerance_xy_m = float(self.get_parameter("handeye_tolerance_xy_m").value)
        self.handeye_coarse_tolerance_xy_m = float(
            self.get_parameter("handeye_coarse_tolerance_xy_m").value
        )
        self.pixel_tolerance_px = float(self.get_parameter("pixel_tolerance_px").value)
        self.coarse_pixel_tolerance_px = float(self.get_parameter("coarse_pixel_tolerance_px").value)
        self.coarse_translation_scale = float(self.get_parameter("coarse_translation_scale").value)
        self.coarse_max_step_mm = float(self.get_parameter("coarse_max_step_mm").value)
        self.max_step_mm = float(self.get_parameter("max_step_mm").value)
        self.axis_mode = str(self.get_parameter("axis_mode").value).lower()
        self.coarse_axis_mode = str(self.get_parameter("coarse_axis_mode").value).lower()
        self.tool_axis_from_optical_x = str(self.get_parameter("tool_axis_from_optical_x").value).lower()
        self.tool_axis_from_optical_y = str(self.get_parameter("tool_axis_from_optical_y").value).lower()
        self.tool_axis_from_optical_z = str(self.get_parameter("tool_axis_from_optical_z").value).lower()
        self.sign_tool_from_optical_x = float(self.get_parameter("sign_tool_from_optical_x").value)
        self.sign_tool_from_optical_y = float(self.get_parameter("sign_tool_from_optical_y").value)
        self.sign_tool_from_optical_z = float(self.get_parameter("sign_tool_from_optical_z").value)
        self.trans_vel_linear = float(self.get_parameter("trans_vel_linear").value)
        self.trans_vel_angular = float(self.get_parameter("trans_vel_angular").value)
        self.trans_acc_linear = float(self.get_parameter("trans_acc_linear").value)
        self.trans_acc_angular = float(self.get_parameter("trans_acc_angular").value)

        self.enable_book_angle_align = bool(self.get_parameter("enable_book_angle_align").value)
        self.book_angle_tolerance_deg = float(self.get_parameter("book_angle_tolerance_deg").value)
        self.max_book_angle_step_deg = float(self.get_parameter("max_book_angle_step_deg").value)
        self.sign_tool_b_from_book_angle = float(
            self.get_parameter("sign_tool_b_from_book_angle").value
        )
        self.rot_vel_linear = float(self.get_parameter("rot_vel_linear").value)
        self.rot_vel_angular = float(self.get_parameter("rot_vel_angular").value)
        self.rot_acc_linear = float(self.get_parameter("rot_acc_linear").value)
        self.rot_acc_angular = float(self.get_parameter("rot_acc_angular").value)

        self.target_distance_m = float(self.get_parameter("target_distance_m").value)
        self.depth_tolerance_m = float(self.get_parameter("depth_tolerance_m").value)

        self.yolo_conf = float(self.get_parameter("yolo_conf").value)
        self.display_conf_threshold = float(self.get_parameter("display_conf_threshold").value)

        self.valid_axis_modes = {"all", "z_only", "x_only", "y_only", "xy_only", "largest"}
        self.valid_translation_sources = {"pixel", "handeye_tool"}
        self.valid_tool_axes = {"x", "y", "z"}
        if self.translation_source not in self.valid_translation_sources:
            raise ValueError(
                "translation_source must be one of "
                f"{sorted(self.valid_translation_sources)}, got '{self.translation_source}'"
            )
        if self.axis_mode not in self.valid_axis_modes:
            raise ValueError(
                f"axis_mode must be one of {sorted(self.valid_axis_modes)}, got '{self.axis_mode}'"
            )
        if self.coarse_axis_mode not in self.valid_axis_modes:
            raise ValueError(
                f"coarse_axis_mode must be one of {sorted(self.valid_axis_modes)}, got '{self.coarse_axis_mode}'"
            )
        self.validate_tool_axis("tool_axis_from_optical_x", self.tool_axis_from_optical_x)
        self.validate_tool_axis("tool_axis_from_optical_y", self.tool_axis_from_optical_y)
        self.validate_tool_axis("tool_axis_from_optical_z", self.tool_axis_from_optical_z)
        if len(self.target_joint_pose_deg) != 6:
            raise ValueError("target_joint_pose_deg must contain exactly 6 joint values")

        self.target_lock = load_json_file(self.target_lock_json)

        self.log_info("Loading YOLO model...")
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"YOLO model not found: {self.model_path}")
        self.yolo_model = YOLO(self.model_path)
        self.t_tool_camera = load_tool_camera_transform(self.calibration_result_path)

        self.log_info("Starting RealSense...")
        self.pipeline, self.align, self.color_intrinsics = vision.init_realsense(
            width=self.width,
            height=self.height,
            fps=self.fps,
        )

        self.move_joint_client = self.create_client(MoveJoint, self.move_joint_service)
        self.move_line_client = self.create_client(MoveLine, self.move_line_service)
        self.current_posx_client = self.create_client(GetCurrentPosx, self.current_posx_service)

        self.state = "START"
        self.last_action_sent_motion = False
        self.abort_requested = False
        self.request_shutdown = False
        self.pick_sequence_success = False
        self.pick_sequence_aborted_reason = ""
        self.pick_stage_results = {}
        self.gripper_ready = None
        self.gripper_torque_enabled = None
        self.gripper_open_success = False
        self.gripper_soft_grip_success = False
        self.gripper_hard_grip_success = False
        self.final_pull_executed = False

        self.latest_frame = None
        self.latest_depth_frame = None
        self.latest_books = []
        self.current_target_book = None
        self.current_selection_info = {}
        self.current_selected_pixel = None
        self.current_error_px = None
        self.current_book_angle_deg = None
        self.current_camera_xyz_m = None
        self.current_book_tool_m = None
        self.current_tool_error_m = None
        self.current_active_translation_source = None
        self.current_depth_m = None
        self.current_pixel_aligned = False
        self.current_depth_aligned = False
        self.current_angle_aligned = False
        self.frozen_target_signature = None
        self.frozen_target_initialized = False
        self.previous_tracked_pixel = None

        self.print_config()

    def log_info(self, message):
        logger = self.get_logger()
        if hasattr(logger, "info"):
            logger.info(message)
        elif hasattr(logger, "dinfo"):
            logger.dinfo(message)
        else:
            logger.warn(message)

    def print_config(self):
        if self.auto_run:
            self.get_logger().warn("auto_run=true: the node will advance without pressing Enter.")
        else:
            self.get_logger().warn("Manual mode: press Enter once per state action.")
        if self.dry_run:
            self.get_logger().warn("dry_run=true: MoveJoint and MoveLine requests will be printed only.")
        else:
            self.get_logger().error("dry_run=false: this node may move the real robot.")
        self.log_info(
            "\n"
            "Configuration\n"
            f"  camera_frame={self.camera_frame}, base_frame={self.base_frame}\n"
            f"  alignment_payload_json={self.alignment_payload_json}, "
            f"save_alignment_payload_on_done={self.save_alignment_payload_on_done}\n"
            f"  current_posx_service={self.current_posx_service}, current_posx_ref={self.current_posx_ref}\n"
            f"  enable_pick_sequence={self.enable_pick_sequence} (ignored in this node), "
            f"enable_gripper_control={self.enable_gripper_control} (ignored in this node)\n"
            f"  gripper_open_position={self.gripper_open_position}, "
            f"gripper_soft_grip_position={self.gripper_soft_grip_position}, "
            f"gripper_hard_grip_position={self.gripper_hard_grip_position}, "
            f"gripper_timeout_sec={self.gripper_timeout_sec:.2f}\n"
            f"  gripper_require_ready={self.gripper_require_ready}, "
            f"gripper_require_torque_enabled={self.gripper_require_torque_enabled}\n"
            f"  pick_axis={self.pick_axis}, pick_axis_sign={self.pick_axis_sign:.1f}\n"
            f"  insert1_mm={self.insert1_mm:.1f}, pull1_mm={self.pull1_mm:.1f}, "
            f"insert2_mm={self.insert2_mm:.1f}, pull_final_mm={self.pull_final_mm:.1f}, "
            f"pick_step_max_mm={self.pick_step_max_mm:.1f}\n"
            f"  pick_vel_linear={self.pick_vel_linear:.1f}, pick_vel_angular={self.pick_vel_angular:.1f}, "
            f"pick_acc_linear={self.pick_acc_linear:.1f}, pick_acc_angular={self.pick_acc_angular:.1f}\n"
            f"  auto_run={self.auto_run}, auto_step_period_sec={self.auto_step_period_sec:.3f}, "
            f"auto_post_motion_wait_sec={self.auto_post_motion_wait_sec:.3f}, "
            f"auto_tf_retry_sec={self.auto_tf_retry_sec:.3f}, auto_max_steps={self.auto_max_steps}\n"
            f"  show_display={self.show_display}, window_name={self.window_name}\n"
            f"  model_path={self.model_path}\n"
            f"  enable_movej={self.enable_movej}, start_from_current_pose={self.start_from_current_pose}, "
            f"target_joint_pose_deg={self.target_joint_pose_deg}\n"
            f"  target_lock_json={self.target_lock_json}, book_index={self.book_index}, "
            f"allow_confidence_fallback={self.allow_confidence_fallback}, "
            f"lock_max_pixel_distance={self.lock_max_pixel_distance:.1f}, "
            f"freeze_target_during_run={self.freeze_target_during_run}, "
            f"runtime_track_max_pixel_distance={self.runtime_track_max_pixel_distance:.1f}, "
            f"runtime_track_use_previous_pixel={self.runtime_track_use_previous_pixel}, "
            f"runtime_track_max_step_px={self.runtime_track_max_step_px:.1f}\n"
            f"  desired_pixel=[{self.desired_pixel_x:.1f}, {self.desired_pixel_y:.1f}], "
            f"pixel_to_mm=[{self.pixel_to_mm_x:.3f}, {self.pixel_to_mm_y:.3f}], "
            f"max_pixel_relative_mm={self.max_pixel_relative_mm:.1f}\n"
            f"  translation_source={self.translation_source}, allow_pixel_fallback={self.allow_pixel_fallback}\n"
            f"  calibration_result_path={self.calibration_result_path}\n"
            "  desired_book_tool_xyz_m="
            f"[{self.desired_book_tool_x_m:.3f}, {self.desired_book_tool_y_m:.3f}, "
            f"{self.desired_book_tool_z_m:.3f}], "
            f"sign_handeye_tool_xyz=[{self.sign_handeye_tool_x:.1f}, {self.sign_handeye_tool_y:.1f}, {self.sign_handeye_tool_z:.1f}], "
            f"handeye_tolerance_xy_m={self.handeye_tolerance_xy_m:.3f}, "
            f"handeye_coarse_tolerance_xy_m={self.handeye_coarse_tolerance_xy_m:.3f}\n"
            f"  pixel_tolerance_px={self.pixel_tolerance_px:.1f}, "
            f"coarse_pixel_tolerance_px={self.coarse_pixel_tolerance_px:.1f}\n"
            f"  trans_vel_linear={self.trans_vel_linear:.1f}, trans_vel_angular={self.trans_vel_angular:.1f}, "
            f"trans_acc_linear={self.trans_acc_linear:.1f}, trans_acc_angular={self.trans_acc_angular:.1f}\n"
            f"  enable_book_angle_align={self.enable_book_angle_align}, "
            f"book_angle_tolerance_deg={self.book_angle_tolerance_deg:.3f}, "
            f"max_book_angle_step_deg={self.max_book_angle_step_deg:.3f}, "
            f"sign_tool_b_from_book_angle={self.sign_tool_b_from_book_angle:.1f}\n"
            f"  target_distance_m={self.target_distance_m:.3f}, depth_tolerance_m={self.depth_tolerance_m:.3f}\n"
            f"  yolo_conf={self.yolo_conf:.2f}, display_conf_threshold={self.display_conf_threshold:.2f}\n"
            f"  coarse_axis_mode={self.coarse_axis_mode}, axis_mode={self.axis_mode}\n"
            f"  coarse_max_step_mm={self.coarse_max_step_mm:.1f}, max_step_mm={self.max_step_mm:.1f}\n"
            "  translation mapping: "
            f"optical X -> tool {self.tool_axis_from_optical_x.upper()} "
            f"sign={self.sign_tool_from_optical_x:.1f}, "
            f"optical Y -> tool {self.tool_axis_from_optical_y.upper()} "
            f"sign={self.sign_tool_from_optical_y:.1f}, "
            f"optical Z -> tool {self.tool_axis_from_optical_z.upper()} "
            f"sign={self.sign_tool_from_optical_z:.1f}\n"
            "  recommended flow: finish ArUco alignment first, then run this node from the "
            "current aligned pose with hand-eye book alignment.\n"
            "  rotation hint: book angle align is optional and can be disabled with "
            "--enable-book-angle-align false"
        )

    def validate_tool_axis(self, parameter_name, axis):
        if axis not in self.valid_tool_axes:
            raise ValueError(
                f"{parameter_name} must be one of {sorted(self.valid_tool_axes)}, got '{axis}'"
            )

    @staticmethod
    def format_list(values):
        return "[" + ", ".join(f"{float(value):.3f}" for value in values) + "]"

    @staticmethod
    def clamp(value, max_abs):
        return clamp(value, max_abs)

    @staticmethod
    def clamp_scalar(value, lower, upper):
        return max(lower, min(upper, float(value)))

    def start_camera(self):
        return self.pipeline, self.align, self.color_intrinsics

    def stop_camera(self):
        if getattr(self, "pipeline", None) is not None:
            try:
                self.pipeline.stop()
            except Exception:
                pass
            self.pipeline = None
        if self.show_display:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass

    def capture_frame(self):
        frame, depth_frame, _color_frame = vision.get_realsense_frames(self.pipeline, self.align)
        if frame is None:
            return None, None
        return frame, depth_frame

    def load_target_lock(self):
        self.target_lock = load_json_file(self.target_lock_json)
        return self.target_lock

    def transform_camera_point_to_tool(self, camera_xyz_m):
        if not is_finite_vector(camera_xyz_m, 3):
            return None
        point = np.array(
            [float(camera_xyz_m[0]), float(camera_xyz_m[1]), float(camera_xyz_m[2]), 1.0],
            dtype=np.float64,
        )
        transformed = self.t_tool_camera @ point
        return [float(v) for v in transformed[:3].tolist()]

    def get_selected_pixel(self, selected_book):
        center = (selected_book.get("obb_info") or {}).get("center_px")
        if is_finite_vector(center, 2):
            return [float(center[0]), float(center[1])]
        return None

    def get_book_size_px(self, book):
        size_px = (book.get("obb_info") or {}).get("size_px")
        if is_finite_vector(size_px, 2):
            return [float(size_px[0]), float(size_px[1])]
        return None

    def get_book_angle_deg(self, book):
        angle_deg = (book.get("obb_info") or {}).get("angle_deg")
        if is_finite_number(angle_deg):
            return float(angle_deg)
        return None

    def make_tracking_signature(self, book, selection_info):
        return {
            "book_index": int(book.get("index", -1)),
            "selected_pixel": self.get_selected_pixel(book),
            "size_px": self.get_book_size_px(book),
            "angle_deg": self.get_book_angle_deg(book),
            "selection_source": selection_info.get("selection_source"),
            "reason": selection_info.get("reason"),
        }

    def should_seed_frozen_target(self, selection_info):
        if not isinstance(selection_info, dict):
            return False
        source = str(selection_info.get("selection_source") or "")
        return source in {"manual_book_index", "target_lock"}

    def update_frozen_target_signature(self, book, selection_info, force=False):
        if not force and self.frozen_target_initialized:
            return
        self.frozen_target_signature = self.make_tracking_signature(book, selection_info)
        self.frozen_target_initialized = True

    def select_runtime_frozen_target(self, books):
        if not self.frozen_target_signature:
            return None, {}

        seed_px = self.frozen_target_signature.get("selected_pixel")
        focus_px = seed_px
        target_size_px = self.frozen_target_signature.get("size_px")
        target_angle_deg = self.frozen_target_signature.get("angle_deg")
        if focus_px is None:
            return None, {}

        scored = []
        for book in books:
            center_px = self.get_selected_pixel(book)
            if center_px is None:
                continue

            size_px = self.get_book_size_px(book)
            angle_deg = self.get_book_angle_deg(book)
            seed_dist = pixel_distance(center_px, seed_px)
            if seed_dist is None:
                continue

            prev_dist = None
            if self.runtime_track_use_previous_pixel and is_finite_vector(self.previous_tracked_pixel, 2):
                prev_dist = pixel_distance(center_px, self.previous_tracked_pixel)
                if prev_dist is not None and prev_dist > self.runtime_track_max_step_px:
                    continue

            size_diff = 0.0
            if is_finite_vector(size_px, 2) and target_size_px is not None:
                size_diff = abs(float(size_px[0]) - target_size_px[0]) + abs(
                    float(size_px[1]) - target_size_px[1]
                )

            angle_diff = 0.0
            if is_finite_number(angle_deg) and target_angle_deg is not None:
                angle_diff = abs(angle_wrap_deg(float(angle_deg) - target_angle_deg))

            continuity_term = float(prev_dist) if prev_dist is not None else 0.0
            score = (
                continuity_term
                + 0.25 * float(seed_dist)
                + 0.35 * float(size_diff)
                + 0.1 * float(angle_diff)
            )
            scored.append(
                {
                    "book": book,
                    "score": score,
                    "pixel_distance": float(seed_dist),
                    "previous_pixel_distance": None if prev_dist is None else float(prev_dist),
                    "size_diff": float(size_diff),
                    "angle_diff": float(angle_diff),
                }
            )

        if not scored:
            return None, {}

        scored.sort(
            key=lambda item: (
                float(item["score"]),
                -float(item["book"].get("confidence", 0.0)),
                int(item["book"].get("index", -1)),
            )
        )
        best = scored[0]
        if best["pixel_distance"] > self.runtime_track_max_pixel_distance:
            self.get_logger().warn(
                "Frozen target tracking rejected because pixel distance is too large: "
                f"{best['pixel_distance']:.1f}px > {self.runtime_track_max_pixel_distance:.1f}px"
            )
            return None, {}

        info = {
            "selection_source": "runtime_frozen_target",
            "reason": "runtime_frozen_target",
            "book_index": int(best["book"]["index"]),
            "pixel_distance": round(float(best["pixel_distance"]), 3),
            "previous_pixel_distance": (
                None
                if best["previous_pixel_distance"] is None
                else round(float(best["previous_pixel_distance"]), 3)
            ),
            "size_diff": round(float(best["size_diff"]), 3),
            "angle_diff": round(float(best["angle_diff"]), 3),
            "score": round(float(best["score"]), 3),
            "seed_book_index": self.frozen_target_signature.get("book_index"),
            "seed_selection_source": self.frozen_target_signature.get("selection_source"),
            "seed_reason": self.frozen_target_signature.get("reason"),
        }
        return best["book"], info

    def select_target_book(self, books):
        if not books:
            return None, {}

        manual_index = None
        if self.book_index >= 0:
            manual_index = int(self.book_index)

        if manual_index is not None:
            for book in books:
                if int(book.get("index", -1)) == manual_index:
                    return book, {
                        "selection_source": "manual_book_index",
                        "reason": "manual_book_index",
                        "book_index": int(book["index"]),
                    }
            self.get_logger().warn(f"book_index={manual_index} not found in current detection.")
            return None, {}

        if self.freeze_target_during_run and self.frozen_target_initialized:
            selected_book, selection_info = self.select_runtime_frozen_target(books)
            if selected_book is not None:
                return selected_book, selection_info
            self.get_logger().warn(
                "Frozen target is not visible in the current frame. "
                "Will not switch to another book automatically."
            )
            return None, {}

        lock_payload = self.load_target_lock()
        if lock_payload is not None:
            focus_px = get_lock_focus_pixel(lock_payload)
            target_size_px = get_lock_size_px(lock_payload)
            target_angle_deg = get_lock_angle_deg(lock_payload)
            if focus_px is not None:
                scored = []
                for book in books:
                    center_px = self.get_selected_pixel(book)
                    if center_px is None:
                        continue
                    size_px = (book.get("obb_info") or {}).get("size_px")
                    angle_deg = (book.get("obb_info") or {}).get("angle_deg")
                    pix_dist = pixel_distance(center_px, focus_px)
                    if pix_dist is None:
                        continue
                    size_diff = 0.0
                    if is_finite_vector(size_px, 2) and target_size_px is not None:
                        size_diff = abs(float(size_px[0]) - target_size_px[0]) + abs(
                            float(size_px[1]) - target_size_px[1]
                        )
                    angle_diff = 0.0
                    if is_finite_number(angle_deg) and target_angle_deg is not None:
                        angle_diff = abs(angle_wrap_deg(float(angle_deg) - target_angle_deg))
                    score = float(pix_dist) + 0.3 * float(size_diff) + 0.1 * float(angle_diff)
                    scored.append(
                        {
                            "book": book,
                            "score": score,
                            "pixel_distance": float(pix_dist),
                            "size_diff": float(size_diff),
                            "angle_diff": float(angle_diff),
                        }
                    )

                if scored:
                    scored.sort(
                        key=lambda item: (
                            float(item["score"]),
                            -float(item["book"].get("confidence", 0.0)),
                            int(item["book"].get("index", -1)),
                        )
                    )
                    best = scored[0]
                    if best["pixel_distance"] <= self.lock_max_pixel_distance:
                        info = {
                            "selection_source": "target_lock",
                            "reason": "target_lock",
                            "book_index": int(best["book"]["index"]),
                            "target_lock_focus_px": focus_px,
                            "target_lock_size_px": target_size_px,
                            "target_lock_angle_deg": target_angle_deg,
                            "pixel_distance": round(float(best["pixel_distance"]), 3),
                            "size_diff": round(float(best["size_diff"]), 3),
                            "angle_diff": round(float(best["angle_diff"]), 3),
                            "score": round(float(best["score"]), 3),
                        }
                        return best["book"], info

                    self.get_logger().warn(
                        "target lock matched a book, but pixel distance is too large: "
                        f"{best['pixel_distance']:.1f}px > {self.lock_max_pixel_distance:.1f}px"
                    )
                    return None, {}

        if self.allow_confidence_fallback:
            best = max(books, key=lambda item: float(item.get("confidence", 0.0)))
            return best, {
                "selection_source": "fallback_highest_confidence",
                "reason": "fallback_highest_confidence",
                "book_index": int(best["index"]),
            }

        return None, {}

    def acquire_current_target(self):
        frame, depth_frame = self.capture_frame()
        if frame is None:
            self.get_logger().warn("RealSense frame is not available.")
            return None

        books = detect_books(
            self.yolo_model,
            frame,
            depth_frame,
            self.color_intrinsics,
            yolo_conf=self.yolo_conf,
            display_conf_threshold=self.display_conf_threshold,
        )
        self.latest_frame = frame
        self.latest_depth_frame = depth_frame
        self.latest_books = books

        if not books:
            self.get_logger().warn("No target book detected by YOLO.")
            if self.show_display:
                self.update_display(frame, books, None, None, None)
            return None

        selected_book, selection_info = self.select_target_book(books)
        if selected_book is None:
            self.get_logger().warn("Target book was not found in the current frame.")
            if self.show_display:
                self.update_display(frame, books, None, None, None)
            return None

        selected_pixel = self.get_selected_pixel(selected_book)
        if selected_pixel is None:
            self.get_logger().warn("Selected book pixel is invalid.")
            return None

        error_px = [
            float(selected_pixel[0]) - self.desired_pixel_x,
            float(selected_pixel[1]) - self.desired_pixel_y,
        ]
        angle_deg = float((selected_book.get("obb_info") or {}).get("angle_deg", 0.0))
        camera_xyz_m = selected_book.get("camera_xyz_m")
        depth_valid = bool(selected_book.get("depth_valid"))
        if not depth_valid or not is_finite_vector(camera_xyz_m, 3):
            center_px = selected_pixel
            camera_xyz_m = vision.deproject_pixel_to_camera_xyz(
                depth_frame,
                self.color_intrinsics,
                center_px[0],
                center_px[1],
            )
            depth_valid = vision.is_valid_camera_xyz(camera_xyz_m)

        current_depth_m = camera_xyz_m[2] if depth_valid and is_finite_vector(camera_xyz_m, 3) else None
        current_book_tool_m = self.transform_camera_point_to_tool(camera_xyz_m)

        active_translation_source = "pixel"
        current_tool_error_m = None
        if self.translation_source == "handeye_tool" and is_finite_vector(current_book_tool_m, 3):
            active_translation_source = "handeye_tool"
            current_tool_error_m = [
                float(current_book_tool_m[0]) - self.desired_book_tool_x_m,
                float(current_book_tool_m[1]) - self.desired_book_tool_y_m,
                float(current_book_tool_m[2]) - self.desired_book_tool_z_m,
            ]
        elif self.translation_source == "handeye_tool" and not self.allow_pixel_fallback:
            self.get_logger().warn("Hand-eye translation requested but camera_xyz_m is invalid.")
            return None

        self.current_target_book = selected_book
        self.current_selection_info = selection_info
        self.current_selected_pixel = selected_pixel
        self.current_error_px = error_px
        self.current_book_angle_deg = angle_deg
        self.current_camera_xyz_m = camera_xyz_m
        self.current_book_tool_m = current_book_tool_m
        self.current_tool_error_m = current_tool_error_m
        self.current_active_translation_source = active_translation_source
        self.current_depth_m = current_depth_m
        self.current_pixel_aligned = False
        self.current_depth_aligned = False
        self.current_angle_aligned = False

        self.log_info(
            "\n"
            "[TargetBook]\n"
            f"  selection_source={selection_info.get('selection_source')}\n"
            f"  reason={selection_info.get('reason')}\n"
            f"  book_index={int(selected_book['index'])}\n"
            f"  confidence={float(selected_book.get('confidence', 0.0)):.3f}\n"
            f"  selected_pixel={self.format_pixel(selected_pixel)}\n"
            f"  desired_pixel={self.format_pixel([self.desired_pixel_x, self.desired_pixel_y])}\n"
            f"  error_px={self.format_pixel(error_px)}\n"
            f"  pixel_to_mm=[{self.pixel_to_mm_x:.3f}, {self.pixel_to_mm_y:.3f}]\n"
            f"  max_pixel_relative_mm={self.max_pixel_relative_mm:.1f}\n"
            f"  book_angle_deg={angle_deg:.3f}\n"
            f"  camera_xyz_m={(camera_xyz_m if depth_valid else 'invalid depth')}\n"
            f"  active_translation_source={active_translation_source}\n"
            f"  book_tool_xyz_m={current_book_tool_m}\n"
            f"  tool_error_xyz_m={current_tool_error_m}"
        )

        if self.freeze_target_during_run and (
            not self.frozen_target_initialized and self.should_seed_frozen_target(selection_info)
        ):
            self.update_frozen_target_signature(selected_book, selection_info, force=True)
            self.log_info(
                "\n"
                "[FrozenTargetSeed]\n"
                f"  selection_source={selection_info.get('selection_source')}\n"
                f"  reason={selection_info.get('reason')}\n"
                f"  book_index={int(selected_book['index'])}\n"
                f"  selected_pixel={self.format_pixel(selected_pixel)}"
            )
        self.previous_tracked_pixel = list(selected_pixel)

        if self.show_display:
            self.update_display(frame, books, selected_book, selected_pixel, error_px)

        return selected_book

    def run_movej_step(self):
        if not self.enable_movej:
            self.log_info("MoveJ skipped because enable_movej=false.")
            return

        request = MoveJoint.Request()
        request.pos = self.target_joint_pose_deg
        request.vel = self.movej_vel
        request.acc = self.movej_acc
        request.time = self.movej_time
        request.radius = self.movej_radius
        request.mode = self.movej_mode
        request.blend_type = self.movej_blend_type
        request.sync_type = self.movej_sync_type
        self.print_movej_request(request)

        if self.dry_run:
            self.get_logger().warn("dry_run=true: skipped move_joint service call.")
            self.last_action_sent_motion = True
            return

        self.last_action_sent_motion = self.call_service(
            self.move_joint_client,
            self.move_joint_service,
            request,
            "MoveJoint",
        )

    def run_detect_target_book_step(self):
        selected_book = self.acquire_current_target()
        if selected_book is None:
            return

        angle_deg = float(self.current_book_angle_deg or 0.0)
        self.log_info(
            "\n"
            f"Detect target book state in {self.camera_frame}\n"
            f"  book_index={int(selected_book['index'])}\n"
            f"  confidence={float(selected_book.get('confidence', 0.0)):.3f}\n"
            f"  selected_pixel={self.format_pixel(self.current_selected_pixel)}\n"
            f"  desired_pixel={self.format_pixel([self.desired_pixel_x, self.desired_pixel_y])}\n"
            f"  error_px={self.format_pixel(self.current_error_px)}\n"
            f"  book_angle_deg={angle_deg:.3f}\n"
            f"  book_angle_tolerance_deg={self.book_angle_tolerance_deg:.3f}"
        )

        if not self.enable_book_angle_align:
            self.log_info("Book angle alignment skipped because enable_book_angle_align=false.")
            self.current_angle_aligned = True
            self.state = "COARSE_BOOK_ALIGN"
            return

        if abs(angle_deg) < self.book_angle_tolerance_deg:
            self.current_angle_aligned = True
            self.log_info("Book angle aligned. DETECT_TARGET_BOOK -> COARSE_BOOK_ALIGN")
            self.state = "COARSE_BOOK_ALIGN"
            return

        raw_step_deg = self.sign_tool_b_from_book_angle * angle_deg
        move_b_deg = self.clamp(raw_step_deg, self.max_book_angle_step_deg)
        request = MoveLine.Request()
        request.pos = [0.0, 0.0, 0.0, 0.0, move_b_deg, 0.0]
        request.vel = [self.rot_vel_linear, self.rot_vel_angular]
        request.acc = [self.rot_acc_linear, self.rot_acc_angular]
        self.fill_moveline_common(request)
        self.print_book_angle_request(request, angle_deg, raw_step_deg, move_b_deg)

        if self.dry_run:
            self.get_logger().warn("dry_run=true: skipped move_line service call.")
            self.last_action_sent_motion = True
            return

        self.last_action_sent_motion = self.call_service(
            self.move_line_client,
            self.move_line_service,
            request,
            "MoveLine",
        )

    def run_pixel_translation_step(
        self,
        translation_scale,
        next_state_when_aligned,
        next_state_after_step,
        label,
        axis_mode,
        tolerance_px,
        active_max_step_mm,
    ):
        selected_book = self.acquire_current_target()
        if selected_book is None:
            return

        error_x_px, error_y_px = self.current_error_px
        selected_pixel = self.current_selected_pixel
        active_source = self.current_active_translation_source or "pixel"
        self.log_info(
            "\n"
            f"{label.title()} state in {self.camera_frame}\n"
            f"  book_index={int(selected_book['index'])}\n"
            f"  confidence={float(selected_book.get('confidence', 0.0)):.3f}\n"
            f"  selected_pixel={self.format_pixel(selected_pixel)}\n"
            f"  desired_pixel={self.format_pixel([self.desired_pixel_x, self.desired_pixel_y])}\n"
            f"  error_px={self.format_pixel(self.current_error_px)}\n"
            f"  active_translation_source={active_source}\n"
            f"  book_tool_xyz_m={self.current_book_tool_m}\n"
            f"  tool_error_xyz_m={self.current_tool_error_m}\n"
            f"  axis_mode={axis_mode}, translation_scale={translation_scale:.3f}\n"
            f"  coarse/fine={label}\n"
            f"  active max_step_mm={active_max_step_mm:.1f}\n"
            f"  tolerance_px={tolerance_px:.1f}"
        )

        if active_source == "handeye_tool":
            tolerance_m = (
                self.handeye_coarse_tolerance_xy_m
                if label == "coarse book align"
                else self.handeye_tolerance_xy_m
            )
            error_x_m = float(self.current_tool_error_m[0]) if is_finite_vector(self.current_tool_error_m, 3) else 0.0
            error_y_m = float(self.current_tool_error_m[1]) if is_finite_vector(self.current_tool_error_m, 3) else 0.0
            aligned = abs(error_x_m) < tolerance_m and abs(error_y_m) < tolerance_m
        else:
            tolerance_m = None
            aligned = self.translation_aligned(error_x_px, error_y_px, tolerance_px)

        if aligned:
            self.current_pixel_aligned = True
            self.log_info(f"{label} aligned.")
            if next_state_when_aligned == "DONE":
                self.enter_done_state()
            else:
                self.state = next_state_when_aligned
            return

        if active_source == "handeye_tool":
            move_tool_x_mm, move_tool_y_mm, move_tool_z_mm, active_axes = self.compute_handeye_translation_step(
                translation_scale,
                axis_mode,
                active_max_step_mm,
            )
        else:
            move_tool_x_mm, move_tool_y_mm, move_tool_z_mm, active_axes = self.compute_pixel_translation_step(
                error_x_px,
                error_y_px,
                translation_scale,
                axis_mode,
                active_max_step_mm,
            )
        request = MoveLine.Request()
        request.pos = [move_tool_x_mm, move_tool_y_mm, move_tool_z_mm, 0.0, 0.0, 0.0]
        request.vel = [self.trans_vel_linear, self.trans_vel_angular]
        request.acc = [self.trans_acc_linear, self.trans_acc_angular]
        self.fill_moveline_common(request)
        if active_source == "handeye_tool":
            self.print_handeye_translation_request(
                request,
                active_axes,
                translation_scale,
                label,
                tolerance_m,
            )
        else:
            self.print_translation_request(request, active_axes, translation_scale, label)

        if self.dry_run:
            self.get_logger().warn("dry_run=true: skipped move_line service call.")
            self.last_action_sent_motion = True
            self.state = next_state_after_step
            return

        if self.call_service(self.move_line_client, self.move_line_service, request, "MoveLine"):
            self.last_action_sent_motion = True
            self.state = next_state_after_step

    def run_depth_approach_step(self):
        selected_book = self.acquire_current_target()
        if selected_book is None:
            return

        if self.target_distance_m <= 0.0:
            self.log_info("Depth approach skipped because target_distance_m <= 0.0.")
            self.current_depth_aligned = True
            self.enter_done_state()
            return

        if self.current_depth_m is None or not is_finite_number(self.current_depth_m):
            self.get_logger().warn("Depth approach skipped because selected book depth is invalid.")
            return

        error_z_m = float(self.current_depth_m) - self.target_distance_m
        self.log_info(
            "\n"
            "Approach Z state\n"
            f"  book_index={int(selected_book['index'])}\n"
            f"  current_depth_m={float(self.current_depth_m):.6f}\n"
            f"  target_distance_m={self.target_distance_m:.6f}\n"
            f"  error_z_m={error_z_m:.6f}\n"
            f"  depth_tolerance_m={self.depth_tolerance_m:.6f}"
        )

        if abs(error_z_m) < self.depth_tolerance_m:
            self.current_depth_aligned = True
            self.log_info("Depth aligned. APPROACH_Z -> DONE")
            self.enter_done_state()
            return

        move_tool_z_mm = self.sign_tool_from_optical_z * error_z_m * 1000.0
        move_tool_z_mm = self.clamp(move_tool_z_mm, min(self.max_step_mm, self.max_pixel_relative_mm))

        request = MoveLine.Request()
        request.pos = [0.0, 0.0, move_tool_z_mm, 0.0, 0.0, 0.0]
        request.vel = [self.trans_vel_linear, self.trans_vel_angular]
        request.acc = [self.trans_acc_linear, self.trans_acc_angular]
        self.fill_moveline_common(request)
        self.print_depth_approach_request(request, error_z_m, move_tool_z_mm)

        if self.dry_run:
            self.get_logger().warn("dry_run=true: skipped move_line service call.")
            self.last_action_sent_motion = True
            return

        self.last_action_sent_motion = self.call_service(
            self.move_line_client,
            self.move_line_service,
            request,
            "MoveLine",
        )

    def compute_pixel_translation_step(
        self,
        error_x_px,
        error_y_px,
        translation_scale,
        axis_mode,
        max_step_mm,
    ):
        selected_axes = self.selected_pixel_axes(error_x_px, error_y_px, axis_mode)
        scale = self.clamp_scalar(translation_scale, 0.0, 1.0)
        move_by_tool_axis = {"x": 0.0, "y": 0.0, "z": 0.0}
        corrections = {
            "optical_x": (
                self.tool_axis_from_optical_x,
                self.sign_tool_from_optical_x * error_x_px * self.pixel_to_mm_x * scale,
            ),
            "optical_y": (
                self.tool_axis_from_optical_y,
                self.sign_tool_from_optical_y * error_y_px * self.pixel_to_mm_y * scale,
            ),
        }

        active_axes = []
        for optical_axis in selected_axes:
            tool_axis, correction_mm = corrections[optical_axis]
            move_by_tool_axis[tool_axis] += correction_mm
            active_axes.append(f"{optical_axis}->tool_{tool_axis}")

        limit = min(float(max_step_mm), self.max_pixel_relative_mm)
        return (
            self.clamp(move_by_tool_axis["x"], limit),
            self.clamp(move_by_tool_axis["y"], limit),
            self.clamp(move_by_tool_axis["z"], limit),
            active_axes,
        )

    def compute_handeye_translation_step(self, translation_scale, axis_mode, max_step_mm):
        if not is_finite_vector(self.current_tool_error_m, 3):
            raise RuntimeError("hand-eye translation requires valid current_tool_error_m")

        selected_axes = self.selected_pixel_axes(
            float(self.current_tool_error_m[0]),
            float(self.current_tool_error_m[1]),
            axis_mode,
        )
        scale = self.clamp_scalar(translation_scale, 0.0, 1.0)
        limit = min(float(max_step_mm), self.max_pixel_relative_mm)
        move_by_tool_axis = {"x": 0.0, "y": 0.0, "z": 0.0}
        corrections = {
            "optical_x": ("x", self.sign_handeye_tool_x * float(self.current_tool_error_m[0]) * 1000.0 * scale),
            "optical_y": ("y", self.sign_handeye_tool_y * float(self.current_tool_error_m[1]) * 1000.0 * scale),
        }

        active_axes = []
        for pseudo_axis in selected_axes:
            tool_axis, correction_mm = corrections[pseudo_axis]
            move_by_tool_axis[tool_axis] += correction_mm
            active_axes.append(f"book_tool_{tool_axis}")

        return (
            self.clamp(move_by_tool_axis["x"], limit),
            self.clamp(move_by_tool_axis["y"], limit),
            self.clamp(move_by_tool_axis["z"], limit),
            active_axes,
        )

    def selected_pixel_axes(self, error_x_px, error_y_px, axis_mode):
        if axis_mode == "all":
            return ["optical_x", "optical_y"]
        if axis_mode == "x_only":
            return ["optical_x"]
        if axis_mode == "y_only":
            return ["optical_y"]
        if axis_mode == "xy_only":
            return ["optical_x", "optical_y"]
        if axis_mode == "z_only":
            return []

        normalized_errors = {
            "optical_x": abs(error_x_px) / self.pixel_tolerance_px if self.pixel_tolerance_px > 0.0 else 0.0,
            "optical_y": abs(error_y_px) / self.pixel_tolerance_px if self.pixel_tolerance_px > 0.0 else 0.0,
        }
        return [max(normalized_errors, key=normalized_errors.get)]

    def translation_aligned(self, error_x_px, error_y_px, tolerance_px):
        return abs(error_x_px) < tolerance_px and abs(error_y_px) < tolerance_px

    def fill_moveline_common(self, request):
        request.time = 0.0
        request.radius = 0.0
        request.ref = 1
        request.mode = 1
        request.blend_type = 0
        request.sync_type = 0

    def call_service(self, client, service_name, request, label):
        if not client.wait_for_service(timeout_sec=1.0):
            self.get_logger().error(f"Service not available: {service_name}. No movement sent.")
            if self.auto_run and not self.dry_run:
                self.abort_requested = True
            return False

        self.get_logger().warn(f"Calling {service_name}")
        future = client.call_async(request)
        start_time = time.monotonic()
        while rclpy.ok() and not future.done():
            if time.monotonic() - start_time > 10.0:
                self.get_logger().error(f"{label} service call timed out after 10 seconds.")
                return False
            time.sleep(0.05)

        if future.result() is None:
            self.get_logger().error(f"{label} service failed: {future.exception()}")
            return False

        response = future.result()
        if response.success:
            self.log_info(f"{label} service returned success=true")
            return True

        self.get_logger().error(f"{label} service returned success=false")
        return False

    def read_current_tcp_posx(self):
        if self.dry_run:
            self.get_logger().warn("dry_run=true: current TCP pose is not read for payload saving.")
            return None

        if not self.current_posx_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().warn(f"Service not available: {self.current_posx_service}")
            return None

        request = GetCurrentPosx.Request()
        request.ref = self.current_posx_ref
        future = self.current_posx_client.call_async(request)
        start_time = time.monotonic()
        while rclpy.ok() and not future.done():
            if time.monotonic() - start_time > 5.0:
                self.get_logger().warn(f"{self.current_posx_service} timed out after 5 seconds.")
                return None
            time.sleep(0.05)

        if future.result() is None:
            self.get_logger().warn(f"{self.current_posx_service} failed: {future.exception()}")
            return None

        response = future.result()
        if not bool(response.success):
            self.get_logger().warn(f"{self.current_posx_service} returned success=false.")
            return None

        if not response.task_pos_info:
            self.get_logger().warn(f"{self.current_posx_service} returned empty task_pos_info.")
            return None

        current = list(response.task_pos_info[0].data[:6])
        if len(current) != 6 or not all(math.isfinite(float(value)) for value in current):
            self.get_logger().warn(f"Invalid current TCP pose: {current}")
            return None

        return [float(value) for value in current]

    def enter_done_state(self):
        self.state = "DONE"
        self.print_final_state()
        self.save_alignment_payload()

    def print_final_state(self):
        self.log_info(
            "\n"
            "DONE final state\n"
            f"  selected_book_index={self.current_selection_info.get('book_index')}\n"
            f"  selection_source={self.current_selection_info.get('selection_source')}\n"
            f"  active_translation_source={self.current_active_translation_source}\n"
            f"  selected_pixel={self.format_pixel(self.current_selected_pixel)}\n"
            f"  desired_pixel={self.format_pixel([self.desired_pixel_x, self.desired_pixel_y])}\n"
            f"  final_error_px={self.format_pixel(self.current_error_px)}\n"
            f"  book_tool_xyz_m={self.current_book_tool_m}\n"
            f"  tool_error_xyz_m={self.current_tool_error_m}\n"
            f"  book_angle_deg={float(self.current_book_angle_deg or 0.0):.3f}\n"
            f"  current_depth_m={(None if self.current_depth_m is None else round(float(self.current_depth_m), 3))}\n"
            f"  pixel_aligned={self.current_pixel_aligned}\n"
            f"  angle_aligned={self.current_angle_aligned}\n"
            f"  depth_aligned={self.current_depth_aligned}\n"
            f"  pick_sequence_success={self.pick_sequence_success}\n"
            f"  pick_sequence_aborted_reason={self.pick_sequence_aborted_reason}\n"
            f"  pick_stage_results={json.dumps(self.pick_stage_results, ensure_ascii=False)}\n"
            f"  aligned={self.current_pixel_aligned and self.current_angle_aligned and (self.current_depth_aligned or self.target_distance_m <= 0.0)}"
        )

    def save_alignment_payload(self):
        if not self.save_alignment_payload_on_done:
            return

        current_tcp_pose = self.read_current_tcp_posx()
        payload = {
            "timestamp": datetime.now().isoformat(),
            "source": "book_visual_servo_align",
            "aligned": bool(
                self.current_pixel_aligned
                and self.current_angle_aligned
                and (self.current_depth_aligned or self.target_distance_m <= 0.0)
            ),
            "pick_sequence_enabled": bool(self.enable_pick_sequence),
            "pick_sequence_success": bool(self.pick_sequence_success),
            "pick_sequence_aborted_reason": self.pick_sequence_aborted_reason,
            "pick_stage_results": self.pick_stage_results,
            "gripper_control_enabled": bool(self.enable_gripper_control),
            "gripper_ready": self.gripper_ready,
            "gripper_torque_enabled": self.gripper_torque_enabled,
            "gripper_open_success": bool(self.gripper_open_success),
            "gripper_soft_grip_success": bool(self.gripper_soft_grip_success),
            "gripper_hard_grip_success": bool(self.gripper_hard_grip_success),
            "final_pull_executed": bool(self.final_pull_executed),
            "pick_axis": self.pick_axis,
            "pick_axis_sign": float(self.pick_axis_sign),
            "insert1_mm": float(self.insert1_mm),
            "pull1_mm": float(self.pull1_mm),
            "insert2_mm": float(self.insert2_mm),
            "pull_final_mm": float(self.pull_final_mm),
            "state": self.state,
            "camera_frame": self.camera_frame,
            "base_frame": self.base_frame,
            "target_lock_json": self.target_lock_json,
            "selection_info": self.current_selection_info,
            "selected_book_index": self.current_selection_info.get("book_index"),
            "freeze_target_during_run": self.freeze_target_during_run,
            "runtime_track_max_pixel_distance": self.runtime_track_max_pixel_distance,
            "runtime_track_use_previous_pixel": self.runtime_track_use_previous_pixel,
            "runtime_track_max_step_px": self.runtime_track_max_step_px,
            "previous_tracked_pixel": self.previous_tracked_pixel,
            "frozen_target_signature": self.frozen_target_signature,
            "active_translation_source": self.current_active_translation_source,
            "selected_pixel": self.current_selected_pixel,
            "desired_pixel": [self.desired_pixel_x, self.desired_pixel_y],
            "final_error_px": self.current_error_px,
            "pixel_to_mm": [self.pixel_to_mm_x, self.pixel_to_mm_y],
            "max_pixel_relative_mm": self.max_pixel_relative_mm,
            "translation_source": self.translation_source,
            "allow_pixel_fallback": self.allow_pixel_fallback,
            "calibration_result_path": self.calibration_result_path,
            "book_tool_xyz_m": self.current_book_tool_m,
            "desired_book_tool_xyz_m": [
                self.desired_book_tool_x_m,
                self.desired_book_tool_y_m,
                self.desired_book_tool_z_m,
            ],
            "tool_error_xyz_m": self.current_tool_error_m,
            "handeye_tolerance_xy_m": self.handeye_tolerance_xy_m,
            "handeye_coarse_tolerance_xy_m": self.handeye_coarse_tolerance_xy_m,
            "pixel_tolerance_px": self.pixel_tolerance_px,
            "coarse_pixel_tolerance_px": self.coarse_pixel_tolerance_px,
            "book_angle_deg": self.current_book_angle_deg,
            "angle_tolerance_deg": self.book_angle_tolerance_deg,
            "current_depth_m": self.current_depth_m,
            "target_distance_m": self.target_distance_m,
            "current_tcp_pose": current_tcp_pose,
            "selected_book": self.sanitize_book_for_payload(self.current_target_book),
            "book_detection_count": len(self.latest_books),
        }

        os.makedirs(os.path.dirname(self.alignment_payload_json) or ".", exist_ok=True)
        with open(self.alignment_payload_json, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)

        self.log_info(
            f"Alignment payload saved: {self.alignment_payload_json}\n"
            f"  selected_book_index={payload['selected_book_index']}\n"
            f"  selected_pixel={payload['selected_pixel']}\n"
            f"  final_error_px={payload['final_error_px']}"
        )

    def format_pixel(self, pixel):
        if not is_finite_vector(pixel, 2):
            return "invalid"
        return f"[{float(pixel[0]):.1f}, {float(pixel[1]):.1f}]"

    def sanitize_book_for_payload(self, book):
        if not isinstance(book, dict):
            return None

        points = book.get("points")
        if points is not None:
            try:
                points = np.array(points, dtype=np.float32).reshape(-1, 2)
                points = [[round(float(x), 1), round(float(y), 1)] for x, y in points]
            except Exception:
                points = None

        camera_xyz_m = book.get("camera_xyz_m")
        if is_finite_vector(camera_xyz_m, 3):
            camera_xyz_m = [round(float(v), 3) for v in camera_xyz_m]
        else:
            camera_xyz_m = None

        obb_info = book.get("obb_info") or {}
        sanitized_obb = {
            "center_px": obb_info.get("center_px"),
            "size_px": obb_info.get("size_px"),
            "angle_deg": obb_info.get("angle_deg"),
        }

        return {
            "index": int(book.get("index", -1)),
            "confidence": round(float(book.get("confidence", 0.0)), 3),
            "points": points,
            "obb_info": sanitized_obb,
            "camera_xyz_m": camera_xyz_m,
            "depth_valid": bool(book.get("depth_valid")),
        }

    def print_movej_request(self, request):
        self.log_info(
            "\n"
            "Computed MoveJoint request\n"
            f"  pos [deg]: {self.format_list(request.pos)}\n"
            f"  vel={request.vel:.3f}, acc={request.acc:.3f}, "
            f"time={request.time:.3f}, radius={request.radius:.3f}, "
            f"mode={request.mode}, blend_type={request.blend_type}, sync_type={request.sync_type}"
        )

    def print_book_angle_request(self, request, angle_deg, raw_step_deg, move_b_deg):
        self.log_info(
            "\n"
            "Computed book angle MoveLine request\n"
            f"  book_angle_deg={angle_deg:.3f}\n"
            f"  sign_tool_b_from_book_angle={self.sign_tool_b_from_book_angle:.1f}\n"
            f"  raw_step_deg={raw_step_deg:.3f}, move_b_deg={move_b_deg:.3f}\n"
            f"  max_book_angle_step_deg={self.max_book_angle_step_deg:.3f}\n"
            f"  book_angle_tolerance_deg={self.book_angle_tolerance_deg:.3f}\n"
            f"  pos [mm,deg]: {self.format_list(request.pos)}\n"
            f"  vel: {self.format_list(request.vel)}\n"
            f"  acc: {self.format_list(request.acc)}\n"
            f"  time={request.time:.3f}, radius={request.radius:.3f}, "
            f"ref={request.ref}, mode={request.mode}, "
            f"blend_type={request.blend_type}, sync_type={request.sync_type}"
        )

    def print_handeye_translation_request(self, request, active_axes, translation_scale, label, tolerance_m):
        self.log_info(
            "\n"
            f"Computed {label} MoveLine request (handeye_tool)\n"
            f"  label={label}\n"
            f"  active_axes={active_axes}\n"
            f"  translation_scale={translation_scale:.3f}\n"
            f"  book_tool_xyz_m={self.current_book_tool_m}\n"
            "  desired_book_tool_xyz_m="
            f"[{self.desired_book_tool_x_m:.3f}, {self.desired_book_tool_y_m:.3f}, {self.desired_book_tool_z_m:.3f}]\n"
            "  sign_handeye_tool_xyz="
            f"[{self.sign_handeye_tool_x:.1f}, {self.sign_handeye_tool_y:.1f}, {self.sign_handeye_tool_z:.1f}]\n"
            f"  tool_error_xyz_m={self.current_tool_error_m}\n"
            f"  tolerance_xy_m={tolerance_m:.3f}\n"
            f"  pos [mm,deg]: {self.format_list(request.pos)}\n"
            f"  vel: {self.format_list(request.vel)}\n"
            f"  acc: {self.format_list(request.acc)}\n"
            f"  time={request.time:.3f}, radius={request.radius:.3f}, "
            f"ref={request.ref}, mode={request.mode}, "
            f"blend_type={request.blend_type}, sync_type={request.sync_type}"
        )

    def print_translation_request(self, request, active_axes, translation_scale, label):
        self.log_info(
            "\n"
            f"Computed {label} MoveLine request\n"
            f"  label={label}\n"
            f"  selected_book_index={self.current_selection_info.get('book_index')}\n"
            f"  selected_pixel={self.format_pixel(self.current_selected_pixel)}\n"
            f"  desired_pixel={self.format_pixel([self.desired_pixel_x, self.desired_pixel_y])}\n"
            f"  error_px={self.format_pixel(self.current_error_px)}\n"
            f"  axis_mode={self.coarse_axis_mode if label == 'coarse book align' else self.axis_mode}\n"
            f"  translation_scale={translation_scale:.3f}\n"
            f"  active_axes={active_axes}\n"
            f"  active max_step_mm={self.coarse_max_step_mm if label == 'coarse book align' else self.max_step_mm:.1f}\n"
            f"  max_pixel_relative_mm={self.max_pixel_relative_mm:.1f}\n"
            f"  trans_vel_linear={self.trans_vel_linear:.1f}, trans_vel_angular={self.trans_vel_angular:.1f}\n"
            f"  trans_acc_linear={self.trans_acc_linear:.1f}, trans_acc_angular={self.trans_acc_angular:.1f}\n"
            "  mapping:\n"
            f"    optical X -> tool {self.tool_axis_from_optical_x.upper()} sign={self.sign_tool_from_optical_x:.1f}\n"
            f"    optical Y -> tool {self.tool_axis_from_optical_y.upper()} sign={self.sign_tool_from_optical_y:.1f}\n"
            f"    optical Z -> tool {self.tool_axis_from_optical_z.upper()} sign={self.sign_tool_from_optical_z:.1f}\n"
            f"  pos [mm,deg]: {self.format_list(request.pos)}\n"
            f"  vel: {self.format_list(request.vel)}\n"
            f"  acc: {self.format_list(request.acc)}\n"
            f"  time={request.time:.3f}, radius={request.radius:.3f}, "
            f"ref={request.ref}, mode={request.mode}, "
            f"blend_type={request.blend_type}, sync_type={request.sync_type}"
        )

    def print_depth_approach_request(self, request, error_z_m, move_tool_z_mm):
        self.log_info(
            "\n"
            "Computed depth approach MoveLine request\n"
            f"  current_depth_m={float(self.current_depth_m or 0.0):.6f}\n"
            f"  target_distance_m={self.target_distance_m:.6f}\n"
            f"  error_z_m={error_z_m:.6f}\n"
            f"  move_tool_z_mm={move_tool_z_mm:.3f}\n"
            f"  depth_tolerance_m={self.depth_tolerance_m:.6f}\n"
            f"  pos [mm,deg]: {self.format_list(request.pos)}\n"
            f"  vel: {self.format_list(request.vel)}\n"
            f"  acc: {self.format_list(request.acc)}\n"
            f"  time={request.time:.3f}, radius={request.radius:.3f}, "
            f"ref={request.ref}, mode={request.mode}, "
            f"blend_type={request.blend_type}, sync_type={request.sync_type}"
        )

    def update_display(self, frame, books, selected_book, selected_pixel, error_px):
        if not self.show_display or frame is None:
            return

        vis = frame.copy()
        center_px = (int(round(self.desired_pixel_x)), int(round(self.desired_pixel_y)))
        screen_center = (vis.shape[1] // 2, vis.shape[0] // 2)

        cv2.drawMarker(vis, screen_center, (160, 160, 160), markerType=cv2.MARKER_CROSS, markerSize=18, thickness=2)
        cv2.drawMarker(vis, center_px, (0, 0, 255), markerType=cv2.MARKER_CROSS, markerSize=24, thickness=2)

        for book in books:
            pts = np.array(book["points"], dtype=np.int32)
            is_selected = selected_book is not None and int(book.get("index", -1)) == int(selected_book.get("index", -2))
            color = (0, 0, 255) if is_selected else (0, 255, 0)
            thickness = 3 if is_selected else 2
            cv2.drawContours(vis, [pts], 0, color, thickness)
            center = book.get("obb_info", {}).get("center_px")
            if is_finite_vector(center, 2):
                cx = int(round(center[0]))
                cy = int(round(center[1]))
                label = f"#{int(book.get('index', -1))} {float(book.get('confidence', 0.0)):.2f}"
                cv2.putText(vis, label, (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        if is_finite_vector(selected_pixel, 2):
            sp = (int(round(selected_pixel[0])), int(round(selected_pixel[1])))
            cv2.circle(vis, sp, 5, (0, 255, 255), -1)

        overlay_lines = [
            f"state: {self.state}",
            f"source: {self.current_active_translation_source}",
            f"desired: [{self.desired_pixel_x:.1f}, {self.desired_pixel_y:.1f}]",
            f"error_px: [{error_px[0]:.1f}, {error_px[1]:.1f}]" if is_finite_vector(error_px, 2) else "error_px: invalid",
            f"pixel_to_mm: [{self.pixel_to_mm_x:.2f}, {self.pixel_to_mm_y:.2f}]",
            f"book_index: {self.current_selection_info.get('book_index')}",
            f"selection: {self.current_selection_info.get('selection_source')}",
        ]
        if self.freeze_target_during_run and self.frozen_target_signature is not None:
            overlay_lines.append(
                "frozen_target_seed: "
                f"#{self.frozen_target_signature.get('book_index')} "
                f"({self.frozen_target_signature.get('selection_source')})"
            )
        if is_finite_vector(self.current_book_tool_m, 3):
            overlay_lines.append(
                "book_tool_xyz_m: "
                f"[{self.current_book_tool_m[0]:.3f}, {self.current_book_tool_m[1]:.3f}, {self.current_book_tool_m[2]:.3f}]"
            )
        if is_finite_vector(self.current_tool_error_m, 3):
            overlay_lines.append(
                "tool_error_mm: "
                f"[{self.current_tool_error_m[0] * 1000.0:.1f}, "
                f"{self.current_tool_error_m[1] * 1000.0:.1f}, "
                f"{self.current_tool_error_m[2] * 1000.0:.1f}]"
            )
        y = 24
        for line in overlay_lines:
            cv2.putText(vis, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
            y += 22

        cv2.imshow(self.window_name, vis)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            self.request_shutdown = True

    def handle_enter(self):
        self.last_action_sent_motion = False
        if self.abort_requested:
            self.get_logger().error("Alignment is aborted. Restart after fixing the error.")
            return
        if self.state == "START":
            if self.start_from_current_pose or not self.enable_movej:
                self.log_info("START -> DETECT_TARGET_BOOK (using current pose; recommended after ArUco alignment)")
                self.state = "DETECT_TARGET_BOOK"
            else:
                self.log_info("START -> MOVEJ_READY")
                self.state = "MOVEJ_READY"
            return
        if self.state == "MOVEJ_READY":
            self.run_movej_step()
            self.state = "WAIT_AFTER_MOVEJ"
            return
        if self.state == "WAIT_AFTER_MOVEJ":
            self.log_info("Starting target book detection.")
            self.state = "DETECT_TARGET_BOOK"
            return
        if self.state == "DETECT_TARGET_BOOK":
            self.run_detect_target_book_step()
            return
        if self.state == "COARSE_BOOK_ALIGN":
            self.run_pixel_translation_step(
                translation_scale=self.coarse_translation_scale,
                next_state_when_aligned="FINE_BOOK_ALIGN",
                next_state_after_step="COARSE_BOOK_ALIGN",
                label="coarse book align",
                axis_mode=self.coarse_axis_mode,
                tolerance_px=self.coarse_pixel_tolerance_px,
                active_max_step_mm=self.coarse_max_step_mm,
            )
            return
        if self.state == "FINE_BOOK_ALIGN":
            self.run_pixel_translation_step(
                translation_scale=1.0,
                next_state_when_aligned="APPROACH_Z" if self.target_distance_m > 0.0 else "DONE",
                next_state_after_step="FINE_BOOK_ALIGN",
                label="fine book align",
                axis_mode=self.axis_mode,
                tolerance_px=self.pixel_tolerance_px,
                active_max_step_mm=self.max_step_mm,
            )
            return
        if self.state == "APPROACH_Z":
            self.run_depth_approach_step()
            return
        if self.state == "DONE":
            self.print_final_state()
            self.save_alignment_payload()
            return

        self.get_logger().error(f"Unknown state: {self.state}")


def input_loop(node):
    print("Press Enter for one state action, q to quit")
    while rclpy.ok() and not node.request_shutdown:
        try:
            command = input(f"[{node.state}]> ").strip().lower()
        except EOFError:
            break
        except KeyboardInterrupt:
            raise

        if command == "q":
            break
        if command:
            print("Press Enter with no text to step, or q to quit")
            continue

        node.handle_enter()


def sleep_while_ok(duration_sec):
    end_time = time.monotonic() + max(0.0, float(duration_sec))
    while rclpy.ok() and time.monotonic() < end_time:
        time.sleep(min(0.1, end_time - time.monotonic()))


def auto_loop(node):
    print("AUTO RUN: the node advances by itself. Press Ctrl-C to stop immediately.")
    step_count = 0
    while rclpy.ok() and node.state != "DONE" and not node.abort_requested and not node.request_shutdown:
        if node.auto_max_steps > 0 and step_count >= node.auto_max_steps:
            node.get_logger().warn(
                f"auto_max_steps={node.auto_max_steps} reached; stopping auto loop."
            )
            break

        previous_state = node.state
        node.handle_enter()
        step_count += 1

        if node.state == "DONE" or node.request_shutdown:
            break

        if node.last_action_sent_motion:
            delay_sec = node.auto_post_motion_wait_sec
        elif previous_state == node.state:
            delay_sec = node.auto_tf_retry_sec
        else:
            delay_sec = node.auto_step_period_sec

        node.log_info(
            f"Auto step {step_count}: {previous_state} -> {node.state}. "
            f"Next step in {delay_sec:.1f} sec."
        )
        sleep_while_ok(delay_sec)

    if node.state == "DONE":
        node.log_info("Auto alignment finished: state=DONE")
    elif node.abort_requested:
        node.get_logger().error("Auto alignment stopped because a required service was unavailable.")


def main(args=None):
    rclpy.init(args=args)
    node = None
    executor = None
    spin_thread = None

    try:
        node = BookVisualServoAlign()
        executor = SingleThreadedExecutor()
        executor.add_node(node)
        spin_thread = threading.Thread(target=executor.spin, daemon=True)
        spin_thread.start()

        try:
            if node.auto_run:
                auto_loop(node)
            else:
                input_loop(node)
        except KeyboardInterrupt:
            node.get_logger().warn("Interrupted; exiting without sending another movement.")
    finally:
        if executor is not None:
            executor.shutdown()
        if node is not None:
            node.stop_camera()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        if spin_thread is not None:
            spin_thread.join(timeout=1.0)


if __name__ == "__main__":
    main()
