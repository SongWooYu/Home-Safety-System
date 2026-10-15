from __future__ import annotations

import unittest

import numpy as np

from smarthome_vision.pipeline import CameraWorker, pose_visible_keypoint_ratio


class OverlayScalingTest(unittest.TestCase):
    def test_detection_box_scales_from_source_to_stream_coordinates(self):
        worker = CameraWorker.__new__(CameraWorker)
        worker._poses = []
        worker._detections = [
            {
                "box": [960, 540, 1440, 810],
                "confidence": 0.9,
                "label": "person",
            }
        ]
        worker._faces = []
        worker.ai_enabled = True
        worker.label = "Dahua"
        worker._capture_fps = 15.0
        worker.pose_enabled = False

        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        worker._draw_overlay(frame, (1080, 1920, 3))

        np.testing.assert_array_equal(frame[180, 320], np.array([0, 220, 70]))
        np.testing.assert_array_equal(frame[270, 480], np.array([0, 220, 70]))
        np.testing.assert_array_equal(frame[180, 316], np.array([0, 0, 0]))

    def test_hailo_shadow_box_uses_distinct_color_and_scales(self):
        worker = CameraWorker.__new__(CameraWorker)
        worker._poses = []
        worker._detections = []
        worker._hailo_shadow_poses = [
            {
                "box": [960, 540, 1440, 810],
                "confidence": 0.8,
                "keypoints": [[0.0, 0.0, 0.0] for _ in range(17)],
            }
        ]
        worker.hailo_shadow_keypoint_confidence = 0.25
        worker._faces = []
        worker.ai_enabled = True
        worker.label = "Dahua"
        worker._capture_fps = 15.0
        worker.pose_enabled = False

        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        worker._draw_overlay(frame, (1080, 1920, 3))

        np.testing.assert_array_equal(frame[180, 320], np.array([255, 0, 255]))
        np.testing.assert_array_equal(frame[270, 480], np.array([255, 0, 255]))

    def test_visible_keypoint_ratio_is_comparable_between_backends(self):
        pose = {
            "keypoints": [
                [0.0, 0.0, 0.9],
                [0.0, 0.0, 0.25],
                [0.0, 0.0, 0.1],
            ]
        }

        self.assertAlmostEqual(
            pose_visible_keypoint_ratio([pose], confidence=0.25),
            2 / 3,
        )
        self.assertEqual(pose_visible_keypoint_ratio([], confidence=0.25), 0.0)


if __name__ == "__main__":
    unittest.main()
