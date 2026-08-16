import unittest

from csi_gateway.activity import ActivityPrediction
from csi_gateway.activity_events import ActivityEventAggregator
from csi_gateway.fall_alert import build_detected_fall_event
from csi_gateway.live_detection import DetectionEvent


def prediction(sequence: int, fall_score: float) -> ActivityPrediction:
    other_score = 1.0 - fall_score
    return ActivityPrediction(
        label="fall_suspected" if fall_score >= other_score else "other_motion",
        scores={
            "fall_suspected": fall_score,
            "walking": 0.0,
            "other_motion": other_score,
        },
        confidence=max(fall_score, other_score),
        first_sequence=sequence,
        last_sequence=sequence + 949,
        window_finished_at="2026-08-16T00:00:00Z",
        model_version="model-v1",
        preprocessing_version="test-v1",
    )


def radar_fall() -> DetectionEvent:
    return DetectionEvent(
        event_id="radar-fall-1",
        event_type="fall_suspected",
        label="fall_like",
        detected_at="2026-08-16T00:00:00Z",
        confidence=0.9,
        source="impact_then_no_recovery_rule",
        evidence={
            "impact_ratio": 4.0,
            "post_impact_moving_ratio": 0.0,
            "no_recovery_sec": 8.0,
            "presence_state": "present",
            "presence_probability": 0.9,
            "sample_count": 8,
        },
    )


class ActivityEventAggregatorTests(unittest.TestCase):
    def test_overlapping_windows_become_one_candidate(self):
        aggregator = ActivityEventAggregator(
            fall_score_threshold=0.8,
            episode_gap_seconds=1.0,
        )
        for index, score in enumerate((0.81, 0.91, 0.87)):
            events = aggregator.observe(
                prediction(index * 20, score),
                observed_at=index * 0.2,
                detected_at="2026-08-16T00:00:00Z",
            )
            self.assertEqual(events, [])

        events = aggregator.expire(1.5)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "ml_fall_candidate")
        self.assertEqual(events[0].evidence["ml_window_count"], 3)
        self.assertAlmostEqual(events[0].evidence["ml_fall_score_max"], 0.91)

    def test_radar_event_and_ml_episode_create_one_fused_fall(self):
        aggregator = ActivityEventAggregator(fall_score_threshold=0.8)
        aggregator.observe(
            prediction(100, 0.91),
            observed_at=1.0,
            detected_at="2026-08-16T00:00:01Z",
        )

        fused = aggregator.fuse_radar_fall(radar_fall(), observed_at=9.0)
        duplicate = aggregator.fuse_radar_fall(radar_fall(), observed_at=9.1)

        self.assertIsNotNone(fused)
        self.assertEqual(fused.source, "ml_radar_fusion")
        self.assertEqual(fused.evidence["fusion_rule"], "ml_and_radar_v1")
        self.assertEqual(fused.evidence["ml_window_count"], 1)
        self.assertIsNone(duplicate)

        app_event = build_detected_fall_event(
            window_id=fused.event_id,
            detected_at=fused.detected_at,
            room_id="living-room",
            risk_score=fused.confidence,
            motion_confidence=fused.confidence,
            presence_state=str(fused.evidence["presence_state"]),
            presence_probability=float(fused.evidence["presence_probability"]),
            no_recovery_sec=float(fused.evidence["no_recovery_sec"]),
        )
        self.assertEqual(app_event["event_type"], "fall_suspected")
        self.assertEqual(app_event["window_id"], "radar-fall-1")

    def test_radar_without_ml_is_record_only_candidate(self):
        aggregator = ActivityEventAggregator()

        self.assertIsNone(
            aggregator.fuse_radar_fall(radar_fall(), observed_at=9.0)
        )
        candidate = aggregator.radar_candidate(radar_fall())
        self.assertEqual(candidate.event_type, "radar_fall_candidate")


if __name__ == "__main__":
    unittest.main()
