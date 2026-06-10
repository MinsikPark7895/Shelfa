import threading
import time

import rclpy
from dsr_msgs2.srv import MoveLine
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from tf2_ros import Buffer, TransformException, TransformListener


class ArucoMarkerStepAlign(Node):
    def __init__(self):
        super().__init__("aruco_marker_step_align")

        self.declare_parameter("camera_frame", "camera_color_optical_frame")
        self.declare_parameter("marker_frame", "aruco_marker_6")
        self.declare_parameter("move_line_service", "/dsr01/motion/move_line")
        self.declare_parameter("axis_mode", "all")
        self.declare_parameter("target_distance_m", 0.30)
        self.declare_parameter("tolerance_xy_m", 0.005)
        self.declare_parameter("tolerance_z_m", 0.010)
        self.declare_parameter("max_step_mm", 5.0)
        self.declare_parameter("vel_linear", 10.0)
        self.declare_parameter("vel_angular", 10.0)
        self.declare_parameter("acc_linear", 20.0)
        self.declare_parameter("acc_angular", 20.0)
        self.declare_parameter("tool_axis_from_optical_x", "x")
        self.declare_parameter("tool_axis_from_optical_y", "y")
        self.declare_parameter("tool_axis_from_optical_z", "z")
        self.declare_parameter("sign_tool_from_optical_x", -1.0)
        self.declare_parameter("sign_tool_from_optical_y", -1.0)
        self.declare_parameter("sign_tool_from_optical_z", 1.0)
        self.declare_parameter("dry_run", True)

        self.camera_frame = str(self.get_parameter("camera_frame").value)
        self.marker_frame = str(self.get_parameter("marker_frame").value)
        self.move_line_service = str(self.get_parameter("move_line_service").value)
        self.axis_mode = str(self.get_parameter("axis_mode").value)
        self.target_distance_m = float(self.get_parameter("target_distance_m").value)
        self.tolerance_xy_m = float(self.get_parameter("tolerance_xy_m").value)
        self.tolerance_z_m = float(self.get_parameter("tolerance_z_m").value)
        self.max_step_mm = float(self.get_parameter("max_step_mm").value)
        self.vel_linear = float(self.get_parameter("vel_linear").value)
        self.vel_angular = float(self.get_parameter("vel_angular").value)
        self.acc_linear = float(self.get_parameter("acc_linear").value)
        self.acc_angular = float(self.get_parameter("acc_angular").value)
        self.tool_axis_from_optical_x = str(self.get_parameter("tool_axis_from_optical_x").value)
        self.tool_axis_from_optical_y = str(self.get_parameter("tool_axis_from_optical_y").value)
        self.tool_axis_from_optical_z = str(self.get_parameter("tool_axis_from_optical_z").value)
        self.sign_tool_from_optical_x = float(self.get_parameter("sign_tool_from_optical_x").value)
        self.sign_tool_from_optical_y = float(self.get_parameter("sign_tool_from_optical_y").value)
        self.sign_tool_from_optical_z = float(self.get_parameter("sign_tool_from_optical_z").value)
        self.dry_run = bool(self.get_parameter("dry_run").value)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.move_line_client = self.create_client(MoveLine, self.move_line_service)
        self.valid_axis_modes = {"all", "z_only", "x_only", "y_only", "xy_only", "largest"}
        self.valid_tool_axes = {"x", "y", "z"}
        if self.axis_mode not in self.valid_axis_modes:
            raise ValueError(
                f"axis_mode must be one of {sorted(self.valid_axis_modes)}, got '{self.axis_mode}'"
            )
        self.validate_tool_axis("tool_axis_from_optical_x", self.tool_axis_from_optical_x)
        self.validate_tool_axis("tool_axis_from_optical_y", self.tool_axis_from_optical_y)
        self.validate_tool_axis("tool_axis_from_optical_z", self.tool_axis_from_optical_z)

        self.get_logger().warn(
            "This node only performs step translation alignment. It does not rotate-align the camera."
        )
        self.get_logger().info(f"axis_mode={self.axis_mode}")
        self.get_logger().info(
            "Optical-to-tool mapping: "
            f"optical X -> tool {self.tool_axis_from_optical_x.upper()} "
            f"sign={self.sign_tool_from_optical_x:.1f}, "
            f"optical Y -> tool {self.tool_axis_from_optical_y.upper()} "
            f"sign={self.sign_tool_from_optical_y:.1f}, "
            f"optical Z -> tool {self.tool_axis_from_optical_z.upper()} "
            f"sign={self.sign_tool_from_optical_z:.1f}"
        )
        if self.dry_run:
            self.get_logger().warn("dry_run is true: move_line will NOT be called.")
        else:
            self.get_logger().error(
                f"dry_run is false: this node may move the robot via {self.move_line_service}."
            )

    def lookup_marker(self):
        try:
            transform = self.tf_buffer.lookup_transform(
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

        translation = transform.transform.translation
        return (translation.x, translation.y, translation.z)

    def run_one_step(self):
        marker_position = self.lookup_marker()
        if marker_position is None:
            return

        current_x, current_y, current_z = marker_position
        error_x = current_x
        error_y = current_y
        error_z = current_z - self.target_distance_m

        self.get_logger().info(
            "\n"
            f"Marker in {self.camera_frame} [m]\n"
            f"  x={current_x:.6f}, y={current_y:.6f}, z={current_z:.6f}\n"
            f"  target distance z={self.target_distance_m:.6f} m\n"
            f"  error [m]: x={error_x:.6f}, y={error_y:.6f}, z={error_z:.6f}"
        )

        if (
            abs(error_x) < self.tolerance_xy_m
            and abs(error_y) < self.tolerance_xy_m
            and abs(error_z) < self.tolerance_z_m
        ):
            self.get_logger().info("aligned: within x/y/z tolerances. No movement sent.")
            return

        move_tool_x_mm, move_tool_y_mm, move_tool_z_mm, active_axes = self.compute_tool_step(
            error_x,
            error_y,
            error_z,
        )

        request = MoveLine.Request()
        request.pos = [move_tool_x_mm, move_tool_y_mm, move_tool_z_mm, 0.0, 0.0, 0.0]
        request.vel = [self.vel_linear, self.vel_angular]
        request.acc = [self.acc_linear, self.acc_angular]
        request.time = 0.0
        request.radius = 0.0
        request.ref = 1
        request.mode = 1
        request.blend_type = 0
        request.sync_type = 0

        self.print_request(request, active_axes)

        if self.dry_run:
            self.get_logger().warn("dry_run=true: skipped move_line service call.")
            return

        self.call_move_line(request)

    def call_move_line(self, request):
        if not self.move_line_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().error(
                f"Service not available: {self.move_line_service}. No movement sent."
            )
            return

        self.get_logger().warn(f"Calling {self.move_line_service}")
        future = self.move_line_client.call_async(request)
        start_time = time.monotonic()
        while rclpy.ok() and not future.done():
            if time.monotonic() - start_time > 10.0:
                self.get_logger().error("move_line service call timed out after 10 seconds.")
                return
            time.sleep(0.05)

        if future.result() is None:
            self.get_logger().error(f"move_line service failed: {future.exception()}")
            return

        response = future.result()
        if response.success:
            self.get_logger().info("move_line service returned success=true")
        else:
            self.get_logger().error("move_line service returned success=false")

    def selected_optical_axes(self, error_x, error_y, error_z):
        if self.axis_mode == "all":
            return ["optical_x", "optical_y", "optical_z"]
        if self.axis_mode == "z_only":
            return ["optical_z"]
        if self.axis_mode == "x_only":
            return ["optical_x"]
        if self.axis_mode == "y_only":
            return ["optical_y"]
        if self.axis_mode == "xy_only":
            return ["optical_x", "optical_y"]

        normalized_errors = {
            "optical_z": abs(error_z) / self.tolerance_z_m if self.tolerance_z_m > 0.0 else 0.0,
            "optical_x": abs(error_x) / self.tolerance_xy_m if self.tolerance_xy_m > 0.0 else 0.0,
            "optical_y": abs(error_y) / self.tolerance_xy_m if self.tolerance_xy_m > 0.0 else 0.0,
        }
        return [max(normalized_errors, key=normalized_errors.get)]

    def compute_tool_step(self, error_x, error_y, error_z):
        selected_axes = self.selected_optical_axes(error_x, error_y, error_z)
        move_by_tool_axis = {"x": 0.0, "y": 0.0, "z": 0.0}
        active_axes = []

        corrections = {
            "optical_x": (
                self.tool_axis_from_optical_x,
                self.sign_tool_from_optical_x * error_x * 1000.0,
            ),
            "optical_y": (
                self.tool_axis_from_optical_y,
                self.sign_tool_from_optical_y * error_y * 1000.0,
            ),
            "optical_z": (
                self.tool_axis_from_optical_z,
                self.sign_tool_from_optical_z * error_z * 1000.0,
            ),
        }

        for optical_axis in selected_axes:
            tool_axis, correction_mm = corrections[optical_axis]
            move_by_tool_axis[tool_axis] += correction_mm
            active_axes.append(f"{optical_axis}->tool_{tool_axis}")

        return (
            self.clamp(move_by_tool_axis["x"], self.max_step_mm),
            self.clamp(move_by_tool_axis["y"], self.max_step_mm),
            self.clamp(move_by_tool_axis["z"], self.max_step_mm),
            active_axes,
        )

    def print_request(self, request, active_axes):
        self.get_logger().info(
            "\n"
            "Computed MoveLine request\n"
            f"  axis_mode={self.axis_mode}, active_axes={active_axes}\n"
            "  optical-to-tool mapping:\n"
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
    def format_list(values):
        return "[" + ", ".join(f"{value:.3f}" for value in values) + "]"


def input_loop(node):
    print("Press Enter to compute one alignment step, q then Enter to quit")
    while rclpy.ok():
        try:
            command = input("> ").strip().lower()
        except EOFError:
            break
        except KeyboardInterrupt:
            raise

        if command == "q":
            break
        if command:
            print("Press Enter with no text to compute one step, or q then Enter to quit")
            continue

        node.run_one_step()


def main(args=None):
    rclpy.init(args=args)
    node = ArucoMarkerStepAlign()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    try:
        input_loop(node)
    except KeyboardInterrupt:
        node.get_logger().warn("Interrupted; exiting without sending another movement.")
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
        spin_thread.join(timeout=1.0)


if __name__ == "__main__":
    main()
