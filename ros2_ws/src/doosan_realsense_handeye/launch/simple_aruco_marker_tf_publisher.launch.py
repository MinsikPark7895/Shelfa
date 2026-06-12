from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            Node(
                package="doosan_realsense_handeye",
                executable="simple_aruco_marker_tf_publisher",
                name="simple_aruco_marker_tf_publisher",
                output="screen",
            )
        ]
    )
