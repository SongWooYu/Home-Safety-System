from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from .events import EventBus
from .fall_detection import FallTracker
from .inference import NcnnObjectDetector, NcnnPoseEstimator
from .sources import PiCameraSource, RtspSource, UsbCameraSource
from .sources.base import CameraSource


POSE_SKELETON = (
    (5, 7), (7, 9),
    (6, 8), (8, 10),
    (5, 6),
    (5, 11), (6, 12),
    (11, 12),
    (11, 13), (13, 15),
    (12, 14), (14, 16),
)


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
    pose_enabled: bool
    pose_state: str
    fall_state: str
    fall_confidence: float
    capture_fps: float
    last_frame_age: float | None
    error: str | None


class CameraWorker:
    def __init__(
        self,
        camera_config: dict[str, Any],
        source: CameraSource,
        detector: NcnnObjectDetector,
        pose_estimator: NcnnPoseEstimator | None,
        event_bus: EventBus,
        jpeg_quality: int,
        fall_config: dict[str, Any],
        status_publish_interval: float,
    ):
        self.config = camera_config
        self.camera_id = camera_config["id"]
        self.label = camera_config.get("label", self.camera_id)
        self.source_type = camera_config["type"]
        self.source = source
        self.detector = detector
        self.pose_estimator = pose_estimator
        self.event_bus = event_bus
        self.jpeg_quality = jpeg_quality
        self.ai_enabled = bool(camera_config.get("ai_enabled", False))
        self.analysis_interval = 1.0 / max(float(camera_config.get("analysis_fps", 3)), 0.1)
        self.person_clear_seconds = float(camera_config.get("person_clear_seconds", 3.0))
        self.pose_enabled = bool(
            fall_config.get("enabled", False)
            and pose_estimator is not None
            and camera_config.get("fall_detection", True)
        )
        self.pose_interval = 1.0 / max(float(fall_config.get("analysis_fps", 1.5)), 0.1)
        self.status_publish_interval = max(status_publish_interval, 1.0)
        self.fall_tracker = FallTracker(
            keypoint_confidence=float(fall_config.get("keypoint_confidence", 0.25)),
            transition_window=float(fall_config.get("transition_window", 3.0)),
            confirm_seconds=float(fall_config.get("confirm_seconds", 1.2)),
            recovery_seconds=float(fall_config.get("recovery_seconds", 2.0)),
            motion_window_seconds=float(fall_config.get("motion_window_seconds", 1.5)),
            motion_min_drop=float(fall_config.get("motion_min_drop", 0.10)),
            motion_max_compression=float(fall_config.get("motion_max_compression", 0.78)),
        )

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._jpeg: bytes | None = None
        self._detections: list[dict] = []
        self._poses: list[dict] = []
        self._online = False
        self._error: str | None = None
        self._last_frame_at: float | None = None
        self._capture_fps = 0.0
        self._person_present = False
        self._person_seen_streak = 0
        self._last_person_seen_at: float | None = None

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
        next_pose_analysis = 0.0
        next_status_publish = 0.0

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

            if self.pose_enabled and self.pose_estimator is not None and now >= next_pose_analysis:
                self._poses = self.pose_estimator.estimate(frame)
                pose_result = self.fall_tracker.update(self._poses, frame.shape, now)
                next_pose_analysis = now + self.pose_interval
                if pose_result.event_type:
                    severity = "critical" if pose_result.event_type == "fall_confirmed" else "warning"
                    if pose_result.event_type == "fall_cleared":
                        severity = "normal"
                    self.event_bus.emit(
                        self.camera_id,
                        pose_result.event_type,
                        pose_result.confidence,
                        {
                            "severity": severity,
                            "pose_state": pose_result.pose_state,
                            "source_type": self.source_type,
                            **pose_result.metrics,
                        },
                    )

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

            if now >= next_status_publish:
                self.event_bus.publish_status(self.camera_id, self.status_dict())
                next_status_publish = now + self.status_publish_interval

    def _handle_person_state(self) -> None:
        people = [item for item in self._detections if item["label"] == "person"]
        now = time.monotonic()
        if people:
            self._person_seen_streak += 1
            self._last_person_seen_at = now
        else:
            self._person_seen_streak = 0

        person_present = self._person_present
        if not self._person_present and self._person_seen_streak >= 2:
            person_present = True
        elif (
            self._person_present
            and self._last_person_seen_at is not None
            and now - self._last_person_seen_at >= self.person_clear_seconds
        ):
            person_present = False
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
        for pose in self._poses:
            keypoints = pose["keypoints"]
            for start, end in POSE_SKELETON:
                if keypoints[start][2] < 0.25 or keypoints[end][2] < 0.25:
                    continue
                start_point = (int(keypoints[start][0]), int(keypoints[start][1]))
                end_point = (int(keypoints[end][0]), int(keypoints[end][1]))
                cv2.line(frame, start_point, end_point, (255, 210, 70), 2)
            for x, y, confidence in keypoints:
                if confidence >= 0.25:
                    cv2.circle(frame, (int(x), int(y)), 3, (255, 230, 120), -1)

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

        if self.pose_enabled and self.fall_tracker.fall_state != "normal":
            is_confirmed = self.fall_tracker.fall_state == "confirmed"
            fall_color = (30, 30, 255) if is_confirmed else (0, 165, 255)
            fall_label = "FALL CONFIRMED" if is_confirmed else "FALL SUSPECTED"
            cv2.rectangle(frame, (0, 42), (frame.shape[1], 82), fall_color, -1)
            cv2.putText(
                frame,
                f"{fall_label} | {self.fall_tracker.confidence:.2f}",
                (12, 70),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
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
                pose_enabled=self.pose_enabled,
                pose_state=self.fall_tracker.pose_state,
                fall_state=self.fall_tracker.fall_state,
                fall_confidence=round(self.fall_tracker.confidence, 3),
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
        fall_config = config.get("fall_detection", {})
        self.pose_estimator: NcnnPoseEstimator | None = None
        if fall_config.get("enabled", False):
            self.pose_estimator = NcnnPoseEstimator(
                model_dir=fall_config["model"],
                input_size=int(fall_config.get("input_size", 320)),
                confidence=float(fall_config.get("confidence", 0.35)),
                nms_iou=float(fall_config.get("nms_iou", 0.45)),
                threads=int(fall_config.get("threads", 2)),
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
                self.pose_estimator,
                self.event_bus,
                int(config["server"].get("jpeg_quality", 80)),
                fall_config,
                float(config["mqtt"].get("status_interval_seconds", 5)),
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

