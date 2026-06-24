# Shelfa 로봇 미션 서비스 인터페이스

이 문서는 SLAM/상위 로직 담당자가 로봇 책 조작 미션을 호출할 때 필요한 서비스 계약을 정리한 것입니다.

## 전체 구조

로봇 미션은 두 개의 서비스 요청으로 분리됩니다.

1. 책장에서 책 뽑기
2. 임시로 내려둔 책을 보관함에 넣기

기존 로봇 코드는 책을 뽑고 보관함에 넣는 과정을 한 번에 실행했지만, 실제 시스템에서는 중간에 SLAM/이동/상위 판단 로직이 들어갈 수 있습니다. 그래서 `doosan_realsense_handeye` 쪽은 서비스 서버로 동작하고, 외부 노드는 필요한 시점에 아래 서비스를 호출하면 됩니다.

## ArUco Marker 규칙

| 용도 | marker id |
| --- | --- |
| 책장 | `0`, `1` |
| 보관함 | `2`, `3` |

책장에서 책을 뽑을 때는 `0` 또는 `1`만 요청할 수 있습니다.

보관함에 책을 넣을 때는 `2` 또는 `3`만 요청할 수 있습니다.

현재 프로토타입에서 실제 로봇 동작까지 확인된 조합은 책장 marker `0`, 보관함 marker `2`입니다. marker `1`, `3`에 대한 서비스 인터페이스와 코드 경로는 준비되어 있지만, 실제 위치/자세 검증은 추가 테스트가 필요합니다.

## 서비스 1: 책장에서 책 뽑기

서비스 타입:

```text
shelfa_msgs/srv/PickBookFromShelf
```

요청:

```text
int32 shelf_id
string book_title
```

응답:

```text
bool success
string message
string held_book_title
string result_json
```

동작:

1. `shelf_id`에 해당하는 책장 ArUco marker를 찾습니다.
2. marker 기준으로 로봇을 정렬합니다.
3. `book_title`에 해당하는 책을 비전/OCR로 찾습니다.
4. 책을 뽑습니다.
5. 책을 임시 위치에 내려놓습니다.
6. 내부 상태에 현재 뽑아둔 책 제목을 저장합니다.

제약:

- `shelf_id`는 `0` 또는 `1`이어야 합니다.
- `book_title`은 빈 문자열이면 안 됩니다.
- 이미 뽑아둔 책이 있으면 추가로 책을 뽑을 수 없습니다.

호출 예시:

```bash
ros2 service call /shelfa/pick_book_from_shelf shelfa_msgs/srv/PickBookFromShelf \
  "{shelf_id: 0, book_title: '제3인류'}"
```

## 서비스 2: 보관함에 책 넣기

서비스 타입:

```text
shelfa_msgs/srv/PlaceBookInStorage
```

요청:

```text
int32 storage_id
```

응답:

```text
bool success
string message
string placed_book_title
string result_json
```

동작:

1. `storage_id`에 해당하는 보관함 ArUco marker를 찾습니다.
2. marker 기준으로 로봇을 정렬합니다.
3. 임시 위치에 내려둔 책을 다시 잡습니다.
4. 보관함 위치에 책을 넣습니다.
5. 성공하면 내부 상태에서 뽑아둔 책 정보를 비웁니다.

제약:

- `storage_id`는 `2` 또는 `3`이어야 합니다.
- 뽑아둔 책이 없으면 보관함에 넣을 수 없습니다.

호출 예시:

```bash
ros2 service call /shelfa/place_book_in_storage shelfa_msgs/srv/PlaceBookInStorage \
  "{storage_id: 2}"
```

## 상태 관리

로봇 서비스 서버는 현재 뽑아둔 책 정보를 파일로 저장합니다.

기본 경로:

```text
realtime_results/book_service_state.json
```

이 파일에는 대략 아래 정보가 저장됩니다.

```json
{
  "held_book_title": "제3인류",
  "held_from_shelf_id": 0,
  "last_pick_result_json": "realtime_results/mission_result.json",
  "last_place_result_json": "",
  "updated_at": "..."
}
```

상위 로직에서 직접 이 파일을 수정하는 것은 권장하지 않습니다. 상태 초기화가 필요하면 로봇 담당자와 확인 후 진행하는 것이 안전합니다.

## 결과 확인

각 미션의 상세 결과는 응답의 `result_json` 경로에서 확인할 수 있습니다.

기본 경로:

```text
realtime_results/mission_result.json
```

실패 시 `message`에는 실패 단계, return code, abort reason 등이 포함됩니다.

## 실행 전 필요한 전제

서비스 서버만 실행한다고 카메라/로봇/그리퍼가 자동으로 모두 준비되는 것은 아닙니다. 실제 실행 전에는 아래 노드들이 준비되어 있어야 합니다.

- Doosan robot bringup
- RealSense camera node
- 카메라와 로봇 `link_6` 사이 static TF
- ArUco marker TF publisher
- gripper service node
- `doosan_realsense_handeye`의 book mission service server

아래는 실제 로봇 동작 테스트 기준 실행 순서입니다.

### 1. 워크스페이스 빌드 및 환경 로드

```bash
cd /home/dakae/ros2_ws/src/Shelfa/ros2_ws
source /opt/ros/humble/setup.bash

colcon build \
  --base-paths src/shelfa_msgs src/doosan_realsense_handeye \
  --packages-select shelfa_msgs doosan_realsense_handeye \
  --symlink-install

source install/setup.bash
```

### 2. Doosan robot bringup

두산 로봇의 motion service가 떠 있어야 합니다.

필수 확인 대상:

```text
/dsr01/motion/move_joint
/dsr01/motion/move_line
/dsr01/aux_control/get_current_posx
```

서비스 확인:

```bash
ros2 service list | grep /dsr01
```

실행 명령은 로봇 bringup 환경에 맞춰 사용합니다. 예시는 다음과 같습니다.

```bash
ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py \
  mode:=real \
  model:=e0509 \
  host:=192.168.137.100 \
  port:=12345
```

### 3. RealSense camera node

```bash
ros2 launch realsense2_camera rs_launch.py \
  enable_color:=true \
  enable_depth:=true \
  align_depth.enable:=true \
  publish_tf:=true \
  rgb_camera.color_profile:=1280x720x30 \
  depth_module.depth_profile:=1280x720x30
```

필수 확인 대상:

```text
/camera/camera/color/image_raw
/camera/camera/color/camera_info
/camera/camera/aligned_depth_to_color/image_raw
```

### 4. ArUco marker TF publisher

책장 marker `0`용 publisher:

```bash
ros2 run doosan_realsense_handeye simple_aruco_marker_tf_publisher \
  --ros-args \
  -p marker_id:=0 \
  -p child_frame:=aruco_marker_0 \
  -p parent_frame:=camera_color_optical_frame \
  -p image_topic:=/camera/camera/color/image_raw \
  -p camera_info_topic:=/camera/camera/color/camera_info
```

보관함 marker `2`용 publisher:

```bash
ros2 run doosan_realsense_handeye simple_aruco_marker2_tf_publisher \
  --ros-args \
  -p marker_id:=2 \
  -p child_frame:=aruco_marker_2 \
  -p parent_frame:=camera_color_optical_frame \
  -p image_topic:=/camera/camera/color/image_raw \
  -p camera_info_topic:=/camera/camera/color/camera_info
```

현재 실사용 테스트는 marker `0`, `2` 기준입니다. marker `1`, `3`을 쓰려면 해당 marker가 카메라에 보이는 초기 자세와 정렬 파라미터를 별도로 검증해야 합니다.

TF 확인:

```bash
ros2 run tf2_ros tf2_echo camera_color_optical_frame aruco_marker_0
```

```bash
ros2 run tf2_ros tf2_echo camera_color_optical_frame aruco_marker_2
```

### 5. Gripper service node

```bash
ros2 launch dsr_gripper_tcp gripper_service_node.launch.py
```

필수 확인 대상:

```text
/gripper_service/get_state
/gripper_service/set_position
/gripper_service/set_torque
```

서비스 확인:

```bash
ros2 service list | grep gripper_service
```

### 6. Book mission service server

서비스 서버 기본 실행 예시:

```bash
ros2 launch doosan_realsense_handeye book_mission_service_server.launch.py
```

기본값은 안전을 위해 `dry_run:=true`입니다. 실제 로봇을 움직일 때만 명시적으로 아래처럼 실행합니다.

```bash
ros2 launch doosan_realsense_handeye book_mission_service_server.launch.py \
  dry_run:=false \
  dry_run_contract_mode:=false \
  auto_run:=true
```

서비스 서버가 제공하는 서비스:

```text
/shelfa/pick_book_from_shelf
/shelfa/place_book_in_storage
```

서비스 확인:

```bash
ros2 service list | grep shelfa
```

## 서비스 요청 예시

### 책장에서 책 뽑기

현재 실사용 검증 기준은 `shelf_id: 0`입니다.

```bash
ros2 service call /shelfa/pick_book_from_shelf shelfa_msgs/srv/PickBookFromShelf \
  "{shelf_id: 0, book_title: '제3인류'}"
```

성공하면 로봇은 marker `0` 기준으로 책장에 정렬한 뒤 요청된 제목의 책을 찾아 뽑고, 임시 위치에 내려놓습니다. 이후 내부 상태에는 현재 뽑아둔 책 제목이 저장됩니다.

같은 상태에서 다시 책 뽑기를 요청하면 안전상 거부됩니다.

### 보관함에 책 넣기

현재 실사용 검증 기준은 `storage_id: 2`입니다.

```bash
ros2 service call /shelfa/place_book_in_storage shelfa_msgs/srv/PlaceBookInStorage \
  "{storage_id: 2}"
```

성공하면 로봇은 marker `2` 기준으로 보관함에 정렬한 뒤, 임시 위치에 내려둔 책을 다시 잡아 보관함에 넣습니다. 성공 후 내부 상태의 `held_book_title`은 초기화됩니다.

뽑아둔 책이 없는 상태에서 보관함 넣기를 요청하면 안전상 거부됩니다.

## 서비스 계약 테스트 모드

SLAM/상위 로직에서 서비스 요청과 응답 형태만 먼저 확인하려면 아래 모드를 사용합니다.

```bash
ros2 launch doosan_realsense_handeye book_mission_service_server.launch.py \
  dry_run:=true \
  dry_run_contract_mode:=true
```

이 모드에서는 실제 정렬, 비전, OCR, 로봇 이동, 그리퍼 제어를 실행하지 않습니다. 대신 서비스 요청 검증, 상태 저장/초기화, 응답 포맷만 빠르게 확인합니다.

## SLAM/상위 로직에서 기대되는 흐름

예상 흐름은 다음과 같습니다.

1. SLAM/상위 로직이 책장 위치를 결정합니다.
2. 로봇 서비스에 `PickBookFromShelf`를 호출합니다.
3. 로봇이 책을 뽑아 임시 위치에 내려놓습니다.
4. SLAM/상위 로직이 보관함 위치 또는 다음 이동을 결정합니다.
5. 로봇 서비스에 `PlaceBookInStorage`를 호출합니다.
6. 로봇이 임시 위치의 책을 다시 잡아 보관함에 넣습니다.

즉, 외부 로직은 “책장 번호와 책 제목”, “보관함 번호”만 넘기고, 실제 정렬/비전/OCR/집기/넣기 동작은 로봇 미션 노드가 담당합니다.
