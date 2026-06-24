import cv2
import os
import json
import time
import numpy as np
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_pir_api", "0")

from ultralytics import YOLO
from paddleocr import PaddleOCR

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from geometry_msgs.msg import PointStamped, PoseStamped
from cv_bridge import CvBridge
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import Buffer, TransformException, TransformListener
import tf2_geometry_msgs  # noqa: F401 - PointStamped/PoseStamped TF 변환 등록용

try:
    from dsr_gripper_tcp_interfaces.srv import SetPosition
except ImportError:
    SetPosition = None

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MODEL_REL_PATH = Path("runs/obb/runs/obb/book_spine_v1/weights/best.pt")


def resolve_model_path():
    candidates = []

    env_path = os.environ.get("BOOK_SPINE_MODEL_PATH")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    candidates.append(PACKAGE_ROOT / MODEL_REL_PATH)
    candidates.append(Path.cwd() / MODEL_REL_PATH)

    for ancestor in Path(__file__).resolve().parents:
        candidates.append(ancestor / MODEL_REL_PATH)
        candidates.append(ancestor / "src" / "doosan_realsense_handeye" / MODEL_REL_PATH)
        candidates.append(ancestor / "src" / "dakae_e0509_servo" / MODEL_REL_PATH)

    seen = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        candidate_str = str(candidate)
        if candidate_str in seen:
            continue
        seen.add(candidate_str)
        if candidate.exists():
            return candidate_str

    return str(PACKAGE_ROOT / MODEL_REL_PATH)


MODEL_PATH = resolve_model_path()

OUTPUT_DIR = "./realtime_results"
CROP_DIR = os.path.join(OUTPUT_DIR, "crops")
TITLE_CROP_DIR = os.path.join(OUTPUT_DIR, "title_crops")
JSON_PATH = os.path.join(OUTPUT_DIR, "realtime_ocr_results.json")
ARUCO_INIT_JSON_PATH = os.path.join(OUTPUT_DIR, "aruco_initial_pose.json")
FRAME_ID = "camera_color_optical_frame"
COORDINATE_TYPE = "camera_frame"
COORDINATE_UNIT = "meter"
OCR_TARGET_LONG_SIDE = 960

YOLO_CONF = 0.75
YOLO_IOU = 0.5
DISPLAY_CONF_THRESHOLD = 0.75
OCR_MIN_SCORE_THRESHOLD = 0.45
BOOK_SPINE_MIN_CONF = 0.50
BOOK_SPINE_MIN_SHORT_SIDE_PX = 8.0
BOOK_SPINE_MIN_LONG_SIDE_PX = 40.0
BOOK_SPINE_MIN_ASPECT_RATIO = 2.0
BOOK_SPINE_MAX_ASPECT_RATIO = 25.0

ARUCO_DICT_NAME = "DICT_4X4_50"
ARUCO_TARGET_ID = 0
ARUCO_MARKER_LENGTH_M = 0.05

ROBOT_NAMESPACE = "/dsr01"
BASE_FRAME = "base_link"
CAMERA_FRAME = FRAME_ID
TARGET_POSE_TOPIC = "/book_pick_target_pose"
AUTO_MOVE_ENABLED = False
AUTO_OCR_ON_TARGET = False
PRE_GRASP_OFFSET_M = 0.08
BOOK_TOP_OFFSET_M = 0.03
MAX_MOVE_DISTANCE_M = 0.30
MIN_TARGET_DEPTH_M = 0.20
MAX_TARGET_DEPTH_M = 1.20
APPROACH_AXIS = "x"
APPROACH_SIGN = -1
PRE_GRASP_ORIENTATION_XYZW = [0.0, 0.0, 0.0, 1.0]
GRIPPER_CONTROL_ENABLED = False
GRIPPER_SERVICE_NAME = "/gripper_service/set_position"
GRIPPER_OPEN_POSITION = 0
GRIPPER_CLOSE_POSITION = 500
GRIPPER_TIMEOUT_SEC = 5.0
DEFAULT_COLOR_IMAGE_TOPIC = "/camera/camera/color/image_raw"
DEFAULT_DEPTH_IMAGE_TOPIC = "/camera/camera/aligned_depth_to_color/image_raw"
DEFAULT_CAMERA_INFO_TOPIC = "/camera/camera/color/camera_info"
DEFAULT_DEPTH_SCALE_M = 0.001


@dataclass
class CameraIntrinsics:
    width: int
    height: int
    fx: float
    fy: float
    ppx: float
    ppy: float
    coeffs: list


class DepthImageFrame:
    def __init__(self, image_array, encoding, depth_scale_m=DEFAULT_DEPTH_SCALE_M):
        self._image = np.asarray(image_array)
        self.encoding = str(encoding or "").lower()
        self.depth_scale_m = float(depth_scale_m)

    def get_height(self):
        return int(self._image.shape[0])

    def get_width(self):
        return int(self._image.shape[1])

    def get_distance(self, x, y):
        if self._image.size == 0:
            return 0.0

        h = self.get_height()
        w = self.get_width()
        xx = int(min(max(int(x), 0), w - 1))
        yy = int(min(max(int(y), 0), h - 1))
        value = self._image[yy, xx]

        if value is None:
            return 0.0

        try:
            depth_value = float(value)
        except (TypeError, ValueError):
            return 0.0

        if not np.isfinite(depth_value) or depth_value <= 0.0:
            return 0.0

        if "32f" in self.encoding or "float" in self.encoding:
            return depth_value

        return depth_value * self.depth_scale_m


def camera_info_to_intrinsics(camera_info_msg):
    return CameraIntrinsics(
        width=int(camera_info_msg.width),
        height=int(camera_info_msg.height),
        fx=float(camera_info_msg.k[0]),
        fy=float(camera_info_msg.k[4]),
        ppx=float(camera_info_msg.k[2]),
        ppy=float(camera_info_msg.k[5]),
        coeffs=[float(value) for value in camera_info_msg.d],
    )


class RealSenseTopicReader(Node):
    def __init__(self):
        super().__init__("realsense_topic_reader")
        self.declare_parameter("color_image_topic", DEFAULT_COLOR_IMAGE_TOPIC)
        self.declare_parameter("depth_image_topic", DEFAULT_DEPTH_IMAGE_TOPIC)
        self.declare_parameter("camera_info_topic", DEFAULT_CAMERA_INFO_TOPIC)
        self.declare_parameter("depth_scale_m", DEFAULT_DEPTH_SCALE_M)

        self.color_image_topic = str(self.get_parameter("color_image_topic").value)
        self.depth_image_topic = str(self.get_parameter("depth_image_topic").value)
        self.camera_info_topic = str(self.get_parameter("camera_info_topic").value)
        self.depth_scale_m = float(self.get_parameter("depth_scale_m").value)

        self.bridge = CvBridge()
        self.latest_frame = None
        self.latest_depth_frame = None
        self.latest_color_msg = None
        self.latest_depth_msg = None
        self.latest_camera_info = None
        self.latest_intrinsics = None

        self.create_subscription(Image, self.color_image_topic, self._on_color_image, 10)
        self.create_subscription(Image, self.depth_image_topic, self._on_depth_image, 10)
        self.create_subscription(CameraInfo, self.camera_info_topic, self._on_camera_info, 10)

    def _on_color_image(self, msg):
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().warn(f"Failed to convert color image: {exc}")
            return

        self.latest_color_msg = msg
        self.latest_frame = frame

    def _on_depth_image(self, msg):
        try:
            depth_array = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        except Exception as exc:
            self.get_logger().warn(f"Failed to convert depth image: {exc}")
            return

        self.latest_depth_msg = msg
        self.latest_depth_frame = DepthImageFrame(
            depth_array,
            encoding=msg.encoding,
            depth_scale_m=self.depth_scale_m,
        )

    def _on_camera_info(self, msg):
        self.latest_camera_info = msg
        self.latest_intrinsics = camera_info_to_intrinsics(msg)

    def wait_for_ready(self, require_depth=True, timeout_sec=10.0):
        deadline = time.monotonic() + float(timeout_sec)
        while rclpy.ok() and time.monotonic() < deadline:
            if self.latest_frame is not None and self.latest_intrinsics is not None:
                if not require_depth or self.latest_depth_frame is not None:
                    return True
            rclpy.spin_once(self, timeout_sec=0.1)
        return (
            self.latest_frame is not None
            and self.latest_intrinsics is not None
            and (not require_depth or self.latest_depth_frame is not None)
        )

    def snapshot(self):
        return self.latest_frame, self.latest_depth_frame, self.latest_color_msg

    def stop(self):
        return None


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

    if hasattr(intrinsics, "fx") and hasattr(intrinsics, "fy"):
        fx = float(intrinsics.fx)
        fy = float(intrinsics.fy)
        ppx = float(intrinsics.ppx)
        ppy = float(intrinsics.ppy)
    elif hasattr(intrinsics, "k"):
        fx = float(intrinsics.k[0])
        fy = float(intrinsics.k[4])
        ppx = float(intrinsics.k[2])
        ppy = float(intrinsics.k[5])
    else:
        return [None, None, None]

    x = (float(px) - ppx) / fx * float(depth_m)
    y = (float(py) - ppy) / fy * float(depth_m)
    z = float(depth_m)

    return [round(float(x), 3), round(float(y), 3), round(float(z), 3)]


def is_valid_camera_xyz(camera_xyz_m):
    return (
        camera_xyz_m is not None
        and len(camera_xyz_m) == 3
        and all(v is not None for v in camera_xyz_m)
    )


def is_finite_xyz(xyz):
    return (
        is_valid_camera_xyz(xyz)
        and all(np.isfinite(float(v)) for v in xyz)
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


def get_ocr_rotation_plan(crop, allow_upright_rotations=False):
    primary_rotations = [
        ("rot90", cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)),
        ("rot270", cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)),
    ]

    fallback_rotations = []
    if allow_upright_rotations:
        fallback_rotations = [
            ("vertical_original", crop),
            ("rot180", cv2.rotate(crop, cv2.ROTATE_180)),
        ]

    return primary_rotations, fallback_rotations


def run_paddle_ocr_on_crop(
    ocr,
    crop,
    source_name="unknown",
    show_debug=False,
    target_long_side=None,
    allow_upright_rotations=False,
):
    """
    속도 개선 버전:
    기본: 90도, 270도만 사용
    옵션: upright/180도 추가
    """
    rotations_primary, rotations_fallback = get_ocr_rotation_plan(
        crop,
        allow_upright_rotations=allow_upright_rotations,
    )

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

    if rotations_fallback:
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


def run_timed_ocr(
    ocr,
    crop,
    source_name="unknown",
    show_debug=False,
    target_long_side=None,
    allow_upright_rotations=False,
):
    start_time = time.perf_counter()
    ocr_result = run_paddle_ocr_on_crop(
        ocr,
        crop,
        source_name=source_name,
        show_debug=show_debug,
        target_long_side=target_long_side,
        allow_upright_rotations=allow_upright_rotations,
    )
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
    return ocr_result, round(elapsed_ms, 1)


def save_json(
    results,
    trigger_info=None,
    show_log=False,
    robot_targets=None,
    latest_robot_target=None
):
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

    if robot_targets is not None:
        data["robot_targets"] = robot_targets

    if latest_robot_target is not None:
        data["latest_robot_target"] = latest_robot_target

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if show_log:
        print("[Saved JSON]")
        print(json.dumps(data, ensure_ascii=False, indent=2))


def get_aruco_dictionary(dict_name):
    aruco = cv2.aruco

    dict_map = {
        "DICT_4X4_50": aruco.DICT_4X4_50,
        "DICT_4X4_100": aruco.DICT_4X4_100,
        "DICT_5X5_50": aruco.DICT_5X5_50,
        "DICT_5X5_100": aruco.DICT_5X5_100,
        "DICT_6X6_50": aruco.DICT_6X6_50,
        "DICT_6X6_100": aruco.DICT_6X6_100,
    }

    return aruco.getPredefinedDictionary(dict_map[dict_name])


def make_camera_matrix_from_realsense_intrinsics(intrinsics):
    if intrinsics is None:
        raise ValueError("Camera intrinsics are not available")

    if hasattr(intrinsics, "fx") and hasattr(intrinsics, "fy"):
        fx = float(intrinsics.fx)
        fy = float(intrinsics.fy)
        ppx = float(intrinsics.ppx)
        ppy = float(intrinsics.ppy)
        coeffs = getattr(intrinsics, "coeffs", [])
    elif hasattr(intrinsics, "k"):
        fx = float(intrinsics.k[0])
        fy = float(intrinsics.k[4])
        ppx = float(intrinsics.k[2])
        ppy = float(intrinsics.k[5])
        coeffs = getattr(intrinsics, "d", [])
    else:
        raise TypeError(f"Unsupported intrinsics type: {type(intrinsics)!r}")

    camera_matrix = np.array([
        [fx, 0.0, ppx],
        [0.0, fy, ppy],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)
    dist_coeffs = np.array(coeffs, dtype=np.float64).reshape(-1)
    return camera_matrix, dist_coeffs


def rvec_tvec_to_matrix(rvec, tvec):
    R, _ = cv2.Rodrigues(rvec)

    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = R
    T[:3, 3] = np.array(tvec, dtype=np.float64).reshape(3)

    return T


def detect_aruco_pose(frame, color_intrinsics):
    """
    RealSense RGB frame에서 ArUco marker를 인식하고,
    camera frame 기준 marker pose를 반환합니다.
    """
    aruco = cv2.aruco
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    dictionary = get_aruco_dictionary(ARUCO_DICT_NAME)

    if hasattr(aruco, "DetectorParameters"):
        parameters = aruco.DetectorParameters()
    else:
        parameters = aruco.DetectorParameters_create()

    corners, ids, _ = aruco.detectMarkers(
        gray,
        dictionary,
        parameters=parameters
    )

    result = {
        "found": False,
        "marker_id": None,
        "rvec": None,
        "tvec_m": None,
        "T_camera_marker": None,
        "corners": None,
    }

    if ids is None or len(ids) == 0:
        return result

    ids_flat = ids.flatten()

    target_index = None
    for idx, marker_id in enumerate(ids_flat):
        if int(marker_id) == int(ARUCO_TARGET_ID):
            target_index = idx
            break

    if target_index is None:
        return result

    camera_matrix, dist_coeffs = make_camera_matrix_from_realsense_intrinsics(
        color_intrinsics
    )

    target_corners = [corners[target_index]]

    rvecs, tvecs, _ = aruco.estimatePoseSingleMarkers(
        target_corners,
        ARUCO_MARKER_LENGTH_M,
        camera_matrix,
        dist_coeffs
    )

    rvec = rvecs[0][0]
    tvec = tvecs[0][0]
    T_camera_marker = rvec_tvec_to_matrix(rvec, tvec)

    result.update({
        "found": True,
        "marker_id": int(ARUCO_TARGET_ID),
        "rvec": [round(float(v), 6) for v in rvec],
        "tvec_m": [round(float(v), 4) for v in tvec],
        "T_camera_marker": T_camera_marker.tolist(),
        "corners": target_corners,
    })

    return result


def draw_aruco_pose(vis, aruco_pose, color_intrinsics):
    if not aruco_pose["found"]:
        cv2.putText(
            vis,
            "ArUco: not found",
            (20, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2
        )
        return vis

    aruco = cv2.aruco

    camera_matrix, dist_coeffs = make_camera_matrix_from_realsense_intrinsics(
        color_intrinsics
    )

    corners = aruco_pose["corners"]
    rvec = np.array(aruco_pose["rvec"], dtype=np.float64)
    tvec = np.array(aruco_pose["tvec_m"], dtype=np.float64)

    aruco.drawDetectedMarkers(vis, corners)

    try:
        cv2.drawFrameAxes(
            vis,
            camera_matrix,
            dist_coeffs,
            rvec,
            tvec,
            ARUCO_MARKER_LENGTH_M * 0.7
        )
    except Exception:
        pass

    x, y, z = aruco_pose["tvec_m"]

    cv2.putText(
        vis,
        f"ArUco ID:{aruco_pose['marker_id']} xyz(camera): {x:.3f}, {y:.3f}, {z:.3f}m",
        (20, 60),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 255, 255),
        2
    )

    return vis


def save_aruco_initial_pose(aruco_pose):
    data = {
        "timestamp": datetime.now().isoformat(),
        "frame_id": FRAME_ID,
        "coordinate_type": "camera_frame",
        "unit": "meter",
        "aruco": {
            "dict": ARUCO_DICT_NAME,
            "target_id": ARUCO_TARGET_ID,
            "marker_length_m": ARUCO_MARKER_LENGTH_M,
            "tvec_m": aruco_pose["tvec_m"],
            "rvec": aruco_pose["rvec"],
            "T_camera_marker": aruco_pose["T_camera_marker"],
        },
        "meaning": "This pose represents marker pose relative to the gripper camera frame."
    }

    with open(ARUCO_INIT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("[ArUco Init Saved]")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"ArUco 초기 위치 저장: {ARUCO_INIT_JSON_PATH}")


class BookVisionRobotNode(Node):
    """
    비전 코드 안에서 함께 돌리는 ROS2 노드.
    - camera_color_optical_frame 기준 3D point를 base frame으로 변환
    - RViz 확인용 pre_grasp PoseStamped publish
    - 실제 이동 함수는 안전을 위해 기본 비활성화
    """

    def __init__(self):
        super().__init__("book_vision_robot_node")
        self.tf_buffer = Buffer()
        try:
            self.tf_listener = TransformListener(
                self.tf_buffer,
                self,
            )
        except TypeError:
            self.tf_listener = TransformListener(self.tf_buffer, self)
        self.target_pose_pub = self.create_publisher(
            PoseStamped,
            TARGET_POSE_TOPIC,
            10
        )
        self.last_published_pose = None
        self.gripper_client = None
        if SetPosition is not None:
            self.gripper_client = self.create_client(
                SetPosition,
                GRIPPER_SERVICE_NAME
            )

    def destroy_node(self):
        tf_listener = getattr(self, "tf_listener", None)
        if tf_listener is not None and hasattr(tf_listener, "unregister"):
            try:
                tf_listener.unregister()
            except Exception as exc:  # noqa: BLE001
                print(f"[ROS2 TF] TransformListener unregister failed: {exc}")
        return super().destroy_node()

    def transform_camera_xyz_to_base(self, camera_xyz_m):
        if not is_finite_xyz(camera_xyz_m):
            print("[ROS2 TF] camera_xyz_m invalid")
            return None

        point = PointStamped()
        # 최신 TF를 사용해 미래 시점 extrapolation 오류를 피한다.
        point.header.stamp = Time().to_msg()
        point.header.frame_id = CAMERA_FRAME
        point.point.x = float(camera_xyz_m[0])
        point.point.y = float(camera_xyz_m[1])
        point.point.z = float(camera_xyz_m[2])

        try:
            transformed = self.tf_buffer.transform(
                point,
                BASE_FRAME,
                timeout=Duration(seconds=0.5)
            )
        except TransformException as exc:
            print(f"[ROS2 TF] {CAMERA_FRAME} -> {BASE_FRAME} 변환 실패: {exc}")
            return None

        return [
            round(float(transformed.point.x), 4),
            round(float(transformed.point.y), 4),
            round(float(transformed.point.z), 4),
        ]

    def publish_target_pose(self, pose_stamped):
        pose_stamped.header.stamp = self.get_clock().now().to_msg()
        self.target_pose_pub.publish(pose_stamped)
        self.last_published_pose = pose_stamped
        print(f"[ROS2 Publish] target pose published: {TARGET_POSE_TOPIC}")

    def move_to_pre_grasp(self, pose_stamped):
        if not AUTO_MOVE_ENABLED:
            print("AUTO_MOVE_ENABLED=False라 실제 이동하지 않음")
            return False

        if not is_pose_finite(pose_stamped):
            print("[Robot Move] pose에 NaN/Inf가 있어 이동하지 않음")
            return False

        if self.last_published_pose is not None:
            distance = pose_distance_m(self.last_published_pose, pose_stamped)
            if distance > MAX_MOVE_DISTANCE_M:
                print(
                    f"[Robot Move] 이동 후보 거리 {distance:.3f}m > "
                    f"{MAX_MOVE_DISTANCE_M:.3f}m, 이동 차단"
                )
                return False

        return call_doosan_move_pose(pose_stamped)

    def move_gripper(self, position):
        if not GRIPPER_CONTROL_ENABLED:
            print("GRIPPER_CONTROL_ENABLED=False라 그리퍼를 움직이지 않음")
            return False

        if self.gripper_client is None:
            print("[Gripper] dsr_gripper_tcp_interfaces/SetPosition client가 없습니다.")
            return False

        if not self.gripper_client.wait_for_service(timeout_sec=1.0):
            print(f"[Gripper] {GRIPPER_SERVICE_NAME} 서비스가 없습니다.")
            return False

        req = SetPosition.Request()
        req.position = int(position)
        req.timeout_sec = float(GRIPPER_TIMEOUT_SEC)
        future = self.gripper_client.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=GRIPPER_TIMEOUT_SEC)

        if not future.done() or future.result() is None:
            print("[Gripper] 응답 없음")
            return False

        res = future.result()
        print(
            f"[Gripper] position={position} success={res.success} "
            f"msg={res.message} present={res.present_position}"
        )
        return bool(res.success)

    def open_gripper(self):
        return self.move_gripper(GRIPPER_OPEN_POSITION)

    def close_gripper(self):
        return self.move_gripper(GRIPPER_CLOSE_POSITION)


def compute_book_top_pixel_from_obb(points):
    """
    OBB 4점에서 긴 축을 찾고, 이미지 y값이 작은 쪽을 책 상단으로 본다.
    반환 좌표는 depth lookup에 바로 쓰기 좋게 float pixel로 유지한다.
    """
    rect = order_points(np.array(points, dtype=np.float32))
    tl, tr, br, bl = rect

    edge_top = (tl, tr)
    edge_bottom = (bl, br)
    width = float((np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2.0)
    height = float((np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2.0)

    if height >= width:
        end_a = (tl + tr) / 2.0
        end_b = (bl + br) / 2.0
    else:
        end_a = (tl + bl) / 2.0
        end_b = (tr + br) / 2.0
        edge_top = (tl, bl)
        edge_bottom = (tr, br)

    if end_a[1] <= end_b[1]:
        top_center = end_a
        bottom_center = end_b
    else:
        top_center = end_b
        bottom_center = end_a
        edge_top, edge_bottom = edge_bottom, edge_top

    long_vec = bottom_center - top_center
    angle_deg = float(np.degrees(np.arctan2(long_vec[1], long_vec[0])))
    center = rect.mean(axis=0)

    return {
        "top_center_px": [
            round(float(top_center[0]), 1),
            round(float(top_center[1]), 1),
        ],
        "bottom_center_px": [
            round(float(bottom_center[0]), 1),
            round(float(bottom_center[1]), 1),
        ],
        "center_px": [
            round(float(center[0]), 1),
            round(float(center[1]), 1),
        ],
        "top_edge_px": [
            [round(float(edge_top[0][0]), 1), round(float(edge_top[0][1]), 1)],
            [round(float(edge_top[1][0]), 1), round(float(edge_top[1][1]), 1)],
        ],
        "long_axis_angle_deg": round(angle_deg, 1),
    }


def compute_book_top_camera_xyz(depth_frame, color_intrinsics, points):
    top_info = compute_book_top_pixel_from_obb(points)
    top_px = top_info["top_center_px"]
    camera_xyz_m = deproject_pixel_to_camera_xyz(
        depth_frame,
        color_intrinsics,
        top_px[0],
        top_px[1]
    )

    return top_info, camera_xyz_m, is_valid_camera_xyz(camera_xyz_m)


def make_pre_grasp_pose(base_xyz_m):
    pose = PoseStamped()
    pose.header.frame_id = BASE_FRAME

    position = {
        "x": float(base_xyz_m[0]),
        "y": float(base_xyz_m[1]),
        "z": float(base_xyz_m[2]) + BOOK_TOP_OFFSET_M,
    }

    if APPROACH_AXIS not in position:
        raise ValueError(f"지원하지 않는 APPROACH_AXIS: {APPROACH_AXIS}")

    position[APPROACH_AXIS] += float(APPROACH_SIGN) * PRE_GRASP_OFFSET_M

    pose.pose.position.x = position["x"]
    pose.pose.position.y = position["y"]
    pose.pose.position.z = position["z"]
    pose.pose.orientation.x = PRE_GRASP_ORIENTATION_XYZW[0]
    pose.pose.orientation.y = PRE_GRASP_ORIENTATION_XYZW[1]
    pose.pose.orientation.z = PRE_GRASP_ORIENTATION_XYZW[2]
    pose.pose.orientation.w = PRE_GRASP_ORIENTATION_XYZW[3]

    return pose


def pose_to_dict(pose_stamped):
    pose = pose_stamped.pose
    return {
        "position": {
            "x": round(float(pose.position.x), 4),
            "y": round(float(pose.position.y), 4),
            "z": round(float(pose.position.z), 4),
        },
        "orientation": {
            "x": round(float(pose.orientation.x), 6),
            "y": round(float(pose.orientation.y), 6),
            "z": round(float(pose.orientation.z), 6),
            "w": round(float(pose.orientation.w), 6),
        }
    }


def is_pose_finite(pose_stamped):
    values = [
        pose_stamped.pose.position.x,
        pose_stamped.pose.position.y,
        pose_stamped.pose.position.z,
        pose_stamped.pose.orientation.x,
        pose_stamped.pose.orientation.y,
        pose_stamped.pose.orientation.z,
        pose_stamped.pose.orientation.w,
    ]
    return all(np.isfinite(float(v)) for v in values)


def pose_distance_m(pose_a, pose_b):
    a = pose_a.pose.position
    b = pose_b.pose.position
    return float(np.linalg.norm([
        float(a.x) - float(b.x),
        float(a.y) - float(b.y),
        float(a.z) - float(b.z),
    ]))


def call_doosan_move_pose(pose_stamped):
    """
    실제 로봇 이동 연결 지점.

    Doosan ROS2 서비스 이름/타입은 설치 버전과 namespace에 따라 다를 수 있다.
    먼저 아래 명령으로 실제 인터페이스를 확인한 뒤 이 함수를 채운다.

    ros2 service list | grep move
    ros2 service list | grep motion
    ros2 service type /dsr01/motion/move_line
    ros2 interface show dsr_msgs2/srv/MoveLine
    """
    print("[Robot Move] TODO: Doosan move_line/MoveIt2 호출부를 환경에 맞게 연결해야 합니다.")
    print(json.dumps(pose_to_dict(pose_stamped), ensure_ascii=False, indent=2))
    return False


def make_robot_target_payload(
    selected_book,
    title_candidate,
    top_info,
    camera_xyz_m,
    base_xyz_m,
    pre_grasp_pose
):
    return {
        "timestamp": datetime.now().isoformat(),
        "base_frame": BASE_FRAME,
        "camera_frame": CAMERA_FRAME,
        "robot_namespace": ROBOT_NAMESPACE,
        "target_type": "book_top_pre_grasp",
        "book_index": int(selected_book["index"]),
        "book_detection_confidence": round(float(selected_book["confidence"]), 3),
        "title_candidate": title_candidate,
        "book_top_pixel": top_info["top_center_px"],
        "book_top_camera_xyz_m": camera_xyz_m,
        "book_top_base_xyz_m": base_xyz_m,
        "book_top_geometry": top_info,
        "pre_grasp_pose_base": pose_to_dict(pre_grasp_pose),
        "auto_move_enabled": bool(AUTO_MOVE_ENABLED),
        "safety": {
            "pre_grasp_offset_m": PRE_GRASP_OFFSET_M,
            "book_top_offset_m": BOOK_TOP_OFFSET_M,
            "max_move_distance_m": MAX_MOVE_DISTANCE_M,
            "min_target_depth_m": MIN_TARGET_DEPTH_M,
            "max_target_depth_m": MAX_TARGET_DEPTH_M,
            "approach_axis": APPROACH_AXIS,
            "approach_sign": APPROACH_SIGN,
        }
    }


def get_target_title_candidate(ocr, frame, selected_book):
    if not AUTO_OCR_ON_TARGET:
        return "not_checked"

    crop = crop_obb(frame, selected_book["points"], padding=15)
    if crop is None:
        return "ocr_crop_failed"

    title_crop, _ = extract_main_title_region(crop)
    ocr_input = title_crop if title_crop is not None and title_crop.size > 0 else crop

    ocr_result, elapsed_ms = run_timed_ocr(
        ocr,
        ocr_input,
        source_name="target_book",
        show_debug=False,
        target_long_side=None
    )
    title = normalize_korean_title_text(ocr_result["text"])
    print(
        f"[Target OCR] title=\"{title}\" "
        f"score={ocr_result['score']:.2f} elapsed={elapsed_ms:.1f}ms"
    )
    return title if title else "ocr_not_detected"


def build_and_publish_robot_target(
    robot_node,
    latest_frame,
    latest_depth_frame,
    color_intrinsics,
    latest_obb_data,
    latest_aruco_pose,
    ocr=None
):
    if not latest_aruco_pose.get("found"):
        print("[Target] ArUco marker가 보이지 않아 목표 pose를 만들지 않음")
        return None, None

    if latest_frame is None or latest_depth_frame is None:
        print("[Target] 최신 frame/depth가 없어 목표 pose를 만들지 않음")
        return None, None

    if not latest_obb_data:
        print("[Target] 인식된 책등이 없어 목표 pose를 만들지 않음")
        return None, None

    selected_book = max(latest_obb_data, key=lambda item: item["confidence"])
    det_conf = float(selected_book["confidence"])
    if det_conf < DISPLAY_CONF_THRESHOLD:
        print(f"[Target] detection confidence {det_conf:.2f}가 기준보다 낮음")
        return None, None

    top_info, camera_xyz_m, depth_valid = compute_book_top_camera_xyz(
        latest_depth_frame,
        color_intrinsics,
        selected_book["points"]
    )

    if not depth_valid:
        print(f"[Target] 책 상단 depth invalid: pixel={top_info['top_center_px']}")
        return None, None

    depth_m = float(camera_xyz_m[2])
    if depth_m < MIN_TARGET_DEPTH_M or depth_m > MAX_TARGET_DEPTH_M:
        print(
            f"[Target] camera z={depth_m:.3f}m가 안전 범위 "
            f"{MIN_TARGET_DEPTH_M:.2f}~{MAX_TARGET_DEPTH_M:.2f}m 밖이라 중단"
        )
        return None, None

    for _ in range(3):
        rclpy.spin_once(robot_node, timeout_sec=0.02)

    base_xyz_m = robot_node.transform_camera_xyz_to_base(camera_xyz_m)
    if base_xyz_m is None:
        return None, None

    pre_grasp_pose = make_pre_grasp_pose(base_xyz_m)
    if not is_pose_finite(pre_grasp_pose):
        print("[Target] pre_grasp pose에 NaN/Inf가 있어 publish하지 않음")
        return None, None

    title_candidate = get_target_title_candidate(ocr, latest_frame, selected_book)
    payload = make_robot_target_payload(
        selected_book=selected_book,
        title_candidate=title_candidate,
        top_info=top_info,
        camera_xyz_m=camera_xyz_m,
        base_xyz_m=base_xyz_m,
        pre_grasp_pose=pre_grasp_pose
    )

    robot_node.publish_target_pose(pre_grasp_pose)

    print("[Target Candidate]")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    return payload, pre_grasp_pose


def init_realsense(width=1280, height=720, fps=30):
    """Subscribe to the external RealSense node instead of opening the device here."""
    if not rclpy.ok():
        rclpy.init(args=None)

    reader = RealSenseTopicReader()
    ready = reader.wait_for_ready(require_depth=True, timeout_sec=10.0)
    if not ready:
        reader.destroy_node()
        raise RuntimeError(
            "Timed out waiting for RealSense topics. "
            f"Expected color={reader.color_image_topic}, depth={reader.depth_image_topic}, "
            f"camera_info={reader.camera_info_topic}"
        )

    print(
        "Subscribed to RealSense topics: "
        f"color={reader.color_image_topic}, "
        f"depth={reader.depth_image_topic}, "
        f"camera_info={reader.camera_info_topic}"
    )
    return reader, None, reader.latest_intrinsics


def get_realsense_frames(pipeline, align):
    """Return the latest subscribed color/depth frames."""
    if pipeline is None:
        return None, None, None
    return pipeline.snapshot()


def check_ocr_trigger(key=None):
    """
    현재는 s 키가 눌렸을 때 OCR 실행 요청으로 처리합니다.
    """
    return key == ord("s")


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
                print(f"[{i}] 원본 OCR 무검출 -> 추가 재확인 없이 후보 제외")

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

                if db_match_original["status"] == "matched":
                    title_ocr_result = ocr_result_original
                    selected_title = normalize_korean_title_text(
                        db_match_original["matched_title"] or original_text
                    )
                    selected_score = float(title_ocr_result["score"])
                    selected_method = "db_matched_original_ocr"
                else:
                    title_ocr_result = ocr_result_original
                    selected_title = original_text
                    selected_score = float(ocr_result_original["score"])
                    selected_method = "ocr_candidate_original"

            selected_rotation = title_ocr_result["rotation"]
            selected_confidence = float(title_ocr_result["confidence"])
            raw_by_rotation = title_ocr_result["raw_by_rotation"]
            ocr_recheck = {
                "used": False,
                "reason": "disabled",
                "original": {
                    "text": original_text,
                    "resize": "original",
                    "elapsed_ms": elapsed_original_ms,
                    "db_elapsed_ms": db_elapsed_original_ms,
                    "score": round(float(ocr_result_original["score"]), 3),
                    "rotation": ocr_result_original["rotation"]
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

    pipeline = None
    if not rclpy.ok():
        rclpy.init(args=None)
    robot_node = BookVisionRobotNode()

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

    try:
        pipeline, align, color_intrinsics = init_realsense(width=1280, height=720, fps=30)
    except Exception:
        robot_node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        raise

    print("\nRealSense 실시간 실행 시작")
    print("s 키: 현재 화면 OCR 실행")
    print("i 키: 현재 ArUco pose를 초기 위치로 저장")
    print("g 키: 책 상단 pre_grasp target pose 계산/publish")
    print("m 키: AUTO_MOVE_ENABLED=True일 때 마지막 target으로 실제 이동 시도")
    print("q 키: 종료")

    latest_obb_data = []
    latest_frame = None
    latest_depth_frame = None
    latest_aruco_pose = {
        "found": False,
        "marker_id": None,
        "rvec": None,
        "tvec_m": None,
        "T_camera_marker": None,
        "corners": None,
    }
    saved_results = []
    robot_targets = []
    last_robot_target = None
    last_pre_grasp_pose = None
    last_target_status = "target: not published"
    frame_count = 0
    ocr_busy = False

    try:
        while True:
            rclpy.spin_once(pipeline, timeout_sec=0.0)
            rclpy.spin_once(robot_node, timeout_sec=0.0)
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
            latest_aruco_pose = detect_aruco_pose(frame, color_intrinsics)

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

            draw_aruco_pose(vis, latest_aruco_pose, color_intrinsics)

            selected_info = "selected book: none"
            if latest_obb_data:
                best_book = max(latest_obb_data, key=lambda item: item["confidence"])
                selected_info = (
                    f"selected book #{best_book['index']} "
                    f"conf={best_book['confidence']:.2f}"
                )

            cv2.putText(
                vis,
                selected_info,
                (20, 90),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2
            )

            cv2.putText(
                vis,
                last_target_status,
                (20, 120),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 0),
                2
            )

            elapsed = time.time() - start
            fps = 1.0 / elapsed if elapsed > 0 else 0.0

            cv2.putText(
                vis,
                (
                    f"RealSense YOLO FPS: {fps:.1f} | "
                    f"books: {len(latest_obb_data)} | "
                    f"shown>={DISPLAY_CONF_THRESHOLD:.2f} | "
                    f"g: target | m: move | i: init | s: OCR | q: quit"
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

            if key == ord("i") or key == ord("a"):
                if latest_aruco_pose["found"]:
                    save_aruco_initial_pose(latest_aruco_pose)
                else:
                    print("저장할 ArUco marker를 찾지 못했습니다.")

            if key == ord("g"):
                target_payload, pre_grasp_pose = build_and_publish_robot_target(
                    robot_node=robot_node,
                    latest_frame=latest_frame,
                    latest_depth_frame=latest_depth_frame,
                    color_intrinsics=color_intrinsics,
                    latest_obb_data=latest_obb_data,
                    latest_aruco_pose=latest_aruco_pose,
                    ocr=ocr
                )

                if target_payload is not None:
                    last_robot_target = target_payload
                    last_pre_grasp_pose = pre_grasp_pose
                    robot_targets.append(target_payload)
                    top_xyz = target_payload["book_top_camera_xyz_m"]
                    last_target_status = (
                        f"target published | book #{target_payload['book_index']} "
                        f"top xyz={top_xyz[0]:.3f},{top_xyz[1]:.3f},{top_xyz[2]:.3f}m"
                    )
                    save_json(
                        saved_results,
                        trigger_info={
                            "type": "manual_key_g",
                            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                            "mode": "book_top_pre_grasp_target"
                        },
                        robot_targets=robot_targets,
                        latest_robot_target=last_robot_target
                    )
                else:
                    last_target_status = "target publish failed"

            if key == ord("m"):
                if last_pre_grasp_pose is None:
                    print("마지막 pre_grasp pose가 없어 이동할 수 없습니다. 먼저 g 키를 누르세요.")
                else:
                    robot_node.move_to_pre_grasp(last_pre_grasp_pose)

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
                        show_log=True,
                        robot_targets=robot_targets,
                        latest_robot_target=last_robot_target
                    )
                    print(f"JSON 저장: {JSON_PATH}")
                finally:
                    ocr_busy = False

    finally:
        if pipeline is not None:
            pipeline.stop()
            pipeline.destroy_node()
        cv2.destroyAllWindows()

        save_json(
            saved_results,
            robot_targets=robot_targets,
            latest_robot_target=last_robot_target
        )
        robot_node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        print("종료 완료")
        print(f"최종 JSON: {JSON_PATH}")


if __name__ == "__main__":
    main()
