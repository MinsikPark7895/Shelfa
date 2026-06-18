import json
import math
import os
import subprocess
import threading
import time
from datetime import datetime

import rclpy
from dsr_msgs2.srv import GetCurrentPosx, MoveJoint, MoveLine
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from tf2_ros import Buffer, TransformException, TransformListener


MARKER_TARGET_PRESETS = {
    0: [-12.5, -7.77, 91.42, -88.59, 77.57, -6.51],
    1: [-12.5, 13.62, 127.84, -99.84, 82.24, 51.12],
}
MARKER_SCAN_TOOL_Y_OFFSETS_MM = {
    0: 200.0,
    1: 150.0,
}


class ArucoMarkerProtoAlign(Node):
    def __init__(self):
        super().__init__("aruco_marker_proto_align")

        self.declare_parameter("camera_frame", "camera_color_optical_frame")
        self.declare_parameter("marker_frame", "aruco_marker_0")
        self.declare_parameter("marker_frame_prefix", "aruco_marker_")
        self.declare_parameter("target_marker_id", -1)
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("move_joint_service", "/dsr01/motion/move_joint")
        self.declare_parameter("move_line_service", "/dsr01/motion/move_line")
        self.declare_parameter("current_posx_service", "/dsr01/aux_control/get_current_posx")
        self.declare_parameter("dry_run", True)
        self.declare_parameter("current_posx_ref", 0)
        self.declare_parameter("alignment_payload_json", "./realtime_results/alignment_payload.json")
        self.declare_parameter("save_alignment_payload_on_done", True)
        self.declare_parameter("shelf_frame", "")
        self.declare_parameter("auto_run", False)
        self.declare_parameter("auto_step_period_sec", 0.5)
        self.declare_parameter("auto_post_motion_wait_sec", 1.0)
        self.declare_parameter("auto_tf_retry_sec", 0.3)
        self.declare_parameter("auto_max_steps", 300)
        self.declare_parameter("run_post_alignment_pipeline", True)
        self.declare_parameter("post_alignment_target_title", "제3인류")
        self.declare_parameter("post_alignment_no_display", True)

        self.declare_parameter("enable_movej", True)
        self.declare_parameter(
            "target_joint_pose_deg",
            MARKER_TARGET_PRESETS[0],
        )
        self.declare_parameter("movej_vel", 40.0)                 # 변경: 20.0 -> 40.0
        self.declare_parameter("movej_acc", 70.0)                 # 변경: 40.0 -> 70.0
        self.declare_parameter("movej_time", 0.0)
        self.declare_parameter("movej_radius", 0.0)
        self.declare_parameter("movej_mode", 0)
        self.declare_parameter("movej_blend_type", 0)
        self.declare_parameter("movej_sync_type", 0)

        self.declare_parameter("enable_rotation_align", True)
        self.declare_parameter("rotation_tolerance_deg", 2.0)
        self.declare_parameter("max_rot_step_deg", 1.0)
        self.declare_parameter("sign_tool_b_from_camera_y", 1.0)
        self.declare_parameter("rot_vel_linear", 10.0)
        self.declare_parameter("rot_vel_angular", 5.0)
        self.declare_parameter("rot_acc_linear", 20.0)
        self.declare_parameter("rot_acc_angular", 10.0)

        self.declare_parameter("enable_translation_align", True)
        self.declare_parameter("enable_initial_translation_jump", False)
        self.declare_parameter("initial_translation_jump_axis_mode", "all")
        self.declare_parameter("initial_translation_jump_scale", 1.0)
        self.declare_parameter("initial_translation_jump_max_mm", 120.0)
        self.declare_parameter("enable_coarse_translation_before_rotation", True)
        self.declare_parameter("coarse_axis_mode", "all")
        self.declare_parameter("coarse_translation_scale", 0.5)
        self.declare_parameter("coarse_max_step_mm", 30.0)
        self.declare_parameter("target_distance_m", 0.30)
        self.declare_parameter("tolerance_xy_m", 0.005)
        self.declare_parameter("tolerance_z_m", 0.010)
        self.declare_parameter("max_step_mm", 5.0)
        self.declare_parameter("axis_mode", "largest")
        self.declare_parameter("tool_axis_from_optical_x", "x")
        self.declare_parameter("tool_axis_from_optical_y", "y")
        self.declare_parameter("tool_axis_from_optical_z", "z")
        self.declare_parameter("sign_tool_from_optical_x", -1.0)
        self.declare_parameter("sign_tool_from_optical_y", -1.0)
        self.declare_parameter("sign_tool_from_optical_z", 1.0)
        self.declare_parameter("trans_vel_linear", 15.0)
        self.declare_parameter("trans_vel_angular", 10.0)
        self.declare_parameter("trans_acc_linear", 30.0)
        self.declare_parameter("trans_acc_angular", 20.0)
        self.declare_parameter("recheck_rotation_after_translation", False)

        self.camera_frame = str(self.get_parameter("camera_frame").value)
        self.marker_frame = str(self.get_parameter("marker_frame").value)
        self.marker_frame_prefix = str(self.get_parameter("marker_frame_prefix").value)
        self.target_marker_id = int(self.get_parameter("target_marker_id").value)
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.move_joint_service = str(self.get_parameter("move_joint_service").value)
        self.move_line_service = str(self.get_parameter("move_line_service").value)
        self.current_posx_service = str(self.get_parameter("current_posx_service").value)
        self.dry_run = bool(self.get_parameter("dry_run").value)
        self.current_posx_ref = int(self.get_parameter("current_posx_ref").value)
        self.alignment_payload_json = str(self.get_parameter("alignment_payload_json").value)
        self.save_alignment_payload_on_done = bool(
            self.get_parameter("save_alignment_payload_on_done").value
        )
        self.shelf_frame_parameter = str(self.get_parameter("shelf_frame").value)
        self.shelf_frame = self.shelf_frame_parameter or self.marker_frame
        self.auto_run = bool(self.get_parameter("auto_run").value)
        self.auto_step_period_sec = float(self.get_parameter("auto_step_period_sec").value)
        self.auto_post_motion_wait_sec = float(
            self.get_parameter("auto_post_motion_wait_sec").value
        )
        self.auto_tf_retry_sec = float(self.get_parameter("auto_tf_retry_sec").value)
        self.auto_max_steps = int(self.get_parameter("auto_max_steps").value)
        self.run_post_alignment_pipeline = bool(
            self.get_parameter("run_post_alignment_pipeline").value
        )
        self.post_alignment_target_title = str(
            self.get_parameter("post_alignment_target_title").value
        )
        self.post_alignment_no_display = bool(
            self.get_parameter("post_alignment_no_display").value
        )

        self.enable_movej = bool(self.get_parameter("enable_movej").value)
        self.target_joint_pose_deg = [
            float(value) for value in self.get_parameter("target_joint_pose_deg").value
        ]
        self.movej_vel = float(self.get_parameter("movej_vel").value)
        self.movej_acc = float(self.get_parameter("movej_acc").value)
        self.movej_time = float(self.get_parameter("movej_time").value)
        self.movej_radius = float(self.get_parameter("movej_radius").value)
        self.movej_mode = int(self.get_parameter("movej_mode").value)
        self.movej_blend_type = int(self.get_parameter("movej_blend_type").value)
        self.movej_sync_type = int(self.get_parameter("movej_sync_type").value)

        self.enable_rotation_align = bool(self.get_parameter("enable_rotation_align").value)
        self.rotation_tolerance_deg = float(self.get_parameter("rotation_tolerance_deg").value)
        self.max_rot_step_deg = float(self.get_parameter("max_rot_step_deg").value)
        self.sign_tool_b_from_camera_y = float(
            self.get_parameter("sign_tool_b_from_camera_y").value
        )
        self.rot_vel_linear = float(self.get_parameter("rot_vel_linear").value)
        self.rot_vel_angular = float(self.get_parameter("rot_vel_angular").value)
        self.rot_acc_linear = float(self.get_parameter("rot_acc_linear").value)
        self.rot_acc_angular = float(self.get_parameter("rot_acc_angular").value)

        self.enable_translation_align = bool(self.get_parameter("enable_translation_align").value)
        self.enable_initial_translation_jump = bool(
            self.get_parameter("enable_initial_translation_jump").value
        )
        self.initial_translation_jump_axis_mode = str(
            self.get_parameter("initial_translation_jump_axis_mode").value
        ).lower()
        self.initial_translation_jump_scale = float(
            self.get_parameter("initial_translation_jump_scale").value
        )
        self.initial_translation_jump_max_mm = float(
            self.get_parameter("initial_translation_jump_max_mm").value
        )
        self.enable_coarse_translation_before_rotation = bool(
            self.get_parameter("enable_coarse_translation_before_rotation").value
        )
        self.coarse_axis_mode = str(self.get_parameter("coarse_axis_mode").value).lower()
        self.coarse_translation_scale = float(self.get_parameter("coarse_translation_scale").value)
        self.coarse_max_step_mm = float(self.get_parameter("coarse_max_step_mm").value)  # 신규
        self.target_distance_m = float(self.get_parameter("target_distance_m").value)
        self.tolerance_xy_m = float(self.get_parameter("tolerance_xy_m").value)
        self.tolerance_z_m = float(self.get_parameter("tolerance_z_m").value)
        self.max_step_mm = float(self.get_parameter("max_step_mm").value)
        self.axis_mode = str(self.get_parameter("axis_mode").value).lower()
        self.tool_axis_from_optical_x = str(
            self.get_parameter("tool_axis_from_optical_x").value
        ).lower()
        self.tool_axis_from_optical_y = str(
            self.get_parameter("tool_axis_from_optical_y").value
        ).lower()
        self.tool_axis_from_optical_z = str(
            self.get_parameter("tool_axis_from_optical_z").value
        ).lower()
        self.sign_tool_from_optical_x = float(self.get_parameter("sign_tool_from_optical_x").value)
        self.sign_tool_from_optical_y = float(self.get_parameter("sign_tool_from_optical_y").value)
        self.sign_tool_from_optical_z = float(self.get_parameter("sign_tool_from_optical_z").value)
        self.trans_vel_linear = float(self.get_parameter("trans_vel_linear").value)
        self.trans_vel_angular = float(self.get_parameter("trans_vel_angular").value)
        self.trans_acc_linear = float(self.get_parameter("trans_acc_linear").value)
        self.trans_acc_angular = float(self.get_parameter("trans_acc_angular").value)
        self.recheck_rotation_after_translation = bool(
            self.get_parameter("recheck_rotation_after_translation").value
        )
        self.supported_marker_ids = sorted(MARKER_TARGET_PRESETS)

        self.valid_axis_modes = {"all", "z_only", "x_only", "y_only", "xy_only", "largest"}
        self.valid_tool_axes = {"x", "y", "z"}
        if self.axis_mode not in self.valid_axis_modes:
            raise ValueError(
                f"axis_mode must be one of {sorted(self.valid_axis_modes)}, got '{self.axis_mode}'"
            )
        if self.initial_translation_jump_axis_mode not in self.valid_axis_modes:
            raise ValueError(
                "initial_translation_jump_axis_mode must be one of "
                f"{sorted(self.valid_axis_modes)}, got '{self.initial_translation_jump_axis_mode}'"
            )
        if self.coarse_axis_mode not in self.valid_axis_modes:
            raise ValueError(
                "coarse_axis_mode must be one of "
                f"{sorted(self.valid_axis_modes)}, got '{self.coarse_axis_mode}'"
            )
        self.validate_tool_axis("tool_axis_from_optical_x", self.tool_axis_from_optical_x)
        self.validate_tool_axis("tool_axis_from_optical_y", self.tool_axis_from_optical_y)
        self.validate_tool_axis("tool_axis_from_optical_z", self.tool_axis_from_optical_z)
        if len(self.target_joint_pose_deg) != 6:
            raise ValueError("target_joint_pose_deg must contain exactly 6 joint values")

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.move_joint_client = self.create_client(MoveJoint, self.move_joint_service)
        self.move_line_client = self.create_client(MoveLine, self.move_line_service)
        self.current_posx_client = self.create_client(GetCurrentPosx, self.current_posx_service)
        self.state = "START"
        self.last_action_sent_motion = False
        self.abort_requested = False
        self.post_alignment_pipeline_started = False
        self.apply_initial_marker_selection()

        self.print_config()

    def apply_initial_marker_selection(self):
        if self.target_marker_id >= 0:
            self.apply_marker_selection(self.target_marker_id, announce=False)
            return

        inferred_marker_id = self.parse_marker_id(self.marker_frame)
        if inferred_marker_id in self.supported_marker_ids:
            self.apply_marker_selection(inferred_marker_id, announce=False)

    def parse_marker_id(self, value):
        text = str(value).strip()
        if text.isdigit():
            return int(text)
        if text.startswith(self.marker_frame_prefix):
            suffix = text[len(self.marker_frame_prefix):]
            if suffix.isdigit():
                return int(suffix)
        return None

    def apply_marker_selection(self, marker_id, announce=True):
        marker_id = int(marker_id)
        if marker_id not in self.supported_marker_ids:
            raise ValueError(
                f"Unsupported marker id {marker_id}. Supported ids: {self.supported_marker_ids}"
            )

        self.target_marker_id = marker_id
        self.marker_frame = f"{self.marker_frame_prefix}{marker_id}"
        self.target_joint_pose_deg = [float(value) for value in MARKER_TARGET_PRESETS[marker_id]]
        if not self.shelf_frame_parameter:
            self.shelf_frame = self.marker_frame

        if announce:
            self.log_info(
                "\n"
                f"Selected ArUco marker id={self.target_marker_id}\n"
                f"  marker_frame={self.marker_frame}\n"
                f"  target_joint_pose_deg={self.target_joint_pose_deg}"
            )

    def reset_alignment_state(self, reason):
        self.state = "START"
        self.last_action_sent_motion = False
        self.abort_requested = False
        self.get_logger().warn(f"{reason} Alignment state reset to START.")

    def print_config(self):
        if self.auto_run:
            self.get_logger().warn(
                "auto_run=true: the node will advance slowly without pressing Enter."
            )
        else:
            self.get_logger().warn(
                "Prototype alignment: Enter sends at most one action. There is no automatic loop."
            )
        if self.dry_run:
            self.get_logger().warn("dry_run=true: MoveJ and MoveLine requests will be printed only.")
        else:
            self.get_logger().error("dry_run=false: Enter may move the real robot.")
        self.log_info(
            "\n"
            "Configuration\n"
            f"  camera_frame={self.camera_frame}, marker_frame={self.marker_frame}, "
            f"marker_frame_prefix={self.marker_frame_prefix}, "
            f"target_marker_id={self.target_marker_id}\n"
            f"  supported_marker_ids={self.supported_marker_ids}, "
            f"base_frame={self.base_frame}\n"
            f"  alignment_payload_json={self.alignment_payload_json}, "
            f"save_alignment_payload_on_done={self.save_alignment_payload_on_done}\n"
            f"  current_posx_service={self.current_posx_service}, "
            f"current_posx_ref={self.current_posx_ref}\n"
            f"  auto_run={self.auto_run}, "
            f"auto_step_period_sec={self.auto_step_period_sec:.3f}, "
            f"auto_post_motion_wait_sec={self.auto_post_motion_wait_sec:.3f}, "
            f"auto_tf_retry_sec={self.auto_tf_retry_sec:.3f}, "
            f"auto_max_steps={self.auto_max_steps}\n"
            f"  run_post_alignment_pipeline={self.run_post_alignment_pipeline}, "
            f"post_alignment_target_title={self.post_alignment_target_title}, "
            f"post_alignment_no_display={self.post_alignment_no_display}\n"
            f"  enable_movej={self.enable_movej}, target_joint_pose_deg={self.target_joint_pose_deg}\n"
            f"  enable_rotation_align={self.enable_rotation_align}, "
            f"rotation_tolerance_deg={self.rotation_tolerance_deg:.3f}, "
            f"max_rot_step_deg={self.max_rot_step_deg:.3f}, "
            f"sign_tool_b_from_camera_y={self.sign_tool_b_from_camera_y:.1f}\n"
            f"  speed: movej_vel={self.movej_vel:.1f}, movej_acc={self.movej_acc:.1f}, "
            f"trans_vel_linear={self.trans_vel_linear:.1f}, trans_acc_linear={self.trans_acc_linear:.1f}, "
            f"rot_vel_linear={self.rot_vel_linear:.1f}, rot_vel_angular={self.rot_vel_angular:.1f}\n"
            f"  enable_translation_align={self.enable_translation_align}, "
            f"enable_initial_translation_jump={self.enable_initial_translation_jump}, "
            f"initial_translation_jump_axis_mode={self.initial_translation_jump_axis_mode}, "
            f"initial_translation_jump_scale={self.initial_translation_jump_scale:.3f}, "
            f"initial_translation_jump_max_mm={self.initial_translation_jump_max_mm:.1f}\n"
            f"enable_coarse_translation_before_rotation="
            f"{self.enable_coarse_translation_before_rotation}, "
            f"coarse_axis_mode={self.coarse_axis_mode}, "
            f"coarse_translation_scale={self.coarse_translation_scale:.3f}\n"
            f"  coarse_max_step_mm={self.coarse_max_step_mm:.1f} [coarse], "
            f"max_step_mm={self.max_step_mm:.1f} [fine], "
            f"axis_mode={self.axis_mode}, target_distance_m={self.target_distance_m:.3f}\n"
            "  translation mapping: "
            f"optical X -> tool {self.tool_axis_from_optical_x.upper()} "
            f"sign={self.sign_tool_from_optical_x:.1f}, "
            f"optical Y -> tool {self.tool_axis_from_optical_y.upper()} "
            f"sign={self.sign_tool_from_optical_y:.1f}, "
            f"optical Z -> tool {self.tool_axis_from_optical_z.upper()} "
            f"sign={self.sign_tool_from_optical_z:.1f}\n"
            "  rotation direction hint: If rotation oscillates, try: "
            "-p sign_tool_b_from_camera_y:=-1.0"
        )

    def log_info(self, message):
        logger = self.get_logger()
        if hasattr(logger, "info"):
            logger.info(message)
        elif hasattr(logger, "dinfo"):
            logger.dinfo(message)
        else:
            logger.warn(message)

    def handle_enter(self):
        self.last_action_sent_motion = False
        if self.abort_requested:
            self.get_logger().error("Alignment is aborted. Restart the node after fixing the error.")
            return
        if self.state == "START":
            self.log_info("START -> MOVEJ_READY")
            self.state = "MOVEJ_READY"
            return
        if self.state == "MOVEJ_READY":
            self.run_movej_step()
            self.state = "WAIT_AFTER_MOVEJ"
            return
        if self.state == "WAIT_AFTER_MOVEJ":
            if self.enable_initial_translation_jump and self.enable_translation_align:
                self.log_info("Starting one-shot initial translation jump before fine alignment.")
                self.state = "INITIAL_TRANSLATION_JUMP"
            elif self.enable_coarse_translation_before_rotation and self.enable_translation_align:
                self.log_info("Starting coarse translation before rotation.")
                self.state = "COARSE_TRANSLATION_ALIGN"
            else:
                self.log_info("Starting rotation alignment.")
                self.state = "ROTATION_ALIGN"
            return
        if self.state == "INITIAL_TRANSLATION_JUMP":
            self.run_translation_step(
                translation_scale=self.initial_translation_jump_scale,
                next_state_when_aligned="WAIT_AFTER_INITIAL_TRANSLATION_JUMP",
                next_state_after_step="WAIT_AFTER_INITIAL_TRANSLATION_JUMP",
                label="initial translation jump",
                axis_mode=self.initial_translation_jump_axis_mode,
            )
            return
        if self.state == "WAIT_AFTER_INITIAL_TRANSLATION_JUMP":
            if self.enable_coarse_translation_before_rotation and self.enable_translation_align:
                self.log_info("Starting coarse translation after initial jump.")
                self.state = "COARSE_TRANSLATION_ALIGN"
            else:
                self.log_info("Starting rotation alignment after initial jump.")
                self.state = "ROTATION_ALIGN"
            return
        if self.state == "COARSE_TRANSLATION_ALIGN":
            self.run_translation_step(
                translation_scale=self.coarse_translation_scale,
                next_state_when_aligned="WAIT_AFTER_COARSE_TRANSLATION",
                next_state_after_step="WAIT_AFTER_COARSE_TRANSLATION",
                label="coarse translation",
                axis_mode=self.coarse_axis_mode,
            )
            return
        if self.state == "WAIT_AFTER_COARSE_TRANSLATION":
            self.log_info("Starting rotation alignment.")
            self.state = "ROTATION_ALIGN"
            return
        if self.state == "ROTATION_ALIGN":
            self.run_rotation_step()
            return
        if self.state == "WAIT_AFTER_ROTATION":
            self.log_info("Starting translation step alignment.")
            self.state = "TRANSLATION_ALIGN"
            return
        if self.state == "TRANSLATION_ALIGN":
            self.run_translation_step(
                translation_scale=1.0,
                next_state_when_aligned=(
                    "ROTATION_ALIGN"
                    if self.recheck_rotation_after_translation and self.enable_rotation_align
                    else "DONE"
                ),
                next_state_after_step="TRANSLATION_ALIGN",
                label="fine translation",
                axis_mode=self.axis_mode,
            )
            return
        if self.state == "DONE":
            self.log_info("Alignment is already DONE. Press q or Enter at the prompt to exit.")
            return

        self.get_logger().error(f"Unknown state: {self.state}")

    def handle_command(self, command):
        marker_id = self.parse_marker_id(command)
        if marker_id is not None:
            if marker_id not in self.supported_marker_ids:
                self.get_logger().warn(
                    f"Unsupported marker id {marker_id}. Supported ids: {self.supported_marker_ids}"
                )
                return True
            self.apply_marker_selection(marker_id)
            self.reset_alignment_state(f"Marker changed to id={marker_id}.")
            return True
        if command == "next" and self.state == "ROTATION_ALIGN":
            self.get_logger().warn("Forced transition: ROTATION_ALIGN -> WAIT_AFTER_ROTATION")
            self.state = "WAIT_AFTER_ROTATION"
            return True
        if command == "rot" and self.state == "TRANSLATION_ALIGN":
            self.get_logger().warn("Manual transition: TRANSLATION_ALIGN -> ROTATION_ALIGN")
            self.state = "ROTATION_ALIGN"
            return True
        if command == "done" and self.state == "TRANSLATION_ALIGN":
            self.get_logger().warn("Manual transition: TRANSLATION_ALIGN -> DONE")
            self.enter_done_state()
            return True
        return False

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

    def run_rotation_step(self):
        if not self.enable_rotation_align:
            self.log_info("Rotation alignment skipped because enable_rotation_align=false.")
            self.state = "WAIT_AFTER_ROTATION"
            return

        marker_z = self.lookup_marker_z_axis()
        if marker_z is None:
            return

        angle_y_deg = self.compute_angle_y_deg(marker_z)
        self.log_info(
            "\n"
            f"Rotation state in {self.camera_frame}\n"
            f"  marker_z_in_camera: x={marker_z[0]:.6f}, "
            f"y={marker_z[1]:.6f}, z={marker_z[2]:.6f}\n"
            f"  angle_y_deg={angle_y_deg:.3f}\n"
            f"  sign_tool_b_from_camera_y={self.sign_tool_b_from_camera_y:.1f}\n"
            f"  max_rot_step_deg={self.max_rot_step_deg:.3f}\n"
            f"  rotation_tolerance_deg={self.rotation_tolerance_deg:.3f}"
        )

        if abs(angle_y_deg) < self.rotation_tolerance_deg:
            self.log_info("rotation aligned. ROTATION_ALIGN -> WAIT_AFTER_ROTATION")
            self.state = "WAIT_AFTER_ROTATION"
            return

        raw_step_deg = self.sign_tool_b_from_camera_y * angle_y_deg
        move_b_deg = self.clamp(raw_step_deg, self.max_rot_step_deg)
        request = MoveLine.Request()
        request.pos = [0.0, 0.0, 0.0, 0.0, move_b_deg, 0.0]
        request.vel = [self.rot_vel_linear, self.rot_vel_angular]
        request.acc = [self.rot_acc_linear, self.rot_acc_angular]
        self.fill_moveline_common(request)
        self.print_rotation_request(request, angle_y_deg, raw_step_deg, move_b_deg)

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

    def run_translation_step(
        self,
        translation_scale,
        next_state_when_aligned,
        next_state_after_step,
        label,
        axis_mode,
    ):
        if not self.enable_translation_align:
            self.log_info("Translation alignment skipped because enable_translation_align=false.")
            self.state = next_state_when_aligned
            return

        # label에 따라 initial/coarse/fine max_step_mm 선택
        if label == "initial translation jump":
            active_max_step_mm = self.initial_translation_jump_max_mm
            step_kind = "initial"
        elif label == "coarse translation":
            active_max_step_mm = self.coarse_max_step_mm
            step_kind = "coarse"
        else:  # "fine translation"
            active_max_step_mm = self.max_step_mm
            step_kind = "fine"

        position = self.lookup_marker_translation()
        if position is None:
            return

        current_x, current_y, current_z = position
        error_x = current_x
        error_y = current_y
        error_z = current_z - self.target_distance_m
        self.log_info(
            "\n"
            f"{label.title()} state in {self.camera_frame} [m]\n"
            f"  x={current_x:.6f}, y={current_y:.6f}, z={current_z:.6f}\n"
            f"  target_distance_m={self.target_distance_m:.6f}\n"
            f"  error [m]: x={error_x:.6f}, y={error_y:.6f}, z={error_z:.6f}\n"
            f"  normalized error: x={self.normalized_error(error_x, self.tolerance_xy_m):.3f}, "
            f"y={self.normalized_error(error_y, self.tolerance_xy_m):.3f}, "
            f"z={self.normalized_error(error_z, self.tolerance_z_m):.3f}\n"
            f"  axis_mode={axis_mode}, translation_scale={translation_scale:.3f}\n"
            f"  max_step_mm={active_max_step_mm:.1f} [{step_kind}]"  # coarse/fine 표시
        )

        if self.translation_aligned(error_x, error_y, error_z):
            self.log_info(f"{label} aligned.")
            if next_state_when_aligned == "DONE":
                self.enter_done_state()
            else:
                self.state = next_state_when_aligned
            return

        move_tool_x_mm, move_tool_y_mm, move_tool_z_mm, active_axes = (
            self.compute_translation_step(
                error_x,
                error_y,
                error_z,
                translation_scale,
                axis_mode,
                active_max_step_mm,  # coarse/fine 구분된 한계값 전달
            )
        )
        request = MoveLine.Request()
        request.pos = [move_tool_x_mm, move_tool_y_mm, move_tool_z_mm, 0.0, 0.0, 0.0]
        request.vel = [self.trans_vel_linear, self.trans_vel_angular]
        request.acc = [self.trans_acc_linear, self.trans_acc_angular]
        self.fill_moveline_common(request)
        self.print_translation_request(request, active_axes, translation_scale, label)

        if self.dry_run:
            self.get_logger().warn("dry_run=true: skipped move_line service call.")
            self.last_action_sent_motion = True
            self.state = next_state_after_step
            return

        if self.call_service(self.move_line_client, self.move_line_service, request, "MoveLine"):
            self.last_action_sent_motion = True
            self.state = next_state_after_step

    def lookup_marker_transform(self):
        try:
            return self.tf_buffer.lookup_transform(
                self.camera_frame,
                self.marker_frame,
                rclpy.time.Time(),
                timeout=Duration(seconds=0.5),
            )
        except TransformException as exc:
            self.get_logger().warn(
                f"TF lookup failed; no movement will be sent: "
                f"{self.camera_frame} -> {self.marker_frame}: {exc}"
            )
            return None

    def lookup_marker_z_axis(self):
        transform = self.lookup_marker_transform()
        if transform is None:
            return None
        rotation = transform.transform.rotation
        matrix = self.quaternion_to_matrix(rotation.x, rotation.y, rotation.z, rotation.w)
        return (matrix[0][2], matrix[1][2], matrix[2][2])

    def lookup_marker_pose(self):
        transform = self.lookup_marker_transform()
        if transform is None:
            return None

        translation = transform.transform.translation
        rotation = transform.transform.rotation
        matrix = self.quaternion_to_matrix(rotation.x, rotation.y, rotation.z, rotation.w)
        marker_normal = (matrix[0][2], matrix[1][2], matrix[2][2])
        return translation, marker_normal

    def lookup_marker_translation(self):
        transform = self.lookup_marker_transform()
        if transform is None:
            return None
        translation = transform.transform.translation
        return (translation.x, translation.y, translation.z)

    def compute_translation_step(
        self, error_x, error_y, error_z, translation_scale, axis_mode, max_step_mm
    ):
        """
        max_step_mm: 호출 측에서 coarse/fine 구분하여 전달.
          - coarse translation -> self.coarse_max_step_mm (기본 30.0 mm)
          - fine   translation -> self.max_step_mm        (기본  5.0 mm)
        """
        selected_axes = self.selected_optical_axes(error_x, error_y, error_z, axis_mode)
        scale = self.clamp_scalar(translation_scale, 0.0, 1.0)
        move_by_tool_axis = {"x": 0.0, "y": 0.0, "z": 0.0}
        corrections = {
            "optical_x": (
                self.tool_axis_from_optical_x,
                self.sign_tool_from_optical_x * error_x * 1000.0 * scale,
            ),
            "optical_y": (
                self.tool_axis_from_optical_y,
                self.sign_tool_from_optical_y * error_y * 1000.0 * scale,
            ),
            "optical_z": (
                self.tool_axis_from_optical_z,
                self.sign_tool_from_optical_z * error_z * 1000.0 * scale,
            ),
        }

        active_axes = []
        for optical_axis in selected_axes:
            tool_axis, correction_mm = corrections[optical_axis]
            move_by_tool_axis[tool_axis] += correction_mm
            active_axes.append(f"{optical_axis}->tool_{tool_axis}")

        return (
            self.clamp(move_by_tool_axis["x"], max_step_mm),
            self.clamp(move_by_tool_axis["y"], max_step_mm),
            self.clamp(move_by_tool_axis["z"], max_step_mm),
            active_axes,
        )

    def selected_optical_axes(self, error_x, error_y, error_z, axis_mode):
        if axis_mode == "all":
            return ["optical_x", "optical_y", "optical_z"]
        if axis_mode == "z_only":
            return ["optical_z"]
        if axis_mode == "x_only":
            return ["optical_x"]
        if axis_mode == "y_only":
            return ["optical_y"]
        if axis_mode == "xy_only":
            return ["optical_x", "optical_y"]

        normalized_errors = {
            "optical_x": abs(error_x) / self.tolerance_xy_m if self.tolerance_xy_m > 0.0 else 0.0,
            "optical_y": abs(error_y) / self.tolerance_xy_m if self.tolerance_xy_m > 0.0 else 0.0,
            "optical_z": abs(error_z) / self.tolerance_z_m if self.tolerance_z_m > 0.0 else 0.0,
        }
        return [max(normalized_errors, key=normalized_errors.get)]

    def translation_aligned(self, error_x, error_y, error_z):
        return (
            abs(error_x) < self.tolerance_xy_m
            and abs(error_y) < self.tolerance_xy_m
            and abs(error_z) < self.tolerance_z_m
        )

    def print_final_state(self):
        position = self.lookup_marker_translation()
        marker_z = self.lookup_marker_z_axis()
        if position is None or marker_z is None:
            self.get_logger().warn("DONE: final TF is not available.")
            return
        error_x = position[0]
        error_y = position[1]
        error_z = position[2] - self.target_distance_m
        angle_y_deg = self.compute_angle_y_deg(marker_z)
        self.log_info(
            "\n"
            "DONE final state\n"
            f"  camera->marker [m]: x={position[0]:.6f}, y={position[1]:.6f}, z={position[2]:.6f}\n"
            f"  angle_y_deg={angle_y_deg:.3f}\n"
            f"  rotation_aligned={abs(angle_y_deg) < self.rotation_tolerance_deg}\n"
            f"  translation_aligned={self.translation_aligned(error_x, error_y, error_z)}"
        )

    def enter_done_state(self):
        self.state = "DONE"
        self.print_final_state()
        self.save_alignment_payload()
        self.run_post_alignment_pipeline_if_needed()

    def run_post_alignment_pipeline_if_needed(self):
        if not self.run_post_alignment_pipeline:
            return
        if self.post_alignment_pipeline_started:
            return

        command = [
            "ros2",
            "run",
            "doosan_realsense_handeye",
            "marker_book_pipeline",
            "--alignment-payload-json",
            self.alignment_payload_json,
            "--target-title",
            self.post_alignment_target_title,
        ]
        if self.dry_run:
            command.append("--dry-run")
        if self.post_alignment_no_display:
            command.append("--no-display")

        self.post_alignment_pipeline_started = True
        self.get_logger().warn(
            "Starting post-alignment pipeline:\n"
            f"  {' '.join(command)}"
        )
        try:
            subprocess.run(command, check=True)
            self.log_info("Post-alignment pipeline completed successfully.")
        except (OSError, subprocess.CalledProcessError) as exc:
            self.get_logger().error(f"Post-alignment pipeline failed: {exc}")

    def save_alignment_payload(self):
        if not self.save_alignment_payload_on_done:
            return

        pose = self.lookup_marker_pose()
        if pose is None:
            self.get_logger().warn("Alignment payload was not saved because marker TF is not available.")
            return

        aligned_tcp_pose = self.read_current_tcp_posx()
        if aligned_tcp_pose is None:
            self.get_logger().warn(
                "Alignment payload was not saved because current TCP pose could not be read."
            )
            return

        translation, marker_normal_camera = pose
        front_direction_base = self.transform_vector_camera_to_base(marker_normal_camera)
        marker_position_base = self.transform_point_camera_to_base(
            (translation.x, translation.y, translation.z)
        )

        if front_direction_base is None:
            self.get_logger().warn(
                "Alignment payload was not saved because marker normal could not be transformed "
                f"from {self.camera_frame} to {self.base_frame}."
            )
            return

        payload = {
            "timestamp": datetime.now().isoformat(),
            "aligned": True,
            "base_frame": self.base_frame,
            "camera_frame": self.camera_frame,
            "marker_frame": self.marker_frame,
            "target_marker_id": self.target_marker_id,
            "scan_tool_y_offset_mm": MARKER_SCAN_TOOL_Y_OFFSETS_MM.get(
                self.target_marker_id,
                0.0,
            ),
            "shelf_frame": self.shelf_frame,
            "bookshelf_front_direction_base": [
                round(float(value), 6) for value in front_direction_base
            ],
            "marker_translation_camera_m": [
                round(float(translation.x), 6),
                round(float(translation.y), 6),
                round(float(translation.z), 6),
            ],
            "marker_position_base_m": marker_position_base,
            "aligned_tcp_pose": [round(float(value), 3) for value in aligned_tcp_pose],
            "source": "aruco_marker_proto_align",
        }

        os.makedirs(os.path.dirname(self.alignment_payload_json) or ".", exist_ok=True)
        with open(self.alignment_payload_json, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)

        self.log_info(
            f"Alignment payload saved: {self.alignment_payload_json}\n"
            f"  aligned_tcp_pose={payload['aligned_tcp_pose']}\n"
            f"  bookshelf_front_direction_base={payload['bookshelf_front_direction_base']}"
        )

    def read_current_tcp_posx(self):
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

    def transform_point_camera_to_base(self, xyz_camera):
        try:
            transform = self.tf_buffer.lookup_transform(
                self.base_frame,
                self.camera_frame,
                rclpy.time.Time(),
                timeout=Duration(seconds=0.5),
            )
        except TransformException:
            return None

        rotation = transform.transform.rotation
        matrix = self.quaternion_to_matrix(rotation.x, rotation.y, rotation.z, rotation.w)
        translated = transform.transform.translation
        rotated = self.multiply_matrix_vector(matrix, xyz_camera)
        return [
            round(float(rotated[0] + translated.x), 6),
            round(float(rotated[1] + translated.y), 6),
            round(float(rotated[2] + translated.z), 6),
        ]

    def transform_vector_camera_to_base(self, vector_camera):
        try:
            transform = self.tf_buffer.lookup_transform(
                self.base_frame,
                self.camera_frame,
                rclpy.time.Time(),
                timeout=Duration(seconds=0.5),
            )
        except TransformException as exc:
            self.get_logger().warn(
                f"TF lookup failed for vector transform: "
                f"{self.base_frame} -> {self.camera_frame}: {exc}"
            )
            return None

        rotation = transform.transform.rotation
        matrix = self.quaternion_to_matrix(rotation.x, rotation.y, rotation.z, rotation.w)
        return self.normalize(self.multiply_matrix_vector(matrix, vector_camera))

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

        detail_fields = []
        for attr in ("message", "msg", "error", "ext_result"):
            if hasattr(response, attr):
                value = getattr(response, attr)
                if value not in (None, "", [], (), {}):
                    detail_fields.append(f"{attr}={value}")
        if detail_fields:
            self.get_logger().error(
                f"{label} service returned success=false ({', '.join(detail_fields)})"
            )
        else:
            self.get_logger().error(f"{label} service returned success=false")
        return False

    def print_movej_request(self, request):
        self.log_info(
            "\n"
            "Computed MoveJoint request\n"
            f"  pos [deg]: {self.format_list(request.pos)}\n"
            f"  vel={request.vel:.3f}, acc={request.acc:.3f}, "
            f"time={request.time:.3f}, radius={request.radius:.3f}, "
            f"mode={request.mode}, blend_type={request.blend_type}, sync_type={request.sync_type}"
        )

    def print_rotation_request(self, request, angle_y_deg, raw_step_deg, move_b_deg):
        self.log_info(
            "\n"
            "Computed rotation MoveLine request\n"
            f"  angle_y_deg={angle_y_deg:.3f}\n"
            f"  sign_tool_b_from_camera_y={self.sign_tool_b_from_camera_y:.1f}\n"
            f"  raw_step_deg={raw_step_deg:.3f}, move_b_deg={move_b_deg:.3f}\n"
            f"  max_rot_step_deg={self.max_rot_step_deg:.3f}\n"
            f"  rotation_tolerance_deg={self.rotation_tolerance_deg:.3f}\n"
            "  oscillation hint: If rotation oscillates, try: "
            "-p sign_tool_b_from_camera_y:=-1.0\n"
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
            f"  active_axes={active_axes}\n"
            f"  translation_scale={translation_scale:.3f}\n"
            "  mapping:\n"
            f"    optical X -> tool {self.tool_axis_from_optical_x.upper()} "
            f"sign={self.sign_tool_from_optical_x:.1f}\n"
            f"    optical Y -> tool {self.tool_axis_from_optical_y.upper()} "
            f"sign={self.sign_tool_from_optical_y:.1f}\n"
            f"    optical Z -> tool {self.tool_axis_from_optical_z.upper()} "
            f"sign={self.sign_tool_from_optical_z:.1f}\n"
            f"  pos [mm,deg]: {self.format_list(request.pos)}\n"
            f"  vel: {self.format_list(request.vel)}\n"
            f"  acc: {self.format_list(request.acc)}\n"
            f"  time={request.time:.3f}, radius={request.radius:.3f}, "
            f"ref={request.ref}, mode={request.mode}, "
            f"blend_type={request.blend_type}, sync_type={request.sync_type}"
        )

    @staticmethod
    def compute_angle_y_deg(marker_z):
        return math.degrees(math.atan2(marker_z[0], -marker_z[2]))

    @staticmethod
    def quaternion_to_matrix(x, y, z, w):
        norm = math.sqrt(x * x + y * y + z * z + w * w)
        if norm == 0.0:
            raise ValueError("zero-length quaternion")
        x /= norm
        y /= norm
        z /= norm
        w /= norm

        return [
            [
                1.0 - 2.0 * (y * y + z * z),
                2.0 * (x * y - z * w),
                2.0 * (x * z + y * w),
            ],
            [
                2.0 * (x * y + z * w),
                1.0 - 2.0 * (x * x + z * z),
                2.0 * (y * z - x * w),
            ],
            [
                2.0 * (x * z - y * w),
                2.0 * (y * z + x * w),
                1.0 - 2.0 * (x * x + y * y),
            ],
        ]

    @staticmethod
    def normalize(vector):
        norm = math.sqrt(sum(float(value) * float(value) for value in vector))
        if norm == 0.0:
            raise ValueError("vector norm must be non-zero")
        return tuple(float(value) / norm for value in vector)

    @staticmethod
    def multiply_matrix_vector(matrix, vector):
        return tuple(
            sum(matrix[row][col] * vector[col] for col in range(3))
            for row in range(3)
        )

    @staticmethod
    def clamp(value, max_abs):
        if max_abs <= 0.0:
            return 0.0
        return max(-max_abs, min(max_abs, value))

    def validate_tool_axis(self, parameter_name, axis):
        if axis not in self.valid_tool_axes:
            raise ValueError(
                f"{parameter_name} must be one of {sorted(self.valid_tool_axes)}, got '{axis}'"
            )

    @staticmethod
    def normalized_error(error, tolerance):
        if tolerance <= 0.0:
            return 0.0
        return abs(error) / tolerance

    @staticmethod
    def clamp_scalar(value, lower, upper):
        return max(lower, min(upper, value))

    @staticmethod
    def format_list(values):
        return "[" + ", ".join(f"{value:.3f}" for value in values) + "]"


def input_loop(node):
    print(
        "Press Enter for one state action, 0 or 1 to select the ArUco marker, q to quit, "
        "next in ROTATION_ALIGN, rot/done in TRANSLATION_ALIGN"
    )
    while rclpy.ok():
        try:
            command = input(f"[{node.state}]> ").strip().lower()
        except EOFError:
            break
        except KeyboardInterrupt:
            raise

        if command == "q":
            break
        if command:
            if not node.handle_command(command):
                print("Valid commands: Enter, 0, 1, q, next, rot, done")
            continue

        if node.state == "DONE":
            break

        node.handle_enter()


def sleep_while_ok(duration_sec):
    end_time = time.monotonic() + max(0.0, float(duration_sec))
    while rclpy.ok() and time.monotonic() < end_time:
        time.sleep(min(0.1, end_time - time.monotonic()))


def auto_loop(node):
    print(
        "AUTO RUN: the node advances by itself. Press Ctrl-C to stop immediately."
    )
    step_count = 0
    while rclpy.ok() and node.state != "DONE" and not node.abort_requested:
        if node.auto_max_steps > 0 and step_count >= node.auto_max_steps:
            node.get_logger().warn(
                f"auto_max_steps={node.auto_max_steps} reached; stopping auto loop."
            )
            break

        previous_state = node.state
        node.handle_enter()
        step_count += 1

        if node.state == "DONE":
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


def prompt_for_marker_selection(node):
    if node.target_marker_id in node.supported_marker_ids:
        return True

    print(f"Select ArUco marker id to align {node.supported_marker_ids} (q to quit)")
    while rclpy.ok():
        try:
            command = input("marker id> ").strip().lower()
        except EOFError:
            return False
        except KeyboardInterrupt:
            raise

        if command == "q":
            return False
        if not command:
            continue
        marker_id = node.parse_marker_id(command)
        if marker_id in node.supported_marker_ids:
            node.apply_marker_selection(marker_id)
            node.reset_alignment_state(f"Marker changed to id={marker_id}.")
            node.print_config()
            return True
        print(f"Supported marker ids: {node.supported_marker_ids}")


def main(args=None):
    rclpy.init(args=args)
    node = ArucoMarkerProtoAlign()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    try:
        if not prompt_for_marker_selection(node):
            return
        if node.auto_run:
            auto_loop(node)
        else:
            input_loop(node)
    except KeyboardInterrupt:
        node.get_logger().warn("Interrupted; exiting without sending another movement.")
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        spin_thread.join(timeout=1.0)


if __name__ == "__main__":
    main()
