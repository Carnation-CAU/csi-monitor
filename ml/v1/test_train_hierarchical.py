import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from train_hierarchical import (
    ACTIVITY_BY_ID,
    collapse_label,
    hierarchical_prediction,
    inactivity_features,
    longest_true_run,
)


class HierarchicalTests(unittest.TestCase):
    def test_verified_activity_mapping(self):
        self.assertEqual(ACTIVITY_BY_ID["2"], "walk")
        self.assertEqual(ACTIVITY_BY_ID["7"], "fall")
        self.assertEqual(collapse_label("fall"), "fall_suspected")
        self.assertEqual(collapse_label("jump"), "other_motion")

    def test_longest_true_run(self):
        self.assertEqual(longest_true_run(np.array([False, True, True, False, True])), 2)

    def test_inactivity_accepts_variable_length_time_axis(self):
        amplitude = np.zeros((120, 52), dtype=float)
        timestamp = np.arange(120, dtype=float) * 10_000.0
        result = inactivity_features(amplitude, timestamp)
        self.assertTrue(np.isfinite(result["inactivity_score"]))
        self.assertGreaterEqual(result["inactivity_score"], 0.0)
        self.assertLessEqual(result["inactivity_score"], 1.0)

    def test_missing_inactivity_does_not_suppress_model_fall(self):
        prediction = hierarchical_prediction(
            np.array([0.8, 0.8]), np.array([0.1, 0.1]),
            np.array([0.2, 0.2]), probability_threshold=0.5,
            inactivity_threshold=0.7,
            inactivity_available=np.array([True, False]),
        )
        self.assertEqual(prediction.tolist(), ["other_motion", "fall_suspected"])


if __name__ == "__main__":
    unittest.main()
