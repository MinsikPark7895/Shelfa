import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node

def generate_launch_description():
    pkg_gazebo_ros = get_package_share_directory('gazebo_ros')
    pkg_turtlebot3_gazebo = get_package_share_directory('turtlebot3_gazebo')

    # Gazebo 모델 패스 환경변수 설정
    shelfa_dir = '/home/minsik/Desktop/Shelfa'
    gazebo_model_path = os.environ.get('GAZEBO_MODEL_PATH', '')
    if gazebo_model_path:
        gazebo_model_path += ':'
    gazebo_model_path += os.path.join(shelfa_dir, 'worlds', 'model_editor_models') + ':' + \
                         os.path.join(shelfa_dir, 'worlds', 'building_editor_models') + ':' + \
                         os.path.join(pkg_turtlebot3_gazebo, 'models')

    # TurtleBot3 모델 설정
    os.environ['TURTLEBOT3_MODEL'] = 'waffle_pi'

    # 월드 파일 경로
    world_file_path = os.path.join(shelfa_dir, 'worlds', 'library_layout.world')

    # SDF 모델 파일 경로 (waffle_pi)
    urdf_path = os.path.join(
        pkg_turtlebot3_gazebo, 'models', 'turtlebot3_waffle_pi', 'model.sdf'
    )

    # Gazebo 서버 실행
    gzserver_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_gazebo_ros, 'launch', 'gzserver.launch.py')
        ),
        launch_arguments={'world': world_file_path}.items()
    )

    # Gazebo 클라이언트 실행
    gzclient_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_gazebo_ros, 'launch', 'gzclient.launch.py')
        )
    )

    # 로봇 상태 발행자
    robot_state_publisher_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_turtlebot3_gazebo, 'launch', 'robot_state_publisher.launch.py')
        ),
        launch_arguments={'use_sim_time': 'true'}.items()
    )

    # ✅ 핵심 수정: spawn_turtlebot3.launch.py 대신 Node를 직접 사용
    # - z=0.2 : 바닥에서 살짝 띄워 물리 충돌 폭발(star-burst) 방지
    # - entity 이름을 'shelfa_robot'으로 고정해 좀비 엔티티 충돌 방지
    spawn_turtlebot_cmd = Node(
        package='gazebo_ros',
        executable='spawn_entity.py',
        arguments=[
            '-entity', 'shelfa_robot',
            '-file', urdf_path,
            '-x', '2.0',
            '-y', '-4.0',
            '-z', '0.01',  # 로봇 바퀴가 바닥에 파묻혀 튕기는(bouncing) 현상을 방지하기 위해 0에 최대한 가깝게(0.01) 설정
            '-Y', '0.0',
        ],
        output='screen',
    )

    return LaunchDescription([
        SetEnvironmentVariable(name='GAZEBO_MODEL_PATH', value=gazebo_model_path),
        gzserver_cmd,
        gzclient_cmd,
        robot_state_publisher_cmd,
        spawn_turtlebot_cmd
    ])
