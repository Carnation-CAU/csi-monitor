import json
import tempfile
import unittest
from pathlib import Path

from csi_gateway.live_detection import (
    EventJournal,
    LiveActionDetector,
    LiveDetectionConfig,
)
from csi_gateway.radar import RadarSample


def radar_sample(*, moving: bool, jitter_ratio: float = 0.0) -> RadarSample:
    threshold = 0.1
    return RadarSample(
        sequence=1,
        timestamp="0",
        wander=0.2,
        someone_threshold=0.1,
        someone=True,
        jitter=jitter_ratio * threshold,
        move_threshold=threshold,
        moving=moving,
    )


class LiveActionDetectorTests(unittest.TestCase):
    def test_records_stabilized_moving_and_static_transitions(self):
        detector = LiveActionDetector(
            config=LiveDetectionConfig(
                window_seconds=1.0,
                min_samples=3,
                classification_interval_seconds=0.1,
                prediction_confirmations=1,
            )
        )

        events = []
        for observed_at in (0.0, 0.5, 1.0):
            events.extend(
                detector.update(
                    radar_sample(moving=True, jitter_ratio=1.2),
                    observed_at=observed_at,
                    detected_at=f"2026-08-16T00:00:0{int(observed_at)}Z",
                    presence_state="present",
                    presence_probability=1.0,
                )
            )
        self.assertEqual([event.label for event in events], ["moving"])

        events = []
        for observed_at in (2.0, 2.5, 3.0):
            events.extend(
                detector.update(
                    radar_sample(moving=False),
                    observed_at=observed_at,
                    detected_at=f"2026-08-16T00:00:0{int(observed_at)}Z",
                    presence_state="present",
                    presence_probability=1.0,
                )
            )
        self.assertEqual([event.label for event in events], ["static"])

    def test_fall_candidate_requires_impact_followed_by_no_recovery(self):
        detector = LiveActionDetector(
            config=LiveDetectionConfig(
                min_samples=99,
                fall_impact_ratio=2.5,
                fall_no_recovery_seconds=3.0,
                fall_max_moving_ratio=0.2,
            )
        )

        events = detector.update(
            radar_sample(moving=True, jitter_ratio=4.0),
            observed_at=0.0,
            detected_at="2026-08-16T00:00:00Z",
            presence_state="present",
            presence_probability=0.9,
        )
        for observed_at in (1.0, 2.0, 3.0):
            events.extend(
                detector.update(
                    radar_sample(moving=False),
                    observed_at=observed_at,
                    detected_at=f"2026-08-16T00:00:0{int(observed_at)}Z",
                    presence_state="present",
                    presence_probability=0.9,
                )
            )

        fall_events = [event for event in events if event.event_type == "fall_suspected"]
        self.assertEqual(len(fall_events), 1)
        self.assertEqual(fall_events[0].detected_at, "2026-08-16T00:00:00Z")
        self.assertEqual(fall_events[0].evidence["no_recovery_sec"], 3.0)

    def test_continued_movement_cancels_fall_candidate(self):
        detector = LiveActionDetector(
            config=LiveDetectionConfig(
                min_samples=99,
                fall_no_recovery_seconds=3.0,
            )
        )
        all_events = detector.update(
            radar_sample(moving=True, jitter_ratio=4.0),
            observed_at=0.0,
            detected_at="2026-08-16T00:00:00Z",
            presence_state="present",
            presence_probability=0.9,
        )
        for observed_at in (1.0, 2.0, 3.0):
            all_events.extend(
                detector.update(
                    radar_sample(moving=True, jitter_ratio=1.0),
                    observed_at=observed_at,
                    detected_at=f"2026-08-16T00:00:0{int(observed_at)}Z",
                    presence_state="present",
                    presence_probability=0.9,
                )
            )
        self.assertFalse(
            any(event.event_type == "fall_suspected" for event in all_events)
        )


class EventJournalTests(unittest.TestCase):
    def test_appends_detection_as_utf8_json_line(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = EventJournal(Path(temp_dir))
            path = journal.append(
                {
                    "event_type": "activity_detected",
                    "detected_at": "2026-08-16T12:00:00+09:00",
                    "label": "움직임",
                }
            )

            self.assertEqual(path.name, "2026-08-16.jsonl")
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(record["label"], "움직임")


if __name__ == "__main__":
    unittest.main()
