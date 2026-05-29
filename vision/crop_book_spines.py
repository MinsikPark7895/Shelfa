import cv2
import os
import json
import time
import numpy as np
from pathlib import Path
from datetime import datetime

os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_pir_api", "0")

from ultralytics import YOLO
from paddleocr import PaddleOCR


# ==============================
# 경로 설정
# ==============================
BASE_DIR = Path(__file__).resolve().parent

MODEL_PATH = str(BASE_DIR / "runs/obb/runs/obb/book_spine_v1/weights/best.pt")
IMAGE_PATH = "/home/user/130324_26_3.jpg"

OUTPUT_DIR = str(BASE_DIR / "crop_results_130324")
CROP_DIR = os.path.join(OUTPUT_DIR, "crops")
TITLE_CROP_DIR = os.path.join(OUTPUT_DIR, "title_crops")
JSON_PATH = os.path.join(OUTPUT_DIR, "ocr_results.json")
FRAME_ID = "gripper_camera"
COORDINATE_TYPE = "camera_frame"
OCR_TARGET_LONG_SIDE = 960
OCR_BENCHMARK_SIZES = [700, 960]


# ==============================
# 기본 유틸
# ==============================
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
    """
    OCR 결과를 제목 후보처럼 정리합니다.
    예: 사 물 인 터 넷 -> 사물인터넷
    """
    if not text:
        return ""

    text = clean_text(text)
    chars = list(text)
    result = []

    for i, ch in enumerate(chars):
        if ch == " ":
            prev_ch = chars[i - 1] if i > 0 else ""
            next_ch = chars[i + 1] if i + 1 < len(chars) else ""

            # 한글 사이 공백 제거
            if is_korean(prev_ch) and is_korean(next_ch):
                continue

        result.append(ch)

    text = "".join(result)
    text = " ".join(text.split())

    return text.strip()


def bbox_center(bbox):
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def bbox_size(bbox):
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    return max(xs) - min(xs), max(ys) - min(ys)


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


def make_book_payload(book_id, selected_title, det_conf, ocr_score, obb_info):
    center_px = obb_info["center_px"]

    return {
        "book_id": int(book_id),
        "title_candidate": selected_title,
        "confidence": {
            "detection": round(float(det_conf), 3),
            "ocr": round(float(ocr_score), 3),
        },
        "obb": obb_info,
        "target_point": {
            "type": "book_spine_center",
            "pixel": center_px,
            "camera_xyz_m": [None, None, None],
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


# ==============================
# OBB crop 관련
# ==============================
def order_points(pts):
    """
    OBB 4점을 top-left, top-right, bottom-right, bottom-left 순서로 정렬
    """
    rect = np.zeros((4, 2), dtype=np.float32)

    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)

    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]

    return rect


def normalize_spine_vertical(crop):
    """
    책등 crop을 기본적으로 세로로 긴 형태로 맞춤
    """
    h, w = crop.shape[:2]

    if w > h:
        crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)

    return crop


def crop_obb(image, points, padding=15):
    """
    YOLO OBB 4점 기준으로 책등을 반듯하게 펼쳐 crop
    """
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


# ==============================
# 제목 영역 분리
# ==============================
def extract_main_title_region(crop):
    """
    책등 crop 안에서 가장 큰 제목 영역처럼 보이는 부분을 분리합니다.
    OCR이 숫자/로고/출판사에 끌리지 않도록 큰 텍스트 덩어리를 따로 자릅니다.
    """
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

    # 세로로 떨어진 글자를 하나의 덩어리로 묶기 위한 팽창 커널
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


# ==============================
# OCR 전처리
# ==============================
def resize_for_ocr(image, target_long_side=900):
    h, w = image.shape[:2]
    long_side = max(h, w)

    if long_side >= target_long_side:
        return image

    scale = target_long_side / long_side
    new_w = int(w * scale)
    new_h = int(h * scale)

    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)


def preprocess_for_ocr(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    return gray


# ==============================
# OCR 결과 그룹화
# ==============================
def group_vertical_texts(ocr_results, crop_width=None, x_threshold=None):
    """
    세로 한 글자씩 잡힌 결과를 하나로 묶음.
    crop_width를 기준으로 x_threshold를 동적으로 계산합니다.
    """
    if x_threshold is None:
        x_threshold = int(crop_width * 0.15) if crop_width else 70

        # 너무 작거나 너무 커지는 것 방지
        x_threshold = max(20, min(x_threshold, 120))

    items = []

    for bbox, text, conf in ocr_results:
        text = clean_text(text)

        if not text:
            continue

        cx, cy = bbox_center(bbox)
        bw, bh = bbox_size(bbox)

        items.append({
            "text": text,
            "conf": float(conf),
            "cx": cx,
            "cy": cy,
            "w": bw,
            "h": bh,
        })

    if not items:
        return []

    items.sort(key=lambda x: x["cx"])

    columns = []

    for item in items:
        placed = False

        for col in columns:
            col_cx = sum(i["cx"] for i in col) / len(col)

            if abs(item["cx"] - col_cx) < x_threshold:
                col.append(item)
                placed = True
                break

        if not placed:
            columns.append([item])

    groups = []

    for col in columns:
        col.sort(key=lambda x: x["cy"])

        one_char_count = sum(len(i["text"]) == 1 for i in col)

        if one_char_count >= len(col) * 0.6:
            text = "".join(i["text"] for i in col)
        else:
            text = " ".join(i["text"] for i in col)

        text = normalize_korean_title_text(text)

        avg_conf = sum(i["conf"] for i in col) / len(col)

        groups.append({
            "text": text,
            "confidence": avg_conf,
            "count": len(col),
            "type": "vertical_group",
            "x_threshold": x_threshold,
        })

    groups.sort(key=lambda x: (len(x["text"]), x["confidence"]), reverse=True)

    return groups


def group_horizontal_texts(ocr_results, y_threshold=50):
    """
    가로로 잡힌 단어들을 줄 단위로 묶음.
    예: 사물 / 인터넷 -> 사물 인터넷
    """
    items = []

    for bbox, text, conf in ocr_results:
        text = clean_text(text)

        if not text:
            continue

        cx, cy = bbox_center(bbox)

        items.append({
            "text": text,
            "conf": float(conf),
            "cx": cx,
            "cy": cy,
        })

    if not items:
        return []

    items.sort(key=lambda x: x["cy"])

    lines = []

    for item in items:
        placed = False

        for line in lines:
            line_cy = sum(i["cy"] for i in line) / len(line)

            if abs(item["cy"] - line_cy) < y_threshold:
                line.append(item)
                placed = True
                break

        if not placed:
            lines.append([item])

    groups = []

    for line in lines:
        line.sort(key=lambda x: x["cx"])

        text = " ".join(i["text"] for i in line)
        text = normalize_korean_title_text(text)

        avg_conf = sum(i["conf"] for i in line) / len(line)

        groups.append({
            "text": text,
            "confidence": avg_conf,
            "count": len(line),
            "type": "horizontal_group",
        })

    groups.sort(key=lambda x: (len(x["text"]), x["confidence"]), reverse=True)

    return groups


def score_candidate(candidate):
    text = candidate["text"]
    conf = candidate["confidence"]
    count = candidate["count"]

    length_score = min(len(text) / 10, 1.0)
    group_score = min(count / 5, 1.0)

    # 제목 후보는 길이와 그룹 수를 조금 더 반영
    score = conf * 0.55 + length_score * 0.30 + group_score * 0.15

    return score


def run_ocr_on_crop(reader, crop, target_long_side=None):
    """
    PaddleOCR 기반 OCR.
    속도 개선 버전:
    1차: 원본, 90도만 OCR
    2차: 결과가 안 좋을 때만 270도, 180도 OCR
    """
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

            # PaddleOCR은 이미지 배열도 받을 수 있음
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

    # 1차 결과가 충분하면 fallback 생략
    if candidates:
        best = candidates[0]
        text_len = len(best["text"])
        score = float(best["score"])

        if text_len >= 2 and score >= 0.45:
            best["raw_by_rotation"] = raw_by_rotation
            return best

    # 1차 결과가 부족하면 2차 방향도 OCR
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
    ocr_result = run_ocr_on_crop(
        reader,
        crop,
        target_long_side=target_long_side
    )
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    return ocr_result, round(elapsed_ms, 1)


def benchmark_ocr_sizes(reader, crop, target_sizes):
    benchmark_results = []

    for target_size in target_sizes:
        start_time = time.perf_counter()
        ocr_result = run_ocr_on_crop(
            reader,
            crop,
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
            "result": ocr_result,
        })

    return benchmark_results


def make_one_line_summary(index, selected_title, det_conf, ocr_score, method):
    title = selected_title if selected_title else "인식 실패"

    return (
        f"{index}번 책 | "
        f"제목후보: {title} | "
        f"감지신뢰도: {det_conf:.2f} | "
        f"OCR점수: {ocr_score:.2f} | "
        f"방식: {method}"
    )


# ==============================
# main
# ==============================
def main():
    os.makedirs(CROP_DIR, exist_ok=True)
    os.makedirs(TITLE_CROP_DIR, exist_ok=True)

    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {MODEL_PATH}")

    if not os.path.exists(IMAGE_PATH):
        raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {IMAGE_PATH}")

    image = cv2.imread(IMAGE_PATH)

    if image is None:
        raise RuntimeError(f"이미지를 읽을 수 없습니다: {IMAGE_PATH}")

    image_name = Path(IMAGE_PATH).stem

    print("YOLO OBB 모델 로드 중...")
    model = YOLO(MODEL_PATH)

    print("PaddleOCR 초기화 중...")
    reader = PaddleOCR(
        lang="korean",
        use_textline_orientation=True,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        enable_mkldnn=False
    )
    print("PaddleOCR 준비 완료")

    print("책등 감지 중...")
    results = model.predict(
        image,
        conf=0.25,
        iou=0.5,
        verbose=False
    )

    vis = image.copy()

    if results[0].obb is None:
        print("감지된 책등이 없습니다.")
        return

    obb_data = results[0].obb
    print(f"감지된 책등 수: {len(obb_data)}")

    final_results = []

    for i, obb in enumerate(obb_data):
        points = obb.xyxyxyxy[0].cpu().numpy()
        det_conf = float(obb.conf[0].cpu().numpy())
        obb_info = compute_obb_properties(points)

        crop = crop_obb(image, points, padding=15)

        if crop is None:
            print(f"[{i}] crop 실패")
            continue

        crop_path = os.path.join(
            CROP_DIR,
            f"{image_name}_book_{i:02d}_conf_{det_conf:.2f}.jpg"
        )
        cv2.imwrite(crop_path, crop)

        # 속도 개선: 전체 책등 OCR은 생략
        full_ocr_result = None
        full_text = ""

        # 제목 영역 분리 후 OCR
        title_crop, title_box = extract_main_title_region(crop)

        title_crop_path = None
        title_ocr_result = None
        title_text = ""

        if title_crop is not None and title_crop.size > 0:
            title_crop_path = os.path.join(
                TITLE_CROP_DIR,
                f"{image_name}_book_{i:02d}_title_crop.jpg"
            )
            cv2.imwrite(title_crop_path, title_crop)

            original_ocr_result, original_elapsed_ms = run_timed_ocr(
                reader,
                title_crop,
                target_long_side=None
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
            recheck_elapsed_ms = None
            recheck_db_match = None

            if need_ocr_recheck(original_db_match):
                recheck_used = True
                print(f"[{i}] DB 매칭 불확실 -> 960 리사이즈 OCR 재확인")
                recheck_ocr_result, recheck_elapsed_ms = run_timed_ocr(
                    reader,
                    title_crop,
                    target_long_side=OCR_TARGET_LONG_SIDE
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
                selected_rotation = title_ocr_result["rotation"]
            elif recheck_db_match and recheck_db_match["status"] == "matched":
                title_ocr_result = recheck_ocr_result
                title_text = normalize_korean_title_text(title_ocr_result["text"])
                selected_title = normalize_korean_title_text(
                    recheck_db_match["matched_title"] or title_text
                )
                selected_score = float(title_ocr_result["score"])
                selected_method = "db_matched_recheck_960"
                selected_rotation = title_ocr_result["rotation"]
            else:
                original_score = float(original_ocr_result["score"])
                recheck_score = float(recheck_ocr_result["score"]) if recheck_ocr_result else -1.0

                if recheck_ocr_result and recheck_score > original_score:
                    title_ocr_result = recheck_ocr_result
                    title_text = normalize_korean_title_text(title_ocr_result["text"])
                    selected_title = title_text
                    selected_score = recheck_score
                    selected_method = "ocr_candidate_recheck_960"
                    selected_rotation = title_ocr_result["rotation"]
                else:
                    title_ocr_result = original_ocr_result
                    title_text = normalize_korean_title_text(title_ocr_result["text"])
                    selected_title = title_text
                    selected_score = original_score
                    selected_method = "ocr_candidate_original"
                    selected_rotation = title_ocr_result["rotation"]

            title_benchmark = []
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
                    "resize": OCR_TARGET_LONG_SIDE if recheck_ocr_result else None,
                    "elapsed_ms": recheck_elapsed_ms,
                    "score": round(float(recheck_ocr_result["score"]), 3) if recheck_ocr_result else None,
                    "rotation": recheck_ocr_result["rotation"] if recheck_ocr_result else "none",
                }
            }
        else:
            title_benchmark = []
            ocr_recheck = {
                "used": False,
                "reason": "not_found",
                "original": {
                    "text": "",
                    "resize": "original",
                    "elapsed_ms": None,
                    "score": 0.0,
                    "rotation": "none",
                },
                "recheck_960": {
                    "text": "",
                    "resize": None,
                    "elapsed_ms": None,
                    "score": None,
                    "rotation": "none",
                }
            }

            # 최종 제목 선택
            selected_title = ""
            selected_score = 0.0
            selected_method = "title_crop_failed"
            selected_rotation = "none"
            title_text = ""

        print(f"[{i}] 최종 제목: \"{selected_title}\" method={selected_method}")

        one_line = make_one_line_summary(
            index=i,
            selected_title=selected_title,
            det_conf=det_conf,
            ocr_score=selected_score,
            method=selected_method
        )

        item = {
            "index": i,
            "one_line": one_line,

            "selected_title": selected_title,
            "selected_method": selected_method,
            "selected_rotation": selected_rotation,
            "selected_score": round(selected_score, 3),

            "full_ocr_text": full_text,
            "full_ocr_confidence": 0.0,
            "full_ocr_score": 0.0,
            "full_ocr_rotation": "skipped",
            "full_ocr_type": "skipped",

            "title_crop_text": title_text,
            "title_crop_file": title_crop_path,
            "title_box": title_box,

            "crop_file": crop_path,
            "det_confidence": round(det_conf, 3),

            "raw_full_by_rotation": {},
            "raw_title_by_rotation": title_ocr_result["raw_by_rotation"] if title_ocr_result else {},
            "ocr_recheck": ocr_recheck,
            "ocr_benchmark": [
                {k: v for k, v in benchmark.items() if k != "result"}
                for benchmark in title_benchmark
            ],
            "vision_position": make_book_payload(
                book_id=i,
                selected_title=selected_title,
                det_conf=det_conf,
                ocr_score=selected_score,
                obb_info=obb_info
            ),
        }

        final_results.append(item)

        # 시각화
        pts_int = points.astype(np.int32)
        cv2.drawContours(vis, [pts_int], 0, (0, 255, 0), 2)

        cx = int(points[:, 0].mean())
        cy = int(points[:, 1].mean())

        cv2.putText(
            vis,
            f"#{i} {selected_title[:10]}",
            (cx, cy),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2
        )

        print("-" * 60)
        print(one_line)
        print(f"    전체 OCR: {full_text}")
        print(f"    제목 OCR: {title_text}")
        if title_benchmark:
            for benchmark in title_benchmark:
                bench_text = benchmark["text"] if benchmark["text"] else "인식 실패"
                print(
                    f"    OCR {benchmark['target_long_side']}: "
                    f"{bench_text} | score={benchmark['score']:.2f} | "
                    f"conf={benchmark['confidence']:.2f} | "
                    f"rot={benchmark['rotation']} | "
                    f"time={benchmark['elapsed_ms']:.1f}ms"
                )
        print(f"    crop 저장: {crop_path}")
        print(f"    title crop 저장: {title_crop_path}")

    vis_path = os.path.join(OUTPUT_DIR, f"{image_name}_detected_ocr.jpg")
    cv2.imwrite(vis_path, vis)

    json_data = {
        "timestamp": datetime.now().isoformat(),
        "image_path": IMAGE_PATH,
        "model_path": MODEL_PATH,
        "frame_id": FRAME_ID,
        "coordinate_type": COORDINATE_TYPE,
        "total_books": len(final_results),
        "books": [item["vision_position"] for item in final_results],
        "results": final_results,
    }

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    print("\n완료")
    print(f"crop 폴더: {CROP_DIR}")
    print(f"title crop 폴더: {TITLE_CROP_DIR}")
    print(f"OCR JSON: {JSON_PATH}")
    print(f"시각화 이미지: {vis_path}")


if __name__ == "__main__":
    main()
