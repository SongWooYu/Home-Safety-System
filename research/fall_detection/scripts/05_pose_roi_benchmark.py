from pathlib import Path
import json
import time

import cv2
import numpy as np
import pandas as pd
from ultralytics import YOLO


MANIFEST = Path("data/aihub71641/manifests/val_manifest.csv")
IMAGE_LABEL_ROOT = Path("data/aihub71641/labels/val/이미지")
RAW_ROOT = Path("/Volumes/AIData/aihub71641/raw/val")
MODEL = Path("models/yolo11n-pose.pt")

OUT = Path("data/pose_smoke/pose_roi320_benchmark.csv")
PREVIEW_DIR = Path("data/pose_smoke/roi_previews")

SCENARIO_ID = "00001_H_A_SY"

SAMPLE_FPS = 5.0
IMGSZ = 320
CONFS = [0.25, 0.10]

ROI_MARGIN = 0.20


def get_scene_bbox(scene_id):
    files = sorted(
        IMAGE_LABEL_ROOT.rglob(f"{scene_id}_I*.json")
    )

    boxes = []

    for path in files:
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)

        raw = data["bboxdata"]["bbox_location"]

        vals = [
            float(v.strip())
            for v in raw.split(",")
        ]

        if len(vals) != 4:
            continue

        x1, y1, x2, y2 = vals

        if x2 > x1 and y2 > y1:
            boxes.append(
                (x1, y1, x2, y2)
            )

    if not boxes:
        raise RuntimeError(
            f"No BBOX labels for {scene_id}"
        )

    a = np.asarray(boxes, dtype=np.float32)

    return {
        "count": len(boxes),
        "x1": float(a[:, 0].min()),
        "y1": float(a[:, 1].min()),
        "x2": float(a[:, 2].max()),
        "y2": float(a[:, 3].max()),
    }


def expand_bbox(box, width, height):
    x1 = box["x1"]
    y1 = box["y1"]
    x2 = box["x2"]
    y2 = box["y2"]

    bw = x2 - x1
    bh = y2 - y1

    x1 -= bw * ROI_MARGIN
    x2 += bw * ROI_MARGIN

    y1 -= bh * ROI_MARGIN
    y2 += bh * ROI_MARGIN

    x1 = max(0, int(round(x1)))
    y1 = max(0, int(round(y1)))

    x2 = min(width, int(round(x2)))
    y2 = min(height, int(round(y2)))

    return x1, y1, x2, y2


def select_person(result):
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

    areas = (
        (boxes[:, 2] - boxes[:, 0])
        * (boxes[:, 3] - boxes[:, 1])
    )

    return int(np.argmax(areas))


video_index = {
    p.stem: p
    for p in RAW_ROOT.rglob("*.mp4")
}

print("Videos indexed:", len(video_index))

df = pd.read_csv(MANIFEST)

group = (
    df[df["scenario_id"] == SCENARIO_ID]
    .sort_values("camera")
)

if len(group) != 8:
    raise RuntimeError(
        f"Expected 8 cameras, got {len(group)}"
    )

model = YOLO(str(MODEL))

PREVIEW_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

rows = []

for conf in CONFS:

    print()
    print("=" * 90)
    print(
        f"ROI BENCHMARK imgsz={IMGSZ} "
        f"conf={conf}"
    )
    print("=" * 90)

    dummy = np.zeros(
        (720, 720, 3),
        dtype=np.uint8,
    )

    for _ in range(2):
        model.predict(
            dummy,
            imgsz=IMGSZ,
            conf=conf,
            device="mps",
            verbose=False,
        )

    for _, row in group.iterrows():

        scene_id = row["scene_id"]
        camera = int(row["camera"])

        bbox_info = get_scene_bbox(
            scene_id
        )

        video = video_index[scene_id]

        cap = cv2.VideoCapture(
            str(video)
        )

        source_fps = cap.get(
            cv2.CAP_PROP_FPS
        )

        width = int(
            cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        )

        height = int(
            cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        )

        x1, y1, x2, y2 = expand_bbox(
            bbox_info,
            width,
            height,
        )

        roi_w = x2 - x1
        roi_h = y2 - y1

        roi_area_ratio = (
            (roi_w * roi_h)
            / (width * height)
        )

        step = max(
            1,
            round(
                source_fps / SAMPLE_FPS
            )
        )

        fall_start = int(
            row["fall_start_frame"]
        )

        fall_end = int(
            row["fall_end_frame"]
        )

        totals = {
            "pre": 0,
            "fall": 0,
            "post": 0,
        }

        detected = {
            "pre": 0,
            "fall": 0,
            "post": 0,
        }

        kp_ratios = []
        infer_times = []

        frame_id = 0
        preview_saved = False

        while True:

            ok, frame = cap.read()

            if not ok:
                break

            if frame_id % step != 0:
                frame_id += 1
                continue

            if frame_id < fall_start:
                phase = "pre"
            elif frame_id <= fall_end:
                phase = "fall"
            else:
                phase = "post"

            totals[phase] += 1

            crop = frame[
                y1:y2,
                x1:x2
            ]

            t0 = time.perf_counter()

            result = model.predict(
                crop,
                imgsz=IMGSZ,
                conf=conf,
                device="mps",
                max_det=3,
                verbose=False,
            )[0]

            infer_times.append(
                (
                    time.perf_counter()
                    - t0
                ) * 1000.0
            )

            idx = select_person(
                result
            )

            if (
                idx is not None
                and result.keypoints is not None
            ):
                detected[phase] += 1

                if (
                    result.keypoints.conf
                    is not None
                ):
                    kp_conf = (
                        result
                        .keypoints
                        .conf[idx]
                        .detach()
                        .cpu()
                        .numpy()
                    )

                    kp_ratios.append(
                        float(
                            np.mean(
                                kp_conf >= 0.25
                            )
                        )
                    )

            if (
                not preview_saved
                and frame_id >= fall_start
            ):
                plotted = result.plot()

                cv2.imwrite(
                    str(
                        PREVIEW_DIR
                        / (
                            f"{scene_id}"
                            f"_conf{conf}.jpg"
                        )
                    ),
                    plotted,
                )

                preview_saved = True

            frame_id += 1

        cap.release()

        total_n = sum(
            totals.values()
        )

        detected_n = sum(
            detected.values()
        )

        detection_rate = (
            detected_n / total_n
            if total_n
            else 0.0
        )

        def phase_rate(name):
            if totals[name] == 0:
                return float("nan")

            return (
                detected[name]
                / totals[name]
            )

        visible_kpt = (
            float(np.mean(kp_ratios))
            if kp_ratios
            else 0.0
        )

        pose_coverage = (
            detection_rate
            * visible_kpt
        )

        r = {
            "conf": conf,
            "camera": camera,
            "scene_id": scene_id,
            "bbox_labels":
                bbox_info["count"],
            "roi_width": roi_w,
            "roi_height": roi_h,
            "roi_area_ratio":
                roi_area_ratio,
            "detection_rate":
                detection_rate,
            "pre_rate":
                phase_rate("pre"),
            "fall_rate":
                phase_rate("fall"),
            "post_rate":
                phase_rate("post"),
            "visible_keypoint_ratio":
                visible_kpt,
            "pose_coverage":
                pose_coverage,
            "mean_ms":
                float(
                    np.mean(infer_times)
                ),
        }

        rows.append(r)

        print(
            f"C{camera} "
            f"bbox={bbox_info['count']} "
            f"roi={roi_w}x{roi_h} "
            f"area={roi_area_ratio:.2f} "
            f"all={r['detection_rate']:.2f} "
            f"pre={r['pre_rate']:.2f} "
            f"fall={r['fall_rate']:.2f} "
            f"post={r['post_rate']:.2f} "
            f"kpt={visible_kpt:.2f} "
            f"coverage={pose_coverage:.2f} "
            f"ms={r['mean_ms']:.1f}"
        )


out_df = pd.DataFrame(rows)

OUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

out_df.to_csv(
    OUT,
    index=False,
)

print()
print("=" * 90)
print("SUMMARY")
print("=" * 90)

summary = (
    out_df
    .groupby("conf")
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
        worst_fall_camera=(
            "fall_rate",
            "min",
        ),
        visible_keypoints=(
            "visible_keypoint_ratio",
            "mean",
        ),
        pose_coverage=(
            "pose_coverage",
            "mean",
        ),
        mean_ms=(
            "mean_ms",
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
print("Previews:", PREVIEW_DIR)
