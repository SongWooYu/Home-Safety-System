from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from smarthome_vision.gru_numpy import NumpyFallEnsemble


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "fall_gru" / "b76_sqrt_ensemble" / "numpy"


class GruBatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ensemble = NumpyFallEnsemble(MODEL)

    def test_batch_matches_single_track_predictions(self):
        rng = np.random.default_rng(20261015)
        sequences = rng.normal(
            0.0,
            0.5,
            size=(6, 20, 76),
        ).astype(np.float32)

        expected = [
            self.ensemble.predict(sequence)
            for sequence in sequences
        ]
        actual = self.ensemble.predict_batch(sequences)

        self.assertEqual(len(actual), len(expected))
        for expected_item, actual_item in zip(expected, actual):
            self.assertEqual(
                actual_item["class_name"],
                expected_item["class_name"],
            )
            for class_name in self.ensemble.classes:
                self.assertAlmostEqual(
                    actual_item["probabilities"][class_name],
                    expected_item["probabilities"][class_name],
                    places=5,
                )


if __name__ == "__main__":
    unittest.main()
