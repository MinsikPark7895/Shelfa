import math
import time

import numpy as np
import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from tf2_ros import Buffer, TransformBroadcaster, TransformException, TransformListener

from .config_utils import node_parameters
from .logger_utils import safe_log_info
from .transform_utils import (
    make_transform,
    matrix_to_euler_xyz,
    matrix_to_quaternion,
    transform_stamped_to_matrix,
)


class AlignToMarkerPreview(Node):
    def __init__(self):
        super().__init__("align_to_marker_preview")
        self._declare_parameters()
        self._read_parameters()

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.tf_broadcaster = TransformBroadcaster(self)
        self.latest_output_time = 0.0
        self.latest_tf_warn_time = 0.0
        self.create_timer(0.05, self._on_timer)

        self.get_logger().warn(
            "Preview-only TCP alignment node. This node publishes TF only; it never calls "
            "Doosan motion, servo, MoveJ, MoveLine, or gripper commands."
        )
        safe_log_info(
            self.get_logger(),
            f"Frames: target={self.target_frame}, approach={self.approach_frame}, "
            f"tool={self.tool_frame}, goal={self.goal_frame}; "
            f"align_axis={self.align_axis}, axis_direction={self.axis_direction}",
        )

    def _declare_parameters(self):
        defaults = node_parameters("align_to_marker_preview")
        live_defaults = node_parameters("live_target_to_base")
        merged = {**live_defaults, **defaults}
        self.declare_parameter("base_frame", merged.get("base_frame", "base_link"))
        self.declare_parameter("tool_frame", merged.get("tool_frame", "link_6"))
        self.declare_parameter("target_frame", merged.get("target_frame", "detected_target"))
        self.declare_parameter("approach_frame", merged.get("approach_frame", "target_approach"))
        self.declare_parameter("goal_frame", merged.get("goal_frame", "aligned_tcp_goal"))
        self.declare_parameter("align_axis", merged.get("align_axis", "z"))
        self.declare_parameter("axis_direction", merged.get("axis_direction", "opposite"))
        self.declare_parameter("output_period_sec", merged.get("output_period_sec", 0.5))
        self.declare_parameter("tf_timeout_sec", merged.get("tf_timeout_sec", 0.5))

    def _read_parameters(self):
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.tool_frame = str(self.get_parameter("tool_frame").value)
        self.target_frame = str(self.get_parameter("target_frame").value)
        self.approach_frame = str(self.get_parameter("approach_frame").value)
        self.goal_frame = str(self.get_parameter("goal_frame").value)
        self.align_axis = str(self.get_parameter("align_axis").value).lower()
        self.axis_direction = str(self.get_parameter("axis_direction").value).lower()
        self.output_period_sec = float(self.get_parameter("output_period_sec").value)
        self.tf_timeout_sec = float(self.get_parameter("tf_timeout_sec").value)

        if self.align_axis != "z":
            raise ValueError("align_axis currently supports only 'z'")
        if self.axis_direction not in ("same", "opposite"):
            raise ValueError("axis_direction must be 'same' or 'opposite'")

    def _on_timer(self):
        try:
            t_base_target = self._lookup_matrix(self.base_frame, self.target_frame)
            t_base_approach = self._lookup_matrix(self.base_frame, self.approach_frame)
            t_base_tool = self._lookup_matrix(self.base_frame, self.tool_frame)
        except TransformException as exc:
            self._warn_tf_failed(exc)
            return

        try:
            t_base_goal, info = self._compute_aligned_goal(
                t_base_target,
                t_base_approach,
                t_base_tool,
            )
        except ValueError as exc:
            self.get_logger().error(f"Alignment preview failed: {exc}")
            return

        stamp = self.get_clock().now().to_msg()
        self._publish_tf(t_base_goal, self.goal_frame, stamp)
        self._print_preview(t_base_goal, info)

    def _warn_tf_failed(self, exc):
        now = time.monotonic()
        if now - self.latest_tf_warn_time < self.output_period_sec:
            return
        self.latest_tf_warn_time = now
        self.get_logger().warn(f"Required TF lookup failed: {exc}")

    def _lookup_matrix(self, parent_frame, child_frame):
        transform = self.tf_buffer.lookup_transform(
            parent_frame,
            child_frame,
            rclpy.time.Time(),
            timeout=Duration(seconds=self.tf_timeout_sec),
        )
        return transform_stamped_to_matrix(transform)

    def _compute_aligned_goal(self, t_base_target, t_base_approach, t_base_tool):
        r_base_target = t_base_target[:3, :3]
        r_base_tool = t_base_tool[:3, :3]
        z_marker_base = self._normalize(r_base_target[:, 2], "marker Z axis")
        z_tcp_current = self._normalize(r_base_tool[:, 2], "current TCP Z axis")
        x_tcp_current = self._normalize(r_base_tool[:, 0], "current TCP X axis")

        if self.axis_direction == "same":
            z_tcp_goal = z_marker_base
        else:
            z_tcp_goal = -z_marker_base
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

        t_base_goal = make_transform(
            rotation=r_base_goal,
            translation=t_base_approach[:3, 3],
        )
        desired_axis = z_marker_base if self.axis_direction == "same" else -z_marker_base
        return t_base_goal, {
            "z_marker_base": z_marker_base,
            "z_tcp_current": z_tcp_current,
            "z_tcp_goal": z_tcp_goal,
            "desired_axis": desired_axis,
            "current_to_goal_angle_deg": self._angle_deg(z_tcp_current, z_tcp_goal),
            "goal_to_desired_angle_deg": self._angle_deg(z_tcp_goal, desired_axis),
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

    def _print_preview(self, t_base_goal, info):
        now = time.monotonic()
        if now - self.latest_output_time < self.output_period_sec:
            return
        self.latest_output_time = now

        xyz = t_base_goal[:3, 3]
        rpy = matrix_to_euler_xyz(t_base_goal[:3, :3])
        quaternion = matrix_to_quaternion(t_base_goal[:3, :3])
        safe_log_info(
            self.get_logger(),
            "\n"
            "Aligned TCP goal preview\n"
            f"  marker Z axis in {self.base_frame}: {self._format_vector(info['z_marker_base'])}\n"
            f"  current TCP Z axis in {self.base_frame}: {self._format_vector(info['z_tcp_current'])}\n"
            f"  goal TCP Z axis in {self.base_frame}: {self._format_vector(info['z_tcp_goal'])}\n"
            f"  angle current TCP Z -> goal TCP Z [deg]: "
            f"{info['current_to_goal_angle_deg']:.3f}\n"
            f"  angle goal TCP Z -> desired marker axis [deg]: "
            f"{info['goal_to_desired_angle_deg']:.3f}\n"
            f"  {self.goal_frame} xyz [m]: {self._format_vector(xyz)}\n"
            f"  {self.goal_frame} rpy [deg]: "
            f"{math.degrees(rpy[0]):.3f}, {math.degrees(rpy[1]):.3f}, "
            f"{math.degrees(rpy[2]):.3f}\n"
            f"  {self.goal_frame} quaternion xyzw: {self._format_vector(quaternion)}",
        )

    @staticmethod
    def _normalize(vector, label):
        values = np.asarray(vector, dtype=float).reshape(3)
        norm = float(np.linalg.norm(values))
        if not math.isfinite(norm) or norm < 1e-9:
            raise ValueError(f"{label} is zero or non-finite")
        return values / norm

    @staticmethod
    def _fallback_perpendicular_axis(axis):
        axis = np.asarray(axis, dtype=float).reshape(3)
        candidates = [
            np.array([1.0, 0.0, 0.0], dtype=float),
            np.array([0.0, 1.0, 0.0], dtype=float),
            np.array([0.0, 0.0, 1.0], dtype=float),
        ]
        candidate = min(candidates, key=lambda item: abs(float(np.dot(axis, item))))
        perpendicular = candidate - float(np.dot(candidate, axis)) * axis
        return perpendicular / np.linalg.norm(perpendicular)

    @staticmethod
    def _angle_deg(a, b):
        a = np.asarray(a, dtype=float).reshape(3)
        b = np.asarray(b, dtype=float).reshape(3)
        value = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
        return math.degrees(math.acos(max(-1.0, min(1.0, value))))

    @staticmethod
    def _format_vector(values):
        return ", ".join(f"{float(value):.6f}" for value in values)


def main(args=None):
    rclpy.init(args=args)
    node = AlignToMarkerPreview()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()

