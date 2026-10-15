from __future__ import annotations

import unittest
from unittest.mock import patch

from smarthome_vision.pipeline import CameraWorker


class _EventBus:
    def __init__(self) -> None:
        self.events: list[tuple[tuple, dict]] = []

    def emit(self, *args, **kwargs):
        self.events.append((args, kwargs))


class _EdgeFall:
    profile = "edgefallkit-test+strict"


def _track(state: str, *, fall_event: bool = False) -> dict:
    return {
        "track_id": 4,
        "state": state,
        "fall_event": fall_event,
        "event_id": 1 if fall_event else 0,
        "temporal_probability": 0.93,
        "temporal_positive": True,
        "hip_drop_speed": 0.5,
        "hip_drop_distance": 0.2,
        "torso_angle_deg": 70.0,
        "bbox_aspect_ratio": 1.6,
    }


class EdgeFallObservabilityTest(unittest.TestCase):
    def test_transitions_are_local_only_and_normal_start_is_silent(self):
        worker = CameraWorker.__new__(CameraWorker)
        worker.camera_id = "dahua"
        worker.edgefall_shadow = _EdgeFall()
        worker.event_bus = _EventBus()
        worker._edgefall_track_states = {}

        with patch("builtins.print") as output:
            worker._record_edgefall_transitions([_track("normal")])
            worker._record_edgefall_transitions([_track("suspected")])
            worker._record_edgefall_transitions(
                [_track("fallen", fall_event=True)]
            )
            worker._record_edgefall_transitions([_track("recovering")])
            worker._record_edgefall_transitions([_track("normal")])

        event_types = [entry[0][1] for entry in worker.event_bus.events]
        self.assertEqual(
            event_types,
            [
                "fall_edgefall_suspected",
                "fall_edgefall_confirmed",
                "fall_edgefall_recovering",
                "fall_edgefall_cleared",
            ],
        )
        self.assertTrue(output.called)
        for args, kwargs in worker.event_bus.events:
            self.assertEqual(args[0], "dahua")
            self.assertFalse(kwargs["publish"])
            self.assertFalse(args[3]["published_to_mqtt"])
