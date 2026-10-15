from __future__ import annotations

import unittest

import numpy as np

from smarthome_vision.pipeline import CameraWorker


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


if __name__ == "__main__":
    unittest.main()
