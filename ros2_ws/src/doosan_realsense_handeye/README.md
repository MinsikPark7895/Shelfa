# doosan_realsense_handeye

Doosan E0509 + RealSense + ArUco marker alignment and OCR book scan helper package for ROS2 Humble.

This package keeps the gripper/camera URDF wrapper, Doosan RViz bringup wrapper, ArUco alignment/probe nodes, and the OCR-based book scan pipeline. It does not modify `doosan-robot2` vendor packages.

## Included Files

- `urdf/e0509_gripper_camera.urdf.xacro`
- `urdf/gripper_camera_macro.xacro`
- `launch/dsr_bringup2_rviz_gripper_camera.launch.py`
- `doosan_realsense_handeye/aruco_realsense_tf_publisher.py`
- `doosan_realsense_handeye/simple_aruco_marker_tf_publisher.py`
- `doosan_realsense_handeye/controller_loader.py`
- `doosan_realsense_handeye/aruco_marker_proto_align.py`
- `doosan_realsense_handeye/aruco_marker_yaw_align.py`
- `doosan_realsense_handeye/aruco_marker_step_align.py`
- `doosan_realsense_handeye/aruco_marker_rotation_probe.py`
- `doosan_realsense_handeye/aruco_handeye_target_tf.py`
- `doosan_realsense_handeye/handeye_transform_utils.py`
- `doosan_realsense_handeye/handeye_config_utils.py`
- `doosan_realsense_handeye/charuco_detector.py`
- `doosan_realsense_handeye/handeye_sample_collector.py`
- `doosan_realsense_handeye/run_handeye_calibration.py`
- `doosan_realsense_handeye/validate_handeye.py`
- `doosan_realsense_handeye/object_to_base_transformer.py`
- `doosan_realsense_handeye/live_target_to_base.py`
- `doosan_realsense_handeye/align_to_marker_preview.py`
- `doosan_realsense_handeye/move_to_approach.py`
- `doosan_realsense_handeye/tf_book_target_to_approach.py`
- `doosan_realsense_handeye/realtime_yolo_paddle_ocr.py`
- `doosan_realsense_handeye/vision_pipeline_utils.py`
- `doosan_realsense_handeye/book_scan_after_alignment.py`
- `doosan_realsense_handeye/book_mission_state_machine.py`
- `config/handeye_servo.yaml`
- `config/book_mission_state_machine.yaml`
- `launch/simple_aruco_marker_tf_publisher.launch.py`
- `launch/aruco_handeye_target_tf.launch.py`
- `launch/handeye_sample_collector.launch.py`
- `launch/validate_handeye.launch.py`
- `launch/live_target_to_base.launch.py`
- `launch/align_to_marker_preview.launch.py`
- `launch/object_to_base_transformer.launch.py`
- `launch/move_to_approach.launch.py`
- `launch/book_mission_state_machine.launch.py`

The old keyboard Servo test code is intentionally not included in this release.

## Required Environment

- ROS2 Humble
- Doosan ROS2 packages installed in the workspace, including:
  - `doosan-robot2`
  - `dsr_bringup2`
  - `dsr_controller2`
  - `dsr_description2`
  - `dsr_msgs2`
- RH-P12 gripper description package:
  - `rh_p12_rn_a_description`
- RealSense ROS wrapper:
  - `realsense2_camera`
- Separate ArUco TF publisher:
  - expected marker frame for the current mission flow: `aruco_marker_0`

Expected TF chain:

```text
base_link
-> ... -> link_6 -> tool0
-> camera_color_optical_frame
-> aruco_marker_0
```

## Build

Copy this package into the receiver's ROS2 workspace:

```bash
cd ~/ros2_ws/src
# place doosan_realsense_handeye here

cd ~/ros2_ws
colcon build --symlink-install --packages-select doosan_realsense_handeye
source install/setup.bash
```

## Current Runtime Startup Order

`book_mission_state_machine` does not own the robot, camera, gripper, or marker
publisher by itself. Start the following nodes in separate terminals before
running the mission node.

Use the workspace setup in every terminal:

```bash
cd /home/dakae/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
```

### 1. Doosan Robot Bringup

This starts the Doosan E0509 control stack and publishes the robot TF tree.
For the current lab network, the commonly used controller host is
`192.168.137.100`. Replace it if the robot IP is different.

```bash
ros2 launch doosan_realsense_handeye dsr_bringup2_rviz_gripper_camera.launch.py \
  host:=192.168.137.100 \
  rt_host:=192.168.137.50 \
  mode:=real \
  model:=e0509 \
  name:=dsr01
```

Quick checks:

```bash
ros2 service list | grep /dsr01/motion
ros2 topic echo /dsr01/joint_states --once
```

### 2. RH-P12 Gripper TCP Bridge

The mission node talks to `/gripper_service/*`. Keep this bridge running if
gripper control is enabled.

```bash
ros2 launch dsr_gripper_tcp gripper_service_node.launch.py \
  controller_host:=192.168.137.100 \
  namespace:=dsr01 \
  service_prefix:=dsr_controller2
```

Quick checks:

```bash
ros2 service list | grep /gripper_service
ros2 topic echo /gripper_service/state --once
```

### 3. RealSense Camera Node

The vision pipeline subscribes to RealSense topics. It no longer opens the
camera with `pyrealsense2` directly.

```bash
ros2 launch realsense2_camera rs_launch.py \
  enable_color:=true \
  enable_depth:=true \
  align_depth.enable:=true \
  publish_tf:=true \
  rgb_camera.color_profile:=1280x720x30 \
  depth_module.depth_profile:=1280x720x30
```

Required topics:

```bash
ros2 topic list | grep camera
ros2 topic echo /camera/camera/color/camera_info --once
```

The mission expects these topics by default:

- `/camera/camera/color/image_raw`
- `/camera/camera/color/camera_info`
- `/camera/camera/aligned_depth_to_color/image_raw`

### 4. Hand-Eye Static TF

This connects the robot TF tree to the RealSense optical frame. Without this
bridge, alignment can detect the marker but cannot save a base-referenced
payload.

```bash
ros2 run tf2_ros static_transform_publisher \
  -0.01151140132331922 \
  -0.04068446401037196 \
  0.06598386871074707 \
  -0.0004988115704339 \
  0.01053595856067635 \
  0.9999443259620144 \
  -0.0002995673497136527 \
  link_6 \
  camera_color_optical_frame
```

Quick check:

```bash
ros2 run tf2_ros tf2_echo base_link camera_color_optical_frame
```

### 5. ArUco Marker TF Publisher

The current mission uses marker id `0` and frame `aruco_marker_0`.

```bash
ros2 run doosan_realsense_handeye simple_aruco_marker_tf_publisher --ros-args \
  -p marker_id:=0 \
  -p child_frame:=aruco_marker_0 \
  -p parent_frame:=camera_color_optical_frame \
  -p image_topic:=/camera/camera/color/image_raw \
  -p camera_info_topic:=/camera/camera/color/camera_info
```

Quick check:

```bash
ros2 run tf2_ros tf2_echo camera_color_optical_frame aruco_marker_0
```

### 6. Mission State Machine

Dry-run launch, no real robot motion:

```bash
ros2 launch doosan_realsense_handeye book_mission_state_machine.launch.py
```

Manual stepping with real robot motion. Each major state waits for Enter:

```bash
ros2 run doosan_realsense_handeye book_mission_state_machine \
  --ros-args \
  -p dry_run:=false \
  -p auto_run:=false \
  -p alignment_dry_run:=false \
  -p alignment_auto_run:=false
```

Useful runtime outputs:

- `realtime_results/alignment_payload.json`
- `realtime_results/book_scan_result.json`
- `realtime_results/target_book_lock.json`
- `realtime_results/mission_state_trace.json`
- `realtime_results/mission_result.json`

## YOLO Book Spine Model

`realtime_yolo_paddle_ocr.py` loads the YOLO OBB model from this project-relative path:

```text
runs/obb/runs/obb/book_spine_v1/weights/best.pt
```

If the model was trained or exported elsewhere, copy it into the package workspace before running book scan:

```bash
cd /home/user/doosan_realsense_handeye
mkdir -p runs/obb/runs/obb/book_spine_v1/weights
cp "/home/user/Book spine instance segmentation.v1i.yolov8/runs/obb/runs/obb/book_spine_v1/weights/best.pt" \
  runs/obb/runs/obb/book_spine_v1/weights/best.pt
ls -lh runs/obb/runs/obb/book_spine_v1/weights/best.pt
```

## 1. Start RealSense

Start the external RealSense node first. This package now subscribes to the published image
topics instead of opening the camera device itself.

For the current mission flow, run the same RealSense command shown in
`Current Runtime Startup Order`. The important part is that color, aligned
depth, and camera info topics are available.

```bash
ros2 launch realsense2_camera rs_launch.py \
  enable_color:=true \
  enable_depth:=true \
  align_depth.enable:=true \
  publish_tf:=true \
  rgb_camera.color_profile:=1280x720x30 \
  depth_module.depth_profile:=1280x720x30
```

The book-scan pipeline expects:

- `/camera/camera/color/image_raw`
- `/camera/camera/color/camera_info`
- `/camera/camera/aligned_depth_to_color/image_raw`

## 2. Start Doosan RViz Bringup With Custom URDF

This launch keeps the Doosan namespace/controller/RViz flow but uses `e0509_gripper_camera.urdf.xacro`.

```bash
ros2 launch doosan_realsense_handeye dsr_bringup2_rviz_gripper_camera.launch.py \
  host:=192.168.137.100 \
  rt_host:=192.168.137.50 \
  mode:=real \
  model:=e0509 \
  name:=dsr01
```

Useful checks:

```bash
ros2 topic echo /dsr01/joint_states --once
ros2 run tf2_ros tf2_echo base_link camera_color_optical_frame
ros2 run tf2_tools view_frames
```

## 3. Start ArUco TF Publisher

This package includes a small image-based ArUco TF publisher that subscribes to
`/camera/camera/color/image_raw` and `/camera/camera/color/camera_info`.
The current mission flow detects marker id `0` and publishes
`camera_color_optical_frame -> aruco_marker_0`.

Run it directly:

```bash
ros2 run doosan_realsense_handeye simple_aruco_marker_tf_publisher --ros-args \
  -p marker_id:=0 \
  -p child_frame:=aruco_marker_0 \
  -p parent_frame:=camera_color_optical_frame \
  -p image_topic:=/camera/camera/color/image_raw \
  -p camera_info_topic:=/camera/camera/color/camera_info
```

For the current mission flow, prefer the explicit `ros2 run` command above so
`marker_id`, `child_frame`, image topic, and camera info topic are all fixed.

Optional display:

```bash
ros2 run doosan_realsense_handeye simple_aruco_marker_tf_publisher --ros-args \
  -p marker_id:=0 \
  -p child_frame:=aruco_marker_0 \
  -p parent_frame:=camera_color_optical_frame \
  -p show_display:=true
```

```bash
ros2 run tf2_ros tf2_echo camera_color_optical_frame aruco_marker_0
```

## 3.5 Hand-Eye Bridge For Base-Referenced Target Frames

`aruco_handeye_target_tf` is a reference/legacy helper that merges a
`camera -> aruco_marker_*` TF with the
hand-eye calibration result `T_tool_camera` and the live robot TF `base_link -> link_6`.

It publishes:

```text
base_link -> detected_target
base_link -> target_approach
base_link -> aligned_tcp_goal
```

Formula:

```text
T_base_target = T_base_tool @ T_tool_camera @ T_camera_marker
```

This lets the existing E0509 servo package keep using the current ArUco TF publisher while gaining
the base-referenced target/approach frames from the newer hand-eye workflow.

Default config file:

```text
config/handeye_servo.yaml
```

Run:

```bash
ros2 launch doosan_realsense_handeye aruco_handeye_target_tf.launch.py
```

Or:

```bash
ros2 run doosan_realsense_handeye aruco_handeye_target_tf --ros-args \
  --params-file /home/user/Shelfa/ros2_ws/src/doosan_realsense_handeye/config/handeye_servo.yaml
```

Before running, confirm that `calibration_result_path` points at the correct hand-eye YAML.
The default assumes:

```text
/home/user/Shelfa/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_tool_camera.yaml
```

## 3.6 Hand-Eye Calibration And Validation Tools

This package now also includes the measurement-only hand-eye tools used in the separate
`doosan_realsense_handeye` workspace:

```bash
ros2 launch doosan_realsense_handeye handeye_sample_collector.launch.py
ros2 run doosan_realsense_handeye run_handeye_calibration -- --help
ros2 launch doosan_realsense_handeye validate_handeye.launch.py
ros2 run doosan_realsense_handeye object_to_base_transformer --point 0.1 0.0 0.5
ros2 launch doosan_realsense_handeye live_target_to_base.launch.py
ros2 launch doosan_realsense_handeye align_to_marker_preview.launch.py
ros2 launch doosan_realsense_handeye move_to_approach.launch.py
```

## 3.6 TF Book Approach Verification

`tf_book_target_to_approach` reads `book_scan_result.json`, converts the selected
book's camera-space point to `base_link` through the live `base_link -> link_6`
TF plus the hand-eye calibration matrix, and computes a safe approach pose in
front of the book.

Dry-run mode is the default. Add `--execute` only after confirming the printed
target and safety checks.

Example:

```bash
ros2 run doosan_realsense_handeye tf_book_target_to_approach \
  --scan-result realtime_results/book_scan_result.json \
  --book-index 0
```

The default calibration search order is:

```text
T_link6_camera_ANDREFF.yaml
T_tool_camera.yaml
config/handeye_servo.yaml calibration_result_path
```

## 4. Main Prototype Alignment Node

`aruco_marker_proto_align` is the main hand-operated prototype node.

It performs at most one robot action per Enter key press:

```text
START
-> MOVEJ_READY
-> WAIT_AFTER_MOVEJ
-> COARSE_TRANSLATION_ALIGN
-> WAIT_AFTER_COARSE_TRANSLATION
-> ROTATION_ALIGN
-> WAIT_AFTER_ROTATION
-> TRANSLATION_ALIGN
-> DONE
```

Default observation MoveJ pose:

```text
[45.72522, 14.837949, 112.757722, -57.964578, 124.563048, 47.803207]
```

This value is in degrees and ordered as `joint_1` through `joint_6`.

### Dry Run

Always start with dry run:

```bash
ros2 run doosan_realsense_handeye aruco_marker_proto_align --ros-args \
  -p target_distance_m:=0.40
```

### Actual Run

Start small:

```bash
ros2 run doosan_realsense_handeye aruco_marker_proto_align --ros-args \
  -p dry_run:=false \
  -p target_distance_m:=0.40 \
  -p coarse_axis_mode:=all \
  -p coarse_translation_scale:=0.5 \
  -p max_step_mm:=1.0 \
  -p max_rot_step_deg:=1.0
```

Recommended conservative auto run:

```bash
ros2 run doosan_realsense_handeye aruco_marker_proto_align --ros-args \
  -p dry_run:=false \
  -p auto_run:=true \
  -p target_distance_m:=0.30
```

If rotation oscillates, test the opposite rotation sign:

```bash
ros2 run doosan_realsense_handeye aruco_marker_proto_align --ros-args \
  -p dry_run:=false \
  -p auto_run:=true \
  -p target_distance_m:=0.30 \
  -p sign_tool_b_from_camera_y:=-1.0
```

### Skip MoveJ

Use this if the robot is already in a safe observation pose:

```bash
ros2 run doosan_realsense_handeye aruco_marker_proto_align --ros-args \
  -p dry_run:=false \
  -p enable_movej:=false \
  -p target_distance_m:=0.40 \
  -p max_step_mm:=1.0 \
  -p max_rot_step_deg:=1.0
```

### Runtime Commands

- Enter: run one action for the current state
- `q`: quit
- `next`: in `ROTATION_ALIGN`, force transition to translation
- `rot`: in `TRANSLATION_ALIGN`, return to rotation alignment
- `done`: in `TRANSLATION_ALIGN`, print final status and enter `DONE`

## Translation Settings

Coarse translation before rotation is enabled by default:

```text
enable_coarse_translation_before_rotation = true
coarse_axis_mode = all
coarse_translation_scale = 0.5
```

Fine translation uses:

```text
axis_mode = largest
```

Current default translation mapping:

```text
tool_axis_from_optical_x = x
tool_axis_from_optical_y = y
tool_axis_from_optical_z = z
sign_tool_from_optical_x = -1.0
sign_tool_from_optical_y = -1.0
sign_tool_from_optical_z = 1.0
```

Verify one translation axis at a time before trusting `largest` or `all`:

```bash
ros2 run doosan_realsense_handeye aruco_marker_proto_align --ros-args \
  -p dry_run:=false \
  -p enable_movej:=false \
  -p target_distance_m:=0.40 \
  -p axis_mode:=z_only \
  -p max_step_mm:=1.0

ros2 run doosan_realsense_handeye aruco_marker_proto_align --ros-args \
  -p dry_run:=false \
  -p enable_movej:=false \
  -p target_distance_m:=0.40 \
  -p axis_mode:=x_only \
  -p max_step_mm:=1.0

ros2 run doosan_realsense_handeye aruco_marker_proto_align --ros-args \
  -p dry_run:=false \
  -p enable_movej:=false \
  -p target_distance_m:=0.40 \
  -p axis_mode:=y_only \
  -p max_step_mm:=1.0
```

If an error grows during an axis-only test, flip the corresponding sign:

```bash
-p sign_tool_from_optical_x:=1.0
-p sign_tool_from_optical_y:=1.0
-p sign_tool_from_optical_z:=-1.0
```

## Rotation Settings

This setup uses only Doosan MoveLine B, `pos[4]`, for camera-frame Y rotation alignment.

```text
pos = [0, 0, 0, 0, move_b_deg, 0]
```

Default:

```text
sign_tool_b_from_camera_y = 1.0
max_rot_step_deg = 1.0
```

If `abs(angle_y_deg)` increases after a rotation step, flip:

```bash
-p sign_tool_b_from_camera_y:=-1.0
```

## Helper Nodes

Position-only helper:

```bash
ros2 run doosan_realsense_handeye aruco_marker_step_align --ros-args \
  -p target_distance_m:=0.40 \
  -p axis_mode:=z_only
```

Y-rotation-only helper:

```bash
ros2 run doosan_realsense_handeye aruco_marker_yaw_align --ros-args \
  -p max_rot_step_deg:=1.0
```

Rotation probe:

```bash
ros2 run doosan_realsense_handeye aruco_marker_rotation_probe
```

## Book Scan After Alignment

`book_scan_after_alignment` reads the saved alignment payload, computes a
book-scan pose, and runs YOLO OBB + PaddleOCR + depth/TF validation. It does
not execute book picking or grasp calibration.

Before running it, complete these steps:

```text
1. Move to the ArUco search/alignment pose.
2. Detect the ArUco marker and finish bookshelf alignment.
3. Save realtime_results/alignment_payload.json.
```

Basic scan:

```bash
ros2 run doosan_realsense_handeye book_scan_after_alignment \
  --alignment-payload-json realtime_results/alignment_payload.json \
  --target-title 제3인류
```

Headless scan:

```bash
ros2 run doosan_realsense_handeye book_scan_after_alignment \
  --alignment-payload-json realtime_results/alignment_payload.json \
  --target-title 제3인류 \
  --no-display
```

YOLO-only scan without OCR:

```bash
ros2 run doosan_realsense_handeye book_scan_after_alignment \
  --alignment-payload-json realtime_results/alignment_payload.json \
  --disable-ocr \
  --book-index 0
```

Mock payload test:

```bash
ros2 run doosan_realsense_handeye book_scan_after_alignment \
  --use-mock-alignment \
  --target-title 제3인류
```

Outputs:

- `realtime_results/book_scan_result.json`
- `realtime_results/target_book_lock.json`
- `realtime_results/book_scan_ocr_debug/`

Notes:

- `book_index` is per-scan and not stable across runs.
- OCR input crops are saved by default for later inspection.
- Use `--ocr-max-books` or `--disable-ocr` if OCR latency is too high.
- `realtime_yolo_paddle_ocr.py` provides the shared subscriber-based camera/YOLO/OCR utility code used by this scan pipeline.

## Book Mission State Machine

`book_mission_state_machine` runs the full flow as one sequential mission:

```text
START
-> MOVE_HOME
-> PREPARE_GRIPPER_VIEW
-> ALIGN_MARKER
-> DETECT_BOOK
-> PREPARE_GRIPPER_PICK_OPEN
-> MOVE_TO_BOOK_35CM_OFFSET
-> LOWER_CAMERA_FOR_VERIFY
-> VERIFY_BOOK_AGAIN
-> ALIGN_BOOK_LATERAL
-> MOVE_LEFT_1CM
-> SET_GRIPPER_600_AFTER_ALIGN
-> EXPERIMENTAL_PICK_CYCLES
-> MOVE_TO_PLACE_POSE
-> LOWER_TO_PLACE_BOOK
-> RELEASE_BOOK
-> RETURN_HOME
-> DONE
```

It reuses the existing alignment, scan, and pick helpers, and writes progress to:

- `realtime_results/mission_state_trace.json`
- `realtime_results/mission_result.json`

Run it with the default config:

```bash
ros2 launch doosan_realsense_handeye book_mission_state_machine.launch.py
```

Manual stepping with real robot motion:

```bash
ros2 run doosan_realsense_handeye book_mission_state_machine \
  --ros-args \
  -p dry_run:=false \
  -p auto_run:=false \
  -p alignment_dry_run:=false \
  -p alignment_auto_run:=false
```

Override the designated place pose as needed:

```bash
ros2 run doosan_realsense_handeye book_mission_state_machine --ros-args \
  -p place_joint_pose_deg:="[10.0, 0.0, 90.0, 0.0, 90.0, 0.0]"
```

## Current Full Pick Then Marker2 Place Demo

This is the current detect-and-pick demo route for the Doosan E0509,
RealSense, RH-P12 gripper, ArUco marker 0 bookshelf alignment, and ArUco
marker 2 placement target.

All commands below assume this workspace layout:

```bash
cd /home/user/Shelfa/ros2_ws
source /opt/ros/humble/setup.bash
source /home/user/Shelfa/ros2_ws/install/setup.bash
source /home/user/Shelfa/ros2_ws/src/doosan_realsense_handeye/_external_clones/Shelfa-detect-and-pick/ros2_ws/install/setup.bash
export ROS_LOG_DIR=/tmp
```

Start the required runtime nodes in separate terminals.

### 1. Gripper Service

```bash
ros2 launch dsr_gripper_tcp gripper_service_node.launch.py
```

### 2. RealSense Camera

```bash
ros2 launch realsense2_camera rs_launch.py \
  enable_color:=true \
  enable_depth:=true \
  align_depth.enable:=true \
  publish_tf:=true \
  rgb_camera.color_profile:=1280x720x30 \
  depth_module.depth_profile:=1280x720x30
```

### 3. Hand-Eye Static TF

```bash
ros2 run tf2_ros static_transform_publisher \
  -0.01151140132331922 \
  -0.04068446401037196 \
  0.06598386871074707 \
  -0.0004988115704339 \
  0.01053595856067635 \
  0.9999443259620144 \
  -0.0002995673497136527 \
  link_6 \
  camera_color_optical_frame
```

### 4. ArUco Marker 0 TF Publisher

Marker 0 is used for bookshelf alignment and first book picking.

```bash
ros2 run doosan_realsense_handeye simple_aruco_marker_tf_publisher \
  --ros-args \
  -p marker_id:=0 \
  -p marker_length_m:=0.05 \
  -p child_frame:=aruco_marker_0 \
  -p parent_frame:=camera_color_optical_frame \
  -p image_topic:=/camera/camera/color/image_raw \
  -p camera_info_topic:=/camera/camera/color/camera_info
```

### 5. ArUco Marker 2 TF Publisher

Marker 2 is used for the second placement target.

```bash
ros2 run doosan_realsense_handeye simple_aruco_marker2_tf_publisher \
  --ros-args \
  -p marker_id:=2 \
  -p marker_length_m:=0.05 \
  -p child_frame:=aruco_marker_2 \
  -p parent_frame:=camera_color_optical_frame \
  -p image_topic:=/camera/camera/color/image_raw \
  -p camera_info_topic:=/camera/camera/color/camera_info
```

### 6. Full Demo Runner

The full runner performs first bookshelf pick/place, waits for Enter, then
performs marker2 placement.

```bash
ros2 run doosan_realsense_handeye full_pick_then_marker2_place_sequence \
  --ros-args \
  -p dry_run:=false
```

The current runner uses manual stepping. Major movement states wait for Enter;
enter `q` at prompts that support it to abort.

### First Mission: Bookshelf Pick And Home Placement

```text
ALIGN_MARKER
  Align to ArUco marker 0. Marker alignment is manual-step mode.

DETECT_BOOK
  Move to the book scan pose from the alignment payload.
  Detect books with YOLO, run OCR, match target_title="제3인류".
  Print selected book pixels, camera_xyz_m, and base_xyz_m.

PREPARE_GRIPPER_PICK_OPEN
  Open the gripper before approaching the selected book.

MOVE_TO_BOOK_35CM_OFFSET
  Move along tool Z toward the selected book.
  Target distance is 0.35 m from the selected book depth.
  Current TCP pose and selected book base coordinates are logged before motion.

LOWER_CAMERA_FOR_VERIFY
  Move along tool Y by 70 mm for the second OCR verification pose.

VERIFY_BOOK_AGAIN
  Re-run YOLO/OCR at the current pose and confirm the selected book.

ALIGN_BOOK_LATERAL
  Laterally align to the verified book using image-space error.

MOVE_LEFT_1CM
  Apply the final lateral offset before gripping.

SET_GRIPPER_600_AFTER_ALIGN
  Set the gripper to position 600.

EXPERIMENTAL_PICK_CYCLES
  Push/pull by 70 mm while soft gripping/opening.
  Final grip uses position 660.
  Pull the book out by 400 mm along tool Z.

MOVE_TO_PLACE_POSE
  Move to the home/place joint pose [0, 0, 90, 0, 90, 0].

LOWER_TO_PLACE_BOOK
  Lower along tool Z+ by 170 mm before opening the gripper.

RELEASE_BOOK
  Open the gripper and place the book at the home/place pose.

RETURN_HOME
  Return to [0, 0, 90, 0, 90, 0].
```

After the first mission completes, the runner waits:

```text
First book-pick mission completed. Press Enter to start marker2 place mission...
```

### Second Mission: Re-Grip And Marker2 Placement

```text
RUN_MARKER2_ALIGN
  Align to ArUco marker 2 in manual-step mode.
  Save the aligned TCP pose at marker2 target distance 0.50 m.

MOVEJ_BOX_HOME
  Move to [0, 0, 90, 0, 90, 0].

OPEN_GRIPPER_FOR_REGRIP
  Open the gripper to position 500.

DESCEND_TO_BOX_BOOK
  Move tool Z+ by 200 mm to re-grip the book placed by the first mission.

CLOSE_GRIPPER_ON_BOX_BOOK
  Close the gripper to position 660.

LIFT_FROM_BOX
  Move tool Z- by 200 mm.

MOVE_TO_SAVED_MARKER2_TCP_POSE
  Move directly to the saved marker2-aligned TCP pose.

PRE_INSERT_FROM_SAVED_Z_100
  Move tool Z+ by 100 mm.

DROP_FROM_SAVED_Y_150
  Move tool Y+ by 150 mm.

INSERT_REMAINING_FROM_SAVED_Z
  Move tool Z+ by the remaining 300 mm.

OPEN_GRIPPER_PLACE_BOOK
  Open the gripper to position 500 and place the book.

RETREAT_REMAINING_FROM_SAVED_Z
  Move tool Z- by 300 mm.

RAISE_FROM_SAVED_Y_150
  Move tool Y- by 150 mm.

RETREAT_PRE_INSERT_FROM_SAVED_Z_100
  Move tool Z- by 100 mm.

MOVEJ_BOX_HOME_RETURN
  Return to [0, 0, 90, 0, 90, 0].
```

To test only the second mission:

```bash
ros2 run doosan_realsense_handeye box_regrip_marker2_place_sequence \
  --ros-args \
  -p dry_run:=false \
  -p require_enter:=true
```

## Reference Only: Book Visual Servo Align

`book_visual_servo_align.py` is kept as a reference implementation for the
older pixel-based visual servo experiment. It is no longer the main demo route.

```bash
ros2 run doosan_realsense_handeye book_visual_servo_align \
  --execute \
  --auto-run \
  --target-lock-json realtime_results/target_book_lock.json
```

Manual stepping with the default temporary gripper-center desired pixel:

```bash
ros2 run doosan_realsense_handeye book_visual_servo_align \
  --target-lock-json realtime_results/target_book_lock.json
```

## Safety

- Default `dry_run:=true` means no robot motion is sent.
- Use `max_step_mm:=1.0` and `max_rot_step_deg:=1.0` for first real tests.
- Every movement requires pressing Enter.
- There is no automatic continuous movement loop.
- If the marker TF is missing, the nodes do not move.
- Keep the robot emergency stop ready.
- Validate translation signs and rotation sign on the actual wall marker.
- The marker pose can differ between floor testing and wall testing.

## URDF Notes

- `tool0` is recreated locally from the Doosan E0509 vendor URDF.
- Gripper and camera attach under `tool0`.
- RealSense frame names:
  - `camera_link`
  - `camera_color_frame`
  - `camera_color_optical_frame`
  - `camera_depth_frame`
  - `camera_depth_optical_frame`
- Temporary mount offsets are kept near the top of `urdf/e0509_gripper_camera.urdf.xacro`.
