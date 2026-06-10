import math
import time
from pathlib import Path

import numpy as np
import rclpy
import yaml
from cv_bridge import CvBridge
from geometry_msgs.msg import TransformStamped
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import Buffer, TransformBroadcaster, TransformException, TransformListener

from .charuco_detector import BoardPoseDetector, camera_info_to_matrices
from .config_utils import nested_get, node_parameters
from .logger_utils import safe_log_info
from .transform_utils import (
    make_transform,
    matrix_from_yaml_dict,
    matrix_to_euler_xyz,
    matrix_to_quaternion,
    transform_stamped_to_matrix,
)


class LiveTargetToBase(Node):
    def __init__(self):
        super().__init__("live_target_to_base")
        self._declare_parameters()
        self._read_parameters()

        self.bridge = CvBridge()
        self.latest_camera_info = None
        self.latest_detection_time = 0.0
        self.latest_output_time = 0.0
        self.t_link6_camera = self._load_calibration_result(self.calibration_result_path)
        self.t_target_approach = make_transform(
            translation=[
                self.approach_offset_x,
                self.approach_offset_y,
                self.approach_offset_z,
            ]
        )

        self.detector = BoardPoseDetector(
            self.board_type,
            self.board_config,
            self.get_logger(),
            log_period_sec=self.detection_log_period_sec,
        )
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.tf_broadcaster = TransformBroadcaster(self)

        self.create_subscription(CameraInfo, self.camera_info_topic, self._on_camera_info, 10)
        self.create_subscription(Image, self.color_image_topic, self._on_image, 10)

        self.get_logger().warn(
            "Measurement-only live target transform. This node reads image, camera_info, TF, "
            "and calibration YAML only; it never sends robot motion commands."
        )
        safe_log_info(
            self.get_logger(),
            f"Using {self.base_frame} -> {self.tool_frame} and calibration "
            f"{self.calibration_result_path}. The T_tool_camera YAML key is interpreted as "
            f"T_{self.tool_frame}_camera for this setup.",
        )
        safe_log_info(
            self.get_logger(),
            "Target approach offset in target frame [m]: "
            f"x={self.approach_offset_x:.6f}, "
            f"y={self.approach_offset_y:.6f}, "
            f"z={self.approach_offset_z:.6f}",
        )

    def _declare_parameters(self):
        live_defaults = node_parameters("live_target_to_base")
        collector_defaults = node_parameters("handeye_sample_collector")
        defaults = {**collector_defaults, **live_defaults}
        self.declare_parameter("base_frame", defaults.get("base_frame", "base_link"))
        self.declare_parameter("tool_frame", defaults.get("tool_frame", "link_6"))
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
            "calibration_result_path",
            defaults.get(
                "calibration_result_path",
                "/home/user/Shelfa/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_tool_camera.yaml",
            ),
        )
        self.declare_parameter("tf_timeout_sec", defaults.get("tf_timeout_sec", 0.5))
        self.declare_parameter(
            "min_detection_interval_sec",
            defaults.get("min_detection_interval_sec", 0.05),
        )
        self.declare_parameter(
            "detection_log_period_sec",
            defaults.get("detection_log_period_sec", 2.0),
        )
        self.declare_parameter(
            "target_output_period_sec",
            defaults.get("target_output_period_sec", 0.5),
        )
        self.declare_parameter(
            "approach_offset_x",
            defaults.get("approach_offset_x", 0.0),
        )
        self.declare_parameter(
            "approach_offset_y",
            defaults.get("approach_offset_y", 0.0),
        )
        self.declare_parameter(
            "approach_offset_z",
            defaults.get("approach_offset_z", 0.10),
        )
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
        self.calibration_result_path = str(self.get_parameter("calibration_result_path").value)
        self.tf_timeout_sec = float(self.get_parameter("tf_timeout_sec").value)
        self.min_detection_interval_sec = float(
            self.get_parameter("min_detection_interval_sec").value
        )
        self.detection_log_period_sec = float(
            self.get_parameter("detection_log_period_sec").value
        )
        self.target_output_period_sec = float(
            self.get_parameter("target_output_period_sec").value
        )
        self.approach_offset_x = float(self.get_parameter("approach_offset_x").value)
        self.approach_offset_y = float(self.get_parameter("approach_offset_y").value)
        self.approach_offset_z = float(self.get_parameter("approach_offset_z").value)
        self.target_frame_name = str(self.get_parameter("target_frame_name").value)
        self.approach_frame_name = str(self.get_parameter("approach_frame_name").value)
        self.publish_aligned_goal = bool(self.get_parameter("publish_aligned_goal").value)
        self.goal_frame_name = str(self.get_parameter("goal_frame_name").value)
        self.align_axis = str(self.get_parameter("align_axis").value).lower()
        self.axis_direction = str(self.get_parameter("axis_direction").value).lower()
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
        if self.align_axis != "z":
            raise ValueError("align_axis currently supports only 'z'")
        if self.axis_direction not in ("same", "opposite"):
            raise ValueError("axis_direction must be 'same' or 'opposite'")

    def _load_calibration_result(self, calibration_result_path):
        with Path(calibration_result_path).open("r", encoding="utf-8") as stream:
            data = yaml.safe_load(stream) or {}
        if "T_tool_camera" not in data:
            raise ValueError(f"{calibration_result_path} does not contain T_tool_camera")
        return matrix_from_yaml_dict(data["T_tool_camera"])

    def _on_camera_info(self, msg):
        self.latest_camera_info = msg

    def _on_image(self, msg):
        if self.latest_camera_info is None:
            self.get_logger().warn("Waiting for CameraInfo before board pose estimation")
            return

        now = time.monotonic()
        if now - self.latest_detection_time < self.min_detection_interval_sec:
            return
        self.latest_detection_time = now

        try:
            image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().error(f"cv_bridge conversion failed: {exc}")
            return

        camera_matrix, dist_coeffs = camera_info_to_matrices(self.latest_camera_info)
        detection = self.detector.estimate(image, camera_matrix, dist_coeffs)
        if detection is None:
            return

        try:
            tf = self.tf_buffer.lookup_transform(
                self.base_frame,
                self.tool_frame,
                rclpy.time.Time(),
                timeout=Duration(seconds=self.tf_timeout_sec),
            )
        except TransformException as exc:
            self.get_logger().warn(
                f"TF lookup failed: {self.base_frame} -> {self.tool_frame}: {exc}"
            )
            return

        t_base_link6 = transform_stamped_to_matrix(tf)
        t_camera_target = detection["T_camera_target"]
        t_base_target = t_base_link6 @ self.t_link6_camera @ t_camera_target
        t_base_approach = t_base_target @ self.t_target_approach
        stamp = self.get_clock().now().to_msg()
        self._publish_pose_tf(t_base_target, self.target_frame_name, stamp)
        self._publish_pose_tf(t_base_approach, self.approach_frame_name, stamp)
        self._print_target_pose(t_base_target, t_base_approach, detection["info"])

    def _print_target_pose(self, t_base_target, t_base_approach, detection_info):
        now = time.monotonic()
        if now - self.latest_output_time < self.target_output_period_sec:
            return
        self.latest_output_time = now

        target_translation, target_euler = self._pose_components(t_base_target)
        approach_translation, approach_euler = self._pose_components(t_base_approach)
        safe_log_info(
            self.get_logger(),
            "\n"
            f"T_{self.base_frame}_target from live {self.board_type} detection\n"
            f"  target xyz [m]: {target_translation[0]:.6f}, "
            f"{target_translation[1]:.6f}, {target_translation[2]:.6f}\n"
            f"  target rpy [deg]: {math.degrees(target_euler[0]):.3f}, "
            f"{math.degrees(target_euler[1]):.3f}, {math.degrees(target_euler[2]):.3f}\n"
            f"  approach xyz [m]: {approach_translation[0]:.6f}, "
            f"{approach_translation[1]:.6f}, {approach_translation[2]:.6f}\n"
            f"  approach rpy [deg]: {math.degrees(approach_euler[0]):.3f}, "
            f"{math.degrees(approach_euler[1]):.3f}, "
            f"{math.degrees(approach_euler[2]):.3f}\n"
            f"  detection: markers={detection_info.get('marker_count')}, "
            f"corners={detection_info.get('corner_count')}, "
            f"dictionary={detection_info.get('dictionary')}, "
            f"marker_id={detection_info.get('marker_id', 'n/a')}",
        )

    def _publish_pose_tf(self, transform, child_frame_id, stamp):
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

    @staticmethod
    def _pose_components(transform):
        translation = transform[:3, 3]
        euler = matrix_to_euler_xyz(transform[:3, :3])
        return translation, euler


def main(args=None):
    rclpy.init(args=args)
    node = LiveTargetToBase()
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

