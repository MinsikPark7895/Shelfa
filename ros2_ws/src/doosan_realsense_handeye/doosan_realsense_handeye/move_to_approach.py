import math
import time

import numpy as np
import rclpy
from dsr_msgs2.srv import GetCurrentPosx, MoveLine
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from tf2_ros import Buffer, TransformException, TransformListener

from .config_utils import node_parameters
from .logger_utils import safe_log_info
from .transform_utils import transform_stamped_to_matrix


class MoveToApproach(Node):
    def __init__(self):
        super().__init__("move_to_approach")
        self._declare_parameters()
        self._read_parameters()

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.current_posx_client = self.create_client(GetCurrentPosx, self.current_posx_service)
        self.move_line_client = self.create_client(MoveLine, self.move_service)
        self._has_run = False
        self._current_posx_start_time = None
        self._move_line_start_time = None
        self._pending_current_posx_future = None
        self._pending_move_line_future = None
        self._plan_context = None
        self.create_timer(0.5, self._run_once)

        self.get_logger().warn(
            "One-shot approach motion test. execute=false by default, so no robot motion "
            "service is called unless execute:=true is explicitly set."
        )

    def _declare_parameters(self):
        defaults = node_parameters("move_to_approach")
        self.declare_parameter("base_frame", defaults.get("base_frame", "base_link"))
        self.declare_parameter("tool_frame", defaults.get("tool_frame", "link_6"))
        self.declare_parameter("target_frame", defaults.get("target_frame", "target_approach"))
        self.declare_parameter("execute", defaults.get("execute", False))
        self.declare_parameter("max_step_m", defaults.get("max_step_m", 0.30))
        self.declare_parameter("vel", defaults.get("vel", 20.0))
        self.declare_parameter("acc", defaults.get("acc", 40.0))
        self.declare_parameter(
            "move_service",
            defaults.get("move_service", "/dsr01/motion/move_line"),
        )
        self.declare_parameter(
            "current_posx_service",
            defaults.get("current_posx_service", "/dsr01/aux_control/get_current_posx"),
        )
        self.declare_parameter("task_ref", defaults.get("task_ref", 0))
        self.declare_parameter("tf_timeout_sec", defaults.get("tf_timeout_sec", 0.5))
        self.declare_parameter("service_timeout_sec", defaults.get("service_timeout_sec", 10.0))

    def _read_parameters(self):
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.tool_frame = str(self.get_parameter("tool_frame").value)
        self.target_frame = str(self.get_parameter("target_frame").value)
        self.execute = bool(self.get_parameter("execute").value)
        self.max_step_m = float(self.get_parameter("max_step_m").value)
        self.vel = float(self.get_parameter("vel").value)
        self.acc = float(self.get_parameter("acc").value)
        self.move_service = str(self.get_parameter("move_service").value)
        self.current_posx_service = str(self.get_parameter("current_posx_service").value)
        self.task_ref = int(self.get_parameter("task_ref").value)
        self.tf_timeout_sec = float(self.get_parameter("tf_timeout_sec").value)
        self.service_timeout_sec = float(self.get_parameter("service_timeout_sec").value)

    def _run_once(self):
        if self._pending_current_posx_future is not None:
            if time.monotonic() - self._current_posx_start_time > self.service_timeout_sec:
                self.get_logger().error(
                    f"get_current_posx service call timed out after "
                    f"{self.service_timeout_sec:.1f} seconds. No movement sent."
                )
                self._pending_current_posx_future = None
                self._shutdown()
            return
        if self._pending_move_line_future is not None:
            if time.monotonic() - self._move_line_start_time > self.service_timeout_sec:
                self.get_logger().error(
                    f"move_line service call timed out after {self.service_timeout_sec:.1f} seconds."
                )
                self._pending_move_line_future = None
                self._shutdown()
            return
        if self._has_run:
            return
        self._has_run = True

        try:
            current_tf = self._lookup_transform(self.base_frame, self.tool_frame)
            target_tf = self._lookup_transform(self.base_frame, self.target_frame)
        except TransformException as exc:
            self.get_logger().error(f"Required TF lookup failed. No movement sent: {exc}")
            self._shutdown()
            return

        t_base_tool = transform_stamped_to_matrix(current_tf)
        t_base_target = transform_stamped_to_matrix(target_tf)

        current_xyz = t_base_tool[:3, 3]
        target_xyz = t_base_target[:3, 3]

        if not self._valid_vector(current_xyz) or not self._valid_vector(target_xyz):
            self.get_logger().error("Current or target translation contains NaN/Inf. No movement sent.")
            self._shutdown()
            return
        if self.max_step_m <= 0.0 or not math.isfinite(self.max_step_m):
            self.get_logger().error("max_step_m must be finite and positive. No movement sent.")
            self._shutdown()
            return

        distance_m = float(np.linalg.norm(target_xyz - current_xyz))
        self._request_current_task_pose(current_xyz, target_xyz, distance_m)

    def _lookup_transform(self, parent_frame, child_frame):
        return self.tf_buffer.lookup_transform(
            parent_frame,
            child_frame,
            rclpy.time.Time(),
            timeout=Duration(seconds=self.tf_timeout_sec),
        )

    def _request_current_task_pose(self, current_xyz, target_xyz, distance_m):
        if not self.current_posx_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().error(
                f"Service not available: {self.current_posx_service}. "
                "Cannot read current Doosan task pose, so no movement sent."
            )
            self._shutdown()
            return

        request = GetCurrentPosx.Request()
        request.ref = self.task_ref
        self._plan_context = {
            "current_xyz": current_xyz,
            "target_xyz": target_xyz,
            "distance_m": distance_m,
        }
        self._current_posx_start_time = time.monotonic()
        self._pending_current_posx_future = self.current_posx_client.call_async(request)
        self._pending_current_posx_future.add_done_callback(self._on_current_posx_done)

    def _on_current_posx_done(self, future):
        self._pending_current_posx_future = None
        if future.result() is None:
            self.get_logger().error(
                f"get_current_posx service call failed: {future.exception()}. No movement sent."
            )
            self._shutdown()
            return

        current_task_pose = self._extract_current_task_pose(future.result())
        if current_task_pose is None:
            self._shutdown()
            return

        context = self._plan_context or {}
        current_xyz = context.get("current_xyz")
        target_xyz = context.get("target_xyz")
        distance_m = context.get("distance_m")
        request = self._make_move_line_request(target_xyz, current_task_pose)
        self._print_plan(current_xyz, target_xyz, current_task_pose, distance_m, request)

        if distance_m > self.max_step_m:
            self.get_logger().error(
                f"Distance {distance_m:.6f} m exceeds max_step_m={self.max_step_m:.6f}. "
                "No movement sent."
            )
            self._shutdown()
            return

        if not self.execute:
            self.get_logger().warn("execute=false: dry run only. Skipped move_line service call.")
            self._shutdown()
            return

        self._call_move_line(request)

    def _extract_current_task_pose(self, response):
        if not response.success:
            self.get_logger().error("get_current_posx returned success=false. No movement sent.")
            return None
        if not response.task_pos_info:
            self.get_logger().error("get_current_posx returned no task_pos_info. No movement sent.")
            return None

        values = list(response.task_pos_info[0].data)
        if len(values) < 6:
            self.get_logger().error(
                f"get_current_posx returned {len(values)} task pose values; expected at least 6. "
                "No movement sent."
            )
            return None

        pose = np.asarray(values[:6], dtype=float)
        if not self._valid_vector(pose):
            self.get_logger().error("Current Doosan task pose contains NaN/Inf. No movement sent.")
            return None
        return pose

    def _make_move_line_request(self, target_xyz_m, current_task_pose):
        request = MoveLine.Request()
        request.pos = [
            float(target_xyz_m[0] * 1000.0),
            float(target_xyz_m[1] * 1000.0),
            float(target_xyz_m[2] * 1000.0),
            float(current_task_pose[3]),
            float(current_task_pose[4]),
            float(current_task_pose[5]),
        ]
        request.vel = [self.vel, self.vel]
        request.acc = [self.acc, self.acc]
        request.time = 0.0
        request.radius = 0.0
        request.ref = 0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 0
        return request

    def _print_plan(self, current_xyz, target_xyz, current_task_pose, distance_m, request):
        safe_log_info(
            self.get_logger(),
            "\n"
            "Computed one-shot Doosan MoveLine plan to target_approach\n"
            f"  current {self.tool_frame} xyz [m]: "
            f"{current_xyz[0]:.6f}, {current_xyz[1]:.6f}, {current_xyz[2]:.6f}\n"
            f"  target {self.target_frame} xyz [m]: "
            f"{target_xyz[0]:.6f}, {target_xyz[1]:.6f}, {target_xyz[2]:.6f}\n"
            f"  current Doosan task pose [mm,deg]: {self._format_list(current_task_pose)}\n"
            f"  distance current->target [m]: {distance_m:.6f}\n"
            f"  final MoveLine pos [mm,deg]: {self._format_list(request.pos)}\n"
            f"  vel [mm/s,deg/s]: {self._format_list(request.vel)}\n"
            f"  acc [mm/s^2,deg/s^2]: {self._format_list(request.acc)}\n"
            f"  ref={request.ref} (DR_BASE), mode={request.mode} (ABS), "
            f"blend_type={request.blend_type}, sync_type={request.sync_type}\n"
            f"  current_posx_service={self.current_posx_service}, task_ref={self.task_ref}\n"
            f"  move_service={self.move_service}\n"
            f"  execute={self.execute}",
        )

    def _call_move_line(self, request):
        if not self.move_line_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().error(f"Service not available: {self.move_service}. No movement sent.")
            self._shutdown()
            return

        self.get_logger().warn(f"execute=true: calling {self.move_service} exactly once.")
        self._move_line_start_time = time.monotonic()
        self._pending_move_line_future = self.move_line_client.call_async(request)
        self._pending_move_line_future.add_done_callback(self._on_move_line_done)

    def _on_move_line_done(self, future):
        self._pending_move_line_future = None
        if future.result() is None:
            self.get_logger().error(f"move_line service call failed: {future.exception()}")
            self._shutdown()
            return

        response = future.result()
        if response.success:
            safe_log_info(self.get_logger(), "move_line service returned success=true")
        else:
            self.get_logger().error("move_line service returned success=false")
        self._shutdown()

    @staticmethod
    def _valid_vector(values):
        return bool(np.all(np.isfinite(np.asarray(values, dtype=float))))

    @staticmethod
    def _format_list(values):
        return "[" + ", ".join(f"{float(value):.3f}" for value in values) + "]"

    def _shutdown(self):
        safe_log_info(self.get_logger(), "move_to_approach finished.")
        rclpy.shutdown()


def main(args=None):
    rclpy.init(args=args)
    node = MoveToApproach()
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
