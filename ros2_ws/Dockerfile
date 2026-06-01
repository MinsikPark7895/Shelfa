# syntax=docker/dockerfile:1
# ==========================================
# 1단계: 의존성 캐싱을 위한 파일 추출 (Cacher)
# ==========================================
FROM ubuntu:jammy AS cacher

# 전체 소스코드를 임시 폴더로 복사합니다.
COPY src /tmp/src

# 빌드 의존성 분석에 필요한 package.xml 파일들만 추출해서 /pkg_xmls 에 모아둡니다.
# (이 단계를 거쳐야 C++ 파이썬 코드가 변경되어도 rosdep 설치가 캐시됩니다!)
RUN mkdir -p /pkg_xmls && \
    cd /tmp && find src -name "package.xml" -exec cp --parents {} /pkg_xmls/ \;

# ==========================================
# 2단계: 실제 ROS 2 환경 구축 (Builder)
# ==========================================
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

# 1단계(cacher)에서 추출해둔 package.xml 파일들만 먼저 복사합니다.
# 소스코드가 바뀌어도 package.xml 내용이 같다면 도커가 이 단계부터는 캐시를 사용합니다!
COPY --from=cacher /pkg_xmls/src /ros2_ws/src

# 의존성 패키지(Gazebo 등) 다운로드 및 설치 (캐시 적용됨)
RUN apt-get update && \
    rosdep init || true && \
    rosdep update && \
    rosdep install -i --from-path src --rosdistro humble -y && \
    rm -rf /var/lib/apt/lists/*

# 이제 진짜 소스코드를 복사합니다. (코드 수정 시 여기서부터만 재실행됨)
COPY src /ros2_ws/src

# ROS 패키지 빌드 1단계: 가장 무겁고 50분이나 걸리는 dsr_msgs2까지만 먼저 빌드해서 '세이브 포인트'를 만듭니다.
# (BuildKit 캐시 마운트를 사용하여 이전 빌드의 찌꺼기 파일(build 폴더)을 재사용합니다!)
RUN --mount=type=cache,target=/ros2_ws/build \
    --mount=type=cache,target=/ros2_ws/log \
    mkdir -p /ros2_ws/src/doosan-robot2/dsr_common2/include && \
    /bin/bash -c "source /opt/ros/humble/setup.bash && colcon build --packages-up-to dsr_msgs2 --executor sequential --parallel-workers 1"

# ROS 패키지 빌드 2단계: 나머지 패키지들을 이어서 빌드합니다.
# (마찬가지로 캐시 마운트를 사용하여 수정된 파일만 1초 만에 빌드합니다!)
RUN --mount=type=cache,target=/ros2_ws/build \
    --mount=type=cache,target=/ros2_ws/log \
    /bin/bash -c "source /opt/ros/humble/setup.bash && colcon build --executor sequential --parallel-workers 1"
# 컨테이너 진입점 설정
RUN echo '#!/bin/bash\n\
source /opt/ros/humble/setup.bash\n\
source /ros2_ws/install/setup.bash\n\
exec "$@"' > /ros2_ws/entrypoint.sh \
    && chmod +x /ros_entrypoint.sh

ENTRYPOINT ["/ros_entrypoint.sh"]

# 실행 명령어 
CMD ["/bin/bash"]
