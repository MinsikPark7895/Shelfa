import numpy as np

from .handeye_transform_utils import *  # noqa: F401,F403


def invert_transform(transform):
    t = np.asarray(transform, dtype=float).reshape(4, 4)
    inv = np.eye(4, dtype=float)
    inv[:3, :3] = t[:3, :3].T
    inv[:3, 3] = -inv[:3, :3] @ t[:3, 3]
    return inv


def multiply_transforms(*transforms):
    result = np.eye(4, dtype=float)
    for transform in transforms:
        result = result @ np.asarray(transform, dtype=float).reshape(4, 4)
    return result


def transform_point(transform, point_xyz):
    point = np.ones(4, dtype=float)
    point[:3] = np.asarray(point_xyz, dtype=float).reshape(3)
    return (np.asarray(transform, dtype=float).reshape(4, 4) @ point)[:3]


def pose_msg_to_matrix(pose):
    q = pose.orientation
    p = pose.position
    return make_transform(quaternion_to_matrix(q.x, q.y, q.z, q.w), [p.x, p.y, p.z])

