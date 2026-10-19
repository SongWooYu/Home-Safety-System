from pathlib import Path
import unittest

import cv2
import numpy as np

from smarthome_vision.pipeline import draw_face_label
from smarthome_vision.presentation import analysis_readiness
from smarthome_vision.sources.picamera import select_full_fov_mode


class PresentationTest(unittest.TestCase):
    def status(self, **kwargs):
        return {"pose_enabled": True, "online": True, "edgefall_enabled": True,
                "person_count": 0, "edgefall_tracks": [], **kwargs}

    def test_no_person_is_waiting_not_zero_risk(self):
        state = analysis_readiness(self.status())
        self.assertEqual(state["code"], "waiting")
        self.assertIsNone(state["motion_score"])

    def test_person_without_valid_pose_is_not_reported_as_normal(self):
        state = analysis_readiness(self.status(person_count=1))
        self.assertEqual(state["code"], "pose_needed")
        track = {"track_id": 2, "visible": True, "valid": False,
                 "age_frames": 100, "temporal_probability": .95}
        state = analysis_readiness(self.status(person_count=1, edgefall_tracks=[track], edgefall_best_track_id=2))
        self.assertEqual(state["code"], "pose_needed")
        self.assertIsNone(state["motion_score"])

    def test_real_zero_score_is_preserved_for_valid_track(self):
        track = {"track_id": 2, "visible": True, "valid": True,
                 "age_frames": 100, "temporal_probability": 0.0}
        state = analysis_readiness(self.status(person_count=1, edgefall_tracks=[track], edgefall_best_track_id=2))
        self.assertEqual(state["code"], "analyzing")
        self.assertEqual(state["motion_score"], 0.0)
        self.assertEqual(analysis_readiness(self.status(online=False))["code"], "offline")

    def test_stale_track_score_is_not_displayed(self):
        track = {"track_id": 2, "visible": False, "valid": True,
                 "age_frames": 100, "temporal_probability": .98}
        state = analysis_readiness(self.status(edgefall_tracks=[track], edgefall_best_track_id=2))
        self.assertEqual(state["code"], "waiting")
        self.assertIsNone(state["motion_score"])

    def test_motion_only_candidate_is_not_presented_as_model_confirmation(self):
        track = {"track_id": 2, "visible": True, "valid": True,
                 "age_frames": 100, "temporal_probability": .02,
                 "temporal_positive": False, "geometry_candidate": True,
                 "decision_reason": "model_not_confirmed"}
        state = analysis_readiness(self.status(edgefall_tracks=[track], edgefall_best_track_id=2))
        self.assertEqual(state["decision_label"], "동작 후보 · 모델 미동의")
        self.assertFalse(state["temporal_positive"])
        self.assertTrue(state["geometry_candidate"])

    def test_combined_confirmation_is_explicit(self):
        track = {"track_id": 2, "visible": True, "valid": True,
                 "age_frames": 100, "temporal_probability": .95,
                 "temporal_positive": True, "geometry_candidate": True,
                 "decision_reason": "temporal_and_geometry"}
        state = analysis_readiness(self.status(edgefall_tracks=[track], edgefall_best_track_id=2))
        self.assertEqual(state["decision_label"], "모델·동작 조건 모두 충족")
        self.assertTrue(state["temporal_positive"])

    def test_sensor_mode_prefers_full_fov_without_full_resolution_cost(self):
        modes = [
            {"size": (1536, 864), "crop_limits": (768, 432, 3072, 1728), "fps": 120},
            {"size": (4608, 2592), "crop_limits": (0, 0, 4608, 2592), "fps": 14},
            {"size": (2304, 1296), "crop_limits": (0, 0, 4608, 2592), "fps": 56},
        ]
        self.assertEqual(select_full_fov_mode(modes, 960, 540, 15)["size"], (2304, 1296))

    @unittest.skipUnless(Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf").is_file() and hasattr(cv2, "freetype"), "requires fonts-nanum and OpenCV FreeType")
    def test_korean_names_render_as_distinct_glyphs_instead_of_tofu(self):
        font = cv2.freetype.createFreeType2()
        font.loadFontData(fontFileName="/usr/share/fonts/truetype/nanum/NanumGothic.ttf", idx=0)
        first = np.zeros((80, 200, 3), np.uint8)
        second = first.copy()
        draw_face_label(first, "홍", (10, 45), (255, 255, 255), font)
        draw_face_label(second, "김", (10, 45), (255, 255, 255), font)
        self.assertGreater(np.count_nonzero(first), 50)
        self.assertFalse(np.array_equal(first, second))
        # Labels near the bottom must remain inside their background rectangle.
        glyph_rows = np.where(np.any(first, axis=(1, 2)))[0]
        self.assertGreaterEqual(glyph_rows.min(), 45 - 24)
        self.assertLessEqual(glyph_rows.max(), 45 + 5)


if __name__ == "__main__":
    unittest.main()
