from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from smarthome_vision.shadow_log import ShadowObservationLog


class ShadowObservationLogTest(unittest.TestCase):
    def test_rate_limits_and_never_adds_image_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.jsonl"
            log = ShadowObservationLog(path, interval_seconds=1.0, max_bytes=4096)

            self.assertTrue(log.maybe_write({"camera_id": "dahua", "tracks": []}, now=1.0))
            self.assertFalse(log.maybe_write({"camera_id": "dahua", "tracks": []}, now=1.5))
            self.assertTrue(log.maybe_write({"camera_id": "dahua", "tracks": []}, now=1.6, force=True))

            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["camera_id"], "dahua")
            self.assertNotIn("frame", records[0])

    def test_rotates_at_size_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.jsonl"
            log = ShadowObservationLog(path, interval_seconds=0.1, max_bytes=1024)

            for index in range(20):
                log.maybe_write(
                    {"index": index, "padding": "x" * 120},
                    now=index * 0.2,
                )

            self.assertTrue(path.exists())
            self.assertTrue(Path(str(path) + ".1").exists())
            self.assertLessEqual(path.stat().st_size, 1024)


if __name__ == "__main__":
    unittest.main()
