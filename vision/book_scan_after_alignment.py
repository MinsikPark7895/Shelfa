#!/usr/bin/env python3
"""
ArUco 정렬 완료 payload를 받아 책 탐색까지만 수행하는 파이프라인.

이 파일은 책 뽑기, hook, gripper, pick_plan 실행을 만들지 않는다.
정렬은 외부 모듈/팀이 담당하고, 여기서는 정렬 완료 자세에서 book_scan_pose를
계산한 뒤 YOLO OBB + PaddleOCR + depth/TF 결과를 JSON/RViz로 검증한다.
"""

import argparse
import json
import os
import time
from datetime import datetime

import cv2
import numpy as np
from geometry_msgs.msg import Pose
from visualization_msgs.msg import Marker, MarkerArray

try:
    from . import realtime_yolo_paddle_ocr as vision
    from .vision_pipeline_utils import (
        compute_book_keypoints_from_obb,
        deproject_keypoints_to_camera_xyz,
        detect_books,
        draw_books,
    )
except ImportError:
    import realtime_yolo_paddle_ocr as vision
    from vision_pipeline_utils import (
        compute_book_keypoints_from_obb,
        deproject_keypoints_to_camera_xyz,
        detect_books,
        draw_books,
    )


BOOK_SCAN_JSON_PATH = os.path.join(vision.OUTPUT_DIR, "book_scan_result.json")
TARGET_BOOK_LOCK_JSON_PATH = os.path.join(vision.OUTPUT_DIR, "target_book_lock.json")
BOOK_SCAN_OCR_DEBUG_DIR = os.path.join(vision.OUTPUT_DIR, "book_scan_ocr_debug")
DEFAULT_ALIGNMENT_PAYLOAD_PATH = os.path.join(
    vision.OUTPUT_DIR,
    "alignment_payload.json"
)
DEFAULT_TARGET_TITLE = "제3인류"
BOOK_SCAN_MARKER_TOPIC = "/book_scan_markers"
BOOK_SCAN_BACKOFF_M = 0.20
MOCK_ALIGNMENT_BASE_FRAME = "base_link"
MOCK_ALIGNMENT_CAMERA_FRAME = "camera_color_optical_frame"
MOCK_ALIGNMENT_SHELF_FRAME = "bookshelf_frame"
MOCK_ALIGNMENT_FRONT_DIRECTION_BASE = [-1.0, 0.0, 0.0]
MOCK_ALIGNMENT_TCP_POSE = [500.0, 0.0, 400.0, 180.0, 0.0, 90.0]

SCAN_STATES = [
    "WAIT_ALIGNMENT_DONE",
    "MAKE_BOOK_SCAN_POSE",
    "CAPTURE_FRAME",
    "DETECT_BOOKS",
    "OCR_TITLES",
    "COMPUTE_BOOK_LOCATIONS",
    "SELECT_TARGET_BOOK_OPTIONAL",
    "PUBLISH_AND_SAVE",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Alignment payload 이후 book_scan_pose에서 책등/OCR/좌표만 계산합니다."
    )
    parser.add_argument(
        "--alignment-payload-json",
        default=DEFAULT_ALIGNMENT_PAYLOAD_PATH,
        help="정렬 팀이 저장한 alignment payload JSON 경로입니다."
    )
    parser.add_argument(
        "--alignment-payload",
        default=None,
        help="파일 대신 직접 넘기는 alignment payload JSON 문자열입니다."
    )
    parser.add_argument(
        "--use-mock-alignment",
        action="store_true",
        help="alignment payload 파일을 읽지 않고 내장 mock alignment payload를 사용합니다."
    )
    parser.add_argument(
        "--target-title",
        default=DEFAULT_TARGET_TITLE,
        help="포함 문자열로 선택할 목표 책 제목입니다. 없거나 매칭 실패 시 최고 confidence 책을 fallback 선택합니다."
    )
    parser.add_argument(
        "--book-index",
        type=int,
        default=None,
        help="OCR 선택 대신 지정한 book_index를 선택/lock합니다.",
    )
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--no-display", action="store_true")
    parser.add_argument(
        "--disable-ocr",
        action="store_true",
        help="PaddleOCR 초기화/실행을 건너뛰고 YOLO + 수동 book_index 선택만 사용합니다.",
    )
    parser.add_argument(
        "--no-save-ocr-debug-crops",
        action="store_true",
        help="책별 OCR 입력 crop 저장을 끕니다.",
    )
    parser.add_argument(
        "--ocr-target-long-side",
        type=int,
        default=vision.OCR_TARGET_LONG_SIDE,
        help="OCR 전에 입력 이미지의 긴 변을 지정 크기로 확대/축소합니다. 예: 960",
    )
    parser.add_argument(
        "--ocr-crop-padding",
        type=int,
        default=25,
        help="YOLO OBB crop 주변 padding pixel입니다.",
    )
    parser.add_argument(
        "--disable-ocr-multi-input",
        action="store_true",
        help="title crop/full OBB crop 다중 OCR 후보 평가를 끄고 title crop만 사용합니다.",
    )
    parser.add_argument(
        "--ocr-max-books",
        type=int,
        default=5,
        help="confidence 상위 N권만 OCR합니다. 0이면 모든 검출 책을 OCR합니다.",
    )
    return parser.parse_args()


def set_state(result, state):
    result["state"] = state
    result["state_history"].append({
        "state": state,
        "timestamp": datetime.now().isoformat(),
    })
    print(f"[State] {state}")


def load_alignment_payload(args):
    if args.use_mock_alignment:
        return get_mock_alignment_payload()

    if args.alignment_payload:
        return json.loads(args.alignment_payload)

    with open(args.alignment_payload_json, "r", encoding="utf-8") as f:
        return json.load(f)


def get_mock_alignment_payload():
    return {
        "aligned": True,
        "base_frame": MOCK_ALIGNMENT_BASE_FRAME,
        "camera_frame": MOCK_ALIGNMENT_CAMERA_FRAME,
        "shelf_frame": MOCK_ALIGNMENT_SHELF_FRAME,
        "bookshelf_front_direction_base": list(MOCK_ALIGNMENT_FRONT_DIRECTION_BASE),
        "aligned_tcp_pose": list(MOCK_ALIGNMENT_TCP_POSE),
    }


def is_finite_vector(values, length):
    if not isinstance(values, (list, tuple)) or len(values) != length:
        return False
    return all(np.isfinite(float(v)) for v in values)


def is_valid_book_mid_pose(book):
    if not isinstance(book, dict):
        return False

    depth_valid = book.get("depth_valid") or {}
    if bool(depth_valid.get("mid")) is not True:
        return False

    tf_valid = book.get("tf_valid") or {}
    if bool(tf_valid.get("mid")) is not True:
        return False

    base_xyz = book.get("base_xyz_m") or {}
    return is_finite_vector(base_xyz.get("mid"), 3)


def validate_alignment_payload(payload):
    required = [
        "aligned",
        "base_frame",
        "camera_frame",
        "shelf_frame",
        "bookshelf_front_direction_base",
        "aligned_tcp_pose",
    ]
    missing = [key for key in required if key not in payload]
    if missing:
        return False, f"alignment payload missing keys: {missing}"

    if not payload.get("aligned"):
        return False, "alignment payload aligned=false"

    front = payload.get("bookshelf_front_direction_base")
    if not is_finite_vector(front, 3):
        return False, "bookshelf_front_direction_base must be finite [x, y, z]"

    try:
        parse_aligned_tcp_pose_to_posx_mm(payload.get("aligned_tcp_pose"))
    except (TypeError, ValueError) as exc:
        return False, f"aligned_tcp_pose invalid: {exc}"

    return True, None


def parse_aligned_tcp_pose_to_posx_mm(aligned_tcp_pose):
    """
    aligned_tcp_pose는 우선 Doosan posx mm/deg [x,y,z,rx,ry,rz]를 기대한다.
    dict 형태라면 posx_mm, posx, 또는 position_m + rpy_deg 조합도 허용한다.
    """
    if isinstance(aligned_tcp_pose, (list, tuple)):
        if not is_finite_vector(aligned_tcp_pose, 6):
            raise ValueError("list pose must be [x_mm, y_mm, z_mm, rx_deg, ry_deg, rz_deg]")
        return [float(v) for v in aligned_tcp_pose]

    if not isinstance(aligned_tcp_pose, dict):
        raise TypeError("expected list or dict")

    for key in ("posx_mm", "posx"):
        value = aligned_tcp_pose.get(key)
        if value is not None:
            if not is_finite_vector(value, 6):
                raise ValueError(f"{key} must be length-6 finite list")
            return [float(v) for v in value]

    position_m = aligned_tcp_pose.get("position_m") or aligned_tcp_pose.get("position")
    rpy_deg = aligned_tcp_pose.get("rpy_deg") or aligned_tcp_pose.get("orientation_rpy_deg")
    if is_finite_vector(position_m, 3) and is_finite_vector(rpy_deg, 3):
        return [
            float(position_m[0]) * 1000.0,
            float(position_m[1]) * 1000.0,
            float(position_m[2]) * 1000.0,
            float(rpy_deg[0]),
            float(rpy_deg[1]),
            float(rpy_deg[2]),
        ]

    raise ValueError("dict pose must contain posx_mm/posx or position_m + rpy_deg")


def compute_book_scan_pose(alignment_payload):
    aligned_posx = parse_aligned_tcp_pose_to_posx_mm(
        alignment_payload["aligned_tcp_pose"]
    )
    front = np.array(
        alignment_payload["bookshelf_front_direction_base"],
        dtype=np.float64
    )
    norm = np.linalg.norm(front)
    if norm < 1e-9:
        raise ValueError("bookshelf_front_direction_base norm is zero")

    front = front / norm
    scan_posx = list(aligned_posx)
    scan_posx[0] += float(front[0]) * BOOK_SCAN_BACKOFF_M * 1000.0
    scan_posx[1] += float(front[1]) * BOOK_SCAN_BACKOFF_M * 1000.0
    scan_posx[2] += float(front[2]) * BOOK_SCAN_BACKOFF_M * 1000.0

    return {
        "frame_id": alignment_payload["base_frame"],
        "description": "aligned_tcp_pose + bookshelf_front_direction_base * 0.20m",
        "backoff_m": BOOK_SCAN_BACKOFF_M,
        "bookshelf_front_direction_base": [round(float(v), 6) for v in front],
        "posx_mm_deg": [round(float(v), 3) for v in scan_posx],
    }


def make_ocr_debug_path(timestamp, book_index, suffix):
    return os.path.join(
        BOOK_SCAN_OCR_DEBUG_DIR,
        f"{timestamp}_book_{int(book_index):02d}_{suffix}.jpg",
    )


def save_debug_image(path, image):
    if image is None or image.size == 0:
        return None
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cv2.imwrite(path, image)
    return path


def image_shape_payload(image):
    if image is None or image.size == 0:
        return None
    height, width = image.shape[:2]
    return [int(width), int(height)]


def normalize_for_match(text):
    return vision.normalize_korean_title_text(str(text or "")).lower()


def target_text_bonus(text, target_title):
    text_norm = normalize_for_match(text)
    target_norm = normalize_for_match(target_title)
    if not text_norm or not target_norm:
        return 0.0
    if target_norm in text_norm or text_norm in target_norm:
        return 0.35
    overlap = len(set(text_norm) & set(target_norm))
    return min(0.25, overlap * 0.08)


def run_ocr_candidate(ocr, image, source_name, args):
    ocr_result, elapsed_ms = vision.run_timed_ocr(
        ocr,
        image,
        source_name=source_name,
        show_debug=False,
        target_long_side=args.ocr_target_long_side,
    )
    text = vision.normalize_korean_title_text(ocr_result.get("text", ""))
    score = float(ocr_result.get("score", 0.0))
    adjusted_score = score + target_text_bonus(text, args.target_title)
    return {
        "source": source_name,
        "text": text,
        "base_score": round(score, 3),
        "adjusted_score": round(float(adjusted_score), 3),
        "elapsed_ms": round(float(elapsed_ms), 1),
        "rotation": ocr_result.get("rotation"),
        "raw_by_rotation": ocr_result.get("raw_by_rotation", {}),
        "ocr_result": ocr_result,
    }


def extract_title_candidates_for_book(ocr, frame, book, args, timestamp):
    crop = vision.crop_obb(frame, book["points"], padding=int(args.ocr_crop_padding))
    debug = {
        "book_index": int(book["index"]),
        "crop_file": None,
        "title_crop_file": None,
        "ocr_input_file": None,
        "crop_size_px": None,
        "title_crop_size_px": None,
        "ocr_input_size_px": None,
        "ocr_target_long_side": args.ocr_target_long_side,
        "ocr_crop_padding": int(args.ocr_crop_padding),
        "candidate_results": [],
        "ocr_result": None,
        "elapsed_ms": None,
    }
    if crop is None:
        debug["error"] = "crop_obb_failed"
        return [], debug

    if not args.no_save_ocr_debug_crops:
        debug["crop_file"] = save_debug_image(
            make_ocr_debug_path(timestamp, book["index"], "obb_crop"),
            crop,
        )
    debug["crop_size_px"] = image_shape_payload(crop)

    title_crop, _ = vision.extract_main_title_region(crop)
    ocr_inputs = []
    if title_crop is not None and title_crop.size > 0:
        if not args.no_save_ocr_debug_crops:
            debug["title_crop_file"] = save_debug_image(
                make_ocr_debug_path(timestamp, book["index"], "title_crop"),
                title_crop,
            )
        debug["title_crop_size_px"] = image_shape_payload(title_crop)
        ocr_inputs.append(("title_crop", title_crop))
    else:
        debug["title_crop_size_px"] = None

    if not args.disable_ocr_multi_input:
        ocr_inputs.append(("obb_crop", crop))
    elif not ocr_inputs:
        ocr_inputs.append(("obb_crop", crop))

    seen_sources = set()
    unique_ocr_inputs = []
    for source_name, image in ocr_inputs:
        if source_name in seen_sources:
            continue
        seen_sources.add(source_name)
        unique_ocr_inputs.append((source_name, image))

    candidate_results = []
    for source_name, image in unique_ocr_inputs:
        input_file = None
        if not args.no_save_ocr_debug_crops:
            input_file = save_debug_image(
                make_ocr_debug_path(timestamp, book["index"], f"ocr_input_{source_name}"),
                image,
            )
        result = run_ocr_candidate(
            ocr,
            image,
            f"book_scan_{book['index']}_{source_name}",
            args,
        )
        result["ocr_input_file"] = input_file
        result["ocr_input_size_px"] = image_shape_payload(image)
        candidate_results.append(result)

    candidate_results.sort(
        key=lambda item: float(item.get("adjusted_score", 0.0)),
        reverse=True,
    )
    debug["candidate_results"] = candidate_results

    if candidate_results:
        best = candidate_results[0]
        debug["ocr_input_file"] = best.get("ocr_input_file")
        debug["ocr_input_size_px"] = best.get("ocr_input_size_px")
        debug["ocr_result"] = best.get("ocr_result")
        debug["elapsed_ms"] = best.get("elapsed_ms")
    else:
        best = None

    if best is None:
        return [], debug

    text = best.get("text", "")
    if not text:
        return [], debug

    return [{
        "text": text,
        "score": round(float(best.get("base_score", 0.0)), 3),
        "adjusted_score": round(float(best.get("adjusted_score", 0.0)), 3),
        "elapsed_ms": round(float(best.get("elapsed_ms", 0.0)), 1),
        "rotation": best.get("rotation"),
        "ocr_source": best.get("source"),
        "ocr_input_file": debug["ocr_input_file"],
    }], debug


def make_skipped_ocr_debug(book, reason):
    return {
        "book_index": int(book["index"]),
        "skipped": True,
        "reason": reason,
        "crop_file": None,
        "title_crop_file": None,
        "ocr_input_file": None,
        "candidate_results": [],
        "ocr_result": None,
        "elapsed_ms": None,
    }


def transform_camera_xyz_to_base(robot_node, camera_xyz_m):
    if not vision.is_valid_camera_xyz(camera_xyz_m):
        return None
    return robot_node.transform_camera_xyz_to_base(camera_xyz_m)


def build_book_scan_entries(robot_node, frame, depth_frame, color_intrinsics, ocr, obb_data, args):
    books = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    if args.disable_ocr:
        ocr_indexes = set()
    elif int(args.ocr_max_books) > 0:
        ocr_indexes = {
            int(book["index"])
            for book in sorted(
                obb_data,
                key=lambda item: float(item.get("confidence", 0.0)),
                reverse=True,
            )[:int(args.ocr_max_books)]
        }
    else:
        ocr_indexes = {int(book["index"]) for book in obb_data}

    print(
        f"[BookScan] detected_books={len(obb_data)} "
        f"ocr_books={len(ocr_indexes)} ocr_max_books={int(args.ocr_max_books)}"
    )

    for order, book in enumerate(obb_data, start=1):
        obb_size = book["obb_info"].get("size_px")
        print(
            f"[BookScan] ({order}/{len(obb_data)}) book_index={int(book['index'])} "
            f"conf={float(book['confidence']):.3f} size_px={obb_size}"
        )
        keypoints = compute_book_keypoints_from_obb(book)
        keypoint_camera = deproject_keypoints_to_camera_xyz(
            depth_frame,
            color_intrinsics,
            keypoints,
        )
        center_px = book["obb_info"]["center_px"]
        center_camera_xyz_m = vision.deproject_pixel_to_camera_xyz(
            depth_frame,
            color_intrinsics,
            center_px[0],
            center_px[1],
        )

        center_base = transform_camera_xyz_to_base(robot_node, center_camera_xyz_m)
        top_base = transform_camera_xyz_to_base(
            robot_node,
            keypoint_camera["top_camera_xyz_m"],
        )
        mid_base = transform_camera_xyz_to_base(
            robot_node,
            keypoint_camera["mid_camera_xyz_m"],
        )
        bottom_base = transform_camera_xyz_to_base(
            robot_node,
            keypoint_camera["bottom_camera_xyz_m"],
        )

        if args.disable_ocr:
            print(f"[BookScan][OCR] disabled book_index={int(book['index'])}")
            title_candidates = []
            ocr_debug = make_skipped_ocr_debug(book, "disable_ocr")
        elif int(book["index"]) in ocr_indexes:
            print(f"[BookScan][OCR] start book_index={int(book['index'])}")
            ocr_start = time.perf_counter()
            title_candidates, ocr_debug = extract_title_candidates_for_book(
                ocr,
                frame,
                book,
                args,
                timestamp,
            )
            print(
                f"[BookScan][OCR] done book_index={int(book['index'])} "
                f"elapsed={(time.perf_counter() - ocr_start):.2f}s "
                f"candidates={title_candidates}"
            )
        else:
            print(f"[BookScan][OCR] skip book_index={int(book['index'])}")
            title_candidates = []
            ocr_debug = make_skipped_ocr_debug(book, "ocr_max_books_limit")

        books.append({
            "book_index": int(book["index"]),
            "confidence": round(float(book["confidence"]), 3),
            "title_candidates": title_candidates,
            "ocr_debug": ocr_debug,
            "pixels": {
                "center": center_px,
                "top": keypoints["top_center_px"],
                "mid": keypoints["mid_center_px"],
                "bottom": keypoints["bottom_center_px"],
            },
            "camera_xyz_m": {
                "center": center_camera_xyz_m,
                "top": keypoint_camera["top_camera_xyz_m"],
                "mid": keypoint_camera["mid_camera_xyz_m"],
                "bottom": keypoint_camera["bottom_camera_xyz_m"],
            },
            "base_xyz_m": {
                "center": center_base,
                "top": top_base,
                "mid": mid_base,
                "bottom": bottom_base,
            },
            "depth_valid": {
                "center": vision.is_valid_camera_xyz(center_camera_xyz_m),
                "top": vision.is_valid_camera_xyz(keypoint_camera["top_camera_xyz_m"]),
                "mid": vision.is_valid_camera_xyz(keypoint_camera["mid_camera_xyz_m"]),
                "bottom": vision.is_valid_camera_xyz(keypoint_camera["bottom_camera_xyz_m"]),
            },
            "tf_valid": {
                "center": center_base is not None,
                "top": top_base is not None,
                "mid": mid_base is not None,
                "bottom": bottom_base is not None,
            },
            "obb": {
                "center_px": book["obb_info"]["center_px"],
                "size_px": book["obb_info"]["size_px"],
                "angle_deg": book["obb_info"]["angle_deg"],
                "points": [
                    [round(float(x), 1), round(float(y), 1)]
                    for x, y in np.array(book["points"]).reshape(-1, 2)
                ],
            },
        })
    return books


def select_target_book_candidate(books, target_title, override_book_index=None):
    if not books:
        return None

    valid_books = [book for book in books if is_valid_book_mid_pose(book)]
    if not valid_books:
        return None

    if override_book_index is not None:
        for book in valid_books:
            if int(book["book_index"]) == int(override_book_index):
                return {
                    "reason": "manual_book_index",
                    "book_index": int(book["book_index"]),
                    "matched_text": None,
                    "target_title": target_title,
                    "confidence": round(float(book["confidence"]), 3),
                }
        print(f"[BookSelect] book_index={override_book_index}인 valid book을 찾지 못했습니다.")
        return None

    highest_conf_book = max(valid_books, key=lambda item: float(item["confidence"]))
    target_norm = (
        vision.normalize_korean_title_text(target_title).lower()
        if target_title else ""
    )

    if target_norm:
        partial_matches = []
        for book in valid_books:
            for candidate in book.get("title_candidates", []):
                text = str(candidate.get("text", "")).lower()
                if target_norm in text or text in target_norm:
                    return {
                        "reason": "title_match",
                        "book_index": int(book["book_index"]),
                        "matched_text": candidate["text"],
                        "target_title": target_title,
                        "confidence": round(float(book["confidence"]), 3),
                        "ocr_score": candidate.get("score"),
                        "ocr_adjusted_score": candidate.get("adjusted_score"),
                    }
                bonus = target_text_bonus(text, target_title)
                if bonus > 0.0:
                    partial_matches.append((bonus, book, candidate))

        if partial_matches:
            partial_matches.sort(
                key=lambda item: (
                    float(item[2].get("adjusted_score", item[2].get("score", 0.0))),
                    float(item[0]),
                    float(item[1]["confidence"]),
                ),
                reverse=True,
            )
            _bonus, book, candidate = partial_matches[0]
            return {
                "reason": "title_partial_match",
                "book_index": int(book["book_index"]),
                "matched_text": candidate["text"],
                "target_title": target_title,
                "confidence": round(float(book["confidence"]), 3),
                "ocr_score": candidate.get("score"),
                "ocr_adjusted_score": candidate.get("adjusted_score"),
            }

        return {
            "reason": "fallback_highest_confidence",
            "book_index": int(highest_conf_book["book_index"]),
            "matched_text": None,
            "target_title": target_title,
            "confidence": round(float(highest_conf_book["confidence"]), 3),
        }

    return {
        "reason": "fallback_no_target_title",
        "book_index": int(highest_conf_book["book_index"]),
        "matched_text": None,
        "target_title": target_title,
        "confidence": round(float(highest_conf_book["confidence"]), 3),
    }


def print_selected_book_pose(books, selected_book_candidate):
    if selected_book_candidate is None:
        print("[SelectedBookPose] valid mid pose를 가진 선택 책이 없습니다.")
        return

    selected_index = int(selected_book_candidate["book_index"])
    selected_book = None
    for book in books:
        if int(book.get("book_index", -1)) == selected_index:
            selected_book = book
            break

    if selected_book is None:
        print(f"[SelectedBookPose] book_index={selected_index}인 책을 books에서 찾지 못했습니다.")
        return

    print("\n" + "=" * 80)
    print("[SelectedBookPose]")
    print(f"book_index: {selected_index}")
    print(f"reason: {selected_book_candidate.get('reason')}")
    print(f"matched_text: {selected_book_candidate.get('matched_text')}")
    print(f"target_title: {selected_book_candidate.get('target_title')}")
    print(f"title_candidates: {selected_book.get('title_candidates', [])}")
    print(f"pixels.mid: {(selected_book.get('pixels') or {}).get('mid')}")
    print(f"camera_xyz_m.mid: {(selected_book.get('camera_xyz_m') or {}).get('mid')}")
    print(f"base_xyz_m.mid: {(selected_book.get('base_xyz_m') or {}).get('mid')}")
    print(f"depth_valid.mid: {(selected_book.get('depth_valid') or {}).get('mid')}")
    print(f"tf_valid.mid: {(selected_book.get('tf_valid') or {}).get('mid')}")
    print("=" * 80 + "\n")


def find_book_by_candidate(books, selected_book_candidate):
    if selected_book_candidate is None:
        return None
    selected_index = int(selected_book_candidate["book_index"])
    for book in books:
        if int(book.get("book_index", -1)) == selected_index:
            return book
    return None


def save_target_book_lock(books, selected_book_candidate, target_title):
    selected_book = find_book_by_candidate(books, selected_book_candidate)
    if selected_book is None:
        print("[TargetLock] 선택된 book dict를 찾지 못해 target lock을 저장하지 않았습니다.")
        return

    pixels = selected_book.get("pixels") or {}
    obb = selected_book.get("obb") or {}
    payload = {
        "target_title": target_title,
        "locked_from_book_index": int(selected_book.get("book_index")),
        "matched_text": selected_book_candidate.get("matched_text"),
        "title_candidates": selected_book.get("title_candidates", []),
        "pixels_mid": pixels.get("mid"),
        "pixels_center": pixels.get("center"),
        "obb_center_px": obb.get("center_px"),
        "obb_size_px": obb.get("size_px"),
        "obb_angle_deg": obb.get("angle_deg"),
        "timestamp": datetime.now().isoformat(),
    }

    os.makedirs(os.path.dirname(TARGET_BOOK_LOCK_JSON_PATH) or ".", exist_ok=True)
    with open(TARGET_BOOK_LOCK_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[TargetLock] saved: {TARGET_BOOK_LOCK_JSON_PATH}")


def make_point_marker(frame_id, marker_id, xyz, color, scale=0.025):
    marker = Marker()
    marker.header.frame_id = frame_id
    marker.header.stamp.sec = 0
    marker.header.stamp.nanosec = 0
    marker.ns = "book_scan_points"
    marker.id = marker_id
    marker.type = Marker.SPHERE
    marker.action = Marker.ADD
    marker.pose.position.x = float(xyz[0])
    marker.pose.position.y = float(xyz[1])
    marker.pose.position.z = float(xyz[2])
    marker.pose.orientation.w = 1.0
    marker.scale.x = scale
    marker.scale.y = scale
    marker.scale.z = scale
    marker.color.r = color[0]
    marker.color.g = color[1]
    marker.color.b = color[2]
    marker.color.a = color[3]
    return marker


def make_text_marker(frame_id, marker_id, xyz, text):
    marker = Marker()
    marker.header.frame_id = frame_id
    marker.header.stamp.sec = 0
    marker.header.stamp.nanosec = 0
    marker.ns = "book_scan_labels"
    marker.id = marker_id
    marker.type = Marker.TEXT_VIEW_FACING
    marker.action = Marker.ADD
    marker.pose.position.x = float(xyz[0])
    marker.pose.position.y = float(xyz[1])
    marker.pose.position.z = float(xyz[2]) + 0.035
    marker.pose.orientation.w = 1.0
    marker.scale.z = 0.025
    marker.color.r = 1.0
    marker.color.g = 1.0
    marker.color.b = 1.0
    marker.color.a = 0.95
    marker.text = text
    return marker


def make_scan_pose_marker(frame_id, marker_id, book_scan_pose):
    posx = book_scan_pose["posx_mm_deg"]
    marker = Marker()
    marker.header.frame_id = frame_id
    marker.header.stamp.sec = 0
    marker.header.stamp.nanosec = 0
    marker.ns = "book_scan_pose"
    marker.id = marker_id
    marker.type = Marker.CUBE
    marker.action = Marker.ADD
    marker.pose = Pose()
    marker.pose.position.x = float(posx[0]) / 1000.0
    marker.pose.position.y = float(posx[1]) / 1000.0
    marker.pose.position.z = float(posx[2]) / 1000.0
    marker.pose.orientation.w = 1.0
    marker.scale.x = 0.04
    marker.scale.y = 0.04
    marker.scale.z = 0.04
    marker.color.r = 0.1
    marker.color.g = 0.6
    marker.color.b = 1.0
    marker.color.a = 0.6
    return marker


def publish_book_scan_markers(robot_node, marker_pub, books, selected_book_candidate, book_scan_pose):
    marker_array = MarkerArray()
    frame_id = vision.BASE_FRAME
    marker_array.markers.append(make_scan_pose_marker(frame_id, 1, book_scan_pose))

    selected_index = (
        None if selected_book_candidate is None
        else selected_book_candidate["book_index"]
    )

    marker_id = 10
    for book in books:
        center = book["base_xyz_m"]["center"]
        top = book["base_xyz_m"]["top"]
        mid = book["base_xyz_m"]["mid"]
        if center is None:
            continue

        is_selected = book["book_index"] == selected_index
        center_color = (1.0, 0.2, 0.2, 1.0) if is_selected else (0.0, 1.0, 0.2, 0.85)
        marker_array.markers.append(make_point_marker(frame_id, marker_id, center, center_color, 0.03))
        marker_id += 1

        if top is not None:
            marker_array.markers.append(make_point_marker(frame_id, marker_id, top, (1.0, 0.8, 0.0, 0.8), 0.02))
            marker_id += 1
        if mid is not None:
            marker_array.markers.append(make_point_marker(frame_id, marker_id, mid, (0.2, 0.8, 1.0, 0.8), 0.02))
            marker_id += 1

        title = book["title_candidates"][0]["text"] if book["title_candidates"] else "no_ocr"
        label = f"#{book['book_index']} {title}"
        marker_array.markers.append(make_text_marker(frame_id, marker_id, center, label))
        marker_id += 1

    marker_pub.publish(marker_array)
    print(f"[RViz] book scan markers published: {BOOK_SCAN_MARKER_TOPIC}")


def save_book_scan_result(result):
    os.makedirs(vision.OUTPUT_DIR, exist_ok=True)
    with open(BOOK_SCAN_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[Saved] {BOOK_SCAN_JSON_PATH}")


def draw_scan_overlay(frame, obb_data, selected_book_candidate, target_title, status):
    vis = frame.copy()
    draw_books(vis, obb_data)
    selected_index = (
        None if selected_book_candidate is None
        else selected_book_candidate["book_index"]
    )
    selected_text = "selected: none"
    if selected_book_candidate is not None:
        selected_text = (
            f"selected: #{selected_book_candidate.get('book_index')} "
            f"{selected_book_candidate.get('reason')}"
        )

    for book in obb_data:
        pts = np.array(book["points"], dtype=np.int32)
        is_selected = (
            selected_index is not None
            and int(book["index"]) == int(selected_index)
        )
        color = (0, 0, 255) if is_selected else (0, 255, 255)
        thickness = 4 if is_selected else 2
        cv2.drawContours(vis, [pts], 0, color, thickness)

        center = tuple(np.mean(pts, axis=0).astype(int))
        label = f"#{int(book['index'])} conf={float(book['confidence']):.2f}"
        cv2.putText(
            vis,
            label,
            (center[0] - 40, center[1]),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2,
        )
    cv2.putText(
        vis,
        f"target_title: {target_title}",
        (20, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
    )
    cv2.putText(
        vis,
        selected_text,
        (20, 60),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 255),
        2,
    )
    cv2.putText(
        vis,
        f"status: {status} | q: quit",
        (20, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 0) if status == "book_scan_done" else (0, 165, 255),
        2,
    )
    return vis


def main():
    args = parse_args()
    os.makedirs(vision.OUTPUT_DIR, exist_ok=True)
    os.makedirs(vision.CROP_DIR, exist_ok=True)
    os.makedirs(vision.TITLE_CROP_DIR, exist_ok=True)
    os.makedirs(BOOK_SCAN_OCR_DEBUG_DIR, exist_ok=True)

    result = {
        "timestamp": datetime.now().isoformat(),
        "mode": "book_scan_after_alignment",
        "target_title": args.target_title,
        "states": SCAN_STATES,
        "state_history": [],
        "alignment_payload": None,
        "book_scan_pose": None,
        "books": [],
        "selected_book_candidate": None,
        "status": "started",
    }

    pipeline = None
    robot_node = None

    try:
        set_state(result, "WAIT_ALIGNMENT_DONE")
        alignment_payload = load_alignment_payload(args)
        ok, error = validate_alignment_payload(alignment_payload)
        if not ok:
            result["status"] = "alignment_payload_invalid"
            result["error"] = error
            save_book_scan_result(result)
            print(f"[Alignment] {error}")
            return
        result["alignment_payload"] = alignment_payload

        if not vision.rclpy.ok():
            vision.rclpy.init(args=None)
        robot_node = vision.BookVisionRobotNode()
        marker_pub = robot_node.create_publisher(MarkerArray, BOOK_SCAN_MARKER_TOPIC, 10)

        set_state(result, "MAKE_BOOK_SCAN_POSE")
        book_scan_pose = compute_book_scan_pose(alignment_payload)
        result["book_scan_pose"] = book_scan_pose
        print("[BookScanPose]")
        print(json.dumps(book_scan_pose, ensure_ascii=False, indent=2))

        print("YOLO OBB 모델 로드 중...")
        yolo_model = vision.YOLO(vision.MODEL_PATH)
        ocr = None
        if args.disable_ocr:
            print("[OCR] --disable-ocr: PaddleOCR 초기화와 OCR 실행을 건너뜁니다.")
        else:
            print("PaddleOCR 초기화 중...")
            ocr = vision.PaddleOCR(
                lang="korean",
                use_textline_orientation=True,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                enable_mkldnn=False,
            )
            print("PaddleOCR 준비 완료")

        pipeline, align, color_intrinsics = vision.init_realsense(
            width=args.width,
            height=args.height,
            fps=args.fps,
        )

        set_state(result, "CAPTURE_FRAME")
        frame = None
        depth_frame = None
        for _ in range(10):
            frame, depth_frame, _ = vision.get_realsense_frames(pipeline, align)
            if frame is not None and depth_frame is not None:
                break
            time.sleep(0.05)
        if frame is None or depth_frame is None:
            result["status"] = "capture_failed"
            save_book_scan_result(result)
            return

        set_state(result, "DETECT_BOOKS")
        obb_data = detect_books(yolo_model, frame, depth_frame, color_intrinsics)
        if not obb_data:
            result["status"] = "book_not_found"
            save_book_scan_result(result)
            print("YOLO 책등 인식 실패")
            return

        set_state(result, "OCR_TITLES")
        set_state(result, "COMPUTE_BOOK_LOCATIONS")
        books = build_book_scan_entries(
            robot_node,
            frame.copy(),
            depth_frame,
            color_intrinsics,
            ocr,
            obb_data,
            args,
        )
        result["books"] = books

        set_state(result, "SELECT_TARGET_BOOK_OPTIONAL")
        selected_book_candidate = select_target_book_candidate(
            books,
            args.target_title,
            override_book_index=args.book_index,
        )
        result["selected_book_candidate"] = selected_book_candidate
        if selected_book_candidate is None:
            result["status"] = "no_valid_book_pose"
            result["error"] = "depth/tf valid mid pose를 가진 책이 없습니다."
            print("[BookSelect] depth/tf valid mid pose를 가진 책이 없습니다.")
        else:
            print_selected_book_pose(books, selected_book_candidate)
            save_target_book_lock(books, selected_book_candidate, args.target_title)

        set_state(result, "PUBLISH_AND_SAVE")
        publish_book_scan_markers(
            robot_node,
            marker_pub,
            books,
            selected_book_candidate,
            book_scan_pose,
        )
        if selected_book_candidate is not None:
            result["status"] = "book_scan_done"
        save_book_scan_result(result)

        if not args.no_display:
            vis = draw_scan_overlay(
                frame,
                obb_data,
                selected_book_candidate,
                args.target_title,
                result["status"],
            )
            while True:
                cv2.imshow("Bookshelf Book Scan", vis)
                if (cv2.waitKey(20) & 0xFF) == ord("q"):
                    break

    except FileNotFoundError as exc:
        result["status"] = "alignment_payload_file_not_found"
        result["error"] = str(exc)
        save_book_scan_result(result)
        print(f"[Alignment] payload 파일을 찾지 못했습니다: {exc}")
    finally:
        if pipeline is not None:
            pipeline.stop()
        cv2.destroyAllWindows()
        if robot_node is not None:
            robot_node.destroy_node()
        if vision.rclpy.ok():
            vision.rclpy.shutdown()
        print("Bookshelf book scan pipeline 종료")


if __name__ == "__main__":
    main()
