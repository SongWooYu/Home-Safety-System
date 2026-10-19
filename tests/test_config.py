from __future__ import annotations

import unittest
from pathlib import Path

from smarthome_vision.config import load_config


ROOT = Path(__file__).resolve().parents[1]


class RuntimeConfigTest(unittest.TestCase):
    def test_hailo_edgefall_paths_resolve_without_legacy_inference_section(self):
        config = load_config(ROOT / "config" / "cameras.yaml")
        fall = config["fall_detection"]

        self.assertNotIn("inference", config)
        self.assertEqual(fall["backend"], "hailo_edgefall")
        self.assertTrue(Path(fall["model"]).is_absolute())
        self.assertTrue(Path(fall["edgefall"]["library"]).is_absolute())
        self.assertTrue(fall["edgefall"]["publish_mqtt"])


if __name__ == "__main__":
    unittest.main()
