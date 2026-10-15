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
    @staticmethod
    def _pose(
        *,
        hip_y: float,
        horizontal: bool,
        box: list[float] | None = None,
    ) -> dict[str, object]:
        keypoints = [[320.0, hip_y, 0.9] for _ in range(17)]
        if horizontal:
            keypoints[5] = [220.0, hip_y - 8.0, 0.9]
            keypoints[6] = [240.0, hip_y - 8.0, 0.9]
            keypoints[11] = [400.0, hip_y, 0.9]
            keypoints[12] = [420.0, hip_y, 0.9]
        else:
            keypoints[5] = [300.0, hip_y - 160.0, 0.9]
            keypoints[6] = [340.0, hip_y - 160.0, 0.9]
            keypoints[11] = [300.0, hip_y, 0.9]
            keypoints[12] = [340.0, hip_y, 0.9]
        return {
            "confidence": 0.9,
            "box": box or [200.0, 80.0, 440.0, 600.0],
            "keypoints": keypoints,
        }

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
        self.assertGreaterEqual(tracks[0]["hip_y"], 0.0)
        self.assertLessEqual(tracks[0]["hip_y"], 1.0)

    def test_profile_identifies_foreshortened_persistence_policy(self):
        with EdgeFallShadow(LIBRARY) as shadow:
            self.assertEqual(
                shadow.profile,
                "edgefallkit-hailo8-yolov8s-pose-v1+foreshortened-persistence-v4",
            )

    def test_static_lying_posture_cannot_originate_fall(self):
        pose = self._pose(
            hip_y=390.0,
            horizontal=True,
            box=[70.0, 250.0, 570.0, 450.0],
        )
        states: list[str] = []
        events: list[bool] = []
        with EdgeFallShadow(LIBRARY) as shadow:
            for frame in range(90):
                tracks = shadow.update([pose], 640, 640, frame / 15.0)
                states.append(tracks[0]["state"])
                events.append(tracks[0]["fall_event"])

        self.assertEqual(set(states), {"normal"})
        self.assertFalse(any(events))

    def test_fast_bend_without_horizontal_box_cannot_confirm_fall(self):
        states: list[str] = []
        events: list[bool] = []
        with EdgeFallShadow(LIBRARY) as shadow:
            for frame in range(20):
                tracks = shadow.update(
                    [self._pose(hip_y=330.0, horizontal=False)],
                    640,
                    640,
                    frame / 15.0,
                )
                states.append(tracks[0]["state"])
                events.append(tracks[0]["fall_event"])
            for frame in range(20, 70):
                tracks = shadow.update(
                    [
                        self._pose(
                            hip_y=430.0,
                            horizontal=True,
                            box=[220.0, 120.0, 420.0, 600.0],
                        )
                    ],
                    640,
                    640,
                    frame / 15.0,
                )
                states.append(tracks[0]["state"])
                events.append(tracks[0]["fall_event"])

        self.assertNotIn("fallen", states)
        self.assertFalse(any(events))

    def test_strong_rapid_horizontal_drop_confirms_before_track_loss(self):
        states: list[str] = []
        events: list[bool] = []
        with EdgeFallShadow(LIBRARY) as shadow:
            for frame in range(20):
                tracks = shadow.update(
                    [self._pose(hip_y=330.0, horizontal=False)],
                    640,
                    640,
                    frame / 15.0,
                )
                states.append(tracks[0]["state"])
                events.append(tracks[0]["fall_event"])

            tracks = shadow.update(
                [
                    self._pose(
                        hip_y=430.0,
                        horizontal=True,
                        box=[70.0, 250.0, 570.0, 450.0],
                    )
                ],
                640,
                640,
                20 / 15.0,
            )
            states.append(tracks[0]["state"])
            events.append(tracks[0]["fall_event"])

        self.assertEqual(states[-1], "fallen")
        self.assertTrue(events[-1])

    def test_rapid_drop_then_horizontal_posture_confirms_in_same_window(self):
        states: list[str] = []
        events: list[bool] = []
        with EdgeFallShadow(LIBRARY) as shadow:
            for frame in range(20):
                tracks = shadow.update(
                    [self._pose(hip_y=330.0, horizontal=False)],
                    640,
                    640,
                    frame / 15.0,
                )
                states.append(tracks[0]["state"])
                events.append(tracks[0]["fall_event"])

            # The impact and final lying box normally peak on adjacent Hailo
            # samples, not on one exact frame.  Arm on the rapid drop first.
            tracks = shadow.update(
                [
                    self._pose(
                        hip_y=360.0,
                        horizontal=True,
                        box=[160.0, 170.0, 480.0, 570.0],
                    )
                ],
                640,
                640,
                20 / 15.0,
            )
            states.append(tracks[0]["state"])
            events.append(tracks[0]["fall_event"])

            # On the next sample, speed can already be low while the person
            # box has become fully horizontal.  The same candidate confirms.
            tracks = shadow.update(
                [
                    self._pose(
                        hip_y=365.0,
                        horizontal=True,
                        box=[70.0, 250.0, 570.0, 450.0],
                    )
                ],
                640,
                640,
                21 / 15.0,
            )
            states.append(tracks[0]["state"])
            events.append(tracks[0]["fall_event"])

        self.assertEqual(states[-2:], ["suspected", "fallen"])
        self.assertTrue(events[-1])

    def test_foreshortened_fall_confirms_after_horizontal_persistence(self):
        states: list[str] = []
        events: list[bool] = []
        with EdgeFallShadow(LIBRARY) as shadow:
            for frame in range(20):
                tracks = shadow.update(
                    [self._pose(hip_y=330.0, horizontal=False)],
                    640,
                    640,
                    frame / 15.0,
                )
                states.append(tracks[0]["state"])
                events.append(tracks[0]["fall_event"])

            # A side/back fall toward the camera can rotate the torso quickly
            # without producing a wide 2-D box or a large image-Y hip drop.
            for frame in range(20, 36):
                tracks = shadow.update(
                    [
                        self._pose(
                            hip_y=350.0,
                            horizontal=True,
                            box=[100.0, 200.0, 540.0, 600.0],
                        )
                    ],
                    640,
                    640,
                    frame / 15.0,
                )
                states.append(tracks[0]["state"])
                events.append(tracks[0]["fall_event"])

        self.assertEqual(states[-1], "fallen")
        self.assertTrue(any(events))

    def test_quick_foreshortened_bend_recovers_before_confirmation(self):
        states: list[str] = []
        events: list[bool] = []
        with EdgeFallShadow(LIBRARY) as shadow:
            for frame in range(20):
                tracks = shadow.update(
                    [self._pose(hip_y=330.0, horizontal=False)],
                    640,
                    640,
                    frame / 15.0,
                )
                states.append(tracks[0]["state"])
                events.append(tracks[0]["fall_event"])

            for frame in range(20, 26):
                tracks = shadow.update(
                    [
                        self._pose(
                            hip_y=350.0,
                            horizontal=True,
                            box=[100.0, 200.0, 540.0, 600.0],
                        )
                    ],
                    640,
                    640,
                    frame / 15.0,
                )
                states.append(tracks[0]["state"])
                events.append(tracks[0]["fall_event"])

            for frame in range(26, 46):
                tracks = shadow.update(
                    [self._pose(hip_y=330.0, horizontal=False)],
                    640,
                    640,
                    frame / 15.0,
                )
                states.append(tracks[0]["state"])
                events.append(tracks[0]["fall_event"])

        self.assertNotIn("fallen", states)
        self.assertFalse(any(events))

    def test_slow_deliberate_lie_down_stays_normal(self):
        states: list[str] = []
        events: list[bool] = []
        with EdgeFallShadow(LIBRARY) as shadow:
            for frame in range(20):
                tracks = shadow.update(
                    [self._pose(hip_y=330.0, horizontal=False)],
                    640,
                    640,
                    frame / 15.0,
                )
                states.append(tracks[0]["state"])
                events.append(tracks[0]["fall_event"])
            for offset in range(1, 46):
                hip_y = 330.0 + (100.0 * offset / 45.0)
                tracks = shadow.update(
                    [
                        self._pose(
                            hip_y=hip_y,
                            horizontal=offset >= 40,
                            box=(
                                [70.0, 250.0, 570.0, 450.0]
                                if offset >= 40
                                else [200.0, 80.0, 440.0, 600.0]
                            ),
                        )
                    ],
                    640,
                    640,
                    (20 + offset) / 15.0,
                )
                states.append(tracks[0]["state"])
                events.append(tracks[0]["fall_event"])

        self.assertEqual(set(states), {"normal"})
        self.assertFalse(any(events))


if __name__ == "__main__":
    unittest.main()
