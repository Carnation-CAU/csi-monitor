import tempfile
import unittest
from pathlib import Path

from ml.s3.evaluation import (
    ScoredEvent,
    TimedEvent,
    choose_recall_threshold,
    evaluate_events,
    leave_one_group_out,
    pr_roc_curve,
    save_experiment_record,
)


class S3EvaluationTests(unittest.TestCase):
    def test_pr_roc_curve_includes_false_positive_rate(self):
        rows = pr_roc_curve([True, False], [0.9, 0.2])
        perfect = next(row for row in rows if row["threshold"] == 0.9)
        self.assertEqual(perfect["fall_recall"], 1.0)
        self.assertEqual(perfect["fall_precision"], 1.0)
        self.assertEqual(perfect["false_positive_rate"], 0.0)

    def test_event_matching_counts_one_detection_per_physical_fall(self):
        actual = [TimedEvent("fall-1", "s1", 10.0)]
        predicted = [
            ScoredEvent("p1", "s1", 10.5, 0.9),
            ScoredEvent("p2", "s1", 11.0, 0.8),
        ]
        metrics, matches = evaluate_events(actual, predicted)
        self.assertEqual(metrics.true_positive_count, 1)
        self.assertEqual(metrics.false_positive_count, 1)
        self.assertEqual(matches[0]["latencySeconds"], 0.5)

    def test_threshold_selection_prioritizes_recall_then_precision(self):
        selected = choose_recall_threshold(
            [True, True, False, False], [0.9, 0.4, 0.5, 0.1], target_recall=1.0
        )
        self.assertEqual(selected["threshold"], 0.4)
        self.assertEqual(selected["fall_recall"], 1.0)

    def test_group_split_never_leaks_held_out_room(self):
        rows = [{"room_id": "a"}, {"room_id": "a"}, {"room_id": "b"}]
        folds = leave_one_group_out(rows, "room_id")
        train, test, group = folds[0]
        self.assertTrue(all(rows[index]["room_id"] != group for index in train))
        self.assertTrue(all(rows[index]["room_id"] == group for index in test))

    def test_experiment_json_is_written(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = save_experiment_record(
                Path(temp_dir) / "result.json",
                experiment_id="x",
                dataset_version="s3-v1",
                configuration={"window": 5},
                metrics={"fall_recall": 1.0},
            )
            self.assertIn('"fall_recall": 1.0', path.read_text())


if __name__ == "__main__":
    unittest.main()
