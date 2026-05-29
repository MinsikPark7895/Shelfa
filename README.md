# Shelfa

## Vision Module

This branch includes a `vision/` module for real-time book-spine detection and OCR.

Main contents:
- `vision/realtime_yolo_paddle_ocr.py`: RealSense + YOLO-OBB + PaddleOCR live pipeline
- `vision/realtime_realsense_ocr.py`: RealSense-based OCR-related script
- `vision/crop_book_spines.py`: crop generation utility
- `vision/convert_seg_to_obb.py`: segmentation-to-OBB conversion utility
- `vision/test_paddle_ocr.py`: OCR test script
- `vision/data.yaml`: dataset config

See `vision/README.md` for setup and usage notes.
