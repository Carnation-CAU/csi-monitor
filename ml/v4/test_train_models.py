import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from train_models import (  # noqa: E402
    FEATURE_VARIANTS,
    MODEL_NAMES,
    TRAINING_VARIANTS,
    combine_features,
    make_model,
    model_parameters,
    summarize_ood,
)


class V4ModelTests(unittest.TestCase):
    def test_expected_experiment_matrix(self):
        self.assertEqual(len(MODEL_NAMES), 3)
        self.assertEqual(len(FEATURE_VARIANTS), 2)
        self.assertEqual(len(TRAINING_VARIANTS), 2)
        self.assertEqual(len(MODEL_NAMES) * len(FEATURE_VARIANTS) * len(TRAINING_VARIANTS), 12)

    def test_all_model_factories_fit_small_multiclass_data(self):
        rng = np.random.default_rng(42)
        x = rng.normal(size=(60, 5))
        y = np.asarray(["fall", "walk", "turn"] * 20)
        for name in MODEL_NAMES:
            prediction = make_model(name).fit(x, y).predict(x[:3])
            self.assertEqual(len(prediction), 3, name)

    def test_combine_features(self):
        stats = np.asarray([[1.0, 2.0], [3.0, 4.0]])
        distances = np.asarray([[0.1], [0.2]])
        indices = np.asarray([0, 1])
        np.testing.assert_allclose(
            combine_features(stats, distances, indices, "stats_only"), stats,
        )
        np.testing.assert_allclose(
            combine_features(stats, distances, indices, "stats_plus_dtw"),
            np.asarray([[1.0, 2.0, 0.1], [3.0, 4.0, 0.2]]),
        )

    def test_model_parameters_are_recorded(self):
        self.assertEqual(set(model_parameters()), set(MODEL_NAMES))

    def test_ood_summary_counts_combined_false_alarms(self):
        rows = []
        for model in MODEL_NAMES:
            for feature in FEATURE_VARIANTS:
                rows.extend([
                    {"protocol": "p", "model": model, "feature_variant": feature,
                     "original_label": "jump", "prediction": "fall_suspected"},
                    {"protocol": "p", "model": model, "feature_variant": feature,
                     "original_label": "squat", "prediction": "other_motion"},
                ])
        summary = summarize_ood(rows)
        combined = [row for row in summary if row["original_label"] == "combined"]
        self.assertEqual(len(combined), len(MODEL_NAMES) * len(FEATURE_VARIANTS))
        self.assertTrue(all(row["fall_suspected_rate"] == 0.5 for row in combined))


if __name__ == "__main__":
    unittest.main()
