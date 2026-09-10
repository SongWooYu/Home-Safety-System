from __future__ import annotations

import math
import time
from dataclasses import dataclass, field


@dataclass
class FallResult:
    pose_state: str = "unknown"
    fall_state: str = "normal"
    confidence: float = 0.0
    event_type: str | None = None
    metrics: dict[str, float] = field(default_factory=dict)


class FallTracker:
    """Time-based exhibition fall detector using COCO pose keypoints."""

    LEFT_SHOULDER = 5
    RIGHT_SHOULDER = 6
    LEFT_HIP = 11
    RIGHT_HIP = 12
    LEFT_ANKLE = 15
    RIGHT_ANKLE = 16

    def __init__(
        self,
        keypoint_confidence: float = 0.25,
        transition_window: float = 3.0,
        confirm_seconds: float = 1.2,
        recovery_seconds: float = 2.0,
        lost_grace_seconds: float = 1.0,
        motion_window_seconds: float = 1.5,
        motion_min_drop: float = 0.10,
        motion_max_compression: float = 0.78,
    ):
        self.keypoint_confidence = keypoint_confidence
        self.transition_window = transition_window
        self.confirm_seconds = confirm_seconds
        self.recovery_seconds = recovery_seconds
        self.lost_grace_seconds = lost_grace_seconds
        self.motion_window_seconds = motion_window_seconds
        self.motion_min_drop = motion_min_drop
        self.motion_max_compression = motion_max_compression
        self.fall_state = "normal"
        self.pose_state = "unknown"
        self.confidence = 0.0
        self.metrics: dict[str, float] = {}
        self._upright_seen_at: float | None = None
        self._candidate_since: float | None = None
        self._recovery_since: float | None = None
        self._last_pose_at: float | None = None
        self._upright_history: list[tuple[float, dict[str, float]]] = []
        self._motion_baseline: dict[str, float] | None = None

    def update(
        self,
        poses: list[dict],
        frame_shape: tuple[int, ...],
        now: float | None = None,
    ) -> FallResult:
        now = time.monotonic() if now is None else now
        event_type = None

        if poses:
            pose = max(
                poses,
                key=lambda item: (item["box"][2] - item["box"][0])
                * (item["box"][3] - item["box"][1]),
            )
            self.pose_state, self.confidence, self.metrics = self._classify(
                pose,
                frame_shape,
            )
            if self.pose_state in {"standing", "sitting"} and self._is_motion_fall(now):
                self.pose_state = "lying"
            self._last_pose_at = now
        elif self._last_pose_at is None or now - self._last_pose_at > self.lost_grace_seconds:
            self.pose_state = "unknown"
            self.confidence = 0.0
            self.metrics = {}

        if self.pose_state in {"standing", "sitting"}:
            self._upright_seen_at = now
            self._remember_upright(now)
            self._candidate_since = None
            if self.fall_state == "confirmed":
                if self._recovery_since is None:
                    self._recovery_since = now
                elif now - self._recovery_since >= self.recovery_seconds:
                    self.fall_state = "normal"
                    self._recovery_since = None
                    self._motion_baseline = None
                    event_type = "fall_cleared"
            elif self.fall_state == "suspected":
                self.fall_state = "normal"
                self._recovery_since = None
                self._motion_baseline = None
                event_type = "fall_cleared"
            else:
                self.fall_state = "normal"
                self._recovery_since = None
                self._motion_baseline = None
        elif self.pose_state == "lying":
            self._recovery_since = None
            recent_upright = (
                self._upright_seen_at is not None
                and now - self._upright_seen_at <= self.transition_window
            )
            if self.fall_state == "normal" and recent_upright:
                self.fall_state = "suspected"
                self._candidate_since = now
                event_type = "fall_suspected"
            elif (
                self.fall_state == "suspected"
                and self._candidate_since is not None
                and now - self._candidate_since >= self.confirm_seconds
            ):
                self.fall_state = "confirmed"
                event_type = "fall_confirmed"
        elif (
            self.fall_state == "suspected"
            and self._last_pose_at is not None
            and now - self._last_pose_at > self.lost_grace_seconds
        ):
            self.fall_state = "normal"
            self._candidate_since = None
            self._motion_baseline = None

        return FallResult(
            pose_state=self.pose_state,
            fall_state=self.fall_state,
            confidence=self.confidence,
            event_type=event_type,
            metrics=self.metrics.copy(),
        )

    def _is_motion_fall(self, now: float) -> bool:
        """Detect a front/back fall that remains vertical in the 2D image."""
        self._prune_upright_history(now)
        current_center = self.metrics.get("torso_center_y", -1.0)
        current_height = self.metrics.get("box_height_ratio", 0.0)
        current_span = self.metrics.get("keypoint_span_y", 0.0)
        current_aspect = self.metrics.get("aspect_ratio", 0.0)
        if current_center < 0.50 or current_height <= 0.0 or current_span <= 0.0:
            return False

        baselines = (
            [self._motion_baseline]
            if self._motion_baseline is not None and self.fall_state in {"suspected", "confirmed"}
            else [sample for _, sample in self._upright_history]
        )
        best: tuple[float, float, float, dict[str, float]] | None = None
        for baseline in baselines:
            base_center = baseline.get("torso_center_y", -1.0)
            base_height = baseline.get("box_height_ratio", 0.0)
            base_span = baseline.get("keypoint_span_y", 0.0)
            base_aspect = baseline.get("aspect_ratio", 0.0)
            if min(base_center, base_height, base_span, base_aspect) <= 0.0:
                continue
            drop = current_center - base_center
            compression = min(current_height / base_height, current_span / base_span)
            aspect_gain = current_aspect / base_aspect
            if best is None or drop > best[0]:
                best = (drop, compression, aspect_gain, baseline)

        if best is None:
            return False
        drop, compression, aspect_gain, baseline = best
        collapsed = compression <= self.motion_max_compression or aspect_gain >= 1.35
        is_fall_motion = drop >= self.motion_min_drop and collapsed
        if is_fall_motion and self._motion_baseline is None:
            self._motion_baseline = baseline.copy()
        self.metrics.update(
            {
                "vertical_drop": round(drop, 3),
                "body_compression": round(compression, 3),
                "aspect_gain": round(aspect_gain, 3),
                "motion_fall": 1.0 if is_fall_motion else 0.0,
            }
        )
        return is_fall_motion

    def _remember_upright(self, now: float) -> None:
        self._prune_upright_history(now)
        self._upright_history.append((now, self.metrics.copy()))

    def _prune_upright_history(self, now: float) -> None:
        cutoff = now - self.motion_window_seconds
        self._upright_history = [sample for sample in self._upright_history if sample[0] >= cutoff]

    def _classify(
        self,
        pose: dict,
        frame_shape: tuple[int, ...],
    ) -> tuple[str, float, dict[str, float]]:
        frame_height, frame_width = frame_shape[:2]
        x1, y1, x2, y2 = pose["box"]
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        aspect_ratio = width / height
        center_y = ((y1 + y2) / 2) / max(1.0, frame_height)
        keypoints = pose["keypoints"]

        torso_angle = self._torso_angle(keypoints)
        torso_center_y = self._torso_center_y(keypoints, frame_height)
        visible_confidences = [
            point[2] for point in keypoints if point[2] >= self.keypoint_confidence
        ]
        visible_y = [
            point[1] for point in keypoints if point[2] >= self.keypoint_confidence
        ]
        keypoint_quality = (
            sum(visible_confidences) / len(visible_confidences)
            if visible_confidences
            else 0.0
        )

        lying_by_box = False
        lying_by_torso = (
            torso_angle is not None and torso_angle >= 58.0 and aspect_ratio >= 0.85
        )
        upright_by_box = aspect_ratio <= 0.90
        upright_by_torso = torso_angle is None or torso_angle <= 42.0

        if lying_by_box or lying_by_torso:
            pose_state = "lying"
            geometry_score = min(
                1.0,
                max(aspect_ratio / 1.6, (torso_angle or 0.0) / 90.0),
            )
        elif upright_by_box and upright_by_torso:
            pose_state = "standing" if self._ankles_visible(keypoints) else "sitting"
            geometry_score = min(1.0, height / max(1.0, frame_height * 0.55))
        else:
            pose_state = "sitting"
            geometry_score = 0.55

        confidence = min(
            0.99,
            max(0.0, 0.45 * float(pose["confidence"]) + 0.35 * keypoint_quality + 0.20 * geometry_score),
        )
        metrics = {
            "aspect_ratio": round(aspect_ratio, 3),
            "torso_angle": round(torso_angle if torso_angle is not None else -1.0, 1),
            "center_y": round(center_y, 3),
            "torso_center_y": round(torso_center_y if torso_center_y is not None else -1.0, 3),
            "box_height_ratio": round(height / max(1.0, frame_height), 3),
            "keypoint_span_y": round(
                (max(visible_y) - min(visible_y)) / max(1.0, frame_height)
                if len(visible_y) >= 4
                else 0.0,
                3,
            ),
            "keypoint_quality": round(keypoint_quality, 3),
        }
        return pose_state, confidence, metrics


    def _torso_center_y(self, keypoints: list[list[float]], frame_height: int) -> float | None:
        required = (
            self.LEFT_SHOULDER,
            self.RIGHT_SHOULDER,
            self.LEFT_HIP,
            self.RIGHT_HIP,
        )
        if any(keypoints[index][2] < self.keypoint_confidence for index in required):
            return None
        return sum(keypoints[index][1] for index in required) / (4.0 * max(1, frame_height))
    def _torso_angle(self, keypoints: list[list[float]]) -> float | None:
        required = (
            self.LEFT_SHOULDER,
            self.RIGHT_SHOULDER,
            self.LEFT_HIP,
            self.RIGHT_HIP,
        )
        if any(keypoints[index][2] < self.keypoint_confidence for index in required):
            return None
        shoulder_x = (keypoints[self.LEFT_SHOULDER][0] + keypoints[self.RIGHT_SHOULDER][0]) / 2
        shoulder_y = (keypoints[self.LEFT_SHOULDER][1] + keypoints[self.RIGHT_SHOULDER][1]) / 2
        hip_x = (keypoints[self.LEFT_HIP][0] + keypoints[self.RIGHT_HIP][0]) / 2
        hip_y = (keypoints[self.LEFT_HIP][1] + keypoints[self.RIGHT_HIP][1]) / 2
        return math.degrees(math.atan2(abs(shoulder_x - hip_x), abs(shoulder_y - hip_y) + 1e-6))

    def _ankles_visible(self, keypoints: list[list[float]]) -> bool:
        return (
            keypoints[self.LEFT_ANKLE][2] >= self.keypoint_confidence
            or keypoints[self.RIGHT_ANKLE][2] >= self.keypoint_confidence
        )
