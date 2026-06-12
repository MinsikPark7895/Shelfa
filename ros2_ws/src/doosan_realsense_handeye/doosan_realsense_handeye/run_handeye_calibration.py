import argparse
from pathlib import Path

import cv2
import numpy as np
import yaml

from .config_utils import default_config_path, node_parameters
from .transform_utils import matrix_from_yaml_dict, matrix_to_yaml_dict, make_transform


METHODS = {
    "TSAI": cv2.CALIB_HAND_EYE_TSAI,
    "PARK": cv2.CALIB_HAND_EYE_PARK,
    "HORAUD": cv2.CALIB_HAND_EYE_HORAUD,
    "ANDREFF": cv2.CALIB_HAND_EYE_ANDREFF,
    "DANIILIDIS": cv2.CALIB_HAND_EYE_DANIILIDIS,
}


def load_samples(path):
    with Path(path).open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    samples = data.get("samples", [])
    if len(samples) < 3:
        raise ValueError(f"At least 3 samples are required, got {len(samples)}")
    return data, samples


def calibrate(samples, method_name):
    method_key = method_name.upper()
    if method_key not in METHODS:
        raise ValueError(f"Unsupported method '{method_name}'. Choose one of {sorted(METHODS)}")

    rotations_gripper2base = []
    translations_gripper2base = []
    rotations_target2cam = []
    translations_target2cam = []

    for sample in samples:
        t_base_tool = matrix_from_yaml_dict(sample["T_base_tool"])
        t_camera_target = matrix_from_yaml_dict(sample["T_camera_target"])
        rotations_gripper2base.append(t_base_tool[:3, :3])
        translations_gripper2base.append(t_base_tool[:3, 3].reshape(3, 1))
        rotations_target2cam.append(t_camera_target[:3, :3])
        translations_target2cam.append(t_camera_target[:3, 3].reshape(3, 1))

    rotation_cam2gripper, translation_cam2gripper = cv2.calibrateHandEye(
        rotations_gripper2base,
        translations_gripper2base,
        rotations_target2cam,
        translations_target2cam,
        method=METHODS[method_key],
    )
    return make_transform(rotation_cam2gripper, np.asarray(translation_cam2gripper).reshape(3))


def write_result(path, transform, method_name, sample_count, metadata):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {
            "unit": "meter",
            "transform": "T_tool_camera",
            "opencv_output": "R_cam2gripper, t_cam2gripper",
            "handeye_method": method_name.upper(),
            "sample_count": int(sample_count),
            "base_frame": metadata.get("base_frame"),
            "tool_frame": metadata.get("tool_frame"),
            "camera_frame": metadata.get("camera_frame"),
        },
        "T_tool_camera": matrix_to_yaml_dict(transform),
    }
    with output_path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(payload, stream, sort_keys=False)
    return output_path


def parse_args(args=None):
    collector_defaults = node_parameters("handeye_sample_collector")
    parser = argparse.ArgumentParser(
        description="Run OpenCV hand-eye calibration from saved Doosan/RealSense samples."
    )
    parser.add_argument(
        "--config",
        default=str(default_config_path()),
        help="Config YAML used for default paths and method.",
    )
    parser.add_argument(
        "--samples",
        default=collector_defaults.get(
            "sample_save_path",
            "/home/user/Shelfa/ros2_ws/src/doosan_realsense_handeye/data/samples/handeye_samples.yaml",
        ),
    )
    parser.add_argument(
        "--output",
        default=collector_defaults.get(
            "calibration_result_path",
            "/home/user/Shelfa/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_tool_camera.yaml",
        ),
    )
    parser.add_argument(
        "--method",
        default=str(collector_defaults.get("handeye_method", "TSAI")).upper(),
        choices=sorted(METHODS),
    )
    parsed = parser.parse_args(args)
    if parsed.config != str(default_config_path()):
        custom_defaults = node_parameters("handeye_sample_collector", parsed.config)
        if parsed.samples == parser.get_default("samples"):
            parsed.samples = custom_defaults.get("sample_save_path", parsed.samples)
        if parsed.output == parser.get_default("output"):
            parsed.output = custom_defaults.get("calibration_result_path", parsed.output)
        if parsed.method == parser.get_default("method"):
            parsed.method = str(custom_defaults.get("handeye_method", parsed.method)).upper()
    return parsed


def main(args=None):
    parsed = parse_args(args)
    data, samples = load_samples(parsed.samples)
    transform = calibrate(samples, parsed.method)
    output_path = write_result(
        parsed.output,
        transform,
        parsed.method,
        len(samples),
        data.get("metadata", {}),
    )
    translation = transform[:3, 3]
    print(f"Saved T_tool_camera to {output_path}")
    print(
        "translation [m]: "
        f"x={translation[0]:.6f}, y={translation[1]:.6f}, z={translation[2]:.6f}"
    )


if __name__ == "__main__":
    main()

