#!/usr/bin/env python3
"""
TF-based book target approach verification node.

This node reads book_scan_result.json, converts the selected book's camera-space
point into base_link using hand-eye calibration plus live TF, and then computes
an approach pose that stays a safe distance in front of the book.

It is intentionally one-shot and test-oriented:
- dry-run is the default
- no gripper actions
- no pull/insert sequence
- current TCP orientation is preserved from the Doosan task pose
"""

import argparse
import json
import math
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import rclpy
import yaml
from dsr_msgs2.srv import GetCurrentPosx, MoveLine
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from tf2_ros import Buffer, TransformException, TransformListener

from .handeye_config_utils import load_config
from .handeye_transform_utils import (
    matrix_from_yaml_dict,
    matrix_to_euler_xyz,
    transform_stamped_to_matrix,
)


DEFAULT_SCAN_RESULT = "realtime_results/book_scan_result.json"
DEFAULT_PAYLOAD_JSON = "realtime_results/tf_book_target_to_approach_payload.json"
DEFAULT_BASE_FRAME = "base_link"
DEFAULT_TOOL_FRAME = "link_6"
DEFAULT_CAMERA_FRAME = "camera_color_optical_frame"
DEFAULT_MOVE_LINE_SERVICE = "/dsr01/motion/move_line"
DEFAULT_CURRENT_POSX_SERVICE = "/dsr01/aux_control/get_current_posx"
DEFAULT_CURRENT_POSX_REF = 0
DEFAULT_MOVE_STRATEGY = "staged_xy_then_approach"
DEFAULT_BASE_SOURCE = "scan"
DEFAULT_APPROACH_DISTANCE_M = 0.15
DEFAULT_SAFE_Z_MODE = "current_z"
DEFAULT_SAFE_Z_M = None
DEFAULT_XY_STAGE_FIRST = True
DEFAULT_EXECUTE_STAGE = "all"
DEFAULT_MAX_STAGE_STEP_M = 0.40
DEFAULT_MAX_TOTAL_STEP_M = 0.80
DEFAULT_MAX_STAGE1_FORWARD_M = 0.02
DEFAULT_MAX_STAGE3_FORWARD_M = 0.40
DEFAULT_FRONT_DIRECTION_SIGN = 1.0
DEFAULT_STAGE1_LATERAL_SIGN = 1.0
DEFAULT_REFINE_AFTER_STAGE1 = False
DEFAULT_RESCAN_NO_DISPLAY = False
DEFAULT_RESCAN_ALIGNMENT_PAYLOAD_JSON = "realtime_results/alignment_payload.json"
DEFAULT_RESCAN_WIDTH = 640
DEFAULT_RESCAN_HEIGHT = 480
DEFAULT_RESCAN_FPS = 30
DEFAULT_RESCAN_TIMEOUT_SEC = 600.0
DEFAULT_VEL_LINEAR = 15.0
DEFAULT_VEL_ANGULAR = 10.0
DEFAULT_ACC_LINEAR = 30.0
DEFAULT_ACC_ANGULAR = 20.0
DEFAULT_TF_TIMEOUT_SEC = 0.5
DEFAULT_SERVICE_TIMEOUT_SEC = 60.0
DEFAULT_ANDREFF_CALIBRATION = (
    "/home/user/Shelfa/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/"
    "T_link6_camera_ANDREFF.yaml"
)
DEFAULT_TOOL_CAMERA_CALIBRATION = (
    "/home/user/Shelfa/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/"
    "T_tool_camera.yaml"
)


def is_finite_vector(values, length):
    if not isinstance(values, (list, tuple)) or len(values) != length:
        return False
    try:
        return all(math.isfinite(float(v)) for v in values)
    except (TypeError, ValueError):
        return False


def load_json_file(path):
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists():
        return None
    try:
        with file_path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[TFBookTarget] failed to load JSON {path}: {exc}")
        return None
    return payload if isinstance(payload, dict) else None


def load_scan_result(path):
    with Path(path).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def normalize_book_index(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_book_index(book):
    if not isinstance(book, dict):
        return None
    for key in ("book_index", "index"):
        if key in book and book[key] is not None:
            try:
                return int(book[key])
            except (TypeError, ValueError):
                continue
    return None


def find_book_by_index(books, target_index):
    if target_index is None:
        return None
    for book in books or []:
        if get_book_index(book) == int(target_index):
            return book
    return None


def extract_vector_from_container(container, preferred_keys=("mid", "center")):
    if isinstance(container, dict):
        for key in preferred_keys:
            value = container.get(key)
            if is_finite_vector(value, 3):
                return [float(v) for v in value], f"{key}"
    elif is_finite_vector(container, 3):
        return [float(v) for v in container], "direct"
    return None, None


def extract_book_point(book, container_key):
    container = book.get(container_key) if isinstance(book, dict) else None
    point, source = extract_vector_from_container(container)
    if point is not None:
        return point, f"{container_key}.{source}"
    return None, None


def format_vec(values, digits=3):
    if values is None:
        return "None"
    if isinstance(values, np.ndarray):
        values = values.tolist()
    if isinstance(values, (list, tuple)):
        return "[" + ", ".join(f"{float(v):.{digits}f}" for v in values) + "]"
    return str(values)


def default_handeye_candidates():
    candidates = [
        DEFAULT_ANDREFF_CALIBRATION,
        DEFAULT_TOOL_CAMERA_CALIBRATION,
    ]

    try:
        config = load_config()
        for node_name in (
            "aruco_handeye_target_tf",
            "live_target_to_base",
            "handeye_sample_collector",
            "validate_handeye",
            "object_to_base_transformer",
        ):
            node_cfg = config.get(node_name, {}).get("ros__parameters", {})
            calibration_path = node_cfg.get("calibration_result_path")
            if calibration_path:
                candidates.append(calibration_path)
    except Exception:
        pass

    seen = set()
    unique_candidates = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique_candidates.append(candidate)
    return unique_candidates


def resolve_calibration_path(explicit_path):
    candidates = []
    if explicit_path:
        candidates.append(explicit_path)
    candidates.extend(default_handeye_candidates())

    checked = []
    for candidate in candidates:
        candidate_path = Path(candidate).expanduser()
        checked.append(str(candidate_path))
        if candidate_path.exists():
            return candidate_path

    raise FileNotFoundError(
        "No hand-eye calibration YAML found. Tried: " + ", ".join(checked)
    )


def load_handeye_transform(calibration_path):
    with Path(calibration_path).open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}

    for key in ("T_link_6_camera", "T_link6_camera", "T_tool_camera"):
        if key in data:
            return matrix_from_yaml_dict(data[key]), key

    if "matrix" in data or ("rotation_matrix" in data and "translation" in data):
        return matrix_from_yaml_dict(data), "matrix"

    raise ValueError(
        f"{calibration_path} does not contain T_link_6_camera / T_link6_camera / T_tool_camera"
    )


class TfBookTargetToApproach(Node):
    def __init__(self, args):
        super().__init__("tf_book_target_to_approach")
        self.args = args
        self.dry_run = bool(args.dry_run or not args.execute)

        self.scan_result_path = args.scan_result
        self.output_json = args.output_json
        self.book_index_override = args.book_index
        self.base_frame = args.base_frame
        self.tool_frame = args.tool_frame
        self.camera_frame = args.camera_frame
        self.move_strategy = str(args.move_strategy)
        self.base_source = str(args.base_source).lower()
        self.move_line_service = args.move_line_service
        self.current_posx_service = args.current_posx_service
        self.current_posx_ref = int(args.current_posx_ref)
        self.tf_timeout_sec = float(args.tf_timeout_sec)
        self.service_timeout_sec = float(args.service_timeout_sec)
        self.approach_distance_m = float(args.approach_distance_m)
        self.safe_z_mode = str(args.safe_z_mode).lower()
        self.safe_z_m = None if args.safe_z_m is None else float(args.safe_z_m)
        self.xy_stage_first = bool(args.xy_stage_first)
        self.execute_stage = str(args.execute_stage).lower()
        self.max_stage_step_m = float(args.max_stage_step_m)
        self.max_total_step_m = float(args.max_total_step_m)
        self.max_stage1_forward_m = float(args.max_stage1_forward_m)
        self.max_stage3_forward_m = float(args.max_stage3_forward_m)
        self.front_direction_sign = float(args.front_direction_sign)
        self.stage1_lateral_sign = float(args.stage1_lateral_sign)
        self.refine_after_stage1 = bool(args.refine_after_stage1)
        self.rescan_no_display = bool(args.rescan_no_display)
        self.coarse_base_source = str(args.coarse_base_source).lower()
        self.fine_base_source = str(args.fine_base_source).lower()
        self.rescan_alignment_payload_json = str(args.rescan_alignment_payload_json)
        self.rescan_width = int(args.rescan_width)
        self.rescan_height = int(args.rescan_height)
        self.rescan_fps = int(args.rescan_fps)
        self.rescan_timeout_sec = float(args.rescan_timeout_sec)
        self.vel_linear = float(args.vel_linear)
        self.vel_angular = float(args.vel_angular)
        self.acc_linear = float(args.acc_linear)
        self.acc_angular = float(args.acc_angular)
        self.calibration_result_path = args.calibration_result_path
        self.valid_move_strategies = {"staged_xy_then_approach"}
        self.valid_base_sources = {"scan", "handeye"}
        self.valid_safe_z_modes = {"current_z", "book_z", "fixed"}
        self.valid_execute_stages = {"all", "xy_only", "approach_only"}
        if self.move_strategy not in self.valid_move_strategies:
            raise ValueError(
                f"move_strategy must be one of {sorted(self.valid_move_strategies)}, got {self.move_strategy!r}"
            )
        if self.base_source not in self.valid_base_sources:
            raise ValueError(
                f"base_source must be one of {sorted(self.valid_base_sources)}, got {self.base_source!r}"
            )
        if self.safe_z_mode not in self.valid_safe_z_modes:
            raise ValueError(
                f"safe_z_mode must be one of {sorted(self.valid_safe_z_modes)}, got {self.safe_z_mode!r}"
            )
        if self.execute_stage not in self.valid_execute_stages:
            raise ValueError(
                f"execute_stage must be one of {sorted(self.valid_execute_stages)}, got {self.execute_stage!r}"
            )
        if self.front_direction_sign not in (-1.0, 1.0):
            raise ValueError(
                f"front_direction_sign must be 1.0 or -1.0, got {self.front_direction_sign!r}"
            )
        if self.stage1_lateral_sign not in (-1.0, 1.0):
            raise ValueError(
                f"stage1_lateral_sign must be 1.0 or -1.0, got {self.stage1_lateral_sign!r}"
            )
        if self.coarse_base_source not in self.valid_base_sources:
            raise ValueError(
                f"coarse_base_source must be one of {sorted(self.valid_base_sources)}, got {self.coarse_base_source!r}"
            )
        if self.fine_base_source not in self.valid_base_sources:
            raise ValueError(
                f"fine_base_source must be one of {sorted(self.valid_base_sources)}, got {self.fine_base_source!r}"
            )

        self.move_line_client = self.create_client(MoveLine, self.move_line_service)
        self.current_posx_client = self.create_client(GetCurrentPosx, self.current_posx_service)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.scan_result = None
        self.selected_candidate = None
        self.selected_book = None
        self.selection_source = None
        self.selected_book_index = None
        self.alignment_payload = None
        self.bookshelf_front_direction_base = None
        self.book_base_xyz_source = None
        self.book_base_xyz = None
        self.camera_point = None
        self.camera_point_source = None
        self.base_point_from_scan = None
        self.base_point_from_scan_source = None
        self.base_point_from_handeye = None
        self.current_link6_pose = None
        self.current_link6_pose_mm = None
        self.current_link6_xyz_m = None
        self.current_link6_translation = None
        self.current_base_to_tool_tf = None
        self.safe_pre_approach_xyz_m = None
        self.stage1_lateral_pose = None
        self.stage1_xy_pose = None
        self.stage2_z_pose = None
        self.stage3_approach_pose = None
        self.stage_decomposition = {}
        self.stage1_dsr_posx = None
        self.stage2_dsr_posx = None
        self.stage3_dsr_posx = None
        self.generated_dsr_posx = None
        self.generated_dsr_posx_list = []
        self.stage_distances = {}
        self.move_success = False
        self.safety_check = {
            "ok": False,
            "reasons": [],
        }
        self.calibration_matrix = None
        self.calibration_key = None
        self.calibration_source_file = None

        self._print_config()

    def _reset_runtime_state(self):
        self.scan_result = None
        self.selected_candidate = None
        self.selected_book = None
        self.selection_source = None
        self.selected_book_index = None
        self.alignment_payload = None
        self.bookshelf_front_direction_base = None
        self.book_base_xyz_source = None
        self.book_base_xyz = None
        self.camera_point = None
        self.camera_point_source = None
        self.base_point_from_scan = None
        self.base_point_from_scan_source = None
        self.base_point_from_handeye = None
        self.current_link6_pose = None
        self.current_link6_pose_mm = None
        self.current_link6_xyz_m = None
        self.current_link6_translation = None
        self.current_base_to_tool_tf = None
        self.safe_pre_approach_xyz_m = None
        self.stage1_lateral_pose = None
        self.stage1_xy_pose = None
        self.stage2_z_pose = None
        self.stage3_approach_pose = None
        self.stage_decomposition = {}
        self.stage1_dsr_posx = None
        self.stage2_dsr_posx = None
        self.stage3_dsr_posx = None
        self.generated_dsr_posx = None
        self.generated_dsr_posx_list = []
        self.stage_distances = {}
        self.execution_stage_distances = {}
        self.move_success = False
        self.safety_check = {
            "ok": False,
            "reasons": [],
        }

    def _print_config(self):
        self.get_logger().warn(
            "dry_run=true: no robot motion will be sent unless --execute is given."
        )
        self.log_info(
            "\n"
            "Configuration\n"
            f"  scan_result_path={self.scan_result_path}\n"
            f"  output_json={self.output_json}\n"
            f"  base_frame={self.base_frame}, tool_frame={self.tool_frame}, camera_frame={self.camera_frame}\n"
            f"  move_strategy={self.move_strategy}\n"
            f"  base_source={self.base_source}\n"
            f"  move_line_service={self.move_line_service}\n"
            f"  current_posx_service={self.current_posx_service}, current_posx_ref={self.current_posx_ref}\n"
            f"  tf_timeout_sec={self.tf_timeout_sec:.3f}, service_timeout_sec={self.service_timeout_sec:.3f}\n"
            f"  approach_distance_m={self.approach_distance_m:.3f}\n"
            f"  safe_z_mode={self.safe_z_mode}, safe_z_m={self.safe_z_m}\n"
            f"  xy_stage_first={self.xy_stage_first}, execute_stage={self.execute_stage}\n"
            f"  max_stage_step_m={self.max_stage_step_m:.3f}, max_total_step_m={self.max_total_step_m:.3f}\n"
            f"  max_stage1_forward_m={self.max_stage1_forward_m:.3f}, "
            f"max_stage3_forward_m={self.max_stage3_forward_m:.3f}\n"
            f"  front_direction_sign={self.front_direction_sign:.1f}\n"
            f"  stage1_lateral_sign={self.stage1_lateral_sign:.1f}\n"
            f"  refine_after_stage1={self.refine_after_stage1}\n"
            f"  rescan_no_display={self.rescan_no_display}\n"
            f"  coarse_base_source={self.coarse_base_source}, fine_base_source={self.fine_base_source}\n"
            f"  rescan_alignment_payload_json={self.rescan_alignment_payload_json}\n"
            f"  rescan=[{self.rescan_width}, {self.rescan_height}]@{self.rescan_fps} "
            f"timeout={self.rescan_timeout_sec:.1f}\n"
            f"  vel=[{self.vel_linear:.1f}, {self.vel_angular:.1f}], "
            f"acc=[{self.acc_linear:.1f}, {self.acc_angular:.1f}]\n"
            f"  calibration_result_path={self.calibration_result_path or 'auto-detect'}"
        )

    def log_info(self, message):
        logger = self.get_logger()
        if hasattr(logger, "info"):
            logger.info(message)
        elif hasattr(logger, "dinfo"):
            logger.dinfo(message)
        else:
            logger.warn(message)

    def _lookup_base_to_tool_matrix(self):
        try:
            transform = self.tf_buffer.lookup_transform(
                self.base_frame,
                self.tool_frame,
                rclpy.time.Time(),
                timeout=Duration(seconds=self.tf_timeout_sec),
            )
        except TransformException as exc:
            raise RuntimeError(
                f"TF lookup failed: {self.base_frame} -> {self.tool_frame}: {exc}"
            ) from exc
        return transform_stamped_to_matrix(transform)

    def _wait_for_future(self, future, timeout_sec, timeout_message):
        done_event = threading.Event()
        future.add_done_callback(lambda _future: done_event.set())

        if done_event.wait(timeout=float(timeout_sec)):
            return

        raise RuntimeError(timeout_message)

    def _read_current_tcp_pose(self):
        if not self.current_posx_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError(f"Service not available: {self.current_posx_service}")

        request = GetCurrentPosx.Request()
        request.ref = self.current_posx_ref
        future = self.current_posx_client.call_async(request)
        self._wait_for_future(
            future,
            self.service_timeout_sec,
            f"{self.current_posx_service} timed out after {self.service_timeout_sec:.1f} sec",
        )

        if future.result() is None:
            raise RuntimeError(f"{self.current_posx_service} failed: {future.exception()}")

        response = future.result()
        if not bool(response.success):
            raise RuntimeError(f"{self.current_posx_service} returned success=false")
        if not response.task_pos_info:
            raise RuntimeError(f"{self.current_posx_service} returned empty task_pos_info")

        current = list(response.task_pos_info[0].data[:6])
        if len(current) != 6 or not all(math.isfinite(float(v)) for v in current):
            raise RuntimeError(f"Invalid current TCP pose: {current}")

        return [float(v) for v in current]

    def _load_scan_and_select_book(self):
        self.scan_result = load_scan_result(self.scan_result_path)
        books = self.scan_result.get("books", [])
        if not isinstance(books, list) or not books:
            raise RuntimeError("book_scan_result.json does not contain books")

        self.alignment_payload = self.scan_result.get("alignment_payload")
        if not isinstance(self.alignment_payload, dict):
            sidecar_path = Path(self.scan_result_path).with_name("alignment_payload.json")
            self.alignment_payload = load_json_file(sidecar_path)

        if isinstance(self.alignment_payload, dict):
            front_direction, _source = extract_vector_from_container(
                self.alignment_payload.get("bookshelf_front_direction_base"),
                preferred_keys=("direct",),
            )
            self.bookshelf_front_direction_base = front_direction
        if self.bookshelf_front_direction_base is None:
            book_scan_pose = self.scan_result.get("book_scan_pose") or {}
            front_direction, _source = extract_vector_from_container(
                book_scan_pose.get("bookshelf_front_direction_base"),
                preferred_keys=("direct",),
            )
            self.bookshelf_front_direction_base = front_direction

        selected_candidate = self.scan_result.get("selected_book_candidate") or {}
        if self.book_index_override is not None:
            target_index = int(self.book_index_override)
            selection_source = "manual_book_index"
        else:
            target_index = normalize_book_index(selected_candidate.get("book_index"))
            selection_source = str(selected_candidate.get("reason", "selected_book_candidate"))

        if target_index is None:
            raise RuntimeError("selected_book_candidate.book_index is missing and --book-index was not set")

        selected_book = find_book_by_index(books, target_index)
        if selected_book is None:
            raise RuntimeError(
                f"book_index {target_index} was not found in book_scan_result.json books list"
            )

        self.selected_candidate = selected_candidate
        self.selected_book = selected_book
        self.selection_source = selection_source
        self.selected_book_index = target_index
        return selected_book

    def _build_rescan_command(self):
        target_title = None
        if isinstance(self.selected_candidate, dict):
            target_title = self.selected_candidate.get("target_title")
        if not target_title and isinstance(self.scan_result, dict):
            candidate = self.scan_result.get("selected_book_candidate") or {}
            target_title = candidate.get("target_title")
        if not target_title and self.book_index_override is None:
            return None

        cmd = [
            "ros2",
            "run",
            "doosan_realsense_handeye",
            "book_scan_after_alignment",
            "--alignment-payload-json",
            self.rescan_alignment_payload_json,
            "--width",
            str(self.rescan_width),
            "--height",
            str(self.rescan_height),
            "--fps",
            str(self.rescan_fps),
            "--skip-scan-move",
        ]
        if self.rescan_no_display:
            cmd.append("--no-display")
        if self.book_index_override is not None:
            cmd.extend(["--book-index", str(int(self.book_index_override))])
        elif target_title:
            cmd.extend(["--target-title", str(target_title)])
        return cmd

    def _run_rescan_after_stage1(self):
        cmd = self._build_rescan_command()
        if cmd is None:
            self.get_logger().warn("Vision rescan skipped because target_title is unavailable.")
            return False

        self.log_info("Running vision rescan before hand-eye refinement:\n  " + " ".join(cmd))
        if self.dry_run:
            self.get_logger().warn("dry_run=true: rescan command not executed.")
            return True

        try:
            subprocess.run(cmd, check=True, timeout=self.rescan_timeout_sec)
        except subprocess.TimeoutExpired as exc:
            self.get_logger().error(
                f"Vision rescan timed out after {self.rescan_timeout_sec:.1f} sec: {exc}"
            )
            return False
        except subprocess.CalledProcessError as exc:
            self.get_logger().error(f"Vision rescan failed with return code {exc.returncode}")
            return False
        return True

    def _load_book_points(self):
        camera_point, camera_source = extract_book_point(self.selected_book, "camera_xyz_m")
        if camera_point is None:
            return False, "selected book의 camera_xyz_m.mid / camera_xyz_m.center가 유효하지 않습니다."

        base_scan_point, base_scan_source = extract_book_point(self.selected_book, "base_xyz_m")
        self.camera_point = camera_point
        self.camera_point_source = camera_source
        self.base_point_from_scan = base_scan_point
        self.base_point_from_scan_source = base_scan_source
        return True, None

    def _select_book_base_xyz(self):
        if self.base_source == "scan":
            if self.base_point_from_scan is None:
                raise RuntimeError(
                    "base_source=scan but selected book의 base_xyz_m.mid / base_xyz_m.center가 유효하지 않습니다."
                )
            return list(self.base_point_from_scan), self.base_point_from_scan_source

        if self.base_point_from_handeye is None:
            raise RuntimeError("base_source=handeye but hand-eye base point is unavailable")
        return list(self.base_point_from_handeye), "handeye"

    def _resolve_stage_z(self, current_z, book_z, stage_name):
        if self.safe_z_mode == "current_z":
            return float(current_z)
        if self.safe_z_mode == "book_z":
            if book_z is None:
                raise RuntimeError(f"{stage_name}: safe_z_mode=book_z but book_z is unavailable")
            return float(book_z)
        if self.safe_z_mode == "fixed":
            if self.safe_z_m is None:
                raise RuntimeError(f"{stage_name}: safe_z_mode=fixed but safe_z_m is not set")
            return float(self.safe_z_m)
        raise RuntimeError(f"Unsupported safe_z_mode: {self.safe_z_mode}")

    def _build_pose(self, xyz_m, current_pose):
        return [
            float(xyz_m[0]),
            float(xyz_m[1]),
            float(xyz_m[2]),
            float(current_pose[3]),
            float(current_pose[4]),
            float(current_pose[5]),
        ]

    def _pose_distance_m(self, pose_a, pose_b):
        if pose_a is None or pose_b is None:
            return float("nan")
        return float(
            np.linalg.norm(
                np.array(pose_a[:3], dtype=float) - np.array(pose_b[:3], dtype=float)
            )
        )

    def _normalize_front_vector(self, front):
        if not is_finite_vector(front, 3):
            raise RuntimeError("bookshelf_front_direction_base must be finite [x, y, z]")
        front_vec = np.asarray([float(v) for v in front], dtype=float)
        norm = float(np.linalg.norm(front_vec))
        if norm < 1e-9:
            raise RuntimeError("bookshelf_front_direction_base norm is zero")
        return (front_vec / norm) * float(self.front_direction_sign)

    def _decompose_move_vector(self, move_vector_base, front_vector):
        move_vector = np.asarray(move_vector_base, dtype=float)
        front = np.asarray(front_vector, dtype=float)
        forward_component = float(np.dot(move_vector, front))
        forward_vector = forward_component * front
        lateral_vector = move_vector - forward_vector
        lateral_distance = float(np.linalg.norm(lateral_vector))
        return {
            "move_vector_base_m": [float(v) for v in move_vector.tolist()],
            "forward_vector_base_m": [float(v) for v in forward_vector.tolist()],
            "forward_component_m": round(forward_component, 6),
            "lateral_vector_base_m": [float(v) for v in lateral_vector.tolist()],
            "lateral_distance_m": round(lateral_distance, 6),
            "vertical_component_m": round(float(move_vector[2]), 6),
        }

    def _stage_label(self, stage_name):
        return {
            "stage1": "[Stage 1] XY safe move",
            "stage2": "[Stage 2] Z adjust",
            "stage3": "[Stage 3] Approach outside shelf",
        }.get(stage_name, f"[{stage_name}]")

    def _select_execution_order(self):
        if self.execute_stage == "xy_only":
            return ["stage1"]
        if self.execute_stage == "approach_only":
            return ["stage3"]
        if self.execute_stage == "all":
            if self.xy_stage_first:
                return ["stage1", "stage2", "stage3"]
            return ["stage2", "stage3"]
        raise RuntimeError(f"Unsupported execute_stage: {self.execute_stage}")

    def _load_calibration(self):
        calibration_path = resolve_calibration_path(self.calibration_result_path)
        matrix, key = load_handeye_transform(calibration_path)
        self.calibration_matrix = np.asarray(matrix, dtype=float).reshape(4, 4)
        self.calibration_key = key
        self.calibration_source_file = str(calibration_path)
        return self.calibration_matrix

    def _compute_target_pose(self):
        self.current_base_to_tool_tf = self._lookup_base_to_tool_matrix()
        current_translation = self.current_base_to_tool_tf[:3, 3]
        self.current_link6_translation = [float(v) for v in current_translation.tolist()]
        self.current_link6_pose = self._read_current_tcp_pose()
        self.current_link6_pose_mm = list(self.current_link6_pose)
        self.current_link6_xyz_m = [float(v) / 1000.0 for v in self.current_link6_pose_mm[:3]]

        if self.current_link6_pose is None:
            raise RuntimeError("Current Doosan task pose could not be read.")

        camera_point_h = np.array([self.camera_point[0], self.camera_point[1], self.camera_point[2], 1.0], dtype=float)
        base_book_h = self.current_base_to_tool_tf @ self.calibration_matrix @ camera_point_h
        if not np.all(np.isfinite(base_book_h[:3])):
            raise RuntimeError(f"Computed base book point is invalid: {base_book_h[:3].tolist()}")

        self.base_point_from_handeye = [float(v) for v in base_book_h[:3].tolist()]
        self.book_base_xyz, self.book_base_xyz_source = self._select_book_base_xyz()

        front = self._normalize_front_vector(self.bookshelf_front_direction_base)

        safe_pre_approach = np.array(self.book_base_xyz, dtype=float) + front * float(
            self.approach_distance_m
        )
        if not np.all(np.isfinite(safe_pre_approach)):
            raise RuntimeError(f"Computed safe_pre_approach is invalid: {safe_pre_approach.tolist()}")
        self.safe_pre_approach_xyz_m = [float(v) for v in safe_pre_approach.tolist()]

        current_xyz = np.asarray(self.current_link6_xyz_m, dtype=float)
        current_z = float(current_xyz[2])
        book_z = float(self.book_base_xyz[2]) if self.book_base_xyz is not None else None
        stage1_z = current_z
        stage2_z = self._resolve_stage_z(current_z, book_z, "stage2_z_pose")
        stage3_z = self._resolve_stage_z(current_z, book_z, "stage3_approach_pose")

        raw_to_safe = safe_pre_approach - current_xyz
        raw_to_safe_decomp = self._decompose_move_vector(raw_to_safe, front)
        stage1_lateral = (
            np.asarray(raw_to_safe_decomp["lateral_vector_base_m"], dtype=float)
            * float(self.stage1_lateral_sign)
        )
        stage1_lateral_xyz = current_xyz + stage1_lateral
        stage1_xy_xyz = stage1_lateral_xyz.copy()
        stage1_xy_xyz[2] = stage1_z

        stage2_xyz = [
            float(stage1_xy_xyz[0]),
            float(stage1_xy_xyz[1]),
            float(stage2_z),
        ]
        stage3_xyz = [
            float(self.safe_pre_approach_xyz_m[0]),
            float(self.safe_pre_approach_xyz_m[1]),
            float(stage3_z),
        ]

        self.stage1_lateral_pose = self._build_pose(stage1_lateral_xyz.tolist(), self.current_link6_pose)
        self.stage1_xy_pose = self._build_pose(stage1_xy_xyz.tolist(), self.current_link6_pose)
        self.stage2_z_pose = self._build_pose(stage2_xyz, self.current_link6_pose)
        self.stage3_approach_pose = self._build_pose(stage3_xyz, self.current_link6_pose)
        self.stage1_dsr_posx = [float(v * 1000.0) for v in self.stage1_xy_pose[:3]] + list(
            self.stage1_xy_pose[3:6]
        )
        self.stage2_dsr_posx = [float(v * 1000.0) for v in self.stage2_z_pose[:3]] + list(
            self.stage2_z_pose[3:6]
        )
        self.stage3_dsr_posx = [float(v * 1000.0) for v in self.stage3_approach_pose[:3]] + list(
            self.stage3_approach_pose[3:6]
        )
        self.generated_dsr_posx = list(self.stage3_dsr_posx)
        self.generated_dsr_posx_list = [
            list(self.stage1_dsr_posx),
            list(self.stage2_dsr_posx),
            list(self.stage3_dsr_posx),
        ]

        stage1_from_current = self._pose_distance_m(self.current_link6_xyz_m, self.stage1_xy_pose)
        stage2_from_stage1 = self._pose_distance_m(self.stage1_xy_pose, self.stage2_z_pose)
        stage2_from_current = self._pose_distance_m(self.current_link6_xyz_m, self.stage2_z_pose)
        stage3_from_stage2 = self._pose_distance_m(self.stage2_z_pose, self.stage3_approach_pose)
        stage3_from_stage1 = self._pose_distance_m(self.stage1_xy_pose, self.stage3_approach_pose)
        total_distance_m = self._pose_distance_m(self.current_link6_xyz_m, self.stage3_approach_pose)

        stage1_decomp = self._decompose_move_vector(
            np.asarray(self.stage1_xy_pose[:3], dtype=float) - current_xyz,
            front,
        )
        stage2_decomp = self._decompose_move_vector(
            np.asarray(self.stage2_z_pose[:3], dtype=float) - np.asarray(self.stage1_xy_pose[:3], dtype=float),
            front,
        )
        stage3_decomp = self._decompose_move_vector(
            np.asarray(self.stage3_approach_pose[:3], dtype=float) - np.asarray(self.stage2_z_pose[:3], dtype=float),
            front,
        )
        self.stage_decomposition = {
            "front_vector_base": [float(v) for v in front.tolist()],
            "current_xyz_m": [float(v) for v in current_xyz.tolist()],
            "book_base_xyz": list(self.book_base_xyz),
            "safe_pre_approach_xyz_m": list(self.safe_pre_approach_xyz_m),
            "stage1_lateral_pose": self.stage1_lateral_pose,
            "stage1": stage1_decomp,
            "stage2": stage2_decomp,
            "stage3": stage3_decomp,
        }
        self.stage_distances = {
            "stage1_distance_m_from_current": round(stage1_from_current, 6),
            "stage2_distance_m_from_stage1": round(stage2_from_stage1, 6),
            "stage2_distance_m_from_current": round(stage2_from_current, 6),
            "stage3_distance_m_from_stage2": round(stage3_from_stage2, 6),
            "stage3_distance_m_from_stage1": round(stage3_from_stage1, 6),
            "total_distance_m": round(total_distance_m, 6),
        }

        self.safety_check = {
            "ok": True,
            "reasons": [],
            "current_pose_available": True,
            "tf_lookup_available": True,
            "camera_point_source": self.camera_point_source,
            "calibration_source_file": self.calibration_source_file,
            "move_strategy": self.move_strategy,
            "base_source": self.base_source,
            "execute_stage": self.execute_stage,
            "xy_stage_first": self.xy_stage_first,
            "max_stage_step_m": float(self.max_stage_step_m),
            "max_total_step_m": float(self.max_total_step_m),
            "front_direction_sign": float(self.front_direction_sign),
            "stage1_lateral_sign": float(self.stage1_lateral_sign),
            "stage_distances": self.stage_distances,
        }
        stage_order = self._select_execution_order()

        if total_distance_m > self.max_total_step_m:
            self.safety_check["ok"] = False
            self.safety_check["reasons"].append(
                f"current_to_final_distance_m {total_distance_m:.3f} > max_total_step_m {self.max_total_step_m:.3f}"
            )

        if "stage1" in stage_order and abs(stage1_decomp["forward_component_m"]) > self.max_stage1_forward_m:
            self.safety_check["ok"] = False
            self.safety_check["reasons"].append(
                "stage1 forward component "
                f"{stage1_decomp['forward_component_m']:.3f} > max_stage1_forward_m {self.max_stage1_forward_m:.3f}"
            )
        if "stage3" in stage_order and abs(stage3_decomp["forward_component_m"]) > self.max_stage3_forward_m:
            self.safety_check["ok"] = False
            self.safety_check["reasons"].append(
                "stage3 |forward component| "
                f"{abs(stage3_decomp['forward_component_m']):.3f} > "
                f"max_stage3_forward_m {self.max_stage3_forward_m:.3f} "
                f"(raw={stage3_decomp['forward_component_m']:.3f})"
            )

        stage_pose_map = {
            "stage1": self.stage1_xy_pose,
            "stage2": self.stage2_z_pose,
            "stage3": self.stage3_approach_pose,
        }

        current_pose = list(self.current_link6_xyz_m)
        self.execution_stage_distances = {}
        for stage_name in stage_order:
            target_pose = stage_pose_map[stage_name]
            distance_m = self._pose_distance_m(current_pose, target_pose)
            self.execution_stage_distances[f"{stage_name}_distance_m"] = round(distance_m, 6)
            if distance_m > self.max_stage_step_m:
                self.safety_check["ok"] = False
                self.safety_check["reasons"].append(
                    f"{stage_name} distance_m {distance_m:.3f} > max_stage_step_m {self.max_stage_step_m:.3f}"
                )
            current_pose = target_pose

        return total_distance_m

    def _build_move_line_request(self):
        request = MoveLine.Request()
        request.pos = [float(v) for v in self.generated_dsr_posx]
        request.vel = [float(self.vel_linear), float(self.vel_angular)]
        request.acc = [float(self.acc_linear), float(self.acc_angular)]
        request.time = 0.0
        request.radius = 0.0
        request.ref = 0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 0
        return request

    def _call_move_line(self, request):
        if not self.move_line_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError(f"Service not available: {self.move_line_service}")

        future = self.move_line_client.call_async(request)
        self._wait_for_future(
            future,
            self.service_timeout_sec,
            f"{self.move_line_service} timed out after {self.service_timeout_sec:.1f} sec",
        )

        if future.result() is None:
            raise RuntimeError(f"{self.move_line_service} failed: {future.exception()}")

        response = future.result()
        if not bool(response.success):
            raise RuntimeError(f"{self.move_line_service} returned success=false")
        return True

    def _move_stage(self, stage_name, pose, prev_pose):
        if pose is None:
            return True
        distance_m = self._pose_distance_m(prev_pose, pose)
        self.log_info(
            f"{self._stage_label(stage_name)}\n"
            f"  target posx={format_vec([pose[0] * 1000.0, pose[1] * 1000.0, pose[2] * 1000.0, pose[3], pose[4], pose[5]])}\n"
            f"distance_m={distance_m:.3f}"
        )
        if distance_m < 1e-6:
            self.log_info(f"{self._stage_label(stage_name)} skipped because target pose matches current pose.")
            return True

        request = MoveLine.Request()
        request.pos = [
            float(pose[0] * 1000.0),
            float(pose[1] * 1000.0),
            float(pose[2] * 1000.0),
            float(pose[3]),
            float(pose[4]),
            float(pose[5]),
        ]
        request.vel = [float(self.vel_linear), float(self.vel_angular)]
        request.acc = [float(self.acc_linear), float(self.acc_angular)]
        request.time = 0.0
        request.radius = 0.0
        request.ref = 0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 0

        self.log_info(
            f"{self._stage_label(stage_name)} MoveLine request\n"
            f"  pos={format_vec(request.pos)}\n"
            f"  vel={format_vec(request.vel)}\n"
            f"  acc={format_vec(request.acc)}"
        )
        if self.dry_run:
            self.log_info(f"{self._stage_label(stage_name)} dry_run=true: move not sent.")
            return True

        return self._call_move_line(request)

    def _execute_staged_motion(self):
        stage_order = self._select_execution_order()
        stage_pose_map = {
            "stage1": self.stage1_xy_pose,
            "stage2": self.stage2_z_pose,
            "stage3": self.stage3_approach_pose,
        }
        prev_pose = self.current_link6_xyz_m
        for stage_name in stage_order:
            pose = stage_pose_map[stage_name]
            if not self._move_stage(stage_name, pose, prev_pose):
                return False
            prev_pose = pose
        return True

    def _save_payload(self):
        payload = {
            "timestamp": datetime.now().isoformat(),
            "source": "tf_book_target_to_approach",
            "aligned": bool(self.move_success),
            "execute": bool(self.args.execute),
            "dry_run": bool(self.dry_run),
            "move_strategy": self.move_strategy,
            "base_source": self.base_source,
            "selection_source": self.selection_source,
            "selected_book_index": self.selected_book_index,
            "selected_book_candidate": self.selected_candidate,
            "selected_book": self._sanitize_book_for_payload(self.selected_book),
            "camera_xyz_m": self.camera_point,
            "camera_xyz_m_source": self.camera_point_source,
            "base_xyz_m_from_scan": self.base_point_from_scan,
            "base_xyz_m_from_scan_source": self.base_point_from_scan_source,
            "base_xyz_m_from_handeye": self.base_point_from_handeye,
            "book_base_xyz": self.book_base_xyz,
            "book_base_xyz_source": self.book_base_xyz_source,
            "bookshelf_front_direction_base": self.bookshelf_front_direction_base,
            "approach_distance_m": self.approach_distance_m,
            "T_link_6_camera_source_file": self.calibration_source_file,
            "T_link_6_camera_key": self.calibration_key,
            "current_link6_pose": self.current_link6_pose,
            "current_link6_pose_mm": self.current_link6_pose_mm,
            "current_xyz_m": self.current_link6_xyz_m,
            "current_link6_translation_m": self.current_link6_translation,
            "stage1_xy_pose": self.stage1_xy_pose,
            "stage1_lateral_pose": self.stage1_lateral_pose,
            "stage2_z_pose": self.stage2_z_pose,
            "stage3_approach_pose": self.stage3_approach_pose,
            "target_approach_pose": {
                "position_m": self.safe_pre_approach_xyz_m,
                "rpy_deg": self.current_link6_pose[3:6] if self.current_link6_pose else None,
            },
            "generated_dsr_posx": self.generated_dsr_posx,
            "generated_dsr_posx_list": self.generated_dsr_posx_list,
            "stage_decomposition": self.stage_decomposition,
            "stage_distances": self.stage_distances,
            "execution_stage_distances": getattr(self, "execution_stage_distances", {}),
            "move_success": bool(self.move_success),
            "safety_check": self.safety_check,
            "book_scan_result_path": self.scan_result_path,
            "move_line_service": self.move_line_service,
            "current_posx_service": self.current_posx_service,
            "base_frame": self.base_frame,
            "tool_frame": self.tool_frame,
            "camera_frame": self.camera_frame,
        }

        os.makedirs(os.path.dirname(self.output_json) or ".", exist_ok=True)
        with Path(self.output_json).open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)

        self.log_info(
            f"Saved payload: {self.output_json}\n"
            f"  selected_book_index={payload['selected_book_index']}\n"
            f"  camera_xyz_m={payload['camera_xyz_m']}\n"
            f"  base_xyz_m_from_handeye={payload['base_xyz_m_from_handeye']}\n"
            f"  target_approach_pose={payload['target_approach_pose']}\n"
            f"  move_success={payload['move_success']}\n"
            f"  safety_check_ok={payload['safety_check'].get('ok')}"
        )

    def _sanitize_book_for_payload(self, book):
        if not isinstance(book, dict):
            return None
        result = {
            "book_index": get_book_index(book),
            "confidence": round(float(book.get("confidence", 0.0)), 3),
        }
        if "title_candidates" in book:
            result["title_candidates"] = book.get("title_candidates")

        if "camera_xyz_m" in book:
            camera_xyz, camera_source = extract_book_point(book, "camera_xyz_m")
            result["camera_xyz_m"] = camera_xyz
            result["camera_xyz_m_source"] = camera_source

        if "base_xyz_m" in book:
            base_xyz, base_source = extract_book_point(book, "base_xyz_m")
            result["base_xyz_m"] = base_xyz
            result["base_xyz_m_source"] = base_source

        if "obb" in book:
            result["obb"] = book.get("obb")
        elif "obb_info" in book:
            result["obb"] = book.get("obb_info")
        return result

    def print_summary(self, distance_m):
        stage_decomp = self.stage_decomposition or {}
        stage1 = stage_decomp.get("stage1", {})
        stage2 = stage_decomp.get("stage2", {})
        stage3 = stage_decomp.get("stage3", {})
        self.log_info(
            "\n"
            "[TFBookTarget]\n"
            f"  selection_source={self.selection_source}\n"
            f"  selected_book_index={self.selected_book_index}\n"
            f"  candidate_reason={self.selected_candidate.get('reason') if self.selected_candidate else None}\n"
            f"  selected_book_confidence={float(self.selected_book.get('confidence', 0.0)):.3f}\n"
            f"  base_source={self.base_source}\n"
            f"  camera_xyz_m={self.camera_point} ({self.camera_point_source})\n"
            f"  base_xyz_m_from_scan={self.base_point_from_scan} ({self.base_point_from_scan_source})\n"
            f"  base_xyz_m_from_handeye={self.base_point_from_handeye}\n"
            f"  book_base_xyz={self.book_base_xyz}\n"
            f"  book_base_xyz_source={self.book_base_xyz_source}\n"
            f"  bookshelf_front_direction_base={self.bookshelf_front_direction_base}\n"
            f"  front_vector_base={stage_decomp.get('front_vector_base')}\n"
            f"  safe_pre_approach_xyz_m={stage_decomp.get('safe_pre_approach_xyz_m')}\n"
            f"  approach_distance_m={self.approach_distance_m:.3f}\n"
            f"  stage1_lateral_pose={self.stage1_lateral_pose}\n"
            f"  stage1_xy_pose={self.stage1_xy_pose}\n"
            f"  stage2_z_pose={self.stage2_z_pose}\n"
            f"  stage3_approach_pose={self.stage3_approach_pose}\n"
            f"  stage1_forward_component_m={stage1.get('forward_component_m')}\n"
            f"  stage1_lateral_distance_m={stage1.get('lateral_distance_m')}\n"
            f"  stage1_vertical_component_m={stage1.get('vertical_component_m')}\n"
            f"  stage2_forward_component_m={stage2.get('forward_component_m')}\n"
            f"  stage3_forward_component_m={stage3.get('forward_component_m')}\n"
            f"  stage3_lateral_distance_m={stage3.get('lateral_distance_m')}\n"
            f"  stage_distances={self.stage_distances}\n"
            f"  execution_stage_distances={getattr(self, 'execution_stage_distances', {})}\n"
            f"  safety_check_ok={self.safety_check.get('ok')}\n"
            f"  safety_check_reasons={self.safety_check.get('reasons')}\n"
            f"  base_to_tool_translation_m={self.current_link6_translation}\n"
            f"  current_link6_pose_mm={self.current_link6_pose_mm}\n"
            f"  current_xyz_m={self.current_link6_xyz_m}\n"
            f"  current_link6_pose={self.current_link6_pose}\n"
            f"  target_approach_xyz_m={self.safe_pre_approach_xyz_m}\n"
            f"  target_approach_dsr_posx={self.generated_dsr_posx}\n"
            f"  distance_to_target_m={distance_m:.3f}\n"
            f"  max_stage_step_m={self.max_stage_step_m:.3f}\n"
            f"  max_total_step_m={self.max_total_step_m:.3f}\n"
            f"  front_direction_sign={self.front_direction_sign:.1f}\n"
            f"  stage1_lateral_sign={self.stage1_lateral_sign:.1f}\n"
            f"  dry_run={self.dry_run}, execute={bool(self.args.execute)}"
        )
        if self.base_point_from_scan is not None and self.base_point_from_handeye is not None:
            delta = np.array(self.base_point_from_handeye) - np.array(self.base_point_from_scan)
            self.log_info(
                "  scan_vs_handeye_delta_m="
                f"{format_vec(delta.tolist())}"
            )
            delta_norm = float(np.linalg.norm(delta))
            if delta_norm >= 0.05:
                self.get_logger().warn(
                    "[WARN] scan_vs_handeye_delta is large. Hand-eye target may be unreliable."
                )
        if self.safety_check.get("reasons"):
            self.get_logger().warn(
                "Safety check notes: " + "; ".join(self.safety_check["reasons"])
            )

    def run_once(self):
        self._reset_runtime_state()
        self._load_scan_and_select_book()
        ok, reason = self._load_book_points()
        if not ok:
            self.safety_check = {
                "ok": False,
                "reasons": [reason],
            }
            self._save_payload()
            self.print_summary(float("nan"))
            return 1

        self._load_calibration()

        distance_m = None
        try:
            distance_m = self._compute_target_pose()
        except Exception as exc:
            self.safety_check = {
                "ok": False,
                "reasons": [str(exc)],
            }
            self._save_payload()
            self.get_logger().error(str(exc))
            return 1

        self.print_summary(distance_m)

        if not self.safety_check.get("ok"):
            self.move_success = False
            self._save_payload()
            return 1

        if self.dry_run:
            self.get_logger().warn(
                "dry_run=true: computed MoveLine request will not be sent."
            )
            self.move_success = False
            self._save_payload()
            return 0

        try:
            self.log_info(
                "\n"
                "Computed staged Doosan MoveLine plan to book approach\n"
                f"  stage1_xy_pose={self.stage1_xy_pose}\n"
                f"  stage2_z_pose={self.stage2_z_pose}\n"
                f"  stage3_approach_pose={self.stage3_approach_pose}\n"
                f"  generated_dsr_posx_list={self.generated_dsr_posx_list}\n"
                f"  stage_distances={self.stage_distances}\n"
                f"  execution_stage_distances={getattr(self, 'execution_stage_distances', {})}\n"
                f"  execute_stage={self.execute_stage}, xy_stage_first={self.xy_stage_first}"
            )
            self.move_success = self._execute_staged_motion()
            if self.move_success:
                self.log_info("Staged move sequence completed successfully")
        except Exception as exc:
            self.move_success = False
            self.safety_check["ok"] = False
            self.safety_check["reasons"].append(str(exc))
            self.get_logger().error(f"MoveLine failed: {exc}")
            self._save_payload()
            return 1

        self._save_payload()
        return 0


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Use hand-eye calibration and live TF to compute a safe approach pose "
            "for the selected book."
        )
    )
    parser.add_argument("--scan-result", default=DEFAULT_SCAN_RESULT)
    parser.add_argument("--book-index", type=int, default=None)
    parser.add_argument("--move-strategy", default=DEFAULT_MOVE_STRATEGY)
    parser.add_argument("--base-source", default=DEFAULT_BASE_SOURCE)
    parser.add_argument("--calibration-result-path", default=None)
    parser.add_argument("--base-frame", default=DEFAULT_BASE_FRAME)
    parser.add_argument("--tool-frame", default=DEFAULT_TOOL_FRAME)
    parser.add_argument("--camera-frame", default=DEFAULT_CAMERA_FRAME)
    parser.add_argument("--move-line-service", default=DEFAULT_MOVE_LINE_SERVICE)
    parser.add_argument("--current-posx-service", default=DEFAULT_CURRENT_POSX_SERVICE)
    parser.add_argument("--current-posx-ref", type=int, default=DEFAULT_CURRENT_POSX_REF)
    parser.add_argument("--tf-timeout-sec", type=float, default=DEFAULT_TF_TIMEOUT_SEC)
    parser.add_argument("--service-timeout-sec", type=float, default=DEFAULT_SERVICE_TIMEOUT_SEC)
    parser.add_argument("--approach-distance-m", type=float, default=DEFAULT_APPROACH_DISTANCE_M)
    parser.add_argument("--safe-z-mode", default=DEFAULT_SAFE_Z_MODE)
    parser.add_argument("--safe-z-m", type=float, default=DEFAULT_SAFE_Z_M)
    parser.add_argument(
        "--xy-stage-first",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_XY_STAGE_FIRST,
    )
    parser.add_argument("--execute-stage", default=DEFAULT_EXECUTE_STAGE)
    parser.add_argument("--max-stage-step-m", type=float, default=DEFAULT_MAX_STAGE_STEP_M)
    parser.add_argument("--max-total-step-m", type=float, default=DEFAULT_MAX_TOTAL_STEP_M)
    parser.add_argument("--max-stage1-forward-m", type=float, default=DEFAULT_MAX_STAGE1_FORWARD_M)
    parser.add_argument("--max-stage3-forward-m", type=float, default=DEFAULT_MAX_STAGE3_FORWARD_M)
    parser.add_argument(
        "--front-direction-sign",
        type=float,
        default=DEFAULT_FRONT_DIRECTION_SIGN,
        help="bookshelf_front_direction_base 부호를 반전할 때 -1.0을 사용합니다.",
    )
    parser.add_argument(
        "--stage1-lateral-sign",
        type=float,
        default=DEFAULT_STAGE1_LATERAL_SIGN,
        help="stage1의 lateral 이동 방향을 반전할 때 -1.0을 사용합니다.",
    )
    parser.add_argument(
        "--refine-after-stage1",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_REFINE_AFTER_STAGE1,
        help="stage1 coarse move 후 vision rescan을 수행하고 hand-eye fine 접근을 이어서 실행합니다.",
    )
    parser.add_argument(
        "--rescan-no-display",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_RESCAN_NO_DISPLAY,
        help="stage1 이후 vision rescan 화면 표시를 끄려면 true로 설정합니다.",
    )
    parser.add_argument(
        "--coarse-base-source",
        default=DEFAULT_BASE_SOURCE,
        help="refine-after-stage1의 coarse pass에 사용할 base source입니다.",
    )
    parser.add_argument(
        "--fine-base-source",
        default="handeye",
        help="refine-after-stage1의 fine pass에 사용할 base source입니다.",
    )
    parser.add_argument(
        "--rescan-alignment-payload-json",
        default=DEFAULT_RESCAN_ALIGNMENT_PAYLOAD_JSON,
        help="stage1 이후 다시 book_scan_after_alignment를 실행할 때 사용할 alignment payload JSON입니다.",
    )
    parser.add_argument(
        "--rescan-width",
        type=int,
        default=DEFAULT_RESCAN_WIDTH,
    )
    parser.add_argument(
        "--rescan-height",
        type=int,
        default=DEFAULT_RESCAN_HEIGHT,
    )
    parser.add_argument(
        "--rescan-fps",
        type=int,
        default=DEFAULT_RESCAN_FPS,
    )
    parser.add_argument(
        "--rescan-timeout-sec",
        type=float,
        default=DEFAULT_RESCAN_TIMEOUT_SEC,
    )
    parser.add_argument("--vel-linear", type=float, default=DEFAULT_VEL_LINEAR)
    parser.add_argument("--vel-angular", type=float, default=DEFAULT_VEL_ANGULAR)
    parser.add_argument("--acc-linear", type=float, default=DEFAULT_ACC_LINEAR)
    parser.add_argument("--acc-angular", type=float, default=DEFAULT_ACC_ANGULAR)
    parser.add_argument("--output-json", default=DEFAULT_PAYLOAD_JSON)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    rclpy.init(args=None)

    node = TfBookTargetToApproach(args)
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    try:
        if not node.refine_after_stage1:
            return node.run_once()

        original_base_source = node.base_source
        original_execute_stage = node.execute_stage
        original_xy_stage_first = node.xy_stage_first

        node.base_source = node.coarse_base_source
        node.execute_stage = "xy_only"
        coarse_rc = node.run_once()
        if coarse_rc != 0:
            return coarse_rc

        if not node._run_rescan_after_stage1():
            return 1

        node.base_source = node.fine_base_source
        node.execute_stage = "all"
        node.xy_stage_first = False
        fine_rc = node.run_once()

        node.base_source = original_base_source
        node.execute_stage = original_execute_stage
        node.xy_stage_first = original_xy_stage_first
        return fine_rc
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        spin_thread.join(timeout=1.0)


if __name__ == "__main__":
    raise SystemExit(main())
