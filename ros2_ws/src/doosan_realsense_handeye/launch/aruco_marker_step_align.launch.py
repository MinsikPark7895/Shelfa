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
            DeclareLaunchArgument("axis_mode", default_value="all"),
            DeclareLaunchArgument("target_distance_m", default_value="0.30"),
            DeclareLaunchArgument("tolerance_xy_m", default_value="0.005"),
            DeclareLaunchArgument("tolerance_z_m", default_value="0.010"),
            DeclareLaunchArgument("max_step_mm", default_value="5.0"),
            DeclareLaunchArgument("vel_linear", default_value="10.0"),
            DeclareLaunchArgument("vel_angular", default_value="10.0"),
            DeclareLaunchArgument("acc_linear", default_value="20.0"),
            DeclareLaunchArgument("acc_angular", default_value="20.0"),
            DeclareLaunchArgument("tool_axis_from_optical_x", default_value="x"),
            DeclareLaunchArgument("tool_axis_from_optical_y", default_value="y"),
            DeclareLaunchArgument("tool_axis_from_optical_z", default_value="z"),
            DeclareLaunchArgument("sign_tool_from_optical_x", default_value="-1.0"),
            DeclareLaunchArgument("sign_tool_from_optical_y", default_value="-1.0"),
            DeclareLaunchArgument("sign_tool_from_optical_z", default_value="1.0"),
            DeclareLaunchArgument("dry_run", default_value="true"),
            Node(
                package="doosan_realsense_handeye",
                executable="aruco_marker_step_align",
                name="aruco_marker_step_align",
                output="screen",
                emulate_tty=True,
                parameters=[
                    {"camera_frame": LaunchConfiguration("camera_frame")},
                    {"marker_frame": LaunchConfiguration("marker_frame")},
                    {"move_line_service": LaunchConfiguration("move_line_service")},
                    {"axis_mode": LaunchConfiguration("axis_mode")},
                    {
                        "target_distance_m": ParameterValue(
                            LaunchConfiguration("target_distance_m"),
                            value_type=float,
                        )
                    },
                    {
                        "tolerance_xy_m": ParameterValue(
                            LaunchConfiguration("tolerance_xy_m"),
                            value_type=float,
                        )
                    },
                    {
                        "tolerance_z_m": ParameterValue(
                            LaunchConfiguration("tolerance_z_m"),
                            value_type=float,
                        )
                    },
                    {
                        "max_step_mm": ParameterValue(
                            LaunchConfiguration("max_step_mm"),
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
                    {"tool_axis_from_optical_x": LaunchConfiguration("tool_axis_from_optical_x")},
                    {"tool_axis_from_optical_y": LaunchConfiguration("tool_axis_from_optical_y")},
                    {"tool_axis_from_optical_z": LaunchConfiguration("tool_axis_from_optical_z")},
                    {
                        "sign_tool_from_optical_x": ParameterValue(
                            LaunchConfiguration("sign_tool_from_optical_x"),
                            value_type=float,
                        )
                    },
                    {
                        "sign_tool_from_optical_y": ParameterValue(
                            LaunchConfiguration("sign_tool_from_optical_y"),
                            value_type=float,
                        )
                    },
                    {
                        "sign_tool_from_optical_z": ParameterValue(
                            LaunchConfiguration("sign_tool_from_optical_z"),
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
