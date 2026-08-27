import time
import math
import cv2
import numpy as np
from picamera2 import Picamera2
from ultralytics import YOLO


MODEL_PATH = "/home/pi/songwoo/striming/models/yolo11n-pose_ncnn_model"

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480

IMG_SIZE = 320
CONF_THRES = 0.35
KEYPOINT_CONF_THRES = 0.30


# COCO pose skeleton
SKELETON = [
    (5, 7), (7, 9),
    (6, 8), (8, 10),
    (5, 6),
    (11, 12),
    (5, 11), (6, 12),
    (11, 13), (13, 15),
    (12, 14), (14, 16),
]


# -------------------------
# Fall tracking (noise filter)
# -------------------------
class FallTracker:
    def __init__(self):
        self.history = []

    def update(self, value):
        self.history.append(value)
        if len(self.history) > 5:
            self.history.pop(0)

        return self.history.count(True) >= 3


fall_tracker = FallTracker()


# -------------------------
# utils
# -------------------------
def is_valid_point(kpts, confs, idx):
    x, y = kpts[idx]

    if x <= 0 or y <= 0:
        return False

    if confs is not None and confs[idx] < KEYPOINT_CONF_THRES:
        return False

    return True


def calc_angle(a, b, c):
    ba = a - b
    bc = c - b

    denom = np.linalg.norm(ba) * np.linalg.norm(bc)
    if denom < 1e-6:
        return None

    cosang = np.dot(ba, bc) / denom
    cosang = np.clip(cosang, -1.0, 1.0)

    return math.degrees(math.acos(cosang))


# -------------------------
# WARNING detection
# -------------------------
def is_warning(kpts, confs):

    L_SHO, R_SHO = 5, 6
    L_HIP, R_HIP = 11, 12

    required = [L_SHO, R_SHO, L_HIP, R_HIP]

    for i in required:
        if not is_valid_point(kpts, confs, i):
            return False

    l_sho = np.array(kpts[L_SHO])
    r_sho = np.array(kpts[R_SHO])
    l_hip = np.array(kpts[L_HIP])
    r_hip = np.array(kpts[R_HIP])

    mid_sho = (l_sho + r_sho) / 2
    mid_hip = (l_hip + r_hip) / 2

    dx = mid_sho[0] - mid_hip[0]
    dy = mid_sho[1] - mid_hip[1]

    angle = abs(math.degrees(math.atan2(dy, dx)))

    body_h = abs(mid_sho[1] - mid_hip[1])
    body_w = abs(mid_sho[0] - mid_hip[0]) + 1e-6

    ratio = body_h / body_w

    return angle < 50 and ratio < 1.2


# -------------------------
# FALL detection (advanced)
# -------------------------
def is_fall(kpts, confs):

    L_SHO, R_SHO = 5, 6
    L_HIP, R_HIP = 11, 12
    NOSE = 0
    L_ANK, R_ANK = 15, 16

    required = [L_SHO, R_SHO, L_HIP, R_HIP, NOSE, L_ANK, R_ANK]

    for i in required:
        if not is_valid_point(kpts, confs, i):
            return False

    l_sho = np.array(kpts[L_SHO])
    r_sho = np.array(kpts[R_SHO])
    l_hip = np.array(kpts[L_HIP])
    r_hip = np.array(kpts[R_HIP])
    nose = np.array(kpts[NOSE])
    l_ank = np.array(kpts[L_ANK])
    r_ank = np.array(kpts[R_ANK])

    mid_sho = (l_sho + r_sho) / 2
    mid_hip = (l_hip + r_hip) / 2

    dx = mid_sho[0] - mid_hip[0]
    dy = mid_sho[1] - mid_hip[1]

    angle = abs(math.degrees(math.atan2(dy, dx)))

    body_h = abs(mid_sho[1] - mid_hip[1])
    body_w = abs(mid_sho[0] - mid_hip[0]) + 1e-6
    ratio = body_h / body_w

    head_down = nose[1] > mid_hip[1]
    feet_low = (l_ank[1] > mid_hip[1]) and (r_ank[1] > mid_hip[1])

    fast_fall = angle < 30 and ratio < 0.7
    slow_fall = head_down and ratio < 1.0

    raw_fall = (fast_fall or slow_fall) and feet_low

    return fall_tracker.update(raw_fall)


# -------------------------
# Camera + YOLO
# -------------------------
class VideoCamera:
    def __init__(self):
        self.model = YOLO(MODEL_PATH)

        self.picam2 = Picamera2()
        config = self.picam2.create_video_configuration(
            main={"format": "RGB888", "size": (CAMERA_WIDTH, CAMERA_HEIGHT)}
        )
        self.picam2.configure(config)
        self.picam2.start()

        self.prev_time = time.time()

    def __del__(self):
        if hasattr(self, "picam2"):
            try:
                self.picam2.stop()
                self.picam2.close()
            except:
                pass

    def get_frame(self):

        frame_rgb = self.picam2.capture_array()

        result = self.model.predict(
            frame_rgb,
            imgsz=IMG_SIZE,
            conf=CONF_THRES,
            verbose=False,
        )[0]

        frame = frame_rgb.copy()

        boxes = None
        if result.boxes is not None:
            boxes = result.boxes.xyxy.cpu().numpy()

        status = "NORMAL"

        if result.keypoints is not None and result.keypoints.xy is not None:

            kpts_all = result.keypoints.xy.cpu().numpy()

            confs_all = None
            if result.keypoints.conf is not None:
                confs_all = result.keypoints.conf.cpu().numpy()

            for person_idx, kpts in enumerate(kpts_all):

                confs = confs_all[person_idx] if confs_all is not None else None

                if is_fall(kpts, confs):
                    status = "FALL"
                elif is_warning(kpts, confs):
                    status = "WARNING"

                if boxes is not None and person_idx < len(boxes):
                    x1, y1, x2, y2 = map(int, boxes[person_idx])
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                for i, j in SKELETON:
                    if is_valid_point(kpts, confs, i) and is_valid_point(kpts, confs, j):
                        p1 = tuple(map(int, kpts[i]))
                        p2 = tuple(map(int, kpts[j]))
                        cv2.line(frame, p1, p2, (0, 255, 255), 2)

        # FPS
        now = time.time()
        fps = 1.0 / max(now - self.prev_time, 1e-6)
        self.prev_time = now

        cv2.putText(
            frame,
            f"FPS: {fps:.1f}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 0),
            2,
        )

        # -------------------------
        # STATUS UI
        # -------------------------
        color = (0, 255, 0)

        if status == "WARNING":
            color = (0, 255, 255)
        elif status == "FALL":
            color = (0, 0, 255)

        cv2.putText(
            frame,
            f"STATUS: {status}",
            (10, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            color,
            3,
        )

        _, buffer = cv2.imencode(".jpg", frame)
        return buffer.tobytes()


# -------------------------
# Flask stream
# -------------------------
def generate_frames(camera):
    while True:
        frame = camera.get_frame()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        )