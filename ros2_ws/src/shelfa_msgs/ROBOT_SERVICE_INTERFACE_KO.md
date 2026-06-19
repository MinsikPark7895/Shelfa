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

서비스 서버 기본 실행 예시:

```bash
ros2 launch doosan_realsense_handeye book_mission_service_server.launch.py
```

기본값은 안전을 위해 `dry_run:=true`입니다. 실제 로봇을 움직일 때만 명시적으로 아래처럼 실행합니다.

```bash
ros2 launch doosan_realsense_handeye book_mission_service_server.launch.py \
  dry_run:=false \
  auto_run:=true
```

## SLAM/상위 로직에서 기대되는 흐름

예상 흐름은 다음과 같습니다.

1. SLAM/상위 로직이 책장 위치를 결정합니다.
2. 로봇 서비스에 `PickBookFromShelf`를 호출합니다.
3. 로봇이 책을 뽑아 임시 위치에 내려놓습니다.
4. SLAM/상위 로직이 보관함 위치 또는 다음 이동을 결정합니다.
5. 로봇 서비스에 `PlaceBookInStorage`를 호출합니다.
6. 로봇이 임시 위치의 책을 다시 잡아 보관함에 넣습니다.

즉, 외부 로직은 “책장 번호와 책 제목”, “보관함 번호”만 넘기고, 실제 정렬/비전/OCR/집기/넣기 동작은 로봇 미션 노드가 담당합니다.
