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
    LEFT_KNEE = 13
    RIGHT_KNEE = 14
    LEFT_ANKLE = 15
    RIGHT_ANKLE = 16

    def __init__(
        self,
        keypoint_confidence: float = 0.25,
        transition_window: float = 3.0,
        confirm_seconds: float = 1.2,
        recovery_seconds: float = 2.0,
        lost_grace_seconds: float = 1.0,
    ):
        self.keypoint_confidence = keypoint_confidence
        self.transition_window = transition_window
        self.confirm_seconds = confirm_seconds
        self.recovery_seconds = recovery_seconds
        self.lost_grace_seconds = lost_grace_seconds
        self.fall_state = "normal"
        self.pose_state = "unknown"
        self.confidence = 0.0
        self.metrics: dict[str, float] = {}
        self._upright_seen_at: float | None = None
        self._candidate_since: float | None = None
        self._recovery_since: float | None = None
        self._last_pose_at: float | None = None

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
            self._last_pose_at = now
        elif self._last_pose_at is None or now - self._last_pose_at > self.lost_grace_seconds:
            self.pose_state = "unknown"
            self.confidence = 0.0
            self.metrics = {}

        if self.pose_state in {"standing", "sitting"}:
            self._upright_seen_at = now
            self._candidate_since = None
            if self.fall_state == "confirmed":
                if self._recovery_since is None:
                    self._recovery_since = now
                elif now - self._recovery_since >= self.recovery_seconds:
                    self.fall_state = "normal"
                    self._recovery_since = None
                    event_type = "fall_cleared"
            elif self.fall_state == "suspected":
                self.fall_state = "normal"
                self._recovery_since = None
                event_type = "fall_cleared"
            else:
                self.fall_state = "normal"
                self._recovery_since = None
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

        return FallResult(
            pose_state=self.pose_state,
            fall_state=self.fall_state,
            confidence=self.confidence,
            event_type=event_type,
            metrics=self.metrics.copy(),
        )

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
        knee_angle = self._mean_knee_angle(keypoints)
        hip_knee_drop = self._hip_knee_drop(keypoints, height)
        visible_confidences = [
            point[2] for point in keypoints if point[2] >= self.keypoint_confidence
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
            sitting_by_legs = (
                (knee_angle is not None and knee_angle <= 145.0)
                or (hip_knee_drop is not None and hip_knee_drop <= 0.18)
            )
            pose_state = (
                "sitting"
                if sitting_by_legs or not self._ankles_visible(keypoints)
                else "standing"
            )
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
            "knee_angle": round(knee_angle if knee_angle is not None else -1.0, 1),
            "hip_knee_drop": round(
                hip_knee_drop if hip_knee_drop is not None else -1.0,
                3,
            ),
            "center_y": round(center_y, 3),
            "keypoint_quality": round(keypoint_quality, 3),
        }
        return pose_state, confidence, metrics

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

    def _mean_knee_angle(self, keypoints: list[list[float]]) -> float | None:
        angles = []
        for hip_index, knee_index, ankle_index in (
            (self.LEFT_HIP, self.LEFT_KNEE, self.LEFT_ANKLE),
            (self.RIGHT_HIP, self.RIGHT_KNEE, self.RIGHT_ANKLE),
        ):
            if any(
                keypoints[index][2] < self.keypoint_confidence
                for index in (hip_index, knee_index, ankle_index)
            ):
                continue
            angles.append(
                self._joint_angle(
                    keypoints[hip_index],
                    keypoints[knee_index],
                    keypoints[ankle_index],
                )
            )
        return sum(angles) / len(angles) if angles else None

    def _hip_knee_drop(
        self,
        keypoints: list[list[float]],
        box_height: float,
    ) -> float | None:
        drops = []
        for hip_index, knee_index in (
            (self.LEFT_HIP, self.LEFT_KNEE),
            (self.RIGHT_HIP, self.RIGHT_KNEE),
        ):
            if any(
                keypoints[index][2] < self.keypoint_confidence
                for index in (hip_index, knee_index)
            ):
                continue
            drops.append(
                abs(keypoints[knee_index][1] - keypoints[hip_index][1])
                / max(1.0, box_height)
            )
        return sum(drops) / len(drops) if drops else None

    @staticmethod
    def _joint_angle(
        first: list[float],
        center: list[float],
        third: list[float],
    ) -> float:
        first_vector = (first[0] - center[0], first[1] - center[1])
        third_vector = (third[0] - center[0], third[1] - center[1])
        first_length = math.hypot(*first_vector)
        third_length = math.hypot(*third_vector)
        if first_length <= 1e-6 or third_length <= 1e-6:
            return 180.0
        cosine = (
            first_vector[0] * third_vector[0]
            + first_vector[1] * third_vector[1]
        ) / (first_length * third_length)
        return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
