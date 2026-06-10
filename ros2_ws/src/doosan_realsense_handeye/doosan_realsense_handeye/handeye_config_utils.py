from pathlib import Path

import yaml


PACKAGE_NAME = "doosan_realsense_handeye"
CONFIG_RELATIVE_PATH = Path("config") / "handeye_servo.yaml"


def package_root_from_source():
    return Path(__file__).resolve().parents[1]


def default_config_path():
    try:
        from ament_index_python.packages import get_package_share_directory

        share_path = Path(get_package_share_directory(PACKAGE_NAME))
        config_path = share_path / CONFIG_RELATIVE_PATH
        if config_path.exists():
            return config_path
    except Exception:
        pass
    return package_root_from_source() / CONFIG_RELATIVE_PATH


def load_config(config_path=None):
    path = Path(config_path) if config_path else default_config_path()
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    return data


def node_parameters(node_name, config_path=None):
    data = load_config(config_path)
    node_config = data.get(node_name, {})
    return node_config.get("ros__parameters", {})
