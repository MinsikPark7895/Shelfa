from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    config_path = PathJoinSubstitution(
        [FindPackageShare("doosan_realsense_handeye"), "config", "handeye_servo.yaml"]
    )

    return LaunchDescription(
        [
            Node(
                package="doosan_realsense_handeye",
                executable="aruco_handeye_target_tf",
                name="aruco_handeye_target_tf",
                output="screen",
                parameters=[config_path],
            )
        ]
    )
