#!/usr/bin/env python3
"""
ArUco 정렬 완료 payload를 받아 책 탐색까지만 수행하는 파이프라인.

이 파일은 책 뽑기, hook, gripper, pick_plan 실행을 만들지 않는다.
정렬은 외부 모듈/팀이 담당하고, 여기서는 정렬 완료 자세에서 book_scan_pose를
계산한 뒤 YOLO OBB + PaddleOCR + depth/TF 결과를 JSON/RViz로 검증한다.
"""

import argparse
import difflib
import json
import os
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

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
        "--yolo-conf",
        type=float,
        default=0.75,
        help="YOLO OBB 검출 confidence threshold입니다. 높일수록 후보가 줄어듭니다.",
    )
    parser.add_argument(
        "--use-ocr-title-match",
        action="store_true",
        help="OCR 제목 문자열을 target book 선택에 사용합니다. OCR 후보가 있으면 기본적으로 함께 적용됩니다.",
    )
    parser.add_argument(
        "--book-index",
        type=int,
        default=None,
        help="OCR 선택 대신 지정한 book_index를 선택합니다. target lock 저장도 이 book을 기준으로 합니다.",
    )
    parser.add_argument(
        "--lock-book-index",
        type=int,
        default=None,
        help="target lock만 강제로 지정할 book_index입니다. --book-index와 함께 쓰면 --book-index가 우선합니다.",
    )
    parser.add_argument(
        "--allow-fallback-lock",
        action="store_true",
        help="fallback_highest_confidence 결과도 target lock 저장을 허용합니다.",
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
        default=None,
        help="OCR 전에 입력 이미지의 긴 변을 지정 크기로 확대/축소합니다. 기본값은 비활성화입니다.",
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
        "--ocr-include-upright-rotations",
        action="store_true",
        help="OCR에 rot0/rot180 후보를 추가합니다. 기본은 rot90/rot270만 사용합니다.",
    )
    parser.add_argument(
        "--ocr-max-variants-per-book",
        type=int,
        default=2,
        help="한 책당 OCR 처리할 crop variant 개수 제한입니다. 기본은 title_crop 우선 2개입니다.",
    )
    parser.add_argument(
        "--ocr-max-books",
        type=int,
        default=0,
        help="confidence 상위 N권만 OCR합니다. 0이면 모든 검출 책을 OCR합니다.",
    )
    parser.add_argument(
        "--ocr-early-stop-on-match",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="title_match/title_fuzzy_match가 나오면 남은 OCR 책을 중단합니다.",
    )
    parser.add_argument(
        "--ocr-early-stop-reasons",
        default="title_match,title_fuzzy_match",
        help="글로벌 OCR 조기 종료 이유를 comma-separated로 지정합니다.",
    )
    parser.add_argument(
        "--ocr-early-stop-on-partial",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="title_partial_match도 글로벌 OCR 조기 종료 이유에 포함합니다.",
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


def sanitize_for_json(obj, _stack=None):
    if _stack is None:
        _stack = set()

    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        value = float(obj)
        return value if np.isfinite(value) else None
    if isinstance(obj, str):
        return obj
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, np.ndarray):
        return sanitize_for_json(obj.tolist(), _stack)

    obj_id = id(obj)
    if obj_id in _stack:
        return "[Circular]"

    if isinstance(obj, dict):
        _stack.add(obj_id)
        try:
            return {
                str(key): sanitize_for_json(value, _stack)
                for key, value in obj.items()
            }
        finally:
            _stack.discard(obj_id)

    if isinstance(obj, (list, tuple, set)):
        _stack.add(obj_id)
        try:
            return [sanitize_for_json(value, _stack) for value in obj]
        finally:
            _stack.discard(obj_id)

    if hasattr(obj, "tolist"):
        try:
            return sanitize_for_json(obj.tolist(), _stack)
        except Exception:
            pass

    if hasattr(obj, "__dict__"):
        try:
            _stack.add(obj_id)
            try:
                return {
                    str(key): sanitize_for_json(value, _stack)
                    for key, value in vars(obj).items()
                    if not str(key).startswith("_")
                }
            finally:
                _stack.discard(obj_id)
        except Exception:
            pass

    return str(obj)


def normalize_ocr_text(text: str) -> str:
    if text is None:
        return ""

    normalized = unicodedata.normalize("NFKC", str(text)).lower()
    chars = []
    for ch in normalized:
        if "가" <= ch <= "힣" or "0" <= ch <= "9" or "a" <= ch <= "z":
            chars.append(ch)
    return "".join(chars)


def normalize_title_for_match(text: str) -> str:
    return strip_long_numeric_runs(normalize_ocr_text(text))


def strip_long_numeric_runs(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\d{4,}", "", text)


def best_sequence_similarity(target_text: str, candidate_text: str) -> float:
    if not target_text or not candidate_text:
        return 0.0

    target_len = len(target_text)
    candidate_len = len(candidate_text)
    if candidate_len <= target_len + 6:
        return float(difflib.SequenceMatcher(None, target_text, candidate_text).ratio())

    window_len = max(target_len, min(candidate_len, target_len + 4))
    best = 0.0
    for start in range(0, candidate_len - window_len + 1):
        window = candidate_text[start:start + window_len]
        ratio = float(difflib.SequenceMatcher(None, target_text, window).ratio())
        if ratio > best:
            best = ratio
    return best


def get_match_priority(match_reason: str) -> int:
    priority_map = {
        "title_match": 0,
        "title_fuzzy_match": 1,
        "title_partial_match": 2,
        "fallback_highest_confidence": 3,
        "fallback_no_target_title": 4,
        "none": 5,
    }
    return priority_map.get(str(match_reason or "none"), 5)


def score_title_match(ocr_text: str, target_title: str) -> Dict[str, Any]:
    raw_text = "" if ocr_text is None else str(ocr_text)
    normalized_text = normalize_ocr_text(raw_text)
    normalized_target = normalize_ocr_text(target_title)
    scoring_text = normalize_title_for_match(raw_text)
    scoring_target = normalize_title_for_match(target_title)

    target_chars = []
    seen = set()
    for ch in scoring_target:
        if ch not in seen:
            seen.add(ch)
            target_chars.append(ch)

    target_char_total = len(target_chars)
    target_char_overlap = sum(1 for ch in target_chars if ch in scoring_text)
    overlap_ratio = (
        float(target_char_overlap) / float(target_char_total)
        if target_char_total > 0
        else 0.0
    )

    seq_similarity = max(
        best_sequence_similarity(scoring_target, scoring_text),
        best_sequence_similarity(scoring_target, normalized_text),
    )
    title_similarity_score = max(overlap_ratio, seq_similarity)

    keyword_bonus = 0.0
    match_reason_candidate = "none"

    if normalized_target and normalized_target in normalized_text:
        match_reason_candidate = "title_match"
        title_similarity_score = 1.0
        keyword_bonus = 1.5
    else:
        if "3인류" in normalized_text:
            match_reason_candidate = "title_partial_match"
            keyword_bonus = max(keyword_bonus, 1.5)
        elif "인류" in normalized_text and "3" in normalized_text:
            match_reason_candidate = "title_partial_match"
            keyword_bonus = max(keyword_bonus, 1.2)
        elif target_char_overlap >= 3:
            match_reason_candidate = "title_fuzzy_match"
            keyword_bonus = max(keyword_bonus, 0.8)

        # OCR이 '제3인류'를 '스제크인류', '스체크인류'처럼 읽는 경우를 살린다.
        # 핵심 단어 '인류'가 살아 있고, target 문자 일부가 겹치며,
        # 전체 문자열 유사도도 아주 낮지 않으면 fuzzy match로 인정한다.
        if (
            match_reason_candidate == "none"
            and "인류" in normalized_text
            and target_char_overlap >= 2
            and title_similarity_score >= 0.45
        ):
            match_reason_candidate = "title_fuzzy_match"
            keyword_bonus = max(keyword_bonus, 0.7)

        if (
            match_reason_candidate == "none"
            and normalized_text.endswith("인류")
            and target_char_overlap >= 2
            and seq_similarity >= 0.45
        ):
            match_reason_candidate = "title_fuzzy_match"
            keyword_bonus = max(keyword_bonus, 0.7)

        if match_reason_candidate == "none" and title_similarity_score >= 0.55:
            match_reason_candidate = "title_fuzzy_match"
            keyword_bonus = max(keyword_bonus, 0.4)

    return {
        "raw_text": raw_text,
        "normalized_text": normalized_text,
        "normalized_target": normalized_target,
        "seq_similarity": round(float(seq_similarity), 3),
        "overlap_ratio": round(float(overlap_ratio), 3),
        "title_similarity_score": round(float(title_similarity_score), 3),
        "target_char_overlap": int(target_char_overlap),
        "target_char_total": int(target_char_total),
        "keyword_bonus": round(float(keyword_bonus), 3),
        "match_reason_candidate": match_reason_candidate,
    }


def candidate_text_is_useful(candidate: Dict[str, Any]) -> bool:
    text = candidate.get("text") or candidate.get("raw_text") or ""
    return bool(str(text).strip())


def parse_csv_reason_set(value):
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    return {item.strip() for item in str(value).split(",") if item.strip()}


def get_global_early_stop_reasons(args):
    reasons = parse_csv_reason_set(args.ocr_early_stop_reasons)
    if bool(args.ocr_early_stop_on_partial):
        reasons.add("title_partial_match")
    else:
        reasons.discard("title_partial_match")
    if not bool(args.ocr_early_stop_on_match):
        reasons.clear()
    return reasons


def is_allowed_target_lock_reason(reason: str, allow_fallback_lock: bool = False) -> bool:
    allowed = {
        "title_match",
        "title_fuzzy_match",
        "title_partial_match",
        "manual_book_index",
        "manual_lock_book_index",
    }
    if allow_fallback_lock:
        allowed.add("fallback_highest_confidence")
    return str(reason or "") in allowed


def iter_ocr_text_entries(ocr_result):
    entries = []
    raw_by_rotation = ocr_result.get("raw_by_rotation") or {}

    if isinstance(raw_by_rotation, dict):
        for rotation_name, raw_items in raw_by_rotation.items():
            if not isinstance(raw_items, list):
                continue
            for rotation_index, item in enumerate(raw_items):
                if not isinstance(item, dict):
                    continue
                text = item.get("text", "")
                if text is None:
                    text = ""
                text = str(text)
                if not text.strip():
                    continue
                entries.append({
                    "text": text,
                    "confidence": float(item.get("confidence") or 0.0),
                    "rotation": rotation_name,
                    "rotation_index": int(rotation_index),
                })

    if entries:
        return entries

    fallback_text = ocr_result.get("text", "")
    if fallback_text is None:
        fallback_text = ""
    fallback_text = str(fallback_text)
    if fallback_text.strip():
        entries.append({
            "text": fallback_text,
            "confidence": float(ocr_result.get("confidence") or 0.0),
            "rotation": ocr_result.get("rotation") or "none",
            "rotation_index": 0,
        })

    return entries


def build_ocr_candidate_result(entry, ocr_result, args, source_name, elapsed_ms, book_index):
    raw_text = str(entry.get("text", ""))
    entry_confidence = float(entry.get("confidence") or 0.0)
    match_info = score_title_match(raw_text, args.target_title)
    adjusted_score = entry_confidence + 1.5 * float(match_info["title_similarity_score"]) + float(match_info["keyword_bonus"])
    result = {
        "source": source_name,
        "text": raw_text,
        "raw_text": raw_text,
        "score": round(entry_confidence, 3),
        "base_score": round(entry_confidence, 3),
        "adjusted_score": round(float(adjusted_score), 3),
        "normalized_text": match_info["normalized_text"],
        "normalized_target": match_info["normalized_target"],
        "seq_similarity": match_info["seq_similarity"],
        "overlap_ratio": match_info["overlap_ratio"],
        "title_similarity_score": match_info["title_similarity_score"],
        "target_char_overlap": match_info["target_char_overlap"],
        "target_char_total": match_info["target_char_total"],
        "keyword_bonus": match_info["keyword_bonus"],
        "match_reason_candidate": match_info["match_reason_candidate"],
        "elapsed_ms": round(float(elapsed_ms), 1),
        "rotation": entry.get("rotation"),
        "rotation_index": int(entry.get("rotation_index", 0)),
        "raw_by_rotation": ocr_result.get("raw_by_rotation", {}),
        "ocr_result": ocr_result,
    }
    return result


def choose_best_ocr_candidate(candidate_results):
    if not candidate_results:
        return None

    def sort_key(item):
        priority = get_match_priority(item.get("match_reason_candidate"))
        return (
            int(priority),
            -float(item.get("adjusted_score", 0.0)),
            -float(item.get("score", 0.0)),
            int(item.get("rotation_index", 0)),
        )

    return sorted(candidate_results, key=sort_key)[0]


def run_ocr_candidate(ocr, image, source_name, args, book_index):
    ocr_result, elapsed_ms = vision.run_timed_ocr(
        ocr,
        image,
        source_name=source_name,
        show_debug=False,
        target_long_side=args.ocr_target_long_side,
        allow_upright_rotations=bool(args.ocr_include_upright_rotations),
    )
    entries = iter_ocr_text_entries(ocr_result)
    candidate_results = [
        build_ocr_candidate_result(entry, ocr_result, args, source_name, elapsed_ms, book_index)
        for entry in entries
    ]
    best_candidate = choose_best_ocr_candidate(candidate_results)
    if best_candidate is None:
        best_candidate = {
            "source": source_name,
            "text": "",
            "raw_text": "",
            "score": 0.0,
            "base_score": 0.0,
            "adjusted_score": 0.0,
            "normalized_text": "",
            "normalized_target": normalize_ocr_text(args.target_title),
            "seq_similarity": 0.0,
            "overlap_ratio": 0.0,
            "title_similarity_score": 0.0,
            "target_char_overlap": 0,
            "target_char_total": 0,
            "keyword_bonus": 0.0,
            "match_reason_candidate": "none",
            "elapsed_ms": round(float(elapsed_ms), 1),
            "rotation": ocr_result.get("rotation"),
            "rotation_index": 0,
            "raw_by_rotation": ocr_result.get("raw_by_rotation", {}),
            "ocr_result": ocr_result,
        }

    print("[OCRMatchDebug]")
    print(f"book_index: {int(book_index)}")
    print(f"raw_text: {best_candidate['raw_text']}")
    print(f"normalized_text: {best_candidate['normalized_text']}")
    print(f"normalized_target: {best_candidate['normalized_target']}")
    print(f"seq_similarity: {best_candidate['seq_similarity']}")
    print(f"overlap_ratio: {best_candidate['overlap_ratio']}")
    print(f"title_similarity_score: {best_candidate['title_similarity_score']}")
    print(f"target_char_overlap: {best_candidate['target_char_overlap']}")
    print(f"keyword_bonus: {best_candidate['keyword_bonus']}")
    print(f"match_reason_candidate: {best_candidate['match_reason_candidate']}")
    print(f"adjusted_score: {best_candidate['adjusted_score']}")

    best_candidate["candidate_results"] = [dict(item) for item in candidate_results]
    return best_candidate


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
        "ocr_include_upright_rotations": bool(args.ocr_include_upright_rotations),
        "ocr_max_variants_per_book": int(args.ocr_max_variants_per_book),
        "candidate_results": [],
        "ocr_result": None,
        "elapsed_ms": None,
        "processed_variants": 0,
        "variant_limit": int(args.ocr_max_variants_per_book),
        "stopped_early": False,
        "stop_reason": None,
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

    candidate_results = []
    processed_variants = 0
    variant_limit = max(1, int(args.ocr_max_variants_per_book))
    stop_reasons = {"title_match", "title_fuzzy_match", "title_partial_match"}

    for source_name, image in ocr_inputs:
        if processed_variants >= variant_limit:
            debug["stopped_early"] = True
            debug["stop_reason"] = "variant_limit"
            break

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
            book["index"],
        )
        result["ocr_input_file"] = input_file
        result["ocr_input_size_px"] = image_shape_payload(image)
        candidate_results.append(result)
        processed_variants += 1
        debug["processed_variants"] = processed_variants
        debug["candidate_results"] = [dict(item) for item in candidate_results]

        if str(result.get("match_reason_candidate") or "") in stop_reasons:
            debug["stopped_early"] = True
            debug["stop_reason"] = result.get("match_reason_candidate")
            debug["stop_text"] = result.get("text")
            print(
                f"[OCR][EarlyStop] book_index={int(book['index'])} "
                f"reason={result.get('match_reason_candidate')} text={result.get('text')}"
            )
            break

    candidate_results.sort(
        key=lambda item: (
            get_match_priority(item.get("match_reason_candidate")),
            -float(item.get("adjusted_score", 0.0)),
            -float(item.get("score", 0.0)),
        ),
    )
    debug["candidate_results"] = [dict(item) for item in candidate_results]

    if candidate_results:
        best = candidate_results[0]
        debug["ocr_input_file"] = best.get("ocr_input_file")
        debug["ocr_input_size_px"] = best.get("ocr_input_size_px")
        debug["ocr_result"] = best.get("ocr_result")
        debug["elapsed_ms"] = best.get("elapsed_ms")
        debug["best_match_reason"] = best.get("match_reason_candidate")
        debug["best_text"] = best.get("text")
    else:
        best = None

    if best is None:
        return [], debug

    title_candidates = []
    for candidate in candidate_results:
        if not candidate_text_is_useful(candidate):
            continue
        title_candidates.append({
            "text": candidate.get("text", ""),
            "score": round(float(candidate.get("score", candidate.get("base_score", 0.0))), 3),
            "base_score": round(float(candidate.get("base_score", candidate.get("score", 0.0))), 3),
            "adjusted_score": round(float(candidate.get("adjusted_score", 0.0)), 3),
            "elapsed_ms": round(float(candidate.get("elapsed_ms", 0.0)), 1),
            "rotation": candidate.get("rotation"),
            "ocr_source": candidate.get("source"),
            "ocr_input_file": candidate.get("ocr_input_file") or debug["ocr_input_file"],
            "normalized_text": candidate.get("normalized_text"),
            "normalized_target": candidate.get("normalized_target"),
            "seq_similarity": candidate.get("seq_similarity"),
            "overlap_ratio": candidate.get("overlap_ratio"),
            "title_similarity_score": candidate.get("title_similarity_score"),
            "target_char_overlap": candidate.get("target_char_overlap"),
            "target_char_total": candidate.get("target_char_total"),
            "keyword_bonus": candidate.get("keyword_bonus"),
            "match_reason_candidate": candidate.get("match_reason_candidate"),
            "raw_text": candidate.get("raw_text", candidate.get("text", "")),
        })

    return title_candidates, debug


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


def load_previous_target_lock():
    if not os.path.exists(TARGET_BOOK_LOCK_JSON_PATH):
        return None

    try:
        with open(TARGET_BOOK_LOCK_JSON_PATH, "r", encoding="utf-8") as f:
            lock = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[BookScan][OCRPriority] target lock 로드 실패: {exc}")
        return None

    if not isinstance(lock, dict):
        return None

    return lock


def get_lock_focus_pixel(lock_payload):
    if not isinstance(lock_payload, dict):
        return None

    for key in ("pixels_mid", "pixels_center", "obb_center_px"):
        pixel = lock_payload.get(key)
        if is_finite_vector(pixel, 2):
            return [float(pixel[0]), float(pixel[1])]
    return None


def pixel_distance(px_a, px_b):
    if not is_finite_vector(px_a, 2) or not is_finite_vector(px_b, 2):
        return None
    return float(np.linalg.norm(np.array(px_a, dtype=np.float64) - np.array(px_b, dtype=np.float64)))


def select_ocr_target_books(obb_data, args, frame):
    frame_h, frame_w = frame.shape[:2]
    screen_center = [float(frame_w) / 2.0, float(frame_h) / 2.0]
    target_lock = load_previous_target_lock()
    lock_focus_px = get_lock_focus_pixel(target_lock)

    prioritized = []
    for book in obb_data:
        index = int(book["index"])
        conf = float(book.get("confidence", 0.0))
        center_px = book.get("obb_info", {}).get("center_px")
        focus_px = center_px if is_finite_vector(center_px, 2) else None
        if focus_px is None:
            continue

        manual_reason = None
        manual_priority = None
        if args.book_index is not None and index == int(args.book_index):
            manual_reason = "manual_book_index"
            manual_priority = 0
        elif args.lock_book_index is not None and index == int(args.lock_book_index):
            manual_reason = "manual_lock_book_index"
            manual_priority = 0

        lock_distance = pixel_distance(focus_px, lock_focus_px) if lock_focus_px is not None else None
        center_distance = pixel_distance(focus_px, screen_center)

        if manual_priority is not None:
            priority_group = 0
            primary_distance = 0.0
            reason = manual_reason
        elif lock_distance is not None:
            priority_group = 1
            primary_distance = lock_distance
            reason = "previous_target_lock"
        else:
            priority_group = 2
            primary_distance = center_distance if center_distance is not None else float("inf")
            reason = "screen_center"

        prioritized.append({
            "book_index": index,
            "priority_group": priority_group,
            "primary_distance": round(float(primary_distance), 3) if np.isfinite(primary_distance) else float("inf"),
            "confidence": round(conf, 3),
            "reason": reason,
            "manual_reason": manual_reason,
            "focus_px": focus_px,
            "lock_distance": round(float(lock_distance), 3) if lock_distance is not None else None,
            "center_distance": round(float(center_distance), 3) if center_distance is not None else None,
        })

    if not prioritized:
        return [], {
            "screen_center_px": screen_center,
            "lock_focus_px": lock_focus_px,
            "selected_indexes": [],
        }

    prioritized.sort(
        key=lambda item: (
            int(item["priority_group"]),
            float(item["primary_distance"]),
            -float(item["confidence"]),
            int(item["book_index"]),
        )
    )

    max_books = int(args.ocr_max_books)
    if max_books > 0:
        selected = prioritized[:max_books]
    else:
        selected = prioritized

    ocr_indexes = [int(item["book_index"]) for item in selected]

    print(
        f"[BookScan][OCRPriority] screen_center_px={screen_center} "
        f"lock_focus_px={lock_focus_px} selected_indexes={ocr_indexes}"
    )
    for item in selected:
        print(
            f"[BookScan][OCRPriority] book_index={item['book_index']} "
            f"reason={item['reason']} priority_group={item['priority_group']} "
            f"primary_distance={item['primary_distance']} confidence={item['confidence']}"
        )

    return ocr_indexes, {
        "screen_center_px": screen_center,
        "lock_focus_px": lock_focus_px,
        "selected_indexes": ocr_indexes,
        "prioritized": prioritized,
    }


def transform_camera_xyz_to_base(robot_node, camera_xyz_m):
    if not vision.is_valid_camera_xyz(camera_xyz_m):
        return None
    return robot_node.transform_camera_xyz_to_base(camera_xyz_m)


def build_book_scan_entries(robot_node, frame, depth_frame, color_intrinsics, ocr, obb_data, args):
    books = []
    build_debug = {
        "ocr_priority_debug": getattr(args, "_ocr_priority_debug", None),
        "global_early_stop_reasons": sorted(list(get_global_early_stop_reasons(args))),
        "stopped_early": False,
        "stop_reason": None,
        "stop_text": None,
        "stop_book_index": None,
    }
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    if args.disable_ocr:
        ocr_indexes = set()
    else:
        ordered_ocr_indexes, ocr_priority_debug = select_ocr_target_books(
            obb_data,
            args,
            frame,
        )
        ocr_indexes = set(ordered_ocr_indexes)
        if not hasattr(args, "_ocr_priority_debug"):
            setattr(args, "_ocr_priority_debug", ocr_priority_debug)
            build_debug["ocr_priority_debug"] = ocr_priority_debug

    print(
        f"[BookScan] detected_books={len(obb_data)} "
        f"ocr_books={len(ocr_indexes)} ocr_max_books={int(args.ocr_max_books)}"
    )

    global_early_stop_reasons = get_global_early_stop_reasons(args)

    for order, book in enumerate(obb_data, start=1):
        obb_size = book["obb_info"].get("size_px")
        stop_after_append = False
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

        book_entry = {
            "book_index": int(book["index"]),
            "confidence": round(float(book["confidence"]), 3),
            "title_candidates": [],
            "ocr_debug": None,
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
        }

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

            if title_candidates:
                best_candidate = title_candidates[0]
                best_reason = str(best_candidate.get("match_reason_candidate") or "")
                if best_reason in global_early_stop_reasons:
                    build_debug["stopped_early"] = True
                    build_debug["stop_reason"] = best_reason
                    build_debug["stop_text"] = best_candidate.get("text")
                    build_debug["stop_book_index"] = int(book["index"])
                    print(
                        f"[OCR][GlobalStop] target title matched. "
                        f"Skip remaining OCR books. book_index={int(book['index'])} "
                        f"reason={best_reason} text={best_candidate.get('text')}"
                    )
                    stop_after_append = True
        else:
            print(f"[BookScan][OCR] skip book_index={int(book['index'])}")
            title_candidates = []
            ocr_debug = make_skipped_ocr_debug(book, "ocr_max_books_limit")

        book_entry["title_candidates"] = title_candidates
        book_entry["ocr_debug"] = ocr_debug
        books.append(book_entry)
        if stop_after_append:
            break
    return books, build_debug


def select_target_book_candidate(
    books,
    target_title,
    override_book_index=None,
    lock_book_index=None,
    use_ocr_title_match=False,
):
    if not books:
        return None

    valid_books = [book for book in books if is_valid_book_mid_pose(book)]
    if not valid_books:
        return None

    manual_index = None
    manual_reason = None
    if override_book_index is not None:
        manual_index = int(override_book_index)
        manual_reason = "manual_book_index"
    elif lock_book_index is not None:
        manual_index = int(lock_book_index)
        manual_reason = "manual_lock_book_index"

    if manual_index is not None:
        for book in valid_books:
            if int(book["book_index"]) == int(manual_index):
                return {
                    "reason": manual_reason,
                    "book_index": int(book["book_index"]),
                    "matched_text": None,
                    "target_title": target_title,
                    "confidence": round(float(book["confidence"]), 3),
                    "selection_source": manual_reason,
                }
        print(f"[BookSelect] book_index={manual_index}인 valid book을 찾지 못했습니다.")
        return None

    highest_conf_book = max(valid_books, key=lambda item: float(item["confidence"]))

    ocr_candidates_available = any(book.get("title_candidates") for book in valid_books)
    should_use_ocr_title_match = bool(target_title) and (bool(use_ocr_title_match) or ocr_candidates_available)

    if should_use_ocr_title_match and target_title:
        candidate_pool = []
        for book in valid_books:
            for candidate in book.get("title_candidates", []):
                reason = str(candidate.get("match_reason_candidate") or "none")
                priority = get_match_priority(reason)
                if priority >= get_match_priority("fallback_highest_confidence"):
                    continue
                if not candidate_text_is_useful(candidate):
                    continue
                candidate_pool.append((
                    priority,
                    -float(candidate.get("adjusted_score", candidate.get("score", 0.0))),
                    -float(book["confidence"]),
                    -int(book["book_index"]),
                    book,
                    candidate,
                ))

        if candidate_pool:
            candidate_pool.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
            _priority, _neg_adjusted, _neg_confidence, _neg_index, book, candidate = candidate_pool[0]
            return {
                "reason": candidate.get("match_reason_candidate"),
                "book_index": int(book["book_index"]),
                "matched_text": candidate.get("text"),
                "target_title": target_title,
                "confidence": round(float(book["confidence"]), 3),
                "ocr_score": candidate.get("score"),
                "ocr_adjusted_score": candidate.get("adjusted_score"),
                "ocr_match_reason": candidate.get("match_reason_candidate"),
                "ocr_source": candidate.get("ocr_source"),
                "selection_source": "ocr_title_match",
            }

        return {
            "reason": "fallback_highest_confidence",
            "book_index": int(highest_conf_book["book_index"]),
            "matched_text": None,
            "target_title": target_title,
            "confidence": round(float(highest_conf_book["confidence"]), 3),
            "selection_source": "fallback_highest_confidence",
        }

    return {
        "reason": "fallback_no_target_title",
        "book_index": int(highest_conf_book["book_index"]),
        "matched_text": None,
        "target_title": target_title,
        "confidence": round(float(highest_conf_book["confidence"]), 3),
        "selection_source": "fallback_no_target_title",
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
    print(f"selection_source: {selected_book_candidate.get('selection_source')}")
    print(f"matched_text: {selected_book_candidate.get('matched_text')}")
    print(f"target_title: {selected_book_candidate.get('target_title')}")
    print(f"ocr_match_reason: {selected_book_candidate.get('ocr_match_reason')}")
    print(f"ocr_score: {selected_book_candidate.get('ocr_score')}")
    print(f"ocr_adjusted_score: {selected_book_candidate.get('ocr_adjusted_score')}")
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


def save_target_book_lock(books, selected_book_candidate, target_title, allow_fallback_lock=False):
    if selected_book_candidate is None:
        print("[TargetLock] selected book candidate가 없어 target lock을 저장하지 않았습니다.")
        return

    reason = str(selected_book_candidate.get("reason") or "")
    if not is_allowed_target_lock_reason(reason, allow_fallback_lock=allow_fallback_lock):
        print(
            f"[TargetLock] reason={reason} 는 기본 저장 대상이 아닙니다. "
            "target lock을 저장하지 않았습니다."
        )
        return

    selected_book = find_book_by_candidate(books, selected_book_candidate)
    if selected_book is None:
        print("[TargetLock] 선택된 book dict를 찾지 못해 target lock을 저장하지 않았습니다.")
        return

    pixels = selected_book.get("pixels") or {}
    obb = selected_book.get("obb") or {}
    payload = {
        "target_title": target_title,
        "selected_reason": reason,
        "locked_from_book_index": int(selected_book.get("book_index")),
        "matched_text": selected_book_candidate.get("matched_text"),
        "ocr_score": selected_book_candidate.get("ocr_score"),
        "ocr_adjusted_score": selected_book_candidate.get("ocr_adjusted_score"),
        "ocr_match_reason": selected_book_candidate.get("ocr_match_reason"),
        "selection_source": selected_book_candidate.get("selection_source"),
        "title_candidates": selected_book.get("title_candidates", []),
        "pixels_mid": pixels.get("mid"),
        "pixels_center": pixels.get("center"),
        "obb_center_px": obb.get("center_px"),
        "obb_size_px": obb.get("size_px"),
        "obb_angle_deg": obb.get("angle_deg"),
        "timestamp": datetime.now().isoformat(),
    }

    os.makedirs(os.path.dirname(TARGET_BOOK_LOCK_JSON_PATH) or ".", exist_ok=True)
    safe_payload = sanitize_for_json(payload)
    with open(TARGET_BOOK_LOCK_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(safe_payload, f, ensure_ascii=False, indent=2)
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
    safe_result = sanitize_for_json(result)
    with open(BOOK_SCAN_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(safe_result, f, ensure_ascii=False, indent=2)
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
        "yolo_conf": float(args.yolo_conf),
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
        obb_data = detect_books(
            yolo_model,
            frame,
            depth_frame,
            color_intrinsics,
            yolo_conf=args.yolo_conf,
        )
        if not obb_data:
            result["status"] = "book_not_found"
            save_book_scan_result(result)
            print("YOLO 책등 인식 실패")
            return

        set_state(result, "OCR_TITLES")
        set_state(result, "COMPUTE_BOOK_LOCATIONS")
        books, ocr_build_debug = build_book_scan_entries(
            robot_node,
            frame.copy(),
            depth_frame,
            color_intrinsics,
            ocr,
            obb_data,
            args,
        )
        result["books"] = books
        result["ocr_priority_debug"] = getattr(args, "_ocr_priority_debug", None)
        result["ocr_early_stop_debug"] = ocr_build_debug

        set_state(result, "SELECT_TARGET_BOOK_OPTIONAL")
        selected_book_candidate = select_target_book_candidate(
            books,
            args.target_title,
            override_book_index=args.book_index,
            lock_book_index=args.lock_book_index,
            use_ocr_title_match=args.use_ocr_title_match,
        )
        result["selected_book_candidate"] = selected_book_candidate
        if selected_book_candidate is None:
            result["status"] = "no_valid_book_pose"
            result["error"] = "depth/tf valid mid pose를 가진 책이 없습니다."
            print("[BookSelect] depth/tf valid mid pose를 가진 책이 없습니다.")
        else:
            print_selected_book_pose(books, selected_book_candidate)
            save_target_book_lock(
                books,
                selected_book_candidate,
                args.target_title,
                allow_fallback_lock=args.allow_fallback_lock,
            )

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
