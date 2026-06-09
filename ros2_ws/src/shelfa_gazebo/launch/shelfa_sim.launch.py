import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

def generate_launch_description():
    pkg_gazebo_ros = get_package_share_directory('gazebo_ros')
    pkg_turtlebot3_gazebo = get_package_share_directory('turtlebot3_gazebo')

    # Gazebo 모델 패스 환경변수 설정 (기존 패스 보존 + Shelfa + Turtlebot3 모델)
    shelfa_dir = '/home/minsik/Desktop/Shelfa'
    gazebo_model_path = os.environ.get('GAZEBO_MODEL_PATH', '')
    if gazebo_model_path:
        gazebo_model_path += ':'
    gazebo_model_path += os.path.join(shelfa_dir, 'worlds', 'model_editor_models') + ':' + \
                         os.path.join(shelfa_dir, 'worlds', 'building_editor_models') + ':' + \
                         os.path.join(pkg_turtlebot3_gazebo, 'models')

    
    # TurtleBot3 기본 모델 설정 (카메라가 달려있는 waffle_pi 사용)
    os.environ['TURTLEBOT3_MODEL'] = 'waffle_pi'

    # 우리가 만든 library_layout.world 파일 절대 경로
    world_file_path = os.path.join(shelfa_dir, 'worlds', 'library_layout.world')

    # Gazebo 서버 (gzserver) 실행 + 우리의 world 파일 주입
    gzserver_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_gazebo_ros, 'launch', 'gzserver.launch.py')
        ),
        launch_arguments={'world': world_file_path}.items()
    )

    # Gazebo 클라이언트 (gzclient) 실행
    gzclient_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_gazebo_ros, 'launch', 'gzclient.launch.py')
        )
    )

    # TurtleBot3 로봇 스폰 런치 파일 가져오기 (원하는 시작 좌표 지정)
    # 시작 위치는 로비 근처인 x=-2, y=-5 부근으로 설정
    robot_state_publisher_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_turtlebot3_gazebo, 'launch', 'robot_state_publisher.launch.py')
        ),
        launch_arguments={'use_sim_time': 'true'}.items()
    )

    spawn_turtlebot_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_turtlebot3_gazebo, 'launch', 'spawn_turtlebot3.launch.py')
        ),
        launch_arguments={
            'x_pose': '-2.0',
            'y_pose': '-5.0'
        }.items()
    )

    return LaunchDescription([
        SetEnvironmentVariable(name='GAZEBO_MODEL_PATH', value=gazebo_model_path),
        gzserver_cmd,
        gzclient_cmd,
        robot_state_publisher_cmd,
        spawn_turtlebot_cmd
    ])
