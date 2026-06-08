from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    default_config = PathJoinSubstitution(
        [FindPackageShare("doosan_realsense_handeye"), "config", "handeye_config.yaml"]
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument("config_file", default_value=default_config),
            Node(
                package="doosan_realsense_handeye",
                executable="validate_handeye",
                name="validate_handeye",
                output="screen",
                arguments=[
                    "--config",
                    LaunchConfiguration("config_file"),
                ],
            ),
        ]
    )
