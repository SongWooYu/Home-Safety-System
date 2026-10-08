#!/usr/bin/env python3
"""Summarize Pi5 temporal fall shadow observations without reading video."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT / "runtime" / "fall-shadow-observations-quiet.jsonl",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser.parse_args()


def load_records(path: Path) -> list[dict]:
    paths = [path.with_name(path.name + ".1"), path]
    records = []
    for candidate in paths:
        if not candidate.exists():
            continue
        for line_number, line in enumerate(
            candidate.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {candidate}:{line_number}: {exc}") from exc
    return records


def summarize(records: list[dict]) -> dict:
    timestamps = []
    track_ids = set()
    transitions = Counter()
    rule_events = Counter()
    rule_states = Counter()
    quality_flags = Counter()
    ready = 0
    eligible = 0
    scores = []
    inference_ms = []

    for record in records:
        timestamp = record.get("timestamp")
        if timestamp:
            timestamps.append(datetime.fromisoformat(timestamp))
        if record.get("pose_inference_ms") is not None:
            inference_ms.append(float(record["pose_inference_ms"]))
        rule = record.get("rule") or {}
        if rule.get("event_type"):
            rule_events[str(rule["event_type"])] += 1
        if rule.get("fall_state"):
            rule_states[str(rule["fall_state"])] += 1
        for track in record.get("tracks", []):
            track_ids.add((record.get("camera_id"), track.get("track_id")))
            transition = track.get("transition")
            if transition:
                transitions[str(transition)] += 1
            for flag in track.get("quality_flags", []):
                quality_flags[str(flag)] += 1
            if track.get("ready"):
                ready += 1
                scores.append(float(track.get("alert_score", 0.0)))
                if track.get("quality_eligible"):
                    eligible += 1

    duration_seconds = 0.0
    if len(timestamps) >= 2:
        duration_seconds = max(0.0, (max(timestamps) - min(timestamps)).total_seconds())
    return {
        "records": len(records),
        "duration_seconds": round(duration_seconds, 3),
        "unique_tracks": len(track_ids),
        "ready_track_observations": ready,
        "quality_eligible_ratio": round(eligible / ready, 4) if ready else None,
        "max_alert_score": round(max(scores), 4) if scores else None,
        "mean_alert_score": round(sum(scores) / len(scores), 4) if scores else None,
        "mean_pose_inference_ms": (
            round(sum(inference_ms) / len(inference_ms), 3) if inference_ms else None
        ),
        "transitions": dict(transitions),
        "gru_transitions": dict(transitions),
        "rule_events": dict(rule_events),
        "rule_state_samples": dict(rule_states),
        "quality_flags": dict(quality_flags),
    }


def main() -> int:
    args = parse_args()
    records = load_records(args.path)
    if not records:
        raise SystemExit(f"No observation records found at {args.path}")
    result = summarize(records)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
