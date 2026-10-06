from pathlib import Path
import time

import cv2
import numpy as np
import pandas as pd
from ultralytics import YOLO


MANIFEST = Path("data/aihub71641/manifests/val_manifest.csv")
RAW_ROOT = Path("/Volumes/AIData/aihub71641/raw/val")
OUT_ROOT = Path("data/pose_smoke")

SAMPLE_FPS = 10.0
IMGSZ = 320
CONF = 0.25


def build_video_index():
    print("Indexing MP4 files...")
    index = {}

    for p in RAW_ROOT.rglob("*.mp4"):
        index[p.stem] = p

    print("MP4 indexed:", len(index))
    return index


def choose_scenario(df):
    # 낙상이고 C1~C8 8개 시점이 모두 존재하는 첫 scenario
    for scenario_id, group in df[df["is_fall"] == 1].groupby("scenario_id"):
        if len(group) == 8:
            return scenario_id, group.sort_values("camera")

    raise RuntimeError("8-view fall scenario not found")


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


df = pd.read_csv(MANIFEST)
video_index = build_video_index()

scenario_id, group = choose_scenario(df)

print()
print("Selected scenario:", scenario_id)
print(group[
    [
        "scene_id",
        "camera",
        "fall_class",
        "fall_start_frame",
        "fall_end_frame",
    ]
].to_string(index=False))

print()
print("Loading YOLO11n-pose...")

model = YOLO("yolo11n-pose.pt")

scenario_out = OUT_ROOT / scenario_id
scenario_out.mkdir(parents=True, exist_ok=True)

summary = []

for _, row in group.iterrows():

    scene_id = row["scene_id"]

    if scene_id not in video_index:
        print("MISSING:", scene_id)
        continue

    video_path = video_index[scene_id]

    cap = cv2.VideoCapture(str(video_path))

    source_fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if source_fps <= 0:
        raise RuntimeError(f"Invalid FPS: {video_path}")

    step = max(1, round(source_fps / SAMPLE_FPS))

    print()
    print("=" * 80)
    print("Scene:", scene_id)
    print("Video:", video_path)
    print("FPS:", source_fps)
    print("Frames:", frame_count)
    print("Sample step:", step)

    frame_ids = []
    timestamps = []

    keypoints_xy = []
    keypoints_conf = []

    boxes_xyxy = []
    box_conf = []

    valid = []
    inference_ms = []

    frame_index = 0
    processed = 0

    while True:
        ok, frame = cap.read()

        if not ok:
            break

        if frame_index % step != 0:
            frame_index += 1
            continue

        started = time.perf_counter()

        result = model.predict(
            source=frame,
            imgsz=IMGSZ,
            conf=CONF,
            device="mps",
            verbose=False,
        )[0]

        elapsed_ms = (time.perf_counter() - started) * 1000.0

        person_idx = select_person(result)

        frame_ids.append(frame_index)
        timestamps.append(frame_index / source_fps)
        inference_ms.append(elapsed_ms)

        if person_idx is None or result.keypoints is None:
            keypoints_xy.append(
                np.full((17, 2), np.nan, dtype=np.float32)
            )
            keypoints_conf.append(
                np.zeros(17, dtype=np.float32)
            )
            boxes_xyxy.append(
                np.full(4, np.nan, dtype=np.float32)
            )
            box_conf.append(0.0)
            valid.append(0)

        else:
            xy = (
                result.keypoints.xyn[person_idx]
                .detach()
                .cpu()
                .numpy()
                .astype(np.float32)
            )

            if result.keypoints.conf is not None:
                kp_conf = (
                    result.keypoints.conf[person_idx]
                    .detach()
                    .cpu()
                    .numpy()
                    .astype(np.float32)
                )
            else:
                kp_conf = np.ones(17, dtype=np.float32)

            box = (
                result.boxes.xyxyn[person_idx]
                .detach()
                .cpu()
                .numpy()
                .astype(np.float32)
            )

            conf = float(
                result.boxes.conf[person_idx]
                .detach()
                .cpu()
                .item()
            )

            keypoints_xy.append(xy)
            keypoints_conf.append(kp_conf)
            boxes_xyxy.append(box)
            box_conf.append(conf)
            valid.append(1)

        processed += 1

        frame_index += 1

    cap.release()

    output = scenario_out / f"{scene_id}.npz"

    np.savez_compressed(
        output,
        scene_id=scene_id,
        camera=int(row["camera"]),
        source_fps=float(source_fps),
        sample_fps=float(SAMPLE_FPS),
        frame_ids=np.asarray(frame_ids, dtype=np.int32),
        timestamps=np.asarray(timestamps, dtype=np.float32),
        keypoints_xy=np.asarray(keypoints_xy, dtype=np.float32),
        keypoints_conf=np.asarray(keypoints_conf, dtype=np.float32),
        boxes_xyxy=np.asarray(boxes_xyxy, dtype=np.float32),
        box_conf=np.asarray(box_conf, dtype=np.float32),
        valid=np.asarray(valid, dtype=np.uint8),
        fall_start_frame=int(row["fall_start_frame"]),
        fall_end_frame=int(row["fall_end_frame"]),
    )

    detection_rate = (
        float(np.mean(valid))
        if valid
        else 0.0
    )

    mean_ms = (
        float(np.mean(inference_ms))
        if inference_ms
        else 0.0
    )

    print("Processed samples:", processed)
    print(f"Detection rate : {detection_rate:.3f}")
    print(f"Mean infer ms  : {mean_ms:.1f}")
    print("Saved:", output)

    summary.append({
        "scene_id": scene_id,
        "camera": int(row["camera"]),
        "samples": processed,
        "detection_rate": detection_rate,
        "mean_inference_ms": mean_ms,
    })


summary_df = pd.DataFrame(summary)

summary_path = scenario_out / "summary.csv"
summary_df.to_csv(summary_path, index=False)

print()
print("=" * 80)
print("SUMMARY")
print("=" * 80)
print(summary_df.to_string(index=False))

if len(summary_df):
    print()
    print(
        "overall detection rate:",
        summary_df["detection_rate"].mean()
    )
    print(
        "overall inference ms:",
        summary_df["mean_inference_ms"].mean()
    )

print()
print("Saved summary:", summary_path)
