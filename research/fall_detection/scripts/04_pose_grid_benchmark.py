from pathlib import Path
import time

import cv2
import numpy as np
import pandas as pd
from ultralytics import YOLO


MANIFEST = Path(
    "data/aihub71641/manifests/val_manifest.csv"
)

RAW_ROOT = Path(
    "/Volumes/AIData/aihub71641/raw/val"
)

MODEL = Path(
    "models/yolo11n-pose.pt"
)

OUT = Path(
    "data/pose_smoke/pose_grid_benchmark.csv"
)

SCENARIO_ID = "00001_H_A_SY"

SAMPLE_FPS = 5.0

CONFIGS = [
    (320, 0.25),
    (320, 0.10),
    (640, 0.25),
    (640, 0.10),
    (960, 0.10),
]


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


print("Indexing videos...")

video_index = {
    p.stem: p
    for p in RAW_ROOT.rglob("*.mp4")
}

print("Videos:", len(video_index))

df = pd.read_csv(MANIFEST)

group = (
    df[df["scenario_id"] == SCENARIO_ID]
    .sort_values("camera")
)

if len(group) != 8:
    raise RuntimeError(
        f"Expected 8 views, got {len(group)}"
    )

model = YOLO(str(MODEL))

rows = []

for imgsz, conf in CONFIGS:

    print()
    print("=" * 90)
    print(
        f"CONFIG imgsz={imgsz} conf={conf}"
    )
    print("=" * 90)

    # 각 해상도별 MPS compile/warmup
    dummy = np.zeros(
        (720, 1280, 3),
        dtype=np.uint8,
    )

    for _ in range(2):
        model.predict(
            dummy,
            imgsz=imgsz,
            conf=conf,
            device="mps",
            verbose=False,
        )

    for _, row in group.iterrows():

        scene_id = row["scene_id"]
        camera = int(row["camera"])

        video_path = video_index[scene_id]

        cap = cv2.VideoCapture(
            str(video_path)
        )

        source_fps = cap.get(
            cv2.CAP_PROP_FPS
        )

        step = max(
            1,
            round(source_fps / SAMPLE_FPS)
        )

        start = int(
            row["fall_start_frame"]
        )

        end = int(
            row["fall_end_frame"]
        )

        frame_index = 0

        phase_total = {
            "pre": 0,
            "fall": 0,
            "post": 0,
        }

        phase_detected = {
            "pre": 0,
            "fall": 0,
            "post": 0,
        }

        visible_kpts = []
        times_ms = []

        while True:

            ok, frame = cap.read()

            if not ok:
                break

            if frame_index % step != 0:
                frame_index += 1
                continue

            if frame_index < start:
                phase = "pre"
            elif frame_index <= end:
                phase = "fall"
            else:
                phase = "post"

            phase_total[phase] += 1

            t0 = time.perf_counter()

            result = model.predict(
                frame,
                imgsz=imgsz,
                conf=conf,
                device="mps",
                verbose=False,
                max_det=3,
            )[0]

            times_ms.append(
                (time.perf_counter() - t0)
                * 1000.0
            )

            person_idx = select_person(result)

            if (
                person_idx is not None
                and result.keypoints is not None
            ):

                phase_detected[phase] += 1

                if (
                    result.keypoints.conf
                    is not None
                ):
                    kp_conf = (
                        result.keypoints.conf[
                            person_idx
                        ]
                        .detach()
                        .cpu()
                        .numpy()
                    )

                    visible_kpts.append(
                        float(
                            np.mean(
                                kp_conf >= 0.25
                            )
                        )
                    )

            frame_index += 1

        cap.release()

        total = sum(
            phase_total.values()
        )

        detected = sum(
            phase_detected.values()
        )

        def rate(name):
            n = phase_total[name]
            if n == 0:
                return float("nan")

            return (
                phase_detected[name] / n
            )

        result_row = {
            "imgsz": imgsz,
            "conf": conf,
            "camera": camera,
            "scene_id": scene_id,
            "samples": total,
            "detection_rate":
                detected / total
                if total else 0,
            "pre_rate": rate("pre"),
            "fall_rate": rate("fall"),
            "post_rate": rate("post"),
            "visible_keypoint_ratio":
                float(np.mean(visible_kpts))
                if visible_kpts
                else 0,
            "mean_ms":
                float(np.mean(times_ms))
                if times_ms
                else 0,
            "p95_ms":
                float(
                    np.percentile(
                        times_ms,
                        95,
                    )
                )
                if times_ms
                else 0,
        }

        rows.append(result_row)

        print(
            f"C{camera} "
            f"all={result_row['detection_rate']:.2f} "
            f"pre={result_row['pre_rate']:.2f} "
            f"fall={result_row['fall_rate']:.2f} "
            f"post={result_row['post_rate']:.2f} "
            f"kpt={result_row['visible_keypoint_ratio']:.2f} "
            f"ms={result_row['mean_ms']:.1f}"
        )


result_df = pd.DataFrame(rows)

OUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

result_df.to_csv(
    OUT,
    index=False,
)

print()
print("=" * 90)
print("CONFIG SUMMARY")
print("=" * 90)

summary = (
    result_df
    .groupby(["imgsz", "conf"])
    .agg(
        detection_rate=(
            "detection_rate",
            "mean",
        ),
        worst_camera=(
            "detection_rate",
            "min",
        ),
        fall_rate=(
            "fall_rate",
            "mean",
        ),
        visible_keypoints=(
            "visible_keypoint_ratio",
            "mean",
        ),
        mean_ms=(
            "mean_ms",
            "mean",
        ),
        p95_ms=(
            "p95_ms",
            "mean",
        ),
    )
    .reset_index()
)

print(
    summary.to_string(
        index=False
    )
)

print()
print("Saved:", OUT)
