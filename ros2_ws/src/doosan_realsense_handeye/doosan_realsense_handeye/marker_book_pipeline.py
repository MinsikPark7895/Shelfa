#!/usr/bin/env python3

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

import rclpy
from dsr_msgs2.srv import MoveLine
from rclpy.node import Node

from .book_scan_after_alignment import compute_book_scan_pose


DEFAULT_ALIGNMENT_PAYLOAD_JSON = "realtime_results/alignment_payload.json"
DEFAULT_SCAN_RESULT_JSON = "realtime_results/book_scan_result.json"
DEFAULT_OUTPUT_JSON = "realtime_results/marker_book_pipeline_result.json"
DEFAULT_TARGET_TITLE = "제3인류"


class MarkerBookPipelineNode(Node):
    def __init__(self, args):
        super().__init__("marker_book_pipeline")
        self.args = args
        self.move_line_client = self.create_client(MoveLine, args.move_line_service)

    def log_info(self, message):
        logger = self.get_logger()
        if hasattr(logger, "info"):
            logger.info(message)
        elif hasattr(logger, "dinfo"):
            logger.dinfo(message)
        else:
            logger.warn(message)

    def load_alignment_payload(self):
        with open(self.args.alignment_payload_json, "r", encoding="utf-8") as stream:
            return json.load(stream)

    def move_to_scan_pose(self, scan_pose):
        request = MoveLine.Request()
        request.pos = [float(v) for v in scan_pose["posx_mm_deg"]]
        request.vel = [float(self.args.scan_move_vel_linear), float(self.args.scan_move_vel_angular)]
        request.acc = [float(self.args.scan_move_acc_linear), float(self.args.scan_move_acc_angular)]
        request.time = 0.0
        request.radius = 0.0
        request.ref = 0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 0

        self.log_info(
            "\n"
            "Move to book scan pose\n"
            f"  posx_mm_deg={scan_pose['posx_mm_deg']}\n"
            f"  vel={request.vel}\n"
            f"  acc={request.acc}\n"
            f"  dry_run={self.args.dry_run}"
        )

        if self.args.dry_run:
            self.get_logger().warn("dry_run=true: scan pose move skipped.")
            return True

        if not self.move_line_client.wait_for_service(timeout_sec=1.0):
            raise RuntimeError(f"Service not available: {self.args.move_line_service}")

        future = self.move_line_client.call_async(request)
        start_time = time.monotonic()
        while rclpy.ok() and not future.done():
            if time.monotonic() - start_time > self.args.service_timeout_sec:
                raise RuntimeError(
                    f"{self.args.move_line_service} timed out after "
                    f"{self.args.service_timeout_sec:.1f} sec"
                )
            rclpy.spin_once(self, timeout_sec=0.05)

        if future.result() is None:
            raise RuntimeError(f"{self.args.move_line_service} failed: {future.exception()}")

        response = future.result()
        if not bool(getattr(response, "success", False)):
            raise RuntimeError(f"{self.args.move_line_service} returned success=false")

        self.log_info("Scan pose move completed successfully.")
        return True

    def run_subprocess(self, command, label):
        self.log_info(f"{label} command:\n  {' '.join(command)}")
        subprocess.run(command, check=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "After ArUco alignment, move to the marker-specific scan pose, "
            "run OCR book scan, approach the selected book, and execute the pick sequence."
        )
    )
    parser.add_argument("--alignment-payload-json", default=DEFAULT_ALIGNMENT_PAYLOAD_JSON)
    parser.add_argument("--scan-result-json", default=DEFAULT_SCAN_RESULT_JSON)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--move-line-service", default="/dsr01/motion/move_line")
    parser.add_argument("--service-timeout-sec", type=float, default=30.0)
    parser.add_argument("--scan-move-vel-linear", type=float, default=20.0)
    parser.add_argument("--scan-move-vel-angular", type=float, default=10.0)
    parser.add_argument("--scan-move-acc-linear", type=float, default=40.0)
    parser.add_argument("--scan-move-acc-angular", type=float, default=20.0)
    parser.add_argument("--target-title", default=DEFAULT_TARGET_TITLE)
    parser.add_argument("--yolo-conf", type=float, default=0.75)
    parser.add_argument("--no-display", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--enable-gripper-control", action="store_true", default=True)
    return parser.parse_args()


def save_result(path, payload):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)


def main(args=None):
    parsed = parse_args()
    rclpy.init(args=args)
    node = MarkerBookPipelineNode(parsed)
    result = {
        "timestamp": datetime.now().isoformat(),
        "source": "marker_book_pipeline",
        "alignment_payload_json": parsed.alignment_payload_json,
        "scan_result_json": parsed.scan_result_json,
        "target_title": parsed.target_title,
        "dry_run": bool(parsed.dry_run),
        "steps": [],
        "success": False,
    }

    try:
        alignment_payload = node.load_alignment_payload()
        scan_pose = compute_book_scan_pose(alignment_payload)
        result["scan_pose"] = scan_pose

        node.move_to_scan_pose(scan_pose)
        result["steps"].append("move_to_scan_pose")

        scan_command = [
            "ros2",
            "run",
            "doosan_realsense_handeye",
            "book_scan_after_alignment",
            "--alignment-payload-json",
            parsed.alignment_payload_json,
            "--target-title",
            parsed.target_title,
            "--yolo-conf",
            str(parsed.yolo_conf),
        ]
        if parsed.no_display:
            scan_command.append("--no-display")
        node.run_subprocess(scan_command, "Book scan")
        result["steps"].append("book_scan_after_alignment")

        approach_command = [
            "ros2",
            "run",
            "doosan_realsense_handeye",
            "tf_book_target_to_approach",
            "--scan-result",
            parsed.scan_result_json,
        ]
        if not parsed.dry_run:
            approach_command.append("--execute")
        node.run_subprocess(approach_command, "Book approach")
        result["steps"].append("tf_book_target_to_approach")

        pick_command = [
            "ros2",
            "run",
            "doosan_realsense_handeye",
            "book_pick_sequence_node",
            "--ros-args",
            "-p",
            f"dry_run:={'true' if parsed.dry_run else 'false'}",
            "-p",
            f"enable_gripper_control:={'true' if parsed.enable_gripper_control else 'false'}",
        ]
        node.run_subprocess(pick_command, "Book pick")
        result["steps"].append("book_pick_sequence_node")

        result["success"] = True
        save_result(parsed.output_json, result)
    except Exception as exc:
        result["error"] = str(exc)
        save_result(parsed.output_json, result)
        raise
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
