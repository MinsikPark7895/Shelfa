#!/usr/bin/env python3
"""RealSense 컬러 영상에서 ArUco를 검출해 TF로 publish하는 노드."""

import math
import time

import cv2
import numpy as np
import pyrealsense2 as rs
import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.node import Node
from tf2_ros import TransformBroadcaster


def rotation_matrix_to_quaternion(matrix):
    trace = float(np.trace(matrix))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        qw = 0.25 * scale
        qx = (matrix[2, 1] - matrix[1, 2]) / scale
        qy = (matrix[0, 2] - matrix[2, 0]) / scale
        qz = (matrix[1, 0] - matrix[0, 1]) / scale
    elif matrix[0, 0] > matrix[1, 1] and matrix[0, 0] > matrix[2, 2]:
        scale = math.sqrt(1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2]) * 2.0
        qw = (matrix[2, 1] - matrix[1, 2]) / scale
        qx = 0.25 * scale
        qy = (matrix[0, 1] + matrix[1, 0]) / scale
        qz = (matrix[0, 2] + matrix[2, 0]) / scale
    elif matrix[1, 1] > matrix[2, 2]:
        scale = math.sqrt(1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2]) * 2.0
        qw = (matrix[0, 2] - matrix[2, 0]) / scale
        qx = (matrix[0, 1] + matrix[1, 0]) / scale
        qy = 0.25 * scale
        qz = (matrix[1, 2] + matrix[2, 1]) / scale
    else:
        scale = math.sqrt(1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1]) * 2.0
        qw = (matrix[1, 0] - matrix[0, 1]) / scale
        qx = (matrix[0, 2] + matrix[2, 0]) / scale
        qy = (matrix[1, 2] + matrix[2, 1]) / scale
        qz = 0.25 * scale

    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    return qx / norm, qy / norm, qz / norm, qw / norm


class ArucoRealSenseTfPublisher(Node):
    def __init__(self):
        super().__init__("aruco_realsense_tf_publisher")
        self.declare_parameter("camera_frame", "camera_color_optical_frame")
        self.declare_parameter("marker_frame_prefix", "aruco_marker_")
        self.declare_parameter("target_id", 6)
        self.declare_parameter("marker_length_m", 0.05)
        self.declare_parameter("aruco_dict", "DICT_4X4_50")
        self.declare_parameter("width", 1280)
        self.declare_parameter("height", 720)
        self.declare_parameter("fps", 30)
        self.declare_parameter("publish_all_ids", False)
        self.declare_parameter("log_period_sec", 1.0)
        self.declare_parameter("show_display", False)
        self.declare_parameter("window_name", "ArUco RealSense View")

        self.camera_frame = str(self.get_parameter("camera_frame").value)
        self.marker_frame_prefix = str(self.get_parameter("marker_frame_prefix").value)
        self.target_id = int(self.get_parameter("target_id").value)
        self.marker_length_m = float(self.get_parameter("marker_length_m").value)
        self.aruco_dict_name = str(self.get_parameter("aruco_dict").value)
        self.width = int(self.get_parameter("width").value)
        self.height = int(self.get_parameter("height").value)
        self.fps = int(self.get_parameter("fps").value)
        self.publish_all_ids = bool(self.get_parameter("publish_all_ids").value)
        self.log_period_sec = float(self.get_parameter("log_period_sec").value)
        self.show_display = bool(self.get_parameter("show_display").value)
        self.window_name = str(self.get_parameter("window_name").value)

        self.tf_broadcaster = TransformBroadcaster(self)
        self.dictionary = self.get_aruco_dictionary(self.aruco_dict_name)
        self.parameters = self.make_detector_parameters()
        self.detector = self.make_detector()
        self.pipeline = None
        self.pipeline_started = False
        self.camera_matrix = None
        self.dist_coeffs = None
        self.last_log_time = 0.0
        self.request_shutdown = False

    def log_info(self, message):
        logger = self.get_logger()
        if hasattr(logger, "info"):
            logger.info(message)
        elif hasattr(logger, "dinfo"):
            logger.dinfo(message)
        else:
            logger.warn(message)

    def get_aruco_dictionary(self, name):
        aruco = cv2.aruco
        dict_map = {
            "DICT_4X4_50": aruco.DICT_4X4_50,
            "DICT_4X4_100": aruco.DICT_4X4_100,
            "DICT_4X4_250": aruco.DICT_4X4_250,
            "DICT_5X5_50": aruco.DICT_5X5_50,
            "DICT_5X5_100": aruco.DICT_5X5_100,
            "DICT_5X5_250": aruco.DICT_5X5_250,
            "DICT_6X6_50": aruco.DICT_6X6_50,
            "DICT_6X6_100": aruco.DICT_6X6_100,
            "DICT_6X6_250": aruco.DICT_6X6_250,
        }
        if hasattr(aruco, name):
            return aruco.getPredefinedDictionary(getattr(aruco, name))
        if name not in dict_map:
            raise ValueError(f"unsupported aruco_dict: {name}")
        return aruco.getPredefinedDictionary(dict_map[name])

    def make_detector_parameters(self):
        aruco = cv2.aruco
        if hasattr(aruco, "DetectorParameters"):
            return aruco.DetectorParameters()
        return aruco.DetectorParameters_create()

    def make_detector(self):
        aruco = cv2.aruco
        if hasattr(aruco, "ArucoDetector"):
            return aruco.ArucoDetector(self.dictionary, self.parameters)
        return None

    def start_camera(self):
        self.pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(rs.stream.color, self.width, self.height, rs.format.bgr8, self.fps)
        profile = self.pipeline.start(config)
        self.pipeline_started = True
        intr = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
        self.camera_matrix = np.array(
            [[intr.fx, 0.0, intr.ppx], [0.0, intr.fy, intr.ppy], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        self.dist_coeffs = np.array(intr.coeffs, dtype=np.float64)
        self.log_info(
            f"RealSense ArUco TF publisher started: {self.width}x{self.height}@{self.fps}, "
            f"target_id={self.target_id}, marker_length_m={self.marker_length_m:.3f}"
        )

    def stop_camera(self):
        if self.pipeline is not None and self.pipeline_started:
            self.pipeline.stop()
            self.pipeline_started = False
            self.pipeline = None
        if self.show_display:
            cv2.destroyAllWindows()

    def spin_once_camera(self):
        frames = self.pipeline.wait_for_frames()
        color_frame = frames.get_color_frame()
        if not color_frame:
            return

        image = np.asanyarray(color_frame.get_data())
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        display_image = image.copy() if self.show_display else None
        if self.detector is not None:
            corners, ids, _ = self.detector.detectMarkers(gray)
        else:
            corners, ids, _ = cv2.aruco.detectMarkers(
                gray,
                self.dictionary,
                parameters=self.parameters,
            )

        if ids is None or len(ids) == 0:
            self.maybe_log("No ArUco marker detected")
            self.update_display(display_image, corners, None, None)
            return

        ids_flat = ids.flatten()
        published = []
        target_detected = False
        for index, marker_id in enumerate(ids_flat):
            marker_id = int(marker_id)
            if not self.publish_all_ids and marker_id != self.target_id:
                continue

            rvecs, tvecs, _ = cv2.aruco.estimatePoseSingleMarkers(
                [corners[index]],
                self.marker_length_m,
                self.camera_matrix,
                self.dist_coeffs,
            )
            self.publish_marker_tf(marker_id, rvecs[0][0], tvecs[0][0])
            published.append(marker_id)
            if marker_id == self.target_id:
                target_detected = True

        if published:
            self.maybe_log(f"Published ArUco TF ids={published}")
        else:
            self.maybe_log(f"Detected ids={list(map(int, ids_flat))}, target_id={self.target_id} not found")
        self.update_display(display_image, corners, ids, target_detected)

    def update_display(self, display_image, corners, ids, target_detected):
        if not self.show_display or display_image is None:
            return

        status_text = "No ArUco marker detected"
        status_color = (0, 0, 255)

        if ids is not None and len(ids) > 0:
            cv2.aruco.drawDetectedMarkers(display_image, corners, ids)
            ids_flat = [int(marker_id) for marker_id in ids.flatten()]
            if target_detected:
                status_text = f"Detected target id={self.target_id}"
                status_color = (0, 200, 0)
            else:
                status_text = f"Detected ids={ids_flat}, target_id={self.target_id} not found"
                status_color = (0, 165, 255)

            for marker_corners, marker_id in zip(corners, ids_flat):
                pts = np.array(marker_corners[0], dtype=np.int32)
                center = tuple(np.mean(pts, axis=0).astype(int))
                cv2.circle(display_image, center, 4, (255, 255, 0), -1)
                cv2.putText(
                    display_image,
                    f"id={marker_id}",
                    (center[0] + 8, center[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 255),
                    2,
                )

        cv2.putText(
            display_image,
            status_text,
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            status_color,
            2,
        )
        cv2.putText(
            display_image,
            "q: quit",
            (20, 70),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2,
        )
        cv2.imshow(self.window_name, display_image)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            self.log_info("Display window closed by user (q). Stopping ArUco TF publisher.")
            self.request_shutdown = True

    def publish_marker_tf(self, marker_id, rvec, tvec):
        rotation_matrix, _ = cv2.Rodrigues(rvec)
        qx, qy, qz, qw = rotation_matrix_to_quaternion(rotation_matrix)

        transform = TransformStamped()
        transform.header.stamp = self.get_clock().now().to_msg()
        transform.header.frame_id = self.camera_frame
        transform.child_frame_id = f"{self.marker_frame_prefix}{marker_id}"
        transform.transform.translation.x = float(tvec[0])
        transform.transform.translation.y = float(tvec[1])
        transform.transform.translation.z = float(tvec[2])
        transform.transform.rotation.x = qx
        transform.transform.rotation.y = qy
        transform.transform.rotation.z = qz
        transform.transform.rotation.w = qw
        self.tf_broadcaster.sendTransform(transform)

    def maybe_log(self, message):
        now = time.monotonic()
        if now - self.last_log_time >= self.log_period_sec:
            self.log_info(message)
            self.last_log_time = now


def main(args=None):
    rclpy.init(args=args)
    node = ArucoRealSenseTfPublisher()
    try:
        node.start_camera()
        while rclpy.ok() and not node.request_shutdown:
            rclpy.spin_once(node, timeout_sec=0.0)
            node.spin_once_camera()
    except KeyboardInterrupt:
        pass
    finally:
        node.stop_camera()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
