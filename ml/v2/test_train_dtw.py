import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from train_dtw import (  # noqa: E402
    build_templates,
    dtw_distance,
    motion_waveform,
    nearest_template_predictions,
)


class DtwExperimentTests(unittest.TestCase):
    def test_identical_series_have_zero_distance(self):
        values = np.asarray([0.0, 1.0, 2.0, 1.0])
        self.assertAlmostEqual(dtw_distance(values, values, window=2), 0.0)

    def test_dtw_aligns_a_delayed_peak(self):
        first = np.asarray([0.0, 0.0, 1.0, 1.0, 0.0])
        delayed = np.asarray([0.0, 0.0, 0.0, 1.0, 1.0])
        different = np.asarray([1.0, 1.0, 0.0, 0.0, 0.0])
        self.assertLess(
            dtw_distance(first, delayed, window=2),
            dtw_distance(first, different, window=2),
        )

    def test_motion_waveform_has_fixed_normalized_shape(self):
        rng = np.random.default_rng(42)
        waveform = motion_waveform(rng.normal(size=(950, 52)))
        self.assertEqual(waveform.shape, (64,))
        self.assertAlmostEqual(float(waveform.mean()), 0.0, places=6)
        self.assertAlmostEqual(float(waveform.std()), 1.0, places=6)

    def test_templates_use_only_selected_training_rows(self):
        waveforms = np.asarray([[0.0, 0.0], [2.0, 2.0], [100.0, 100.0]])
        labels = np.asarray(["walk", "walk", "walk"])
        train = np.asarray([True, True, False])
        template = build_templates(waveforms, labels, train, ["walk"])["walk"]
        np.testing.assert_allclose(template, np.zeros(2))

    def test_nearest_template_predictions_collapse_labels(self):
        distances = np.asarray([[0.1, 0.9], [0.8, 0.2]])
        result = nearest_template_predictions(distances, ["fall", "walk"])
        self.assertEqual(result.tolist(), ["fall_suspected", "walking"])


if __name__ == "__main__":
    unittest.main()
