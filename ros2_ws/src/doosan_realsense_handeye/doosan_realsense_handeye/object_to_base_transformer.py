import argparse
from pathlib import Path

import numpy as np
import rclpy
import yaml
from rclpy.duration import Duration
from rclpy.node import Node
from tf2_ros import Buffer, TransformException, TransformListener

from .config_utils import default_config_path, node_parameters
from .logger_utils import safe_log_info
from .transform_utils import matrix_from_yaml_dict, transform_point, transform_stamped_to_matrix


def load_tool_camera(path):
    with Path(path).open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    if "T_tool_camera" not in data:
        raise ValueError(f"{path} does not contain T_tool_camera")
    return matrix_from_yaml_dict(data["T_tool_camera"])


class ObjectToBaseTransformer(Node):
    def __init__(self, point, calibration_result_path, base_frame, tool_frame, tf_timeout_sec):
        super().__init__("object_to_base_transformer")
        self.point = np.asarray(point, dtype=float).reshape(3)
        self.calibration_result_path = calibration_result_path
        self.base_frame = base_frame
        self.tool_frame = tool_frame
        self.tf_timeout_sec = tf_timeout_sec
        self.t_tool_camera = load_tool_camera(self.calibration_result_path)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

    def run_once(self):
        try:
            tf = self.tf_buffer.lookup_transform(
                self.base_frame,
                self.tool_frame,
                rclpy.time.Time(),
                timeout=Duration(seconds=self.tf_timeout_sec),
            )
        except TransformException as exc:
            raise RuntimeError(f"TF lookup failed: {self.base_frame} -> {self.tool_frame}: {exc}")
        t_base_tool = transform_stamped_to_matrix(tf)
        t_base_camera = t_base_tool @ self.t_tool_camera
        point_base = transform_point(t_base_camera, self.point)
        safe_log_info(
            self.get_logger(),
            "P_camera [m]: "
            f"{self.point[0]:.6f}, {self.point[1]:.6f}, {self.point[2]:.6f}",
        )
        safe_log_info(
            self.get_logger(),
            "P_base [m]: "
            f"{point_base[0]:.6f}, {point_base[1]:.6f}, {point_base[2]:.6f}",
        )
        return point_base


def parse_args(args=None):
    defaults = node_parameters("object_to_base_transformer")
    parser = argparse.ArgumentParser(
        description="Transform a 3D point from camera coordinates to Doosan base coordinates."
    )
    parser.add_argument(
        "--config",
        default=str(default_config_path()),
        help="Config YAML used for default frames and calibration path.",
    )
    parser.add_argument("--point", nargs=3, type=float, required=True, metavar=("X", "Y", "Z"))
    parser.add_argument(
        "--calibration-result",
        default=defaults.get(
            "calibration_result_path",
            "/home/user/Shelfa/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_tool_camera.yaml",
        ),
    )
    parser.add_argument("--base-frame", default=defaults.get("base_frame", "base_link"))
    parser.add_argument("--tool-frame", default=defaults.get("tool_frame", "tool0"))
    parser.add_argument("--tf-timeout-sec", type=float, default=defaults.get("tf_timeout_sec", 0.5))
    parsed = parser.parse_args(args)
    if parsed.config != str(default_config_path()):
        custom_defaults = node_parameters("object_to_base_transformer", parsed.config)
        if parsed.calibration_result == parser.get_default("calibration_result"):
            parsed.calibration_result = custom_defaults.get(
                "calibration_result_path",
                parsed.calibration_result,
            )
        if parsed.base_frame == parser.get_default("base_frame"):
            parsed.base_frame = custom_defaults.get("base_frame", parsed.base_frame)
        if parsed.tool_frame == parser.get_default("tool_frame"):
            parsed.tool_frame = custom_defaults.get("tool_frame", parsed.tool_frame)
        if parsed.tf_timeout_sec == parser.get_default("tf_timeout_sec"):
            parsed.tf_timeout_sec = float(
                custom_defaults.get("tf_timeout_sec", parsed.tf_timeout_sec)
            )
    return parsed


def main(args=None):
    parsed = parse_args(args)
    rclpy.init(args=[])
    node = ObjectToBaseTransformer(
        parsed.point,
        parsed.calibration_result,
        parsed.base_frame,
        parsed.tool_frame,
        parsed.tf_timeout_sec,
    )
    try:
        rclpy.spin_once(node, timeout_sec=0.2)
        node.run_once()
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()

