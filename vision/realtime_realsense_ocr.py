import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_pir_api", "0")

try:
    import pyrealsense2 as rs
except ImportError as exc:
    print("pyrealsense2를 찾을 수 없습니다.")
    print("RealSense 실시간 모드를 사용하려면 pyrealsense2를 설치하세요.")
    print("예: python -m pip install pyrealsense2")
    raise SystemExit(1) from exc

from ultralytics import YOLO
from paddleocr import PaddleOCR


FRAME_ID = "gripper_camera"
COORDINATE_TYPE = "camera_frame"
OCR_RECHECK_LONG_SIDE = 960


def parse_args():
    parser = argparse.ArgumentParser(description="RealSense Book Spine OCR Pipeline")
    parser.add_argument("--source", default="realsense", choices=["realsense", "image"])
    parser.add_argument("--image_path", default="")
    parser.add_argument(
        "--model",
        default="./runs/obb/runs/obb/book_spine_v1/weights/best.pt"
    )
    parser.add_argument("--output_dir", default="./realtime_results")
    parser.add_argument("--conf", type=float, default=0.4)
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument("--display_conf", type=float, default=0.4)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    return parser.parse_args()


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

    return " ".join("".join(result).split()).strip()


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

    dst = np.array(
        [
            [0, 0],
            [max_width - 1, 0],
            [max_width - 1, max_height - 1],
            [0, max_height - 1],
        ],
        dtype=np.float32,
    )

    matrix = cv2.getPerspectiveTransform(rect, dst)
    crop = cv2.warpPerspective(image, matrix, (max_width, max_height))
    crop = cv2.copyMakeBorder(
        crop,
        padding,
        padding,
        padding,
        padding,
        cv2.BORDER_REPLICATE,
    )
    return normalize_spine_vertical(crop)


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
        7,
    )

    kernel_h = max(7, h // 25)
    kernel_w = max(3, w // 12)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_w, kernel_h))
    merged = cv2.dilate(binary, kernel, iterations=2)

    contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
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

        candidates.append({"box": (x, y, bw, bh), "score": score})

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
        "score": round(float(candidates[0]["score"]), 3),
    }
    return title_crop, title_box


def resize_for_ocr(image, target_long_side=OCR_RECHECK_LONG_SIDE):
    h, w = image.shape[:2]
    long_side = max(h, w)
    if long_side >= target_long_side:
        return image

    scale = target_long_side / long_side
    new_w = int(w * scale)
    new_h = int(h * scale)
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)


def score_candidate(candidate):
    text = candidate["text"]
    conf = candidate["confidence"]
    count = candidate["count"]
    length_score = min(len(text) / 10, 1.0)
    group_score = min(count / 5, 1.0)
    return conf * 0.55 + length_score * 0.30 + group_score * 0.15


def match_title_from_db(ocr_text):
    if not ocr_text:
        return {"status": "not_found", "matched_title": "", "candidates": []}

    return {"status": "not_found", "matched_title": "", "candidates": []}


def need_ocr_recheck(db_match_result):
    return db_match_result["status"] in ["not_found", "ambiguous"]


def run_ocr_on_crop(reader, crop, target_long_side=None):
    rotations_primary = [
        ("vertical_original", crop),
        ("rot90", cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)),
    ]
    rotations_fallback = [
        ("rot270", cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)),
        ("rot180", cv2.rotate(crop, cv2.ROTATE_180)),
    ]

    def run_rotations(rotations):
        candidates = []
        raw_by_rotation = {}

        for rot_name, img in rotations:
            if target_long_side is not None:
                img = resize_for_ocr(img, target_long_side=target_long_side)

            results = reader.predict(img)
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
                {"text": t, "confidence": round(s, 3)}
                for t, s in zip(texts, scores)
            ]

            if not texts:
                continue

            joined_text = normalize_korean_title_text(" ".join(texts))
            avg_conf = sum(scores) / len(scores)
            candidate = {
                "text": joined_text,
                "confidence": avg_conf,
                "count": len(texts),
                "type": "paddle_group",
                "rotation": rot_name,
            }
            candidate["score"] = score_candidate(candidate)
            candidates.append(candidate)

        return candidates, raw_by_rotation

    candidates, raw_by_rotation = run_rotations(rotations_primary)
    candidates.sort(key=lambda x: x["score"], reverse=True)

    if candidates:
        best = candidates[0]
        if len(best["text"]) >= 2 and float(best["score"]) >= 0.45:
            best["raw_by_rotation"] = raw_by_rotation
            return best

    fallback_candidates, fallback_raw = run_rotations(rotations_fallback)
    candidates.extend(fallback_candidates)
    raw_by_rotation.update(fallback_raw)

    if not candidates:
        return {
            "text": "",
            "confidence": 0.0,
            "rotation": "none",
            "type": "none",
            "score": 0.0,
            "raw_by_rotation": raw_by_rotation,
        }

    candidates.sort(key=lambda x: x["score"], reverse=True)
    best = candidates[0]
    best["raw_by_rotation"] = raw_by_rotation
    return best


def run_timed_ocr(reader, crop, target_long_side=None):
    start_time = time.perf_counter()
    result = run_ocr_on_crop(reader, crop, target_long_side=target_long_side)
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
    return result, round(elapsed_ms, 1)


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
        "center_px": [round(float(center[0]), 1), round(float(center[1]), 1)],
        "size_px": [round(float(short_side), 1), round(float(long_side), 1)],
        "angle_deg": round(angle_deg, 1),
    }


def init_realsense(width=640, height=480, fps=30):
    pipeline = rs.pipeline()
    config = rs.config()

    config.enable_stream(rs.stream.color, width, height, rs.format.bgr8, fps)
    config.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)

    try:
        profile = pipeline.start(config)
    except Exception as exc:
        raise RuntimeError(
            "RealSense 카메라를 시작할 수 없습니다. 카메라 연결과 권한을 확인하세요."
        ) from exc

    align = rs.align(rs.stream.color)
    color_profile = profile.get_stream(rs.stream.color).as_video_stream_profile()
    intrinsics = color_profile.get_intrinsics()
    return pipeline, align, intrinsics


def get_realsense_frame(pipeline, align):
    frames = pipeline.wait_for_frames()
    aligned_frames = align.process(frames)
    color_frame = aligned_frames.get_color_frame()
    depth_frame = aligned_frames.get_depth_frame()

    if not color_frame or not depth_frame:
        return None, None

    color_image = np.asanyarray(color_frame.get_data())
    return color_image, depth_frame


def get_depth_at_center(depth_frame, cx, cy):
    if depth_frame is None:
        return None

    width = depth_frame.get_width()
    height = depth_frame.get_height()
    x = int(round(cx))
    y = int(round(cy))
    values = []

    for dy in range(-2, 3):
        for dx in range(-2, 3):
            xx = min(max(x + dx, 0), width - 1)
            yy = min(max(y + dy, 0), height - 1)
            depth_m = float(depth_frame.get_distance(xx, yy))
            if depth_m > 0:
                values.append(depth_m)

    if not values:
        return None

    return round(float(np.median(values)), 3)


def pixel_to_camera_xyz(u, v, depth_m, intrinsics):
    if depth_m is None or depth_m <= 0:
        return {"x_m": None, "y_m": None, "z_m": None}

    point = rs.rs2_deproject_pixel_to_point(
        intrinsics,
        [float(u), float(v)],
        float(depth_m),
    )
    return {
        "x_m": round(float(point[0]), 3),
        "y_m": round(float(point[1]), 3),
        "z_m": round(float(point[2]), 3),
    }


def ensure_dirs(output_dir):
    output_dir = Path(output_dir)
    crop_dir = output_dir / "crops"
    title_crop_dir = output_dir / "title_crops"
    vis_dir = output_dir / "visualizations"
    output_dir.mkdir(parents=True, exist_ok=True)
    crop_dir.mkdir(parents=True, exist_ok=True)
    title_crop_dir.mkdir(parents=True, exist_ok=True)
    vis_dir.mkdir(parents=True, exist_ok=True)
    return output_dir, crop_dir, title_crop_dir, vis_dir


def make_runtime_paths(output_dir):
    output_dir, crop_dir, title_crop_dir, vis_dir = ensure_dirs(output_dir)
    return {
        "output_dir": output_dir,
        "crop_dir": crop_dir,
        "title_crop_dir": title_crop_dir,
        "vis_dir": vis_dir,
        "json_path": output_dir / "realtime_ocr_results.json",
        "latest_vis_path": vis_dir / "latest_detected.jpg",
    }


def save_json(json_path, books, source):
    data = {
        "timestamp": datetime.now().isoformat(),
        "frame_id": FRAME_ID,
        "coordinate_type": COORDINATE_TYPE,
        "source": source,
        "total_books": len(books),
        "books": books,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def format_book_json(
    book_id,
    selected_title,
    selected_method,
    det_conf,
    ocr_score,
    obb_info,
    depth_m,
    camera_coord,
    ocr_recheck,
    crop_path,
    title_crop_path,
):
    return {
        "book_id": int(book_id),
        "title_candidate": selected_title,
        "selected_method": selected_method,
        "confidence": {
            "detection": round(float(det_conf), 3),
            "ocr": round(float(ocr_score), 3),
        },
        "obb": obb_info,
        "depth": {
            "depth_m": depth_m,
            "valid": depth_m is not None,
        },
        "camera_coord": camera_coord,
        "ocr_recheck": ocr_recheck,
        "crop_path": str(crop_path) if crop_path else "",
        "title_crop_path": str(title_crop_path) if title_crop_path else "",
    }


def process_book(reader, color_image, depth_frame, intrinsics, book, paths, timestamp, save_artifacts):
    i = book["index"]
    points = book["points"]
    det_conf = book["confidence"]
    obb_info = compute_obb_properties(points)

    crop = crop_obb(color_image, points, padding=15)
    if crop is None:
        return None

    crop_path = None
    if save_artifacts:
        crop_path = paths["crop_dir"] / f"{timestamp}_book_{i:02d}_conf_{det_conf:.2f}.jpg"
        cv2.imwrite(str(crop_path), crop)

    title_crop, title_box = extract_main_title_region(crop)
    title_crop_path = None
    title_ocr_result = None
    title_text = ""

    if title_crop is not None and title_crop.size > 0:
        if save_artifacts:
            title_crop_path = paths["title_crop_dir"] / f"{timestamp}_book_{i:02d}_title_crop.jpg"
            cv2.imwrite(str(title_crop_path), title_crop)

        original_ocr_result, original_elapsed_ms = run_timed_ocr(
            reader,
            title_crop,
            target_long_side=None,
        )
        original_text = normalize_korean_title_text(original_ocr_result["text"])
        original_db_match = match_title_from_db(original_text)

        print(
            f"[{i}] 1차 OCR(original): "
            f"\"{original_text}\" score={original_ocr_result['score']:.2f} "
            f"db={original_db_match['status']}"
        )

        recheck_used = False
        recheck_reason = original_db_match["status"]
        recheck_ocr_result = None
        recheck_elapsed_ms = 0.0
        recheck_db_match = None

        if need_ocr_recheck(original_db_match):
            recheck_used = True
            print(f"[{i}] DB 매칭 불확실 -> 960 리사이즈 OCR 재확인")
            recheck_ocr_result, recheck_elapsed_ms = run_timed_ocr(
                reader,
                title_crop,
                target_long_side=OCR_RECHECK_LONG_SIDE,
            )
            recheck_text = normalize_korean_title_text(recheck_ocr_result["text"])
            recheck_db_match = match_title_from_db(recheck_text)

            print(
                f"[{i}] 2차 OCR(960): "
                f"\"{recheck_text}\" score={recheck_ocr_result['score']:.2f} "
                f"db={recheck_db_match['status']}"
            )

        if original_db_match["status"] == "matched":
            title_ocr_result = original_ocr_result
            title_text = normalize_korean_title_text(title_ocr_result["text"])
            selected_title = normalize_korean_title_text(
                original_db_match["matched_title"] or title_text
            )
            selected_score = float(title_ocr_result["score"])
            selected_method = "db_matched_original_ocr"
        elif recheck_db_match and recheck_db_match["status"] == "matched":
            title_ocr_result = recheck_ocr_result
            title_text = normalize_korean_title_text(title_ocr_result["text"])
            selected_title = normalize_korean_title_text(
                recheck_db_match["matched_title"] or title_text
            )
            selected_score = float(title_ocr_result["score"])
            selected_method = "db_matched_recheck_960"
        else:
            original_score = float(original_ocr_result["score"])
            recheck_score = float(recheck_ocr_result["score"]) if recheck_ocr_result else -1.0

            if recheck_ocr_result and recheck_score > original_score:
                title_ocr_result = recheck_ocr_result
                title_text = normalize_korean_title_text(title_ocr_result["text"])
                selected_title = title_text
                selected_score = recheck_score
                selected_method = "ocr_candidate_recheck_960"
            else:
                title_ocr_result = original_ocr_result
                title_text = normalize_korean_title_text(title_ocr_result["text"])
                selected_title = title_text
                selected_score = original_score
                selected_method = "ocr_candidate_original"

        ocr_recheck = {
            "used": recheck_used,
            "reason": recheck_reason,
            "original": {
                "text": original_text,
                "resize": "original",
                "elapsed_ms": original_elapsed_ms,
                "score": round(float(original_ocr_result["score"]), 3),
                "rotation": original_ocr_result["rotation"],
            },
            "recheck_960": {
                "text": normalize_korean_title_text(recheck_ocr_result["text"]) if recheck_ocr_result else "",
                "resize": OCR_RECHECK_LONG_SIDE if recheck_ocr_result else None,
                "elapsed_ms": recheck_elapsed_ms,
                "score": round(float(recheck_ocr_result["score"]), 3) if recheck_ocr_result else 0.0,
                "rotation": recheck_ocr_result["rotation"] if recheck_ocr_result else "none",
            },
        }
    else:
        selected_title = ""
        selected_score = 0.0
        selected_method = "title_crop_failed"
        ocr_recheck = {
            "used": False,
            "reason": "not_found",
            "original": {
                "text": "",
                "resize": "original",
                "elapsed_ms": 0.0,
                "score": 0.0,
                "rotation": "none",
            },
            "recheck_960": {
                "text": "",
                "resize": None,
                "elapsed_ms": 0.0,
                "score": 0.0,
                "rotation": "none",
            },
        }
        title_box = None

    center_px = obb_info["center_px"]
    depth_m = get_depth_at_center(depth_frame, center_px[0], center_px[1])
    camera_coord = pixel_to_camera_xyz(center_px[0], center_px[1], depth_m, intrinsics)

    print(f"[{i}] 최종 제목: \"{selected_title}\" method={selected_method}")

    return {
        "book_id": i,
        "title_candidate": selected_title,
        "selected_method": selected_method,
        "ocr_score": selected_score,
        "obb": obb_info,
        "depth_m": depth_m,
        "camera_coord": camera_coord,
        "ocr_recheck": ocr_recheck,
        "crop_path": crop_path,
        "title_crop_path": title_crop_path,
        "title_box": title_box,
        "det_confidence": det_conf,
    }


def draw_results(image, results):
    vis = image.copy()

    for item in results:
        pts_int = np.array(item["points"]).astype(np.int32)
        cv2.drawContours(vis, [pts_int], 0, (0, 255, 0), 2)

        cx = int(item["obb"]["center_px"][0])
        cy = int(item["obb"]["center_px"][1])
        title = item["title_candidate"] if item["title_candidate"] else "인식 실패"
        camera_coord = item["camera_coord"]
        xyz_text = (
            f"x:{camera_coord['x_m']} y:{camera_coord['y_m']} z:{camera_coord['z_m']}"
            if camera_coord["z_m"] is not None else "xyz: none"
        )

        cv2.putText(
            vis,
            f"#{item['book_id']} {title[:12]}",
            (cx, cy),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 255),
            2,
        )
        cv2.putText(
            vis,
            f"det:{item['det_confidence']:.2f} ocr:{item['ocr_score']:.2f}",
            (cx, cy + 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 0),
            1,
        )
        cv2.putText(
            vis,
            xyz_text,
            (cx, cy + 36),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 200, 255),
            1,
        )

    return vis


def build_json_books(processed_books):
    books = []
    for item in processed_books:
        books.append(
            format_book_json(
                book_id=item["book_id"],
                selected_title=item["title_candidate"],
                selected_method=item["selected_method"],
                det_conf=item["det_confidence"],
                ocr_score=item["ocr_score"],
                obb_info=item["obb"],
                depth_m=item["depth_m"],
                camera_coord=item["camera_coord"],
                ocr_recheck=item["ocr_recheck"],
                crop_path=item["crop_path"],
                title_crop_path=item["title_crop_path"],
            )
        )
    return books


def process_detections(model, reader, color_image, depth_frame, intrinsics, args, paths, timestamp, save_artifacts):
    yolo_results = model.predict(
        color_image,
        conf=args.conf,
        iou=args.iou,
        verbose=False,
    )

    if yolo_results[0].obb is None:
        return [], color_image.copy()

    raw_books = []
    for i, obb in enumerate(yolo_results[0].obb):
        points = obb.xyxyxyxy[0].cpu().numpy()
        conf = float(obb.conf[0].cpu().numpy())
        if conf < args.display_conf:
            continue

        raw_books.append({
            "index": i,
            "points": points,
            "confidence": conf,
        })

    processed_books = []
    for book in raw_books:
        processed = process_book(
            reader,
            color_image,
            depth_frame,
            intrinsics,
            book,
            paths,
            timestamp,
            save_artifacts=save_artifacts,
        )
        if processed is None:
            continue
        processed["points"] = book["points"]
        processed_books.append(processed)

    vis = draw_results(color_image, processed_books)
    return processed_books, vis


def init_ocr():
    return PaddleOCR(
        lang="korean",
        use_textline_orientation=True,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        enable_mkldnn=False,
    )


def run_realsense_mode(args, model, reader, paths):
    pipeline, align, intrinsics = init_realsense(
        width=args.width,
        height=args.height,
        fps=args.fps,
    )
    latest_books = []
    latest_vis = None

    print("RealSense 실시간 실행 시작")
    print("q: 종료 | s: 현재 프레임 저장")

    try:
        while True:
            frame_start = time.time()
            color_image, depth_frame = get_realsense_frame(pipeline, align)
            if color_image is None:
                print("RealSense 프레임을 읽을 수 없습니다.")
                continue

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            processed_books, vis = process_detections(
                model,
                reader,
                color_image,
                depth_frame,
                intrinsics,
                args,
                paths,
                timestamp,
                save_artifacts=False,
            )

            latest_books = processed_books
            latest_vis = vis
            json_books = build_json_books(processed_books)
            save_json(paths["json_path"], json_books, source="realsense_live")
            cv2.imwrite(str(paths["latest_vis_path"]), vis)

            elapsed = time.time() - frame_start
            fps = 1.0 / elapsed if elapsed > 0 else 0.0
            cv2.putText(
                vis,
                f"FPS:{fps:.1f} books:{len(processed_books)} | q: quit | s: save",
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2,
            )
            cv2.imshow("RealSense Book OCR", vis)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                save_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                processed_books, vis = process_detections(
                    model,
                    reader,
                    color_image,
                    depth_frame,
                    intrinsics,
                    args,
                    paths,
                    save_timestamp,
                    save_artifacts=True,
                )
                json_books = build_json_books(processed_books)
                save_json(paths["json_path"], json_books, source="realsense_live")
                save_vis_path = paths["vis_dir"] / f"{save_timestamp}_detected.jpg"
                cv2.imwrite(str(save_vis_path), vis)
                print(f"저장 완료: {save_vis_path}")

    finally:
        pipeline.stop()
        cv2.destroyAllWindows()
        if latest_vis is not None:
            cv2.imwrite(str(paths["latest_vis_path"]), latest_vis)
        save_json(paths["json_path"], build_json_books(latest_books), source="realsense_live")
        print("종료 완료")
        print(f"최종 JSON: {paths['json_path']}")


def run_image_mode(args, model, reader, paths):
    if not args.image_path:
        raise ValueError("--source image 사용 시 --image_path를 지정해야 합니다.")

    image = cv2.imread(args.image_path)
    if image is None:
        raise RuntimeError(f"이미지를 읽을 수 없습니다: {args.image_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    processed_books, vis = process_detections(
        model,
        reader,
        image,
        depth_frame=None,
        intrinsics=None,
        args=args,
        paths=paths,
        timestamp=timestamp,
        save_artifacts=True,
    )

    json_books = build_json_books(processed_books)
    save_json(paths["json_path"], json_books, source="image_file")
    save_vis_path = paths["vis_dir"] / f"{timestamp}_detected.jpg"
    cv2.imwrite(str(save_vis_path), vis)

    cv2.imshow("RealSense Book OCR", vis)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    print("완료")
    print(f"시각화 이미지: {save_vis_path}")
    print(f"JSON: {paths['json_path']}")


def main():
    args = parse_args()
    paths = make_runtime_paths(args.output_dir)

    model_path = Path(args.model)
    if not model_path.exists():
        raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {model_path}")

    print("YOLO OBB 모델 로드 중...")
    model = YOLO(str(model_path))

    print("PaddleOCR 초기화 중...")
    reader = init_ocr()
    print("PaddleOCR 준비 완료")

    if args.source == "realsense":
        run_realsense_mode(args, model, reader, paths)
    else:
        run_image_mode(args, model, reader, paths)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"실행 오류: {exc}")
        sys.exit(1)
