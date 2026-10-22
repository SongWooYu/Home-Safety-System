import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from flask import Flask

from smarthome_vision.face_enrollment import GuidedCapture, EnrollmentManager, register_enrollment_routes
from test_face_registry import fake_registry


def observation(view="front", feature=None):
    return {"view":view, "feature":np.array([1., 0.]) if feature is None else feature}


class GuidedEnrollmentTest(unittest.TestCase):
    def complete_view(self, capture, view, start):
        result = False
        for i in range(5):
            stamp = start + i * .3
            result = capture.feed(observation(view), stamp, stamp)
        return result

    def test_time_alone_never_advances_and_wrong_pose_prompts(self):
        capture = GuidedCapture()
        self.complete_view(capture, "front", 1)
        self.assertEqual(capture.step, 1)
        self.assertEqual(capture.public()["direction"], "right")
        self.assertEqual(capture.public()["display_direction"], "left")
        self.assertIn("본인 왼쪽", capture.public()["message"])
        for stamp in range(5, 40):
            self.assertFalse(capture.feed(observation("front"), stamp, stamp))
        self.assertEqual(capture.step, 1)
        self.assertIn("아직 요청한 방향", capture.message)
        self.assertEqual(capture.samples["right"], [])

    def test_three_valid_views_complete(self):
        capture = GuidedCapture()
        self.assertFalse(self.complete_view(capture, "front", 1))
        self.assertFalse(self.complete_view(capture, "right", 4))
        self.assertTrue(self.complete_view(capture, "left", 7))
        self.assertEqual(capture.public()["progress"], 100)
        self.assertNotIn("feature", str(capture.public()))

    def test_duplicate_or_stale_frames_never_complete(self):
        capture = GuidedCapture()
        for _ in range(30):
            capture.feed(observation(), 1, 1)
        self.assertEqual(len(capture.samples["front"]), 1)
        capture.feed(observation(), 1, 10)
        self.assertEqual(len(capture.samples["front"]), 0)
        self.assertEqual(capture.step, 0)

    def test_blur_and_other_person_reset_current_stage(self):
        capture = GuidedCapture()
        self.complete_view(capture, "front", 1)
        capture.feed(observation("right"), 4, 4)
        capture.feed({"error":"얼굴이 흐려요"}, 4.3, 4.3)
        self.assertEqual(capture.samples["right"], [])
        capture.feed(observation("right", np.array([0., 1.])), 4.6, 4.6)
        self.assertIn("같은 얼굴", capture.message)
        self.assertEqual(capture.step, 1)

    def test_observation_rejects_missing_blurred_and_extreme_faces(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = fake_registry(Path(temp))
            frame = np.zeros((200, 200, 3), dtype=np.uint8)
            registry._detect = lambda frame: []
            self.assertIn("error", registry.enrollment_observation(frame))
            face = np.array([20,20,100,100,50,50,100,50,75,70,60,100,90,100,.99])
            registry._detect = lambda frame: [face]
            registry._feature = lambda frame, face: np.array([1., 0.])
            self.assertIn("흐려요", registry.enrollment_observation(frame)["error"])
            registry._face_sharpness = lambda frame, face: 100
            self.assertEqual(registry.enrollment_observation(frame)["view"], "front")
            registry._face_yaw = lambda face: .9
            self.assertIn("너무 옆", registry.enrollment_observation(frame)["error"])

    def test_cancel_conflict_timeout_do_not_save_and_free_samples(self):
        registry = Mock(enrollment_min_samples_per_view=3)
        worker = SimpleNamespace(face_enrollment=True, registration_sample=lambda: (0, None))
        manager = EnrollmentManager(SimpleNamespace(face_registry=registry, workers={"cam3":worker}))
        with patch("smarthome_vision.face_enrollment.threading.Thread"):
            state = manager.start("cam3", "테스트")
            with self.assertRaises(RuntimeError):
                manager.start("cam3", "다른 사람")
            self.assertEqual(manager.get(state["id"], cancel=True)["status"], "cancelled")
            self.assertNotIn("capture", manager.session)
            manager.start("cam3", "테스트")
            manager.session["started"] = time.monotonic() - 46
            manager._run(manager.session, worker, registry, "테스트")
            self.assertEqual(manager.session["status"], "failed")
            registry.save_guided_samples.assert_not_called()

    def test_api_new_session_and_cancel_no_admin_or_biometrics(self):
        app = Flask(__name__)
        pipeline = SimpleNamespace(face_registry=Mock(enrollment_min_samples_per_view=3),
                                   workers={"cam3":SimpleNamespace(face_enrollment=True)})
        register_enrollment_routes(app, pipeline)
        client = app.test_client()
        with patch("smarthome_vision.face_enrollment.threading.Thread"):
            result = client.post("/api/faces/enrollment", json={"name":"테스트", "camera_id":"cam3"})
            self.assertEqual(result.status_code, 202)
            url = "/api/faces/enrollment/" + result.json["id"]
            self.assertEqual(client.get(url).headers["Cache-Control"], "no-store")
            self.assertNotIn("feature", result.get_data(as_text=True))
            self.assertEqual(client.delete(url).json["status"], "cancelled")
            self.assertEqual(client.get(url + "invalid").status_code, 404)
            self.assertEqual(client.post("/api/faces/enrollment", json={}, headers={"Origin":"https://other.example"}).status_code, 403)
