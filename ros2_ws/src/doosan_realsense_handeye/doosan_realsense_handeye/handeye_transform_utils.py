import math

import numpy as np


def quaternion_to_matrix(x, y, z, w):
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0.0:
        raise ValueError("Quaternion norm is zero")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return np.array(
        [
            [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)],
            [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)],
            [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)],
        ],
        dtype=float,
    )


def matrix_to_quaternion(rotation):
    r = np.asarray(rotation, dtype=float).reshape(3, 3)
    trace = np.trace(r)
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (r[2, 1] - r[1, 2]) / s
        y = (r[0, 2] - r[2, 0]) / s
        z = (r[1, 0] - r[0, 1]) / s
    else:
        index = int(np.argmax(np.diag(r)))
        if index == 0:
            s = math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2.0
            w = (r[2, 1] - r[1, 2]) / s
            x = 0.25 * s
            y = (r[0, 1] + r[1, 0]) / s
            z = (r[0, 2] + r[2, 0]) / s
        elif index == 1:
            s = math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2.0
            w = (r[0, 2] - r[2, 0]) / s
            x = (r[0, 1] + r[1, 0]) / s
            y = 0.25 * s
            z = (r[1, 2] + r[2, 1]) / s
        else:
            s = math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2.0
            w = (r[1, 0] - r[0, 1]) / s
            x = (r[0, 2] + r[2, 0]) / s
            y = (r[1, 2] + r[2, 1]) / s
            z = 0.25 * s
    return [float(x), float(y), float(z), float(w)]


def matrix_to_euler_xyz(rotation):
    r = np.asarray(rotation, dtype=float).reshape(3, 3)
    pitch = math.asin(max(-1.0, min(1.0, -r[2, 0])))
    if abs(math.cos(pitch)) > 1e-9:
        roll = math.atan2(r[2, 1], r[2, 2])
        yaw = math.atan2(r[1, 0], r[0, 0])
    else:
        roll = 0.0
        yaw = math.atan2(-r[0, 1], r[1, 1])
    return [float(roll), float(pitch), float(yaw)]


def make_transform(rotation=None, translation=None):
    transform = np.eye(4, dtype=float)
    if rotation is not None:
        transform[:3, :3] = np.asarray(rotation, dtype=float).reshape(3, 3)
    if translation is not None:
        transform[:3, 3] = np.asarray(translation, dtype=float).reshape(3)
    return transform


def transform_msg_to_matrix(transform):
    q = transform.rotation
    t = transform.translation
    return make_transform(quaternion_to_matrix(q.x, q.y, q.z, q.w), [t.x, t.y, t.z])


def transform_stamped_to_matrix(transform_stamped):
    return transform_msg_to_matrix(transform_stamped.transform)


def matrix_from_yaml_dict(data):
    if "matrix" in data:
        return np.asarray(data["matrix"], dtype=float).reshape(4, 4)
    if "rotation_matrix" not in data or "translation" not in data:
        raise ValueError("Transform YAML needs either matrix or rotation_matrix + translation")
    translation = data["translation"]
    return make_transform(
        data["rotation_matrix"],
        [translation["x"], translation["y"], translation["z"]],
    )
