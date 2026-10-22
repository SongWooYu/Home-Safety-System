import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from smarthome_vision.events import EventBus
from smarthome_vision.pipeline import CameraWorker, VisionPipeline
from smarthome_vision.pose_overlay import draw_pose_shapes


def example_pose():
    points = [[0, 0, 0] for _ in range(17)]
    points[5] = [100, 100, 0.9]
    points[7] = [150, 200, 0.8]
    points[9] = [200, 300, 0.1]  # Missing wrist: must not draw or interpolate.
    return {"box":[50, 60, 250, 400], "confidence":0.9, "keypoints":points}


class PoseEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.raw = np.zeros((540, 960, 3), dtype=np.uint8)
        self.now = time.monotonic()
        self.worker = SimpleNamespace(
            _lock=threading.Lock(), _pose_evidence=(self.raw, [example_pose()], 12, self.now),
            _latest_frame=np.full_like(self.raw, 255), _latest_frame_seq=13,
            _latest_frame_captured_at=self.now,
        )
        self.pipeline = VisionPipeline.__new__(VisionPipeline)
        self.pipeline.workers = {"dahua":self.worker}

    def test_shapes_scale_and_missing_joints_not_invented(self):
        frame = np.zeros((270, 480, 3), dtype=np.uint8)
        result = draw_pose_shapes(frame, [example_pose()], self.raw.shape)
        self.assertEqual(result, {"boxes":1, "visible_keypoints":2})
        self.assertEqual(tuple(frame[30, 25]), (255, 0, 255))
        self.assertEqual(tuple(frame[50, 50]), (0, 220, 255))
        self.assertEqual(tuple(frame[150, 100]), (0, 0, 0))

    def test_snapshot_uses_pose_frame_not_newest_raw_and_leaves_source_unchanged(self):
        jpeg, metadata = self.pipeline.capture_event_snapshot("dahua")
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(image.shape[:2], (580, 960))  # 40px footer preserves whole scene.
        self.assertLess(int(image[500, 900].max()), 5)  # black analyzed frame, not white latest frame
        self.assertGreater(int(image[60, 50, 0]), 130)  # magenta box
        self.assertGreater(int(image[100, 100, 2]), 130)  # joint
        self.assertTrue(metadata["pose_frame_matched"])
        self.assertEqual(metadata["frame_seq"], 12)
        self.assertEqual(metadata["overlay"], {"boxes":1, "visible_keypoints":2})
        self.assertEqual(int(self.raw.max()), 0)

    def test_stale_pose_never_drawn_on_a_newer_frame(self):
        self.worker._pose_evidence = (self.raw, [example_pose()], 12, self.now - 3)
        jpeg, metadata = self.pipeline.capture_event_snapshot("dahua")
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        self.assertGreater(int(image[500, 900].min()), 250)
        self.assertFalse(metadata["pose_frame_matched"])
        self.assertEqual(metadata["overlay"], {"boxes":0, "visible_keypoints":0})
        self.worker._latest_frame_captured_at -= 3
        self.assertIsNone(self.pipeline.capture_event_snapshot("dahua"))

    def test_no_person_and_demo_do_not_fabricate_fall_pose(self):
        self.worker._pose_evidence = (self.raw, [], 12, self.now)
        with patch("smarthome_vision.pipeline.cv2.putText", wraps=cv2.putText) as text:
            _, metadata = self.pipeline.capture_event_snapshot("dahua", details={"test":True})
        self.assertIn("MANUAL TEST - NOT AI FALL", text.call_args.args[1])
        self.assertEqual(metadata["overlay"], {"boxes":0, "visible_keypoints":0})
        self.assertTrue(metadata["pose_frame_matched"])

    def test_event_metadata_has_shapes_but_mqtt_never_contains_image(self):
        bus = EventBus({})
        bus.snapshot_provider = self.pipeline.capture_event_snapshot
        event = bus.emit("manual-test", "fall_confirmed", details={"test":True, "source_camera_id":"dahua"})
        self.assertEqual(event["details"]["snapshot"]["overlay"]["boxes"], 1)
        self.assertIsNotNone(bus.evidence.get(event["event_id"]))
        self.assertNotIn("jpeg", event["details"])

    def test_real_ai_loop_publishes_the_frame_pair_before_confirmation(self):
        bus = EventBus({})
        worker = CameraWorker(
            {"id":"dahua", "type":"rtsp", "ai_enabled":True},
            SimpleNamespace(), SimpleNamespace(estimate=lambda frame: [example_pose()]),
            None, None, None, None, bus, 640, 360, 10, 80,
            {"enabled":True, "analysis_fps":15}, {}, 5,
        )
        worker._latest_frame = self.raw
        worker._latest_frame_seq = 42
        worker._latest_frame_captured_at = worker._last_frame_at = time.monotonic()
        worker._online = True
        self.pipeline.workers["dahua"] = worker
        bus.snapshot_provider = self.pipeline.capture_event_snapshot

        def track_update(*args):
            # Capture progressed while the model was working. Evidence stays frame 42.
            worker._latest_frame = np.full_like(self.raw, 255)
            worker._latest_frame_seq = 43
            worker._stop.set()
            return [{"track_id":1, "state":"fallen", "fall_event":True,
                     "event_id":1, "temporal_probability":0.93}]

        worker.edgefall_shadow = SimpleNamespace(update=track_update, profile="fixture")
        with patch("builtins.print"):
            worker._ai_loop()  # deterministic single iteration, no hardware or broker
        event = next(e for e in bus.recent() if e["event_type"] == "fall_confirmed")
        self.assertEqual(event["details"]["snapshot"]["frame_seq"], 42)
        self.assertEqual(event["details"]["snapshot"]["overlay"]["boxes"], 1)
        self.assertIsNone(worker._error)
