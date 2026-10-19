#!/usr/bin/env python3
"""Replay saved pose metadata through native policies, never video/Hailo/MQTT.

Output measures policy behavior on an unlabeled trace, NOT recall or accuracy.
Run with PYTHONPATH=src .venv/bin/python scripts/replay_edgefall_diagnostics.py
--input runtime/diagnostics/...jsonl --library /absolute/path/to/library.so
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from smarthome_vision.edgefall_shadow import EdgeFallRuntime


def replay(path: Path, library: Path) -> dict:
    rows = person_frames = 0
    states, reasons = Counter(), Counter()
    events = []
    first = last = None
    positive = candidates = 0
    with EdgeFallRuntime(str(library.resolve())) as runtime, path.open() as stream:
        profile = runtime.profile
        for line in stream:
            row = json.loads(line)
            rows += 1
            person_frames += bool(row["poses"])
            first = first or row["timestamp"]
            last = row["timestamp"]
            width, height = row["frame_size"]
            tracks = runtime.update(row["poses"], width, height, row["monotonic_sec"])
            for track in tracks:
                states[track["state"]] += 1
                reasons[track["decision_reason"]] += 1
                positive += track["temporal_positive"]
                candidates += track["geometry_candidate"]
                if track["fall_event"]:
                    events.append({"timestamp": row["timestamp"], "frame_seq": row["frame_seq"],
                                   **track})
    return {"input": str(path), "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "library": str(library), "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
            "profile": profile, "start": first, "end": last, "rows": rows,
            "person_frames": person_frames, "states": dict(states), "reasons": dict(reasons),
            "model_positive_observations": positive, "geometry_candidates": candidates,
            "confirmed_events": events,
            "warning": "Unlabeled policy replay; event count is not detection accuracy."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--library", type=Path, action="append", required=True)
    args = parser.parse_args()
    for library in args.library:
        print(json.dumps(replay(args.input, library), ensure_ascii=False))
