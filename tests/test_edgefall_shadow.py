from __future__ import annotations

import os
import time
import unittest

from smarthome_vision.edgefall_shadow import EdgeFallShadow


LIBRARY = os.environ.get(
    "EDGEFALL_SHADOW_LIBRARY",
    "runtime/native/libedgefall_shadow.so",
)


@unittest.skipUnless(os.path.isfile(LIBRARY), "EdgeFall shadow library is not built")
class EdgeFallShadowTest(unittest.TestCase):
    def test_accepts_hailo_pose_contract_and_keeps_mqtt_outside_library(self):
        pose = {
            "confidence": 0.9,
            "box": [200.0, 80.0, 440.0, 600.0],
            "keypoints": [[320.0, 100.0 + index * 20.0, 0.9] for index in range(17)],
        }
        with EdgeFallShadow(LIBRARY) as shadow:
            tracks = shadow.update([pose], 640, 640, time.monotonic())

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["track_id"], 1)
        self.assertEqual(tracks[0]["state"], "normal")
        self.assertTrue(tracks[0]["visible"])
        self.assertIn("temporal_probability", tracks[0])


if __name__ == "__main__":
    unittest.main()
