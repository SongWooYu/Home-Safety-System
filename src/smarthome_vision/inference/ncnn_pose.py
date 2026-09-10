from __future__ import annotations

import threading
from pathlib import Path

import cv2
import ncnn
import numpy as np


class NcnnPoseEstimator:
    """YOLO11 NCNN single-class pose estimator."""

    KEYPOINT_NAMES = (
        "nose",
        "left_eye",
        "right_eye",
        "left_ear",
        "right_ear",
        "left_shoulder",
        "right_shoulder",
        "left_elbow",
        "right_elbow",
        "left_wrist",
        "right_wrist",
        "left_hip",
        "right_hip",
        "left_knee",
        "right_knee",
        "left_ankle",
        "right_ankle",
    )

    def __init__(
        self,
        model_dir: str,
        input_size: int = 320,
        confidence: float = 0.35,
        nms_iou: float = 0.45,
        threads: int = 4,
    ):
        model_path = Path(model_dir)
        param_path = model_path / "model.ncnn.param"
        bin_path = model_path / "model.ncnn.bin"
        if not param_path.exists() or not bin_path.exists():
            raise FileNotFoundError(f"NCNN pose model is incomplete: {model_path}")

        self.input_size = input_size
        self.confidence = confidence
        self.nms_iou = nms_iou
        self.lock = threading.Lock()
        self.net = ncnn.Net()
        self.net.opt.use_vulkan_compute = False
        self.net.opt.num_threads = threads
        if self.net.load_param(str(param_path)) != 0:
            raise RuntimeError(f"Failed to load {param_path}")
        if self.net.load_model(str(bin_path)) != 0:
            raise RuntimeError(f"Failed to load {bin_path}")

    def estimate(self, frame_bgr: np.ndarray) -> list[dict]:
        original_h, original_w = frame_bgr.shape[:2]
        scale = min(self.input_size / original_w, self.input_size / original_h)
        resized_w = max(1, int(round(original_w * scale)))
        resized_h = max(1, int(round(original_h * scale)))
        resized = cv2.resize(frame_bgr, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)

        pad_x = (self.input_size - resized_w) // 2
        pad_y = (self.input_size - resized_h) // 2
        canvas = np.full((self.input_size, self.input_size, 3), 114, dtype=np.uint8)
        canvas[pad_y : pad_y + resized_h, pad_x : pad_x + resized_w] = resized

        image = ncnn.Mat.from_pixels(
            canvas,
            ncnn.Mat.PixelType.PIXEL_BGR2RGB,
            self.input_size,
            self.input_size,
        )
        image.substract_mean_normalize([], [1 / 255.0, 1 / 255.0, 1 / 255.0])

        with self.lock:
            extractor = self.net.create_extractor()
            if extractor.input("in0", image) != 0:
                raise RuntimeError("NCNN pose input failed")
            result, output = extractor.extract("out0")
            if result != 0:
                raise RuntimeError("NCNN pose output failed")

        prediction = np.asarray(output)
        expected_rows = 5 + len(self.KEYPOINT_NAMES) * 3
        if prediction.ndim != 2 or prediction.shape[0] != expected_rows:
            raise RuntimeError(f"Unexpected NCNN pose output shape: {prediction.shape}")

        scores = prediction[4]
        candidate_indices = np.flatnonzero(scores >= self.confidence)
        boxes_xywh: list[list[int]] = []
        confidences: list[float] = []
        keypoints_by_candidate: list[list[list[float]]] = []

        for index in candidate_indices:
            center_x, center_y, width, height = prediction[:4, index]
            x = (float(center_x) - float(width) / 2 - pad_x) / scale
            y = (float(center_y) - float(height) / 2 - pad_y) / scale
            width = float(width) / scale
            height = float(height) / scale
            x1 = max(0, min(original_w - 1, int(round(x))))
            y1 = max(0, min(original_h - 1, int(round(y))))
            x2 = max(0, min(original_w - 1, int(round(x + width))))
            y2 = max(0, min(original_h - 1, int(round(y + height))))
            if x2 <= x1 or y2 <= y1:
                continue

            raw_keypoints = prediction[5:, index].reshape(len(self.KEYPOINT_NAMES), 3)
            keypoints = []
            for keypoint_x, keypoint_y, keypoint_confidence in raw_keypoints:
                decoded_x = max(0.0, min(original_w - 1.0, (float(keypoint_x) - pad_x) / scale))
                decoded_y = max(0.0, min(original_h - 1.0, (float(keypoint_y) - pad_y) / scale))
                keypoints.append([decoded_x, decoded_y, float(keypoint_confidence)])

            boxes_xywh.append([x1, y1, x2 - x1, y2 - y1])
            confidences.append(float(scores[index]))
            keypoints_by_candidate.append(keypoints)

        if not boxes_xywh:
            return []

        selected = cv2.dnn.NMSBoxes(boxes_xywh, confidences, self.confidence, self.nms_iou)
        if selected is None or len(selected) == 0:
            return []

        poses = []
        for selected_index in np.asarray(selected).reshape(-1):
            index = int(selected_index)
            x, y, width, height = boxes_xywh[index]
            poses.append(
                {
                    "confidence": confidences[index],
                    "box": [x, y, x + width, y + height],
                    "keypoints": keypoints_by_candidate[index],
                }
            )
        return poses
