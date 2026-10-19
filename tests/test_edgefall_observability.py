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
    def test_transitions_use_standard_mqtt_contract_and_normal_start_is_silent(self):
        worker = CameraWorker.__new__(CameraWorker)
        worker.camera_id = "dahua"
        worker.source_type = "rtsp"
        worker.edgefall_shadow = _EdgeFall()
        worker.edgefall_publish_mqtt = True
        worker.event_bus = _EventBus()
        worker._edgefall_track_states = {}
        worker._edgefall_event_ids = {}
        worker._edgefall_empty_since = None
        worker._fall_state = "normal"
        worker._fall_confidence = 0.0
        worker._pose_state = "unknown"

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
                "fall_suspected",
                "fall_confirmed",
                "fall_cleared",
            ],
        )
        self.assertTrue(output.called)
        for args, kwargs in worker.event_bus.events:
            self.assertEqual(args[0], "dahua")
            self.assertTrue(kwargs["publish"])
            self.assertTrue(args[3]["published_to_mqtt"])
            self.assertEqual(args[3]["backend"], "hailo_edgefall")

    def test_repeated_native_event_id_is_not_published_twice(self):
        worker = CameraWorker.__new__(CameraWorker)
        worker.camera_id = "dahua"
        worker.source_type = "rtsp"
        worker.edgefall_shadow = _EdgeFall()
        worker.edgefall_publish_mqtt = True
        worker.event_bus = _EventBus()
        worker._edgefall_track_states = {4: "suspected"}
        worker._edgefall_event_ids = {}
        worker._edgefall_empty_since = None
        worker._fall_state = "suspected"
        worker._fall_confidence = 0.0
        worker._pose_state = "suspected"

        worker._record_edgefall_transitions([_track("fallen", fall_event=True)])
        worker._record_edgefall_transitions([_track("fallen", fall_event=True)])

        self.assertEqual(len(worker.event_bus.events), 1)
        self.assertEqual(worker.event_bus.events[0][0][1], "fall_confirmed")
