#!/usr/bin/env python3
"""Subscribe to camera image/camera_info, detect ArUco marker 6, and publish TF."""

import math
import time
import threading

import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import TransformBroadcaster


DEFAULT_NODE_NAME = "simple_aruco_marker_tf_publisher"
DEFAULT_MARKER_ID = 6
DEFAULT_MARKER_LENGTH_M = 0.038
DEFAULT_IMAGE_TOPIC = "/camera/camera/color/image_raw"
DEFAULT_CAMERA_INFO_TOPIC = "/camera/camera/color/camera_info"
DEFAULT_PARENT_FRAME = "camera_color_optical_frame"
DEFAULT_CHILD_FRAME = "aruco_marker_6"
DEFAULT_ARUCO_DICT = "DICT_4X4_50"
DEFAULT_LOG_EVERY_N_DETECTIONS = 10
DEFAULT_LOG_PERIOD_SEC = 1.0


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
    if norm < 1e-12:
        raise ValueError("Quaternion norm is zero")
    return qx / norm, qy / norm, qz / norm, qw / norm


class SimpleArucoMarkerTfPublisher(Node):
    def __init__(self):
        super().__init__(DEFAULT_NODE_NAME)

        self.declare_parameter("marker_id", DEFAULT_MARKER_ID)
        self.declare_parameter("marker_length_m", DEFAULT_MARKER_LENGTH_M)
        self.declare_parameter("image_topic", DEFAULT_IMAGE_TOPIC)
        self.declare_parameter("camera_info_topic", DEFAULT_CAMERA_INFO_TOPIC)
        self.declare_parameter("parent_frame", DEFAULT_PARENT_FRAME)
        self.declare_parameter("child_frame", DEFAULT_CHILD_FRAME)
        self.declare_parameter("aruco_dict", DEFAULT_ARUCO_DICT)
        self.declare_parameter("show_display", False)
        self.declare_parameter("window_name", "Simple ArUco Marker TF")
        self.declare_parameter("log_every_n_detections", DEFAULT_LOG_EVERY_N_DETECTIONS)
        self.declare_parameter("log_period_sec", DEFAULT_LOG_PERIOD_SEC)

        self.marker_id = int(self.get_parameter("marker_id").value)
        self.marker_length_m = float(self.get_parameter("marker_length_m").value)
        self.image_topic = str(self.get_parameter("image_topic").value)
        self.camera_info_topic = str(self.get_parameter("camera_info_topic").value)
        self.parent_frame = str(self.get_parameter("parent_frame").value)
        self.child_frame = str(self.get_parameter("child_frame").value)
        self.aruco_dict_name = str(self.get_parameter("aruco_dict").value)
        self.show_display = bool(self.get_parameter("show_display").value)
        self.window_name = str(self.get_parameter("window_name").value)
        self.log_every_n_detections = max(1, int(self.get_parameter("log_every_n_detections").value))
        self.log_period_sec = float(self.get_parameter("log_period_sec").value)

        self.tf_broadcaster = TransformBroadcaster(self)
        self.camera_info = None
        self.camera_matrix = None
        self.dist_coeffs = None
        self.last_warn_time = 0.0
        self.last_log_time = 0.0
        self.detection_count = 0
        self.request_shutdown = False

        self.dictionary = self._get_aruco_dictionary(self.aruco_dict_name)
        self.detector_params = self._make_detector_parameters()
        self.detector = self._make_detector()

        self.create_subscription(CameraInfo, self.camera_info_topic, self._on_camera_info, 10)
        self.create_subscription(Image, self.image_topic, self._on_image, 10)

        self.log_info(
            "Simple ArUco marker TF publisher ready: "
            f"marker_id={self.marker_id}, marker_length_m={self.marker_length_m:.3f}, "
            f"parent_frame={self.parent_frame}, child_frame={self.child_frame}, "
            f"image_topic={self.image_topic}, camera_info_topic={self.camera_info_topic}"
        )

    def log_info(self, message):
        logger = self.get_logger()
        if hasattr(logger, "info"):
            logger.info(message)
        elif hasattr(logger, "dinfo"):
            logger.dinfo(message)
        else:
            logger.warn(message)

    def _image_to_bgr(self, msg):
        encoding = str(msg.encoding or "").lower()
        width = int(msg.width)
        height = int(msg.height)

        if width <= 0 or height <= 0:
            self._warn_throttled(
                f"Invalid image size: width={width}, height={height}"
            )
            return None

        try:
            if encoding == "bgr8":
                image = np.frombuffer(msg.data, dtype=np.uint8).reshape(height, width, 3)
                return image
            if encoding == "rgb8":
                rgb = np.frombuffer(msg.data, dtype=np.uint8).reshape(height, width, 3)
                return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            if encoding == "mono8":
                mono = np.frombuffer(msg.data, dtype=np.uint8).reshape(height, width)
                return cv2.cvtColor(mono, cv2.COLOR_GRAY2BGR)
            if encoding == "bgra8":
                bgra = np.frombuffer(msg.data, dtype=np.uint8).reshape(height, width, 4)
                return cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
            if encoding == "rgba8":
                rgba = np.frombuffer(msg.data, dtype=np.uint8).reshape(height, width, 4)
                return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)
        except Exception as exc:
            self._warn_throttled(f"Failed to convert image encoding={encoding}: {exc}")
            return None

        self._warn_throttled(f"Unsupported image encoding: {encoding}")
        return None

    def _get_aruco_dictionary(self, name):
        aruco = cv2.aruco
        if hasattr(aruco, name):
            return aruco.getPredefinedDictionary(getattr(aruco, name))
        raise ValueError(f"Unsupported ArUco dictionary: {name}")

    def _make_detector_parameters(self):
        aruco = cv2.aruco
        if hasattr(aruco, "DetectorParameters"):
            return aruco.DetectorParameters()
        return aruco.DetectorParameters_create()

    def _make_detector(self):
        aruco = cv2.aruco
        if hasattr(aruco, "ArucoDetector"):
            return aruco.ArucoDetector(self.dictionary, self.detector_params)
        return None

    def _on_camera_info(self, msg):
        self.camera_info = msg
        self.camera_matrix = np.array(
            [
                [msg.k[0], msg.k[1], msg.k[2]],
                [msg.k[3], msg.k[4], msg.k[5]],
                [msg.k[6], msg.k[7], msg.k[8]],
            ],
            dtype=np.float64,
        )
        self.dist_coeffs = np.array(msg.d, dtype=np.float64).reshape(-1, 1)

    def _on_image(self, msg):
        if self.camera_matrix is None or self.camera_info is None:
            self._warn_throttled("Waiting for CameraInfo before ArUco detection")
            return

        image = self._image_to_bgr(msg)
        if image is None:
            return

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        corners, ids = self._detect_markers(gray)
        display_image = image.copy() if self.show_display else None

        if ids is None or len(ids) == 0:
            self._maybe_show(display_image, corners, ids, None, "No ArUco marker detected")
            self._warn_throttled("No ArUco marker detected")
            return

        ids_flat = [int(marker_id) for marker_id in ids.flatten()]
        target_index = None
        for index, marker_id in enumerate(ids_flat):
            if marker_id == self.marker_id:
                target_index = index
                break

        if target_index is None:
            self._maybe_show(
                display_image,
                corners,
                ids,
                None,
                f"Detected ids={ids_flat}, target_id={self.marker_id} not found",
            )
            self._warn_throttled(
                f"Detected ids={ids_flat}, target_id={self.marker_id} not found"
            )
            return

        pose = self._estimate_pose(corners[target_index])
        if pose is None:
            self._warn_throttled(f"Pose estimation failed for marker_id={self.marker_id}")
            self._maybe_show(
                display_image,
                corners,
                ids,
                False,
                f"Pose estimation failed for id={self.marker_id}",
            )
            return

        rvec, tvec = pose
        self.publish_marker_tf(msg.header.stamp, rvec, tvec)
        self.detection_count += 1

        if self.detection_count % self.log_every_n_detections == 0:
            self.log_info(
                "Detected target marker "
                f"id={self.marker_id}, frame={self.parent_frame}->{self.child_frame}, "
                f"tvec=[{tvec[0]:.3f}, {tvec[1]:.3f}, {tvec[2]:.3f}], "
                f"detection_count={self.detection_count}"
            )

        self._maybe_show(
            display_image,
            corners,
            ids,
            True,
            f"Detected target id={self.marker_id}",
            target_index=target_index,
            rvec=rvec,
            tvec=tvec,
        )

    def _detect_markers(self, gray):
        aruco = cv2.aruco
        if self.detector is not None:
            corners, ids, _rejected = self.detector.detectMarkers(gray)
        else:
            corners, ids, _rejected = aruco.detectMarkers(
                gray,
                self.dictionary,
                parameters=self.detector_params,
            )
        return corners, ids

    def _estimate_pose(self, marker_corners):
        aruco = cv2.aruco
        corners = np.asarray(marker_corners, dtype=np.float64).reshape(1, 4, 2)

        if hasattr(aruco, "estimatePoseSingleMarkers"):
            try:
                rvecs, tvecs, _ = aruco.estimatePoseSingleMarkers(
                    [corners[0]],
                    self.marker_length_m,
                    self.camera_matrix,
                    self.dist_coeffs,
                )
                return rvecs[0][0], tvecs[0][0]
            except Exception:
                pass

        half = float(self.marker_length_m) / 2.0
        object_points = np.array(
            [
                [-half, half, 0.0],
                [half, half, 0.0],
                [half, -half, 0.0],
                [-half, -half, 0.0],
            ],
            dtype=np.float64,
        )

        image_points = corners[0].astype(np.float64)
        flags = getattr(cv2, "SOLVEPNP_IPPE_SQUARE", cv2.SOLVEPNP_ITERATIVE)
        success, rvec, tvec = cv2.solvePnP(
            object_points,
            image_points,
            self.camera_matrix,
            self.dist_coeffs,
            flags=flags,
        )
        if not success:
            return None
        return rvec.reshape(3), tvec.reshape(3)

    def publish_marker_tf(self, stamp, rvec, tvec):
        rotation_matrix, _ = cv2.Rodrigues(np.asarray(rvec, dtype=np.float64).reshape(3, 1))
        qx, qy, qz, qw = rotation_matrix_to_quaternion(rotation_matrix)

        transform = TransformStamped()
        transform.header.stamp = stamp
        transform.header.frame_id = self.parent_frame
        transform.child_frame_id = self.child_frame
        transform.transform.translation.x = float(tvec[0])
        transform.transform.translation.y = float(tvec[1])
        transform.transform.translation.z = float(tvec[2])
        transform.transform.rotation.x = float(qx)
        transform.transform.rotation.y = float(qy)
        transform.transform.rotation.z = float(qz)
        transform.transform.rotation.w = float(qw)
        self.tf_broadcaster.sendTransform(transform)

    def _maybe_show(
        self,
        display_image,
        corners,
        ids,
        target_detected,
        status_text,
        target_index=None,
        rvec=None,
        tvec=None,
    ):
        if not self.show_display or display_image is None:
            return

        if ids is not None and len(ids) > 0 and corners:
            cv2.aruco.drawDetectedMarkers(display_image, corners, ids)
            ids_flat = [int(marker_id) for marker_id in ids.flatten()]
            for marker_corners, marker_id in zip(corners, ids_flat):
                pts = np.array(marker_corners[0], dtype=np.int32)
                center = tuple(np.mean(pts, axis=0).astype(int))
                color = (0, 200, 0) if marker_id == self.marker_id else (0, 165, 255)
                cv2.circle(display_image, center, 4, color, -1)
                cv2.putText(
                    display_image,
                    f"id={marker_id}",
                    (center[0] + 8, center[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 255),
                    2,
                )

            if target_detected and target_index is not None:
                pts = np.array(corners[target_index][0], dtype=np.int32)
                center = tuple(np.mean(pts, axis=0).astype(int))
                cv2.putText(
                    display_image,
                    f"target id={self.marker_id}",
                    (center[0] + 12, center[1] + 18),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )
                if rvec is not None and tvec is not None and hasattr(cv2, "drawFrameAxes"):
                    try:
                        cv2.drawFrameAxes(
                            display_image,
                            self.camera_matrix,
                            self.dist_coeffs,
                            np.asarray(rvec, dtype=np.float64).reshape(3, 1),
                            np.asarray(tvec, dtype=np.float64).reshape(3, 1),
                            self.marker_length_m * 0.5,
                        )
                    except Exception:
                        pass

        cv2.putText(
            display_image,
            status_text,
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0) if target_detected else (0, 0, 255),
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

    def _warn_throttled(self, message):
        now = time.monotonic()
        if now - self.last_warn_time < self.log_period_sec:
            return
        self.last_warn_time = now
        self.get_logger().warn(message)


def main(args=None):
    rclpy.init(args=args)
    node = SimpleArucoMarkerTfPublisher()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()
    try:
        while rclpy.ok() and not node.request_shutdown:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        spin_thread.join(timeout=1.0)


if __name__ == "__main__":
    main()
