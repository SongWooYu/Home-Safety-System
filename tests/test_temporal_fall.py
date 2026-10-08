from __future__ import annotations

import unittest

import numpy as np

from smarthome_vision.temporal_fall import (
    TemporalFallShadow,
    build_b76_feature,
)


def make_pose(box=(20, 10, 120, 190)):
    keypoints = []
    for index in range(17):
        keypoints.append(
            [
                50.0 + index,
                40.0 + index * 2,
                0.9,
            ]
        )
    return {
        "box": list(box),
        "confidence": 0.9,
        "keypoints": keypoints,
    }


class FakeEnsemble:
    def __init__(self):
        self.high = True

    def predict(self, sequence):
        if self.high:
            probabilities = {
                "normal": 0.02,
                "falling": 0.18,
                "fallen": 0.80,
            }
        else:
            probabilities = {
                "normal": 0.98,
                "falling": 0.01,
                "fallen": 0.01,
            }
        return {
            "class_id": 2 if self.high else 0,
            "class_name": "fallen" if self.high else "normal",
            "probabilities": probabilities,
            "alert_score": probabilities["falling"] + probabilities["fallen"],
            "members": {},
        }


class TemporalFallTest(unittest.TestCase):
    def test_b76_feature_matches_expected_shape_and_globals(self):
        feature = build_b76_feature(
            make_pose(),
            (200, 200, 3),
        )

        self.assertEqual(feature.shape, (76,))
        self.assertEqual(feature.dtype, np.float32)
        self.assertAlmostEqual(float(feature[68]), 0.35, places=5)
        self.assertAlmostEqual(float(feature[69]), 0.50, places=5)
        self.assertAlmostEqual(float(feature[70]), 0.50, places=5)
        self.assertAlmostEqual(float(feature[71]), 0.90, places=5)
        self.assertAlmostEqual(float(feature[75]), 1.0, places=5)

    def test_shadow_confirmation_release_and_cooldown(self):
        ensemble = FakeEnsemble()
        detector = TemporalFallShadow(
            ensemble=ensemble,
            sequence_length=2,
            threshold=0.92,
            consecutive=2,
            release_frames=2,
            cooldown_seconds=5.0,
        )

        first = detector.update([make_pose()], (200, 200, 3), now=0.0)[0]
        second = detector.update([make_pose()], (200, 200, 3), now=0.1)[0]
        confirmed = detector.update([make_pose()], (200, 200, 3), now=0.2)[0]

        self.assertEqual(first["state"], "warming")
        self.assertFalse(second["shadow_alert"])
        self.assertEqual(confirmed["transition"], "fall_shadow_confirmed")
        self.assertTrue(confirmed["shadow_alert"])

        ensemble.high = False
        releasing = detector.update([make_pose()], (200, 200, 3), now=0.3)[0]
        cleared = detector.update([make_pose()], (200, 200, 3), now=0.4)[0]

        self.assertTrue(releasing["shadow_alert"])
        self.assertEqual(cleared["transition"], "fall_shadow_cleared")
        self.assertFalse(cleared["shadow_alert"])
        self.assertGreater(cleared["cooldown_remaining"], 4.9)

    def test_motion_prediction_keeps_track_identity(self):
        detector = TemporalFallShadow(
            ensemble=FakeEnsemble(),
            sequence_length=20,
        )

        ids = []
        for index in range(8):
            x = 20 + index * 18
            status = detector.update(
                [make_pose((x, 10, x + 100, 190))],
                (240, 640, 3),
                now=index * 0.1,
            )[0]
            ids.append(status["track_id"])

        self.assertEqual(set(ids), {1})

    def test_quality_diagnostics_do_not_gate_shadow_result(self):
        detector = TemporalFallShadow(
            ensemble=FakeEnsemble(),
            sequence_length=2,
            threshold=0.92,
            consecutive=1,
        )
        clipped_pose = make_pose((0, 0, 120, 190))
        for keypoint in clipped_pose["keypoints"]:
            keypoint[2] = 0.1

        detector.update([clipped_pose], (200, 200, 3), now=0.0)
        status = detector.update([clipped_pose], (200, 200, 3), now=0.1)[0]

        self.assertTrue(status["shadow_alert"])
        self.assertFalse(status["quality_eligible"])
        self.assertTrue(status["quality_is_diagnostic_only"])
        self.assertIn("low_keypoint_visibility", status["quality_flags"])
        self.assertIn("frame_edge_clipped", status["quality_flags"])


if __name__ == "__main__":
    unittest.main()
