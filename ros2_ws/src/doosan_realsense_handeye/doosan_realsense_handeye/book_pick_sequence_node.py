#!/usr/bin/env python3
"""
Standalone pick sequence node.

Dry run:
ros2 run doosan_realsense_handeye book_pick_sequence_node --ros-args \
  -p dry_run:=true \
  -p enable_gripper_control:=true \
  -p pick_axis:=z \
  -p pick_axis_sign:=1.0 \
  -p insert1_mm:=310.0 \
  -p pull1_mm:=310.0 \
  -p insert2_mm:=360.0 \
  -p pull_final_mm:=360.0 \
  -p pick_step_max_mm:=10.0 \
  -p gripper_soft_grip_position:=650 \
  -p gripper_hard_grip_position:=660 \
  -p pick_vel_linear:=60.0 \
  -p pick_acc_linear:=120.0 \
  -p return_to_start_pose:=true \
  -p gripper_timeout_sec:=10.0

Real run:
ros2 run doosan_realsense_handeye book_pick_sequence_node --ros-args \
  -p dry_run:=false \
  -p enable_gripper_control:=true \
  -p pick_axis:=z \
  -p pick_axis_sign:=1.0 \
  -p insert1_mm:=310.0 \
  -p pull1_mm:=310.0 \
  -p insert2_mm:=360.0 \
  -p pull_final_mm:=360.0 \
  -p pick_step_max_mm:=10.0 \
  -p gripper_soft_grip_position:=650 \
  -p gripper_hard_grip_position:=660 \
  -p pick_vel_linear:=60.0 \
  -p pick_acc_linear:=120.0 \
  -p return_to_start_pose:=true \
  -p gripper_timeout_sec:=10.0
"""

import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime

import rclpy
from dsr_msgs2.srv import GetCurrentPosx, MoveJoint, MoveLine
from rclpy.node import Node

from .book_pick_sequence import (
    BookPickSequenceConfig,
    BookPickSequenceExecutor,
    GetState,
    SetPosition,
    SetTorque,
)


DEFAULT_OUTPUT_JSON = "realtime_results/book_pick_sequence_payload.json"


def clamp(value, max_abs):
    if max_abs <= 0.0:
        return 0.0
    return max(-max_abs, min(max_abs, float(value)))


class BookPickSequenceNode(Node):
    def __init__(self):
        super().__init__("book_pick_sequence_node")

        self.declare_parameter("dry_run", True)
        self.declare_parameter("enable_gripper_control", False)
        self.declare_parameter("move_line_service", "/dsr01/motion/move_line")
        self.declare_parameter("move_joint_service", "/dsr01/motion/move_joint")
        self.declare_parameter("current_posx_service", "/dsr01/aux_control/get_current_posx")
        self.declare_parameter("current_posx_ref", 0)
        self.declare_parameter("gripper_state_service", "/gripper_service/get_state")
        self.declare_parameter("gripper_set_torque_service", "/gripper_service/set_torque")
        self.declare_parameter("gripper_set_position_service", "/gripper_service/set_position")
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
        self.declare_parameter("return_to_start_pose", True)
        self.declare_parameter("return_vel_linear", 20.0)
        self.declare_parameter("return_vel_angular", 10.0)
        self.declare_parameter("return_acc_linear", 40.0)
        self.declare_parameter("return_acc_angular", 20.0)
        self.declare_parameter("enable_place_to_box", False)
        self.declare_parameter("box_joint_pose_deg", [0.0, 0.0, 90.0, 0.0, 90.0, 0.0])
        self.declare_parameter("box_movej_vel", 30.0)
        self.declare_parameter("box_movej_acc", 60.0)
        self.declare_parameter("place_drop_distance_mm", 150.0)
        self.declare_parameter("output_json", DEFAULT_OUTPUT_JSON)
        self.declare_parameter("auto_run", True)

        self.dry_run = bool(self.get_parameter("dry_run").value)
        self.enable_gripper_control = bool(self.get_parameter("enable_gripper_control").value)
        self.move_line_service = str(self.get_parameter("move_line_service").value)
        self.move_joint_service = str(self.get_parameter("move_joint_service").value)
        self.current_posx_service = str(self.get_parameter("current_posx_service").value)
        self.current_posx_ref = int(self.get_parameter("current_posx_ref").value)
        self.gripper_state_service = str(self.get_parameter("gripper_state_service").value)
        self.gripper_set_torque_service = str(self.get_parameter("gripper_set_torque_service").value)
        self.gripper_set_position_service = str(
            self.get_parameter("gripper_set_position_service").value
        )
        self.gripper_open_position = int(self.get_parameter("gripper_open_position").value)
        self.gripper_open_position_2 = int(
            self.get_parameter("gripper_open_position_2").value
        )
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
        self.return_to_start_pose = bool(self.get_parameter("return_to_start_pose").value)
        self.return_vel_linear = float(self.get_parameter("return_vel_linear").value)
        self.return_vel_angular = float(self.get_parameter("return_vel_angular").value)
        self.return_acc_linear = float(self.get_parameter("return_acc_linear").value)
        self.return_acc_angular = float(self.get_parameter("return_acc_angular").value)
        self.enable_place_to_box = bool(self.get_parameter("enable_place_to_box").value)
        self.box_joint_pose_deg = [
            float(v) for v in self.get_parameter("box_joint_pose_deg").value
        ]
        self.box_movej_vel = float(self.get_parameter("box_movej_vel").value)
        self.box_movej_acc = float(self.get_parameter("box_movej_acc").value)
        self.place_drop_distance_mm = float(self.get_parameter("place_drop_distance_mm").value)
        self.output_json = str(self.get_parameter("output_json").value)
        self.auto_run = bool(self.get_parameter("auto_run").value)

        self.valid_pick_axes = {"x", "y", "z"}
        if self.pick_axis not in self.valid_pick_axes:
            raise ValueError(
                f"pick_axis must be one of {sorted(self.valid_pick_axes)}, got '{self.pick_axis}'"
            )

        if len(self.box_joint_pose_deg) != 6:
            raise ValueError("box_joint_pose_deg must contain exactly 6 joint values")

        self.move_joint_client = self.create_client(MoveJoint, self.move_joint_service)
        self.move_line_client = self.create_client(MoveLine, self.move_line_service)
        self.current_posx_client = self.create_client(GetCurrentPosx, self.current_posx_service)
        self.gripper_state_client = None
        self.gripper_set_torque_client = None
        self.gripper_set_position_client = None
        if GetState is not None:
            self.gripper_state_client = self.create_client(GetState, self.gripper_state_service)
        if SetTorque is not None:
            self.gripper_set_torque_client = self.create_client(
                SetTorque, self.gripper_set_torque_service
            )
        if SetPosition is not None:
            self.gripper_set_position_client = self.create_client(
                SetPosition, self.gripper_set_position_service
            )

    def log_info(self, message):
        logger = self.get_logger()
        if hasattr(logger, "info"):
            logger.info(message)
        elif hasattr(logger, "dinfo"):
            logger.dinfo(message)
        else:
            logger.warn(message)

    def print_config(self):
        self.log_info(
            "\n"
            "Book pick sequence configuration\n"
            f"  dry_run={self.dry_run}\n"
            f"  enable_gripper_control={self.enable_gripper_control}\n"
            f"  auto_run={self.auto_run}\n"
            f"  move_joint_service={self.move_joint_service}\n"
            f"  move_line_service={self.move_line_service}\n"
            f"  current_posx_service={self.current_posx_service}\n"
            f"  current_posx_ref={self.current_posx_ref}\n"
            f"  gripper_state_service={self.gripper_state_service}\n"
            f"  gripper_set_torque_service={self.gripper_set_torque_service}\n"
            f"  gripper_set_position_service={self.gripper_set_position_service}\n"
            f"  gripper_open_position={self.gripper_open_position}\n"
            f"  gripper_open_position_2={self.gripper_open_position_2}\n"
            f"  gripper_soft_grip_position={self.gripper_soft_grip_position}\n"
            f"  gripper_hard_grip_position={self.gripper_hard_grip_position}\n"
            f"  gripper_timeout_sec={self.gripper_timeout_sec:.2f}\n"
            f"  gripper_require_ready={self.gripper_require_ready}\n"
            f"  gripper_require_torque_enabled={self.gripper_require_torque_enabled}\n"
            f"  pick_axis={self.pick_axis}\n"
            f"  pick_axis_sign={self.pick_axis_sign:.1f}\n"
            f"  insert1_mm={self.insert1_mm:.1f}\n"
            f"  pull1_mm={self.pull1_mm:.1f}\n"
            f"  insert2_mm={self.insert2_mm:.1f}\n"
            f"  pull_final_mm={self.pull_final_mm:.1f}\n"
            f"  pick_step_max_mm={self.pick_step_max_mm:.1f}\n"
            f"  pick_vel_linear={self.pick_vel_linear:.1f}\n"
            f"  pick_vel_angular={self.pick_vel_angular:.1f}\n"
            f"  pick_acc_linear={self.pick_acc_linear:.1f}\n"
            f"  pick_acc_angular={self.pick_acc_angular:.1f}\n"
            f"  return_to_start_pose={self.return_to_start_pose}\n"
            f"  return_vel_linear={self.return_vel_linear:.1f}\n"
            f"  return_vel_angular={self.return_vel_angular:.1f}\n"
            f"  return_acc_linear={self.return_acc_linear:.1f}\n"
            f"  return_acc_angular={self.return_acc_angular:.1f}\n"
            f"  enable_place_to_box={self.enable_place_to_box}\n"
            f"  box_joint_pose_deg={self.box_joint_pose_deg}\n"
            f"  box_movej_vel={self.box_movej_vel:.1f}\n"
            f"  box_movej_acc={self.box_movej_acc:.1f}\n"
            f"  place_drop_distance_mm={self.place_drop_distance_mm:.1f}\n"
            f"  output_json={self.output_json}"
        )

    def clamp(self, value, max_abs):
        return clamp(value, max_abs)

    def fill_moveline_common(self, request):
        request.time = 0.0
        request.radius = 0.0
        request.ref = 1
        request.mode = 1
        request.blend_type = 0
        request.sync_type = 0

    def wait_for_future(self, future, timeout_sec, label):
        start_time = time.monotonic()
        while rclpy.ok() and not future.done():
            if time.monotonic() - start_time > timeout_sec:
                self.get_logger().error(f"{label} service call timed out after {timeout_sec} seconds.")
                return False
            rclpy.spin_once(self, timeout_sec=0.05)
        return future.done()

    def call_service(self, client, service_name, request, label):
        if client is None:
            self.get_logger().error(f"{label} client unavailable: {service_name}")
            return False
        if not client.wait_for_service(timeout_sec=1.0):
            self.get_logger().error(f"Service not available: {service_name}")
            return False

        self.get_logger().warn(f"Calling {service_name}")
        future = client.call_async(request)
        if not self.wait_for_future(future, 10.0, label):
            return False

        if future.result() is None:
            self.get_logger().error(f"{label} service failed: {future.exception()}")
            return False

        response = future.result()
        if bool(getattr(response, "success", False)):
            self.log_info(f"{label} service returned success=true")
            return True

        message = str(getattr(response, "message", ""))
        self.get_logger().error(f"{label} service returned success=false: {message}")
        return False

    def build_config(self):
        return BookPickSequenceConfig(
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
            return_to_start_pose=self.return_to_start_pose,
            return_vel_linear=self.return_vel_linear,
            return_vel_angular=self.return_vel_angular,
            return_acc_linear=self.return_acc_linear,
            return_acc_angular=self.return_acc_angular,
            enable_place_to_box=self.enable_place_to_box,
            box_joint_pose_deg=self.box_joint_pose_deg,
            box_movej_vel=self.box_movej_vel,
            box_movej_acc=self.box_movej_acc,
            place_drop_distance_mm=self.place_drop_distance_mm,
        )

    def read_current_tcp_posx(self):
        if self.dry_run:
            self.log_info("dry_run=true: 시작 TCP 자세 조회는 실제 서비스 호출 없이 건너뜁니다.")
            return None
        if not self.current_posx_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().warn(f"Service not available: {self.current_posx_service}")
            return None

        request = GetCurrentPosx.Request()
        request.ref = self.current_posx_ref
        future = self.current_posx_client.call_async(request)
        if not self.wait_for_future(future, 5.0, "GetCurrentPosx"):
            return None
        if future.result() is None:
            self.get_logger().warn(f"{self.current_posx_service} failed: {future.exception()}")
            return None

        response = future.result()
        if not bool(getattr(response, "success", False)):
            self.get_logger().warn(f"{self.current_posx_service} returned success=false.")
            return None
        if not response.task_pos_info:
            self.get_logger().warn(f"{self.current_posx_service} returned empty task_pos_info.")
            return None

        current = list(response.task_pos_info[0].data[:6])
        if len(current) != 6:
            self.get_logger().warn(f"Invalid current TCP pose: {current}")
            return None
        return [float(v) for v in current]

    def save_result(self, result):
        payload = {
            "timestamp": datetime.now().isoformat(),
            "source": "book_pick_sequence_node",
            "config": asdict(self.build_config()),
            "success": bool(result.success),
            "aborted_reason": str(result.aborted_reason),
            "stage_results": result.stage_results,
            "gripper_ready": result.gripper_ready,
            "gripper_torque_enabled": result.gripper_torque_enabled,
            "gripper_open_success": bool(result.gripper_open_success),
            "gripper_soft_grip_success": bool(result.gripper_soft_grip_success),
            "gripper_hard_grip_success": bool(result.gripper_hard_grip_success),
            "final_pull_executed": bool(result.final_pull_executed),
            "start_tcp_posx_mm_deg": result.start_tcp_posx_mm_deg,
            "return_to_start_pose": bool(result.return_to_start_pose),
            "return_pose_executed": bool(result.return_pose_executed),
            "return_pose_success": bool(result.return_pose_success),
            "return_pose_aborted_reason": result.return_pose_aborted_reason,
            "return_move_line_pos": result.return_move_line_pos,
            "return_vel_linear": float(result.return_vel_linear),
            "return_acc_linear": float(result.return_acc_linear),
            "place_sequence_executed": bool(result.place_sequence_executed),
            "place_sequence_success": bool(result.place_sequence_success),
            "box_joint_pose_deg": result.box_joint_pose_deg,
            "human_readable_summary": result.human_readable_summary,
        }
        os.makedirs(os.path.dirname(self.output_json) or ".", exist_ok=True)
        with open(self.output_json, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        self.log_info(f"Book pick sequence payload saved: {self.output_json}")

    def execute(self):
        self.print_config()
        if not self.auto_run:
            input("Press Enter to run book pick sequence...")

        start_tcp_posx_mm_deg = self.read_current_tcp_posx()
        if start_tcp_posx_mm_deg is not None:
            self.log_info(f"시작 TCP 자세 저장: {start_tcp_posx_mm_deg}")
        elif self.return_to_start_pose:
            self.get_logger().warn("시작 TCP 자세를 읽지 못했습니다. 복귀 단계는 건너뛸 수 있습니다.")

        executor = BookPickSequenceExecutor(
            node=self,
            config=self.build_config(),
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
            start_tcp_posx_mm_deg=start_tcp_posx_mm_deg,
        )
        result = executor.run()
        self.save_result(result)
        if result.success:
            self.log_info("Book pick sequence completed successfully.")
        else:
            self.get_logger().error(
                f"Book pick sequence failed: {result.aborted_reason}"
            )
        return result


def main(args=None):
    rclpy.init(args=args)
    node = None
    exit_code = 0
    try:
        node = BookPickSequenceNode()
        result = node.execute()
        if not result.success:
            exit_code = 1
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()
    sys.exit(exit_code)
