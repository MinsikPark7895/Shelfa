#!/usr/bin/env python3
"""Move to a preset joint pose, detect an ArUco marker, and move in front of it."""

import math
import time

import cv2
import numpy as np
import pyrealsense2 as rs
import rclpy
from dsr_msgs2.srv import GetCurrentPosx, MoveJoint, MoveLine
from geometry_msgs.msg import TransformStamped
from rclpy.duration import Duration
from rclpy.node import Node
from tf2_ros import Buffer, StaticTransformBroadcaster, TransformException, TransformListener

from .handeye_transform_utils import (
    make_transform,
    matrix_to_quaternion,
    transform_stamped_to_matrix,
)


DEFAULT_JOINT_POSE_DEG = [-17.87, 2.7, 122.02, -100.83, 74.83, 36.16]


class MarkerForwardTargetMove(Node):
    def __init__(self):
        super().__init__("marker_forward_target_move")

        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("camera_frame", "camera_color_optical_frame")
        self.declare_parameter("marker_id", 2)
        self.declare_parameter("marker_frame", "aruco_marker_2")
        self.declare_parameter("target_frame", "aruco_marker_2_forward_target")
        self.declare_parameter("marker_length_m", 0.05)
        self.declare_parameter("aruco_dict", "DICT_4X4_50")
        self.declare_parameter("width", 640)
        self.declare_parameter("height", 480)
        self.declare_parameter("fps", 30)
        self.declare_parameter("forward_distance_m", 0.50)
        self.declare_parameter("forward_axis", "z")
        self.declare_parameter("forward_sign", 1.0)
        self.declare_parameter("joint_pose_deg", DEFAULT_JOINT_POSE_DEG)
        self.declare_parameter("move_joint_service", "/dsr01/motion/move_joint")
        self.declare_parameter("move_line_service", "/dsr01/motion/move_line")
        self.declare_parameter("current_posx_service", "/dsr01/aux_control/get_current_posx")
        self.declare_parameter("current_posx_ref", 0)
        self.declare_parameter("movej_vel", 40.0)
        self.declare_parameter("movej_acc", 70.0)
        self.declare_parameter("movel_vel_linear", 15.0)
        self.declare_parameter("movel_vel_angular", 10.0)
        self.declare_parameter("movel_acc_linear", 30.0)
        self.declare_parameter("movel_acc_angular", 20.0)
        self.declare_parameter("settle_sec", 1.0)
        self.declare_parameter("detect_timeout_sec", 15.0)
        self.declare_parameter("show_display", True)
        self.declare_parameter("dry_run", False)

        self.base_frame = str(self.get_parameter("base_frame").value)
        self.camera_frame = str(self.get_parameter("camera_frame").value)
        self.marker_id = int(self.get_parameter("marker_id").value)
        self.marker_frame = str(self.get_parameter("marker_frame").value)
        self.target_frame = str(self.get_parameter("target_frame").value)
        self.marker_length_m = float(self.get_parameter("marker_length_m").value)
        self.aruco_dict_name = str(self.get_parameter("aruco_dict").value)
        self.width = int(self.get_parameter("width").value)
        self.height = int(self.get_parameter("height").value)
        self.fps = int(self.get_parameter("fps").value)
        self.forward_distance_m = float(self.get_parameter("forward_distance_m").value)
        self.forward_axis = str(self.get_parameter("forward_axis").value).lower()
        self.forward_sign = float(self.get_parameter("forward_sign").value)
        self.joint_pose_deg = [float(v) for v in self.get_parameter("joint_pose_deg").value]
        self.move_joint_service = str(self.get_parameter("move_joint_service").value)
        self.move_line_service = str(self.get_parameter("move_line_service").value)
        self.current_posx_service = str(self.get_parameter("current_posx_service").value)
        self.current_posx_ref = int(self.get_parameter("current_posx_ref").value)
        self.movej_vel = float(self.get_parameter("movej_vel").value)
        self.movej_acc = float(self.get_parameter("movej_acc").value)
        self.movel_vel_linear = float(self.get_parameter("movel_vel_linear").value)
        self.movel_vel_angular = float(self.get_parameter("movel_vel_angular").value)
        self.movel_acc_linear = float(self.get_parameter("movel_acc_linear").value)
        self.movel_acc_angular = float(self.get_parameter("movel_acc_angular").value)
        self.settle_sec = float(self.get_parameter("settle_sec").value)
        self.detect_timeout_sec = float(self.get_parameter("detect_timeout_sec").value)
        self.show_display = bool(self.get_parameter("show_display").value)
        self.dry_run = bool(self.get_parameter("dry_run").value)

        if len(self.joint_pose_deg) != 6:
            raise ValueError("joint_pose_deg must contain exactly 6 values")
        if self.forward_axis not in {"x", "y", "z"}:
            raise ValueError("forward_axis must be one of x, y, z")

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.tf_broadcaster = StaticTransformBroadcaster(self)
        self.move_joint_client = self.create_client(MoveJoint, self.move_joint_service)
        self.move_line_client = self.create_client(MoveLine, self.move_line_service)
        self.current_posx_client = self.create_client(GetCurrentPosx, self.current_posx_service)

        self.dictionary = self._get_aruco_dictionary(self.aruco_dict_name)
        self.detector_params = self._make_detector_parameters()
        self.detector = self._make_detector()

    def log_info(self, message):
        logger = self.get_logger()
        if hasattr(logger, "info"):
            logger.info(message)
        else:
            logger.warn(message)

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

    def _detect_markers(self, gray):
        if self.detector is not None:
            corners, ids, _ = self.detector.detectMarkers(gray)
        else:
            corners, ids, _ = cv2.aruco.detectMarkers(
                gray,
                self.dictionary,
                parameters=self.detector_params,
            )
        return corners, ids

    def _call_future(self, future, timeout_sec, timeout_message):
        start = time.monotonic()
        while rclpy.ok() and not future.done():
            if time.monotonic() - start > timeout_sec:
                raise TimeoutError(timeout_message)
            rclpy.spin_once(self, timeout_sec=0.05)
        if future.result() is None:
            raise RuntimeError(str(future.exception()))
        return future.result()

    def move_to_joint_pose(self):
        request = MoveJoint.Request()
        request.pos = list(self.joint_pose_deg)
        request.vel = self.movej_vel
        request.acc = self.movej_acc
        request.time = 0.0
        request.radius = 0.0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 0
        self.log_info(
            "Moving to preset joint pose\n"
            f"  pos={self.joint_pose_deg}\n"
            f"  service={self.move_joint_service}"
        )
        if self.dry_run:
            self.get_logger().warn("dry_run=true: skipped MoveJoint")
            return
        if not self.move_joint_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError(f"Service not available: {self.move_joint_service}")
        response = self._call_future(
            self.move_joint_client.call_async(request),
            60.0,
            f"{self.move_joint_service} timed out after 60.0 sec",
        )
        if not bool(response.success):
            raise RuntimeError(f"{self.move_joint_service} returned success=false")
        time.sleep(self.settle_sec)

    def get_current_task_pose(self):
        if not self.current_posx_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError(f"Service not available: {self.current_posx_service}")
        request = GetCurrentPosx.Request()
        request.ref = self.current_posx_ref
        response = self._call_future(
            self.current_posx_client.call_async(request),
            10.0,
            f"{self.current_posx_service} timed out after 10.0 sec",
        )
        if not bool(response.success):
            raise RuntimeError(f"{self.current_posx_service} returned success=false")
        if not response.task_pos_info:
            raise RuntimeError(f"{self.current_posx_service} returned empty task_pos_info")
        values = list(response.task_pos_info[0].data)
        if len(values) < 6:
            raise RuntimeError(f"{self.current_posx_service} returned fewer than 6 pose values")
        return [float(v) for v in values[:6]]

    def detect_marker_transform_camera(self):
        pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(rs.stream.color, self.width, self.height, rs.format.bgr8, self.fps)
        profile = pipeline.start(config)
        intr = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
        camera_matrix = np.array(
            [[intr.fx, 0.0, intr.ppx], [0.0, intr.fy, intr.ppy], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        dist_coeffs = np.array(intr.coeffs, dtype=np.float64)

        deadline = time.monotonic() + self.detect_timeout_sec
        try:
            while time.monotonic() < deadline:
                frames = pipeline.wait_for_frames()
                color_frame = frames.get_color_frame()
                if not color_frame:
                    continue
                image = np.asanyarray(color_frame.get_data())
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                corners, ids = self._detect_markers(gray)
                if ids is None or len(ids) == 0:
                    self._show_image(image, None, "No ArUco marker detected")
                    continue

                ids_flat = [int(v) for v in ids.flatten()]
                if self.marker_id not in ids_flat:
                    self._show_image(image, (corners, ids), f"Detected ids={ids_flat}")
                    continue

                index = ids_flat.index(self.marker_id)
                rvecs, tvecs, _ = cv2.aruco.estimatePoseSingleMarkers(
                    [corners[index]],
                    self.marker_length_m,
                    camera_matrix,
                    dist_coeffs,
                )
                rvec = rvecs[0][0]
                tvec = tvecs[0][0]
                rotation, _ = cv2.Rodrigues(rvec)
                transform = make_transform(rotation, tvec)
                self._show_image(image, (corners, ids), f"Detected target id={self.marker_id}")
                return transform
        finally:
            pipeline.stop()
            if self.show_display:
                cv2.destroyAllWindows()

        raise TimeoutError(f"Failed to detect marker_id={self.marker_id} within {self.detect_timeout_sec:.1f} sec")

    def _show_image(self, image, detection, status_text):
        if not self.show_display:
            return
        display = image.copy()
        if detection is not None:
            corners, ids = detection
            cv2.aruco.drawDetectedMarkers(display, corners, ids)
        cv2.putText(
            display,
            status_text,
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
        )
        cv2.imshow("Marker Forward Target Move", display)
        cv2.waitKey(1)

    def lookup_base_to_camera(self):
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                transform = self.tf_buffer.lookup_transform(
                    self.base_frame,
                    self.camera_frame,
                    rclpy.time.Time(),
                    timeout=Duration(seconds=0.5),
                )
                return transform_stamped_to_matrix(transform)
            except TransformException as exc:
                self.get_logger().warn(f"Waiting for {self.base_frame} -> {self.camera_frame}: {exc}")
                rclpy.spin_once(self, timeout_sec=0.1)
        raise TimeoutError(f"Failed to lookup {self.base_frame} -> {self.camera_frame}")

    def compute_target(self, base_to_marker):
        marker_position = base_to_marker[:3, 3]
        axis_index = {"x": 0, "y": 1, "z": 2}[self.forward_axis]
        forward_vector = base_to_marker[:3, axis_index]
        norm = float(np.linalg.norm(forward_vector))
        if norm < 1e-9:
            raise RuntimeError("Marker forward vector norm is zero")
        forward_vector = (self.forward_sign / norm) * forward_vector
        target_position = marker_position + self.forward_distance_m * forward_vector
        return marker_position, forward_vector, target_position

    def publish_static_transforms(self, base_to_marker, target_position):
        marker_q = matrix_to_quaternion(base_to_marker[:3, :3])

        marker_tf = TransformStamped()
        marker_tf.header.stamp = self.get_clock().now().to_msg()
        marker_tf.header.frame_id = self.base_frame
        marker_tf.child_frame_id = self.marker_frame
        marker_tf.transform.translation.x = float(base_to_marker[0, 3])
        marker_tf.transform.translation.y = float(base_to_marker[1, 3])
        marker_tf.transform.translation.z = float(base_to_marker[2, 3])
        marker_tf.transform.rotation.x = marker_q[0]
        marker_tf.transform.rotation.y = marker_q[1]
        marker_tf.transform.rotation.z = marker_q[2]
        marker_tf.transform.rotation.w = marker_q[3]

        target_tf = TransformStamped()
        target_tf.header.stamp = marker_tf.header.stamp
        target_tf.header.frame_id = self.base_frame
        target_tf.child_frame_id = self.target_frame
        target_tf.transform.translation.x = float(target_position[0])
        target_tf.transform.translation.y = float(target_position[1])
        target_tf.transform.translation.z = float(target_position[2])
        target_tf.transform.rotation.x = marker_q[0]
        target_tf.transform.rotation.y = marker_q[1]
        target_tf.transform.rotation.z = marker_q[2]
        target_tf.transform.rotation.w = marker_q[3]

        self.tf_broadcaster.sendTransform([marker_tf, target_tf])

    def move_tcp_to_target(self, target_position_m):
        current_pose = self.get_current_task_pose()
        request = MoveLine.Request()
        request.pos = [
            float(target_position_m[0] * 1000.0),
            float(target_position_m[1] * 1000.0),
            float(target_position_m[2] * 1000.0),
            float(current_pose[3]),
            float(current_pose[4]),
            float(current_pose[5]),
        ]
        request.vel = [self.movel_vel_linear, self.movel_vel_angular]
        request.acc = [self.movel_acc_linear, self.movel_acc_angular]
        request.time = 0.0
        request.radius = 0.0
        request.ref = 0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 0

        self.log_info(
            "Moving TCP to marker forward target\n"
            f"  target_xyz_m={[round(v, 6) for v in target_position_m.tolist()]}\n"
            f"  posx_mm_deg={request.pos}\n"
            f"  service={self.move_line_service}"
        )
        if self.dry_run:
            self.get_logger().warn("dry_run=true: skipped MoveLine")
            return
        if not self.move_line_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError(f"Service not available: {self.move_line_service}")
        response = self._call_future(
            self.move_line_client.call_async(request),
            60.0,
            f"{self.move_line_service} timed out after 60.0 sec",
        )
        if not bool(response.success):
            raise RuntimeError(f"{self.move_line_service} returned success=false")

    def run(self):
        self.log_info(
            "Starting marker forward target move\n"
            f"  joint_pose_deg={self.joint_pose_deg}\n"
            f"  marker_id={self.marker_id}\n"
            f"  marker_frame={self.marker_frame}\n"
            f"  forward_distance_m={self.forward_distance_m:.3f}\n"
            f"  forward_axis={self.forward_axis}\n"
            f"  forward_sign={self.forward_sign:.1f}\n"
            f"  dry_run={self.dry_run}"
        )
        self.move_to_joint_pose()
        camera_to_marker = self.detect_marker_transform_camera()
        base_to_camera = self.lookup_base_to_camera()
        base_to_marker = base_to_camera @ camera_to_marker
        marker_position, forward_vector, target_position = self.compute_target(base_to_marker)
        self.publish_static_transforms(base_to_marker, target_position)

        self.log_info(
            "Computed base_link -> marker and forward target\n"
            f"  marker_position_m={[round(v, 6) for v in marker_position.tolist()]}\n"
            f"  forward_vector_base={[round(v, 6) for v in forward_vector.tolist()]}\n"
            f"  target_position_m={[round(v, 6) for v in target_position.tolist()]}"
        )
        self.move_tcp_to_target(target_position)


def main(args=None):
    rclpy.init(args=args)
    node = MarkerForwardTargetMove()
    try:
        node.run()
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
