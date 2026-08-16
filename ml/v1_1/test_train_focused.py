import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from train_focused import (  # noqa: E402
    CORE_ACTIONS,
    EXCLUDED_ACTIONS,
    core_mask,
    feature_columns,
    summarize_ood,
)


class FocusedExperimentTests(unittest.TestCase):
    def test_action_sets_do_not_overlap(self):
        self.assertFalse(CORE_ACTIONS & EXCLUDED_ACTIONS)
        self.assertEqual(EXCLUDED_ACTIONS, {"jump", "squat"})

    def test_core_mask_excludes_only_jump_and_squat(self):
        labels = np.asarray(["fall", "walk", "jump", "squat", "turn", "arm_wave", "run"])
        self.assertEqual(
            core_mask(labels).tolist(),
            [True, True, False, False, True, True, True],
        )

    def test_feature_columns_exclude_metadata_and_inactivity(self):
        row = {
            "scenario": "1", "label": "walking", "mean": "1.0",
            "inactivity_score": "0.5", "raw_packet_count": "950",
        }
        self.assertEqual(feature_columns(row), ["mean"])

    def test_ood_summary_counts_fall_false_alarm(self):
        rows = [
            {"protocol": "p", "original_label": "jump", "prediction": "fall_suspected"},
            {"protocol": "p", "original_label": "jump", "prediction": "other_motion"},
            {"protocol": "p", "original_label": "squat", "prediction": "other_motion"},
        ]
        combined = next(
            row for row in summarize_ood(rows) if row["original_label"] == "combined"
        )
        self.assertEqual(combined["samples"], 3)
        self.assertAlmostEqual(combined["fall_suspected_rate"], 1 / 3)


if __name__ == "__main__":
    unittest.main()
