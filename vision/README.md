# Vision Module

This folder contains Shelfa's book-spine vision pipeline. It focuses on RealSense capture, YOLO-OBB book-spine detection, PaddleOCR title extraction, depth/TF validation, and ArUco marker TF publishing.

## Main Files

- `realtime_yolo_paddle_ocr.py`: live RealSense + YOLO-OBB + PaddleOCR pipeline
- `book_scan_after_alignment.py`: scans books after an ArUco alignment payload is available
- `vision_pipeline_utils.py`: shared OBB/keypoint/depth helpers
- `aruco_realsense_tf_publisher.py`: publishes ArUco marker TF from RealSense color frames
- `weights/best.pt`: YOLO-OBB book-spine model

## Typical Runs

```bash
python3 vision/realtime_yolo_paddle_ocr.py
```

```bash
python3 vision/book_scan_after_alignment.py \
  --alignment-payload-json vision/realtime_results/alignment_payload.json \
  --target-title 제3인류
```

```bash
python3 vision/book_scan_after_alignment.py \
  --use-mock-alignment \
  --target-title 제3인류
```

For ROS 2 ArUco TF publishing, run the file inside an environment where `rclpy`, `tf2_ros`, OpenCV ArUco, and RealSense are available.

## Runtime Outputs

Do not commit runtime output folders or generated caches:

- `vision/realtime_results/`
- `realtime_results/`
- `paddle_ocr_output/`
- `easyocr_results/`
- `crop_results_130324/`
- `__pycache__/`
- ROS `build/`, `install/`, `log/` folders
