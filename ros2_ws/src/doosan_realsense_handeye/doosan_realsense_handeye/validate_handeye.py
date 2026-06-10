import argparse
import math
from pathlib import Path

import numpy as np
import yaml

from .config_utils import default_config_path, node_parameters
from .transform_utils import invert_transform, matrix_from_yaml_dict, rotation_angle_rad


def load_yaml(path):
    with Path(path).open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def load_tool_camera(path):
    data = load_yaml(path)
    if "T_tool_camera" not in data:
        raise ValueError(f"{path} does not contain T_tool_camera")
    return matrix_from_yaml_dict(data["T_tool_camera"])


def compute_validation(samples, t_tool_camera):
    transforms = []
    for sample in samples:
        t_base_tool = matrix_from_yaml_dict(sample["T_base_tool"])
        t_camera_target = matrix_from_yaml_dict(sample["T_camera_target"])
        transforms.append(t_base_tool @ t_tool_camera @ t_camera_target)

    translations = np.asarray([transform[:3, 3] for transform in transforms], dtype=float)
    mean_translation = np.mean(translations, axis=0)
    residuals = translations - mean_translation
    norms = np.linalg.norm(residuals, axis=1)

    rotations = [transform[:3, :3] for transform in transforms]
    reference_rotation = rotations[0]
    rotation_errors_deg = [
        math.degrees(rotation_angle_rad(reference_rotation.T @ rotation)) for rotation in rotations
    ]

    return {
        "count": len(samples),
        "mean_translation": mean_translation,
        "std_translation": np.std(translations, axis=0),
        "max_error_m": float(np.max(norms)),
        "rmse_m": float(math.sqrt(np.mean(norms * norms))),
        "per_sample_error_m": norms,
        "rotation_error_mean_deg": float(np.mean(rotation_errors_deg)),
        "rotation_error_max_deg": float(np.max(rotation_errors_deg)),
        "base_target_transforms": transforms,
    }


def print_report(report):
    mean = report["mean_translation"]
    std = report["std_translation"]
    print("Hand-eye validation from fixed target samples")
    print(f"  sample count: {report['count']}")
    print(f"  mean target position [m]: {mean[0]:.6f}, {mean[1]:.6f}, {mean[2]:.6f}")
    print(f"  std xyz [m]: {std[0]:.6f}, {std[1]:.6f}, {std[2]:.6f}")
    print(f"  max translation error: {report['max_error_m'] * 1000.0:.3f} mm")
    print(f"  translation RMSE: {report['rmse_m'] * 1000.0:.3f} mm")
    print(f"  mean rotation error from sample 1: {report['rotation_error_mean_deg']:.3f} deg")
    print(f"  max rotation error from sample 1: {report['rotation_error_max_deg']:.3f} deg")


def parse_args(args=None):
    defaults = node_parameters("validate_handeye")
    parser = argparse.ArgumentParser(
        description="Validate T_tool_camera by checking fixed board stability in base frame."
    )
    parser.add_argument(
        "--config",
        default=str(default_config_path()),
        help="Config YAML used for default sample and calibration paths.",
    )
    parser.add_argument(
        "--samples",
        default=defaults.get(
            "sample_save_path",
            "/home/dakae/ros2_ws/src/doosan_realsense_handeye/data/samples/handeye_samples.yaml",
        ),
    )
    parser.add_argument(
        "--calibration-result",
        default=defaults.get(
            "calibration_result_path",
            "/home/dakae/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_tool_camera.yaml",
        ),
    )
    parsed = parser.parse_args(args)
    if parsed.config != str(default_config_path()):
        custom_defaults = node_parameters("validate_handeye", parsed.config)
        if parsed.samples == parser.get_default("samples"):
            parsed.samples = custom_defaults.get("sample_save_path", parsed.samples)
        if parsed.calibration_result == parser.get_default("calibration_result"):
            parsed.calibration_result = custom_defaults.get(
                "calibration_result_path",
                parsed.calibration_result,
            )
    return parsed


def main(args=None):
    parsed = parse_args(args)
    samples_data = load_yaml(parsed.samples)
    samples = samples_data.get("samples", [])
    if len(samples) < 3:
        raise SystemExit(f"At least 3 samples are required, got {len(samples)}")
    t_tool_camera = load_tool_camera(parsed.calibration_result)
    report = compute_validation(samples, t_tool_camera)
    print_report(report)


if __name__ == "__main__":
    main()
