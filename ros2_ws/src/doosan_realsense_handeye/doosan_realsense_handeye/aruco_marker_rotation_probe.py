import math
import json
import os
import threading
import time
from datetime import datetime

import rclpy
from dsr_msgs2.srv import MoveLine
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from tf2_ros import Buffer, TransformException, TransformListener


class ArucoMarkerRotationProbe(Node):
    def __init__(self):
        super().__init__("aruco_marker_rotation_probe")

        self.declare_parameter("camera_frame", "camera_color_optical_frame")
        self.declare_parameter("marker_frame", "aruco_marker_6")
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("move_line_service", "/dsr01/motion/move_line")
        self.declare_parameter("alignment_payload_json", "./realtime_results/alignment_payload.json")
        self.declare_parameter("save_alignment_payload", True)
        self.declare_parameter("shelf_frame", "")
        self.declare_parameter("aligned_tcp_pose", "0.0,0.0,0.0,180.0,0.0,90.0")
        self.declare_parameter("target_normal_x", 0.0)
        self.declare_parameter("target_normal_y", 0.0)
        self.declare_parameter("target_normal_z", -1.0)
        self.declare_parameter("rotate_axis", "none")
        self.declare_parameter("move_slot_for_rx", "rz")
        self.declare_parameter("move_slot_for_ry", "ry")
        self.declare_parameter("move_slot_for_rz", "rz")
        self.declare_parameter("rotate_sign_for_rx", 1.0)
        self.declare_parameter("rotate_sign_for_ry", 1.0)
        self.declare_parameter("rotate_sign_for_rz", 1.0)
        self.declare_parameter("rotate_deg", 1.0)
        self.declare_parameter("custom_rx_deg", 0.0)
        self.declare_parameter("custom_ry_deg", 0.0)
        self.declare_parameter("custom_rz_deg", 0.0)
        self.declare_parameter("print_after_move", True)
        self.declare_parameter("post_move_delay_sec", 1.0)
        self.declare_parameter("dry_run", True)
        self.declare_parameter("vel_linear", 10.0)
        self.declare_parameter("vel_angular", 5.0)
        self.declare_parameter("acc_linear", 20.0)
        self.declare_parameter("acc_angular", 10.0)
        self.declare_parameter("ref", 1)
        self.declare_parameter("mode", 1)

        self.camera_frame = str(self.get_parameter("camera_frame").value)
        self.marker_frame = str(self.get_parameter("marker_frame").value)
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.move_line_service = str(self.get_parameter("move_line_service").value)
        self.alignment_payload_json = str(self.get_parameter("alignment_payload_json").value)
        self.save_alignment_payload_enabled = bool(self.get_parameter("save_alignment_payload").value)
        self.shelf_frame = str(self.get_parameter("shelf_frame").value) or self.marker_frame
        self.aligned_tcp_pose = self.parse_posx_parameter(
            self.get_parameter("aligned_tcp_pose").value
        )
        self.target_normal = self.normalize(
            (
                float(self.get_parameter("target_normal_x").value),
                float(self.get_parameter("target_normal_y").value),
                float(self.get_parameter("target_normal_z").value),
            )
        )
        self.rotate_axis = str(self.get_parameter("rotate_axis").value).lower()
        self.move_slot_for_rx = str(self.get_parameter("move_slot_for_rx").value).lower()
        self.move_slot_for_ry = str(self.get_parameter("move_slot_for_ry").value).lower()
        self.move_slot_for_rz = str(self.get_parameter("move_slot_for_rz").value).lower()
        self.rotate_sign_for_rx = float(self.get_parameter("rotate_sign_for_rx").value)
        self.rotate_sign_for_ry = float(self.get_parameter("rotate_sign_for_ry").value)
        self.rotate_sign_for_rz = float(self.get_parameter("rotate_sign_for_rz").value)
        self.rotate_deg = float(self.get_parameter("rotate_deg").value)
        self.custom_rx_deg = float(self.get_parameter("custom_rx_deg").value)
        self.custom_ry_deg = float(self.get_parameter("custom_ry_deg").value)
        self.custom_rz_deg = float(self.get_parameter("custom_rz_deg").value)
        self.print_after_move = bool(self.get_parameter("print_after_move").value)
        self.post_move_delay_sec = float(self.get_parameter("post_move_delay_sec").value)
        self.dry_run = bool(self.get_parameter("dry_run").value)
        self.vel_linear = float(self.get_parameter("vel_linear").value)
        self.vel_angular = float(self.get_parameter("vel_angular").value)
        self.acc_linear = float(self.get_parameter("acc_linear").value)
        self.acc_angular = float(self.get_parameter("acc_angular").value)
        self.ref = int(self.get_parameter("ref").value)
        self.mode = int(self.get_parameter("mode").value)

        self.valid_axes = {"none", "rx", "ry", "rz", "raw_rx", "raw_ry", "raw_rz", "custom"}
        if self.rotate_axis not in self.valid_axes:
            raise ValueError(f"rotate_axis must be one of {sorted(self.valid_axes)}")
        self.valid_slots = {"rx", "ry", "rz"}
        self.validate_move_slot("move_slot_for_rx", self.move_slot_for_rx)
        self.validate_move_slot("move_slot_for_ry", self.move_slot_for_ry)
        self.validate_move_slot("move_slot_for_rz", self.move_slot_for_rz)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.move_line_client = self.create_client(MoveLine, self.move_line_service)

        self.get_logger().warn(
            "Rotation probe only measures marker normal and optionally sends one small relative rotation."
        )
        if self.rotate_axis == "none":
            self.get_logger().info("rotate_axis=none: move_line will never be called.")
        elif self.rotate_axis.startswith("raw_"):
            self.get_logger().warn(
                f"rotate_axis={self.rotate_axis}: probing the raw Doosan MoveLine slot directly."
            )
        elif self.rotate_axis == "custom":
            self.get_logger().warn(
                "rotate_axis=custom: probing a custom raw Doosan rotation slot combination."
            )
        elif self.dry_run:
            self.get_logger().warn("dry_run=true: computed MoveLine request will be printed only.")
        else:
            self.get_logger().error(
                f"dry_run=false: Enter may rotate the robot via {self.move_line_service}."
            )
        self.get_logger().info(
            "Probe axis to MoveLine slot mapping: "
            f"rx -> {self.move_slot_for_rx}, "
            f"ry -> {self.move_slot_for_ry}, "
            f"rz -> {self.move_slot_for_rz}"
        )
        self.get_logger().info(
            "Probe axis signs: "
            f"rx={self.rotate_sign_for_rx:.1f}, "
            f"ry={self.rotate_sign_for_ry:.1f}, "
            f"rz={self.rotate_sign_for_rz:.1f}"
        )

    def lookup_marker_pose(self):
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
        rotation = transform.transform.rotation
        matrix = self.quaternion_to_matrix(rotation.x, rotation.y, rotation.z, rotation.w)
        marker_normal = (matrix[0][2], matrix[1][2], matrix[2][2])
        return translation, marker_normal

    def probe_once(self):
        pose = self.lookup_marker_pose()
        if pose is None:
            return

        translation, marker_normal = pose
        self.print_marker_state(translation, marker_normal)
        self.save_alignment_payload(translation, marker_normal)

        if self.rotate_axis == "none":
            return

        request = self.make_move_line_request()
        self.print_request(request)

        if self.dry_run:
            self.get_logger().warn("dry_run=true: skipped move_line service call.")
            return

        if not self.call_move_line(request):
            return

        if self.print_after_move:
            time.sleep(max(0.0, self.post_move_delay_sec))
            after_pose = self.lookup_marker_pose()
            if after_pose is None:
                return
            after_translation, after_normal = after_pose
            self.print_marker_state(after_translation, after_normal)
            self.print_pose_delta(translation, marker_normal, after_translation, after_normal)

    def save_alignment_payload(self, translation, marker_normal_camera):
        if not self.save_alignment_payload_enabled:
            return

        front_direction_base = self.transform_vector_camera_to_base(marker_normal_camera)
        marker_position_base = self.transform_point_camera_to_base(
            (translation.x, translation.y, translation.z)
        )

        if front_direction_base is None:
            self.get_logger().warn(
                "Alignment payload was not saved because camera normal could not be transformed "
                f"from {self.camera_frame} to {self.base_frame}."
            )
            return

        payload = {
            "timestamp": datetime.now().isoformat(),
            "aligned": True,
            "base_frame": self.base_frame,
            "camera_frame": self.camera_frame,
            "marker_frame": self.marker_frame,
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
            "aligned_tcp_pose": [round(float(value), 3) for value in self.aligned_tcp_pose],
            "source": "aruco_marker_rotation_probe",
        }

        os.makedirs(os.path.dirname(self.alignment_payload_json) or ".", exist_ok=True)
        with open(self.alignment_payload_json, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)

        self.get_logger().info(
            f"Alignment payload saved: {self.alignment_payload_json}\n"
            f"  bookshelf_front_direction_base={payload['bookshelf_front_direction_base']}"
        )

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

    def print_marker_state(self, translation, marker_normal):
        target = self.target_normal
        dot = self.clamp_scalar(self.dot(marker_normal, target), -1.0, 1.0)
        angle_error_deg = math.degrees(math.acos(dot))
        normal_x_error = marker_normal[0] - target[0]
        normal_y_error = marker_normal[1] - target[1]

        self.get_logger().info(
            "\n"
            f"Marker pose in {self.camera_frame}\n"
            f"  translation [m]: x={translation.x:.6f}, y={translation.y:.6f}, z={translation.z:.6f}\n"
            f"  marker normal: nx={marker_normal[0]:.6f}, "
            f"ny={marker_normal[1]:.6f}, nz={marker_normal[2]:.6f}\n"
            f"  target normal: tx={target[0]:.6f}, ty={target[1]:.6f}, tz={target[2]:.6f}\n"
            f"  angle_error_deg={angle_error_deg:.3f}\n"
            f"  normal_x_error={normal_x_error:.6f}, normal_y_error={normal_y_error:.6f}"
        )

    def print_pose_delta(self, before_translation, before_normal, after_translation, after_normal):
        translation_dx = after_translation.x - before_translation.x
        translation_dy = after_translation.y - before_translation.y
        translation_dz = after_translation.z - before_translation.z
        normal_dx = after_normal[0] - before_normal[0]
        normal_dy = after_normal[1] - before_normal[1]
        normal_dz = after_normal[2] - before_normal[2]
        before_angle = self.angle_to_target_deg(before_normal)
        after_angle = self.angle_to_target_deg(after_normal)

        self.get_logger().info(
            "\n"
            "After-move delta in camera frame\n"
            f"  translation delta [m]: dx={translation_dx:.6f}, "
            f"dy={translation_dy:.6f}, dz={translation_dz:.6f}\n"
            f"  normal delta: dnx={normal_dx:.6f}, dny={normal_dy:.6f}, dnz={normal_dz:.6f}\n"
            f"  angle_error_delta_deg={after_angle - before_angle:.3f} "
            f"(before={before_angle:.3f}, after={after_angle:.3f})"
        )

    def make_move_line_request(self):
        request = MoveLine.Request()
        request.pos = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        if self.rotate_axis == "custom":
            request.pos[3] = self.custom_rx_deg
            request.pos[4] = self.custom_ry_deg
            request.pos[5] = self.custom_rz_deg
        else:
            move_slot = self.move_slot_for_probe_axis()
            slot_index = {"rx": 3, "ry": 4, "rz": 5}[move_slot]
            request.pos[slot_index] = self.rotate_sign_for_probe_axis() * self.rotate_deg

        request.vel = [self.vel_linear, self.vel_angular]
        request.acc = [self.acc_linear, self.acc_angular]
        request.time = 0.0
        request.radius = 0.0
        request.ref = self.ref
        request.mode = self.mode
        request.blend_type = 0
        request.sync_type = 0
        return request

    def print_request(self, request):
        self.get_logger().info(
            "\n"
            "Computed rotation probe MoveLine request\n"
            f"  {self.request_mapping_summary()}\n"
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
            return False

        self.get_logger().warn(f"Calling {self.move_line_service}")
        future = self.move_line_client.call_async(request)
        start_time = time.monotonic()
        while rclpy.ok() and not future.done():
            if time.monotonic() - start_time > 10.0:
                self.get_logger().error("move_line service call timed out after 10 seconds.")
                return False
            time.sleep(0.05)

        if future.result() is None:
            self.get_logger().error(f"move_line service failed: {future.exception()}")
            return False

        if future.result().success:
            self.get_logger().info("move_line service returned success=true")
            return True
        else:
            self.get_logger().error("move_line service returned success=false")
            return False

    def move_slot_for_probe_axis(self):
        if self.rotate_axis == "raw_rx":
            return "rx"
        if self.rotate_axis == "raw_ry":
            return "ry"
        if self.rotate_axis == "raw_rz":
            return "rz"
        if self.rotate_axis == "rx":
            return self.move_slot_for_rx
        if self.rotate_axis == "ry":
            return self.move_slot_for_ry
        if self.rotate_axis == "rz":
            return self.move_slot_for_rz
        raise ValueError(f"rotate_axis={self.rotate_axis} does not have a single MoveLine slot")

    def rotate_sign_for_probe_axis(self):
        if self.rotate_axis.startswith("raw_"):
            return 1.0
        if self.rotate_axis == "rx":
            return self.rotate_sign_for_rx
        if self.rotate_axis == "ry":
            return self.rotate_sign_for_ry
        if self.rotate_axis == "rz":
            return self.rotate_sign_for_rz
        raise ValueError(f"rotate_axis={self.rotate_axis} does not have a single rotation sign")

    def request_mapping_summary(self):
        if self.rotate_axis == "custom":
            return (
                "rotate_axis=custom, raw MoveLine slots: "
                f"rx={self.custom_rx_deg:.3f} deg, "
                f"ry={self.custom_ry_deg:.3f} deg, "
                f"rz={self.custom_rz_deg:.3f} deg"
            )

        return (
            f"rotate_axis={self.rotate_axis}, move_line_slot={self.move_slot_for_probe_axis()}, "
            f"rotate_sign={self.rotate_sign_for_probe_axis():.1f}, rotate_deg={self.rotate_deg:.3f}"
        )

    def angle_to_target_deg(self, marker_normal):
        dot = self.clamp_scalar(self.dot(marker_normal, self.target_normal), -1.0, 1.0)
        return math.degrees(math.acos(dot))

    def validate_move_slot(self, parameter_name, value):
        if value not in self.valid_slots:
            raise ValueError(f"{parameter_name} must be one of {sorted(self.valid_slots)}")

    @staticmethod
    def parse_posx_parameter(value):
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("[") and text.endswith("]"):
                text = text[1:-1]
            values = [item.strip() for item in text.split(",") if item.strip()]
        else:
            values = list(value)

        if len(values) != 6:
            raise ValueError("aligned_tcp_pose must contain 6 values: x,y,z,rx,ry,rz")

        return [float(item) for item in values]

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
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            raise ValueError("target normal must be non-zero")
        return tuple(value / norm for value in vector)

    @staticmethod
    def dot(left, right):
        return sum(left[index] * right[index] for index in range(3))

    @staticmethod
    def multiply_matrix_vector(matrix, vector):
        return tuple(
            sum(matrix[row][col] * vector[col] for col in range(3))
            for row in range(3)
        )

    @staticmethod
    def clamp_scalar(value, lower, upper):
        return max(lower, min(upper, value))

    @staticmethod
    def format_list(values):
        return "[" + ", ".join(f"{value:.3f}" for value in values) + "]"


def input_loop(node):
    print("Press Enter to print normal/probe one rotation step, q then Enter to quit")
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
            print("Press Enter with no text to probe, or q then Enter to quit")
            continue

        node.probe_once()


def main(args=None):
    rclpy.init(args=args)
    node = ArucoMarkerRotationProbe()
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
