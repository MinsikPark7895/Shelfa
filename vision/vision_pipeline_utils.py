import numpy as np
import cv2

try:
    from . import realtime_yolo_paddle_ocr as vision
except ImportError:
    import realtime_yolo_paddle_ocr as vision


def compute_book_keypoints_from_obb(book):
    rect = vision.order_points(np.array(book["points"], dtype=np.float32))
    tl, tr, br, bl = rect

    width = float((np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2.0)
    height = float((np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2.0)

    if height >= width:
        end_a = (tl + tr) / 2.0
        end_b = (bl + br) / 2.0
    else:
        end_a = (tl + bl) / 2.0
        end_b = (tr + br) / 2.0

    if end_a[1] <= end_b[1]:
        top = end_a
        bottom = end_b
    else:
        top = end_b
        bottom = end_a

    mid = (top + bottom) / 2.0

    return {
        "top_center_px": [round(float(top[0]), 1), round(float(top[1]), 1)],
        "mid_center_px": [round(float(mid[0]), 1), round(float(mid[1]), 1)],
        "bottom_center_px": [round(float(bottom[0]), 1), round(float(bottom[1]), 1)],
    }


def deproject_keypoints_to_camera_xyz(depth_frame, color_intrinsics, keypoints):
    return {
        "top_camera_xyz_m": vision.deproject_pixel_to_camera_xyz(
            depth_frame,
            color_intrinsics,
            keypoints["top_center_px"][0],
            keypoints["top_center_px"][1],
        ),
        "mid_camera_xyz_m": vision.deproject_pixel_to_camera_xyz(
            depth_frame,
            color_intrinsics,
            keypoints["mid_center_px"][0],
            keypoints["mid_center_px"][1],
        ),
        "bottom_camera_xyz_m": vision.deproject_pixel_to_camera_xyz(
            depth_frame,
            color_intrinsics,
            keypoints["bottom_center_px"][0],
            keypoints["bottom_center_px"][1],
        ),
    }


def detect_books(yolo_model, frame, depth_frame=None, color_intrinsics=None):
    yolo_results = yolo_model.predict(
        frame,
        conf=vision.YOLO_CONF,
        iou=vision.YOLO_IOU,
        verbose=False,
    )
    obb_data = []

    if not yolo_results or yolo_results[0].obb is None:
        return obb_data

    for index, obb in enumerate(yolo_results[0].obb):
        points = obb.xyxyxyxy[0].cpu().numpy()
        confidence = float(obb.conf[0].cpu().numpy())

        if confidence < vision.DISPLAY_CONF_THRESHOLD:
            continue

        obb_info = vision.compute_obb_properties(points)
        if not vision.is_valid_book_spine(obb_info, confidence):
            continue

        camera_xyz_m = [None, None, None]
        depth_valid = False
        if depth_frame is not None and color_intrinsics is not None:
            center_px = obb_info["center_px"]
            camera_xyz_m = vision.deproject_pixel_to_camera_xyz(
                depth_frame,
                color_intrinsics,
                center_px[0],
                center_px[1],
            )
            depth_valid = vision.is_valid_camera_xyz(camera_xyz_m)

        obb_data.append({
            "index": index,
            "points": points,
            "confidence": confidence,
            "obb_info": obb_info,
            "camera_xyz_m": camera_xyz_m,
            "depth_valid": depth_valid,
        })

    return obb_data


def draw_books(image, obb_data):
    for book in obb_data:
        points = np.array(book["points"], dtype=np.int32)
        cv2.drawContours(image, [points], 0, (0, 255, 0), 2)

        center = book["obb_info"]["center_px"]
        cx = int(round(center[0]))
        cy = int(round(center[1]))
        label = f"#{book['index']} {float(book['confidence']):.2f}"
        cv2.putText(
            image,
            label,
            (cx, cy),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
        )

    return image
