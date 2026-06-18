#!/usr/bin/env python3
"""Run the bookshelf pick mission, then run the saved marker2 place mission."""

import json
import os
import shlex
import subprocess

import rclpy
from rclpy.node import Node


class FullPickThenMarker2PlaceSequence(Node):
    def __init__(self):
        super().__init__("full_pick_then_marker2_place_sequence")

        self.declare_parameter("dry_run", True)
        self.declare_parameter("simulate_when_dry_run", True)
        self.declare_parameter("wait_for_enter_between_sequences", True)
        self.declare_parameter("first_executable", "book_mission_state_machine")
        self.declare_parameter("second_executable", "box_saved_marker2_pose_place_sequence")
        self.declare_parameter("first_timeout_sec", 1200.0)
        self.declare_parameter("second_timeout_sec", 600.0)
        self.declare_parameter("first_result_json", "realtime_results/full_pick_first_result.json")
        self.declare_parameter("first_trace_json", "realtime_results/full_pick_first_trace.json")
        self.declare_parameter("target_title", "제3인류")
        self.declare_parameter("first_extra_ros_args", "")
        self.declare_parameter("second_extra_ros_args", "")

        self.dry_run = bool(self.get_parameter("dry_run").value)
        self.simulate_when_dry_run = bool(self.get_parameter("simulate_when_dry_run").value)
        self.wait_for_enter_between_sequences = bool(
            self.get_parameter("wait_for_enter_between_sequences").value
        )
        self.first_executable = str(self.get_parameter("first_executable").value)
        self.second_executable = str(self.get_parameter("second_executable").value)
        self.first_timeout_sec = float(self.get_parameter("first_timeout_sec").value)
        self.second_timeout_sec = float(self.get_parameter("second_timeout_sec").value)
        self.first_result_json = str(self.get_parameter("first_result_json").value)
        self.first_trace_json = str(self.get_parameter("first_trace_json").value)
        self.target_title = str(self.get_parameter("target_title").value)
        self.first_extra_ros_args = str(self.get_parameter("first_extra_ros_args").value)
        self.second_extra_ros_args = str(self.get_parameter("second_extra_ros_args").value)

    def log_info(self, message):
        logger = self.get_logger()
        if hasattr(logger, "info"):
            logger.info(message)
        elif hasattr(logger, "dinfo"):
            logger.dinfo(message)
        else:
            logger.warn(message)

    def command_with_params(self, executable, params, extra_ros_args):
        command = ["ros2", "run", "doosan_realsense_handeye", executable, "--ros-args"]
        for name, value in params:
            command.extend(["-p", f"{name}:={value}"])
        if extra_ros_args.strip():
            command.extend(shlex.split(extra_ros_args))
        return command

    def first_command(self):
        return self.command_with_params(
            self.first_executable,
            [
                ("dry_run", str(self.dry_run).lower()),
                ("auto_run", "false"),
                ("alignment_dry_run", str(self.dry_run).lower()),
                ("alignment_auto_run", "false"),
                ("enable_gripper_control", "true"),
                ("place_after_experimental_pick_cycles", "true"),
                ("target_title", self.target_title),
                ("result_json", self.first_result_json),
                ("state_trace_json", self.first_trace_json),
            ],
            self.first_extra_ros_args,
        )

    def second_command(self):
        return self.command_with_params(
            self.second_executable,
            [
                ("dry_run", str(self.dry_run).lower()),
                ("require_enter", "true"),
            ],
            self.second_extra_ros_args,
        )

    def remove_old_first_result(self):
        if self.dry_run and self.simulate_when_dry_run:
            return
        for path in (self.first_result_json, self.first_trace_json):
            if path and os.path.exists(path):
                os.remove(path)

    def run_command(self, command, timeout_sec, label):
        self.log_info("\n" + label + "\n  command=" + " ".join(command))
        if self.dry_run and self.simulate_when_dry_run:
            self.get_logger().warn(f"{label}: dry_run simulation, subprocess skipped")
            return
        subprocess.run(command, check=True, timeout=timeout_sec)

    def require_first_mission_done(self):
        if self.dry_run and self.simulate_when_dry_run:
            self.get_logger().warn("dry_run simulation: skipped first mission result check")
            return
        if not os.path.exists(self.first_result_json):
            raise RuntimeError(f"First mission result not found: {self.first_result_json}")
        with open(self.first_result_json, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        status = str(payload.get("status", ""))
        successful_statuses = {"done", "experimental_pick_cycles_done"}
        if status not in successful_statuses:
            raise RuntimeError(
                f"First mission did not finish successfully: status={status}, "
                f"state={payload.get('state')}"
            )
        self.log_info(
            "\nFIRST_MISSION_CONFIRMED\n"
            f"  result_json={self.first_result_json}\n"
            f"  status={status}"
        )

    def print_config(self):
        self.log_info(
            "\n"
            "Full pick then marker2 place sequence\n"
            f"  dry_run={self.dry_run}\n"
            f"  simulate_when_dry_run={self.simulate_when_dry_run}\n"
            f"  wait_for_enter_between_sequences={self.wait_for_enter_between_sequences}\n"
            f"  first_executable={self.first_executable}\n"
            f"  second_executable={self.second_executable}\n"
            f"  first_result_json={self.first_result_json}\n"
            f"  target_title={self.target_title}"
        )

    def run_sequence(self):
        self.print_config()
        self.remove_old_first_result()
        self.run_command(self.first_command(), self.first_timeout_sec, "RUN_FIRST_BOOK_PICK_MISSION")
        self.require_first_mission_done()
        if self.wait_for_enter_between_sequences:
            input("First book-pick mission completed. Press Enter to start marker2 place mission...")
        self.run_command(self.second_command(), self.second_timeout_sec, "RUN_SECOND_MARKER2_PLACE_MISSION")
        self.log_info("\nDONE: full pick then marker2 place sequence completed.")


def main(args=None):
    rclpy.init(args=args)
    node = FullPickThenMarker2PlaceSequence()
    try:
        node.run_sequence()
    except KeyboardInterrupt:
        node.get_logger().warn("Interrupted by user.")
    except Exception as exc:
        node.get_logger().error(f"Sequence failed: {exc}")
        raise
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
