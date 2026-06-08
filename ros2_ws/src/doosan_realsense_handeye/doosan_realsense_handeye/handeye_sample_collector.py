import select
import sys
import termios
import threading
import time
import tty
from pathlib import Path

import rclpy
import yaml
from cv_bridge import CvBridge
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener

from .charuco_detector import BoardPoseDetector, camera_info_to_matrices
from .config_utils import nested_get, node_parameters
from .transform_utils import matrix_to_yaml_dict, transform_stamped_to_matrix


class HandeyeSampleCollector(Node):
    def __init__(self):
        super().__init__("handeye_sample_collector")
        self._declare_parameters()
        self._read_parameters()

        self.bridge = CvBridge()
        self.latest_image = None
        self.latest_camera_info = None
        self.latest_detection = None
        self.latest_detection_stamp = 0.0

        self.detector = BoardPoseDetector(
            self.board_type,
            self.board_config,
            self.get_logger(),
            log_period_sec=self.detection_log_period_sec,
        )
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.create_subscription(Image, self.color_image_topic, self._on_image, 10)
        self.create_subscription(CameraInfo, self.camera_info_topic, self._on_camera_info, 10)
        self.create_service(Trigger, "~/save_sample", self._on_save_sample)

        self.get_logger().warn(
            "Measurement-only collector. Move the robot manually, then press 's' "
            "or call ~/save_sample. This node never sends robot motion commands."
        )
        self.get_logger().info(
            f"Frames: {self.base_frame} -> {self.tool_frame}, camera={self.camera_frame}; "
            f"topics: image={self.color_image_topic}, camera_info={self.camera_info_topic}"
        )

    def _declare_parameters(self):
        defaults = node_parameters("handeye_sample_collector")
        self.declare_parameter("base_frame", defaults.get("base_frame", "base_link"))
        self.declare_parameter("tool_frame", defaults.get("tool_frame", "tool0"))
        self.declare_parameter(
            "camera_frame",
            defaults.get("camera_frame", "camera_color_optical_frame"),
        )
        self.declare_parameter(
            "color_image_topic",
            defaults.get("color_image_topic", "/camera/camera/color/image_raw"),
        )
        self.declare_parameter(
            "camera_info_topic",
            defaults.get("camera_info_topic", "/camera/camera/color/camera_info"),
        )
        self.declare_parameter("board_type", defaults.get("board_type", "charuco"))
        self.declare_parameter(
            "sample_save_path",
            defaults.get(
                "sample_save_path",
                "/home/dakae/ros2_ws/src/doosan_realsense_handeye/data/samples/handeye_samples.yaml",
            ),
        )
        self.declare_parameter(
            "calibration_result_path",
            defaults.get(
                "calibration_result_path",
                "/home/dakae/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_tool_camera.yaml",
            ),
        )
        self.declare_parameter("handeye_method", defaults.get("handeye_method", "TSAI"))
        self.declare_parameter("tf_timeout_sec", defaults.get("tf_timeout_sec", 0.5))
        self.declare_parameter(
            "min_detection_interval_sec",
            defaults.get("min_detection_interval_sec", 0.05),
        )
        self.declare_parameter(
            "detection_log_period_sec",
            defaults.get("detection_log_period_sec", 2.0),
        )
        self.declare_parameter("charuco.squares_x", nested_get(defaults, "charuco.squares_x", 7))
        self.declare_parameter("charuco.squares_y", nested_get(defaults, "charuco.squares_y", 5))
        self.declare_parameter(
            "charuco.square_length",
            nested_get(defaults, "charuco.square_length", 0.030),
        )
        self.declare_parameter(
            "charuco.marker_length",
            nested_get(defaults, "charuco.marker_length", 0.022),
        )
        self.declare_parameter(
            "charuco.dictionary",
            nested_get(defaults, "charuco.dictionary", "DICT_5X5_100"),
        )
        self.declare_parameter(
            "charuco.min_corners",
            nested_get(defaults, "charuco.min_corners", 6),
        )
        self.declare_parameter(
            "aruco.marker_length",
            nested_get(defaults, "aruco.marker_length", 0.050),
        )
        self.declare_parameter("aruco.marker_id", nested_get(defaults, "aruco.marker_id", 6))
        self.declare_parameter(
            "aruco.dictionary",
            nested_get(defaults, "aruco.dictionary", "DICT_5X5_100"),
        )

    def _read_parameters(self):
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.tool_frame = str(self.get_parameter("tool_frame").value)
        self.camera_frame = str(self.get_parameter("camera_frame").value)
        self.color_image_topic = str(self.get_parameter("color_image_topic").value)
        self.camera_info_topic = str(self.get_parameter("camera_info_topic").value)
        self.board_type = str(self.get_parameter("board_type").value).lower()
        self.sample_save_path = str(self.get_parameter("sample_save_path").value)
        self.handeye_method = str(self.get_parameter("handeye_method").value)
        self.tf_timeout_sec = float(self.get_parameter("tf_timeout_sec").value)
        self.min_detection_interval_sec = float(
            self.get_parameter("min_detection_interval_sec").value
        )
        self.detection_log_period_sec = float(
            self.get_parameter("detection_log_period_sec").value
        )
        self.board_config = {
            "charuco": {
                "squares_x": int(self.get_parameter("charuco.squares_x").value),
                "squares_y": int(self.get_parameter("charuco.squares_y").value),
                "square_length": float(self.get_parameter("charuco.square_length").value),
                "marker_length": float(self.get_parameter("charuco.marker_length").value),
                "dictionary": str(self.get_parameter("charuco.dictionary").value),
                "min_corners": int(self.get_parameter("charuco.min_corners").value),
            },
            "aruco": {
                "marker_length": float(self.get_parameter("aruco.marker_length").value),
                "marker_id": int(self.get_parameter("aruco.marker_id").value),
                "dictionary": str(self.get_parameter("aruco.dictionary").value),
            },
        }

    def _on_camera_info(self, msg):
        self.latest_camera_info = msg

    def _on_image(self, msg):
        self.latest_image = msg
        if self.latest_camera_info is None:
            self.get_logger().warn("Waiting for CameraInfo before board pose estimation")
            return
        now = time.monotonic()
        if now - self.latest_detection_stamp < self.min_detection_interval_sec:
            return
        self.latest_detection_stamp = now
        try:
            image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().error(f"cv_bridge conversion failed: {exc}")
            return

        camera_matrix, dist_coeffs = camera_info_to_matrices(self.latest_camera_info)
        self.latest_detection = self.detector.estimate(image, camera_matrix, dist_coeffs)

    def _on_save_sample(self, request, response):
        ok, message = self.save_sample()
        response.success = bool(ok)
        response.message = message
        return response

    def save_sample(self):
        if self.latest_camera_info is None:
            return False, "No CameraInfo received yet"
        if self.latest_detection is None:
            return False, "No valid board detection available in the latest image"
        try:
            tf = self.tf_buffer.lookup_transform(
                self.base_frame,
                self.tool_frame,
                rclpy.time.Time(),
                timeout=Duration(seconds=self.tf_timeout_sec),
            )
        except TransformException as exc:
            message = f"TF lookup failed: {self.base_frame} -> {self.tool_frame}: {exc}"
            self.get_logger().error(message)
            return False, message

        t_base_tool = transform_stamped_to_matrix(tf)
        t_camera_target = self.latest_detection["T_camera_target"]
        sample_path = Path(self.sample_save_path)
        sample_path.parent.mkdir(parents=True, exist_ok=True)
        data = self._read_sample_file(sample_path)
        samples = data.setdefault("samples", [])
        sample = {
            "index": len(samples) + 1,
            "timestamp": self.get_clock().now().nanoseconds / 1e9,
            "base_frame": self.base_frame,
            "tool_frame": self.tool_frame,
            "camera_frame": self.camera_frame,
            "T_base_tool": matrix_to_yaml_dict(t_base_tool),
            "T_camera_target": matrix_to_yaml_dict(t_camera_target),
            "detection": self.latest_detection["info"],
        }
        samples.append(sample)
        data["metadata"] = {
            "unit": "meter",
            "base_frame": self.base_frame,
            "tool_frame": self.tool_frame,
            "camera_frame": self.camera_frame,
            "board_type": self.board_type,
            "handeye_method": self.handeye_method,
            "note": "Robot motion is manual; samples are saved only on explicit user command.",
        }
        with sample_path.open("w", encoding="utf-8") as stream:
            yaml.safe_dump(data, stream, sort_keys=False)
        message = f"Saved sample {len(samples)} to {sample_path}"
        self.get_logger().info(message)
        return True, message

    @staticmethod
    def _read_sample_file(sample_path):
        if not sample_path.exists():
            return {"metadata": {}, "samples": []}
        with sample_path.open("r", encoding="utf-8") as stream:
            data = yaml.safe_load(stream) or {}
        data.setdefault("samples", [])
        return data


def keyboard_loop(node, stop_event):
    if not sys.stdin.isatty():
        node.get_logger().warn(
            "Keyboard input is not a TTY; use /handeye_sample_collector/save_sample instead."
        )
        return
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        node.get_logger().info("Keyboard: press 's' to save a sample, 'q' to quit.")
        while rclpy.ok() and not stop_event.is_set():
            readable, _, _ = select.select([sys.stdin], [], [], 0.1)
            if not readable:
                continue
            char = sys.stdin.read(1)
            if char == "s":
                ok, message = node.save_sample()
                if not ok:
                    node.get_logger().warn(message)
            elif char == "q":
                stop_event.set()
                rclpy.shutdown()
                return
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def main(args=None):
    rclpy.init(args=args)
    node = HandeyeSampleCollector()
    stop_event = threading.Event()
    keyboard_thread = threading.Thread(target=keyboard_loop, args=(node, stop_event), daemon=True)
    keyboard_thread.start()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
