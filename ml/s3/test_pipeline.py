import unittest

import numpy as np
import torch

from ml.s3.dataset import S3Window, augment_window, validate_training_inventory
from ml.s3.features import extract_handcrafted_features, handcrafted_feature_names
from ml.s3.models import make_s3_model
from ml.s3.training import nested_group_folds


def window(room: str, session: str, is_fall: bool = False) -> S3Window:
    return S3Window(
        features=np.zeros((4, 100, 52), dtype=np.float32),
        is_fall=is_fall,
        session_id=session,
        room_id=room,
        person_id=f"person-{room}",
        position_id="center",
        channel=1,
        label="fall_forward" if is_fall else "walk",
        start_seconds=0.0,
        event_at_seconds=2.0 if is_fall else None,
    )


class S3PipelineTests(unittest.TestCase):
    def test_inventory_guard_rejects_tiny_or_unknown_dataset(self):
        blockers = validate_training_inventory(
            {
                "fallEventCount": 2,
                "nonFallSessionCount": 1,
                "rooms": [],
                "people": [],
                "channels": [1],
            }
        )
        self.assertTrue(any("fall events" in blocker for blocker in blockers))
        self.assertTrue(any("known rooms" in blocker for blocker in blockers))

    def test_nested_group_split_keeps_validation_and_test_out_of_train(self):
        rows = [window("a", "a"), window("b", "b"), window("c", "c")]
        folds = nested_group_folds(rows, "room_id")
        self.assertEqual(len(folds), 3)
        for train, validation, test, validation_group, test_group in folds:
            self.assertNotEqual(validation_group, test_group)
            self.assertTrue(all(rows[index].room_id not in {validation_group, test_group} for index in train))
            self.assertTrue(all(rows[index].room_id == validation_group for index in validation))
            self.assertTrue(all(rows[index].room_id == test_group for index in test))

    def test_augmentation_is_bounded_and_keeps_shape(self):
        values = np.ones((4, 100, 52), dtype=np.float32)
        augmented = augment_window(values, np.random.default_rng(7))
        self.assertEqual(augmented.shape, values.shape)
        self.assertTrue(np.isfinite(augmented).all())
        self.assertLess(float(np.max(np.abs(augmented))), 2.0)

    def test_handcrafted_feature_contract(self):
        vector = extract_handcrafted_features(np.zeros((4, 100, 52), dtype=np.float32))
        self.assertEqual(vector.shape, (len(handcrafted_feature_names()),))
        self.assertTrue(np.isfinite(vector).all())

    def test_temporal_models_accept_time_subcarrier_input(self):
        values = torch.zeros((2, 4, 100, 52))
        for name in ("tcn", "cnn_gru", "cnn2d"):
            with self.subTest(name=name):
                output = make_s3_model(name)(values)
                self.assertEqual(tuple(output.shape), (2, 2))


if __name__ == "__main__":
    unittest.main()
