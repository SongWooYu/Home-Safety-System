from __future__ import annotations

import threading
from pathlib import Path

import cv2
import ncnn
import numpy as np
import yaml


class NcnnObjectDetector:
    """YOLO11 NCNN COCO object detector without PyTorch or Ultralytics runtime."""

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
        metadata_path = model_path / "metadata.yaml"
        if not param_path.exists() or not bin_path.exists() or not metadata_path.exists():
            raise FileNotFoundError(f"NCNN model is incomplete: {model_path}")
        metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
        raw_names = metadata.get("names", {})
        if isinstance(raw_names, dict):
            self.class_names = [
                str(name) for _, name in sorted(raw_names.items(), key=lambda item: int(item[0]))
            ]
        elif isinstance(raw_names, list):
            self.class_names = [str(name) for name in raw_names]
        else:
            self.class_names = []
        if not self.class_names:
            raise RuntimeError(f"Class names are missing from {metadata_path}")

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

    def detect(self, frame_bgr: np.ndarray) -> list[dict]:
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
                raise RuntimeError("NCNN input failed")
            result, output = extractor.extract("out0")
            if result != 0:
                raise RuntimeError("NCNN output failed")

        prediction = np.asarray(output)
        if prediction.ndim != 2 or prediction.shape[0] < 5:
            raise RuntimeError(f"Unexpected NCNN output shape: {prediction.shape}")

        class_scores = prediction[4 : 4 + len(self.class_names)]
        if class_scores.shape[0] != len(self.class_names):
            raise RuntimeError(
                f"Model has {class_scores.shape[0]} class rows, expected {len(self.class_names)}"
            )
        class_ids = np.argmax(class_scores, axis=0)
        scores = class_scores[class_ids, np.arange(class_scores.shape[1])]
        candidate_indices = np.flatnonzero(scores >= self.confidence)
        boxes_xywh: list[list[int]] = []
        confidences: list[float] = []
        candidate_class_ids: list[int] = []

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
            boxes_xywh.append([x1, y1, x2 - x1, y2 - y1])
            candidate_class_ids.append(int(class_ids[index]))
            confidences.append(float(scores[index]))

        if not boxes_xywh:
            return []

        selected = cv2.dnn.NMSBoxesBatched(
            boxes_xywh,
            confidences,
            candidate_class_ids,
            self.confidence,
            self.nms_iou,
        )
        if selected is None or len(selected) == 0:
            return []

        detections = []
        for selected_index in np.asarray(selected).reshape(-1):
            index = int(selected_index)
            x, y, width, height = boxes_xywh[index]
            class_id = candidate_class_ids[index]
            detections.append(
                {
                    "class_id": class_id,
                    "label": self.class_names[class_id],
                    "confidence": confidences[index],
                    "box": [x, y, x + width, y + height],
                }
            )
        return detections

