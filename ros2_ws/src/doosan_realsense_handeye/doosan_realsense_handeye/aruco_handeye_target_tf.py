import math
import time
from pathlib import Path

import numpy as np
import rclpy
import yaml
from geometry_msgs.msg import TransformStamped
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from tf2_ros import Buffer, TransformBroadcaster, TransformException, TransformListener

from .handeye_config_utils import node_parameters
from .handeye_transform_utils import (
    make_transform,
    matrix_from_yaml_dict,
    matrix_to_euler_xyz,
    matrix_to_quaternion,
    transform_stamped_to_matrix,
)


def load_tool_camera(path):
    with Path(path).open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    if "T_tool_camera" not in data:
        raise ValueError(f"{path} does not contain T_tool_camera")
    return matrix_from_yaml_dict(data["T_tool_camera"])


class ArucoHandeyeTargetTf(Node):
    def __init__(self):
        super().__init__("aruco_handeye_target_tf")
        self._declare_parameters()
        self._read_parameters()

        self.t_tool_camera = load_tool_camera(self.calibration_result_path)
        self.t_target_approach = make_transform(
            translation=[
                self.approach_offset_x,
                self.approach_offset_y,
                self.approach_offset_z,
            ]
        )
        self.latest_output_time = 0.0
        self.latest_tf_warn_time = 0.0

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.tf_broadcaster = TransformBroadcaster(self)
        self.create_timer(self.publish_period_sec, self._on_timer)

        self.get_logger().warn(
            "Handeye TF bridge enabled. This node reads TF and calibration YAML, then publishes "
            "base-referenced target frames only; it never sends robot motion commands."
        )
        self.log_info(
            f"Frames: {self.base_frame}->{self.tool_frame}, {self.camera_frame}->{self.marker_frame}, "
            f"target={self.target_frame_name}, approach={self.approach_frame_name}, "
            f"goal={self.goal_frame_name if self.publish_aligned_goal else 'disabled'}"
        )

    def _declare_parameters(self):
        defaults = node_parameters("aruco_handeye_target_tf")
        self.declare_parameter("base_frame", defaults.get("base_frame", "base_link"))
        self.declare_parameter("tool_frame", defaults.get("tool_frame", "link_6"))
        self.declare_parameter(
            "camera_frame",
            defaults.get("camera_frame", "camera_color_optical_frame"),
        )
        self.declare_parameter("marker_frame", defaults.get("marker_frame", "aruco_marker_6"))
        self.declare_parameter(
            "calibration_result_path",
            defaults.get(
                "calibration_result_path",
                "/home/user/Shelfa/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_tool_camera.yaml",
            ),
        )
        self.declare_parameter("tf_timeout_sec", defaults.get("tf_timeout_sec", 0.5))
        self.declare_parameter("publish_period_sec", defaults.get("publish_period_sec", 0.05))
        self.declare_parameter("output_period_sec", defaults.get("output_period_sec", 0.5))
        self.declare_parameter("approach_offset_x", defaults.get("approach_offset_x", 0.0))
        self.declare_parameter("approach_offset_y", defaults.get("approach_offset_y", 0.0))
        self.declare_parameter("approach_offset_z", defaults.get("approach_offset_z", 0.10))
        self.declare_parameter(
            "target_frame_name",
            defaults.get("target_frame_name", "detected_target"),
        )
        self.declare_parameter(
            "approach_frame_name",
            defaults.get("approach_frame_name", "target_approach"),
        )
        self.declare_parameter(
            "publish_aligned_goal",
            defaults.get("publish_aligned_goal", True),
        )
        self.declare_parameter(
            "goal_frame_name",
            defaults.get("goal_frame_name", "aligned_tcp_goal"),
        )
        self.declare_parameter("align_axis", defaults.get("align_axis", "z"))
        self.declare_parameter("axis_direction", defaults.get("axis_direction", "opposite"))

    def _read_parameters(self):
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.tool_frame = str(self.get_parameter("tool_frame").value)
        self.camera_frame = str(self.get_parameter("camera_frame").value)
        self.marker_frame = str(self.get_parameter("marker_frame").value)
        self.calibration_result_path = str(self.get_parameter("calibration_result_path").value)
        self.tf_timeout_sec = float(self.get_parameter("tf_timeout_sec").value)
        self.publish_period_sec = float(self.get_parameter("publish_period_sec").value)
        self.output_period_sec = float(self.get_parameter("output_period_sec").value)
        self.approach_offset_x = float(self.get_parameter("approach_offset_x").value)
        self.approach_offset_y = float(self.get_parameter("approach_offset_y").value)
        self.approach_offset_z = float(self.get_parameter("approach_offset_z").value)
        self.target_frame_name = str(self.get_parameter("target_frame_name").value)
        self.approach_frame_name = str(self.get_parameter("approach_frame_name").value)
        self.publish_aligned_goal = bool(self.get_parameter("publish_aligned_goal").value)
        self.goal_frame_name = str(self.get_parameter("goal_frame_name").value)
        self.align_axis = str(self.get_parameter("align_axis").value).lower()
        self.axis_direction = str(self.get_parameter("axis_direction").value).lower()
        if self.align_axis != "z":
            raise ValueError("align_axis currently supports only 'z'")
        if self.axis_direction not in ("same", "opposite"):
            raise ValueError("axis_direction must be 'same' or 'opposite'")

    def _on_timer(self):
        try:
            t_base_tool = self._lookup_matrix(self.base_frame, self.tool_frame)
            t_camera_marker = self._lookup_matrix(self.camera_frame, self.marker_frame)
        except TransformException as exc:
            self._warn_tf_failed(exc)
            return

        t_base_target = t_base_tool @ self.t_tool_camera @ t_camera_marker
        t_base_approach = t_base_target @ self.t_target_approach
        stamp = self.get_clock().now().to_msg()
        self._publish_tf(t_base_target, self.target_frame_name, stamp)
        self._publish_tf(t_base_approach, self.approach_frame_name, stamp)

        if self.publish_aligned_goal:
            try:
                t_base_goal, info = self._compute_aligned_goal(
                    t_base_target,
                    t_base_approach,
                    t_base_tool,
                )
            except ValueError as exc:
                self.get_logger().error(f"Aligned goal computation failed: {exc}")
                return
            self._publish_tf(t_base_goal, self.goal_frame_name, stamp)
        else:
            info = None
            t_base_goal = None

        self._print_summary(t_base_target, t_base_approach, t_base_goal, info)

    def _lookup_matrix(self, parent_frame, child_frame):
        transform = self.tf_buffer.lookup_transform(
            parent_frame,
            child_frame,
            rclpy.time.Time(),
            timeout=Duration(seconds=self.tf_timeout_sec),
        )
        return transform_stamped_to_matrix(transform)

    def _warn_tf_failed(self, exc):
        now = time.monotonic()
        if now - self.latest_tf_warn_time < self.output_period_sec:
            return
        self.latest_tf_warn_time = now
        self.get_logger().warn(f"Required TF lookup failed: {exc}")

    def _compute_aligned_goal(self, t_base_target, t_base_approach, t_base_tool):
        r_base_target = t_base_target[:3, :3]
        r_base_tool = t_base_tool[:3, :3]
        z_marker_base = self._normalize(r_base_target[:, 2], "marker Z axis")
        z_tcp_current = self._normalize(r_base_tool[:, 2], "current TCP Z axis")
        x_tcp_current = self._normalize(r_base_tool[:, 0], "current TCP X axis")

        z_tcp_goal = z_marker_base if self.axis_direction == "same" else -z_marker_base
        z_tcp_goal = self._normalize(z_tcp_goal, "goal TCP Z axis")

        x_projected = x_tcp_current - float(np.dot(x_tcp_current, z_tcp_goal)) * z_tcp_goal
        if np.linalg.norm(x_projected) < 1e-6:
            current_y = self._normalize(r_base_tool[:, 1], "current TCP Y axis")
            x_projected = current_y - float(np.dot(current_y, z_tcp_goal)) * z_tcp_goal
        if np.linalg.norm(x_projected) < 1e-6:
            x_projected = self._fallback_perpendicular_axis(z_tcp_goal)

        x_tcp_goal = self._normalize(x_projected, "goal TCP X axis")
        y_tcp_goal = self._normalize(np.cross(z_tcp_goal, x_tcp_goal), "goal TCP Y axis")
        x_tcp_goal = self._normalize(np.cross(y_tcp_goal, z_tcp_goal), "recomputed goal TCP X axis")
        r_base_goal = np.column_stack((x_tcp_goal, y_tcp_goal, z_tcp_goal))
        if np.linalg.det(r_base_goal) < 0.0:
            raise ValueError("computed rotation is not right-handed")

        return make_transform(rotation=r_base_goal, translation=t_base_approach[:3, 3]), {
            "z_marker_base": z_marker_base,
            "z_tcp_current": z_tcp_current,
            "z_tcp_goal": z_tcp_goal,
            "current_to_goal_angle_deg": self._angle_deg(z_tcp_current, z_tcp_goal),
        }

    def _publish_tf(self, transform, child_frame_id, stamp):
        msg = TransformStamped()
        msg.header.stamp = stamp
        msg.header.frame_id = self.base_frame
        msg.child_frame_id = child_frame_id
        translation = transform[:3, 3]
        quaternion = matrix_to_quaternion(transform[:3, :3])
        msg.transform.translation.x = float(translation[0])
        msg.transform.translation.y = float(translation[1])
        msg.transform.translation.z = float(translation[2])
        msg.transform.rotation.x = float(quaternion[0])
        msg.transform.rotation.y = float(quaternion[1])
        msg.transform.rotation.z = float(quaternion[2])
        msg.transform.rotation.w = float(quaternion[3])
        self.tf_broadcaster.sendTransform(msg)

    def _print_summary(self, t_base_target, t_base_approach, t_base_goal, info):
        now = time.monotonic()
        if now - self.latest_output_time < self.output_period_sec:
            return
        self.latest_output_time = now

        target_xyz, target_rpy = self._pose_components(t_base_target)
        approach_xyz, _ = self._pose_components(t_base_approach)
        lines = [
            "",
            "Handeye target frames",
            f"  {self.target_frame_name} xyz [m]: {self._format_vector(target_xyz)}",
            "  "
            f"{self.target_frame_name} rpy [deg]: "
            f"{math.degrees(target_rpy[0]):.3f}, {math.degrees(target_rpy[1]):.3f}, "
            f"{math.degrees(target_rpy[2]):.3f}",
            f"  {self.approach_frame_name} xyz [m]: {self._format_vector(approach_xyz)}",
        ]
        if t_base_goal is not None and info is not None:
            goal_xyz, goal_rpy = self._pose_components(t_base_goal)
            lines.extend(
                [
                    f"  {self.goal_frame_name} xyz [m]: {self._format_vector(goal_xyz)}",
                    "  "
                    f"{self.goal_frame_name} rpy [deg]: "
                    f"{math.degrees(goal_rpy[0]):.3f}, {math.degrees(goal_rpy[1]):.3f}, "
                    f"{math.degrees(goal_rpy[2]):.3f}",
                    "  "
                    f"angle current TCP Z -> goal TCP Z [deg]: "
                    f"{info['current_to_goal_angle_deg']:.3f}",
                ]
            )
        self.log_info("\n".join(lines))

    def log_info(self, message):
        logger = self.get_logger()
        if hasattr(logger, "info"):
            logger.info(message)
        elif hasattr(logger, "dinfo"):
            logger.dinfo(message)
        else:
            logger.warn(message)

    @staticmethod
    def _pose_components(transform):
        translation = transform[:3, 3]
        euler = matrix_to_euler_xyz(transform[:3, :3])
        return translation, euler

    @staticmethod
    def _format_vector(vector):
        return "[" + ", ".join(f"{float(value):.3f}" for value in vector) + "]"

    @staticmethod
    def _normalize(vector, label):
        norm = np.linalg.norm(vector)
        if norm < 1e-9:
            raise ValueError(f"{label} vector norm is too small")
        return np.asarray(vector, dtype=float) / norm

    @staticmethod
    def _fallback_perpendicular_axis(z_axis):
        z_axis = np.asarray(z_axis, dtype=float)
        basis = np.array([1.0, 0.0, 0.0], dtype=float)
        if abs(float(np.dot(basis, z_axis))) > 0.9:
            basis = np.array([0.0, 1.0, 0.0], dtype=float)
        perp = basis - float(np.dot(basis, z_axis)) * z_axis
        norm = np.linalg.norm(perp)
        if norm < 1e-9:
            raise ValueError("failed to compute fallback perpendicular axis")
        return perp / norm

    @staticmethod
    def _angle_deg(v1, v2):
        dot = float(np.dot(v1, v2))
        dot = max(-1.0, min(1.0, dot))
        return math.degrees(math.acos(dot))


def main(args=None):
    rclpy.init(args=args)
    node = ArucoHandeyeTargetTf()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spin_thread = None
    try:
        import threading

        spin_thread = threading.Thread(target=executor.spin, daemon=True)
        spin_thread.start()
        try:
            while rclpy.ok():
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        if spin_thread is not None:
            spin_thread.join(timeout=1.0)


if __name__ == "__main__":
    main()
