#!/usr/bin/env python3
"""Marker 2 preset entry point for the existing ArUco prototype aligner."""

import sys

from . import aruco_marker_proto_align as proto_align


MARKER2_JOINT_POSE_DEG = [-17.87, 2.7, 122.02, -100.83, 74.83, 36.16]


def _has_param(args, name):
    for index, token in enumerate(args):
        if token in ("-p", "--param") and index + 1 < len(args):
            if str(args[index + 1]).split(":=", 1)[0] == name:
                return True
        if str(token).startswith(f"{name}:="):
            return True
    return False


def _with_default_params(args):
    args = list(sys.argv[1:] if args is None else args)
    defaults = {
        "target_marker_id": "2",
        "marker_frame": "aruco_marker_2",
        "target_distance_m": "0.50",
        "run_post_alignment_pipeline": "false",
    }

    ros_args = []
    for name, value in defaults.items():
        if not _has_param(args, name):
            ros_args.extend(["-p", f"{name}:={value}"])

    if not ros_args:
        return args
    if "--ros-args" not in args:
        return args + ["--ros-args"] + ros_args
    return args + ros_args


def main(args=None):
    proto_align.MARKER_TARGET_PRESETS[2] = list(MARKER2_JOINT_POSE_DEG)
    proto_align.MARKER_SCAN_TOOL_Y_OFFSETS_MM[2] = 0.0
    proto_align.main(args=_with_default_params(args))


if __name__ == "__main__":
    main()
