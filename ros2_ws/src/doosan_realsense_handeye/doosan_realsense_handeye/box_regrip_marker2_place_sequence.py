#!/usr/bin/env python3
"""Re-grip a boxed book, align to ArUco marker 2, and place it by tool offsets."""

import subprocess
import time

import rclpy
from dsr_msgs2.srv import MoveJoint, MoveLine
from rclpy.node import Node

try:
    from dsr_gripper_tcp_interfaces.srv import SetPosition, SetTorque
except ImportError:
    SetPosition = None
    SetTorque = None


BOX_HOME_JOINT_POSE_DEG = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]


class BoxRegripMarker2PlaceSequence(Node):
    def __init__(self, node_name="box_regrip_marker2_place_sequence"):
        super().__init__(node_name)

        self.declare_parameter("dry_run", True)
        self.declare_parameter("require_enter", False)
        self.declare_parameter("box_home_joint_pose_deg", BOX_HOME_JOINT_POSE_DEG)
        self.declare_parameter("box_regrip_down_mm", 200.0)
        self.declare_parameter("marker2_insert_z_mm", 400.0)
        self.declare_parameter("marker2_pre_insert_z_mm", 100.0)
        self.declare_parameter("marker2_drop_y_mm", 150.0)
        self.declare_parameter("move_joint_service", "/dsr01/motion/move_joint")
        self.declare_parameter("move_line_service", "/dsr01/motion/move_line")
        self.declare_parameter("movej_vel", 30.0)
        self.declare_parameter("movej_acc", 60.0)
        self.declare_parameter("movel_vel_linear", 20.0)
        self.declare_parameter("movel_vel_angular", 10.0)
        self.declare_parameter("movel_acc_linear", 40.0)
        self.declare_parameter("movel_acc_angular", 20.0)
        self.declare_parameter("movel_ref", 1)
        self.declare_parameter("movel_mode", 1)
        self.declare_parameter("settle_sec", 0.5)
        self.declare_parameter("enable_gripper_control", True)
        self.declare_parameter("gripper_set_torque_service", "/gripper_service/set_torque")
        self.declare_parameter("gripper_set_position_service", "/gripper_service/set_position")
        self.declare_parameter("gripper_open_position", 500)
        self.declare_parameter("gripper_close_position", 660)
        self.declare_parameter("gripper_timeout_sec", 5.0)
        self.declare_parameter("marker2_align_executable", "aruco_marker2_proto_align")
        self.declare_parameter("marker2_align_timeout_sec", 240.0)

        self.dry_run = bool(self.get_parameter("dry_run").value)
        self.require_enter = bool(self.get_parameter("require_enter").value)
        self.box_home_joint_pose_deg = [
            float(v) for v in self.get_parameter("box_home_joint_pose_deg").value
        ]
        self.box_regrip_down_mm = float(self.get_parameter("box_regrip_down_mm").value)
        self.marker2_insert_z_mm = float(self.get_parameter("marker2_insert_z_mm").value)
        self.marker2_pre_insert_z_mm = float(
            self.get_parameter("marker2_pre_insert_z_mm").value
        )
        self.marker2_drop_y_mm = float(self.get_parameter("marker2_drop_y_mm").value)
        self.move_joint_service = str(self.get_parameter("move_joint_service").value)
        self.move_line_service = str(self.get_parameter("move_line_service").value)
        self.movej_vel = float(self.get_parameter("movej_vel").value)
        self.movej_acc = float(self.get_parameter("movej_acc").value)
        self.movel_vel_linear = float(self.get_parameter("movel_vel_linear").value)
        self.movel_vel_angular = float(self.get_parameter("movel_vel_angular").value)
        self.movel_acc_linear = float(self.get_parameter("movel_acc_linear").value)
        self.movel_acc_angular = float(self.get_parameter("movel_acc_angular").value)
        self.movel_ref = int(self.get_parameter("movel_ref").value)
        self.movel_mode = int(self.get_parameter("movel_mode").value)
        self.settle_sec = float(self.get_parameter("settle_sec").value)
        self.enable_gripper_control = bool(self.get_parameter("enable_gripper_control").value)
        self.gripper_set_torque_service = str(
            self.get_parameter("gripper_set_torque_service").value
        )
        self.gripper_set_position_service = str(
            self.get_parameter("gripper_set_position_service").value
        )
        self.gripper_open_position = int(self.get_parameter("gripper_open_position").value)
        self.gripper_close_position = int(self.get_parameter("gripper_close_position").value)
        self.gripper_timeout_sec = float(self.get_parameter("gripper_timeout_sec").value)
        self.marker2_align_executable = str(
            self.get_parameter("marker2_align_executable").value
        )
        self.marker2_align_timeout_sec = float(
            self.get_parameter("marker2_align_timeout_sec").value
        )

        if len(self.box_home_joint_pose_deg) != 6:
            raise ValueError("box_home_joint_pose_deg must contain exactly 6 values")
        if self.marker2_pre_insert_z_mm > self.marker2_insert_z_mm:
            raise ValueError(
                "marker2_pre_insert_z_mm must be less than or equal to marker2_insert_z_mm"
            )

        self.move_joint_client = self.create_client(MoveJoint, self.move_joint_service)
        self.move_line_client = self.create_client(MoveLine, self.move_line_service)
        self.gripper_set_torque_client = None
        self.gripper_set_position_client = None
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

    def wait_future(self, future, timeout_sec, label):
        start = time.monotonic()
        while rclpy.ok() and not future.done():
            if time.monotonic() - start > timeout_sec:
                raise TimeoutError(f"{label} timed out after {timeout_sec:.1f} sec")
            rclpy.spin_once(self, timeout_sec=0.05)
        if future.result() is None:
            raise RuntimeError(f"{label} failed: {future.exception()}")
        return future.result()

    def wait_for_enter(self, label):
        if not self.require_enter:
            return
        try:
            response = input(f"[{label}] press Enter to run, q to abort > ").strip().lower()
        except EOFError:
            return
        if response == "q":
            raise KeyboardInterrupt

    def call_move_joint(self, joint_pose_deg, label):
        request = MoveJoint.Request()
        request.pos = [float(v) for v in joint_pose_deg]
        request.vel = self.movej_vel
        request.acc = self.movej_acc
        request.time = 0.0
        request.radius = 0.0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 0
        self.log_info(f"\n{label}\n  MoveJoint pos={request.pos}")
        self.wait_for_enter(label)
        if self.dry_run:
            self.get_logger().warn(f"{label}: dry_run=true, skipped MoveJoint")
            return
        if not self.move_joint_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError(f"Service not available: {self.move_joint_service}")
        response = self.wait_future(
            self.move_joint_client.call_async(request),
            60.0,
            label,
        )
        if not bool(response.success):
            raise RuntimeError(f"{label} returned success=false")
        time.sleep(self.settle_sec)

    def call_tool_move(self, x_mm, y_mm, z_mm, label):
        request = MoveLine.Request()
        request.pos = [float(x_mm), float(y_mm), float(z_mm), 0.0, 0.0, 0.0]
        request.vel = [self.movel_vel_linear, self.movel_vel_angular]
        request.acc = [self.movel_acc_linear, self.movel_acc_angular]
        request.time = 0.0
        request.radius = 0.0
        request.ref = self.movel_ref
        request.mode = self.movel_mode
        request.blend_type = 0
        request.sync_type = 0
        self.log_info(f"\n{label}\n  MoveLine pos [mm,deg]={request.pos}")
        self.wait_for_enter(label)
        if self.dry_run:
            self.get_logger().warn(f"{label}: dry_run=true, skipped MoveLine")
            return
        if not self.move_line_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError(f"Service not available: {self.move_line_service}")
        response = self.wait_future(
            self.move_line_client.call_async(request),
            60.0,
            label,
        )
        if not bool(response.success):
            raise RuntimeError(f"{label} returned success=false")
        time.sleep(self.settle_sec)

    def set_gripper_torque(self, enabled):
        if not self.enable_gripper_control:
            self.get_logger().warn("enable_gripper_control=false: skipped gripper torque")
            return
        if SetTorque is None or self.gripper_set_torque_client is None:
            raise RuntimeError("SetTorque service interface is unavailable")
        request = SetTorque.Request()
        request.enabled = bool(enabled)
        self.log_info(f"\nGRIPPER_TORQUE\n  enabled={request.enabled}")
        self.wait_for_enter("GRIPPER_TORQUE")
        if self.dry_run:
            self.get_logger().warn("dry_run=true: skipped SetTorque")
            return
        if not self.gripper_set_torque_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError(f"Service not available: {self.gripper_set_torque_service}")
        response = self.wait_future(
            self.gripper_set_torque_client.call_async(request),
            self.gripper_timeout_sec,
            "SetTorque",
        )
        if not bool(response.success):
            raise RuntimeError("SetTorque returned success=false")

    def set_gripper_position(self, position, label):
        if not self.enable_gripper_control:
            self.get_logger().warn(f"enable_gripper_control=false: skipped {label}")
            return
        if SetPosition is None or self.gripper_set_position_client is None:
            raise RuntimeError("SetPosition service interface is unavailable")
        request = SetPosition.Request()
        request.position = int(position)
        request.timeout_sec = float(self.gripper_timeout_sec)
        self.log_info(f"\n{label}\n  gripper position={request.position}")
        self.wait_for_enter(label)
        if self.dry_run:
            self.get_logger().warn(f"{label}: dry_run=true, skipped SetPosition")
            return
        if not self.gripper_set_position_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError(f"Service not available: {self.gripper_set_position_service}")
        response = self.wait_future(
            self.gripper_set_position_client.call_async(request),
            self.gripper_timeout_sec + 2.0,
            label,
        )
        if not bool(response.success):
            raise RuntimeError(f"{label} returned success=false")
        time.sleep(self.settle_sec)

    def run_marker2_alignment(self):
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
        ]
        self.log_info("\nRUN_MARKER2_ALIGN\n  command=" + " ".join(command))
        self.wait_for_enter("RUN_MARKER2_ALIGN")
        if self.dry_run:
            self.get_logger().warn("dry_run=true: skipped marker2 alignment subprocess")
            return
        subprocess.run(command, check=True, timeout=self.marker2_align_timeout_sec)

    def print_config(self):
        self.log_info(
            "\n"
            "Box re-grip marker2 place sequence\n"
            f"  dry_run={self.dry_run}\n"
            f"  box_home_joint_pose_deg={self.box_home_joint_pose_deg}\n"
            f"  box_regrip_down_mm={self.box_regrip_down_mm:.1f}\n"
            f"  marker2_insert_z_mm={self.marker2_insert_z_mm:.1f}\n"
            f"  marker2_pre_insert_z_mm={self.marker2_pre_insert_z_mm:.1f}\n"
            f"  marker2_drop_y_mm={self.marker2_drop_y_mm:.1f}\n"
            f"  gripper_open_position={self.gripper_open_position}\n"
            f"  gripper_close_position={self.gripper_close_position}\n"
            f"  marker2_align_executable={self.marker2_align_executable}"
        )

    def run_sequence(self):
        self.print_config()
        if self.require_enter:
            input("Press Enter to run box re-grip marker2 place sequence...")

        self.call_move_joint(self.box_home_joint_pose_deg, "MOVEJ_BOX_HOME")
        self.set_gripper_torque(True)
        self.set_gripper_position(self.gripper_open_position, "OPEN_GRIPPER_FOR_REGRIP")
        self.call_tool_move(0.0, 0.0, self.box_regrip_down_mm, "DESCEND_TO_BOX_BOOK")
        self.set_gripper_position(self.gripper_close_position, "CLOSE_GRIPPER_ON_BOX_BOOK")
        self.call_tool_move(0.0, 0.0, -self.box_regrip_down_mm, "LIFT_FROM_BOX")
        self.run_marker2_alignment()
        remaining_insert_z_mm = self.marker2_insert_z_mm - self.marker2_pre_insert_z_mm
        self.call_tool_move(0.0, 0.0, self.marker2_pre_insert_z_mm, "PRE_INSERT_FROM_MARKER2_Z_100")
        self.call_tool_move(0.0, self.marker2_drop_y_mm, 0.0, "DROP_FROM_MARKER2_Y_150")
        self.call_tool_move(0.0, 0.0, remaining_insert_z_mm, "INSERT_REMAINING_FROM_MARKER2_Z")
        self.set_gripper_position(self.gripper_open_position, "OPEN_GRIPPER_PLACE_BOOK")
        self.call_tool_move(0.0, 0.0, -remaining_insert_z_mm, "RETREAT_REMAINING_FROM_MARKER2_Z")
        self.call_tool_move(0.0, -self.marker2_drop_y_mm, 0.0, "RAISE_FROM_PLACE_Y_150")
        self.call_tool_move(0.0, 0.0, -self.marker2_pre_insert_z_mm, "RETREAT_PRE_INSERT_FROM_MARKER2_Z_100")
        self.call_move_joint(self.box_home_joint_pose_deg, "MOVEJ_BOX_HOME_RETURN")
        self.log_info("\nDONE: box re-grip marker2 place sequence completed.")


def main(args=None):
    rclpy.init(args=args)
    node = BoxRegripMarker2PlaceSequence()
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
