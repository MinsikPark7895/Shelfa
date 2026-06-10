from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("camera_frame", default_value="camera_color_optical_frame"),
            DeclareLaunchArgument("marker_frame", default_value="aruco_marker_6"),
            DeclareLaunchArgument("move_line_service", default_value="/dsr01/motion/move_line"),
            DeclareLaunchArgument("tolerance_deg", default_value="1.0"),
            DeclareLaunchArgument("max_rot_step_deg", default_value="1.0"),
            DeclareLaunchArgument("sign_tool_b_from_camera_y", default_value="1.0"),
            DeclareLaunchArgument("vel_linear", default_value="10.0"),
            DeclareLaunchArgument("vel_angular", default_value="5.0"),
            DeclareLaunchArgument("acc_linear", default_value="20.0"),
            DeclareLaunchArgument("acc_angular", default_value="10.0"),
            DeclareLaunchArgument("dry_run", default_value="true"),
            Node(
                package="doosan_realsense_handeye",
                executable="aruco_marker_yaw_align",
                name="aruco_marker_yaw_align",
                output="screen",
                emulate_tty=True,
                parameters=[
                    {"camera_frame": LaunchConfiguration("camera_frame")},
                    {"marker_frame": LaunchConfiguration("marker_frame")},
                    {"move_line_service": LaunchConfiguration("move_line_service")},
                    {
                        "tolerance_deg": ParameterValue(
                            LaunchConfiguration("tolerance_deg"),
                            value_type=float,
                        )
                    },
                    {
                        "max_rot_step_deg": ParameterValue(
                            LaunchConfiguration("max_rot_step_deg"),
                            value_type=float,
                        )
                    },
                    {
                        "sign_tool_b_from_camera_y": ParameterValue(
                            LaunchConfiguration("sign_tool_b_from_camera_y"),
                            value_type=float,
                        )
                    },
                    {
                        "vel_linear": ParameterValue(
                            LaunchConfiguration("vel_linear"),
                            value_type=float,
                        )
                    },
                    {
                        "vel_angular": ParameterValue(
                            LaunchConfiguration("vel_angular"),
                            value_type=float,
                        )
                    },
                    {
                        "acc_linear": ParameterValue(
                            LaunchConfiguration("acc_linear"),
                            value_type=float,
                        )
                    },
                    {
                        "acc_angular": ParameterValue(
                            LaunchConfiguration("acc_angular"),
                            value_type=float,
                        )
                    },
                    {
                        "dry_run": ParameterValue(
                            LaunchConfiguration("dry_run"),
                            value_type=bool,
                        )
                    },
                ],
            ),
        ]
    )
