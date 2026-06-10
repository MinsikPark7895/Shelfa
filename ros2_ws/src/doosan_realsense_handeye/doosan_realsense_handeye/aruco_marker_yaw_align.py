import math
import threading
import time

import rclpy
from dsr_msgs2.srv import MoveLine
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from tf2_ros import Buffer, TransformException, TransformListener


class ArucoMarkerYawAlign(Node):
    def __init__(self):
        super().__init__("aruco_marker_yaw_align")

        self.declare_parameter("camera_frame", "camera_color_optical_frame")
        self.declare_parameter("marker_frame", "aruco_marker_6")
        self.declare_parameter("move_line_service", "/dsr01/motion/move_line")
        self.declare_parameter("tolerance_deg", 1.0)
        self.declare_parameter("max_rot_step_deg", 1.0)
        self.declare_parameter("sign_tool_b_from_camera_y", 1.0)
        self.declare_parameter("vel_linear", 10.0)
        self.declare_parameter("vel_angular", 5.0)
        self.declare_parameter("acc_linear", 20.0)
        self.declare_parameter("acc_angular", 10.0)
        self.declare_parameter("dry_run", True)

        self.camera_frame = str(self.get_parameter("camera_frame").value)
        self.marker_frame = str(self.get_parameter("marker_frame").value)
        self.move_line_service = str(self.get_parameter("move_line_service").value)
        self.tolerance_deg = float(self.get_parameter("tolerance_deg").value)
        self.max_rot_step_deg = float(self.get_parameter("max_rot_step_deg").value)
        self.sign_tool_b_from_camera_y = float(
            self.get_parameter("sign_tool_b_from_camera_y").value
        )
        self.vel_linear = float(self.get_parameter("vel_linear").value)
        self.vel_angular = float(self.get_parameter("vel_angular").value)
        self.acc_linear = float(self.get_parameter("acc_linear").value)
        self.acc_angular = float(self.get_parameter("acc_angular").value)
        self.dry_run = bool(self.get_parameter("dry_run").value)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.move_line_client = self.create_client(MoveLine, self.move_line_service)

        self.get_logger().warn(
            "This node only aligns camera-frame Y rotation using Doosan MoveLine B, pos[4]."
        )
        self.get_logger().warn("MoveLine pos[3] and pos[5] are always kept at 0.0.")
        if self.dry_run:
            self.get_logger().warn("dry_run=true: move_line will NOT be called.")
        else:
            self.get_logger().error(
                f"dry_run=false: Enter may rotate the robot via {self.move_line_service}."
            )

    def lookup_marker_z_axis(self):
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

        rotation = transform.transform.rotation
        matrix = self.quaternion_to_matrix(rotation.x, rotation.y, rotation.z, rotation.w)
        marker_z_in_camera = (matrix[0][2], matrix[1][2], matrix[2][2])
        return marker_z_in_camera

    def run_one_step(self):
        marker_z = self.lookup_marker_z_axis()
        if marker_z is None:
            return

        angle_y_rad = math.atan2(marker_z[0], -marker_z[2])
        angle_y_deg = math.degrees(angle_y_rad)

        self.get_logger().info(
            "\n"
            f"Marker local Z axis in {self.camera_frame}\n"
            f"  marker_z_in_camera: x={marker_z[0]:.6f}, "
            f"y={marker_z[1]:.6f}, z={marker_z[2]:.6f}\n"
            f"  angle_y_deg={angle_y_deg:.3f}\n"
            f"  tolerance_deg={self.tolerance_deg:.3f}"
        )

        if abs(angle_y_deg) < self.tolerance_deg:
            self.get_logger().info("aligned: Y rotation error is within tolerance. No movement sent.")
            return

        raw_step_deg = self.sign_tool_b_from_camera_y * angle_y_deg
        move_b_deg = self.clamp(raw_step_deg, self.max_rot_step_deg)
        request = self.make_move_line_request(move_b_deg)
        self.print_request(request, angle_y_deg, raw_step_deg, move_b_deg)

        if self.dry_run:
            self.get_logger().warn("dry_run=true: skipped move_line service call.")
            return

        self.call_move_line(request)

    def make_move_line_request(self, move_b_deg):
        request = MoveLine.Request()
        request.pos = [0.0, 0.0, 0.0, 0.0, move_b_deg, 0.0]
        request.vel = [self.vel_linear, self.vel_angular]
        request.acc = [self.acc_linear, self.acc_angular]
        request.time = 0.0
        request.radius = 0.0
        request.ref = 1
        request.mode = 1
        request.blend_type = 0
        request.sync_type = 0
        return request

    def print_request(self, request, angle_y_deg, raw_step_deg, move_b_deg):
        self.get_logger().info(
            "\n"
            "Computed Y rotation alignment MoveLine request\n"
            f"  angle_y_deg={angle_y_deg:.3f}\n"
            f"  sign_tool_b_from_camera_y={self.sign_tool_b_from_camera_y:.1f}\n"
            f"  raw_step_deg={raw_step_deg:.3f}, move_b_deg={move_b_deg:.3f}\n"
            f"  pos [mm,deg]: {self.format_list(request.pos)}\n"
            f"  vel: {self.format_list(request.vel)}\n"
            f"  acc: {self.format_list(request.acc)}\n"
            f"  time={request.time:.3f}, radius={request.radius:.3f}, "
            f"ref={request.ref}, mode={request.mode}, "
            f"blend_type={request.blend_type}, sync_type={request.sync_type}"
        )

    def call_move_line(self, request):
        if not self.move_line_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().error(
                f"Service not available: {self.move_line_service}. No rotation sent."
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

        if future.result().success:
            self.get_logger().info("move_line service returned success=true")
        else:
            self.get_logger().error("move_line service returned success=false")

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
    def clamp(value, max_abs):
        if max_abs <= 0.0:
            return 0.0
        return max(-max_abs, min(max_abs, value))

    @staticmethod
    def format_list(values):
        return "[" + ", ".join(f"{value:.3f}" for value in values) + "]"


def input_loop(node):
    print("Press Enter to calculate/send one Y rotation step, q then Enter to quit")
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
            print("Press Enter with no text to step, or q then Enter to quit")
            continue

        node.run_one_step()


def main(args=None):
    rclpy.init(args=args)
    node = ArucoMarkerYawAlign()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    try:
        input_loop(node)
    except KeyboardInterrupt:
        node.get_logger().warn("Interrupted; exiting without sending another rotation.")
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        spin_thread.join(timeout=1.0)


if __name__ == "__main__":
    main()
