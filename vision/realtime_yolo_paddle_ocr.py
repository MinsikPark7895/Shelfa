import cv2
import os
import json
import time
import numpy as np
import pyrealsense2 as rs
from pathlib import Path
from datetime import datetime

os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_pir_api", "0")

from ultralytics import YOLO
from paddleocr import PaddleOCR

MODEL_PATH = "./runs/obb/runs/obb/book_spine_v1/weights/best.pt"

OUTPUT_DIR = "./realtime_results"
CROP_DIR = os.path.join(OUTPUT_DIR, "crops")
TITLE_CROP_DIR = os.path.join(OUTPUT_DIR, "title_crops")
JSON_PATH = os.path.join(OUTPUT_DIR, "realtime_ocr_results.json")
FRAME_ID = "gripper_camera"
COORDINATE_TYPE = "camera_frame"
COORDINATE_UNIT = "meter"
OCR_TARGET_LONG_SIDE = 960
OCR_BENCHMARK_SIZES = [700, 960]

YOLO_CONF = 0.65
YOLO_IOU = 0.5
DISPLAY_CONF_THRESHOLD = 0.65
OCR_MIN_SCORE_THRESHOLD = 0.45
BOOK_SPINE_MIN_CONF = 0.50
BOOK_SPINE_MIN_SHORT_SIDE_PX = 8.0
BOOK_SPINE_MIN_LONG_SIDE_PX = 40.0
BOOK_SPINE_MIN_ASPECT_RATIO = 2.0
BOOK_SPINE_MAX_ASPECT_RATIO = 25.0


def is_korean(ch):
    return "가" <= ch <= "힣"


def clean_text(text):
    text = text.strip()
    text = text.replace("\n", " ")
    text = " ".join(text.split())

    remove_chars = ["|", "_", "~", "`", "·", "ㆍ", "•", "●", "■"]
    for ch in remove_chars:
        text = text.replace(ch, "")

    return text.strip()


def normalize_korean_title_text(text):
    if not text:
        return ""

    text = clean_text(text)
    chars = list(text)
    result = []

    for i, ch in enumerate(chars):
        if ch == " ":
            prev_ch = chars[i - 1] if i > 0 else ""
            next_ch = chars[i + 1] if i + 1 < len(chars) else ""

            if is_korean(prev_ch) and is_korean(next_ch):
                continue

        result.append(ch)

    text = "".join(result)
    text = " ".join(text.split())
    return text.strip()


def compute_obb_properties(points):
    rect = order_points(np.array(points, dtype=np.float32))
    tl, tr, br, bl = rect

    width = float((np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2.0)
    height = float((np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2.0)
    center = rect.mean(axis=0)

    if height >= width:
        long_vec = ((bl + br) / 2.0) - ((tl + tr) / 2.0)
        short_side = width
        long_side = height
    else:
        long_vec = ((tr + br) / 2.0) - ((tl + bl) / 2.0)
        short_side = height
        long_side = width

    angle_deg = float(np.degrees(np.arctan2(long_vec[0], long_vec[1])))

    return {
        "center_px": [
            round(float(center[0]), 1),
            round(float(center[1]), 1),
        ],
        "size_px": [
            round(float(short_side), 1),
            round(float(long_side), 1),
        ],
        "angle_deg": round(angle_deg, 1),
    }


def is_valid_book_spine(obb_info, conf):
    if conf < BOOK_SPINE_MIN_CONF:
        return False

    size_px = obb_info.get("size_px", [0.0, 0.0])
    if len(size_px) != 2:
        return False

    short_side = float(min(size_px))
    long_side = float(max(size_px))

    if short_side <= 0:
        return False

    if short_side < BOOK_SPINE_MIN_SHORT_SIDE_PX:
        return False

    if long_side < BOOK_SPINE_MIN_LONG_SIDE_PX:
        return False

    aspect_ratio = long_side / short_side

    if aspect_ratio < BOOK_SPINE_MIN_ASPECT_RATIO:
        return False

    if aspect_ratio > BOOK_SPINE_MAX_ASPECT_RATIO:
        return False

    return True


def get_depth_at_pixel(depth_frame, px, py):
    if depth_frame is None:
        return None

    h = depth_frame.get_height()
    w = depth_frame.get_width()
    x = int(round(px))
    y = int(round(py))

    offsets = [
        (0, 0), (-1, 0), (1, 0), (0, -1), (0, 1),
        (-2, 0), (2, 0), (0, -2), (0, 2)
    ]

    for dx, dy in offsets:
        xx = min(max(x + dx, 0), w - 1)
        yy = min(max(y + dy, 0), h - 1)
        depth_m = depth_frame.get_distance(xx, yy)
        if depth_m and depth_m > 0:
            return float(depth_m)

    return None


def deproject_pixel_to_camera_xyz(depth_frame, intrinsics, px, py):
    depth_m = get_depth_at_pixel(depth_frame, px, py)

    if depth_m is None or intrinsics is None:
        return [None, None, None]

    xyz = rs.rs2_deproject_pixel_to_point(
        intrinsics,
        [float(px), float(py)],
        float(depth_m)
    )

    return [round(float(v), 3) for v in xyz]


def is_valid_camera_xyz(camera_xyz_m):
    return (
        camera_xyz_m is not None
        and len(camera_xyz_m) == 3
        and all(v is not None for v in camera_xyz_m)
    )


def extract_depth_from_camera_xyz(camera_xyz_m):
    if is_valid_camera_xyz(camera_xyz_m):
        return camera_xyz_m[2]
    return None


def format_camera_xyz_text(camera_xyz_m):
    if not is_valid_camera_xyz(camera_xyz_m):
        return "invalid depth"
    return f"{camera_xyz_m[0]:.3f}, {camera_xyz_m[1]:.3f}, {camera_xyz_m[2]:.3f}m"


def make_book_payload(
    book_id,
    selected_title,
    selected_method,
    det_conf,
    ocr_score,
    obb_info,
    camera_xyz_m,
    depth_valid
):
    center_px = obb_info["center_px"]
    depth_m = extract_depth_from_camera_xyz(camera_xyz_m) if depth_valid else None

    return {
        "book_id": int(book_id),
        "title_candidate": selected_title,
        "selected_method": selected_method,
        "confidence": {
            "detection": round(float(det_conf), 3),
            "ocr": round(float(ocr_score), 3),
        },
        "coordinate_frame": {
            "frame_id": FRAME_ID,
            "coordinate_type": COORDINATE_TYPE,
            "unit": COORDINATE_UNIT
        },
        "obb": obb_info,
        "depth": {
            "valid": bool(depth_valid),
            "depth_m": depth_m
        },
        "target_point": {
            "type": "book_spine_center",
            "pixel": center_px,
            "camera_xyz_m": camera_xyz_m,
        }
    }


def match_title_from_db(ocr_text):
    """
    TODO: 실제 DB 검색 로직으로 교체 예정.
    """
    if not ocr_text:
        return {
            "status": "not_found",
            "matched_title": "",
            "candidates": []
        }

    return {
        "status": "not_found",
        "matched_title": "",
        "candidates": []
    }


def need_ocr_recheck(db_match_result):
    return db_match_result["status"] in ["not_found", "ambiguous"]


def run_timed_db_match(ocr_text):
    start_time = time.perf_counter()
    match_result = match_title_from_db(ocr_text)
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
    return match_result, round(elapsed_ms, 1)


def order_points(pts):
    rect = np.zeros((4, 2), dtype=np.float32)

    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)

    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]

    return rect


def normalize_spine_vertical(crop):
    h, w = crop.shape[:2]

    if w > h:
        crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)

    return crop


def crop_obb(image, points, padding=15):
    points = np.array(points, dtype=np.float32)
    rect = order_points(points)

    tl, tr, br, bl = rect

    width_top = np.linalg.norm(tr - tl)
    width_bottom = np.linalg.norm(br - bl)
    max_width = int(max(width_top, width_bottom))

    height_left = np.linalg.norm(bl - tl)
    height_right = np.linalg.norm(br - tr)
    max_height = int(max(height_left, height_right))

    if max_width < 5 or max_height < 5:
        return None

    dst = np.array([
        [0, 0],
        [max_width - 1, 0],
        [max_width - 1, max_height - 1],
        [0, max_height - 1]
    ], dtype=np.float32)

    M = cv2.getPerspectiveTransform(rect, dst)
    crop = cv2.warpPerspective(image, M, (max_width, max_height))

    crop = cv2.copyMakeBorder(
        crop,
        padding,
        padding,
        padding,
        padding,
        cv2.BORDER_REPLICATE
    )

    crop = normalize_spine_vertical(crop)

    return crop


def extract_main_title_region(crop):
    h, w = crop.shape[:2]

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    blur = cv2.GaussianBlur(gray, (3, 3), 0)

    binary = cv2.adaptiveThreshold(
        blur,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        7
    )

    kernel_h = max(7, h // 25)
    kernel_w = max(3, w // 12)

    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (kernel_w, kernel_h)
    )

    merged = cv2.dilate(binary, kernel, iterations=2)

    contours, _ = cv2.findContours(
        merged,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    candidates = []

    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        area = bw * bh

        if area < h * w * 0.01:
            continue

        if bw < 5 or bh < 10:
            continue

        cx = x + bw / 2

        area_score = area / max(h * w, 1)
        center_score = 1.0 - abs(cx - w / 2) / max(w / 2, 1)
        vertical_score = min(bh / max(h, 1), 1.0)

        score = area_score * 0.5 + center_score * 0.25 + vertical_score * 0.25

        candidates.append({
            "box": (x, y, bw, bh),
            "score": score,
            "area": area
        })

    if not candidates:
        return None, None

    candidates.sort(key=lambda c: c["score"], reverse=True)

    x, y, bw, bh = candidates[0]["box"]

    pad_x = max(5, int(bw * 0.20))
    pad_y = max(5, int(bh * 0.12))

    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(w, x + bw + pad_x)
    y2 = min(h, y + bh + pad_y)

    title_crop = crop[y1:y2, x1:x2]

    title_box = {
        "x1": int(x1),
        "y1": int(y1),
        "x2": int(x2),
        "y2": int(y2),
        "score": round(float(candidates[0]["score"]), 3)
    }

    return title_crop, title_box


def resize_for_ocr(image, target_long_side=OCR_TARGET_LONG_SIDE):
    h, w = image.shape[:2]
    long_side = max(h, w)

    if long_side >= target_long_side:
        return image

    scale = target_long_side / long_side
    new_w = int(w * scale)
    new_h = int(h * scale)

    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)


def make_debug_display_image(image, title, max_width=900, max_height=900):
    h, w = image.shape[:2]
    scale = min(max_width / max(w, 1), max_height / max(h, 1), 1.0)
    disp_w = max(1, int(w * scale))
    disp_h = max(1, int(h * scale))
    display = cv2.resize(image, (disp_w, disp_h), interpolation=cv2.INTER_AREA)

    banner_h = 60
    canvas = np.zeros((disp_h + banner_h, disp_w, 3), dtype=np.uint8)
    canvas[:banner_h] = (30, 30, 30)
    canvas[banner_h:] = display

    for idx, line in enumerate(title.split("\n")):
        cv2.putText(
            canvas,
            line,
            (10, 25 + idx * 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
            cv2.LINE_AA
        )

    return canvas


def show_ocr_debug_image(source_name, rotation_name, before_image, ocr_image):
    before_h, before_w = before_image.shape[:2]
    after_h, after_w = ocr_image.shape[:2]
    resized = "YES" if (before_h, before_w) != (after_h, after_w) else "NO"

    title = (
        f"source: {source_name} | rotation: {rotation_name}\n"
        f"before: {before_w}x{before_h} -> ocr: {after_w}x{after_h} | resized: {resized}"
    )

    debug_image = make_debug_display_image(ocr_image, title)
    cv2.imshow("OCR Input Debug", debug_image)
    cv2.waitKey(1)


def score_ocr_text(text, avg_conf, count):
    length_score = min(len(text) / 10, 1.0)
    group_score = min(count / 5, 1.0)

    return avg_conf * 0.55 + length_score * 0.30 + group_score * 0.15


def run_paddle_ocr_on_crop(
    ocr,
    crop,
    source_name="unknown",
    show_debug=False,
    target_long_side=None
):
    """
    속도 개선 버전:
    1차: 원본, 90도
    2차: 결과가 안 좋으면 270도, 180도 추가
    """
    rotations_primary = [
        ("vertical_original", crop),
        ("rot90", cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)),
    ]

    rotations_fallback = [
        ("rot270", cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)),
        ("rot180", cv2.rotate(crop, cv2.ROTATE_180)),
    ]

    raw_by_rotation = {}

    def run_rotations(rotations):
        candidates = []

        for rot_name, img in rotations:
            before_img = img.copy()
            if target_long_side is not None:
                img = resize_for_ocr(img, target_long_side=target_long_side)

            if show_debug:
                show_ocr_debug_image(source_name, rot_name, before_img, img)

            results = ocr.predict(img)

            texts = []
            scores = []

            for res in results:
                rec_texts = res.get("rec_texts", [])
                rec_scores = res.get("rec_scores", [])

                for text, score in zip(rec_texts, rec_scores):
                    text = normalize_korean_title_text(text)

                    if not text:
                        continue

                    texts.append(text)
                    scores.append(float(score))

            raw_by_rotation[rot_name] = [
                {
                    "text": t,
                    "confidence": round(s, 3)
                }
                for t, s in zip(texts, scores)
            ]

            if not texts:
                continue

            joined_text = normalize_korean_title_text(" ".join(texts))
            avg_conf = sum(scores) / len(scores)

            score = score_ocr_text(
                text=joined_text,
                avg_conf=avg_conf,
                count=len(texts)
            )

            candidates.append({
                "text": joined_text,
                "confidence": avg_conf,
                "count": len(texts),
                "rotation": rot_name,
                "type": "paddle_group",
                "score": score
            })

        return candidates

    candidates = run_rotations(rotations_primary)
    candidates.sort(key=lambda x: x["score"], reverse=True)

    if candidates:
        best = candidates[0]
        if len(best["text"]) >= 2 and best["score"] >= 0.45:
            best["raw_by_rotation"] = raw_by_rotation
            return best

    fallback_candidates = run_rotations(rotations_fallback)
    candidates.extend(fallback_candidates)

    if not candidates:
        return {
            "text": "",
            "confidence": 0.0,
            "rotation": "none",
            "type": "none",
            "score": 0.0,
            "raw_by_rotation": raw_by_rotation
        }

    candidates.sort(key=lambda x: x["score"], reverse=True)
    best = candidates[0]
    best["raw_by_rotation"] = raw_by_rotation

    return best


def run_timed_ocr(ocr, crop, source_name="unknown", show_debug=False, target_long_side=None):
    start_time = time.perf_counter()
    ocr_result = run_paddle_ocr_on_crop(
        ocr,
        crop,
        source_name=source_name,
        show_debug=show_debug,
        target_long_side=target_long_side
    )
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
    return ocr_result, round(elapsed_ms, 1)


def benchmark_ocr_sizes(ocr, crop, source_name, show_debug, target_sizes):
    benchmark_results = []

    for target_size in target_sizes:
        start_time = time.perf_counter()
        ocr_result = run_paddle_ocr_on_crop(
            ocr,
            crop,
            source_name=source_name,
            show_debug=show_debug,
            target_long_side=target_size
        )
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        benchmark_results.append({
            "target_long_side": int(target_size),
            "text": normalize_korean_title_text(ocr_result["text"]),
            "score": round(float(ocr_result["score"]), 3),
            "confidence": round(float(ocr_result["confidence"]), 3),
            "rotation": ocr_result["rotation"],
            "type": ocr_result["type"],
            "elapsed_ms": round(elapsed_ms, 1),
            "result": ocr_result
        })

    return benchmark_results


def save_json(results, trigger_info=None, show_log=False):
    data = {
        "timestamp": datetime.now().isoformat(),
        "frame_id": FRAME_ID,
        "coordinate_type": COORDINATE_TYPE,
        "coordinate_unit": COORDINATE_UNIT,
        "source": "realsense_live_yolo_obb_paddleocr",
        "total_books": len(results),
        "books": [item["vision_position"] for item in results],
        "results": results
    }

    if trigger_info is not None:
        data["trigger"] = trigger_info

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if show_log:
        print("[Saved JSON]")
        print(json.dumps(data, ensure_ascii=False, indent=2))


def init_realsense(width=1280, height=720, fps=30):
    """
    RealSense color + depth 카메라 초기화
    """
    pipeline = rs.pipeline()
    config = rs.config()

    config.enable_stream(
        rs.stream.color,
        width,
        height,
        rs.format.bgr8,
        fps
    )
    config.enable_stream(
        rs.stream.depth,
        width,
        height,
        rs.format.z16,
        fps
    )

    profile = pipeline.start(config)
    align = rs.align(rs.stream.color)
    color_profile = profile.get_stream(rs.stream.color).as_video_stream_profile()
    color_intrinsics = color_profile.get_intrinsics()

    print(f"RealSense color+depth stream 시작: {width}x{height} @ {fps}fps")

    return pipeline, align, color_intrinsics


def get_realsense_frames(pipeline, align):
    """
    RealSense color/depth frame을 정렬해서 반환
    """
    frames = pipeline.wait_for_frames()
    aligned_frames = align.process(frames)
    color_frame = aligned_frames.get_color_frame()
    depth_frame = aligned_frames.get_depth_frame()

    if not color_frame or not depth_frame:
        return None, None, None

    color_image = np.asanyarray(color_frame.get_data())

    return color_image, depth_frame, color_frame


def check_ocr_trigger(key=None):
    """
    현재는 s 키가 눌렸을 때 OCR 실행 요청으로 처리합니다.
    """
    return key == ord("s")


def on_ocr_trigger_signal():
    """
    TODO:
    로봇팔이 원하는 위치로 이동한 뒤,
    ROS2 topic/service로 OCR 실행 신호를 보내면
    이 함수가 trigger flag를 True로 바꾸는 구조로 확장 예정.
    """
    pass


def run_ocr_once(
    frame,
    depth_frame,
    color_intrinsics,
    obb_data,
    ocr,
    timestamp
):
    """
    현재 프레임과 현재 감지된 OBB 결과를 기준으로 OCR을 한 번만 수행합니다.
    """
    results = []

    print("\n" + "=" * 70)
    print("[Trigger] OCR requested by manual key s")
    print(f"OCR 실행: {timestamp}")
    print(f"감지된 책등 수: {len(obb_data)}")

    for book in obb_data:
        i = book["index"]
        points = book["points"]
        det_conf = book["confidence"]
        obb_info = book["obb_info"]
        camera_xyz_m = book.get("camera_xyz_m")
        depth_valid = book.get("depth_valid", is_valid_camera_xyz(camera_xyz_m))

        crop = crop_obb(frame, points, padding=15)

        if crop is None:
            print(f"[{i}] crop 실패")
            continue

        crop_path = os.path.join(
            CROP_DIR,
            f"{timestamp}_book_{i:02d}_conf_{det_conf:.2f}.jpg"
        )
        cv2.imwrite(crop_path, crop)

        title_crop, title_box = extract_main_title_region(crop)
        title_crop_path = None
        title_ocr_result = None

        if title_crop is not None and title_crop.size > 0:
            title_crop_path = os.path.join(
                TITLE_CROP_DIR,
                f"{timestamp}_book_{i:02d}_title_crop.jpg"
            )
            cv2.imwrite(title_crop_path, title_crop)
            ocr_input = title_crop
            ocr_source = "title_crop"

            ocr_result_original, elapsed_original_ms = run_timed_ocr(
                ocr,
                ocr_input,
                source_name=ocr_source,
                show_debug=False,
                target_long_side=None
            )
            original_text = normalize_korean_title_text(ocr_result_original["text"])
            recheck_used = False
            recheck_reason = "no_text_detected"
            ocr_result_960 = None
            elapsed_960_ms = 0.0
            db_match_960 = None
            db_elapsed_960_ms = 0.0
            db_match_original = {
                "status": "not_found",
                "matched_title": "",
                "candidates": []
            }
            db_elapsed_original_ms = 0.0

            if not original_text:
                print(
                    f"[{i}] 1차 OCR(original): "
                    f"\"\" score={ocr_result_original['score']:.2f} "
                    f"| ocr={elapsed_original_ms:.1f}ms"
                )
                print(f"[{i}] 원본 OCR 무검출 -> 960 재확인 없이 후보 제외")

                title_ocr_result = ocr_result_original
                selected_title = ""
                selected_score = 0.0
                selected_method = "ocr_not_detected_original"
            else:
                db_match_original, db_elapsed_original_ms = run_timed_db_match(original_text)

                print(
                    f"[{i}] 1차 OCR(original): "
                    f"\"{original_text}\" score={ocr_result_original['score']:.2f} "
                    f"db={db_match_original['status']} "
                    f"| ocr={elapsed_original_ms:.1f}ms db={db_elapsed_original_ms:.1f}ms"
                )

                recheck_reason = db_match_original["status"]

                if need_ocr_recheck(db_match_original):
                    recheck_used = True
                    print(f"[{i}] DB 매칭 불확실 -> 960 OCR 재확인")
                    ocr_result_960, elapsed_960_ms = run_timed_ocr(
                        ocr,
                        ocr_input,
                        source_name=ocr_source,
                        show_debug=False,
                        target_long_side=OCR_TARGET_LONG_SIDE
                    )
                    recheck_text = normalize_korean_title_text(ocr_result_960["text"])
                    db_match_960, db_elapsed_960_ms = run_timed_db_match(recheck_text)

                    print(
                        f"[{i}] 2차 OCR(960): "
                        f"\"{recheck_text}\" score={ocr_result_960['score']:.2f} "
                        f"db={db_match_960['status']} "
                        f"| ocr={elapsed_960_ms:.1f}ms db={db_elapsed_960_ms:.1f}ms"
                    )

                if db_match_original["status"] == "matched":
                    title_ocr_result = ocr_result_original
                    selected_title = normalize_korean_title_text(
                        db_match_original["matched_title"] or original_text
                    )
                    selected_score = float(title_ocr_result["score"])
                    selected_method = "db_matched_original_ocr"
                elif db_match_960 and db_match_960["status"] == "matched":
                    title_ocr_result = ocr_result_960
                    selected_title = normalize_korean_title_text(
                        db_match_960["matched_title"] or normalize_korean_title_text(ocr_result_960["text"])
                    )
                    selected_score = float(title_ocr_result["score"])
                    selected_method = "db_matched_recheck_960"
                else:
                    original_score = float(ocr_result_original["score"])
                    recheck_score = float(ocr_result_960["score"]) if ocr_result_960 else -1.0

                    if ocr_result_960 and recheck_score > original_score:
                        title_ocr_result = ocr_result_960
                        selected_title = normalize_korean_title_text(title_ocr_result["text"])
                        selected_score = recheck_score
                        selected_method = "ocr_candidate_recheck_960"
                    else:
                        title_ocr_result = ocr_result_original
                        selected_title = original_text
                        selected_score = original_score
                        selected_method = "ocr_candidate_original"

            selected_rotation = title_ocr_result["rotation"]
            selected_confidence = float(title_ocr_result["confidence"])
            raw_by_rotation = title_ocr_result["raw_by_rotation"]
            ocr_recheck = {
                "used": recheck_used,
                "reason": recheck_reason,
                "original": {
                    "text": original_text,
                    "resize": "original",
                    "elapsed_ms": elapsed_original_ms,
                    "db_elapsed_ms": db_elapsed_original_ms,
                    "score": round(float(ocr_result_original["score"]), 3),
                    "rotation": ocr_result_original["rotation"]
                },
                "recheck_960": {
                    "text": normalize_korean_title_text(ocr_result_960["text"]) if ocr_result_960 else "",
                    "resize": OCR_TARGET_LONG_SIDE if ocr_result_960 else None,
                    "elapsed_ms": elapsed_960_ms if ocr_result_960 else 0.0,
                    "db_elapsed_ms": db_elapsed_960_ms if ocr_result_960 else 0.0,
                    "score": round(float(ocr_result_960["score"]), 3) if ocr_result_960 else 0.0,
                    "rotation": ocr_result_960["rotation"] if ocr_result_960 else "none"
                }
            }
        else:
            ocr_source = "full_crop"
            selected_title = ""
            selected_score = 0.0
            selected_method = "title_crop_failed"
            selected_rotation = "none"
            selected_confidence = 0.0
            raw_by_rotation = {}
            ocr_recheck = {
                "used": False,
                "reason": "not_found",
                "original": {
                    "text": "",
                    "resize": "original",
                    "elapsed_ms": 0.0,
                    "db_elapsed_ms": 0.0,
                    "score": 0.0,
                    "rotation": "none"
                },
                "recheck_960": {
                    "text": "",
                    "resize": None,
                    "elapsed_ms": 0.0,
                    "db_elapsed_ms": 0.0,
                    "score": 0.0,
                    "rotation": "none"
                }
            }

        if not is_valid_camera_xyz(camera_xyz_m):
            center_px = obb_info["center_px"]
            camera_xyz_m = deproject_pixel_to_camera_xyz(
                depth_frame,
                color_intrinsics,
                center_px[0],
                center_px[1]
            )
            depth_valid = is_valid_camera_xyz(camera_xyz_m)

        xyz_text = format_camera_xyz_text(camera_xyz_m)

        one_line = (
            f"{i}번 책 | "
            f"제목후보: {selected_title if selected_title else '인식 실패'} | "
            f"감지신뢰도: {det_conf:.2f} | "
            f"OCR점수: {selected_score:.2f} | "
            f"xyz(camera): {xyz_text if depth_valid else 'invalid depth'} | "
            f"방식: {selected_method}"
        )

        if not selected_title or float(selected_score) < OCR_MIN_SCORE_THRESHOLD:
            print(
                f"[{i}] 제외됨 | "
                f"제목후보: {selected_title if selected_title else '없음'} | "
                f"OCR점수: {selected_score:.2f} < {OCR_MIN_SCORE_THRESHOLD:.2f}"
            )
            print(f"    crop: {crop_path}")
            print(f"    title_crop: {title_crop_path}")
            continue

        result_item = {
            "timestamp": timestamp,
            "index": i,
            "one_line": one_line,
            "selected_title": selected_title,
            "selected_method": selected_method,
            "det_confidence": round(det_conf, 3),
            "ocr_score": round(float(selected_score), 3),
            "ocr_confidence": round(float(selected_confidence), 3),
            "ocr_rotation": selected_rotation,
            "ocr_source": ocr_source,
            "crop_file": crop_path,
            "title_crop_file": title_crop_path,
            "title_box": title_box,
            "raw_by_rotation": raw_by_rotation,
            "ocr_recheck": ocr_recheck,
            "trigger": {
                "type": "manual_key_s",
                "timestamp": timestamp,
                "mode": "single_shot_ocr"
            },
            "vision_position": make_book_payload(
                book_id=i,
                selected_title=selected_title,
                selected_method=selected_method,
                det_conf=det_conf,
                ocr_score=selected_score,
                obb_info=obb_info,
                camera_xyz_m=camera_xyz_m,
                depth_valid=depth_valid
            )
        }

        results.append(result_item)

        print(one_line)
        print(f"    target_point(camera_xyz_m): {camera_xyz_m if depth_valid else 'invalid depth'}")
        print(f"    crop: {crop_path}")
        print(f"    title_crop: {title_crop_path}")

    print("=" * 70)
    return results


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(CROP_DIR, exist_ok=True)
    os.makedirs(TITLE_CROP_DIR, exist_ok=True)

    print("YOLO OBB 모델 로드 중...")
    yolo_model = YOLO(MODEL_PATH)

    print("PaddleOCR 초기화 중...")
    ocr = PaddleOCR(
        lang="korean",
        use_textline_orientation=True,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        enable_mkldnn=False
    )
    print("PaddleOCR 준비 완료")

    pipeline, align, color_intrinsics = init_realsense(width=1280, height=720, fps=30)

    print("\nRealSense 실시간 실행 시작")
    print("s 키: 현재 화면 OCR 실행")
    print("q 키: 종료")

    latest_obb_data = []
    latest_frame = None
    latest_depth_frame = None
    saved_results = []
    frame_count = 0
    ocr_busy = False

    try:
        while True:
            frame, depth_frame, _ = get_realsense_frames(pipeline, align)

            if frame is None:
                print("RealSense frame을 읽을 수 없습니다.")
                continue

            latest_frame = frame.copy()
            latest_depth_frame = depth_frame
            frame_count += 1

            start = time.time()

            yolo_results = yolo_model.predict(
                frame,
                conf=YOLO_CONF,
                iou=YOLO_IOU,
                verbose=False
            )

            vis = frame.copy()
            latest_obb_data = []

            if yolo_results[0].obb is not None:
                for i, obb in enumerate(yolo_results[0].obb):
                    points = obb.xyxyxyxy[0].cpu().numpy()
                    conf = float(obb.conf[0].cpu().numpy())

                    if conf < DISPLAY_CONF_THRESHOLD:
                        continue

                    obb_info = compute_obb_properties(points)
                    if not is_valid_book_spine(obb_info, conf):
                        continue

                    center_px = obb_info["center_px"]
                    camera_xyz_m = deproject_pixel_to_camera_xyz(
                        latest_depth_frame,
                        color_intrinsics,
                        center_px[0],
                        center_px[1]
                    )
                    depth_valid = is_valid_camera_xyz(camera_xyz_m)
                    latest_obb_data.append({
                        "index": i,
                        "points": points,
                        "confidence": conf,
                        "obb_info": obb_info,
                        "camera_xyz_m": camera_xyz_m,
                        "depth_valid": depth_valid
                    })

                    pts_int = points.astype(np.int32)
                    cv2.drawContours(vis, [pts_int], 0, (0, 255, 0), 2)

                    cx = int(points[:, 0].mean())
                    cy = int(points[:, 1].mean())

                    cv2.putText(
                        vis,
                        f"#{i} {conf:.2f}",
                        (cx, cy),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 255, 255),
                        2
                    )
                    xyz_display = (
                        f"xyz: {format_camera_xyz_text(camera_xyz_m)}"
                        if depth_valid else "xyz: invalid depth"
                    )
                    cv2.putText(
                        vis,
                        xyz_display,
                        (cx, cy + 18),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.45,
                        (255, 255, 0),
                        1
                    )

            elapsed = time.time() - start
            fps = 1.0 / elapsed if elapsed > 0 else 0.0

            cv2.putText(
                vis,
                (
                    f"RealSense YOLO FPS: {fps:.1f} | "
                    f"books: {len(latest_obb_data)} | "
                    f"shown>={DISPLAY_CONF_THRESHOLD:.2f} | s: OCR | q: quit"
                ),
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2
            )

            cv2.imshow("RealSense YOLO OBB + PaddleOCR", vis)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break

            if check_ocr_trigger(key) and not ocr_busy:
                if latest_frame is None or not latest_obb_data:
                    print("OCR할 책등이 없습니다.")
                    continue

                ocr_busy = True
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                try:
                    results = run_ocr_once(
                        frame=latest_frame.copy(),
                        depth_frame=latest_depth_frame,
                        color_intrinsics=color_intrinsics,
                        obb_data=latest_obb_data,
                        ocr=ocr,
                        timestamp=timestamp
                    )
                    saved_results.extend(results)
                    save_json(
                        saved_results,
                        trigger_info={
                            "type": "manual_key_s",
                            "timestamp": timestamp,
                            "mode": "single_shot_ocr"
                        },
                        show_log=True
                    )
                    print(f"JSON 저장: {JSON_PATH}")
                finally:
                    ocr_busy = False

    finally:
        pipeline.stop()
        cv2.destroyAllWindows()

        save_json(saved_results)
        print("종료 완료")
        print(f"최종 JSON: {JSON_PATH}")


if __name__ == "__main__":
    main()
