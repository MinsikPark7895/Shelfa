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
            DeclareLaunchArgument("base_frame", default_value="base_link"),
            DeclareLaunchArgument("move_line_service", default_value="/dsr01/motion/move_line"),
            DeclareLaunchArgument("alignment_payload_json", default_value="./realtime_results/alignment_payload.json"),
            DeclareLaunchArgument("save_alignment_payload", default_value="true"),
            DeclareLaunchArgument("shelf_frame", default_value=""),
            DeclareLaunchArgument("aligned_tcp_pose", default_value="0.0,0.0,0.0,180.0,0.0,90.0"),
            DeclareLaunchArgument("target_normal_x", default_value="0.0"),
            DeclareLaunchArgument("target_normal_y", default_value="0.0"),
            DeclareLaunchArgument("target_normal_z", default_value="-1.0"),
            DeclareLaunchArgument("rotate_axis", default_value="none"),
            DeclareLaunchArgument("move_slot_for_rx", default_value="rz"),
            DeclareLaunchArgument("move_slot_for_ry", default_value="ry"),
            DeclareLaunchArgument("move_slot_for_rz", default_value="rz"),
            DeclareLaunchArgument("rotate_sign_for_rx", default_value="1.0"),
            DeclareLaunchArgument("rotate_sign_for_ry", default_value="1.0"),
            DeclareLaunchArgument("rotate_sign_for_rz", default_value="1.0"),
            DeclareLaunchArgument("rotate_deg", default_value="1.0"),
            DeclareLaunchArgument("custom_rx_deg", default_value="0.0"),
            DeclareLaunchArgument("custom_ry_deg", default_value="0.0"),
            DeclareLaunchArgument("custom_rz_deg", default_value="0.0"),
            DeclareLaunchArgument("print_after_move", default_value="true"),
            DeclareLaunchArgument("post_move_delay_sec", default_value="1.0"),
            DeclareLaunchArgument("dry_run", default_value="true"),
            DeclareLaunchArgument("vel_linear", default_value="10.0"),
            DeclareLaunchArgument("vel_angular", default_value="5.0"),
            DeclareLaunchArgument("acc_linear", default_value="20.0"),
            DeclareLaunchArgument("acc_angular", default_value="10.0"),
            DeclareLaunchArgument("ref", default_value="1"),
            DeclareLaunchArgument("mode", default_value="1"),
            Node(
                package="doosan_realsense_handeye",
                executable="aruco_marker_rotation_probe",
                name="aruco_marker_rotation_probe",
                output="screen",
                emulate_tty=True,
                parameters=[
                    {"camera_frame": LaunchConfiguration("camera_frame")},
                    {"marker_frame": LaunchConfiguration("marker_frame")},
                    {"base_frame": LaunchConfiguration("base_frame")},
                    {"move_line_service": LaunchConfiguration("move_line_service")},
                    {"alignment_payload_json": LaunchConfiguration("alignment_payload_json")},
                    {
                        "save_alignment_payload": ParameterValue(
                            LaunchConfiguration("save_alignment_payload"),
                            value_type=bool,
                        )
                    },
                    {"shelf_frame": LaunchConfiguration("shelf_frame")},
                    {"aligned_tcp_pose": LaunchConfiguration("aligned_tcp_pose")},
                    {
                        "target_normal_x": ParameterValue(
                            LaunchConfiguration("target_normal_x"),
                            value_type=float,
                        )
                    },
                    {
                        "target_normal_y": ParameterValue(
                            LaunchConfiguration("target_normal_y"),
                            value_type=float,
                        )
                    },
                    {
                        "target_normal_z": ParameterValue(
                            LaunchConfiguration("target_normal_z"),
                            value_type=float,
                        )
                    },
                    {"rotate_axis": LaunchConfiguration("rotate_axis")},
                    {"move_slot_for_rx": LaunchConfiguration("move_slot_for_rx")},
                    {"move_slot_for_ry": LaunchConfiguration("move_slot_for_ry")},
                    {"move_slot_for_rz": LaunchConfiguration("move_slot_for_rz")},
                    {
                        "rotate_sign_for_rx": ParameterValue(
                            LaunchConfiguration("rotate_sign_for_rx"),
                            value_type=float,
                        )
                    },
                    {
                        "rotate_sign_for_ry": ParameterValue(
                            LaunchConfiguration("rotate_sign_for_ry"),
                            value_type=float,
                        )
                    },
                    {
                        "rotate_sign_for_rz": ParameterValue(
                            LaunchConfiguration("rotate_sign_for_rz"),
                            value_type=float,
                        )
                    },
                    {
                        "rotate_deg": ParameterValue(
                            LaunchConfiguration("rotate_deg"),
                            value_type=float,
                        )
                    },
                    {
                        "custom_rx_deg": ParameterValue(
                            LaunchConfiguration("custom_rx_deg"),
                            value_type=float,
                        )
                    },
                    {
                        "custom_ry_deg": ParameterValue(
                            LaunchConfiguration("custom_ry_deg"),
                            value_type=float,
                        )
                    },
                    {
                        "custom_rz_deg": ParameterValue(
                            LaunchConfiguration("custom_rz_deg"),
                            value_type=float,
                        )
                    },
                    {
                        "print_after_move": ParameterValue(
                            LaunchConfiguration("print_after_move"),
                            value_type=bool,
                        )
                    },
                    {
                        "post_move_delay_sec": ParameterValue(
                            LaunchConfiguration("post_move_delay_sec"),
                            value_type=float,
                        )
                    },
                    {
                        "dry_run": ParameterValue(
                            LaunchConfiguration("dry_run"),
                            value_type=bool,
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
                    {"ref": ParameterValue(LaunchConfiguration("ref"), value_type=int)},
                    {"mode": ParameterValue(LaunchConfiguration("mode"), value_type=int)},
                ],
            ),
        ]
    )
