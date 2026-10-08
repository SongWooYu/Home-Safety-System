from __future__ import annotations

import math
import time
from collections import deque

import numpy as np

from .gru_numpy import NumpyFallEnsemble


EPS = np.float32(1e-6)
FEATURE_DIM = 76
KEYPOINT_COUNT = 17


def build_b76_feature(
    pose: dict,
    frame_shape: tuple[int, ...],
    keypoint_confidence: float = 0.25,
) -> np.ndarray:
    """
    Runtime equivalent of research script
    09_build_gru_dataset.py B_76 features.

    17 joints * [bbox-relative x, bbox-relative y,
                 confidence, valid mask] = 68

    + bbox cx, cy, w, h
    + log(h / w)
    + bbox confidence
    + frame valid
    + visible keypoint ratio
    = 76
    """

    frame_h, frame_w = frame_shape[:2]

    if frame_w <= 0 or frame_h <= 0:
        return np.zeros(
            FEATURE_DIM,
            dtype=np.float32,
        )

    box = np.asarray(
        pose.get(
            "box",
            [0, 0, 0, 0],
        ),
        dtype=np.float32,
    )

    keypoints = np.asarray(
        pose.get(
            "keypoints",
            [],
        ),
        dtype=np.float32,
    )

    if (
        box.shape != (4,)
        or keypoints.shape
        != (
            KEYPOINT_COUNT,
            3,
        )
    ):
        return np.zeros(
            FEATURE_DIM,
            dtype=np.float32,
        )

    # NCNN runtime outputs pixels.
    # Training cache used Ultralytics xyn/xyxyn,
    # so normalize to full-frame 0..1 first.
    x1 = box[0] / frame_w
    y1 = box[1] / frame_h
    x2 = box[2] / frame_w
    y2 = box[3] / frame_h

    width = np.float32(
        x2 - x1
    )

    height = np.float32(
        y2 - y1
    )

    bbox_valid = bool(
        np.isfinite(
            box
        ).all()
        and width > EPS
        and height > EPS
    )

    if not bbox_valid:
        return np.zeros(
            FEATURE_DIM,
            dtype=np.float32,
        )

    cx = np.float32(
        (x1 + x2) * 0.5
    )

    cy = np.float32(
        (y1 + y2) * 0.5
    )

    xy = np.empty(
        (
            KEYPOINT_COUNT,
            2,
        ),
        dtype=np.float32,
    )

    xy[:, 0] = (
        keypoints[:, 0]
        / frame_w
    )

    xy[:, 1] = (
        keypoints[:, 1]
        / frame_h
    )

    conf = np.nan_to_num(
        keypoints[:, 2],
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )

    conf = np.clip(
        conf,
        0.0,
        1.0,
    ).astype(
        np.float32
    )

    finite_xy = np.isfinite(
        xy
    ).all(
        axis=1
    )

    mask = (
        finite_xy
        & (
            conf
            >= keypoint_confidence
        )
    )

    rel_x = (
        xy[:, 0]
        - cx
    ) / width

    rel_y = (
        xy[:, 1]
        - cy
    ) / height

    rel_x = np.nan_to_num(
        rel_x,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )

    rel_y = np.nan_to_num(
        rel_y,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )

    rel_x = np.clip(
        rel_x,
        -2.0,
        2.0,
    ).astype(
        np.float32
    )

    rel_y = np.clip(
        rel_y,
        -2.0,
        2.0,
    ).astype(
        np.float32
    )

    rel_x[
        ~mask
    ] = 0.0

    rel_y[
        ~mask
    ] = 0.0

    joints = np.stack(
        [
            rel_x,
            rel_y,
            conf,
            mask.astype(
                np.float32
            ),
        ],
        axis=1,
    ).reshape(
        68
    )

    log_aspect = np.float32(
        np.log(
            (
                height
                + EPS
            )
            /
            (
                width
                + EPS
            )
        )
    )

    log_aspect = np.float32(
        np.clip(
            log_aspect,
            -3.0,
            3.0,
        )
    )

    box_conf = np.float32(
        np.clip(
            float(
                pose.get(
                    "confidence",
                    0.0,
                )
            ),
            0.0,
            1.0,
        )
    )

    visible_ratio = np.float32(
        np.mean(
            mask
        )
    )

    global_features = np.asarray(
        [
            cx,
            cy,
            width,
            height,
            log_aspect,
            box_conf,
            1.0,
            visible_ratio,
        ],
        dtype=np.float32,
    )

    feature = np.concatenate(
        [
            joints,
            global_features,
        ]
    ).astype(
        np.float32,
        copy=False,
    )

    if feature.shape != (
        FEATURE_DIM,
    ):
        raise RuntimeError(
            "B76 feature shape "
            f"mismatch: {feature.shape}"
        )

    return feature


def _iou(
    a: np.ndarray,
    b: np.ndarray,
) -> float:

    x1 = max(
        float(a[0]),
        float(b[0]),
    )

    y1 = max(
        float(a[1]),
        float(b[1]),
    )

    x2 = min(
        float(a[2]),
        float(b[2]),
    )

    y2 = min(
        float(a[3]),
        float(b[3]),
    )

    inter_w = max(
        0.0,
        x2 - x1,
    )

    inter_h = max(
        0.0,
        y2 - y1,
    )

    intersection = (
        inter_w
        * inter_h
    )

    area_a = max(
        0.0,
        float(a[2] - a[0]),
    ) * max(
        0.0,
        float(a[3] - a[1]),
    )

    area_b = max(
        0.0,
        float(b[2] - b[0]),
    ) * max(
        0.0,
        float(b[3] - b[1]),
    )

    union = (
        area_a
        + area_b
        - intersection
    )

    if union <= 0.0:
        return 0.0

    return float(
        intersection
        / union
    )


class _Track:
    def __init__(
        self,
        track_id: int,
        box: np.ndarray,
        feature: np.ndarray,
        now: float,
        sequence_length: int,
    ):
        self.track_id = track_id

        self.box = np.asarray(
            box,
            dtype=np.float32,
        )

        self.velocity = np.zeros(
            4,
            dtype=np.float32,
        )

        self.last_seen = now

        self.missed = 0
        self.hits = 1
        self.age = 1

        self.buffer = deque(
            maxlen=sequence_length
        )

        self.buffer.append(
            feature
        )

        self.result: dict | None = None

        self.inference_ms = 0.0

        self.consecutive_hits = 0
        self.release_misses = 0
        self.alert_active = False
        self.cooldown_until = 0.0
        self.transition: str | None = None


class TemporalFallShadow:
    """
    Per-person temporal fall detector.

    This is shadow-only:
    it never emits MQTT fall events.
    """

    def __init__(
        self,
        ensemble: NumpyFallEnsemble,
        sequence_length: int = 20,
        keypoint_confidence: float = 0.25,
        threshold: float = 0.92,
        consecutive: int = 1,
        max_missing_frames: int = 10,
        expire_seconds: float = 1.5,
        release_frames: int = 3,
        cooldown_seconds: float = 5.0,
        quality_min_visible_ratio: float = 0.35,
        quality_min_valid_frame_ratio: float = 0.75,
        quality_edge_margin_ratio: float = 0.01,
    ):
        self.ensemble = ensemble

        self.sequence_length = (
            sequence_length
        )

        self.keypoint_confidence = (
            keypoint_confidence
        )

        self.threshold = threshold

        self.consecutive = max(
            1,
            consecutive,
        )

        self.max_missing_frames = max(
            1,
            max_missing_frames,
        )

        self.expire_seconds = max(
            0.2,
            expire_seconds,
        )

        self.release_frames = max(
            1,
            release_frames,
        )

        self.cooldown_seconds = max(
            0.0,
            cooldown_seconds,
        )

        self.quality_min_visible_ratio = max(
            0.0,
            min(1.0, quality_min_visible_ratio),
        )

        self.quality_min_valid_frame_ratio = max(
            0.0,
            min(1.0, quality_min_valid_frame_ratio),
        )

        self.quality_edge_margin_ratio = max(
            0.0,
            min(0.25, quality_edge_margin_ratio),
        )

        self._tracks: dict[
            int,
            _Track,
        ] = {}

        self._next_track_id = 1

    @staticmethod
    def _box(
        pose: dict,
    ) -> np.ndarray:

        return np.asarray(
            pose["box"],
            dtype=np.float32,
        )

    def _quality_status(
        self,
        track: _Track,
        frame_shape: tuple[int, ...],
        ready: bool,
    ) -> dict:
        features = list(track.buffer)
        valid = [float(item[74]) >= 0.5 for item in features]
        valid_frame_ratio = float(np.mean(valid)) if valid else 0.0
        visible_values = [
            float(item[75])
            for item, is_valid in zip(features, valid)
            if is_valid
        ]
        mean_visible_ratio = (
            float(np.mean(visible_values)) if visible_values else 0.0
        )
        current_visible_ratio = (
            float(features[-1][75]) if features and valid[-1] else 0.0
        )

        frame_h, frame_w = frame_shape[:2]
        margin_x = frame_w * self.quality_edge_margin_ratio
        margin_y = frame_h * self.quality_edge_margin_ratio
        x1, y1, x2, y2 = (float(value) for value in track.box)
        edge_sides = []
        if x1 <= margin_x:
            edge_sides.append("left")
        if y1 <= margin_y:
            edge_sides.append("top")
        if x2 >= frame_w - 1 - margin_x:
            edge_sides.append("right")
        if y2 >= frame_h - 1 - margin_y:
            edge_sides.append("bottom")

        box_area_ratio = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        box_area_ratio /= max(1.0, float(frame_w * frame_h))

        quality_flags = []
        if mean_visible_ratio < self.quality_min_visible_ratio:
            quality_flags.append("low_keypoint_visibility")
        if valid_frame_ratio < self.quality_min_valid_frame_ratio:
            quality_flags.append("missing_pose_frames")
        if edge_sides:
            quality_flags.append("frame_edge_clipped")

        return {
            "current_visible_keypoint_ratio": round(current_visible_ratio, 4),
            "mean_visible_keypoint_ratio": round(mean_visible_ratio, 4),
            "valid_frame_ratio": round(valid_frame_ratio, 4),
            "bbox_area_ratio": round(box_area_ratio, 4),
            "bbox_edge_sides": edge_sides,
            "quality_flags": quality_flags,
            "quality_eligible": ready and not quality_flags,
            "quality_is_diagnostic_only": True,
        }

    def _associate(
        self,
        poses: list[dict],
        frame_shape: tuple[int, ...],
    ) -> tuple[
        dict[int, int],
        set[int],
    ]:

        if (
            not self._tracks
            or not poses
        ):
            return (
                {},
                set(
                    range(
                        len(poses)
                    )
                ),
            )

        frame_h, frame_w = (
            frame_shape[:2]
        )

        diagonal = max(
            1.0,
            math.hypot(
                frame_w,
                frame_h,
            ),
        )

        candidates = []

        for track_id, track in (
            self._tracks.items()
        ):

            prediction_steps = min(
                track.missed + 1,
                3,
            )

            ta = (
                track.box
                + track.velocity
                * prediction_steps
            )

            tcx = (
                ta[0]
                + ta[2]
            ) * 0.5

            tcy = (
                ta[1]
                + ta[3]
            ) * 0.5

            for pose_index, pose in enumerate(
                poses
            ):

                pb = self._box(
                    pose
                )

                pcx = (
                    pb[0]
                    + pb[2]
                ) * 0.5

                pcy = (
                    pb[1]
                    + pb[3]
                ) * 0.5

                distance = (
                    math.hypot(
                        float(
                            pcx - tcx
                        ),
                        float(
                            pcy - tcy
                        ),
                    )
                    / diagonal
                )

                overlap = _iou(
                    ta,
                    pb,
                )

                track_w = max(
                    1.0,
                    float(ta[2] - ta[0]),
                )
                track_h = max(
                    1.0,
                    float(ta[3] - ta[1]),
                )
                pose_w = max(
                    1.0,
                    float(pb[2] - pb[0]),
                )
                pose_h = max(
                    1.0,
                    float(pb[3] - pb[1]),
                )

                size_penalty = (
                    abs(math.log(pose_w / track_w))
                    + abs(math.log(pose_h / track_h))
                )

                max_distance = (
                    0.12
                    + min(track.missed, 3)
                    * 0.04
                )

                if (
                    overlap >= 0.03
                    or distance <= max_distance
                ):
                    score = (
                        overlap * 3.0
                        - distance
                        - size_penalty * 0.10
                    )

                    candidates.append(
                        (
                            score,
                            track_id,
                            pose_index,
                        )
                    )

        candidates.sort(
            reverse=True
        )

        assignments: dict[
            int,
            int,
        ] = {}

        used_tracks = set()

        used_poses = set()

        for (
            _,
            track_id,
            pose_index,
        ) in candidates:

            if (
                track_id
                in used_tracks
                or pose_index
                in used_poses
            ):
                continue

            assignments[
                track_id
            ] = pose_index

            used_tracks.add(
                track_id
            )

            used_poses.add(
                pose_index
            )

        unmatched_poses = (
            set(
                range(
                    len(poses)
                )
            )
            - used_poses
        )

        return (
            assignments,
            unmatched_poses,
        )

    def update(
        self,
        poses: list[dict],
        frame_shape: tuple[int, ...],
        now: float | None = None,
    ) -> list[dict]:

        now = (
            time.monotonic()
            if now is None
            else now
        )

        (
            assignments,
            unmatched_poses,
        ) = self._associate(
            poses,
            frame_shape,
        )

        # Existing tracks.
        for track_id in list(
            self._tracks
        ):

            track = self._tracks[
                track_id
            ]

            pose_index = assignments.get(
                track_id
            )

            track.age += 1
            track.transition = None

            if pose_index is None:

                track.missed += 1
                track.velocity *= np.float32(0.85)

                if (
                    track.missed
                    > self.max_missing_frames
                    or (
                        now
                        - track.last_seen
                    )
                    > self.expire_seconds
                ):
                    del self._tracks[
                        track_id
                    ]

                    continue

                # Missing detection = invalid frame.
                # This matches the training feature
                # representation.
                track.buffer.append(
                    np.zeros(
                        FEATURE_DIM,
                        dtype=np.float32,
                    )
                )

            else:

                pose = poses[
                    pose_index
                ]

                new_box = self._box(
                    pose
                )

                delta = (
                    new_box
                    - track.box
                ).astype(
                    np.float32,
                    copy=False,
                )

                track.velocity = (
                    track.velocity
                    * np.float32(0.65)
                    + delta
                    * np.float32(0.35)
                ).astype(
                    np.float32,
                    copy=False,
                )

                track.box = new_box
                track.last_seen = now
                track.missed = 0
                track.hits += 1

                track.buffer.append(
                    build_b76_feature(
                        pose,
                        frame_shape,
                        self.keypoint_confidence,
                    )
                )

        # New tracks.
        for pose_index in sorted(
            unmatched_poses
        ):

            pose = poses[
                pose_index
            ]

            track_id = (
                self._next_track_id
            )

            self._next_track_id += 1

            self._tracks[
                track_id
            ] = _Track(
                track_id,
                self._box(
                    pose
                ),
                build_b76_feature(
                    pose,
                    frame_shape,
                    self.keypoint_confidence,
                ),
                now,
                self.sequence_length,
            )

        # GRU inference.
        for track in (
            self._tracks.values()
        ):

            if (
                len(track.buffer)
                < self.sequence_length
            ):
                continue

            sequence = np.stack(
                list(
                    track.buffer
                ),
                axis=0,
            ).astype(
                np.float32,
                copy=False,
            )

            started = (
                time.perf_counter()
            )

            result = (
                self.ensemble.predict(
                    sequence
                )
            )

            track.inference_ms = (
                (
                    time.perf_counter()
                    - started
                )
                * 1000.0
            )

            track.result = result

            if (
                result[
                    "alert_score"
                ]
                >= self.threshold
            ):
                track.consecutive_hits += 1
                track.release_misses = 0

                if (
                    not track.alert_active
                    and track.consecutive_hits
                    >= self.consecutive
                    and now
                    >= track.cooldown_until
                ):
                    track.alert_active = True
                    track.transition = (
                        "fall_shadow_confirmed"
                    )

            else:
                track.consecutive_hits = 0

                if track.alert_active:
                    track.release_misses += 1

                    if (
                        track.release_misses
                        >= self.release_frames
                    ):
                        track.alert_active = False
                        track.release_misses = 0
                        track.cooldown_until = (
                            now
                            + self.cooldown_seconds
                        )
                        track.transition = (
                            "fall_shadow_cleared"
                        )
                else:
                    track.release_misses = 0

        statuses = []

        for track in sorted(
            self._tracks.values(),
            key=lambda item:
                item.track_id,
        ):

            ready = (
                track.result
                is not None
            )

            if ready:

                probabilities = (
                    track.result[
                        "probabilities"
                    ]
                )

                state = (
                    track.result[
                        "class_name"
                    ]
                )

                alert_score = float(
                    track.result[
                        "alert_score"
                    ]
                )

            else:

                probabilities = {
                    "normal": 0.0,
                    "falling": 0.0,
                    "fallen": 0.0,
                }

                state = "warming"

                alert_score = 0.0

            statuses.append(
                {
                    "track_id":
                        track.track_id,

                    "bbox": [
                        int(
                            round(
                                float(x)
                            )
                        )
                        for x
                        in track.box
                    ],

                    "buffer":
                        len(
                            track.buffer
                        ),

                    "buffer_required":
                        self.sequence_length,

                    "ready":
                        ready,

                    "missed_frames":
                        track.missed,

                    "hits":
                        track.hits,

                    "age_frames":
                        track.age,

                    "last_seen_age":
                        round(
                            max(
                                0.0,
                                now
                                - track.last_seen,
                            ),
                            3,
                        ),

                    "state":
                        state,

                    "normal":
                        round(
                            float(
                                probabilities[
                                    "normal"
                                ]
                            ),
                            4,
                        ),

                    "falling":
                        round(
                            float(
                                probabilities[
                                    "falling"
                                ]
                            ),
                            4,
                        ),

                    "fallen":
                        round(
                            float(
                                probabilities[
                                    "fallen"
                                ]
                            ),
                            4,
                        ),

                    "alert_score":
                        round(
                            alert_score,
                            4,
                        ),

                    "threshold":
                        self.threshold,

                    "consecutive_hits":
                        track.consecutive_hits,

                    "shadow_alert":
                        (
                            ready
                            and track.alert_active
                        ),

                    "release_misses":
                        track.release_misses,

                    "cooldown_remaining":
                        round(
                            max(
                                0.0,
                                track.cooldown_until
                                - now,
                            ),
                            3,
                        ),

                    "transition":
                        track.transition,

                    "inference_ms":
                        round(
                            track.inference_ms,
                            3,
                        ),

                    **self._quality_status(
                        track,
                        frame_shape,
                        ready,
                    ),
                }
            )

        return statuses
