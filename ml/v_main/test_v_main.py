from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from csi_gateway.activity import ActivityWindow
from ml.runtime import TorchCnnActivityModel


HERE = Path(__file__).resolve().parent
MODEL = HERE / "model.pt"
MODEL_VERSION = "v5.1-efficientnet-b0-espfi-cv-fold1-20260816"


@unittest.skipUnless(MODEL.exists(), "ml/v_main/model.pt is a local, Git-ignored artifact")
class MainModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = TorchCnnActivityModel(MODEL, device="cpu")

    def test_metadata_and_prediction_contract(self):
        self.assertEqual(self.backend.labels, ("fall", "walking", "other_motion"))
        self.assertEqual(self.backend.window_frames, 950)
        self.assertEqual(self.backend.model_version, MODEL_VERSION)
        window = ActivityWindow(np.zeros((950, 52), dtype=np.float32), 1, 950, "2026-08-16T00:00:00Z")
        prediction = self.backend.predict(window)
        self.assertIn(prediction.label, {"fall_suspected", "walking", "other_motion"})
        self.assertEqual(set(prediction.scores), {"fall_suspected", "walking", "other_motion"})
        self.assertAlmostEqual(sum(prediction.scores.values()), 1.0, places=5)
        self.assertEqual(prediction.model_version, MODEL_VERSION)
        self.assertEqual(prediction.preprocessing_version, "amplitude-zscore-v1")


if __name__ == "__main__":
    unittest.main()
