#!/usr/bin/env python3
"""Benchmark the available NCNN pose exports on the Dahua camera.

Frames are captured once and kept in memory so every model sees the same input.
The RTSP URL is intentionally never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from smarthome_vision.config import load_config  # noqa: E402
from smarthome_vision.inference import NcnnPoseEstimator  # noqa: E402
from smarthome_vision.sources import RtspSource  # noqa: E402


MODEL_VARIANTS = (
    ("320", "models/yolo11n-pose_ncnn_model", 320),
    ("640", "models/yolo11n-pose_640_ncnn_model", 640),
    ("960", "models/yolo11n-pose_960_ncnn_model", 960),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare the NCNN pose models using identical live Dahua frames."
    )
    parser.add_argument("--frames", type=int, default=20, help="frames kept in memory")
    parser.add_argument("--warmup", type=int, default=3, help="warm-up inferences per model")
    parser.add_argument(
        "--models",
        nargs="+",
        choices=[item[0] for item in MODEL_VARIANTS],
        default=[item[0] for item in MODEL_VARIANTS],
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=None,
        help="override the configured person confidence threshold",
    )
    parser.add_argument("--json", action="store_true", help="also emit a JSON summary")
    return parser.parse_args()


def dahua_config(config: dict) -> dict:
    for camera in config.get("cameras", []):
        if camera.get("id") == "dahua" and camera.get("type") == "rtsp":
            if not camera.get("url"):
                raise RuntimeError("DAHUA_RTSP_URL is not configured")
            return camera
    raise RuntimeError("Dahua RTSP camera is not configured")


def capture_frames(camera: dict, count: int) -> list[np.ndarray]:
    source = RtspSource(camera["url"], camera.get("transport", "tcp"))
    frames: list[np.ndarray] = []
    source.open()
    try:
        while len(frames) < count:
            frames.append(source.read())
    finally:
        source.close()
    return frames


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def benchmark_variant(
    name: str,
    model_path: Path,
    input_size: int,
    frames: list[np.ndarray],
    warmup: int,
    confidence: float,
    nms_iou: float,
    threads: int,
    keypoint_confidence: float,
) -> dict:
    estimator = NcnnPoseEstimator(
        model_dir=str(model_path),
        input_size=input_size,
        confidence=confidence,
        nms_iou=nms_iou,
        threads=threads,
    )
    for index in range(warmup):
        estimator.estimate(frames[index % len(frames)])

    latencies_ms: list[float] = []
    person_counts: list[int] = []
    visible_ratios: list[float] = []
    person_confidences: list[float] = []
    for frame in frames:
        started = time.perf_counter()
        poses = estimator.estimate(frame)
        latencies_ms.append((time.perf_counter() - started) * 1000.0)
        person_counts.append(len(poses))
        for pose in poses:
            keypoints = np.asarray(pose["keypoints"], dtype=np.float32)
            visible_ratios.append(float(np.mean(keypoints[:, 2] >= keypoint_confidence)))
            person_confidences.append(float(pose["confidence"]))

    mean_ms = float(np.mean(latencies_ms))
    return {
        "model": name,
        "input_size": input_size,
        "frames": len(frames),
        "mean_ms": round(mean_ms, 3),
        "p50_ms": round(percentile(latencies_ms, 50), 3),
        "p95_ms": round(percentile(latencies_ms, 95), 3),
        "throughput_fps": round(1000.0 / mean_ms, 3),
        "mean_persons_per_frame": round(float(np.mean(person_counts)), 3),
        "frames_with_person_ratio": round(float(np.mean(np.asarray(person_counts) > 0)), 3),
        "mean_visible_keypoint_ratio": (
            round(float(np.mean(visible_ratios)), 3) if visible_ratios else None
        ),
        "mean_person_confidence": (
            round(float(np.mean(person_confidences)), 3) if person_confidences else None
        ),
    }


def main() -> int:
    args = parse_args()
    if args.frames <= 0 or args.warmup < 0:
        raise SystemExit("--frames must be positive and --warmup must be non-negative")

    config = load_config(PROJECT_ROOT / "config" / "cameras.yaml")
    fall = config["fall_detection"]
    confidence = (
        float(args.confidence)
        if args.confidence is not None
        else float(fall.get("confidence", 0.10))
    )
    camera = dahua_config(config)
    selected = {name for name in args.models}

    print(f"Capturing {args.frames} Dahua frames in memory (RTSP URL hidden)...")
    frames = capture_frames(camera, args.frames)
    height, width = frames[0].shape[:2]
    print(f"Captured {len(frames)} frames at {width}x{height}.")

    results = []
    for name, relative_path, input_size in MODEL_VARIANTS:
        if name not in selected:
            continue
        model_path = PROJECT_ROOT / relative_path
        if not model_path.is_dir():
            raise FileNotFoundError(f"NCNN model directory is missing: {model_path}")
        print(f"Benchmarking {name}px NCNN...", flush=True)
        results.append(
            benchmark_variant(
                name=name,
                model_path=model_path,
                input_size=input_size,
                frames=frames,
                warmup=args.warmup,
                confidence=confidence,
                nms_iou=float(fall.get("nms_iou", 0.45)),
                threads=int(fall.get("threads", 4)),
                keypoint_confidence=float(fall.get("keypoint_confidence", 0.25)),
            )
        )

    print("\nmodel  mean ms  p95 ms  max FPS  persons/frame  person frames  visible KP")
    for result in results:
        visible = result["mean_visible_keypoint_ratio"]
        print(
            f"{result['model']:>5}  {result['mean_ms']:>7.1f}  "
            f"{result['p95_ms']:>6.1f}  {result['throughput_fps']:>7.2f}  "
            f"{result['mean_persons_per_frame']:>13.2f}  "
            f"{result['frames_with_person_ratio']:>13.2f}  "
            f"{visible if visible is not None else '-'}"
        )

    if args.json:
        print("\n" + json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
