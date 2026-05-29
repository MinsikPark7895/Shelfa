# Vision Module

## Overview

This folder contains the vision pipeline for book-spine detection and OCR.

Current pipeline:
1. RealSense color/depth stream
2. YOLO-OBB book-spine detection
3. 3D point extraction in `gripper_camera` / `camera_frame`
4. OCR on key trigger (`s`)
5. Result export to JSON

## Main File

- `realtime_yolo_paddle_ocr.py`
- `weights/best.pt`

This script:
- runs real-time YOLO-OBB detection
- displays per-book `camera_xyz_m`
- runs OCR only when `s` is pressed
- stores crop, title crop, and JSON results
- filters weak OCR results and invalid spine-like detections

## Notes

- Coordinate frame: `gripper_camera`
- Coordinate type: `camera_frame`
- Unit: `meter`
- OCR recheck uses `960` resize only when the original OCR text exists but DB matching is uncertain
- If original OCR detects no text, the candidate is rejected without 960 recheck

## Excluded Outputs

The following runtime outputs should not be committed:
- `realtime_results/`
- `paddle_ocr_output/`
- `easyocr_results/`
- `crop_results_130324/`
- validation/prediction output folders under `runs/`

## Typical Run

```bash
python3 vision/realtime_yolo_paddle_ocr.py
```

If needed, update the model path inside the script to point to:

```text
vision/weights/best.pt
```
