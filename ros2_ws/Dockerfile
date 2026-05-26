# ROS 2 버전에 맞게 수정 가능 (예: foxy, humble 등)
FROM osrf/ros:humble-desktop

ENV DEBIAN_FRONTEND=noninteractive

# 기본 의존성 설치 (rosbridge 등 백엔드 통신에 유용한 패키지 포함)
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-colcon-common-extensions \
    ros-humble-rosbridge-suite \
    && rm -rf /var/lib/apt/lists/*

# 작업 디렉토리 설정
WORKDIR /ros2_ws

# 로컬의 src 폴더를 도커 안으로 복사
COPY src /ros2_ws/src

# ROS 패키지 의존성 자동 설치 및 워크스페이스 빌드
RUN apt-get update && /bin/bash -c "source /opt/ros/humble/setup.bash && \
    rosdep init || true && \
    rosdep update && \
    rosdep install -i --from-path src --rosdistro humble -y && \
    colcon build --symlink-install" && \
    rm -rf /var/lib/apt/lists/*
# 컨테이너 진입점 설정
RUN echo '#!/bin/bash\n\
source /opt/ros/humble/setup.bash\n\
source /ros2_ws/install/setup.bash\n\
exec "$@"' > /ros2_ws/entrypoint.sh \
    && chmod +x /ros_entrypoint.sh

ENTRYPOINT ["/ros_entrypoint.sh"]

# 실행 명령어 
CMD ["/bin/bash"]
