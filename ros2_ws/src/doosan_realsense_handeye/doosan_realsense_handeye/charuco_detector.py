import cv2
import numpy as np

from .transform_utils import make_transform


ARUCO_DICTIONARIES = {
    "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
    "DICT_4X4_100": cv2.aruco.DICT_4X4_100,
    "DICT_4X4_250": cv2.aruco.DICT_4X4_250,
    "DICT_4X4_1000": cv2.aruco.DICT_4X4_1000,
    "DICT_5X5_50": cv2.aruco.DICT_5X5_50,
    "DICT_5X5_100": cv2.aruco.DICT_5X5_100,
    "DICT_5X5_250": cv2.aruco.DICT_5X5_250,
    "DICT_5X5_1000": cv2.aruco.DICT_5X5_1000,
    "DICT_6X6_50": cv2.aruco.DICT_6X6_50,
    "DICT_6X6_100": cv2.aruco.DICT_6X6_100,
    "DICT_6X6_250": cv2.aruco.DICT_6X6_250,
    "DICT_6X6_1000": cv2.aruco.DICT_6X6_1000,
    "DICT_ARUCO_ORIGINAL": cv2.aruco.DICT_ARUCO_ORIGINAL,
}


def get_dictionary(name):
    key = str(name).upper()
    if key not in ARUCO_DICTIONARIES:
        raise ValueError(f"Unsupported ArUco dictionary '{name}'")
    if hasattr(cv2.aruco, "getPredefinedDictionary"):
        return cv2.aruco.getPredefinedDictionary(ARUCO_DICTIONARIES[key])
    return cv2.aruco.Dictionary_get(ARUCO_DICTIONARIES[key])


def make_detector_parameters():
    if hasattr(cv2.aruco, "DetectorParameters"):
        return cv2.aruco.DetectorParameters()
    return cv2.aruco.DetectorParameters_create()


def detect_markers(gray, dictionary, parameters):
    if hasattr(cv2.aruco, "ArucoDetector"):
        detector = cv2.aruco.ArucoDetector(dictionary, parameters)
        return detector.detectMarkers(gray)
    return cv2.aruco.detectMarkers(gray, dictionary, parameters=parameters)


def make_charuco_board(squares_x, squares_y, square_length, marker_length, dictionary):
    size = (int(squares_x), int(squares_y))
    if hasattr(cv2.aruco, "CharucoBoard"):
        try:
            return cv2.aruco.CharucoBoard(size, float(square_length), float(marker_length), dictionary)
        except TypeError:
            pass
    return cv2.aruco.CharucoBoard_create(
        int(squares_x),
        int(squares_y),
        float(square_length),
        float(marker_length),
        dictionary,
    )


def estimate_pose_single_markers(corners, marker_length, camera_matrix, dist_coeffs):
    return cv2.aruco.estimatePoseSingleMarkers(
        corners,
        float(marker_length),
        camera_matrix,
        dist_coeffs,
    )


class BoardPoseDetector:
    def __init__(self, board_type, config, logger=None, log_period_sec=2.0):
        self.board_type = str(board_type).lower()
        self.config = config
        self.logger = logger
        self.log_period_sec = float(log_period_sec)
        self._last_warn_by_message = {}
        if self.board_type not in {"charuco", "aruco"}:
            raise ValueError("board_type must be 'charuco' or 'aruco'")

        board_config = config[self.board_type]
        self.dictionary_name = board_config.get("dictionary", "DICT_5X5_100")
        self.dictionary = get_dictionary(self.dictionary_name)
        self.parameters = make_detector_parameters()
        self.charuco_board = None
        if self.board_type == "charuco":
            self.charuco_board = make_charuco_board(
                board_config["squares_x"],
                board_config["squares_y"],
                board_config["square_length"],
                board_config["marker_length"],
                self.dictionary,
            )

    def estimate(self, image_bgr, camera_matrix, dist_coeffs):
        if image_bgr is None:
            return None
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        if self.board_type == "charuco":
            return self._estimate_charuco(gray, camera_matrix, dist_coeffs)
        return self._estimate_aruco(gray, camera_matrix, dist_coeffs)

    def _estimate_charuco(self, gray, camera_matrix, dist_coeffs):
        corners, ids, rejected = detect_markers(gray, self.dictionary, self.parameters)
        marker_count = 0 if ids is None else len(ids)
        if ids is None or marker_count == 0:
            self._warn("ChArUco detection failed: no ArUco markers found")
            return None

        retval, charuco_corners, charuco_ids = cv2.aruco.interpolateCornersCharuco(
            corners,
            ids,
            gray,
            self.charuco_board,
            camera_matrix,
            dist_coeffs,
        )
        corner_count = 0 if charuco_ids is None else len(charuco_ids)
        min_corners = int(self.config["charuco"].get("min_corners", 6))
        if retval is None or corner_count < min_corners:
            self._warn(
                f"ChArUco detection failed: only {corner_count} corners "
                f"(minimum {min_corners}), markers={marker_count}"
            )
            return None

        ok, rvec, tvec = cv2.aruco.estimatePoseCharucoBoard(
            charuco_corners,
            charuco_ids,
            self.charuco_board,
            camera_matrix,
            dist_coeffs,
            None,
            None,
        )
        if not ok:
            self._warn("ChArUco pose estimation failed after corner interpolation")
            return None

        return self._result(rvec, tvec, marker_count, corner_count, rejected)

    def _estimate_aruco(self, gray, camera_matrix, dist_coeffs):
        corners, ids, rejected = detect_markers(gray, self.dictionary, self.parameters)
        if ids is None or len(ids) == 0:
            self._warn("ArUco detection failed: no marker found")
            return None

        marker_id = int(self.config["aruco"].get("marker_id", int(ids[0][0])))
        selected_index = None
        for index, value in enumerate(ids.flatten().tolist()):
            if int(value) == marker_id:
                selected_index = index
                break
        if selected_index is None:
            self._warn(f"ArUco detection failed: marker id {marker_id} not visible")
            return None

        rvecs, tvecs, _ = estimate_pose_single_markers(
            [corners[selected_index]],
            self.config["aruco"]["marker_length"],
            camera_matrix,
            dist_coeffs,
        )
        return self._result(
            rvecs[0].reshape(3, 1),
            tvecs[0].reshape(3, 1),
            len(ids),
            4,
            rejected,
            marker_id=marker_id,
        )

    def _result(self, rvec, tvec, marker_count, corner_count, rejected, marker_id=None):
        rotation, _ = cv2.Rodrigues(np.asarray(rvec, dtype=float).reshape(3, 1))
        translation = np.asarray(tvec, dtype=float).reshape(3)
        transform = make_transform(rotation, translation)
        info = {
            "board_type": self.board_type,
            "dictionary": self.dictionary_name,
            "marker_count": int(marker_count),
            "corner_count": int(corner_count),
            "rejected_count": int(0 if rejected is None else len(rejected)),
            "translation_m": translation.tolist(),
            "rvec": np.asarray(rvec, dtype=float).reshape(3).tolist(),
        }
        if marker_id is not None:
            info["marker_id"] = int(marker_id)
        return {"T_camera_target": transform, "info": info}

    def _warn(self, message):
        if self.logger is not None:
            key = message
            if message.startswith("ChArUco detection failed: only "):
                key = "charuco_insufficient_corners"
            elif message.startswith("ChArUco detection failed: no "):
                key = "charuco_no_markers"
            elif message.startswith("ArUco detection failed: no "):
                key = "aruco_no_markers"
            elif message.startswith("ArUco detection failed: marker id "):
                key = "aruco_marker_id_missing"
            now = cv2.getTickCount() / cv2.getTickFrequency()
            last = self._last_warn_by_message.get(key)
            if last is None or now - last >= self.log_period_sec:
                self._last_warn_by_message[key] = now
                self.logger.warn(message)


def camera_info_to_matrices(camera_info_msg):
    camera_matrix = np.asarray(camera_info_msg.k, dtype=float).reshape(3, 3)
    dist_coeffs = np.asarray(camera_info_msg.d, dtype=float).reshape(-1, 1)
    return camera_matrix, dist_coeffs
