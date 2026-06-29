# 📚 Shelfa — 하이브리드 클라우드 자율주행 도서 관리 시스템

![ROS 2](https://img.shields.io/badge/ROS_2-Humble-22314E?logo=ros)
![OpenCV](https://img.shields.io/badge/OpenCV-5C3EE8?logo=opencv&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi)
![React](https://img.shields.io/badge/React-20232A?logo=react&logoColor=61DAFB)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?logo=github-actions&logoColor=white)

> **Shelfa**는 클라우드 웹 서비스와 오프라인 ROS 2 로봇 시스템을 MQTT로 실시간 연동하여, 사용자가 앱에서 예약한 책을 두산 로봇팔(E0509)이 자동으로 찾아 픽업해 주는 **자율주행 무인 도서 대출/반납 로봇 시스템**입니다.

---

## 👥 팀원 소개 (Team Members)

| 이름 | 역할 | 담당 영역 |
|---|---|---|
| **박민식** | 팀장 | Cloud-to-Edge 시스템 통합, FastAPI 백엔드 API 설계, SLAM/Nav2 자율주행, AI 파이프라인 연동, MQTT 하이브리드 통신망 구축 |
| **백승호** | 부팀장 | 두산 로봇팔(E0509) 제어, 그리퍼 TCP 브릿지 설계, ArUco 기반 정밀 정렬, 그리퍼 하드웨어 개조 |
| **김제원** | 팀원 | YOLO OBB 도서 감지 모델 학습, OCR 파이프라인 구축, Fuzzy Matching, Hand-Eye Calibration |
| **모윤근** | 팀원 | React 프론트엔드 개발,  PostgreSQL DB 연동, 도서 예약 시스템 구현 |

---

## 🌟 주요 기능 (Key Features)

| 구분 | 기능 |
|---|---|
| 🌐 **웹** | 사용자 도서 예약 및 관리 (FastAPI + React + PostgreSQL) |
| 🤖 **자율주행** | ROS 2 기반 AMR 자율주행 및 도서관 매핑 (Nav2, SLAM Toolbox) |
| 🧠 **AI 비전** | YOLO OBB 도서 감지 + OCR Title Crop + Fuzzy Matching 도서 인식 파이프라인 |
| 📐 **정밀 정렬** | Hand-Eye Calibration + ArUco 마커 + RealSense D435 기반 mm 단위 위치 보정 |
| 🦾 **로봇팔** | 두산 E0509 + 커스텀 그리퍼 + Modbus TCP 양방향 통신 + Safe Grasp Action |
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

## 🧠 AI 비전 파이프라인 (AI Vision Pipeline)

대상 도서를 자동으로 인식하는 3단계 파이프라인입니다.

### 1단계: YOLO OBB 도서 감지

일반 바운딩박스(AABB)는 비스듬히 꽂힌 책을 정확히 탐지하지 못하는 한계가 있어, **YOLO OBB(회전 바운딩박스)** 를 도입했습니다. OpenCV `minAreaRect()`를 통해 폴리곤 라벨 4개 꼭짓점을 **중심+크기+각도** 형태로 변환하여 학습했습니다.

| 구분 | 이미지 수 |
|---|---|
| Train (70%) | 1,024장 |
| Valid (20%) | 293장 |
| Test (10%) | 146장 |

### 2단계: OCR 도서 제목 인식

- **Title Crop:** 책등 전체를 OCR하면 저자명/출판사 등 불필요한 텍스트가 혼잡합니다. 책등 **중앙의 가장 길게 이어진 글자 덩어리**만 잘라내어 오직 제목만 OCR 수행합니다.
- **Fuzzy Matching:** OCR 결과와 목표 제목 간 **문자열 유사도 + 글자 포함 비율 복합 점수화** 방식으로 오인식 내성을 크게 낮췄습니다.
- **Early Stop:** 임계값 이상 유사도 확인 즉시 종료하여 불필요한 탐색을 생략합니다.
- **Fallback:** 애매한 경우 OBB Crop OCR로 재확인하여 오매칭 위험을 완화합니다.

### 3단계: 3D 좌표 변환 (Hand-Eye Calibration)

RealSense 카메라로 찾은 도서의 2D 위치를 로봇팔이 실제로 이동할 수 있는 3D 좌표로 변환합니다.

```
RealSense (camera_color_optical_frame)
→ Hand-Eye Calibration (T_link_6_camera)
→ TF2 변환 (base_link ↔ link_6)
→ 로봇팔 접근 좌표 추출
```

5가지 Hand-Eye Calibration 방법을 실험적으로 비교하여 가장 오차가 작은 **ANDREFF 방식(Translation RMSE 1.165mm)** 을 최종 선정했습니다.

| 방법 | Translation RMSE |
|---|---|
| TSAI | 16.270mm |
| PARK | 1.259mm |
| HORAUD | 1.248mm |
| **ANDREFF** | **1.165mm ✅ 최종 선정** |
| DANIILIDIS | 1.306mm |

---

## 🦾 로봇팔 제어 시스템 (Robot Arm Control)

### 그리퍼 TCP 브릿지 아키텍처

기존 제어 방식(DRL 스크립트 실행, Write만 가능)에서 **TCP 양방향 통신 방식**으로 전환하여 실제 파지 여부를 실시간으로 판단할 수 있게 되었습니다.

```
[기존] ROS 2 노드 → DRL 스크립트 → ROBOTIS 그리퍼 (Write only, Read 불가)
[변경] gripper_service_node ↔ 두산 컨트롤러 (DRL TCP Server) ↔ RH-P12-RN (RS-485 Modbus)
       ├─ Write: 구동 명령 전송
       └─ Read:  실시간 상태 조회 (위치/전류/토크)
```

### ROS 2 인터페이스

| 인터페이스 | 타입 | 설명 |
|---|---|---|
| `/gripper_service/state` | Topic | 위치/전류/속도/토크/이동 여부 실시간 발행 |
| `/gripper_service/set_position` | Service | 열기/닫기/특정 위치 이동 |
| `/gripper_service/safe_grasp` | Action | 닫기 → 전류 Read → 증가 확인 → 파지 판단 |

```bash
# Safe Grasp 액션 호출 예시
ros2 action send_goal /gripper_service/safe_grasp \
  dsr_gripper_tcp_interfaces/action/SafeGrasp \
  "{target_position: 700, max_current: 400, current_delta_threshold: 120, timeout_sec: 8.0}"
```

### 실제 책 뽑기 세부 단계

| 단계 | 내용 |
|---|---|
| ① | ArUco 마커 기반 책장 정렬 (Marker 검출 → Pose 계산 → 이동 → 회전 → XYZ 보정) |
| ② | YOLO OBB + OCR으로 목표 도서 상세 위치 파악 |
| ③ | 20cm 오프셋 접근 → 좌우 정렬 → 그리퍼 폭 조절 |
| ④ | Safe Grasp 액션으로 책 파지 (전류 기반 파지 성공 판단) |
| ⑤ | 로봇팔 안전 자세 복귀 → 임시 보관함 적재 |

### 그리퍼 하드웨어 개조

기존 그리퍼는 얇고 세로로 세워진 책 파지에 적합하지 않아, **쐐기형 교체 부품을 직접 3D 모델링/설계**하여 기존 그리퍼에 결합했습니다.

---

## 🚀 한계점 및 향후 개선 방안

### 현재 한계점

| 한계점 | 내용 |
|---|---|
| 책장 환경 | 실제 도서관의 다양한 책장 환경(빠진 책/기울어진 책 등)이 고려되지 않음 |
| 반납 처리 | 사용자가 뒷집에서 꽂다가 다시 컨테이너에 넣는 도서 반납 기능 미구현 |
| 단일 예약 | 동시에 한 권만 예약 가능 (다수 예약 처리 미지원) |
| 수령 확인 | 사용자가 실제로 책을 수령했는지 시스템이 직접 파악 불가 |

### 개선 방안

| 개선 분야 | 내용 |
|---|---|
| 파지 심화 | 모방학습(IL) 또는 강화학습(RL) 기반 주머니준 파지 삽입 알고리즘 적용 |
| 책 정리 | 책 삽입 및 서가 자동 정리 기능 추가 |
| 다수 예약 | 동시 다수 예약 요청 및 큐 처리 시스템 구현 |
| 수령 확인 | 센서 기반(순간 감지, 무게 센서 등) 책 수령 확인 기능 추가 |

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