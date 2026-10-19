from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np

from smarthome_vision.events import EventBus
from smarthome_vision.face_registry import FaceRegistry, FaceRegistryError
from smarthome_vision.pipeline import draw_face_label


def fake_registry(directory: Path) -> FaceRegistry:
    registry = FaceRegistry.__new__(FaceRegistry)
    registry.database_path = directory / "faces.json"
    registry.match_threshold = 0.45
    registry.detection_width = 640
    registry.min_face_size = 70
    registry.enrollment_min_samples_per_view = 3
    registry.enrollment_yaw_threshold = 0.12
    registry.enrollment_max_yaw = 0.65
    registry.enrollment_min_sharpness = 35.0
    registry._lock = threading.RLock()
    registry._people = []
    registry._detect = lambda frame: [np.zeros(15, dtype=np.float32)]
    return registry


class FaceRegistryTest(unittest.TestCase):
    def test_enroll_preserves_views_and_replaces_same_view(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = fake_registry(Path(temp))
            current = {"feature": np.array([1.0, 0.0], dtype=np.float32)}
            registry._feature = lambda frame, face: current["feature"]
            frames = [np.zeros((10, 10, 3), dtype=np.uint8) for _ in range(5)]

            registry.enroll("테스트", frames, "front")
            current["feature"] = np.array([0.8, 0.2], dtype=np.float32)
            registry.enroll("테스트", frames, "left")
            current["feature"] = np.array([0.7, 0.3], dtype=np.float32)
            result = registry.enroll("테스트", frames, "front")

            self.assertEqual(len(registry._people), 1)
            self.assertEqual(sorted(result["views"]), ["front", "left"])
            self.assertEqual(len(registry._people[0]["templates"]), 2)
            payload = json.loads(registry.database_path.read_text())
            self.assertEqual(payload["version"], 2)

    def test_identify_uses_best_template(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = fake_registry(Path(temp))
            registry._people = [
                {
                    "id": "person-a",
                    "name": "등록자",
                    "updated_at": "2026-09-10T00:00:00+00:00",
                    "templates": [
                        {"view": "front", "embedding": [1.0, 0.0], "updated_at": "x"},
                        {"view": "left", "embedding": [0.0, 1.0], "updated_at": "x"},
                    ],
                }
            ]
            registry._feature = lambda frame, face: np.array([0.0, 1.0], dtype=np.float32)

            result = registry.identify(np.zeros((100, 100, 3), dtype=np.uint8))

            self.assertTrue(result[0]["registered"])
            self.assertEqual(result[0]["name"], "등록자")
            self.assertEqual(result[0]["similarity"], 1.0)

    def test_multi_angle_enrollment_builds_three_templates_in_one_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = fake_registry(Path(temp))
            yaw_values = iter([0.0] * 4 + [-0.3] * 4 + [0.3] * 4)
            registry._face_yaw = lambda face: next(yaw_values)
            registry._face_sharpness = lambda frame, face: 100.0
            registry._feature = lambda frame, face: np.array(
                [1.0, 0.2], dtype=np.float32
            )
            frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(12)]

            result = registry.enroll_multi_angle("테스트", frames)

            self.assertEqual(result["mode"], "guided_multi_angle")
            self.assertEqual(result["samples"], {"front": 4, "left": 4, "right": 4})
            self.assertEqual(len(registry._people[0]["templates"]), 3)

    def test_loads_legacy_embedding_as_template(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            path = directory / "faces.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "people": [
                            {
                                "id": "old",
                                "name": "기존",
                                "updated_at": "2026-01-01T00:00:00+00:00",
                                "embedding": [1.0, 0.0],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            )
            registry = fake_registry(directory)

            registry._load()

            self.assertEqual(registry.list_people()[0]["views"], ["legacy"])

    def test_rejects_unknown_view(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = fake_registry(Path(temp))
            with self.assertRaises(FaceRegistryError):
                registry.enroll("테스트", [], "up")

    def test_ascii_face_label_bypasses_freetype_renderer(self):
        frame = np.zeros((80, 240, 3), dtype=np.uint8)
        face_font = Mock()

        draw_face_label(
            frame,
            "songwoo 0.67",
            (10, 45),
            (255, 200, 40),
            face_font,
        )

        face_font.putText.assert_not_called()
        self.assertGreater(np.count_nonzero(frame), 0)

    def test_non_ascii_face_label_uses_freetype_renderer(self):
        frame = np.zeros((80, 240, 3), dtype=np.uint8)
        face_font = Mock()

        draw_face_label(
            frame,
            "홍길동 0.67",
            (10, 45),
            (255, 200, 40),
            face_font,
        )

        face_font.putText.assert_called_once()

    def test_events_have_unique_ids_for_qos_deduplication(self):
        bus = EventBus({"enabled": False})

        first = bus.emit("cam3", "person_detected")
        second = bus.emit("cam3", "person_detected")

        self.assertEqual(first["schema_version"], "1.1")
        self.assertNotEqual(first["event_id"], second["event_id"])


if __name__ == "__main__":
    unittest.main()
