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
            Node(
                package="doosan_realsense_handeye",
                executable="move_to_approach",
                name="move_to_approach",
                output="screen",
                emulate_tty=True,
                parameters=[LaunchConfiguration("config_file")],
            ),
        ]
    )

