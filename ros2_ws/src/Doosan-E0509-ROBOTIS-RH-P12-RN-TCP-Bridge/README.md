# Doosan E0509 - ROBOTIS RH-P12-RN TCP Bridge

[English](./README.md) | [한국어](./README.ko.md)

---

## Introduction

This repository provides a ROS 2 TCP bridge for controlling and monitoring a
**ROBOTIS RH-P12-RN(A)** gripper mounted on a **Doosan E0509** robot.

The project runs a DRL-side TCP server on the Doosan controller, communicates
with the gripper through flange RS-485 Modbus RTU, and exposes the gripper to
ROS 2 as reusable nodes, topics, services, and an action interface.

The original standalone Python prototype is preserved under `old/`. The main
implementation is now the ROS 2 package layout under:

- `dsr_gripper_tcp/`
- `dsr_gripper_tcp_interfaces/`

---

## Why This Project Exists

On the target Doosan E0509 setup, directly reading gripper feedback from ROS 2
through DRL was not reliable enough for closed-loop control.

This bridge solves the problem by:

- running a TCP server inside a DRL script on the Doosan controller,
- using DRL to communicate with the gripper over flange RS-485 Modbus RTU,
- sending lightweight binary command/response packets between ROS 2 and DRL,
- publishing gripper state back to ROS 2 for robot task coordination.

---

## Key Features

- **Bidirectional gripper control**
  - Position move
  - Torque ON/OFF
  - Motion profile configuration
  - State readback

- **ROS 2 service/action server**
  - A single node owns the TCP bridge
  - Robot task nodes can control the gripper through stable service/action APIs

- **Safe grasp action**
  - Performs one closing motion
  - Detects grasp success using current feedback
  - Provides action feedback and result for robot task logic

- **Live web dashboard**
  - ROS 2 client of `gripper_service_node` topics/services
  - Browser-based monitoring and manual control
  - Position, current, velocity, temperature, torque state, and moving state

- **Controller recovery helpers**
  - DRL start retry
  - TCP reconnect
  - Gripper initialize retry
  - Flange serial recovery logic
  - Recoverable command retry for read/config/torque paths

---

## System Architecture

```text
                  ROS 2 robot task/action node
                              |
                              | service / action / topic
                              v
                    [ gripper_service_node ]
                              |
                    DoosanGripperTcpBridge
                              |
                         TCP socket
                              |
                [ Doosan controller DRL script ]
                              |
                    Flange serial Modbus RTU
                              |
                    [ ROBOTIS RH-P12-RN(A) ]
```

The web dashboard does not own the TCP bridge. It runs as a ROS 2 client of
`gripper_service_node`:

```text
Browser <-- SocketIO --> web_dashboard_node
                              |
                              | service / topic
                              v
                    [ gripper_service_node ]
                              |
                         TCP bridge
                              |
                         DRL --> Gripper
```

> `gripper_service_node` is the only TCP bridge owner. `web_dashboard_node` can
> run alongside it because it only subscribes to topics and calls services.

---

## Repository Layout

```text
.
├── dsr_gripper_tcp/
│   ├── dsr_gripper_tcp/
│   │   ├── gripper_tcp_protocol.py
│   │   ├── gripper_tcp_bridge.py
│   │   ├── example_gripper_tcp.py
│   │   ├── web_dashboard.py
│   │   ├── web_dashboard_node.py
│   │   └── gripper_service_node.py
│   ├── launch/
│   │   ├── web_dashboard_node.launch.py
│   │   └── gripper_service_node.launch.py
│   ├── package.xml
│   ├── setup.py
│   └── README.md
├── dsr_gripper_tcp_interfaces/
│   ├── msg/GripperState.msg
│   ├── srv/
│   │   ├── GetState.srv
│   │   ├── GetPosition.srv
│   │   ├── SetPosition.srv
│   │   ├── GetMotionProfile.srv
│   │   ├── SetMotionProfile.srv
│   │   └── SetTorque.srv
│   ├── action/SafeGrasp.action
│   ├── CMakeLists.txt
│   └── package.xml
└── old/
    └── legacy standalone prototype files
```

---

## Requirements

- Ubuntu 22.04
- ROS 2 Humble
- Doosan ROS 2 packages, including `dsr_msgs2`
- Python 3.10+
- Python packages:

```bash
pip install flask flask-socketio
```

---

## Build

Place this repository in your ROS 2 workspace `src/` directory.

```bash
cd ~/ros2_ws
colcon build --packages-select dsr_gripper_tcp_interfaces dsr_gripper_tcp
source install/setup.bash
```

---

## Quick Start

### 1. Start the Service/Action Server

Use this node when another robot control node should command the gripper. This
is the recommended operational entrypoint.

```bash
ros2 launch dsr_gripper_tcp gripper_service_node.launch.py \
  controller_host:=110.120.1.56 \
  namespace:=dsr01 \
  service_prefix:=
```

> **Startup `INITIALIZE` can fail a few times or take a while.** TCP may already
> be connected while the Doosan flange RS-485/Modbus gripper response is still
> not ready, so `INITIALIZE attempt N/M failed` can appear before startup
> succeeds. The default configuration retries up to 10 times; the node is ready
> when `Gripper service node ready` is printed.

Main interfaces:

- `/gripper_service/state`
- `/gripper_service/joint_state`
- `/gripper_service/get_state`
- `/gripper_service/get_position`
- `/gripper_service/set_position`
- `/gripper_service/set_motion_profile`
- `/gripper_service/get_motion_profile`
- `/gripper_service/set_torque`
- `/gripper_service/safe_grasp`

Behavior notes:

- `/gripper_service/get_motion_profile` returns the node's cached motion
  profile. It is not a controller readback service in the current version.
- `/gripper_service/safe_grasp` sends a non-blocking move command, then polls
  live state to publish feedback until grasp success, timeout, cancel, or
  target reach without grasp.
- On communication errors, the service node preserves the last known good state
  and updates `status_text` with the latest error context.

Torque ON:

```bash
ros2 service call /gripper_service/set_torque \
  dsr_gripper_tcp_interfaces/srv/SetTorque "{enabled: true}"
```

Open:

```bash
ros2 service call /gripper_service/set_position \
  dsr_gripper_tcp_interfaces/srv/SetPosition "{position: 0, timeout_sec: 5.0}"
```

Move to a target position:

```bash
ros2 service call /gripper_service/set_position \
  dsr_gripper_tcp_interfaces/srv/SetPosition "{position: 700, timeout_sec: 5.0}"
```

`timeout_sec` is how long the service waits for the target position. Values
`0` or lower use the `gripper_service_node` `default_move_timeout_sec` value.

Safe grasp:

```bash
ros2 action send_goal /gripper_service/safe_grasp \
  dsr_gripper_tcp_interfaces/action/SafeGrasp \
  "{target_position: 700, max_current: 400, current_delta_threshold: 120, timeout_sec: 8.0}" \
  --feedback
```

`max_current` is an absolute present-current threshold. The grasp succeeds when
the current reaches this value. `current_delta_threshold` is relative to the
current measured at the start of the action. For example, if the start current
is 50 and the present current is 180, `current_delta` is 130. Values `0` or
lower for `timeout_sec` use `default_safe_grasp_timeout_sec`.

Monitor state:

```bash
ros2 topic echo /gripper_service/state
```

### 2. Start the Web Dashboard

Use this node for browser-based monitoring and manual control.

```bash
ros2 launch dsr_gripper_tcp web_dashboard_node.launch.py \
  gripper_service_ns:=/gripper_service \
  web_port:=5000
```

Open:

```text
http://localhost:5000
```

### 3. Run the CLI Example

```bash
ros2 run dsr_gripper_tcp example_gripper_tcp \
  --controller-host 110.120.1.56 \
  --namespace dsr01 \
  --service-prefix ""
```

---

## Main Parameters

### `gripper_service_node`

| Name | Default | Description |
|---|---:|---|
| `controller_host` | `110.120.1.56` | Doosan controller IP address |
| `tcp_port` | `20002` | DRL TCP server port |
| `namespace` | `dsr01` | Doosan ROS 2 namespace |
| `service_prefix` | `""` | Doosan DRL service prefix. Use values such as `dsr_controller2` if required by the environment |
| `skip_set_autonomous` | `false` | Skip setting the robot mode to autonomous on startup |
| `initialize_on_start` | `true` | **Send the gripper `INITIALIZE` command on startup. Slow RS-485 responses can cause several failed attempts before success** |
| `goal_current` | `400` | Default target current. Used as the grip force/current limit basis |
| `profile_velocity` | `1500` | Default motion velocity |
| `profile_acceleration` | `1000` | Default motion acceleration |
| `poll_rate_hz` | `20.0` | Publish rate for `/gripper_service/state` |
| `position_max` | `1150` | Maximum gripper position pulse. Also used for JointState normalization |
| `default_move_timeout_sec` | `5.0` | Default timeout used when a `set_position` request timeout is 0 or lower |
| `default_safe_grasp_timeout_sec` | `10.0` | Default timeout used when a `safe_grasp` goal timeout is 0 or lower |
| `safe_grasp_feedback_rate_hz` | `10.0` | Feedback publish rate for `safe_grasp` |
| `grasp_current_threshold` | `300` | Absolute current threshold for `grasp_detected` in the state topic |
| `object_lost_current_threshold` | `80` | After grasping, current below this value becomes an object-loss candidate |
| `object_lost_position_delta` | `80` | Position delta from the grasp position required to mark `object_lost` |
| `state_poll_timeout_sec` | `2.0` | TCP response timeout for state reads |
| `command_retry_count` | `1` | Retry count for read/config/torque/initialize commands after TCP transport errors |
| `connect_timeout_sec` | `20.0` | Timeout for connecting to the DRL TCP server |
| `post_drl_start_sleep_sec` | `0.5` | Delay after DRL start before trying the TCP connection |
| `stop_existing_drl` | `true` | Stop an existing DRL program before starting a new one |
| `drl_stop_mode` | `1` | Stop mode for an existing DRL program. `0=QUICK_STO`, `1=QUICK`, `2=SLOW`, `3=HOLD` |
| `drl_stop_settle_sec` | `5.0` | Wait time for DRL to settle into IDLE after stop |
| `drl_start_retry_count` | `3` | Retry count for failed DRL start requests |
| `drl_start_retry_delay_sec` | `1.0` | Delay between DRL start retries |
| `init_attempts` | `10` | **Full retry count for startup `INITIALIZE`** |
| `init_timeout_sec` | `30.0` | **TCP response timeout for `INITIALIZE`** |
| `init_retry_delay_sec` | `2.0` | **Delay between `INITIALIZE` attempts** |

### `web_dashboard_node`

| Name | Default | Description |
|---|---:|---|
| `gripper_service_ns` | `/gripper_service` | Namespace of the `gripper_service_node` to use |
| `web_host` | `0.0.0.0` | Flask/SocketIO bind address |
| `web_port` | `5000` | Web dashboard port |
| `joint_name` | `rh_p12_rn` | Joint name used when the web node publishes legacy `~/joint_state` |
| `position_max` | `1150` | Normalization basis for the UI position bar and JointState |
| `move_timeout_sec` | `5.0` | Timeout passed from web UI move commands to `set_position` |
| `command_timeout_sec` | `5.0` | Upper timeout while waiting for service responses |
| `service_wait_timeout_sec` | `2.0` | Service discovery retry interval |

---

## Safe Grasp Behavior

`SafeGrasp.action` performs a single closing motion to `target_position`.
It does not move the gripper step-by-step.

After the motion completes, grasp success is judged using current feedback:

- success if `abs(final_current) >= max_current`
- success if the current increase from the start is greater than or equal to
  `current_delta_threshold`

The DRL-side move logic also treats a high-current condition as a valid grasp
completion signal, so the gripper can stop before reaching the final close
position when it contacts an object.

---

## State Feedback

`/gripper_service/state` publishes
`dsr_gripper_tcp_interfaces/msg/GripperState`.

Important fields:

- `present_position`: current gripper position pulse
- `goal_position`: last commanded target position
- `present_current`: measured gripper current
- `present_velocity`: measured velocity
- `torque_enabled`: torque state
- `grasp_detected`: current-based grasp detection
- `object_lost`: possible object loss after a grasp
- `status_text`: node-side status string

A robot task action server can subscribe to this topic while executing arm
motions and abort or recover if `object_lost` becomes true.

---

## Legacy Files

The original standalone prototype files are kept under `old/`:

- `old/example_gripper_tcp.py`
- `old/gripper_tcp_bridge.py`
- `old/gripper_tcp_protocol.py`
- `old/web_dashboard.py`
- `old/README.md`

They are kept for reference only. New development should use the ROS 2 packages.

---

## More Documentation

- `dsr_gripper_tcp/README.md`
- `dsr_gripper_tcp_interfaces/msg/GripperState.msg`
- `dsr_gripper_tcp_interfaces/action/SafeGrasp.action`

