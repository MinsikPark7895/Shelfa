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
        (os.path.join("share", package_name, "urdf"), glob("urdf/*.xacro")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="dakae",
    maintainer_email="dakae@todo.todo",
    description="Doosan E0509 RealSense ArUco alignment helpers.",
    license="TODO: License declaration",
    extras_require={
        "test": [
            "pytest",
        ],
    },
    entry_points={
        "console_scripts": [
            "handeye_sample_collector = doosan_realsense_handeye.handeye_sample_collector:main",
            "run_handeye_calibration = doosan_realsense_handeye.run_handeye_calibration:main",
            "validate_handeye = doosan_realsense_handeye.validate_handeye:main",
            "object_to_base_transformer = doosan_realsense_handeye.object_to_base_transformer:main",
            "live_target_to_base = doosan_realsense_handeye.live_target_to_base:main",
            "align_to_marker_preview = doosan_realsense_handeye.align_to_marker_preview:main",
            "move_to_approach = doosan_realsense_handeye.move_to_approach:main",
            "aruco_marker_step_align = doosan_realsense_handeye.aruco_marker_step_align:main",
            "aruco_marker_rotation_probe = doosan_realsense_handeye.aruco_marker_rotation_probe:main",
            "aruco_marker_yaw_align = doosan_realsense_handeye.aruco_marker_yaw_align:main",
            "aruco_marker_proto_align = doosan_realsense_handeye.aruco_marker_proto_align:main",
            "aruco_maker_proto_align = doosan_realsense_handeye.aruco_maker_proto_align:main",
            "aruco_handeye_target_tf = doosan_realsense_handeye.aruco_handeye_target_tf:main",
            "simple_aruco_marker_tf_publisher = doosan_realsense_handeye.simple_aruco_marker_tf_publisher:main",
            "tf_book_target_to_approach = doosan_realsense_handeye.tf_book_target_to_approach:main",
            "realtime_yolo_paddle_ocr = doosan_realsense_handeye.realtime_yolo_paddle_ocr:main",
            "book_scan_after_alignment = doosan_realsense_handeye.book_scan_after_alignment:main",
            "marker_book_pipeline = doosan_realsense_handeye.marker_book_pipeline:main",
            "book_visual_servo_align = doosan_realsense_handeye.book_visual_servo_align:main",
            "book_pick_sequence_node = doosan_realsense_handeye.book_pick_sequence_node:main",
            "book_mission_state_machine = doosan_realsense_handeye.book_mission_state_machine:main",
            "controller_loader = doosan_realsense_handeye.controller_loader:main",
            "aruco_realsense_tf_publisher = doosan_realsense_handeye.aruco_realsense_tf_publisher:main",
        ],
    },
)
