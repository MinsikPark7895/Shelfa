from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def float_param(name):
    return ParameterValue(LaunchConfiguration(name), value_type=float)


def int_param(name):
    return ParameterValue(LaunchConfiguration(name), value_type=int)


def bool_param(name):
    return ParameterValue(LaunchConfiguration(name), value_type=bool)


def str_param(name):
    return ParameterValue(LaunchConfiguration(name), value_type=str)


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("camera_frame", default_value="camera_color_optical_frame"),
            DeclareLaunchArgument("marker_frame", default_value="aruco_marker_0"),
            DeclareLaunchArgument("marker_frame_prefix", default_value="aruco_marker_"),
            DeclareLaunchArgument("target_marker_id", default_value="-1"),
            DeclareLaunchArgument("move_joint_service", default_value="/dsr01/motion/move_joint"),
            DeclareLaunchArgument("move_line_service", default_value="/dsr01/motion/move_line"),
            DeclareLaunchArgument("current_posx_service", default_value="/dsr01/aux_control/get_current_posx"),
            DeclareLaunchArgument("dry_run", default_value="true"),
            DeclareLaunchArgument("auto_run", default_value="false"),
            DeclareLaunchArgument("auto_step_period_sec", default_value="0.5"),
            DeclareLaunchArgument("auto_post_motion_wait_sec", default_value="1.0"),
            DeclareLaunchArgument("auto_tf_retry_sec", default_value="0.3"),
            DeclareLaunchArgument("auto_max_steps", default_value="300"),
            DeclareLaunchArgument("enable_movej", default_value="true"),
            DeclareLaunchArgument(
                "target_joint_pose_deg",
                default_value="[45.72522, 14.837949, 112.757722, -57.964578, 124.563048, 47.803207]",
            ),
            DeclareLaunchArgument("movej_vel", default_value="20.0"),
            DeclareLaunchArgument("movej_acc", default_value="40.0"),
            DeclareLaunchArgument("movej_time", default_value="0.0"),
            DeclareLaunchArgument("movej_radius", default_value="0.0"),
            DeclareLaunchArgument("movej_mode", default_value="0"),
            DeclareLaunchArgument("movej_blend_type", default_value="0"),
            DeclareLaunchArgument("movej_sync_type", default_value="0"),
            DeclareLaunchArgument("enable_rotation_align", default_value="true"),
            DeclareLaunchArgument("rotation_tolerance_deg", default_value="2.0"),
            DeclareLaunchArgument("max_rot_step_deg", default_value="1.0"),
            DeclareLaunchArgument("sign_tool_b_from_camera_y", default_value="1.0"),
            DeclareLaunchArgument("rot_vel_linear", default_value="10.0"),
            DeclareLaunchArgument("rot_vel_angular", default_value="5.0"),
            DeclareLaunchArgument("rot_acc_linear", default_value="20.0"),
            DeclareLaunchArgument("rot_acc_angular", default_value="10.0"),
            DeclareLaunchArgument("enable_translation_align", default_value="true"),
            DeclareLaunchArgument("enable_coarse_translation_before_rotation", default_value="true"),
            DeclareLaunchArgument("coarse_axis_mode", default_value="all"),
            DeclareLaunchArgument("coarse_translation_scale", default_value="0.5"),
            DeclareLaunchArgument("coarse_max_step_mm", default_value="30.0"),
            DeclareLaunchArgument("target_distance_m", default_value="0.30"),
            DeclareLaunchArgument("tolerance_xy_m", default_value="0.005"),
            DeclareLaunchArgument("tolerance_z_m", default_value="0.010"),
            DeclareLaunchArgument("max_step_mm", default_value="5.0"),
            DeclareLaunchArgument("axis_mode", default_value="largest"),
            DeclareLaunchArgument("tool_axis_from_optical_x", default_value="x"),
            DeclareLaunchArgument("tool_axis_from_optical_y", default_value="y"),
            DeclareLaunchArgument("tool_axis_from_optical_z", default_value="z"),
            DeclareLaunchArgument("sign_tool_from_optical_x", default_value="-1.0"),
            DeclareLaunchArgument("sign_tool_from_optical_y", default_value="-1.0"),
            DeclareLaunchArgument("sign_tool_from_optical_z", default_value="1.0"),
            DeclareLaunchArgument("trans_vel_linear", default_value="15.0"),
            DeclareLaunchArgument("trans_vel_angular", default_value="10.0"),
            DeclareLaunchArgument("trans_acc_linear", default_value="30.0"),
            DeclareLaunchArgument("trans_acc_angular", default_value="20.0"),
            DeclareLaunchArgument("recheck_rotation_after_translation", default_value="false"),
            Node(
                package="doosan_realsense_handeye",
                executable="aruco_marker_proto_align",
                name="aruco_marker_proto_align",
                output="screen",
                emulate_tty=True,
                parameters=[
                    {"camera_frame": str_param("camera_frame")},
                    {"marker_frame": str_param("marker_frame")},
                    {"marker_frame_prefix": str_param("marker_frame_prefix")},
                    {"target_marker_id": int_param("target_marker_id")},
                    {"move_joint_service": str_param("move_joint_service")},
                    {"move_line_service": str_param("move_line_service")},
                    {"current_posx_service": str_param("current_posx_service")},
                    {"dry_run": bool_param("dry_run")},
                    {"auto_run": bool_param("auto_run")},
                    {"auto_step_period_sec": float_param("auto_step_period_sec")},
                    {"auto_post_motion_wait_sec": float_param("auto_post_motion_wait_sec")},
                    {"auto_tf_retry_sec": float_param("auto_tf_retry_sec")},
                    {"auto_max_steps": int_param("auto_max_steps")},
                    {"enable_movej": bool_param("enable_movej")},
                    {"target_joint_pose_deg": LaunchConfiguration("target_joint_pose_deg")},
                    {"movej_vel": float_param("movej_vel")},
                    {"movej_acc": float_param("movej_acc")},
                    {"movej_time": float_param("movej_time")},
                    {"movej_radius": float_param("movej_radius")},
                    {"movej_mode": int_param("movej_mode")},
                    {"movej_blend_type": int_param("movej_blend_type")},
                    {"movej_sync_type": int_param("movej_sync_type")},
                    {"enable_rotation_align": bool_param("enable_rotation_align")},
                    {"rotation_tolerance_deg": float_param("rotation_tolerance_deg")},
                    {"max_rot_step_deg": float_param("max_rot_step_deg")},
                    {"sign_tool_b_from_camera_y": float_param("sign_tool_b_from_camera_y")},
                    {"rot_vel_linear": float_param("rot_vel_linear")},
                    {"rot_vel_angular": float_param("rot_vel_angular")},
                    {"rot_acc_linear": float_param("rot_acc_linear")},
                    {"rot_acc_angular": float_param("rot_acc_angular")},
                    {"enable_translation_align": bool_param("enable_translation_align")},
                    {
                        "enable_coarse_translation_before_rotation": bool_param(
                            "enable_coarse_translation_before_rotation"
                        )
                    },
                    {"coarse_axis_mode": str_param("coarse_axis_mode")},
                    {"coarse_translation_scale": float_param("coarse_translation_scale")},
                    {"coarse_max_step_mm": float_param("coarse_max_step_mm")},
                    {"target_distance_m": float_param("target_distance_m")},
                    {"tolerance_xy_m": float_param("tolerance_xy_m")},
                    {"tolerance_z_m": float_param("tolerance_z_m")},
                    {"max_step_mm": float_param("max_step_mm")},
                    {"axis_mode": str_param("axis_mode")},
                    {"sign_tool_from_optical_x": float_param("sign_tool_from_optical_x")},
                    {"sign_tool_from_optical_y": float_param("sign_tool_from_optical_y")},
                    {"sign_tool_from_optical_z": float_param("sign_tool_from_optical_z")},
                    {"trans_vel_linear": float_param("trans_vel_linear")},
                    {"trans_vel_angular": float_param("trans_vel_angular")},
                    {"trans_acc_linear": float_param("trans_acc_linear")},
                    {"trans_acc_angular": float_param("trans_acc_angular")},
                    {
                        "recheck_rotation_after_translation": bool_param(
                            "recheck_rotation_after_translation"
                        )
                    },
                ],
            ),
        ]
    )
