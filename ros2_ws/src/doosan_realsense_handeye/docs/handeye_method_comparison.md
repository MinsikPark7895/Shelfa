# Hand-Eye Method Comparison

Date: 2026-06-08

Input samples:

```text
/home/dakae/ros2_ws/src/doosan_realsense_handeye/data/samples/handeye_samples.yaml
```

Sample metadata:

- Sample count: 16
- Base frame: `base_link`
- Tool frame used during collection: `link_6`
- Camera frame: `camera_color_optical_frame`
- Board type: `charuco`
- Unit: meter

The calibration result YAML key remains `T_tool_camera` for package compatibility, but in this run
the actual transform meaning is:

```text
T_link_6_camera
```

No sample file was modified.

## Result Files

| Method | Result file |
| --- | --- |
| TSAI | `/home/dakae/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_link6_camera_TSAI.yaml` |
| PARK | `/home/dakae/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_link6_camera_PARK.yaml` |
| HORAUD | `/home/dakae/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_link6_camera_HORAUD.yaml` |
| ANDREFF | `/home/dakae/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_link6_camera_ANDREFF.yaml` |
| DANIILIDIS | `/home/dakae/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_link6_camera_DANIILIDIS.yaml` |

## Validation Summary

| Method | Translation RMSE (mm) | Max translation error (mm) | Std X/Y/Z (mm) | Mean rotation error (deg) | Max rotation error (deg) | T_link_6_camera translation (m) |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| TSAI | 16.270 | 24.000 | 9.940 / 11.597 / 5.604 | 8.678 | 14.351 | -0.017434, -0.050789, 0.081162 |
| PARK | 1.259 | 2.194 | 0.547 / 0.731 / 0.867 | 0.290 | 0.730 | -0.011538, -0.040646, 0.065390 |
| HORAUD | 1.248 | 2.081 | 0.562 / 0.688 / 0.877 | 0.288 | 0.727 | -0.011554, -0.040681, 0.065423 |
| ANDREFF | 1.165 | 1.943 | 0.466 / 0.613 / 0.874 | 0.289 | 0.725 | -0.011511, -0.040684, 0.065984 |
| DANIILIDIS | 1.306 | 2.163 | 0.627 / 0.736 / 0.878 | 0.290 | 0.725 | -0.011505, -0.040652, 0.065101 |

## Recommendation

Recommended method: `ANDREFF`

Reason:

- Lowest translation RMSE: `1.165 mm`
- Lowest max translation error: `1.943 mm`
- Rotation error is effectively tied with PARK, HORAUD, and DANIILIDIS.
- Translation is physically consistent with the other stable methods:
  approximately `x=-11.5 mm`, `y=-40.7 mm`, `z=66.0 mm` from `link_6` to the camera frame.

`TSAI` is not recommended for this sample set because its fixed-target validation error is much
larger: `16.270 mm` RMSE and `24.000 mm` max translation error.

## Commands Used

```bash
source /home/dakae/ros2_ws/install/setup.bash

for method in TSAI PARK HORAUD ANDREFF DANIILIDIS; do
  ros2 run doosan_realsense_handeye run_handeye_calibration \
    --samples /home/dakae/ros2_ws/src/doosan_realsense_handeye/data/samples/handeye_samples.yaml \
    --output /home/dakae/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_link6_camera_${method}.yaml \
    --method ${method}
done

for method in TSAI PARK HORAUD ANDREFF DANIILIDIS; do
  ros2 run doosan_realsense_handeye validate_handeye \
    --samples /home/dakae/ros2_ws/src/doosan_realsense_handeye/data/samples/handeye_samples.yaml \
    --calibration-result /home/dakae/ros2_ws/src/doosan_realsense_handeye/data/calibration_result/T_link6_camera_${method}.yaml
done
```
