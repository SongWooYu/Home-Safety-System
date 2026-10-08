from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from .events import EventBus
from .fall_detection import FallTracker
from .face_registry import FaceRegistry
from .gru_numpy import NumpyFallEnsemble
from .inference import NcnnPoseEstimator
from .temporal_fall import TemporalFallShadow
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
    known_faces: int
    unknown_faces: int
    capture_fps: float
    last_frame_age: float | None
    temporal_enabled: bool
    temporal_mode: str
    temporal_state: str
    temporal_alert_score: float
    temporal_best_track_id: int | None
    temporal_tracks: list[dict[str, Any]]
    error: str | None


class CameraWorker:
    def __init__(
        self,
        camera_config: dict[str, Any],
        source: CameraSource,
        pose_estimator: NcnnPoseEstimator | None,
        temporal_ensemble: NumpyFallEnsemble | None,
        face_registry: FaceRegistry | None,
        event_bus: EventBus,
        stream_width: int,
        stream_height: int,
        stream_fps: float,
        jpeg_quality: int,
        fall_config: dict[str, Any],
        face_config: dict[str, Any],
        status_publish_interval: float,
    ):
        self.config = camera_config
        self.camera_id = camera_config["id"]
        self.label = camera_config.get("label", self.camera_id)
        self.source_type = camera_config["type"]
        self.source = source
        self.pose_estimator = pose_estimator
        self.face_registry = face_registry
        self.event_bus = event_bus
        self.stream_width = max(1, stream_width)
        self.stream_height = max(1, stream_height)
        self.stream_interval = 1.0 / max(stream_fps, 1.0)
        self.jpeg_quality = jpeg_quality
        self.ai_enabled = bool(camera_config.get("ai_enabled", False))
        self.person_clear_seconds = float(camera_config.get("person_clear_seconds", 3.0))
        self.pose_enabled = bool(
            fall_config.get("enabled", False)
            and pose_estimator is not None
            and camera_config.get("fall_detection", True)
        )
        self.pose_interval = 1.0 / max(float(fall_config.get("analysis_fps", 1.5)), 0.1)
        self.status_publish_interval = max(status_publish_interval, 1.0)
        self.face_interval = 1.0 / max(float(face_config.get("analysis_fps", 1.0)), 0.1)
        self.face_enabled = bool(
            face_registry is not None
            and camera_config.get(
                "face_recognition",
                False,
            )
        )
        self.face_enrollment = bool(
            camera_config.get(
                "face_enrollment",
                False,
            )
        )
        self.fall_tracker = FallTracker(
            keypoint_confidence=float(fall_config.get("keypoint_confidence", 0.25)),
            transition_window=float(fall_config.get("transition_window", 3.0)),
            confirm_seconds=float(fall_config.get("confirm_seconds", 1.2)),
            recovery_seconds=float(fall_config.get("recovery_seconds", 2.0)),
        )

        temporal_config = fall_config.get(
            "temporal",
            {},
        )

        self.temporal_mode = str(
            temporal_config.get(
                "mode",
                "off",
            )
        )

        self.temporal_fall = None

        if (
            self.pose_enabled
            and temporal_ensemble is not None
            and temporal_config.get(
                "enabled",
                False,
            )
            and camera_config.get(
                "temporal_fall",
                False,
            )
        ):
            self.temporal_fall = TemporalFallShadow(
                ensemble=temporal_ensemble,
                sequence_length=int(
                    temporal_config.get(
                        "sequence_length",
                        20,
                    )
                ),
                keypoint_confidence=float(
                    temporal_config.get(
                        "keypoint_confidence",
                        0.25,
                    )
                ),
                threshold=float(
                    temporal_config.get(
                        "threshold",
                        0.92,
                    )
                ),
                consecutive=int(
                    temporal_config.get(
                        "consecutive",
                        1,
                    )
                ),
                max_missing_frames=int(
                    temporal_config.get(
                        "max_missing_frames",
                        10,
                    )
                ),
                expire_seconds=float(
                    temporal_config.get(
                        "expire_seconds",
                        1.5,
                    )
                ),
            )

        self._temporal_tracks: list[
            dict[str, Any]
        ] = []

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ai_thread: threading.Thread | None = None
        self._latest_frame: np.ndarray | None = None
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
        self._faces: list[dict] = []
        self._registration_frame: np.ndarray | None = None
        self._last_registration_frame_at = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name=f"camera-{self.camera_id}",
            daemon=True,
        )
        self._thread.start()

        if self.pose_enabled or self.face_enabled:
            self._ai_thread = threading.Thread(
                target=self._ai_loop,
                name=f"camera-ai-{self.camera_id}",
                daemon=True,
            )
            self._ai_thread.start()

    def stop(self) -> None:
        self._stop.set()

        if self._thread is not None:
            self._thread.join(timeout=3)

        if self._ai_thread is not None:
            self._ai_thread.join(timeout=3)

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

        next_status_publish = 0.0
        next_stream_frame = 0.0

        while not self._stop.is_set():

            frame = self.source.read()
            now = time.monotonic()

            # 최신 원본 frame을 AI thread와 공유한다.
            #
            # source.read()는 매번 새로운 ndarray를 반환하므로
            # 별도 copy를 하지 않아 capture 부하를 줄인다.
            with self._lock:
                self._latest_frame = frame

            # 얼굴 등록용 frame은 낮은 주기로만 copy.
            if (
                self.face_enrollment
                and now
                - self._last_registration_frame_at
                >= 0.2
            ):
                with self._lock:
                    self._registration_frame = (
                        frame.copy()
                    )

                self._last_registration_frame_at = (
                    now
                )

            # 실제 capture throughput 측정.
            frame_counter += 1

            elapsed = (
                now
                - fps_started
            )

            if elapsed >= 2.0:

                self._capture_fps = (
                    frame_counter
                    / elapsed
                )

                frame_counter = 0
                fps_started = now

            # Display/JPEG path.
            #
            # AI inference와 완전히 독립되어 있으므로
            # Pose/Face가 느려져도 stream FPS를 막지 않는다.
            if now >= next_stream_frame:

                annotated = frame.copy()

                self._draw_overlay(
                    annotated
                )

                if (
                    annotated.shape[1]
                    != self.stream_width
                    or annotated.shape[0]
                    != self.stream_height
                ):

                    annotated = cv2.resize(
                        annotated,
                        (
                            self.stream_width,
                            self.stream_height,
                        ),
                        interpolation=cv2.INTER_AREA,
                    )

                ok, encoded = cv2.imencode(
                    ".jpg",
                    annotated,
                    [
                        int(
                            cv2.IMWRITE_JPEG_QUALITY
                        ),
                        self.jpeg_quality,
                    ],
                )

                if ok:

                    with self._lock:

                        self._jpeg = (
                            encoded.tobytes()
                        )

                        self._online = True
                        self._error = None
                        self._last_frame_at = now

                next_stream_frame = (
                    now
                    + self.stream_interval
                )

            if now >= next_status_publish:

                self.event_bus.publish_status(
                    self.camera_id,
                    self.status_dict(),
                )

                next_status_publish = (
                    now
                    + self.status_publish_interval
                )

    def _ai_loop(self) -> None:

        next_pose_analysis = 0.0
        next_face_analysis = 0.0

        while not self._stop.is_set():

            now = time.monotonic()

            with self._lock:

                frame = (
                    self._latest_frame
                )

                online = (
                    self._online
                )

                last_frame_at = (
                    self._last_frame_at
                )

            if (
                frame is None
                or not online
                or last_frame_at is None
                or now - last_frame_at > 1.0
            ):

                self._stop.wait(
                    0.01
                )

                continue

            did_work = False


            # --------------------------------------
            # Pose / Fall
            # --------------------------------------

            if (
                self.pose_enabled
                and self.pose_estimator
                is not None
                and now
                >= next_pose_analysis
            ):

                # start-to-start scheduling:
                # inference 시간이 interval보다 짧으면
                # 정확히 목표 Hz에 가깝게 동작한다.
                next_pose_analysis = (
                    now
                    + self.pose_interval
                )

                try:

                    poses = (
                        self.pose_estimator
                        .estimate(
                            frame
                        )
                    )

                    detections = [
                        {
                            "class_id": 0,
                            "label": "person",
                            "confidence":
                                pose[
                                    "confidence"
                                ],
                            "box":
                                pose[
                                    "box"
                                ],
                        }
                        for pose
                        in poses
                    ]

                    with self._lock:

                        self._poses = poses
                        self._detections = (
                            detections
                        )

                    if self.ai_enabled:

                        self._handle_person_state()

                    pose_result = (
                        self.fall_tracker
                        .update(
                            poses,
                            frame.shape,
                            now,
                        )
                    )

                    if self.temporal_fall is not None:

                        temporal_tracks = (
                            self.temporal_fall
                            .update(
                                poses,
                                frame.shape,
                                now,
                            )
                        )

                        with self._lock:
                            self._temporal_tracks = (
                                temporal_tracks
                            )

                    if pose_result.event_type:

                        severity = (
                            "critical"
                            if (
                                pose_result
                                .event_type
                                == "fall_confirmed"
                            )
                            else "warning"
                        )

                        if (
                            pose_result
                            .event_type
                            == "fall_cleared"
                        ):
                            severity = (
                                "normal"
                            )

                        self.event_bus.emit(
                            self.camera_id,
                            pose_result.event_type,
                            pose_result.confidence,
                            {
                                "severity":
                                    severity,

                                "pose_state":
                                    pose_result.pose_state,

                                "source_type":
                                    self.source_type,

                                **pose_result.metrics,
                            },
                        )

                except Exception as exc:

                    with self._lock:
                        self._error = (
                            "pose: "
                            + str(exc)
                        )

                did_work = True


            # --------------------------------------
            # Face recognition
            # --------------------------------------

            if (
                self.face_enabled
                and self.face_registry
                is not None
                and now
                >= next_face_analysis
            ):

                next_face_analysis = (
                    now
                    + self.face_interval
                )

                try:

                    faces = (
                        self.face_registry
                        .identify(
                            frame
                        )
                    )

                except Exception:

                    faces = []

                with self._lock:

                    self._faces = (
                        faces
                    )

                did_work = True


            if not did_work:

                self._stop.wait(
                    0.005
                )

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

        for face in self._faces:
            x1, y1, x2, y2 = face["box"]
            color = (255, 200, 40) if face["registered"] else (80, 80, 255)
            label = "KNOWN" if face["registered"] else "UNKNOWN"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"{label} {face['similarity']:.2f}",
                (x1, min(frame.shape[0] - 8, y2 + 22)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
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

    def registration_frame(self) -> np.ndarray | None:
        with self._lock:
            return None if self._registration_frame is None else self._registration_frame.copy()

    def snapshot(self) -> WorkerSnapshot:
        with self._lock:
            age = (
                None
                if self._last_frame_at is None
                else max(
                    0.0,
                    time.monotonic()
                    - self._last_frame_at,
                )
            )

            detected_objects: dict[
                str,
                int,
            ] = {}

            for detection in self._detections:
                label = detection["label"]

                detected_objects[
                    label
                ] = (
                    detected_objects.get(
                        label,
                        0,
                    )
                    + 1
                )

            temporal_tracks = [
                dict(item)
                for item
                in self._temporal_tracks
            ]

            ready_tracks = [
                item
                for item
                in temporal_tracks
                if item.get(
                    "ready",
                    False,
                )
            ]

            if ready_tracks:
                best_temporal = max(
                    ready_tracks,
                    key=lambda item:
                        float(
                            item.get(
                                "alert_score",
                                0.0,
                            )
                        ),
                )

            elif temporal_tracks:
                best_temporal = max(
                    temporal_tracks,
                    key=lambda item:
                        int(
                            item.get(
                                "buffer",
                                0,
                            )
                        ),
                )

            else:
                best_temporal = None

            if best_temporal is not None:
                temporal_state = str(
                    best_temporal.get(
                        "state",
                        "warming",
                    )
                )

                temporal_alert_score = float(
                    best_temporal.get(
                        "alert_score",
                        0.0,
                    )
                )

                temporal_best_track_id = int(
                    best_temporal[
                        "track_id"
                    ]
                )

            else:
                temporal_state = (
                    "warming"
                    if self.temporal_fall
                    is not None
                    else "off"
                )

                temporal_alert_score = 0.0
                temporal_best_track_id = None

            return WorkerSnapshot(
                camera_id=self.camera_id,
                label=self.label,
                source_type=self.source_type,

                online=(
                    self._online
                    and age is not None
                    and age < 5.0
                ),

                ai_enabled=self.ai_enabled,

                person_count=(
                    detected_objects.get(
                        "person",
                        0,
                    )
                ),

                object_count=sum(
                    detected_objects.values()
                ),

                detected_objects=(
                    detected_objects
                ),

                pose_enabled=self.pose_enabled,

                pose_state=(
                    self.fall_tracker
                    .pose_state
                ),

                fall_state=(
                    self.fall_tracker
                    .fall_state
                ),

                fall_confidence=round(
                    self.fall_tracker
                    .confidence,
                    3,
                ),

                known_faces=sum(
                    1
                    for face
                    in self._faces
                    if face[
                        "registered"
                    ]
                ),

                unknown_faces=sum(
                    1
                    for face
                    in self._faces
                    if not face[
                        "registered"
                    ]
                ),

                capture_fps=round(
                    self._capture_fps,
                    1,
                ),

                last_frame_age=(
                    round(
                        age,
                        1,
                    )
                    if age is not None
                    else None
                ),

                temporal_enabled=(
                    self.temporal_fall
                    is not None
                ),

                temporal_mode=(
                    self.temporal_mode
                    if self.temporal_fall
                    is not None
                    else "off"
                ),

                temporal_state=(
                    temporal_state
                ),

                temporal_alert_score=round(
                    temporal_alert_score,
                    4,
                ),

                temporal_best_track_id=(
                    temporal_best_track_id
                ),

                temporal_tracks=(
                    temporal_tracks
                ),

                error=self._error,
            )

    def status_dict(self) -> dict[str, Any]:
        return self.snapshot().__dict__


class VisionPipeline:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.event_bus = EventBus(config["mqtt"])
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

        self.temporal_ensemble: (
            NumpyFallEnsemble | None
        ) = None

        self.temporal_error: (
            str | None
        ) = None

        temporal_config = (
            fall_config.get(
                "temporal",
                {},
            )
        )

        if temporal_config.get(
            "enabled",
            False,
        ):
            try:
                self.temporal_ensemble = (
                    NumpyFallEnsemble(
                        temporal_config[
                            "model"
                        ]
                    )
                )

            except Exception as exc:
                self.temporal_error = (
                    str(exc)
                )

        face_config = config.get("face_recognition", {})
        self.face_registry: FaceRegistry | None = None
        self.face_error: str | None = None
        if face_config.get("enabled", False):
            try:
                self.face_registry = FaceRegistry(
                    detector_model=face_config["detector_model"],
                    recognizer_model=face_config["recognizer_model"],
                    database_path=face_config["database"],
                    match_threshold=float(face_config.get("match_threshold", 0.45)),
                    detection_width=int(face_config.get("detection_width", 640)),
                    min_face_size=int(face_config.get("min_face_size", 70)),
                )
            except Exception as exc:
                self.face_error = str(exc)
        self.workers: dict[str, CameraWorker] = {}
        for camera in config["cameras"]:
            if not camera.get("enabled", True):
                continue
            source = self._build_source(camera)
            self.workers[camera["id"]] = CameraWorker(
                camera,
                source,
                self.pose_estimator,
                self.temporal_ensemble,
                self.face_registry,
                self.event_bus,
                int(config["server"].get("stream_width", 640)),
                int(config["server"].get("stream_height", 360)),
                float(config["server"].get("stream_fps", 15)),
                int(config["server"].get("jpeg_quality", 80)),
                fall_config,
                face_config,
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
            "temporal_fall_enabled": self.temporal_ensemble is not None,
            "temporal_fall_error": self.temporal_error,
            "face_recognition_enabled": self.face_registry is not None,
            "face_recognition_error": self.face_error,
            "registered_people": len(self.registered_faces()),
            "cameras": [worker.status_dict() for worker in self.workers.values()],
        }


    def registered_faces(self) -> list[dict]:
        return self.face_registry.list_people() if self.face_registry is not None else []

    def enroll_face(self, camera_id: str, name: str, view: str = "front") -> dict:
        if self.face_registry is None:
            raise RuntimeError(self.face_error or "얼굴 인식 기능을 사용할 수 없습니다.")
        worker = self.workers.get(camera_id)
        if worker is None or not worker.face_enrollment:
            raise ValueError("얼굴 등록은 Camera Module 3 또는 웹캠만 사용할 수 있습니다.")

        frames: list[np.ndarray] = []
        for _ in range(5):
            frame = worker.registration_frame()
            if frame is not None:
                frames.append(frame)
            time.sleep(0.25)
        return self.face_registry.enroll(name, frames, view)

    def delete_face(self, person_id: str) -> bool:
        return self.face_registry is not None and self.face_registry.delete(person_id)
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

