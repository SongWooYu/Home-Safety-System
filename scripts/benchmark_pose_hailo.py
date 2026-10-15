#!/usr/bin/env python3
"""Benchmark Hailo pose metadata on the live Dahua latest-frame path."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smarthome_vision.config import load_config  # noqa: E402
from smarthome_vision.inference.hailo_pose import HailoPoseEstimator  # noqa: E402
from smarthome_vision.sources.rtsp import RtspSource  # noqa: E402


DEFAULT_HEF = "/usr/local/hailo/resources/models/hailo8/yolov8m_pose.hef"
DEFAULT_POSTPROCESS = "/usr/local/hailo/resources/so/libyolov8pose_postprocess.so"
DEFAULT_WHOLE_BUFFER = (
    "/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes/"
    "cropping_algorithms/libwhole_buffer.so"
)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float64), fraction * 100.0))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config/cameras.yaml"))
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--confidence", type=float, default=0.0)
    parser.add_argument("--hef", default=DEFAULT_HEF)
    parser.add_argument("--postprocess", default=DEFAULT_POSTPROCESS)
    parser.add_argument("--whole-buffer", default=DEFAULT_WHOLE_BUFFER)
    args = parser.parse_args()

    config = load_config(args.config)
    camera = next(item for item in config["cameras"] if item["id"] == "dahua")
    source = RtspSource(
        camera.get("url", ""),
        camera.get("transport", "tcp"),
        bool(camera.get("low_latency", False)),
        camera.get("backend", "auto"),
        int(camera.get("decode_width", 0)),
        int(camera.get("decode_height", 0)),
        int(camera.get("latency_ms", 100)),
        camera.get("codec", "h264"),
    )
    estimator = HailoPoseEstimator(
        args.hef,
        args.postprocess,
        args.whole_buffer,
        confidence=args.confidence,
    )

    latencies: list[float] = []
    source_ages: list[float] = []
    person_counts: list[int] = []
    visible_ratios: list[float] = []
    detection_confidences: list[float] = []
    keypoint_confidences: list[float] = []
    bbox_area_ratios: list[float] = []
    started = 0.0
    try:
        source.open()
        for _ in range(max(0, args.warmup)):
            estimator.estimate(source.read())

        started = time.monotonic()
        while time.monotonic() - started < max(1.0, args.duration):
            frame = source.read()
            inference_started = time.perf_counter()
            poses = estimator.estimate(frame)
            latencies.append((time.perf_counter() - inference_started) * 1000.0)
            source_ages.append(float(source.buffer_age_ms))
            person_counts.append(len(poses))
            for pose in poses:
                keypoints = np.asarray(pose["keypoints"], dtype=np.float32)
                visible_ratios.append(float(np.mean(keypoints[:, 2] >= 0.25)))
                detection_confidences.append(float(pose["confidence"]))
                keypoint_confidences.extend(float(value) for value in keypoints[:, 2])
                x1, y1, x2, y2 = pose["box"]
                bbox_area_ratios.append(
                    float((x2 - x1) * (y2 - y1) / (frame.shape[1] * frame.shape[0]))
                )
    finally:
        elapsed = max(0.0, time.monotonic() - started) if started else 0.0
        estimator.close()
        source.close()

    detected_frames = sum(count > 0 for count in person_counts)
    summary = {
        "backend": "hailo",
        "model": Path(args.hef).name,
        "postprocess_detection_floor": estimator.postprocess_confidence_floor,
        "requested_confidence": args.confidence,
        "frames": len(latencies),
        "elapsed_seconds": round(elapsed, 3),
        "effective_fps": round(len(latencies) / elapsed, 3) if elapsed else 0.0,
        "inference_ms_mean": round(statistics.fmean(latencies), 3) if latencies else 0.0,
        "inference_ms_p95": round(percentile(latencies, 0.95), 3),
        "source_buffer_age_ms_mean": round(statistics.fmean(source_ages), 3)
        if source_ages
        else 0.0,
        "source_buffer_age_ms_p95": round(percentile(source_ages, 0.95), 3),
        "frames_with_person_ratio": round(detected_frames / len(person_counts), 4)
        if person_counts
        else 0.0,
        "people_per_frame_mean": round(statistics.fmean(person_counts), 3)
        if person_counts
        else 0.0,
        "visible_keypoint_ratio_mean": round(statistics.fmean(visible_ratios), 4)
        if visible_ratios
        else 0.0,
        "detection_confidence_mean": round(
            statistics.fmean(detection_confidences), 4
        )
        if detection_confidences
        else 0.0,
        "keypoint_confidence_mean": round(statistics.fmean(keypoint_confidences), 4)
        if keypoint_confidences
        else 0.0,
        "keypoint_confidence_median": round(percentile(keypoint_confidences, 0.5), 4),
        "keypoint_confidence_p25": round(percentile(keypoint_confidences, 0.25), 4),
        "bbox_area_ratio_mean": round(statistics.fmean(bbox_area_ratios), 4)
        if bbox_area_ratios
        else 0.0,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
