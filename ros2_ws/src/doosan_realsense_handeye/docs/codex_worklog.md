# doosan_realsense_handeye Codex Worklog

## 2026-06-12 - Book Mission State Machine

### Request

Build a single mission state machine for the full flow:
home -> marker alignment -> book detection -> book offset move -> pick -> place -> home.

### Changes

- Added `book_mission_state_machine.py` as a top-level orchestrator.
- Reused the existing ArUco alignment subprocess, book scan helpers, and pick sequence executor
  instead of reimplementing the lower-level robot/service logic.
- Added `config/book_mission_state_machine.yaml` and
  `launch/book_mission_state_machine.launch.py`.
- Added mission trace/result JSON outputs for step-by-step debugging.

### Safety Notes

- Mission defaults remain dry-run oriented.
- The state machine does not own the RealSense device; it subscribes to the external ROS camera
  topics already used by the book scan flow.

## 2026-06-12 - Subscriber-based RealSense Book Scan

### Request

Switch the Doosan book-scan flow from direct RealSense device ownership to subscriber-based
camera input, with the external `realsense2_camera` node publishing image topics first.

### Changes

- Reworked `realtime_yolo_paddle_ocr.py` to read `color/image_raw`, `color/camera_info`, and
  aligned depth images from ROS topics instead of opening `pyrealsense2` directly.
- Kept the legacy helper API shape so older book-vision scripts can still call the shared entry
  points without owning the camera device.
- Updated `book_scan_after_alignment.py` to wait on subscribed frames after the alignment pose is
  reached.
- Updated `README.md` to document the external RealSense launch requirement and the expected image
  topics.

### Safety Notes

- No robot motion command was executed.
- No gripper command was executed.
- The change is limited to the `doosan_realsense_handeye` package.

## 2026-06-08 - Doosan RealSense Hand-Eye Calibration Package

### Request

Create a measurement-only ROS 2 package for Doosan E0509 + RealSense D455f eye-in-hand calibration:
manual robot pose changes, explicit sample saving, ChArUco/ArUco detection, OpenCV hand-eye
calibration, YAML result export, camera-point to base transform testing, and calibration quality
validation.

### Changes

- Added `src/doosan_realsense_handeye`.
- Added configurable defaults for the checked workspace frames:
  - `base_link`
  - `tool0`, later corrected to `link_6` for this setup.
  - `camera_color_optical_frame`
- Added ChArUco-first and single ArUco marker pose estimation with OpenCV aruco API compatibility helpers.
- Added explicit sample collection through keyboard `s` and `std_srvs/Trigger` service only.
- Added OpenCV `cv2.calibrateHandEye` runner with `TSAI`, `PARK`, `HORAUD`, `ANDREFF`, and `DANIILIDIS`.
- Added `T_tool_camera.yaml` export in meters.
- Added `object_to_base_transformer` for `P_base = T_base_tool @ T_tool_camera @ P_camera`.
- Added `validate_handeye` to compute fixed target mean, standard deviation, max error, RMSE, and rotation spread.
- Added launch wrappers and a package README with the requested nine-step RealSense/Doosan/TF/sample/calibrate/validate/transform flow.

### Commands Run

- `python3 -m py_compile src/doosan_realsense_handeye/doosan_realsense_handeye/*.py`
- `colcon build --symlink-install --packages-select doosan_realsense_handeye`
- `source install/setup.bash && ros2 run doosan_realsense_handeye run_handeye_calibration --help`
- `source install/setup.bash && ros2 run doosan_realsense_handeye validate_handeye --help`
- `source install/setup.bash && ros2 run doosan_realsense_handeye object_to_base_transformer --help`
- `ROS_LOG_DIR=/tmp/ros_logs source install/setup.bash && ros2 launch doosan_realsense_handeye handeye_sample_collector.launch.py --show-args`
- `ROS_LOG_DIR=/tmp/ros_logs source install/setup.bash && ros2 launch doosan_realsense_handeye validate_handeye.launch.py --show-args`

### Test Result

- Passed: Python syntax check for the new package modules.
- Passed: `colcon build --symlink-install --packages-select doosan_realsense_handeye`.
- Passed: CLI help for calibration, validation, and point transform executables.
- Passed: launch argument loading for sample collection and validation with `ROS_LOG_DIR=/tmp/ros_logs`.

### Safety Notes

- No robot motion command was implemented or run.
- No Doosan motion/jog/servo/MoveJ/MoveL interface was called.
- No gripper command or forwarding path was implemented or run.
- Live RealSense/TF/image validation still needs to be run by the user with the physical setup active.

## 2026-06-08 - Hand-Eye Method Comparison

### Request

Compare all OpenCV hand-eye calibration methods using the completed sample file:

```text
/home/dakae/ros2_ws/src/doosan_realsense_handeye/data/samples/handeye_samples.yaml
```

The samples were collected with `base_frame=base_link` and `tool_frame=link_6`, so the result file
key `T_tool_camera` should be interpreted as `T_link_6_camera` for this setup.

### Changes

- Generated method-specific calibration YAML files:
  - `data/calibration_result/T_link6_camera_TSAI.yaml`
  - `data/calibration_result/T_link6_camera_PARK.yaml`
  - `data/calibration_result/T_link6_camera_HORAUD.yaml`
  - `data/calibration_result/T_link6_camera_ANDREFF.yaml`
  - `data/calibration_result/T_link6_camera_DANIILIDIS.yaml`
- Added comparison report:
  - `docs/handeye_method_comparison.md`
- Recommended `ANDREFF` based on lowest translation RMSE and max translation error.

### Test Result

- Sample count: 16
- Best method: `ANDREFF`
- `ANDREFF` translation RMSE: `1.165 mm`
- `ANDREFF` max translation error: `1.943 mm`
- `ANDREFF` translation: `x=-0.011511, y=-0.040684, z=0.065984 m`

### Safety Notes

- Existing sample YAML was not modified.
- No robot motion command was implemented or run.
- No Doosan motion/jog/servo/MoveJ/MoveL interface was called.
- No gripper command or forwarding path was implemented or run.

## 2026-06-08 - Live Target To Base Check Node

### Request

Add a read-only live target pose node for the completed calibration. The final result file is
`T_tool_camera.yaml`, but for this collection it means `T_link_6_camera` because samples used
`base_link -> link_6`.

### Changes

- Added `doosan_realsense_handeye.live_target_to_base`.
- Added `live_target_to_base` console entry point.
- Added `launch/live_target_to_base.launch.py`.
- Added `live_target_to_base` defaults to `config/handeye_config.yaml`.
- Reused `BoardPoseDetector` for live ChArUco/ArUco pose detection.
- Computes:
  - `T_base_target = T_base_link_6 @ T_link_6_camera @ T_camera_target`
- Prints target translation, RPY, quaternion, and detection count in the base frame.
- Updated `README.md` with fixed-board live check instructions.

### Commands Run

- `python3 -m py_compile src/doosan_realsense_handeye/doosan_realsense_handeye/*.py`
- `colcon build --symlink-install --packages-select doosan_realsense_handeye`
- `ROS_LOG_DIR=/tmp/ros_logs ros2 launch doosan_realsense_handeye live_target_to_base.launch.py --show-args`
- `ros2 pkg executables doosan_realsense_handeye`
- Short smoke start with `ROS_LOG_DIR=/tmp/ros_logs` and `timeout 3`.

### Test Result

- Passed: Python syntax check.
- Passed: package build.
- Passed: new executable appears in `ros2 pkg executables`.
- Passed: launch file argument loading after rebuild.
- Smoke start reached node initialization and loaded `T_tool_camera.yaml` as `T_link_6_camera`.
- DDS socket creation was blocked by the Codex sandbox, so live image/TF validation must be run on the
  user's active ROS 2 setup.

### Safety Notes

- No robot motion command was implemented or run.
- No Doosan motion/jog/servo/MoveJ/MoveL interface was called.
- No gripper command or forwarding path was implemented or run.

## 2026-06-08 - Target Approach Pose And TF Publishing

### Request

Extend `live_target_to_base` for a wall-mounted ArUco marker:

- Marker id: `6`
- Dictionary: `DICT_4X4_50`
- Marker length: `0.038 m`
- Compute a target-relative approach pose.
- Publish TF frames for RViz.

### Changes

- Added approach offset parameters:
  - `approach_offset_x`
  - `approach_offset_y`
  - `approach_offset_z`
- Default approach offset is `0.30 m` along target Z, configurable by changing the sign of
  `approach_offset_z`.
- Added:
  - `T_base_approach = T_base_target @ T_target_approach`
- Updated logs to print both target and approach xyz/rpy plus marker detection info.
- Added TF broadcasting:
  - `base_link -> detected_target`
  - `base_link -> target_approach`
- Updated `config/handeye_config.yaml` live defaults to `board_type: aruco`, marker id `6`,
  marker length `0.038`, and dictionary `DICT_4X4_50`.
- Updated `README.md` with live approach-pose usage and sign-flip guidance.

### Safety Notes

- No robot motion command was implemented or run.
- No Doosan motion/jog/servo/MoveJ/MoveL interface was called.
- No gripper command or forwarding path was implemented or run.

## 2026-06-08 - One-Shot Move To Approach Dry-Run Node

### Request

Add a guarded Doosan E0509 motion test node that moves only to `target_approach`, not to
`detected_target`, and defaults to no real movement.

### Changes

- Added `doosan_realsense_handeye.move_to_approach`.
- Added `move_to_approach` console entry point.
- Added `launch/move_to_approach.launch.py`.
- Added `move_to_approach` defaults to `config/handeye_config.yaml`.
- Added `dsr_msgs2` package dependency.
- Updated live default `approach_offset_z` to `0.30 m` for a farther first-test approach pose.
- The node looks up:
  - `base_link -> target_approach`
  - `base_link -> link_6`
- It uses `target_approach` XYZ.
- It does not use TF RPY as Doosan `rx, ry, rz`.
- It reads the current Doosan task pose from `/dsr01/aux_control/get_current_posx` and reuses the
  controller's current `rx, ry, rz` values unchanged.
- It converts only target XYZ from meter to millimeter.
- It creates an absolute base-frame `MoveLine` request:
  - `ref=0`
  - `mode=0`
  - `sync_type=0`
- It refuses motion when TF is missing, values are non-finite, or distance exceeds `max_step_m`.
- It sends at most one service request only when `execute=true`.

### Safety Notes

- Default `execute=false` skips the service call and prints the generated pose only.
- No service call was made during implementation.
- The node contains no automatic loop, tracking, servo, MoveJ, or repeated MoveLine behavior.
- If the current Doosan task pose cannot be read, the node refuses movement even when
  `execute=true`.

## 2026-06-08 - TCP Z Axis Marker Alignment Preview

### Request

Add a preview-only node that aligns the TCP Z axis with a detected marker Z axis before connecting
the pose to any real motion.

### Changes

- Added `doosan_realsense_handeye.align_to_marker_preview`.
- Added `align_to_marker_preview` console entry point.
- Added `launch/align_to_marker_preview.launch.py`.
- Added `align_to_marker_preview` defaults to `config/handeye_config.yaml`.
- The node looks up:
  - `base_link -> detected_target`
  - `base_link -> target_approach`
  - `base_link -> link_6`
- It publishes:
  - `base_link -> aligned_tcp_goal`
- It uses `target_approach` translation for the goal position.
- It uses marker Z as the alignment source:
  - default `axis_direction=opposite`: `z_tcp_goal = -z_marker_base`
  - optional `axis_direction=same`: `z_tcp_goal = z_marker_base`
- It projects the current TCP X axis onto the plane perpendicular to `z_tcp_goal` to preserve wrist
  roll as much as possible, then rebuilds a right-handed rotation matrix.

### Safety Notes

- This node publishes TF only.
- It contains no Doosan motion, servo, MoveJ, MoveLine, or gripper service clients.
- No robot command was executed during implementation.
