from pathlib import Path
import csv
import os
import time
import traceback

import cv2
import numpy as np
import pandas as pd
import torch
from ultralytics import YOLO


MANIFEST = Path(
    "data/aihub71641/manifests/val_manifest.csv"
)

RAW_ROOT = Path(
    "/Volumes/AIData/aihub71641/raw/val"
)

MODEL_PATH = Path(
    "models/yolo11n-pose.pt"
)

OUT_ROOT = Path(
    "data/pose_cache/val_yolo11n_pose_960_10fps"
)

LOG_PATH = OUT_ROOT / "extract_log.csv"
ERROR_PATH = OUT_ROOT / "errors.csv"


IMGSZ = 960
CONF = 0.10
TARGET_FPS = 10.0
DEVICE = "mps"

KEYPOINT_COUNT = 17


def select_person(result):
    """
    AI Hub 영상은 주 촬영 대상 1명을 중심으로 구성되어 있으므로
    가장 큰 person bounding box를 해당 actor로 선택한다.
    """

    if result.boxes is None:
        return None

    if len(result.boxes) == 0:
        return None

    boxes = (
        result.boxes.xyxy
        .detach()
        .cpu()
        .numpy()
    )

    if len(boxes) == 0:
        return None

    areas = (
        (boxes[:, 2] - boxes[:, 0])
        * (boxes[:, 3] - boxes[:, 1])
    )

    return int(
        np.argmax(areas)
    )


def output_path_for(row):
    scenario_id = row["scenario_id"]
    scene_id = row["scene_id"]

    return (
        OUT_ROOT
        / scenario_id
        / f"{scene_id}.npz"
    )


def cache_is_valid(path):
    if not path.exists():
        return False

    try:
        with np.load(
            path,
            allow_pickle=False,
        ) as d:

            required = {
                "frame_ids",
                "timestamps",
                "keypoints_xy",
                "keypoints_conf",
                "boxes_xyxy",
                "box_conf",
                "valid",
                "phase",
            }

            if not required.issubset(
                d.files
            ):
                return False

            n = len(
                d["frame_ids"]
            )

            if n <= 0:
                return False

            if (
                d["keypoints_xy"].shape
                != (
                    n,
                    KEYPOINT_COUNT,
                    2,
                )
            ):
                return False

            if (
                d["keypoints_conf"].shape
                != (
                    n,
                    KEYPOINT_COUNT,
                )
            ):
                return False

            if len(
                d["timestamps"]
            ) != n:
                return False

            if len(
                d["valid"]
            ) != n:
                return False

            return True

    except Exception:
        return False


def append_csv(
    path,
    fieldnames,
    row,
):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    exists = path.exists()

    with path.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        if not exists:
            writer.writeheader()

        writer.writerow(row)


def phase_for_frame(
    frame_id,
    is_fall,
    fall_start,
    fall_end,
):
    """
    phase:
      0 = normal (비낙상 영상)
      1 = pre-fall
      2 = falling
      3 = post-fall
    """

    if not is_fall:
        return 0

    if frame_id < fall_start:
        return 1

    if frame_id <= fall_end:
        return 2

    return 3


def process_video(
    model,
    row,
    video_path,
    out_path,
):
    cap = cv2.VideoCapture(
        str(video_path)
    )

    if not cap.isOpened():
        raise RuntimeError(
            f"Cannot open video: "
            f"{video_path}"
        )

    source_fps = cap.get(
        cv2.CAP_PROP_FPS
    )

    frame_count = int(
        cap.get(
            cv2.CAP_PROP_FRAME_COUNT
        )
    )

    width = int(
        cap.get(
            cv2.CAP_PROP_FRAME_WIDTH
        )
    )

    height = int(
        cap.get(
            cv2.CAP_PROP_FRAME_HEIGHT
        )
    )

    if source_fps <= 0:
        cap.release()

        raise RuntimeError(
            f"Invalid FPS: "
            f"{video_path}"
        )

    step = max(
        1,
        round(
            source_fps
            / TARGET_FPS
        ),
    )

    actual_sample_fps = (
        source_fps / step
    )

    is_fall = int(
        row["is_fall"]
    )

    fall_start = int(
        row["fall_start_frame"]
    )

    fall_end = int(
        row["fall_end_frame"]
    )


    frame_ids = []
    timestamps = []

    keypoints_xy = []
    keypoints_conf = []

    boxes_xyxy = []
    box_conf = []

    valid = []
    phases = []

    candidate_count = []

    inference_ms = []


    frame_id = 0

    while True:

        ok = cap.grab()

        if not ok:
            break

        if frame_id % step != 0:
            frame_id += 1
            continue

        ok, frame = cap.retrieve()

        if not ok:
            frame_id += 1
            continue

        t0 = time.perf_counter()

        result = model.predict(
            source=frame,
            imgsz=IMGSZ,
            conf=CONF,
            device=DEVICE,
            max_det=5,
            verbose=False,
        )[0]

        elapsed_ms = (
            time.perf_counter()
            - t0
        ) * 1000.0

        inference_ms.append(
            elapsed_ms
        )

        if result.boxes is None:
            n_candidates = 0
        else:
            n_candidates = len(
                result.boxes
            )

        candidate_count.append(
            n_candidates
        )

        person_idx = (
            select_person(
                result
            )
        )

        frame_ids.append(
            frame_id
        )

        timestamps.append(
            frame_id
            / source_fps
        )

        phases.append(
            phase_for_frame(
                frame_id,
                is_fall,
                fall_start,
                fall_end,
            )
        )

        if (
            person_idx is None
            or result.keypoints
            is None
        ):
            keypoints_xy.append(
                np.full(
                    (
                        KEYPOINT_COUNT,
                        2,
                    ),
                    np.nan,
                    dtype=np.float32,
                )
            )

            keypoints_conf.append(
                np.zeros(
                    KEYPOINT_COUNT,
                    dtype=np.float32,
                )
            )

            boxes_xyxy.append(
                np.full(
                    4,
                    np.nan,
                    dtype=np.float32,
                )
            )

            box_conf.append(
                0.0
            )

            valid.append(
                0
            )

        else:
            xy = (
                result
                .keypoints
                .xyn[
                    person_idx
                ]
                .detach()
                .cpu()
                .numpy()
                .astype(
                    np.float32
                )
            )

            if (
                result.keypoints.conf
                is not None
            ):
                kp_conf = (
                    result
                    .keypoints
                    .conf[
                        person_idx
                    ]
                    .detach()
                    .cpu()
                    .numpy()
                    .astype(
                        np.float32
                    )
                )
            else:
                kp_conf = (
                    np.ones(
                        KEYPOINT_COUNT,
                        dtype=np.float32,
                    )
                )

            box = (
                result
                .boxes
                .xyxyn[
                    person_idx
                ]
                .detach()
                .cpu()
                .numpy()
                .astype(
                    np.float32
                )
            )

            confidence = float(
                result
                .boxes
                .conf[
                    person_idx
                ]
                .detach()
                .cpu()
                .item()
            )

            keypoints_xy.append(
                xy
            )

            keypoints_conf.append(
                kp_conf
            )

            boxes_xyxy.append(
                box
            )

            box_conf.append(
                confidence
            )

            valid.append(
                1
            )

        frame_id += 1


    cap.release()


    frame_ids = np.asarray(
        frame_ids,
        dtype=np.int32,
    )

    timestamps = np.asarray(
        timestamps,
        dtype=np.float32,
    )

    keypoints_xy = np.asarray(
        keypoints_xy,
        dtype=np.float32,
    )

    keypoints_conf = np.asarray(
        keypoints_conf,
        dtype=np.float32,
    )

    boxes_xyxy = np.asarray(
        boxes_xyxy,
        dtype=np.float32,
    )

    box_conf = np.asarray(
        box_conf,
        dtype=np.float32,
    )

    valid = np.asarray(
        valid,
        dtype=np.uint8,
    )

    phases = np.asarray(
        phases,
        dtype=np.uint8,
    )

    candidate_count = np.asarray(
        candidate_count,
        dtype=np.uint8,
    )


    if len(frame_ids) == 0:
        raise RuntimeError(
            f"No sampled frames: "
            f"{video_path}"
        )


    out_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp_path = (
        out_path.parent
        / (
            out_path.stem
            + ".tmp.npz"
        )
    )


    np.savez_compressed(
        tmp_path,

        scene_id=np.asarray(
            str(
                row["scene_id"]
            )
        ),

        scenario_id=np.asarray(
            str(
                row["scenario_id"]
            )
        ),

        actor_id=np.asarray(
            str(
                row["actor_id"]
            )
        ),

        fall_class=np.asarray(
            str(
                row["fall_class"]
            )
        ),

        camera=np.asarray(
            int(
                row["camera"]
            ),
            dtype=np.int16,
        ),

        is_fall=np.asarray(
            is_fall,
            dtype=np.uint8,
        ),

        source_width=np.asarray(
            width,
            dtype=np.int32,
        ),

        source_height=np.asarray(
            height,
            dtype=np.int32,
        ),

        source_fps=np.asarray(
            source_fps,
            dtype=np.float32,
        ),

        source_frame_count=np.asarray(
            frame_count,
            dtype=np.int32,
        ),

        sample_step=np.asarray(
            step,
            dtype=np.int16,
        ),

        target_sample_fps=np.asarray(
            TARGET_FPS,
            dtype=np.float32,
        ),

        actual_sample_fps=np.asarray(
            actual_sample_fps,
            dtype=np.float32,
        ),

        imgsz=np.asarray(
            IMGSZ,
            dtype=np.int16,
        ),

        detector_conf=np.asarray(
            CONF,
            dtype=np.float32,
        ),

        fall_start_frame=np.asarray(
            fall_start,
            dtype=np.int32,
        ),

        fall_end_frame=np.asarray(
            fall_end,
            dtype=np.int32,
        ),

        frame_ids=frame_ids,

        timestamps=timestamps,

        keypoints_xy=keypoints_xy,

        keypoints_conf=keypoints_conf,

        boxes_xyxy=boxes_xyxy,

        box_conf=box_conf,

        valid=valid,

        phase=phases,

        candidate_count=(
            candidate_count
        ),
    )


    os.replace(
        tmp_path,
        out_path,
    )


    detection_rate = float(
        valid.mean()
    )

    visible_ratio = float(
        np.mean(
            keypoints_conf[
                valid.astype(bool)
            ]
            >= 0.25
        )
    ) if valid.any() else 0.0

    pose_coverage = (
        detection_rate
        * visible_ratio
    )

    mean_ms = (
        float(
            np.mean(
                inference_ms
            )
        )
        if inference_ms
        else 0.0
    )

    p95_ms = (
        float(
            np.percentile(
                inference_ms,
                95,
            )
        )
        if inference_ms
        else 0.0
    )

    return {
        "samples":
            len(frame_ids),

        "source_fps":
            source_fps,

        "actual_sample_fps":
            actual_sample_fps,

        "detection_rate":
            detection_rate,

        "visible_keypoints":
            visible_ratio,

        "pose_coverage":
            pose_coverage,

        "mean_candidates":
            float(
                candidate_count.mean()
            ),

        "mean_ms":
            mean_ms,

        "p95_ms":
            p95_ms,
    }


def main():
    OUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        "=" * 100
    )

    print(
        "AI HUB POSE CACHE EXTRACTION"
    )

    print(
        "=" * 100
    )

    print(
        "model     :",
        MODEL_PATH,
    )

    print(
        "imgsz     :",
        IMGSZ,
    )

    print(
        "conf      :",
        CONF,
    )

    print(
        "sample fps:",
        TARGET_FPS,
    )

    print(
        "device    :",
        DEVICE,
    )

    print(
        "output    :",
        OUT_ROOT,
    )

    print()


    if not RAW_ROOT.exists():
        raise RuntimeError(
            f"RAW_ROOT not found: "
            f"{RAW_ROOT}"
        )

    if not MODEL_PATH.exists():
        raise RuntimeError(
            f"MODEL not found: "
            f"{MODEL_PATH}"
        )


    df = pd.read_csv(
        MANIFEST
    ).sort_values(
        [
            "scenario_id",
            "camera",
        ]
    )


    print(
        "Manifest videos:",
        len(df),
    )


    print(
        "Indexing MP4 files..."
    )

    video_index = {
        p.stem: p
        for p
        in RAW_ROOT.rglob(
            "*.mp4"
        )
    }

    print(
        "MP4 indexed:",
        len(video_index),
    )


    missing = [
        x
        for x
        in df["scene_id"]
        if x not in video_index
    ]

    if missing:
        raise RuntimeError(
            f"Missing MP4 count="
            f"{len(missing)}, "
            f"examples="
            f"{missing[:10]}"
        )


    model = YOLO(
        str(
            MODEL_PATH
        )
    )


    print(
        "MPS warm-up..."
    )

    dummy = np.zeros(
        (
            720,
            1280,
            3,
        ),
        dtype=np.uint8,
    )

    for _ in range(3):
        model.predict(
            dummy,
            imgsz=IMGSZ,
            conf=CONF,
            device=DEVICE,
            verbose=False,
        )


    log_fields = [
        "scene_id",
        "scenario_id",
        "actor_id",
        "fall_class",
        "camera",
        "status",
        "samples",
        "source_fps",
        "actual_sample_fps",
        "detection_rate",
        "visible_keypoints",
        "pose_coverage",
        "mean_candidates",
        "mean_ms",
        "p95_ms",
        "elapsed_sec",
        "output",
    ]


    error_fields = [
        "scene_id",
        "video",
        "error",
    ]


    total = len(df)

    completed = 0
    skipped = 0
    failed = 0

    session_start = (
        time.perf_counter()
    )


    for number, (_, row) in enumerate(
        df.iterrows(),
        start=1,
    ):
        scene_id = row[
            "scene_id"
        ]

        video_path = (
            video_index[
                scene_id
            ]
        )

        out_path = (
            output_path_for(
                row
            )
        )


        if cache_is_valid(
            out_path
        ):
            skipped += 1

            print(
                f"[{number:04d}/"
                f"{total:04d}] "
                f"SKIP "
                f"{scene_id}"
            )

            continue


        started = (
            time.perf_counter()
        )


        try:
            metrics = (
                process_video(
                    model,
                    row,
                    video_path,
                    out_path,
                )
            )

            elapsed = (
                time.perf_counter()
                - started
            )

            completed += 1


            log_row = {
                "scene_id":
                    scene_id,

                "scenario_id":
                    row[
                        "scenario_id"
                    ],

                "actor_id":
                    row[
                        "actor_id"
                    ],

                "fall_class":
                    row[
                        "fall_class"
                    ],

                "camera":
                    int(
                        row[
                            "camera"
                        ]
                    ),

                "status":
                    "OK",

                **metrics,

                "elapsed_sec":
                    elapsed,

                "output":
                    str(
                        out_path
                    ),
            }


            append_csv(
                LOG_PATH,
                log_fields,
                log_row,
            )


            print(
                f"[{number:04d}/"
                f"{total:04d}] "
                f"OK "
                f"{scene_id} "
                f"det="
                f"{metrics['detection_rate']:.3f} "
                f"kpt="
                f"{metrics['visible_keypoints']:.3f} "
                f"cov="
                f"{metrics['pose_coverage']:.3f} "
                f"ms="
                f"{metrics['mean_ms']:.1f} "
                f"time="
                f"{elapsed:.1f}s"
            )


        except Exception as exc:
            failed += 1

            print(
                f"[{number:04d}/"
                f"{total:04d}] "
                f"ERROR "
                f"{scene_id}: "
                f"{exc}"
            )


            append_csv(
                ERROR_PATH,
                error_fields,
                {
                    "scene_id":
                        scene_id,

                    "video":
                        str(
                            video_path
                        ),

                    "error":
                        (
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        ),
                },
            )


            traceback.print_exc()


        if (
            number % 100
            == 0
            and torch.backends.mps.is_available()
        ):
            torch.mps.empty_cache()


    session_elapsed = (
        time.perf_counter()
        - session_start
    )


    print()
    print(
        "=" * 100
    )

    print(
        "SESSION COMPLETE"
    )

    print(
        "=" * 100
    )

    print(
        "completed:",
        completed,
    )

    print(
        "skipped  :",
        skipped,
    )

    print(
        "failed   :",
        failed,
    )

    print(
        "elapsed  :",
        f"{session_elapsed / 60:.1f} min",
    )


    caches = list(
        OUT_ROOT.rglob(
            "*.npz"
        )
    )

    valid_count = sum(
        cache_is_valid(p)
        for p in caches
    )


    print(
        "cache files:",
        len(caches),
    )

    print(
        "valid cache:",
        valid_count,
    )


    if LOG_PATH.exists():
        logs = pd.read_csv(
            LOG_PATH
        )

        ok = logs[
            logs[
                "status"
            ] == "OK"
        ]

        if len(ok):
            print()

            print(
                "MEAN detection:",
                ok[
                    "detection_rate"
                ].mean(),
            )

            print(
                "MEAN keypoints:",
                ok[
                    "visible_keypoints"
                ].mean(),
            )

            print(
                "MEAN coverage:",
                ok[
                    "pose_coverage"
                ].mean(),
            )

            print(
                "MEAN inference ms:",
                ok[
                    "mean_ms"
                ].mean(),
            )


if __name__ == "__main__":
    main()
