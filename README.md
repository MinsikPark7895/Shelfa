# 📚 Shelfa — 하이브리드 클라우드 자율주행 도서 관리 시스템

![ROS 2](https://img.shields.io/badge/ROS_2-Humble-22314E?logo=ros)
![OpenCV](https://img.shields.io/badge/OpenCV-5C3EE8?logo=opencv&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi)
![React](https://img.shields.io/badge/React-20232A?logo=react&logoColor=61DAFB)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?logo=github-actions&logoColor=white)

> **Shelfa**는 클라우드 웹 서비스와 오프라인 ROS 2 로봇 시스템을 MQTT로 실시간 연동하여, 사용자가 앱에서 예약한 책을 두산 로봇팔(E0509)이 자동으로 찾아 픽업해 주는 **자율주행 무인 도서 대출/반납 로봇 시스템**입니다.

---

## 🌟 주요 기능 (Key Features)

| 구분 | 기능 |
|---|---|
| 🌐 **웹** | 사용자 도서 예약 및 관리 (FastAPI + React) |
| 🤖 **자율주행** | ROS 2 기반 AMR 자율주행 및 도서관 매핑 (Nav2, SLAM) |
| 👁️ **비전** | ArUco 마커 + RealSense 카메라를 이용한 정밀 비전 정렬 (OpenCV) |
| 🦾 **로봇팔** | 두산 로봇팔(E0509) + 그리퍼를 이용한 무인 도서 파지 및 보관함 적재 |
| ☁️ **인프라** | GitHub Actions CI/CD, GCP Docker 자동 배포, MQTT 하이브리드 통신망 |

---

## 🏗️ 시스템 아키텍처 (System Architecture)

클라우드(웹/백엔드)와 로봇 엣지(Edge)를 **MQTT 브로커**를 통해 완전히 분리한 마이크로서비스 분산 아키텍처입니다.

```mermaid
graph TD
    %% ── 사용자 레이어 ──
    User["👤 사용자 (Web Browser)"]

    %% ── CI/CD Pipeline ──
    subgraph CICD["🚀 CI/CD Pipeline"]
        Github["GitHub Repository"]
        Actions["GitHub Actions\n(Auto Build & Deploy)"]
        Github -- "Push / Merge" --> Actions
    end

    %% ── 클라우드 레이어 ──
    subgraph Cloud["☁️ Cloud & Web Tier (GCP / Docker)"]
        direction TB
        React["💻 React Web App\n(Admin / User UI)"]
        FastAPI["⚙️ FastAPI Backend\n(예약 처리 / 비즈니스 로직)"]
        Postgres[("🗄️ PostgreSQL\n(도서 DB / 예약 DB)")]
        MQTTBroker{"📡 Mosquitto\nMQTT Broker\n(Port 1883)"}

        React -- "REST API (HTTP)" --> FastAPI
        FastAPI -- "Read / Write" --> Postgres
        FastAPI -- "Publish\n(PICKUP Command)" --> MQTTBroker
        MQTTBroker -- "Subscribe\n(Task Status)" --> FastAPI
    end

    Actions -- "Deploy via SSH" --> Cloud
    User -- "도서 예약 요청" --> React

    %% ── 로봇 엣지 레이어 (팀장 PC - SLAM 담당) ──
    subgraph Leader["🖥️ 팀장 PC (ROS_DOMAIN_ID=30) — SLAM & 지휘"]
        direction TB
        Master["👑 Master Orchestrator Node\n(MQTT 수신 → 미션 지시)"]
        Nav2["🗺️ Nav2 Stack\n(자율주행 / AMCL)"]
        SLAM["🗺️ SLAM Toolbox\n(지도 생성)"]

        Master -- "Nav2 Action (목적지 전송)" --> Nav2
    end

    MQTTBroker -- "Subscribe (명령 수신)" --> Master
    Master -- "Publish (상태 보고)" --> MQTTBroker

    %% ── 로봇 엣지 레이어 (팀원 PC - 로봇팔 담당) ──
    subgraph Teammate["🖥️ 팀원 PC (ROS_DOMAIN_ID=26) — 로봇팔 제어"]
        direction TB
        MissionServer["📋 Book Mission\nService Server\n(서비스 콜 수신 대기)"]
        StateMachine["🔄 Book Mission\nState Machine\n(파지 시퀀스 실행)"]
        ArUco0["👁️ ArUco Marker 0\nTF Publisher\n(책장 마커 인식)"]
        ArUco2["👁️ ArUco Marker 2\nTF Publisher\n(보관함 마커 인식)"]
        Gripper["🤖 Gripper Service Node\n(두산 E0509 그리퍼 제어)"]
        DRL["⚙️ Doosan DRL\n(로봇 내장 제어기)"]

        MissionServer -- "미션 시작" --> StateMachine
        StateMachine -- "마커 TF 조회" --> ArUco0
        StateMachine -- "마커 TF 조회" --> ArUco2
        StateMachine -- "파지/해제 명령" --> Gripper
        Gripper -- "Modbus TCP\n(flange_serial_write)" --> DRL
    end

    Master -- "SSH 원격 서비스 콜\n(/shelfa/pick_book_from_shelf)" --> MissionServer
    Master -- "SSH 원격 서비스 콜\n(/shelfa/place_book_in_storage)" --> MissionServer
```

### 기술 스택 (Tech Stack)

| 영역 | 기술 |
|---|---|
| **Web / Cloud** | React, FastAPI, PostgreSQL, Redis, Nginx, Docker Compose, Mosquitto MQTT, GCP |
| **CI/CD** | GitHub Actions, SSH 자동 배포 |
| **Robotics** | ROS 2 Humble, Nav2, SLAM Toolbox, TurtleBot3 |
| **Vision** | Intel RealSense D435, OpenCV 4.x, ArUco Marker |
| **Robot Arm** | Doosan E0509, RH-P12-RN Gripper, Modbus RTU over TCP |

---

## 🖥️ 실행 환경 사전 준비 (Prerequisites)

### 공통
- **OS:** Ubuntu 22.04 LTS
- **Git**, **Python 3.10+**

### 팀장 PC (SLAM / 마스터 노드 담당)
- **ROS 2 Humble** ([설치 가이드](https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html))
- `ros-humble-navigation2`, `ros-humble-nav2-bringup`
- `ros-humble-slam-toolbox`
- Python 패키지: `paho-mqtt`, `python-dotenv`

### 팀원 PC (로봇팔 제어 담당)
- **ROS 2 Humble**
- `ros-humble-realsense2-camera`
- Doosan DSR ROS 2 패키지 (`dsr_msgs2`)
- Python 패키지: `opencv-python` (4.5 이상 권장)

### 서버 / 로컬 웹 배포
- **Docker 24+** 및 **Docker Compose v2**

---

## 🚀 설치 및 실행 방법 (Getting Started)

### Step 1. 저장소 클론 및 환경 변수 설정

```bash
git clone https://github.com/MinsikPark7895/Shelfa.git
cd Shelfa

# .env 파일 생성 (아래 '환경 변수 설정' 섹션 참고)
cp .env.example .env   # 현재는 .env를 직접 작성
```

### Step 2. ROS 2 워크스페이스 빌드

```bash
cd ros2_ws
colcon build --symlink-install
source install/setup.bash
```

### Step 3-A. 서버/웹 실행 (백엔드 + MQTT + 프론트엔드)

```bash
cd ~/Desktop/Shelfa
docker compose up -d
```

> **로컬 테스트 시:** `.env`에서 `SHELFA_ENV=dev` / `SHELFA_MQTT_BROKER=127.0.0.1` 사용  
> **클라우드 배포 시:** `SHELFA_ENV=prod` / `SHELFA_MQTT_BROKER=<GCP외부IP>` 사용

### Step 3-B. 팀장 PC 실행 (SLAM + Nav2 + 마스터 노드)

```bash
cd ~/Desktop/Shelfa

# 가제보 시뮬레이션 + Nav2 + 마스터 노드를 한 번에 시작
./start_leader.sh
```

> 실제 로봇(AMR) 환경에서는 Gazebo 대신 실제 하드웨어 드라이버 노드를 켜야 합니다.

### Step 3-C. 팀원 PC 실행 (두산 로봇팔 + 카메라 + 그리퍼)

```bash
cd ~/Shelfa

# 두산 로봇 bringup + RealSense 카메라 + 그리퍼 서비스 + ArUco 마커 + 미션 서버를 한 번에 시작
./start_teammate.sh
```

### Step 4. 서비스 콜로 직접 미션 실행 (테스트)

```bash
# 팀원 PC의 새 터미널에서 실행
source /opt/ros/humble/setup.bash
source ~/Shelfa/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=26

# '제3인류' 책 파지 명령
ros2 service call /shelfa/pick_book_from_shelf \
  shelfa_msgs/srv/PickBookFromShelf \
  "{shelf_id: 0, book_title: '제3인류'}"

# 보관함에 책 넣기 명령
ros2 service call /shelfa/place_book_in_storage \
  shelfa_msgs/srv/PlaceBookInStorage \
  "{storage_id: 2}"
```

---

## ⚙️ 환경 변수 설정 (Environment Variables)

프로젝트 루트에 `.env` 파일을 생성합니다. **절대 Github에 커밋하지 마세요** (`.gitignore`에 포함되어 있습니다).

```dotenv
# 2. Database
POSTGRES_USER=your_db_user
POSTGRES_PASSWORD=your_db_password
POSTGRES_DB=shelfa_db
DATABASE_URL=postgresql://your_db_user:your_db_password@localhost:5432/shelfa_db

# 3. Redis
REDIS_URL=redis://localhost:6379/0

# 4. Security / JWT
SECRET_KEY=your-super-secret-key-here

# 5. Aladin Open API
ALADIN_TTB_KEY=your_aladin_api_key

# 6. MQTT 계정 (보안 모드)
MQTT_ROBOT_USER=robot
MQTT_ROBOT_PASSWORD=your_robot_mqtt_password
MQTT_BACKEND_USER=backend
MQTT_BACKEND_PASSWORD=your_backend_mqtt_password
MQTT_FRONTEND_USER=frontend
MQTT_FRONTEND_PASSWORD=your_frontend_mqtt_password

# 7. MQTT 브로커 주소 및 환경 모드
# ── [로컬 테스트용] ──
SHELFA_MQTT_BROKER=127.0.0.1
SHELFA_ENV=dev

# ── [클라우드 서버 배포용] 위 로컬 설정을 주석 처리하고 아래를 활성화 ──
# SHELFA_MQTT_BROKER=<GCP_서버_외부_IP>
# SHELFA_ENV=prod

# 8. 팀원 PC (로봇팔 제어 PC) SSH 접속 정보
ROBOT_ARM_PC_IP=172.30.1.99
ROBOT_ARM_PC_USER=user
```

---

## 📂 핵심 디렉토리 구조 (Directory Structure)

```
Shelfa/
├── backend/                    # FastAPI 백엔드 (API, DB 모델, MQTT 발행)
│   ├── main.py
│   ├── routers/
│   └── models/
├── frontend/                   # React 웹 앱 (사용자/관리자 UI)
├── ros2_ws/                    # ROS 2 워크스페이스
│   └── src/
│       ├── master_orchestrator/        # 팀장 PC: MQTT 수신 → Nav2 지휘
│       ├── doosan_realsense_handeye/   # 팀원 PC: 비전 정렬 및 파지 시퀀스
│       │   ├── book_mission_service_server.launch.py
│       │   ├── book_mission_state_machine.py
│       │   └── simple_aruco_marker_tf_publisher.py
│       ├── Doosan-E0509-ROBOTIS-RH-P12-RN-TCP-Bridge/  # 팀원 PC: 두산 그리퍼 제어
│       │   └── dsr_gripper_tcp/
│       │       └── gripper_tcp_bridge.py   # Modbus TCP → DRL 통신 브릿지
│       └── shelfa_msgs/                # 커스텀 ROS 2 서비스 메시지 정의
├── mosquitto/                  # MQTT 브로커 설정 (dev/prod 분리)
├── nginx/                      # Nginx 리버스 프록시 설정
├── docker-compose.yml          # 전체 서비스 컨테이너 정의
├── start_leader.sh             # 팀장 PC: 전체 SLAM/Nav2/마스터 노드 시작
├── start_teammate.sh           # 팀원 PC: 로봇팔/카메라/그리퍼/미션서버 시작
├── request_pick.sh             # 단독 픽업 서비스 콜 테스트 스크립트
├── request_place.sh            # 단독 보관함 적재 서비스 콜 테스트 스크립트
└── .env                        # 환경 변수 (gitignore 처리됨)
```

---

## 🔄 미션 실행 전체 시퀀스 (Mission Execution Flow)

새로운 기능을 추가할 때 아래 흐름을 참고하세요.

```
[1] 사용자 → 웹(React)에서 도서 예약
[2] FastAPI → DB 업데이트 → MQTT Publish (shelfa/robot/command)
[3] master_node.py (팀장 PC) → MQTT 수신 → SEMANTIC_MAP에서 책장 좌표 조회
[4] master_node.py → Nav2 Action → AMR 자율주행 (책장 앞으로 이동)
[5] master_node.py → SSH → 팀원 PC: /shelfa/pick_book_from_shelf 서비스 콜
[6] 팀원 PC: RealSense 카메라 → ArUco 마커 0 인식 → 로봇팔 정밀 정렬
[7] 팀원 PC: 그리퍼 토크 ON → 도서 파지 → 안전 자세로 복귀
[8] master_node.py → Nav2 Action → AMR 자율주행 (보관함으로 이동)
[9] master_node.py → SSH → 팀원 PC: /shelfa/place_book_in_storage 서비스 콜
[10] 팀원 PC: ArUco 마커 2 인식 → 로봇팔 정렬 → 도서 보관함 적재
[11] master_node.py → MQTT Publish (shelfa/robot/status: SUCCESS)
[12] FastAPI → DB 업데이트 → 사용자 앱 화면: "수령 가능" 상태로 변경
```

**새 책장 위치 추가 방법:** `master_node.py`의 `SEMANTIC_MAP` 딕셔너리에 `{x, y, yaw}` 좌표를 추가하면 됩니다.

**새 로봇팔 동작 추가 방법:** `book_mission_state_machine.py`의 상태(Step) 목록 사이에 새로운 Step을 삽입하면 됩니다.

---

## 🛠️ 트러블슈팅 (Troubleshooting)

### ❌ MQTT 브로커가 무한 재시작됨
**증상:** `docker logs shelfa_mqtt`에서 `Unable to open pwfile "/mosquitto/config/passwd"` 반복
```
# 원인: .env 파일의 SHELFA_ENV=prod 상태에서 passwd 파일이 없을 때 발생
# 해결: 로컬 테스트 시 .env에서 아래 설정으로 변경 후 docker compose up -d
SHELFA_MQTT_BROKER=127.0.0.1
SHELFA_ENV=dev
```

### ❌ RealSense 카메라 ArUco 마커 인식 불가 (TF lookup failed)
**증상:** `aruco_marker_0: does not exist` 에러가 반복되며 로봇팔이 무한 대기

**원인 1 — OpenCV Segmentation Fault (cv2 4.6.0 버그):**
```python
# simple_aruco_marker_tf_publisher.py 내 아래 코드를 수정
# 변경 전 (버그 유발):
return aruco.DetectorParameters()
# 변경 후 (안전):
return aruco.DetectorParameters_create()
```

**원인 2 — ROS 2 노드 이름 충돌:** `start_teammate.sh`에서 마커 0번과 2번 노드를 동시에 실행할 때 이름이 같으면 나중에 켜진 노드가 먼저 켜진 노드를 강제 종료시킵니다.
```bash
# start_teammate.sh에 -r __node:= 옵션을 추가하여 이름을 구분해야 합니다.
ros2 run doosan_realsense_handeye simple_aruco_marker_tf_publisher \
  --ros-args \
  -r __node:=aruco_marker_0_node \   # ← 이 줄이 반드시 있어야 함
  -p marker_id:=0 ...
```

### ❌ 그리퍼 `Invalid type : tx_data` 에러
**증상:** 두산 로봇 컨트롤러 로그에서 `flange_serial_write / Invalid type : tx_data` 출력 후 TCP 서버 연결 끊김

**원인:** 두산 DRL 환경의 `flange_serial_write()`는 `bytes`, `bytearray` 타입을 거부합니다.

**해결:** `gripper_tcp_bridge.py`의 Modbus 패킷 생성 함수(`modbus_fc03`, `modbus_fc06`, `modbus_fc16`)가 **순수 정수 리스트(List[int])** 를 반환하도록 수정해야 합니다. 현재 브랜치에는 이미 해당 패치가 적용되어 있습니다.

### ❌ 마스터 노드가 MQTT 신호를 받지 못함
**원인:** `master_node.py`는 **프로그램이 켜지는 순간 딱 한 번** `.env`를 읽습니다.
`.env` 파일을 수정한 뒤에는 반드시 마스터 노드를 재시작해야 합니다.
```bash
# 마스터 노드 실행 중인 터미널에서 Ctrl+C 후 재실행
ros2 run master_orchestrator master_node
```