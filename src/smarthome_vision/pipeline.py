from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .events import EventBus
from .face_registry import FaceRegistry
from .presentation import analysis_readiness
from .inference import HailoPoseEstimator
from .sources import PiCameraSource, RtspSource
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


EDGEFALL_STATE_COLORS = {
    "normal": (45, 165, 70),
    "suspected": (0, 165, 255),
    "fallen": (30, 30, 255),
    "recovering": (180, 80, 255),
    "warming": (95, 105, 120),
}


def select_edgefall_track(
    tracks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Select the same visible-first EdgeFall track for status and overlay."""
    visible = [item for item in tracks if item.get("visible", False)]
    candidates = visible or tracks
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            bool(item.get("fall_detected", False)),
            float(item.get("temporal_probability", 0.0)),
        ),
    )


def pose_visible_keypoint_ratio(
    poses: list[dict],
    confidence: float = 0.25,
) -> float:
    """Return visible COCO keypoints divided by all keypoints in detections."""
    total = 0
    visible = 0
    for pose in poses:
        for keypoint in pose.get("keypoints", []):
            total += 1
            if len(keypoint) >= 3 and float(keypoint[2]) >= confidence:
                visible += 1
    return visible / total if total else 0.0


def draw_face_label(
    frame: np.ndarray,
    label: str,
    origin: tuple[int, int],
    color: tuple[int, int, int],
    face_font: Any | None,
) -> None:
    """Use OpenCV for ASCII labels and FreeType only for non-ASCII text."""
    if label.isascii():
        cv2.putText(
            frame,
            label,
            origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )
        return

    if face_font is not None:
        try:
            face_font.putText(
                frame,
                label,
                # FreeType with bottomLeftOrigin=False places the glyph below
                # this origin; adapt to the baseline used by cv2.putText.
                (origin[0], origin[1] - 21),
                21,
                color,
                -1,
                cv2.LINE_AA,
                False,
            )
            return
        except cv2.error:
            pass

    fallback = "UNKNOWN" if label.startswith("미등록") else "KNOWN"
    score = label.rsplit(" ", 1)[-1]
    cv2.putText(
        frame,
        f"{fallback} {score}",
        origin,
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        color,
        2,
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
    pose_backend: str
    face_enabled: bool
    rule_mode: str
    pose_state: str
    fall_state: str
    fall_confidence: float
    known_faces: int
    unknown_faces: int
    recognized_faces: list[dict[str, Any]]
    capture_fps: float
    last_frame_age: float | None
    source_backend: str
    source_buffer_age_ms: float
    overlay_stream_clients: int
    clean_stream_clients: int
    capture_frame_seq: int
    pose_target_fps: float
    pose_effective_fps: float
    pose_inference_ms: float
    pose_inference_p95_ms: float
    pose_visible_keypoint_ratio: float
    pose_input_age_ms: float
    pose_unique_frames: int
    pose_source_frames_skipped: int
    pose_duplicate_frames_prevented: int
    hailo_shadow_enabled: bool
    hailo_shadow_model: str | None
    hailo_shadow_state: str
    hailo_shadow_person_count: int
    hailo_shadow_effective_fps: float
    hailo_shadow_inference_ms: float
    hailo_shadow_inference_p95_ms: float
    hailo_shadow_visible_keypoint_ratio: float
    hailo_shadow_same_frame: bool
    hailo_shadow_error: str | None
    edgefall_shadow_enabled: bool
    edgefall_shadow_profile: str | None
    edgefall_shadow_state: str
    edgefall_shadow_probability: float
    edgefall_shadow_best_track_id: int | None
    edgefall_shadow_tracks: list[dict[str, Any]]
    edgefall_shadow_error: str | None
    temporal_enabled: bool
    temporal_mode: str
    temporal_state: str
    temporal_alert_score: float
    temporal_best_track_id: int | None
    temporal_tracks: list[dict[str, Any]]
    temporal_observation_logging: bool
    temporal_observation_log_error: str | None
    error: str | None


class CameraWorker:
    def __init__(
        self,
        camera_config: dict[str, Any],
        source: CameraSource,
        pose_estimator: Any | None,
        hailo_shadow_estimator: Any | None,
        hailo_shadow_error: str | None,
        temporal_ensemble: Any | None,
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
        hailo_shadow_config = fall_config.get("hailo_shadow", {})
        self.hailo_shadow_estimator = hailo_shadow_estimator
        self.hailo_shadow_configured = bool(
            hailo_shadow_config.get("enabled", False)
            and camera_config.get("fall_detection", True)
        )
        self.hailo_shadow_enabled = bool(
            self.hailo_shadow_configured
            and hailo_shadow_estimator is not None
        )
        self.hailo_shadow_run_when_viewed = bool(
            hailo_shadow_config.get("run_when_viewed", True)
        )
        self.hailo_shadow_keypoint_confidence = float(
            hailo_shadow_config.get("keypoint_confidence", 0.25)
        )
        self.hailo_shadow_target_fps = max(
            float(hailo_shadow_config.get("analysis_fps", 15.0)),
            0.1,
        )
        self.hailo_shadow_interval = 1.0 / self.hailo_shadow_target_fps
        self._hailo_shadow_error = (
            hailo_shadow_error
            if self.hailo_shadow_configured
            else None
        )
        self.edgefall_shadow: Any | None = None
        self._edgefall_shadow_error: str | None = None
        edgefall_config = hailo_shadow_config.get("edgefall", {})
        if (
            self.hailo_shadow_configured
            and edgefall_config.get("enabled", False)
        ):
            try:
                from .edgefall_shadow import EdgeFallShadow

                self.edgefall_shadow = EdgeFallShadow(
                    library_path=edgefall_config["library"],
                    keypoint_confidence=float(
                        edgefall_config.get(
                            "keypoint_confidence",
                            self.hailo_shadow_keypoint_confidence,
                        )
                    ),
                )
            except Exception as exc:
                self._edgefall_shadow_error = str(exc)
        self.face_registry = face_registry
        self.event_bus = event_bus
        self.stream_width = max(1, stream_width)
        self.stream_height = max(1, stream_height)
        self.stream_fps = max(stream_fps, 1.0)
        self.stream_interval = 1.0 / self.stream_fps
        self.jpeg_quality = jpeg_quality
        self.ai_enabled = bool(camera_config.get("ai_enabled", False))
        self.person_clear_seconds = float(camera_config.get("person_clear_seconds", 3.0))
        self.pose_enabled = bool(
            fall_config.get("enabled", False)
            and pose_estimator is not None
            and camera_config.get("fall_detection", True)
        )
        self.pose_target_fps = max(
            float(fall_config.get("analysis_fps", 1.5)),
            0.1,
        )
        self.pose_interval = 1.0 / self.pose_target_fps
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
        self._face_font = None
        face_font_path = Path(
            str(
                face_config.get(
                    "label_font",
                    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                )
            )
        )
        if self.face_enabled and face_font_path.is_file() and hasattr(cv2, "freetype"):
            try:
                self._face_font = cv2.freetype.createFreeType2()
                self._face_font.loadFontData(fontFileName=str(face_font_path), idx=0)
            except cv2.error:
                self._face_font = None
        # The former Rule and B76 GRU paths are intentionally absent from the
        # production worker. Hailo YOLOv8 pose and EdgeFall own the fall state.
        self.rule_mode = "off"
        self.temporal_mode = "off"
        self.temporal_fall = None
        self.shadow_log = None
        self._fall_state = "normal"
        self._fall_confidence = 0.0
        self._pose_state = "unknown"

        edgefall_config = fall_config.get("edgefall", {})
        self._diagnostic_log = None
        self._diagnostic_log_error = None
        diagnostic_config = edgefall_config.get("diagnostics", {})
        if self.pose_enabled and diagnostic_config.get("enabled", False):
            try:
                from .diagnostic_log import DiagnosticLog
                self._diagnostic_log = DiagnosticLog(
                    diagnostic_config["path"],
                    int(diagnostic_config.get("max_bytes", 20_000_000)),
                    int(diagnostic_config.get("backups", 2)),
                )
            except Exception as exc:
                self._diagnostic_log_error = str(exc)
        self.edgefall_publish_mqtt = bool(
            edgefall_config.get("publish_mqtt", True)
        )
        self.edgefall_shadow = None
        self._edgefall_shadow_error = None
        if self.pose_enabled and edgefall_config.get("enabled", False):
            try:
                from .edgefall_shadow import EdgeFallRuntime

                self.edgefall_shadow = EdgeFallRuntime(
                    library_path=edgefall_config["library"],
                    keypoint_confidence=float(
                        edgefall_config.get("keypoint_confidence", 0.25)
                    ),
                )
            except Exception as exc:
                self._edgefall_shadow_error = str(exc)

        self._temporal_tracks: list[
            dict[str, Any]
        ] = []

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ai_thread: threading.Thread | None = None
        self._latest_frame: np.ndarray | None = None
        self._latest_frame_seq = 0
        self._latest_frame_captured_at: float | None = None
        self._jpeg: bytes | None = None
        self._clean_jpeg: bytes | None = None
        self._overlay_stream_clients = 0
        self._clean_stream_clients = 0
        self._detections: list[dict] = []
        self._poses: list[dict] = []
        self._online = False
        self._error: str | None = None
        self._last_frame_at: float | None = None
        self._capture_fps = 0.0
        self._source_buffer_age_ms = 0.0
        self._person_present = False
        self._person_seen_streak = 0
        self._last_person_seen_at: float | None = None
        self._faces: list[dict] = []
        self._smoothed_faces: list[dict] = []
        self._registration_frame: np.ndarray | None = None
        self._last_registration_frame_at = 0.0
        self._pose_completed_at = deque(maxlen=120)
        self._pose_latency_ms = deque(maxlen=120)
        self._pose_input_age_ms = 0.0
        self._pose_frame_seq = 0
        self._pose_unique_frames = 0
        self._pose_source_frames_skipped = 0
        self._pose_duplicate_frames_prevented = 0
        self._hailo_shadow_poses: list[dict] = []
        self._hailo_shadow_completed_at = deque(maxlen=120)
        self._hailo_shadow_latency_ms = deque(maxlen=120)
        self._hailo_shadow_frame_seq = 0
        self._edgefall_shadow_tracks: list[dict[str, Any]] = []
        self._edgefall_track_states: dict[int, str] = {}
        self._edgefall_event_ids: dict[int, int] = {}
        self._edgefall_empty_since: float | None = None

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

        close_edgefall = getattr(self.edgefall_shadow, "close", None)
        if callable(close_edgefall):
            close_edgefall()
        if self._diagnostic_log is not None:
            self._diagnostic_log.close()

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
                self._latest_frame_seq += 1
                self._latest_frame_captured_at = now
                self._last_frame_at = now
                self._source_buffer_age_ms = float(
                    getattr(self.source, "buffer_age_ms", 0.0)
                )
                self._online = True
                self._error = None

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
                    self._last_registration_frame_at = now

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
                with self._lock:
                    overlay_requested = self._overlay_stream_clients > 0
                    clean_requested = self._clean_stream_clients > 0

                if overlay_requested or clean_requested:
                    source_shape = frame.shape
                    stream_frame = frame
                    if (
                        stream_frame.shape[1] != self.stream_width
                        or stream_frame.shape[0] != self.stream_height
                    ):
                        stream_frame = cv2.resize(
                            stream_frame,
                            (self.stream_width, self.stream_height),
                            interpolation=cv2.INTER_AREA,
                        )

                    clean_jpeg = None
                    if clean_requested:
                        ok, encoded = cv2.imencode(
                            ".jpg",
                            stream_frame,
                            [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
                        )
                        if ok:
                            clean_jpeg = encoded.tobytes()

                    overlay_jpeg = None
                    if overlay_requested:
                        annotated = stream_frame.copy()
                        self._draw_overlay(annotated, source_shape)
                        ok, encoded = cv2.imencode(
                            ".jpg",
                            annotated,
                            [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
                        )
                        if ok:
                            overlay_jpeg = encoded.tobytes()

                    with self._lock:
                        if clean_jpeg is not None:
                            self._clean_jpeg = clean_jpeg
                        if overlay_jpeg is not None:
                            self._jpeg = overlay_jpeg

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
        next_hailo_analysis = 0.0
        next_face_analysis = 0.0
        last_pose_frame_seq = 0
        last_hailo_frame_seq = 0
        last_face_frame_seq = 0
        duplicate_counted_seq = -1

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

                frame_seq = (
                    self._latest_frame_seq
                )

                frame_captured_at = (
                    self._latest_frame_captured_at
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

            pose_due = (
                self.pose_enabled
                and self.pose_estimator
                is not None
                and now
                >= next_pose_analysis
            )

            if (
                pose_due
                and frame_seq
                == last_pose_frame_seq
            ):

                if duplicate_counted_seq != frame_seq:
                    with self._lock:
                        self._pose_duplicate_frames_prevented += 1
                    duplicate_counted_seq = frame_seq

            elif pose_due:

                # Only a newly captured frame can enter the temporal buffer.
                # This prevents a stalled RTSP frame from being repeated at 10 Hz.
                previous_pose_frame_seq = last_pose_frame_seq
                last_pose_frame_seq = frame_seq
                duplicate_counted_seq = -1

                next_pose_analysis = (
                    now
                    + self.pose_interval
                )

                source_frames_skipped = (
                    max(
                        0,
                        frame_seq
                        - previous_pose_frame_seq
                        - 1,
                    )
                    if previous_pose_frame_seq
                    else 0
                )

                input_age_ms = (
                    max(
                        0.0,
                        now - frame_captured_at,
                    )
                    * 1000.0
                    if frame_captured_at
                    is not None
                    else 0.0
                )

                pose_started = time.perf_counter()

                try:

                    poses = (
                        self.pose_estimator
                        .estimate(
                            frame
                        )
                    )

                    pose_finished = time.monotonic()
                    pose_latency_ms = (
                        time.perf_counter()
                        - pose_started
                    ) * 1000.0

                    with self._lock:
                        self._pose_unique_frames += 1
                        self._pose_source_frames_skipped += source_frames_skipped
                        self._pose_input_age_ms = input_age_ms
                        self._pose_frame_seq = frame_seq
                        self._pose_latency_ms.append(pose_latency_ms)
                        self._pose_completed_at.append(pose_finished)

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

                    edgefall_tracks: list[dict[str, Any]] = []
                    edgefall_error = self._edgefall_shadow_error
                    if self.edgefall_shadow is not None:
                        try:
                            edgefall_tracks = self.edgefall_shadow.update(
                                poses,
                                frame.shape[1],
                                frame.shape[0],
                                pose_finished,
                            )
                            edgefall_error = None
                            self._record_edgefall_transitions(edgefall_tracks)
                        except Exception as exc:
                            edgefall_error = str(exc)

                    with self._lock:
                        self._edgefall_shadow_tracks = edgefall_tracks
                        self._edgefall_shadow_error = edgefall_error
                    if self._diagnostic_log is not None:
                        self._diagnostic_log.record({
                            "schema_version": 1,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "monotonic_sec": pose_finished,
                            "camera_id": self.camera_id,
                            "frame_seq": frame_seq,
                            "frame_size": [frame.shape[1], frame.shape[0]],
                            "profile": getattr(self.edgefall_shadow, "profile", None),
                            "input_age_ms": input_age_ms,
                            "inference_ms": pose_latency_ms,
                            "poses": poses,
                            "tracks": edgefall_tracks,
                            "error": edgefall_error,
                        })

                except Exception as exc:

                    with self._lock:
                        self._error = (
                            "pose: "
                            + str(exc)
                        )

                did_work = True


            # --------------------------------------
            # Historical parallel Hailo comparison path. Production config
            # never enables it; the single primary Hailo path above is used.
            # --------------------------------------

            hailo_requested = self._hailo_shadow_requested()
            hailo_due = (
                hailo_requested
                and now >= next_hailo_analysis
                and frame_seq != last_hailo_frame_seq
            )

            if hailo_due:
                last_hailo_frame_seq = frame_seq
                next_hailo_analysis = now + self.hailo_shadow_interval
                self._update_hailo_shadow(frame, frame_seq)
                did_work = True
            elif not hailo_requested:
                with self._lock:
                    self._hailo_shadow_poses = []
                    # The primary Hailo path owns the production EdgeFall
                    # tracks. Disabling a historical comparison must not
                    # erase a result computed earlier in this same loop.
                    if not self.pose_enabled:
                        self._edgefall_shadow_tracks = []


            # --------------------------------------
            # Face recognition
            # --------------------------------------

            if (
                self.face_enabled
                and self.face_registry
                is not None
                and now
                >= next_face_analysis
                and frame_seq
                != last_face_frame_seq
            ):

                last_face_frame_seq = frame_seq

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

                    faces = self._smooth_face_results(faces)

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

    def _smooth_face_results(self, faces: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Reduce YuNet box jitter without adding a stale-frame queue."""
        previous = self._smoothed_faces
        smoothed: list[dict[str, Any]] = []
        for face in faces:
            current = dict(face)
            x1, y1, x2, y2 = (float(value) for value in current["box"])
            best: dict[str, Any] | None = None
            best_iou = 0.0
            for candidate in previous:
                px1, py1, px2, py2 = (
                    float(value) for value in candidate["box"]
                )
                ix1, iy1 = max(x1, px1), max(y1, py1)
                ix2, iy2 = min(x2, px2), min(y2, py2)
                intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
                union = (
                    max(0.0, x2 - x1) * max(0.0, y2 - y1)
                    + max(0.0, px2 - px1) * max(0.0, py2 - py1)
                    - intersection
                )
                iou = intersection / union if union > 0 else 0.0
                if iou > best_iou:
                    best_iou = iou
                    best = candidate
            if best is not None and best_iou >= 0.20:
                # Favor the newest detection so the box follows motion quickly.
                alpha = 0.68
                current["box"] = [
                    int(round(alpha * value + (1.0 - alpha) * old))
                    for value, old in zip(current["box"], best["box"])
                ]
            smoothed.append(current)
        self._smoothed_faces = smoothed
        return smoothed

    def _hailo_shadow_requested(self) -> bool:
        if not self.hailo_shadow_enabled:
            return False
        if not self.hailo_shadow_run_when_viewed:
            return True
        with self._lock:
            return self._overlay_stream_clients > 0

    def _update_hailo_shadow(
        self,
        frame: np.ndarray,
        frame_seq: int,
    ) -> None:
        """Run Hailo and EdgeFall metadata shadow without affecting alarms."""
        if not self._hailo_shadow_requested():
            with self._lock:
                self._hailo_shadow_poses = []
            return

        started = time.perf_counter()
        try:
            poses = self.hailo_shadow_estimator.estimate(frame)
        except Exception as exc:
            with self._lock:
                self._hailo_shadow_poses = []
                self._hailo_shadow_error = str(exc)
            return

        finished = time.monotonic()
        latency_ms = (time.perf_counter() - started) * 1000.0
        edgefall_tracks: list[dict[str, Any]] = []
        edgefall_error: str | None = self._edgefall_shadow_error
        if self.edgefall_shadow is not None:
            try:
                edgefall_tracks = self.edgefall_shadow.update(
                    poses,
                    frame.shape[1],
                    frame.shape[0],
                    finished,
                )
                edgefall_error = None
                self._record_edgefall_transitions(edgefall_tracks)
            except Exception as exc:
                edgefall_error = str(exc)
        with self._lock:
            self._hailo_shadow_poses = poses
            self._edgefall_shadow_tracks = edgefall_tracks
            self._edgefall_shadow_error = edgefall_error
            self._hailo_shadow_frame_seq = frame_seq
            self._hailo_shadow_latency_ms.append(latency_ms)
            self._hailo_shadow_completed_at.append(finished)
            self._hailo_shadow_error = None

    def _record_edgefall_transitions(
        self,
        tracks: list[dict[str, Any]],
    ) -> None:
        """Translate EdgeFall state changes to the existing Pi4 MQTT contract."""
        now = time.monotonic()
        if tracks:
            self._edgefall_empty_since = None
        elif self._fall_state != "normal":
            if self._edgefall_empty_since is None:
                self._edgefall_empty_since = now
            elif now - self._edgefall_empty_since >= 2.0:
                self.event_bus.emit(
                    self.camera_id,
                    "fall_cleared",
                    0.0,
                    {
                        "severity": "normal",
                        "source_type": self.source_type,
                        "backend": "hailo_edgefall",
                        "reason": "track_lost",
                        "shadow": False,
                        "published_to_mqtt": self.edgefall_publish_mqtt,
                    },
                    publish=self.edgefall_publish_mqtt,
                )
                self._fall_state = "normal"
                self._fall_confidence = 0.0
                self._pose_state = "unknown"
                self._edgefall_empty_since = None
        if not tracks:
            self._edgefall_track_states = {}
            return

        current_states: dict[int, str] = {}
        previous_states = self._edgefall_track_states
        states = [str(item.get("state", "normal")) for item in tracks]

        for track in tracks:
            track_id = int(track["track_id"])
            state = str(track.get("state", "normal"))
            previous = previous_states.get(track_id)
            current_states[track_id] = state

            event_id = int(track.get("event_id", 0))
            is_new_fall_event = bool(track.get("fall_event", False)) and (
                event_id > 0
                and self._edgefall_event_ids.get(track_id) != event_id
            )
            transition: str | None = None
            if is_new_fall_event:
                transition = "fall_confirmed"
                self._edgefall_event_ids.pop(track_id, None)
                self._edgefall_event_ids[track_id] = event_id
                # Native track IDs are monotonic, not retained people. Keep only
                # a bounded recent dedup ledger (also covers brief occlusion).
                while len(self._edgefall_event_ids) > 256:
                    self._edgefall_event_ids.pop(next(iter(self._edgefall_event_ids)))
            elif previous is not None and state != previous:
                if state == "suspected":
                    transition = "fall_suspected"
                elif (
                    state == "normal"
                    and previous != "normal"
                    and all(value == "normal" for value in states)
                ):
                    transition = "fall_cleared"

            if "fallen" in states:
                self._fall_state = "confirmed"
            elif "suspected" in states:
                self._fall_state = "suspected"
            elif "recovering" in states:
                self._fall_state = "recovering"
            else:
                self._fall_state = "normal"
            self._pose_state = state
            self._fall_confidence = max(
                (float(item.get("temporal_probability", 0.0)) for item in tracks),
                default=0.0,
            )

            if transition is None:
                continue

            probability = float(track.get("temporal_probability", 0.0))
            severity = (
                "critical"
                if transition == "fall_confirmed"
                else "normal"
                if transition == "fall_cleared"
                else "warning"
            )
            details = {
                "severity": severity,
                "source_type": self.source_type,
                "backend": "hailo_edgefall",
                "shadow": False,
                "published_to_mqtt": self.edgefall_publish_mqtt,
                "model": getattr(self.edgefall_shadow, "profile", "edgefallkit"),
                "track_id": track_id,
                "previous_state": previous,
                "state": state,
                "edgefall_event_id": event_id,
                "temporal_positive": bool(track.get("temporal_positive", False)),
                "hip_drop_speed": float(track.get("hip_drop_speed", 0.0)),
                "hip_drop_distance": float(track.get("hip_drop_distance", 0.0)),
                "torso_angle_deg": float(track.get("torso_angle_deg", 0.0)),
                "bbox_aspect_ratio": float(track.get("bbox_aspect_ratio", 0.0)),
                "decision_reason": track.get("decision_reason", "unknown"),
                "geometry_candidate": bool(track.get("geometry_candidate", False)),
                "motion_continuous": bool(track.get("motion_continuous", False)),
                "confirmation_policy": "temporal_required",
            }
            self.event_bus.emit(
                self.camera_id,
                transition,
                probability,
                details,
                publish=self.edgefall_publish_mqtt,
            )
            print(
                "EDGEFALL_TRANSITION "
                f"camera={self.camera_id} track={track_id} "
                f"previous={previous or 'new'} state={state} "
                f"fall_event={bool(track.get('fall_event', False))} "
                f"event_id={event_id} probability={probability:.4f} "
                f"mqtt={str(self.edgefall_publish_mqtt).lower()}",
                flush=True,
            )

        self._edgefall_track_states = current_states

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

    def _draw_overlay(
        self,
        frame: np.ndarray,
        source_shape: tuple[int, ...] | None = None,
    ) -> None:
        source_height, source_width = (source_shape or frame.shape)[:2]
        scale_x = frame.shape[1] / max(source_width, 1)
        scale_y = frame.shape[0] / max(source_height, 1)

        def point(x: float, y: float) -> tuple[int, int]:
            return (int(round(x * scale_x)), int(round(y * scale_y)))

        def box(value: list[int] | tuple[int, int, int, int]) -> tuple[int, int, int, int]:
            x1, y1, x2, y2 = value
            left, top = point(x1, y1)
            right, bottom = point(x2, y2)
            return left, top, right, bottom

        primary_poses = self._poses
        hailo_shadow_poses = getattr(self, "_hailo_shadow_poses", [])
        edgefall_shadow_tracks = getattr(self, "_edgefall_shadow_tracks", [])
        hailo_keypoint_confidence = getattr(
            self,
            "hailo_shadow_keypoint_confidence",
            0.25,
        )

        for pose in primary_poses:
            keypoints = pose["keypoints"]
            for start, end in POSE_SKELETON:
                if keypoints[start][2] < 0.25 or keypoints[end][2] < 0.25:
                    continue
                start_point = point(keypoints[start][0], keypoints[start][1])
                end_point = point(keypoints[end][0], keypoints[end][1])
                cv2.line(frame, start_point, end_point, (0, 165, 255), 2)
            for x, y, confidence in keypoints:
                if confidence >= 0.25:
                    cv2.circle(frame, point(x, y), 3, (0, 220, 255), -1)

        for detection in self._detections:
            x1, y1, x2, y2 = box(detection["box"])
            confidence = detection["confidence"]
            label = detection["label"]
            color = (255, 0, 255)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"HAILO {label.upper()} {confidence:.2f}",
                (x1, max(24, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                color,
                2,
            )

        for pose in hailo_shadow_poses:
            keypoints = pose["keypoints"]
            for start, end in POSE_SKELETON:
                if (
                    keypoints[start][2] < hailo_keypoint_confidence
                    or keypoints[end][2] < hailo_keypoint_confidence
                ):
                    continue
                cv2.line(
                    frame,
                    point(keypoints[start][0], keypoints[start][1]),
                    point(keypoints[end][0], keypoints[end][1]),
                    (0, 165, 255),
                    2,
                )
            for x, y, confidence in keypoints:
                if confidence >= hailo_keypoint_confidence:
                    cv2.circle(frame, point(x, y), 3, (0, 220, 255), -1)

            x1, y1, x2, y2 = box(pose["box"])
            color = (255, 0, 255)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"HAILO {float(pose['confidence']):.2f}",
                (x1, min(frame.shape[0] - 8, y2 + 24)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.58,
                color,
                2,
            )

        for track in edgefall_shadow_tracks:
            if not track.get("visible", False):
                continue
            x1, y1, _x2, _y2 = box(track["bbox"])
            state = str(track.get("state", "normal")).upper()
            probability = float(track.get("temporal_probability", 0.0))
            color = EDGEFALL_STATE_COLORS.get(
                state.lower(),
                (190, 120, 255),
            )
            label = (
                f"EDGEFALL #{track['track_id']} {state} "
                f"P={probability:.0%}"
            )
            label_scale = 0.68
            label_thickness = 2
            (label_width, label_height), baseline = cv2.getTextSize(
                label,
                cv2.FONT_HERSHEY_SIMPLEX,
                label_scale,
                label_thickness,
            )
            label_y = max(68, y1 - 10)
            cv2.rectangle(
                frame,
                (x1, max(42, label_y - label_height - baseline - 8)),
                (
                    min(frame.shape[1] - 1, x1 + label_width + 12),
                    label_y + baseline + 4,
                ),
                (18, 22, 30),
                -1,
            )
            cv2.putText(
                frame,
                label,
                (x1 + 6, label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                label_scale,
                color,
                label_thickness,
            )

        for face in self._faces:
            x1, y1, x2, y2 = box(face["box"])
            color = (255, 200, 40) if face["registered"] else (80, 80, 255)
            display_name = str(face["name"]) if face["registered"] else "미등록"
            label = f"{display_name} {face['similarity']:.2f}"
            label_origin = (x1, min(frame.shape[0] - 8, y2 + 26))
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            # A solid label background keeps Korean glyphs legible over video.
            label_width = min(frame.shape[1] - x1, len(label) * 19 + 12)
            cv2.rectangle(frame, (x1, label_origin[1] - 24),
                          (x1 + label_width, label_origin[1] + 5), (22, 27, 32), -1)
            draw_face_label(
                frame,
                label,
                label_origin,
                color,
                self._face_font,
            )

        # Camera names/FPS live outside the video. Do not obscure faces or the
        # Dahua clock with a duplicate, rasterised header.

        if hailo_shadow_poses:
            legend = "NCNN: GREEN/CYAN | HAILO SHADOW: MAGENTA/ORANGE"
            legend_y = max(58, frame.shape[0] - 12)
            cv2.rectangle(
                frame,
                (0, legend_y - 24),
                (min(frame.shape[1], 600), legend_y + 4),
                (18, 22, 30),
                -1,
            )
            cv2.putText(
                frame,
                legend,
                (10, legend_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.43,
                (245, 245, 245),
                1,
            )

        if getattr(self, "edgefall_shadow", None) is not None or edgefall_shadow_tracks:
            best_edgefall = select_edgefall_track(edgefall_shadow_tracks)
            if best_edgefall is None or best_edgefall.get("state") == "normal":
                return
            edgefall_state = str(best_edgefall.get("state", "normal"))
            edgefall_text = (
                "EDGEFALL | "
                f"TRACK #{best_edgefall['track_id']} | "
                f"{edgefall_state.upper()}"
            )

            reserved_bottom = 40 if hailo_shadow_poses else 6
            bar_bottom = max(84, frame.shape[0] - reserved_bottom)
            bar_top = max(42, bar_bottom - 44)
            bar_color = EDGEFALL_STATE_COLORS.get(
                edgefall_state,
                EDGEFALL_STATE_COLORS["warming"],
            )
            cv2.rectangle(
                frame,
                (0, bar_top),
                (frame.shape[1], bar_bottom),
                bar_color,
                -1,
            )
            cv2.putText(
                frame,
                edgefall_text,
                (12, bar_bottom - 12),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                (255, 255, 255),
                2,
            )


    def add_stream_client(self, overlay: bool) -> None:
        with self._lock:
            if overlay:
                self._overlay_stream_clients += 1
            else:
                self._clean_stream_clients += 1

    def remove_stream_client(self, overlay: bool) -> None:
        with self._lock:
            if overlay:
                self._overlay_stream_clients = max(0, self._overlay_stream_clients - 1)
            else:
                self._clean_stream_clients = max(0, self._clean_stream_clients - 1)

    def jpeg(self, overlay: bool = True) -> bytes | None:
        with self._lock:
            return self._jpeg if overlay else self._clean_jpeg

    def registration_frame(self) -> np.ndarray | None:
        with self._lock:
            return None if self._registration_frame is None else self._registration_frame.copy()

    def registration_sample(self) -> tuple[float, np.ndarray | None]:
        """Atomic timestamp + frame prevents repeated/stale enrollment samples."""
        with self._lock:
            return (self._last_registration_frame_at,
                    None if self._registration_frame is None else self._registration_frame.copy())

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

            pose_times = list(
                self._pose_completed_at
            )

            if (
                len(pose_times) >= 2
                and pose_times[-1]
                > pose_times[0]
            ):
                pose_effective_fps = (
                    (len(pose_times) - 1)
                    / (
                        pose_times[-1]
                        - pose_times[0]
                    )
                )
            else:
                pose_effective_fps = 0.0

            pose_latencies = list(
                self._pose_latency_ms
            )

            pose_inference_ms = (
                float(np.mean(pose_latencies))
                if pose_latencies
                else 0.0
            )

            pose_inference_p95_ms = (
                float(
                    np.percentile(
                        pose_latencies,
                        95,
                    )
                )
                if pose_latencies
                else 0.0
            )

            hailo_shadow_times = list(self._hailo_shadow_completed_at)
            if (
                len(hailo_shadow_times) >= 2
                and hailo_shadow_times[-1] > hailo_shadow_times[0]
            ):
                hailo_shadow_effective_fps = (
                    (len(hailo_shadow_times) - 1)
                    / (hailo_shadow_times[-1] - hailo_shadow_times[0])
                )
            else:
                hailo_shadow_effective_fps = 0.0

            hailo_shadow_latencies = list(self._hailo_shadow_latency_ms)
            hailo_shadow_inference_ms = (
                float(np.mean(hailo_shadow_latencies))
                if hailo_shadow_latencies
                else 0.0
            )
            hailo_shadow_inference_p95_ms = (
                float(np.percentile(hailo_shadow_latencies, 95))
                if hailo_shadow_latencies
                else 0.0
            )

            hailo_shadow_requested = (
                self.hailo_shadow_enabled
                and (
                    not self.hailo_shadow_run_when_viewed
                    or self._overlay_stream_clients > 0
                )
            )
            if not self.hailo_shadow_configured:
                hailo_shadow_state = "disabled"
            elif not self.hailo_shadow_enabled or self._hailo_shadow_error:
                hailo_shadow_state = "error"
            elif not hailo_shadow_requested:
                hailo_shadow_state = "paused"
            elif not self._hailo_shadow_frame_seq:
                hailo_shadow_state = "warming"
            else:
                hailo_shadow_state = "running"

            edgefall_tracks = [
                dict(item)
                for item in self._edgefall_shadow_tracks
            ]
            best_edgefall = select_edgefall_track(edgefall_tracks)
            edgefall_state = (
                str(best_edgefall.get("state", "warming"))
                if best_edgefall is not None
                else "warming"
                if self.edgefall_shadow is not None
                else "error"
                if self._edgefall_shadow_error
                else "disabled"
            )
            edgefall_probability = (
                float(best_edgefall.get("temporal_probability", 0.0))
                if best_edgefall is not None
                else 0.0
            )
            edgefall_best_track_id = (
                int(best_edgefall["track_id"])
                if best_edgefall is not None
                else None
            )

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

                pose_backend=(
                    str(
                        getattr(
                            self.pose_estimator,
                            "backend_name",
                            "hailo_edgefall",
                        )
                    )
                    if self.pose_enabled
                    else "off"
                ),

                face_enabled=self.face_enabled,

                rule_mode=self.rule_mode,

                pose_state=(
                    self._pose_state
                ),

                fall_state=(
                    self._fall_state
                ),

                fall_confidence=round(
                    self._fall_confidence,
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

                recognized_faces=[
                    {
                        "name": str(face["name"]),
                        "registered": bool(face["registered"]),
                        "similarity": round(float(face["similarity"]), 3),
                    }
                    for face in self._faces
                ],

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

                source_backend=str(
                    getattr(self.source, "backend_active", self.source_type)
                ),

                source_buffer_age_ms=round(
                    self._source_buffer_age_ms,
                    1,
                ),

                overlay_stream_clients=(
                    self._overlay_stream_clients
                ),

                clean_stream_clients=(
                    self._clean_stream_clients
                ),

                capture_frame_seq=(
                    self._latest_frame_seq
                ),

                pose_target_fps=round(
                    self.pose_target_fps,
                    2,
                ),

                pose_effective_fps=round(
                    pose_effective_fps,
                    2,
                ),

                pose_inference_ms=round(
                    pose_inference_ms,
                    2,
                ),

                pose_inference_p95_ms=round(
                    pose_inference_p95_ms,
                    2,
                ),

                pose_visible_keypoint_ratio=round(
                    pose_visible_keypoint_ratio(self._poses, 0.25),
                    4,
                ),

                pose_input_age_ms=round(
                    self._pose_input_age_ms,
                    2,
                ),

                pose_unique_frames=(
                    self._pose_unique_frames
                ),

                pose_source_frames_skipped=(
                    self._pose_source_frames_skipped
                ),

                pose_duplicate_frames_prevented=(
                    self._pose_duplicate_frames_prevented
                ),

                hailo_shadow_enabled=(
                    self.hailo_shadow_configured
                ),

                hailo_shadow_model=(
                    (
                        str(
                            getattr(
                                self.hailo_shadow_estimator,
                                "model_name",
                                "",
                            )
                        )
                        or None
                    )
                    if self.hailo_shadow_configured
                    else None
                ),

                hailo_shadow_state=hailo_shadow_state,

                hailo_shadow_person_count=len(
                    self._hailo_shadow_poses
                ),

                hailo_shadow_effective_fps=round(
                    hailo_shadow_effective_fps,
                    2,
                ),

                hailo_shadow_inference_ms=round(
                    hailo_shadow_inference_ms,
                    2,
                ),

                hailo_shadow_inference_p95_ms=round(
                    hailo_shadow_inference_p95_ms,
                    2,
                ),

                hailo_shadow_visible_keypoint_ratio=round(
                    pose_visible_keypoint_ratio(
                        self._hailo_shadow_poses,
                        self.hailo_shadow_keypoint_confidence,
                    ),
                    4,
                ),

                hailo_shadow_same_frame=(
                    bool(self._hailo_shadow_frame_seq)
                    and self._hailo_shadow_frame_seq == self._pose_frame_seq
                ),

                hailo_shadow_error=self._hailo_shadow_error,

                edgefall_shadow_enabled=(
                    self.edgefall_shadow is not None
                ),

                edgefall_shadow_profile=(
                    str(getattr(self.edgefall_shadow, "profile", "")) or None
                ),

                edgefall_shadow_state=edgefall_state,

                edgefall_shadow_probability=round(
                    edgefall_probability,
                    4,
                ),

                edgefall_shadow_best_track_id=edgefall_best_track_id,

                edgefall_shadow_tracks=edgefall_tracks,

                edgefall_shadow_error=self._edgefall_shadow_error,

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

                temporal_observation_logging=(
                    self.shadow_log is not None
                ),

                temporal_observation_log_error=(
                    self.shadow_log.last_error
                    if self.shadow_log is not None
                    else None
                ),

                error=self._error,
            )

    def status_dict(self) -> dict[str, Any]:
        status = self.snapshot().__dict__
        status.update(
            {
                "fall_backend": "hailo_edgefall" if self.pose_enabled else "off",
                "fall_model": (
                    str(getattr(self.pose_estimator, "model_name", "")) or None
                    if self.pose_enabled
                    else None
                ),
                "fall_mqtt_enabled": bool(
                    self.pose_enabled and self.edgefall_publish_mqtt
                ),
                "edgefall_enabled": self.edgefall_shadow is not None,
                "edgefall_profile": (
                    str(getattr(self.edgefall_shadow, "profile", "")) or None
                ),
                "edgefall_state": status["edgefall_shadow_state"],
                "edgefall_probability": status["edgefall_shadow_probability"],
                "edgefall_best_track_id": status["edgefall_shadow_best_track_id"],
                "edgefall_tracks": status["edgefall_shadow_tracks"],
                "edgefall_error": status["edgefall_shadow_error"],
            }
        )
        for key in list(status):
            if (
                key.startswith("hailo_shadow_")
                or key.startswith("edgefall_shadow_")
                or key.startswith("temporal_")
                or key == "rule_mode"
            ):
                status.pop(key, None)
        status["analysis"] = analysis_readiness(status)
        diagnostic_log = getattr(self, "_diagnostic_log", None)
        status["diagnostic_logging"] = diagnostic_log is not None
        status["diagnostic_log_error"] = (
            diagnostic_log.error if diagnostic_log is not None
            else getattr(self, "_diagnostic_log_error", None)
        )
        status["diagnostic_records_dropped"] = diagnostic_log.dropped if diagnostic_log else 0
        status["camera_view"] = getattr(self.source, "view_info", None)
        return status


class VisionPipeline:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.event_bus = EventBus(config["mqtt"])
        fall_config = config.get("fall_detection", {})
        self.pose_estimator: Any | None = None
        self.hailo_shadow_estimator: Any | None = None
        self.hailo_shadow_error: str | None = None
        if fall_config.get("enabled", False):
            pose_backend = str(
                fall_config.get("backend", "hailo_edgefall")
            ).strip().lower()
            if pose_backend == "hailo_edgefall":
                self.pose_estimator = HailoPoseEstimator(
                    hef_path=fall_config["model"],
                    postprocess_path=fall_config["hailo_postprocess"],
                    whole_buffer_path=fall_config["hailo_whole_buffer"],
                    confidence=float(fall_config.get("confidence", 0.0)),
                    timeout_seconds=float(
                        fall_config.get("hailo_timeout_seconds", 3.0)
                    ),
                )
            else:
                raise ValueError(f"Unsupported pose backend: {pose_backend}")
        self.temporal_ensemble = None
        self.temporal_error = None

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
                    enrollment_min_samples_per_view=int(
                        face_config.get("enrollment_min_samples_per_view", 3)
                    ),
                    enrollment_yaw_threshold=float(
                        face_config.get("enrollment_yaw_threshold", 0.12)
                    ),
                    enrollment_max_yaw=float(
                        face_config.get("enrollment_max_yaw", 0.65)
                    ),
                    enrollment_min_sharpness=float(
                        face_config.get("enrollment_min_sharpness", 35.0)
                    ),
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
                self.hailo_shadow_estimator,
                self.hailo_shadow_error,
                self.temporal_ensemble,
                self.face_registry,
                self.event_bus,
                int(camera.get("stream_width", config["server"].get("stream_width", 640))),
                int(camera.get("stream_height", config["server"].get("stream_height", 360))),
                float(camera.get("stream_fps", config["server"].get("stream_fps", 15))),
                int(camera.get("jpeg_quality", config["server"].get("jpeg_quality", 80))),
                fall_config,
                face_config,
                float(config["mqtt"].get("status_interval_seconds", 5)),
            )

    @staticmethod
    def _build_source(config: dict[str, Any]) -> CameraSource:
        source_type = config["type"]
        if source_type == "picamera2":
            return PiCameraSource(int(config["width"]), int(config["height"]), int(config["fps"]))
        if source_type == "rtsp":
            return RtspSource(
                config.get("url", ""),
                config.get("transport", "tcp"),
                bool(config.get("low_latency", False)),
                config.get("backend", "auto"),
                int(config.get("decode_width", 0)),
                int(config.get("decode_height", 0)),
                int(config.get("latency_ms", 100)),
                config.get("codec", "h264"),
            )
        raise ValueError(f"Unsupported camera source: {source_type}")

    def start(self) -> None:
        self.event_bus.start()
        for worker in self.workers.values():
            worker.start()

    def stop(self) -> None:
        for worker in self.workers.values():
            worker.stop()
        self.event_bus.stop()
        close_pose = getattr(self.pose_estimator, "close", None)
        if callable(close_pose):
            close_pose()
        close_hailo_shadow = getattr(self.hailo_shadow_estimator, "close", None)
        if callable(close_hailo_shadow):
            close_hailo_shadow()

    def status(self) -> dict[str, Any]:
        return {
            "service": "smarthome-vision",
            "mqtt_connected": self.event_bus.connected,
            "mqtt_rejected_events": self.event_bus.rejected_events,
            "fall_backend": "hailo_edgefall",
            "fall_model": str(
                getattr(self.pose_estimator, "model_name", "")
            ) or None,
            "fall_events_publish_mqtt": bool(
                self.config.get("fall_detection", {})
                .get("edgefall", {})
                .get("publish_mqtt", True)
            ),
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
            raise ValueError("얼굴 등록은 Camera Module 3에서만 사용할 수 있습니다.")

        frames: list[np.ndarray] = []
        for _ in range(5):
            frame = worker.registration_frame()
            if frame is not None:
                frames.append(frame)
            time.sleep(0.25)
        return self.face_registry.enroll(name, frames, view)

    def enroll_face_auto(self, camera_id: str, name: str) -> dict:
        if self.face_registry is None:
            raise RuntimeError(self.face_error or "얼굴 인식 기능을 사용할 수 없습니다.")
        worker = self.workers.get(camera_id)
        if worker is None or not worker.face_enrollment:
            raise ValueError("얼굴 등록은 Camera Module 3에서만 사용할 수 있습니다.")

        face_config = self.config.get("face_recognition", {})
        duration = max(6.0, float(face_config.get("enrollment_seconds", 10.0)))
        interval = max(
            0.12,
            float(face_config.get("enrollment_sample_interval", 0.18)),
        )
        frames: list[np.ndarray] = []
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            frame = worker.registration_frame()
            if frame is not None:
                frames.append(frame)
            time.sleep(interval)
        if not frames:
            raise RuntimeError("Camera Module 3의 최신 프레임을 가져오지 못했습니다.")
        return self.face_registry.enroll_multi_angle(name, frames)

    def delete_face(self, person_id: str) -> bool:
        return self.face_registry is not None and self.face_registry.delete(person_id)
    def add_stream_client(self, camera_id: str, overlay: bool) -> None:
        self.workers[camera_id].add_stream_client(overlay)

    def remove_stream_client(self, camera_id: str, overlay: bool) -> None:
        self.workers[camera_id].remove_stream_client(overlay)

    def camera_jpeg(self, camera_id: str, overlay: bool = True) -> bytes:
        worker = self.workers[camera_id]
        jpeg = worker.jpeg(overlay=overlay)
        if jpeg is not None:
            return jpeg

        snapshot = worker.snapshot()
        placeholder = np.full((480, 720, 3), (24, 27, 34), dtype=np.uint8)
        cv2.putText(placeholder, snapshot.label, (36, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (240, 240, 240), 2)
        cv2.putText(placeholder, snapshot.error or "Waiting for camera...", (36, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (80, 170, 255), 2)
        ok, encoded = cv2.imencode(".jpg", placeholder)
        return encoded.tobytes() if ok else b""
