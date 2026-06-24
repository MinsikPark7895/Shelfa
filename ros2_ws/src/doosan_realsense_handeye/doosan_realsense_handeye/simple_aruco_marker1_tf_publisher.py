#!/usr/bin/env python3
"""Marker-1 default wrapper for simple_aruco_marker_tf_publisher."""

from . import simple_aruco_marker_tf_publisher as simple_aruco


def main(args=None):
    simple_aruco.DEFAULT_NODE_NAME = "simple_aruco_marker1_tf_publisher"
    simple_aruco.DEFAULT_MARKER_ID = 1
    simple_aruco.DEFAULT_CHILD_FRAME = "aruco_marker_1"
    simple_aruco.main(args=args)


if __name__ == "__main__":
    main()
