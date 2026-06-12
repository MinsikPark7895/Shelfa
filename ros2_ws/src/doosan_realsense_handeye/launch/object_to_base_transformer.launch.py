from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    default_config = PathJoinSubstitution(
        [FindPackageShare("doosan_realsense_handeye"), "config", "handeye_servo.yaml"]
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument("config_file", default_value=default_config),
            DeclareLaunchArgument("x", default_value="0.1"),
            DeclareLaunchArgument("y", default_value="0.0"),
            DeclareLaunchArgument("z", default_value="0.5"),
            Node(
                package="doosan_realsense_handeye",
                executable="object_to_base_transformer",
                name="object_to_base_transformer",
                output="screen",
                arguments=[
                    "--config",
                    LaunchConfiguration("config_file"),
                    "--point",
                    LaunchConfiguration("x"),
                    LaunchConfiguration("y"),
                    LaunchConfiguration("z"),
                ],
            ),
        ]
    )

