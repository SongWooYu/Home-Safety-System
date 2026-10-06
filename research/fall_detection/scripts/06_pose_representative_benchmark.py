from pathlib import Path
import random
import time

import cv2
import numpy as np
import pandas as pd
from ultralytics import YOLO


MANIFEST = Path("data/aihub71641/manifests/val_manifest.csv")
RAW_ROOT = Path("/Volumes/AIData/aihub71641/raw/val")
MODEL = Path("models/yolo11n-pose.pt")

OUT = Path("data/pose_smoke/representative_40_scenarios.csv")
SELECTED_OUT = Path("data/pose_smoke/representative_40_selected.csv")

IMGSZ = 960
CONF = 0.10
SAMPLE_FPS = 5.0
SEED = 42
PER_CLASS = 10

random.seed(SEED)
np.random.seed(SEED)


def select_person(result):
    if result.boxes is None or len(result.boxes) == 0:
        return None

    boxes = result.boxes.xyxy.detach().cpu().numpy()

    if len(boxes) == 0:
        return None

    areas = (
        (boxes[:, 2] - boxes[:, 0])
        * (boxes[:, 3] - boxes[:, 1])
    )

    return int(np.argmax(areas))


def build_scenario_table(df):
    counts = (
        df.groupby("scenario_id")
        .size()
        .rename("views")
    )

    good_ids = counts[
        counts == 8
    ].index

    scenario_df = (
        df[
            df["scenario_id"]
            .isin(good_ids)
        ]
        .sort_values(
            ["scenario_id", "camera"]
        )
        .drop_duplicates("scenario_id")
        .reset_index(drop=True)
    )

    return scenario_df


def select_diverse_scenarios(
    scenario_df,
):
    classes = sorted(
        scenario_df[
            "fall_class"
        ].unique()
    )

    quotas = {
        cls: PER_CLASS
        for cls in classes
    }

    selected = []
    used_scenarios = set()
    selected_actors = set()

    actors = list(
        scenario_df[
            "actor_id"
        ].unique()
    )

    random.shuffle(actors)

    # 1단계:
    # 가능한 한 다양한 actor를 먼저 포함
    for actor in actors:

        candidates = scenario_df[
            (
                scenario_df[
                    "actor_id"
                ] == actor
            )
            &
            (
                ~scenario_df[
                    "scenario_id"
                ].isin(
                    used_scenarios
                )
            )
        ].copy()

        candidates = candidates[
            candidates[
                "fall_class"
            ].map(
                lambda x:
                quotas.get(x, 0) > 0
            )
        ]

        if candidates.empty:
            continue

        candidates[
            "remaining_quota"
        ] = candidates[
            "fall_class"
        ].map(quotas)

        max_quota = candidates[
            "remaining_quota"
        ].max()

        candidates = candidates[
            candidates[
                "remaining_quota"
            ] == max_quota
        ]

        row = candidates.sample(
            1,
            random_state=(
                SEED + len(selected)
            ),
        ).iloc[0]

        cls = row["fall_class"]

        selected.append(row)

        used_scenarios.add(
            row["scenario_id"]
        )

        selected_actors.add(
            actor
        )

        quotas[cls] -= 1

    # 2단계:
    # 각 클래스가 10개가 될 때까지 채움
    for cls in classes:

        while quotas[cls] > 0:

            candidates = scenario_df[
                (
                    scenario_df[
                        "fall_class"
                    ] == cls
                )
                &
                (
                    ~scenario_df[
                        "scenario_id"
                    ].isin(
                        used_scenarios
                    )
                )
            ].copy()

            if candidates.empty:
                raise RuntimeError(
                    f"Not enough scenarios "
                    f"for {cls}"
                )

            unseen = candidates[
                ~candidates[
                    "actor_id"
                ].isin(
                    selected_actors
                )
            ]

            if not unseen.empty:
                candidates = unseen

            row = candidates.sample(
                1,
                random_state=(
                    SEED
                    + len(selected) * 13
                ),
            ).iloc[0]

            selected.append(row)

            used_scenarios.add(
                row["scenario_id"]
            )

            selected_actors.add(
                row["actor_id"]
            )

            quotas[cls] -= 1

    result = pd.DataFrame(
        selected
    )

    return (
        result
        .sort_values(
            [
                "fall_class",
                "scenario_id",
            ]
        )
        .reset_index(drop=True)
    )


df = pd.read_csv(
    MANIFEST
)

scenario_df = (
    build_scenario_table(df)
)

selected = (
    select_diverse_scenarios(
        scenario_df
    )
)

SELECTED_OUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

selected.to_csv(
    SELECTED_OUT,
    index=False,
)

print(
    "=" * 100
)

print(
    "SELECTED SCENARIOS"
)

print(
    "=" * 100
)

print(
    "scenarios:",
    len(selected),
)

print(
    "actors:",
    selected[
        "actor_id"
    ].nunique(),
)

print()
print("classes:")

print(
    selected[
        "fall_class"
    ].value_counts()
)

print()
print("actors:")

print(
    selected[
        "actor_id"
    ].value_counts()
)

scenario_ids = set(
    selected[
        "scenario_id"
    ]
)

test_df = (
    df[
        df[
            "scenario_id"
        ].isin(
            scenario_ids
        )
    ]
    .sort_values(
        [
            "scenario_id",
            "camera",
        ]
    )
    .reset_index(
        drop=True
    )
)

print()

print(
    "videos:",
    len(test_df),
)

if (
    len(test_df)
    != len(selected) * 8
):
    raise RuntimeError(
        "Every selected scenario "
        "must have exactly 8 views"
    )

print()
print("Indexing MP4s...")

video_index = {
    p.stem: p
    for p
    in RAW_ROOT.rglob(
        "*.mp4"
    )
}

print(
    "videos indexed:",
    len(video_index),
)

missing = [
    scene_id
    for scene_id
    in test_df[
        "scene_id"
    ]
    if scene_id
    not in video_index
]

if missing:
    raise RuntimeError(
        f"Missing MP4s: "
        f"{missing[:10]}"
    )


model = YOLO(
    str(MODEL)
)

# MPS warm-up
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
        device="mps",
        verbose=False,
    )


rows = []

total_videos = len(
    test_df
)

for video_no, (_, row) in enumerate(
    test_df.iterrows(),
    start=1,
):

    scene_id = row[
        "scene_id"
    ]

    scenario_id = row[
        "scenario_id"
    ]

    camera = int(
        row["camera"]
    )

    is_fall = int(
        row["is_fall"]
    )

    video_path = (
        video_index[
            scene_id
        ]
    )

    cap = cv2.VideoCapture(
        str(video_path)
    )

    source_fps = cap.get(
        cv2.CAP_PROP_FPS
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
            / SAMPLE_FPS
        ),
    )

    fall_start = int(
        row[
            "fall_start_frame"
        ]
    )

    fall_end = int(
        row[
            "fall_end_frame"
        ]
    )

    totals = {
        "normal": 0,
        "pre": 0,
        "fall": 0,
        "post": 0,
    }

    detected = {
        "normal": 0,
        "pre": 0,
        "fall": 0,
        "post": 0,
    }

    kp_ratios = []
    infer_times = []
    candidate_counts = []

    frame_id = 0

    while True:

        ok, frame = cap.read()

        if not ok:
            break

        if (
            frame_id
            % step
            != 0
        ):
            frame_id += 1
            continue

        if not is_fall:

            phase = "normal"

        elif (
            frame_id
            < fall_start
        ):

            phase = "pre"

        elif (
            frame_id
            <= fall_end
        ):

            phase = "fall"

        else:

            phase = "post"

        totals[
            phase
        ] += 1

        t0 = (
            time.perf_counter()
        )

        result = model.predict(
            frame,
            imgsz=IMGSZ,
            conf=CONF,
            device="mps",
            max_det=5,
            verbose=False,
        )[0]

        infer_times.append(
            (
                time.perf_counter()
                - t0
            )
            * 1000.0
        )

        count = (
            len(
                result.boxes
            )
            if result.boxes
            is not None
            else 0
        )

        candidate_counts.append(
            count
        )

        person_idx = (
            select_person(
                result
            )
        )

        if (
            person_idx
            is not None
            and result.keypoints
            is not None
        ):

            detected[
                phase
            ] += 1

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
                )

                kp_ratios.append(
                    float(
                        np.mean(
                            kp_conf
                            >= 0.25
                        )
                    )
                )

        frame_id += 1

    cap.release()

    total_samples = sum(
        totals.values()
    )

    detected_samples = sum(
        detected.values()
    )

    detection_rate = (
        detected_samples
        / total_samples
        if total_samples
        else 0.0
    )

    visible_kpt = (
        float(
            np.mean(
                kp_ratios
            )
        )
        if kp_ratios
        else 0.0
    )

    def phase_rate(name):

        if totals[name] == 0:
            return np.nan

        return (
            detected[name]
            / totals[name]
        )

    result_row = {
        "scenario_id":
            scenario_id,

        "scene_id":
            scene_id,

        "actor_id":
            row[
                "actor_id"
            ],

        "fall_class":
            row[
                "fall_class"
            ],

        "camera":
            camera,

        "is_fall":
            is_fall,

        "samples":
            total_samples,

        "detection_rate":
            detection_rate,

        "normal_rate":
            phase_rate(
                "normal"
            ),

        "pre_rate":
            phase_rate(
                "pre"
            ),

        "fall_rate":
            phase_rate(
                "fall"
            ),

        "post_rate":
            phase_rate(
                "post"
            ),

        "visible_keypoints":
            visible_kpt,

        "pose_coverage":
            detection_rate
            * visible_kpt,

        "mean_candidates":
            (
                float(
                    np.mean(
                        candidate_counts
                    )
                )
                if candidate_counts
                else 0.0
            ),

        "mean_ms":
            (
                float(
                    np.mean(
                        infer_times
                    )
                )
                if infer_times
                else 0.0
            ),

        "p95_ms":
            (
                float(
                    np.percentile(
                        infer_times,
                        95,
                    )
                )
                if infer_times
                else 0.0
            ),
    }

    rows.append(
        result_row
    )

    fall_value = (
        result_row[
            "fall_rate"
        ]
    )

    fall_text = (
        "-"
        if pd.isna(
            fall_value
        )
        else (
            f"{fall_value:.2f}"
        )
    )

    print(
        f"[{video_no:03d}/"
        f"{total_videos:03d}] "
        f"{scene_id} "
        f"{row['fall_class']} "
        f"det="
        f"{detection_rate:.2f} "
        f"fall="
        f"{fall_text} "
        f"kpt="
        f"{visible_kpt:.2f} "
        f"ms="
        f"{result_row['mean_ms']:.1f}"
    )


result_df = pd.DataFrame(
    rows
)

OUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

result_df.to_csv(
    OUT,
    index=False,
)


print()
print(
    "=" * 100
)
print(
    "OVERALL"
)
print(
    "=" * 100
)

print(
    "detection_rate:",
    result_df[
        "detection_rate"
    ].mean(),
)

print(
    "worst_video:",
    result_df[
        "detection_rate"
    ].min(),
)

fall_rows = (
    result_df[
        result_df[
            "is_fall"
        ] == 1
    ]
)

print(
    "fall_rate:",
    fall_rows[
        "fall_rate"
    ].mean(),
)

print(
    "worst_fall_video:",
    fall_rows[
        "fall_rate"
    ].min(),
)

print(
    "visible_keypoints:",
    result_df[
        "visible_keypoints"
    ].mean(),
)

print(
    "pose_coverage:",
    result_df[
        "pose_coverage"
    ].mean(),
)

print(
    "mean_ms:",
    result_df[
        "mean_ms"
    ].mean(),
)

print(
    "p95_ms:",
    result_df[
        "p95_ms"
    ].mean(),
)


print()
print(
    "=" * 100
)
print(
    "BY CLASS"
)
print(
    "=" * 100
)

print(
    result_df
    .groupby(
        "fall_class"
    )
    .agg(
        videos=(
            "scene_id",
            "count",
        ),
        detection=(
            "detection_rate",
            "mean",
        ),
        worst_detection=(
            "detection_rate",
            "min",
        ),
        fall_detection=(
            "fall_rate",
            "mean",
        ),
        keypoints=(
            "visible_keypoints",
            "mean",
        ),
        coverage=(
            "pose_coverage",
            "mean",
        ),
    )
    .to_string()
)


print()
print(
    "=" * 100
)
print(
    "BY CAMERA"
)
print(
    "=" * 100
)

print(
    result_df
    .groupby(
        "camera"
    )
    .agg(
        videos=(
            "scene_id",
            "count",
        ),
        detection=(
            "detection_rate",
            "mean",
        ),
        worst_detection=(
            "detection_rate",
            "min",
        ),
        fall_detection=(
            "fall_rate",
            "mean",
        ),
        keypoints=(
            "visible_keypoints",
            "mean",
        ),
        coverage=(
            "pose_coverage",
            "mean",
        ),
    )
    .to_string()
)


print()
print(
    "=" * 100
)
print(
    "20 WORST VIDEOS"
)
print(
    "=" * 100
)

cols = [
    "scene_id",
    "actor_id",
    "fall_class",
    "camera",
    "detection_rate",
    "fall_rate",
    "visible_keypoints",
    "pose_coverage",
]

print(
    result_df
    .sort_values(
        [
            "detection_rate",
            "pose_coverage",
        ]
    )[
        cols
    ]
    .head(20)
    .to_string(
        index=False
    )
)


print()

print(
    "Saved:",
    OUT,
)

print(
    "Selected:",
    SELECTED_OUT,
)
