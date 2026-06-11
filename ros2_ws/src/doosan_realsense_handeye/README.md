# doosan_realsense_handeye

Measurement-only hand-eye calibration tools for a Doosan E0509 with an Intel RealSense D455f mounted near the gripper/TCP in an eye-in-hand layout.

This package does not send robot motion, gripper, servo, MoveJ, or MoveLine commands. Move the robot manually with your normal approved workflow, then explicitly save each sample.

## What It Computes

The package estimates and saves:

```text
T_tool_camera
```

Then it applies:

```text
T_base_object = T_base_tool @ T_tool_camera @ T_camera_object
P_base = T_base_tool @ T_tool_camera @ P_camera
```

All translation units are meters. Board dimensions in `config/handeye_config.yaml` must also be meters.

## Workspace Defaults

The current workspace already contains Doosan E0509 and RealSense/gripper camera support in packages such as `dsr_bringup2`, `dakae_e0509_servo`, and `dakae_e0509_imitation_dataset`.

Default frames in `config/handeye_config.yaml` follow the existing TF traces:

- `base_frame: base_link`
- `tool_frame: link_6`
- `camera_frame: camera_color_optical_frame`

Default RealSense color topics are:

- `/camera/camera/color/image_raw`
- `/camera/camera/color/camera_info`

Do not treat these as universal. Confirm your live setup before collecting samples.

## Install

```bash
cd /home/dakae/ros2_ws
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-select doosan_realsense_handeye
source install/setup.bash
```

Python dependencies needed at runtime include OpenCV with `aruco`, NumPy, PyYAML, and `cv_bridge`.

## Check Topics And Frames

After RealSense and Doosan bringup are running:

```bash
ros2 topic list | grep camera
ros2 topic echo /camera/camera/color/camera_info --once
ros2 run tf2_ros tf2_echo base_link link_6
ros2 run tf2_ros tf2_echo link_6 camera_color_optical_frame
ros2 run tf2_tools view_frames
```

Edit `config/handeye_config.yaml` if your topic or frame names differ. The collector, calibration
runner, validation runner, point transformer, and validation launch wrapper read their defaults from
that YAML unless you override them on the command line.

## Calibration Flow

1. RealSense 실행

```bash
ros2 launch realsense2_camera rs_launch.py \
  enable_color:=true \
  enable_depth:=true \
  align_depth.enable:=true \
  enable_sync:=true \
  publish_tf:=false
```

2. Doosan robot bringup 실행

For the gripper/camera URDF used in this workspace:

```bash
ros2 launch dakae_e0509_servo dsr_bringup2_rviz_gripper_camera.launch.py host:=<ROBOT_IP>
```

Or inspect the vendor bringup arguments first:

```bash
ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py --show-args
```

3. tf 확인

```bash
ros2 run tf2_ros tf2_echo base_link link_6
ros2 run tf2_ros tf2_echo base_link camera_color_optical_frame
```

4. marker board를 작업대에 고정

Use a rigidly mounted ChArUco board first if possible. Set exact board dimensions in meters:

```yaml
board_type: charuco
charuco:
  squares_x: 7
  squares_y: 5
  square_length: 0.030
  marker_length: 0.022
```

For a single ArUco marker board:

```yaml
board_type: aruco
aruco:
  marker_length: 0.050
  marker_id: 6
```

5. 로봇을 서로 다른 15~30개 자세로 이동

Move manually. Use diverse wrist rotations and distances while keeping the fixed board visible. This package intentionally has no robot motion code.

6. 각 자세마다 sample 저장

```bash
ros2 launch doosan_realsense_handeye handeye_sample_collector.launch.py
```

Press `s` in the collector terminal, or call:

```bash
ros2 service call /handeye_sample_collector/save_sample std_srvs/srv/Trigger {}
```

Samples are saved by default to:

```text
/home/dakae/ros2_ws/src/doosan_realsense_handeye/data/samples/handeye_samples.yaml
```

7. hand-eye calibration 실행

```bash
ros2 run doosan_realsense_handeye run_handeye_calibration \
  --samples /home/dakae/ros2_ws/src/doosan_realsense_handeye/data/samples/handeye_samples.yaml \
  --output /home/dakae/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_tool_camera.yaml \
  --method TSAI
```

Supported methods:

- `TSAI`
- `PARK`
- `HORAUD`
- `ANDREFF`
- `DANIILIDIS`

OpenCV receives `T_base_tool` as gripper-to-base and `T_camera_target` as target-to-camera, then returns camera-to-gripper, saved here as `T_tool_camera`.

8. validation 실행

```bash
ros2 run doosan_realsense_handeye validate_handeye \
  --samples /home/dakae/ros2_ws/src/doosan_realsense_handeye/data/samples/handeye_samples.yaml \
  --calibration-result /home/dakae/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_tool_camera.yaml
```

Or:

```bash
ros2 launch doosan_realsense_handeye validate_handeye.launch.py
```

Validation computes `T_base_target` for every sample and reports mean position, XYZ standard deviation, max error, RMSE, and rotation spread.

9. camera 좌표의 임의 점을 base 좌표로 변환

Keep Doosan TF running, then:

```bash
ros2 run doosan_realsense_handeye object_to_base_transformer --point 0.1 0.0 0.5
```

The point is interpreted as `[x, y, z]` in the camera frame associated with the saved
`T_tool_camera`, meters. The live TF lookup uses `object_to_base_transformer.ros__parameters`
from `config/handeye_config.yaml`; override with `--base-frame` or `--tool-frame` only for a
one-off test.

## Live Fixed Board Check

After calibration, `live_target_to_base` detects the ChArUco or ArUco target in the RealSense color
image and prints the live target pose in `base_link`. It also computes a target-relative approach
pose and publishes both poses as TF for RViz.

For the current calibration file:

```text
/home/dakae/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_tool_camera.yaml
```

the YAML key is still `T_tool_camera` for code compatibility, but the actual meaning is
`T_link_6_camera` because samples were collected with `tool_frame: link_6`.

Run:

```bash
source /home/dakae/ros2_ws/install/setup.bash
ros2 launch doosan_realsense_handeye live_target_to_base.launch.py
```

Or directly:

```bash
ros2 run doosan_realsense_handeye live_target_to_base --ros-args \
  --params-file /home/dakae/ros2_ws/src/doosan_realsense_handeye/config/handeye_config.yaml
```

The node computes:

```text
T_base_target = T_base_link_6 @ T_link_6_camera @ T_camera_target
T_base_approach = T_base_target @ T_target_approach
```

Current live defaults are for the wall-mounted ArUco marker:

```yaml
live_target_to_base:
  ros__parameters:
    board_type: aruco
    base_frame: base_link
    tool_frame: link_6
    camera_frame: camera_color_optical_frame
    calibration_result_path: /home/dakae/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_tool_camera.yaml
    approach_offset_x: 0.0
    approach_offset_y: 0.0
    approach_offset_z: 0.30
    aruco:
      marker_id: 6
      marker_length: 0.038
      dictionary: DICT_4X4_50
```

The approach offset is expressed in the detected target frame. The default is `+0.30 m` along marker
Z. Depending on marker coordinate direction and which side of the marker should be approached, flip
the sign:

```bash
ros2 run doosan_realsense_handeye live_target_to_base --ros-args \
  --params-file /home/dakae/ros2_ws/src/doosan_realsense_handeye/config/handeye_config.yaml \
  -p approach_offset_z:=-0.30
```

RViz TF frames:

- `base_link -> detected_target`
- `base_link -> target_approach`

It only reads RealSense image/camera info, TF, and the calibration YAML. It does not send robot,
gripper, servo, MoveJ, or MoveLine commands.

If the board is fixed on the work surface, `T_base_target` should stay nearly constant while the
robot pose changes. Small variation is expected from image noise, marker detection quality, TF timing,
mount flex, and calibration residuals. Large jumps usually point to a wrong frame, stale TF, an
incorrect board size/dictionary, or a calibration result that does not match the current camera mount.

## TCP Marker Alignment Preview

`align_to_marker_preview` reads the live TFs from `live_target_to_base` and publishes a preview-only
TCP goal:

- `base_link -> detected_target`
- `base_link -> target_approach`
- `base_link -> link_6`
- publishes `base_link -> aligned_tcp_goal`

The goal position is the `target_approach` translation. The goal orientation aligns the TCP Z axis
with the marker Z axis. For wall-marker approach, the default is opposite direction:

```text
z_tcp_goal = -z_marker_base
```

To keep wrist roll close to the current pose, the node projects the current TCP X axis onto the
plane perpendicular to `z_tcp_goal`, then rebuilds a right-handed TCP basis. It logs marker Z,
current TCP Z, goal TCP Z, alignment angles, and the `aligned_tcp_goal` xyz/rpy/quaternion.

Run it with the live target node already publishing `detected_target` and `target_approach`:

```bash
source /home/dakae/ros2_ws/install/setup.bash

ros2 launch doosan_realsense_handeye live_target_to_base.launch.py
ros2 launch doosan_realsense_handeye align_to_marker_preview.launch.py
```

Default parameters:

```yaml
align_to_marker_preview:
  ros__parameters:
    base_frame: base_link
    tool_frame: link_6
    target_frame: detected_target
    approach_frame: target_approach
    goal_frame: aligned_tcp_goal
    align_axis: z
    axis_direction: opposite
    output_period_sec: 0.5
```

Use `axis_direction:=same` if your marker and TCP convention should point the TCP Z axis in the same
direction as marker Z:

```bash
ros2 run doosan_realsense_handeye align_to_marker_preview --ros-args \
  --params-file /home/dakae/ros2_ws/src/doosan_realsense_handeye/config/handeye_config.yaml \
  -p axis_direction:=same
```

This node never sends robot motion, servo, MoveJ, MoveLine, or gripper commands. It only publishes
`aligned_tcp_goal` for RViz inspection and later controlled motion integration.

## One-Shot Move To Approach

`move_to_approach` is a guarded one-shot motion test that reads:

- `base_link -> target_approach`
- `base_link -> link_6`

It uses only the `target_approach` translation as the target XYZ. It does not use the marker center
or `detected_target` as a motion target. For the first test, it does not use TF RPY as the Doosan
orientation. Instead, it reads the current Doosan task pose and reuses the controller's current
`rx, ry, rz` values unchanged.

The Doosan services checked in this workspace are:

```text
dsr_msgs2/srv/GetCurrentPosx
int8 ref        # DR_BASE(0), DR_WORLD(2), user coord(101~200)
---
std_msgs/Float64MultiArray[] task_pos_info
bool success
```

```text
dsr_msgs2/srv/MoveLine
pos: double[6]
vel: double[2]
acc: double[2]
time: double
radius: double
ref: int8        # DR_BASE(0), DR_TOOL(1), DR_WORLD(2)
mode: int8       # ABS(0), REL(1)
blend_type: int8
sync_type: int8
---
success: bool
```

The generated request uses absolute base motion:

```text
ref=0
mode=0
sync_type=0
pos=[x_mm, y_mm, z_mm, current_rx_deg, current_ry_deg, current_rz_deg]
```

Here `x_mm, y_mm, z_mm` come from `base_link -> target_approach`. The `current_rx_deg,
current_ry_deg, current_rz_deg` values come from `/dsr01/aux_control/get_current_posx`, not from
TF Euler conversion. If the current task pose cannot be read, the node refuses to move even when
`execute=true`.

Dry run first:

```bash
source /home/dakae/ros2_ws/install/setup.bash

# Keep live target TF publisher running in another terminal.
ros2 launch doosan_realsense_handeye live_target_to_base.launch.py

# In this terminal, compute and print the MoveLine request only.
ros2 launch doosan_realsense_handeye move_to_approach.launch.py
```

The default is:

```yaml
move_to_approach:
  ros__parameters:
    execute: false
    max_step_m: 0.30
    vel: 20.0
    acc: 40.0
    move_service: /dsr01/motion/move_line
    current_posx_service: /dsr01/aux_control/get_current_posx
    task_ref: 0
```

Before any real motion, inspect the printed current `link_6` TF XYZ, target TF XYZ, current Doosan
task pose, distance, and final `MoveLine pos [mm,deg]`. The node refuses to move if either TF is
missing, if the current task pose service fails, if values are NaN/Inf, or if the target is farther
than `max_step_m`.

Actual one-shot motion requires explicitly setting `execute:=true`:

```bash
ros2 run doosan_realsense_handeye move_to_approach --ros-args \
  --params-file /home/dakae/ros2_ws/src/doosan_realsense_handeye/config/handeye_config.yaml \
  -p execute:=true
```

It sends at most one `MoveLine` service request, then exits. It does not automatically repeat,
track, servo, or move toward `detected_target`.

## Common Problems

- Frame direction reversed: verify whether your TF or detector gives `T_camera_target` or `T_target_camera`.
- `T_camera_target` and `T_target_camera` confusion: this package stores the OpenCV marker pose as target-to-camera, named `T_camera_target` to mean camera frame parent, target child.
- mm/m unit confusion: RealSense and OpenCV output translations are meters only if marker length and board sizes are meters.
- Color frame/depth frame confusion: use the color image with the matching color `CameraInfo`; do not mix depth optical frame intrinsics with color pixels.
- TCP frame and real gripper frame mismatch: confirm `link_6` or your chosen `tool_frame` represents the physical point you want. If not, use the correct tool/gripper frame in YAML.
- Pose diversity too low: collect 15 to 30 poses with different wrist rotations, not only small translations.
- Marker detection unstable: improve lighting, print quality, board flatness, exposure, and board size; ChArUco is preferred over a single marker.
- RealSense TF ownership conflict: if the robot URDF publishes camera frames, launch RealSense with `publish_tf:=false`.
- Large validation RMSE: check board dimensions, wrong marker ID, wrong dictionary, stale TF, loose camera mount, and hand-eye method sensitivity.
