#!/usr/bin/env python3
"""Save the marker2-aligned TCP pose, re-grip a book, then place from that pose."""

import json
import os
import subprocess
import time

import rclpy
from dsr_msgs2.srv import GetCurrentPosx, MoveLine

from .box_regrip_marker2_place_sequence import BoxRegripMarker2PlaceSequence


class BoxSavedMarker2PosePlaceSequence(BoxRegripMarker2PlaceSequence):
    def __init__(self):
        super().__init__("box_saved_marker2_pose_place_sequence")

        self.declare_parameter("current_posx_service", "/dsr01/aux_control/get_current_posx")
        self.declare_parameter("current_posx_ref", 0)
        self.declare_parameter("saved_pose_movel_ref", 0)
        self.declare_parameter("saved_pose_movel_mode", 0)
        self.declare_parameter(
            "marker2_alignment_payload_json",
            "realtime_results/saved_marker2_alignment_payload.json",
        )

        self.current_posx_service = str(self.get_parameter("current_posx_service").value)
        self.current_posx_ref = int(self.get_parameter("current_posx_ref").value)
        self.saved_pose_movel_ref = int(self.get_parameter("saved_pose_movel_ref").value)
        self.saved_pose_movel_mode = int(self.get_parameter("saved_pose_movel_mode").value)
        self.marker2_alignment_payload_json = str(
            self.get_parameter("marker2_alignment_payload_json").value
        )

        self.current_posx_client = self.create_client(GetCurrentPosx, self.current_posx_service)

    def wait_for_motion_services(self):
        if self.dry_run:
            return
        if not self.move_joint_client.wait_for_service(timeout_sec=10.0):
            raise RuntimeError(f"Service not available before alignment: {self.move_joint_service}")
        if not self.move_line_client.wait_for_service(timeout_sec=10.0):
            raise RuntimeError(f"Service not available before alignment: {self.move_line_service}")

    def run_marker2_alignment(self):
        self.wait_for_motion_services()
        if not self.dry_run and os.path.exists(self.marker2_alignment_payload_json):
            os.remove(self.marker2_alignment_payload_json)

        command = [
            "ros2",
            "run",
            "doosan_realsense_handeye",
            self.marker2_align_executable,
            "--ros-args",
            "-p",
            f"dry_run:={str(self.dry_run).lower()}",
            "-p",
            "auto_run:=false",
            "-p",
            "enable_movej:=true",
            "-p",
            f"alignment_payload_json:={self.marker2_alignment_payload_json}",
        ]
        self.log_info("\nRUN_MARKER2_ALIGN\n  command=" + " ".join(command))
        self.wait_for_enter("RUN_MARKER2_ALIGN")
        if self.dry_run:
            self.get_logger().warn("dry_run=true: skipped marker2 alignment subprocess")
            return

        subprocess.run(command, check=True, timeout=self.marker2_align_timeout_sec)
        self.require_marker2_alignment_success()

    def require_marker2_alignment_success(self):
        if not os.path.exists(self.marker2_alignment_payload_json):
            raise RuntimeError(
                "marker2 alignment failed: payload was not created "
                f"({self.marker2_alignment_payload_json})"
            )
        with open(self.marker2_alignment_payload_json, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if not bool(payload.get("aligned", False)):
            raise RuntimeError("marker2 alignment failed: payload aligned=false")
        if int(payload.get("target_marker_id", -1)) != 2:
            raise RuntimeError(
                "marker2 alignment failed: unexpected target_marker_id="
                f"{payload.get('target_marker_id')}"
            )
        self.log_info(
            "\nMARKER2_ALIGNMENT_CONFIRMED\n"
            f"  payload={self.marker2_alignment_payload_json}\n"
            f"  aligned_tcp_pose={payload.get('aligned_tcp_pose')}"
        )

    def get_current_task_pose(self):
        if self.dry_run:
            self.get_logger().warn("dry_run=true: using zero saved TCP pose placeholder")
            return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        if not self.current_posx_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError(f"Service not available: {self.current_posx_service}")
        request = GetCurrentPosx.Request()
        request.ref = self.current_posx_ref
        response = self.wait_future(
            self.current_posx_client.call_async(request),
            10.0,
            "GET_SAVED_MARKER2_TCP_POSE",
        )
        if not bool(response.success):
            raise RuntimeError(f"{self.current_posx_service} returned success=false")
        if not response.task_pos_info:
            raise RuntimeError(f"{self.current_posx_service} returned empty task_pos_info")
        pose = [float(v) for v in list(response.task_pos_info[0].data)[:6]]
        if len(pose) != 6:
            raise RuntimeError(f"{self.current_posx_service} returned fewer than 6 pose values")
        self.log_info(f"\nSAVED_MARKER2_TCP_POSE\n  pose [mm,deg]={pose}")
        return pose

    def move_to_saved_marker2_pose(self, saved_pose):
        request = MoveLine.Request()
        request.pos = [float(v) for v in saved_pose]
        request.vel = [self.movel_vel_linear, self.movel_vel_angular]
        request.acc = [self.movel_acc_linear, self.movel_acc_angular]
        request.time = 0.0
        request.radius = 0.0
        request.ref = self.saved_pose_movel_ref
        request.mode = self.saved_pose_movel_mode
        request.blend_type = 0
        request.sync_type = 0

        self.log_info(
            "\nMOVE_TO_SAVED_MARKER2_TCP_POSE\n"
            f"  MoveLine pos [mm,deg]={request.pos}\n"
            f"  ref={request.ref}, mode={request.mode}"
        )
        self.wait_for_enter("MOVE_TO_SAVED_MARKER2_TCP_POSE")
        if self.dry_run:
            self.get_logger().warn("dry_run=true: skipped saved pose MoveLine")
            return
        if not self.move_line_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError(f"Service not available: {self.move_line_service}")
        response = self.wait_future(
            self.move_line_client.call_async(request),
            60.0,
            "MOVE_TO_SAVED_MARKER2_TCP_POSE",
        )
        if not bool(response.success):
            raise RuntimeError("MOVE_TO_SAVED_MARKER2_TCP_POSE returned success=false")
        time.sleep(self.settle_sec)

    def print_config(self):
        super().print_config()
        self.log_info(
            "\n"
            "Saved marker2 pose mode\n"
            f"  current_posx_service={self.current_posx_service}\n"
            f"  current_posx_ref={self.current_posx_ref}\n"
            f"  saved_pose_movel_ref={self.saved_pose_movel_ref}\n"
            f"  saved_pose_movel_mode={self.saved_pose_movel_mode}\n"
            f"  marker2_alignment_payload_json={self.marker2_alignment_payload_json}"
        )

    def run_sequence(self):
        self.print_config()
        if self.require_enter:
            input("Press Enter to run saved marker2 pose place sequence...")

        self.run_marker2_alignment()
        saved_pose = self.get_current_task_pose()

        self.call_move_joint(self.box_home_joint_pose_deg, "MOVEJ_BOX_HOME")
        self.set_gripper_torque(True)
        self.set_gripper_position(self.gripper_open_position, "OPEN_GRIPPER_FOR_REGRIP")
        self.call_tool_move(0.0, 0.0, self.box_regrip_down_mm, "DESCEND_TO_BOX_BOOK")
        self.set_gripper_position(self.gripper_close_position, "CLOSE_GRIPPER_ON_BOX_BOOK")
        self.call_tool_move(0.0, 0.0, -self.box_regrip_down_mm, "LIFT_FROM_BOX")

        self.move_to_saved_marker2_pose(saved_pose)

        remaining_insert_z_mm = self.marker2_insert_z_mm - self.marker2_pre_insert_z_mm
        self.call_tool_move(0.0, 0.0, self.marker2_pre_insert_z_mm, "PRE_INSERT_FROM_SAVED_Z_100")
        self.call_tool_move(0.0, self.marker2_drop_y_mm, 0.0, "DROP_FROM_SAVED_Y_150")
        self.call_tool_move(0.0, 0.0, remaining_insert_z_mm, "INSERT_REMAINING_FROM_SAVED_Z")
        self.set_gripper_position(self.gripper_open_position, "OPEN_GRIPPER_PLACE_BOOK")
        self.call_tool_move(0.0, 0.0, -remaining_insert_z_mm, "RETREAT_REMAINING_FROM_SAVED_Z")
        self.call_tool_move(0.0, -self.marker2_drop_y_mm, 0.0, "RAISE_FROM_SAVED_Y_150")
        self.call_tool_move(0.0, 0.0, -self.marker2_pre_insert_z_mm, "RETREAT_PRE_INSERT_FROM_SAVED_Z_100")
        self.call_move_joint(self.box_home_joint_pose_deg, "MOVEJ_BOX_HOME_RETURN")
        self.log_info("\nDONE: saved marker2 pose place sequence completed.")


def main(args=None):
    rclpy.init(args=args)
    node = BoxSavedMarker2PosePlaceSequence()
    try:
        node.run_sequence()
    except KeyboardInterrupt:
        node.get_logger().warn("Interrupted by user.")
    except Exception as exc:
        node.get_logger().error(f"Sequence failed: {exc}")
        raise
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
