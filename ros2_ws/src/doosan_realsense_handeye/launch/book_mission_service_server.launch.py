from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    default_config = PathJoinSubstitution(
        [
            FindPackageShare("doosan_realsense_handeye"),
            "config",
            "book_mission_service_server.yaml",
        ]
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument("config_file", default_value=default_config),
            DeclareLaunchArgument("dry_run", default_value="true"),
            DeclareLaunchArgument("dry_run_contract_mode", default_value="true"),
            DeclareLaunchArgument("auto_run", default_value="true"),
            DeclareLaunchArgument("publish_camera_static_tf", default_value="true"),
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="link6_to_camera_static_tf",
                output="screen",
                condition=IfCondition(LaunchConfiguration("publish_camera_static_tf")),
                arguments=[
                    "--x",
                    "0.047696284489303686",
                    "--y",
                    "-0.04076754872954019",
                    "--z",
                    "0.06633768863669905",
                    "--qx",
                    "0.5047148772454931",
                    "--qy",
                    "0.5057702861100585",
                    "--qz",
                    "0.4949917689883712",
                    "--qw",
                    "-0.49441122459849096",
                    "--frame-id",
                    "link_6",
                    "--child-frame-id",
                    "camera_link",
                ],
            ),
            Node(
                package="doosan_realsense_handeye",
                executable="book_mission_service_server",
                name="book_mission_service_server",
                output="screen",
                emulate_tty=True,
                parameters=[
                    LaunchConfiguration("config_file"),
                    {
                        "dry_run": ParameterValue(
                            LaunchConfiguration("dry_run"), value_type=bool
                        ),
                        "dry_run_contract_mode": ParameterValue(
                            LaunchConfiguration("dry_run_contract_mode"), value_type=bool
                        ),
                        "auto_run": ParameterValue(
                            LaunchConfiguration("auto_run"), value_type=bool
                        ),
                    },
                ],
            ),
        ]
    )
