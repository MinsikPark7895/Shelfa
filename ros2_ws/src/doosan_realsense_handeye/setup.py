import os
from glob import glob

from setuptools import find_packages, setup

package_name = "doosan_realsense_handeye"

setup(
    name=package_name,
    version="0.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml", "README.md"]),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="dakae",
    maintainer_email="dakae@todo.todo",
    description="Measurement-only hand-eye calibration tools for Doosan E0509 and RealSense.",
    license="TODO: License declaration",
    extras_require={"test": ["pytest"]},
    entry_points={
        "console_scripts": [
            "handeye_sample_collector = doosan_realsense_handeye.handeye_sample_collector:main",
            "run_handeye_calibration = doosan_realsense_handeye.run_handeye_calibration:main",
            "object_to_base_transformer = doosan_realsense_handeye.object_to_base_transformer:main",
            "validate_handeye = doosan_realsense_handeye.validate_handeye:main",
            "live_target_to_base = doosan_realsense_handeye.live_target_to_base:main",
            "align_to_marker_preview = doosan_realsense_handeye.align_to_marker_preview:main",
            "move_to_approach = doosan_realsense_handeye.move_to_approach:main",
        ],
    },
)
