from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from .events import EventBus
from .inference import NcnnObjectDetector
from .sources import PiCameraSource, RtspSource, UsbCameraSource
from .sources.base import CameraSource


@dataclass
class WorkerSnapshot:
    camera_id: str
    label: str
    source_type: str
    online: bool
    ai_enabled: bool
    person_count: int
    object_count: int
    detected_objects: dict[str, int]
    capture_fps: float
    last_frame_age: float | None
    error: str | None


class CameraWorker:
    def __init__(
        self,
        camera_config: dict[str, Any],
        source: CameraSource,
        detector: NcnnObjectDetector,
        event_bus: EventBus,
        jpeg_quality: int,
    ):
        self.config = camera_config
        self.camera_id = camera_config["id"]
        self.label = camera_config.get("label", self.camera_id)
        self.source_type = camera_config["type"]
        self.source = source
        self.detector = detector
        self.event_bus = event_bus
        self.jpeg_quality = jpeg_quality
        self.ai_enabled = bool(camera_config.get("ai_enabled", False))
        self.analysis_interval = 1.0 / max(float(camera_config.get("analysis_fps", 3)), 0.1)

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._jpeg: bytes | None = None
        self._detections: list[dict] = []
        self._online = False
        self._error: str | None = None
        self._last_frame_at: float | None = None
        self._capture_fps = 0.0
        self._person_present = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"camera-{self.camera_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._online = False
            self._error = message

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.source.open()
                with self._lock:
                    self._online = True
                    self._error = None
                self._capture_loop()
            except Exception as exc:
                self._set_error(str(exc))
            finally:
                self.source.close()

            if not self._stop.wait(5):
                continue

    def _capture_loop(self) -> None:
        frame_counter = 0
        fps_started = time.monotonic()
        next_analysis = 0.0

        while not self._stop.is_set():
            frame = self.source.read()
            now = time.monotonic()
            frame_counter += 1
            elapsed = now - fps_started
            if elapsed >= 2.0:
                self._capture_fps = frame_counter / elapsed
                frame_counter = 0
                fps_started = now

            if self.ai_enabled and now >= next_analysis:
                self._detections = self.detector.detect(frame)
                next_analysis = now + self.analysis_interval
                self._handle_person_state()

            annotated = frame.copy()
            self._draw_overlay(annotated)
            ok, encoded = cv2.imencode(
                ".jpg",
                annotated,
                [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
            )
            if not ok:
                continue

            with self._lock:
                self._jpeg = encoded.tobytes()
                self._online = True
                self._error = None
                self._last_frame_at = now

    def _handle_person_state(self) -> None:
        people = [item for item in self._detections if item["label"] == "person"]
        person_present = bool(people)
        if person_present == self._person_present:
            return

        self._person_present = person_present
        if person_present:
            confidence = max(item["confidence"] for item in people)
            self.event_bus.emit(
                self.camera_id,
                "person_detected",
                confidence,
                {"person_count": len(people), "source_type": self.source_type},
            )
        else:
            self.event_bus.emit(
                self.camera_id,
                "person_cleared",
                details={"source_type": self.source_type},
            )
        self.event_bus.publish_status(self.camera_id, self.status_dict())

    def _draw_overlay(self, frame: np.ndarray) -> None:
        for detection in self._detections:
            x1, y1, x2, y2 = detection["box"]
            confidence = detection["confidence"]
            label = detection["label"]
            color = (0, 220, 70) if label == "person" else (0, 185, 255)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"{label.upper()} {confidence:.2f}",
                (x1, max(24, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                color,
                2,
            )

        status = "AI ON" if self.ai_enabled else "MONITOR"
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 42), (18, 22, 30), -1)
        cv2.putText(
            frame,
            f"{self.label} | {status} | {self._capture_fps:.1f} FPS",
            (12, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (245, 245, 245),
            2,
        )

    def jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    def snapshot(self) -> WorkerSnapshot:
        with self._lock:
            age = None if self._last_frame_at is None else max(0.0, time.monotonic() - self._last_frame_at)
            detected_objects: dict[str, int] = {}
            for detection in self._detections:
                label = detection["label"]
                detected_objects[label] = detected_objects.get(label, 0) + 1
            return WorkerSnapshot(
                camera_id=self.camera_id,
                label=self.label,
                source_type=self.source_type,
                online=self._online and age is not None and age < 5.0,
                ai_enabled=self.ai_enabled,
                person_count=detected_objects.get("person", 0),
                object_count=sum(detected_objects.values()),
                detected_objects=detected_objects,
                capture_fps=round(self._capture_fps, 1),
                last_frame_age=round(age, 1) if age is not None else None,
                error=self._error,
            )

    def status_dict(self) -> dict[str, Any]:
        return self.snapshot().__dict__


class VisionPipeline:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.event_bus = EventBus(config["mqtt"])
        inference = config["inference"]
        self.detector = NcnnObjectDetector(
            model_dir=inference["model"],
            input_size=int(inference.get("input_size", 320)),
            confidence=float(inference.get("confidence", 0.35)),
            nms_iou=float(inference.get("nms_iou", 0.45)),
            threads=int(inference.get("threads", 4)),
        )
        self.workers: dict[str, CameraWorker] = {}
        for camera in config["cameras"]:
            if not camera.get("enabled", True):
                continue
            source = self._build_source(camera)
            self.workers[camera["id"]] = CameraWorker(
                camera,
                source,
                self.detector,
                self.event_bus,
                int(config["server"].get("jpeg_quality", 80)),
            )

    @staticmethod
    def _build_source(config: dict[str, Any]) -> CameraSource:
        source_type = config["type"]
        if source_type == "picamera2":
            return PiCameraSource(int(config["width"]), int(config["height"]), int(config["fps"]))
        if source_type == "v4l2":
            return UsbCameraSource(
                config["device"],
                int(config["width"]),
                int(config["height"]),
                int(config["fps"]),
                config.get("input_format", "MJPG"),
            )
        if source_type == "rtsp":
            return RtspSource(config.get("url", ""), config.get("transport", "tcp"))
        raise ValueError(f"Unsupported camera source: {source_type}")

    def start(self) -> None:
        self.event_bus.start()
        for worker in self.workers.values():
            worker.start()

    def stop(self) -> None:
        for worker in self.workers.values():
            worker.stop()
        self.event_bus.stop()

    def status(self) -> dict[str, Any]:
        return {
            "service": "smarthome-vision",
            "mqtt_connected": self.event_bus.connected,
            "cameras": [worker.status_dict() for worker in self.workers.values()],
        }

    def camera_jpeg(self, camera_id: str) -> bytes:
        worker = self.workers[camera_id]
        jpeg = worker.jpeg()
        if jpeg is not None:
            return jpeg

        snapshot = worker.snapshot()
        placeholder = np.full((480, 720, 3), (24, 27, 34), dtype=np.uint8)
        cv2.putText(placeholder, snapshot.label, (36, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (240, 240, 240), 2)
        cv2.putText(placeholder, snapshot.error or "Waiting for camera...", (36, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (80, 170, 255), 2)
        ok, encoded = cv2.imencode(".jpg", placeholder)
        return encoded.tobytes() if ok else b""

