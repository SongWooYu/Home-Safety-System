import unittest

from smarthome_vision.fall_detection import FallTracker


def make_pose(box, horizontal=False, torso_visible=True):
    points = [[70.0, 40.0, 0.9] for _ in range(17)]
    if horizontal:
        points[5] = [70.0, 120.0, 0.9]
        points[6] = [75.0, 130.0, 0.9]
        points[11] = [150.0, 125.0, 0.9]
        points[12] = [155.0, 135.0, 0.9]
        points[15] = [210.0, 130.0, 0.9]
        points[16] = [215.0, 140.0, 0.9]
    else:
        points[5] = [65.0, 55.0, 0.9]
        points[6] = [85.0, 55.0, 0.9]
        points[11] = [68.0, 115.0, 0.9]
        points[12] = [82.0, 115.0, 0.9]
        points[15] = [68.0, 205.0, 0.9]
        points[16] = [82.0, 205.0, 0.9]
    if not torso_visible:
        for index in (5, 6, 11, 12):
            points[index][2] = 0.1
    return {"confidence": 0.9, "box": box, "keypoints": points}


class FallTrackerTest(unittest.TestCase):
    def test_upright_to_lying_transition_confirms_and_recovers(self):
        tracker = FallTracker(confirm_seconds=1.2, recovery_seconds=2.0)

        normal = tracker.update(
            [make_pose([45, 20, 105, 220])],
            (240, 320, 3),
            0.0,
        )
        suspected = tracker.update(
            [make_pose([20, 100, 240, 180], horizontal=True)],
            (240, 320, 3),
            0.5,
        )
        confirmed = tracker.update(
            [make_pose([20, 100, 240, 180], horizontal=True)],
            (240, 320, 3),
            1.8,
        )
        tracker.update([make_pose([45, 20, 105, 220])], (240, 320, 3), 2.0)
        recovered = tracker.update(
            [make_pose([45, 20, 105, 220])],
            (240, 320, 3),
            4.1,
        )

        self.assertEqual((normal.pose_state, normal.fall_state), ("standing", "normal"))
        self.assertEqual(suspected.event_type, "fall_suspected")
        self.assertEqual(confirmed.event_type, "fall_confirmed")
        self.assertEqual(recovered.event_type, "fall_cleared")

    def test_wide_occluded_seated_person_is_not_a_fall(self):
        tracker = FallTracker()
        result = tracker.update(
            [make_pose([0, 0, 180, 100], horizontal=False, torso_visible=False)],
            (720, 1280, 3),
            0.0,
        )

        self.assertEqual(result.pose_state, "sitting")
        self.assertEqual(result.fall_state, "normal")
        self.assertIsNone(result.event_type)


if __name__ == "__main__":
    unittest.main()
