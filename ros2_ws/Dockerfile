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

# [최적화 마법] 패키지 의존성 파일(package.xml)들만 먼저 복사합니다.
# 이렇게 하면 파이썬/C++ 코드가 바뀌어도 이 단계는 캐시(Cache)가 유지됩니다!
COPY src /tmp/src
RUN mkdir -p /ros2_ws/src && \
    cd /tmp && find src -name "package.xml" -exec cp --parents {} /ros2_ws/ \;

# 의존성 패키지(Gazebo 등) 다운로드 및 설치 (이 엄청난 작업이 통째로 영구 저장됩니다)
RUN apt-get update && \
    rosdep init || true && \
    rosdep update && \
    rosdep install -i --from-path src --rosdistro humble -y && \
    rm -rf /var/lib/apt/lists/*

# 이제 진짜 소스코드를 복사합니다. (코드 수정 시 여기서부터만 재실행됨)
COPY src /ros2_ws/src

# ROS 패키지 빌드 (빈 include 폴더가 없어서 CMake가 에러를 내는 것을 방지)
RUN mkdir -p /ros2_ws/src/doosan-robot2/dsr_common2/include && \
    /bin/bash -c "source /opt/ros/humble/setup.bash && colcon build"
# 컨테이너 진입점 설정
RUN echo '#!/bin/bash\n\
source /opt/ros/humble/setup.bash\n\
source /ros2_ws/install/setup.bash\n\
exec "$@"' > /ros2_ws/entrypoint.sh \
    && chmod +x /ros_entrypoint.sh

ENTRYPOINT ["/ros_entrypoint.sh"]

# 실행 명령어 
CMD ["/bin/bash"]
