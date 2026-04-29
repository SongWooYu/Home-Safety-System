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


# COCO pose 17 keypoints
# 0 nose
# 1 left_eye
# 2 right_eye
# 3 left_ear
# 4 right_ear
# 5 left_shoulder
# 6 right_shoulder
# 7 left_elbow
# 8 right_elbow
# 9 left_wrist
# 10 right_wrist
# 11 left_hip
# 12 right_hip
# 13 left_knee
# 14 right_knee
# 15 left_ankle
# 16 right_ankle

SKELETON = [
    (5, 7), (7, 9),       # left arm
    (6, 8), (8, 10),      # right arm
    (5, 6),               # shoulders
    (11, 12),             # hips
    (5, 11), (6, 12),     # torso
    (11, 13), (13, 15),   # left leg
    (12, 14), (14, 16),   # right leg
]


def is_valid_point(kpts, confs, idx):
    x, y = kpts[idx]

    if x <= 0 or y <= 0:
        return False

    if confs is not None:
        if confs[idx] < KEYPOINT_CONF_THRES:
            return False

    return True


def calc_angle(a, b, c):
    """
    Calculate angle ABC in degrees.
    a, b, c: np.array([x, y])
    """
    ba = a - b
    bc = c - b

    denom = np.linalg.norm(ba) * np.linalg.norm(bc)
    if denom < 1e-6:
        return None

    cosang = np.dot(ba, bc) / denom
    cosang = np.clip(cosang, -1.0, 1.0)

    return math.degrees(math.acos(cosang))


def draw_angle(frame, kpts, confs, label, a_idx, b_idx, c_idx):
    if not (
        is_valid_point(kpts, confs, a_idx)
        and is_valid_point(kpts, confs, b_idx)
        and is_valid_point(kpts, confs, c_idx)
    ):
        return

    a = kpts[a_idx]
    b = kpts[b_idx]
    c = kpts[c_idx]

    angle = calc_angle(a, b, c)
    if angle is None:
        return

    bx, by = map(int, b)

    cv2.putText(
        frame,
        f"{label}: {angle:.0f}",
        (bx + 6, by - 6),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (0, 255, 255),
        1,
    )


class VideoCamera:
    def __init__(self):
        self.model = YOLO(MODEL_PATH)

        self.picam2 = Picamera2()
        config = self.picam2.create_video_configuration(
            main={
                "format": "RGB888",
                "size": (CAMERA_WIDTH, CAMERA_HEIGHT),
            }
        )
        self.picam2.configure(config)
        self.picam2.start()

        self.prev_time = time.time()

    def __del__(self):
        if hasattr(self, "picam2"):
            try:
                self.picam2.stop()
                self.picam2.close()
            except Exception:
                pass

    def get_frame(self):
        frame_rgb = self.picam2.capture_array()

        result = self.model.predict(
            frame_rgb,
            imgsz=IMG_SIZE,
            conf=CONF_THRES,
            verbose=False,
        )[0]

        # OpenCV JPEG 인코딩/그리기용 BGR 변환
        frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

        # Bounding boxes
        boxes = None
        if result.boxes is not None and result.boxes.xyxy is not None:
            boxes = result.boxes.xyxy.cpu().numpy()

        # Keypoints
        if result.keypoints is not None and result.keypoints.xy is not None:
            kpts_all = result.keypoints.xy.cpu().numpy()

            confs_all = None
            if result.keypoints.conf is not None:
                confs_all = result.keypoints.conf.cpu().numpy()

            for person_idx, kpts in enumerate(kpts_all):
                confs = None
                if confs_all is not None:
                    confs = confs_all[person_idx]

                # Draw person box
                if boxes is not None and person_idx < len(boxes):
                    x1, y1, x2, y2 = map(int, boxes[person_idx])
                    cv2.rectangle(
                        frame,
                        (x1, y1),
                        (x2, y2),
                        (0, 255, 0),
                        2,
                    )
                    cv2.putText(
                        frame,
                        "person",
                        (x1, max(20, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 255, 0),
                        2,
                    )

                # Draw skeleton lines
                for i, j in SKELETON:
                    if is_valid_point(kpts, confs, i) and is_valid_point(kpts, confs, j):
                        p1 = tuple(map(int, kpts[i]))
                        p2 = tuple(map(int, kpts[j]))
                        cv2.line(frame, p1, p2, (0, 255, 255), 2)

                # Draw keypoints
                for idx, point in enumerate(kpts):
                    if is_valid_point(kpts, confs, idx):
                        x, y = map(int, point)
                        cv2.circle(frame, (x, y), 4, (0, 255, 0), -1)

                # Joint angles
                draw_angle(frame, kpts, confs, "L elbow", 5, 7, 9)
                draw_angle(frame, kpts, confs, "R elbow", 6, 8, 10)
                draw_angle(frame, kpts, confs, "L knee", 11, 13, 15)
                draw_angle(frame, kpts, confs, "R knee", 12, 14, 16)

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

        _, buffer = cv2.imencode(".jpg", frame)
        return buffer.tobytes()


def generate_frames(camera):
    while True:
        frame_bytes = camera.get_frame()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
        )
