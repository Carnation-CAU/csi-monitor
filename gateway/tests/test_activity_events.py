import unittest
from dataclasses import replace

from csi_gateway.activity import ActivityPrediction
from csi_gateway.activity_events import ActivityEventAggregator
from csi_gateway.csi_pipeline import SignalEvidence
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


def radar_fall(
    *,
    confidence: float = 0.9,
    impact_ratio: float = 4.0,
) -> DetectionEvent:
    return DetectionEvent(
        event_id="radar-fall-1",
        event_type="fall_suspected",
        label="fall_like",
        detected_at="2026-08-16T00:00:00Z",
        confidence=confidence,
        source="impact_then_no_recovery_rule",
        evidence={
            "impact_ratio": impact_ratio,
            "post_impact_moving_ratio": 0.0,
            "no_recovery_sec": 8.0,
            "presence_state": "present",
            "presence_probability": 0.9,
            "sample_count": 8,
        },
    )


def signal_evidence(
    observed_at: float,
    score: float,
    quality: float = 1.0,
    proposal_id: str = "proposal-1",
    baseline_age_seconds: float = 10.0,
    proposal_started_at: float | None = None,
) -> SignalEvidence:
    return SignalEvidence(
        state="HIGH_ENERGY_EVENT" if score else "IDLE",
        motion_energy=score,
        phase_energy=score,
        motion_score=score,
        impact_score=score,
        post_event_score=score,
        signal_quality_score=quality,
        baseline_ready=True,
        baseline_adapted=False,
        channel_changed=False,
        observed_at=observed_at,
        proposal_id=proposal_id if score else None,
        proposal_started_at=(
            observed_at if proposal_started_at is None else proposal_started_at
        )
        if score
        else None,
        proposal_active=bool(score),
        baseline_age_seconds=baseline_age_seconds,
    )


class ActivityEventAggregatorTests(unittest.TestCase):
    def test_startup_proposal_tail_stays_quarantined_after_baseline_stabilizes(self):
        aggregator = ActivityEventAggregator(episode_gap_seconds=1.0)
        aggregator.observe_signal(
            signal_evidence(
                4.0,
                1.0,
                baseline_age_seconds=4.0,
                proposal_started_at=0.0,
            ),
            observed_at=4.0,
        )
        aggregator.observe(
            prediction(100, 0.95),
            observed_at=4.1,
            detected_at="2026-08-16T00:00:04Z",
        )

        events = aggregator.expire(5.2)

        self.assertEqual(
            [event.event_type for event in events],
            ["ml_fall_candidate"],
        )

    def test_radar_motion_is_proposal_not_a_required_fall_gate(self):
        aggregator = ActivityEventAggregator(episode_gap_seconds=1.0)
        aggregator.observe_radar_motion(moving=True, observed_at=0.0)
        aggregator.observe_radar_motion(moving=False, observed_at=0.5)
        aggregator.observe(
            prediction(100, 0.15),
            observed_at=1.0,
            detected_at="2026-08-16T00:00:01Z",
        )

        events = aggregator.expire(2.1)

        final = [event for event in events if event.event_type == "fall_suspected"]
        self.assertEqual(len(final), 1)
        self.assertTrue(final[0].evidence["radar_motion_available"])
        self.assertFalse(final[0].evidence["radar_available"])

    def test_low_signal_quality_adjusts_confidence_but_never_vetoes(self):
        aggregator = ActivityEventAggregator(episode_gap_seconds=1.0)
        aggregator.observe_signal(
            signal_evidence(0.0, 1.0, quality=0.0), observed_at=0.0
        )
        aggregator.observe(
            prediction(100, 0.15),
            observed_at=0.1,
            detected_at="2026-08-16T00:00:00Z",
        )

        events = aggregator.expire(1.2)

        final = [event for event in events if event.event_type == "fall_suspected"]
        self.assertEqual(len(final), 1)
        self.assertLess(
            final[0].confidence, final[0].evidence["final_fall_score"]
        )
        self.assertTrue(
            final[0].evidence["signal_quality_adjustment_is_not_a_gate"]
        )

    def test_signal_history_covers_full_fifteen_second_fusion_window(self):
        aggregator = ActivityEventAggregator()
        aggregator.observe_signal(signal_evidence(0.0, 1.0), observed_at=0.0)
        for index in range(1, 1201):
            at = index / 100.0
            aggregator.observe_signal(signal_evidence(at, 0.0), observed_at=at)
            aggregator.expire(at)
        aggregator.observe(
            prediction(100, 0.15),
            observed_at=12.0,
            detected_at="2026-08-16T00:00:12Z",
        )

        events = []
        for index in range(1201, 1402):
            at = index / 100.0
            aggregator.observe_signal(signal_evidence(at, 0.0), observed_at=at)
            events.extend(aggregator.expire(at))

        final = [event for event in events if event.event_type == "fall_suspected"]
        self.assertEqual(len(final), 1)
        self.assertGreaterEqual(final[0].evidence["final_fall_score"], 0.72)

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

    def test_one_signal_proposal_can_create_only_one_final_fall(self):
        aggregator = ActivityEventAggregator(episode_gap_seconds=1.0)
        aggregator.observe_signal(signal_evidence(0.0, 1.0), observed_at=0.0)
        aggregator.observe(
            prediction(100, 0.30),
            observed_at=0.1,
            detected_at="2026-08-16T00:00:00Z",
        )
        first = aggregator.expire(1.2)
        aggregator.observe(
            prediction(200, 0.80),
            observed_at=3.0,
            detected_at="2026-08-16T00:00:03Z",
        )
        repeated = aggregator.expire(4.1)

        self.assertEqual(
            len([event for event in first if event.event_type == "fall_suspected"]),
            1,
        )
        self.assertEqual(
            len(
                [
                    event
                    for event in repeated
                    if event.event_type == "fall_suspected"
                ]
            ),
            0,
        )

    def test_final_refractory_period_suppresses_a_second_proposal(self):
        aggregator = ActivityEventAggregator(
            episode_gap_seconds=1.0,
            final_refractory_seconds=30.0,
        )
        aggregator.observe_signal(
            signal_evidence(0.0, 1.0, proposal_id="proposal-1"),
            observed_at=0.0,
        )
        aggregator.observe(
            prediction(100, 0.30),
            observed_at=0.1,
            detected_at="2026-08-16T00:00:00Z",
        )
        first = aggregator.expire(1.2)
        aggregator.observe_signal(
            signal_evidence(10.0, 1.0, proposal_id="proposal-2"),
            observed_at=10.0,
        )
        aggregator.observe(
            prediction(200, 0.80),
            observed_at=10.1,
            detected_at="2026-08-16T00:00:10Z",
        )
        repeated = aggregator.expire(11.2)

        self.assertEqual(
            len([event for event in first if event.event_type == "fall_suspected"]),
            1,
        )
        self.assertEqual(
            len(
                [
                    event
                    for event in repeated
                    if event.event_type == "fall_suspected"
                ]
            ),
            0,
        )

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
        self.assertEqual(fused.source, "recall_first_soft_fusion")
        self.assertEqual(fused.evidence["fusion_rule"], "recall_first_soft_fusion_v3")
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

    def test_radar_before_ml_is_fused_when_episode_finishes(self):
        aggregator = ActivityEventAggregator(
            fall_score_threshold=0.8,
            episode_gap_seconds=1.0,
            radar_correlation_seconds=15.0,
        )
        self.assertIsNone(
            aggregator.fuse_radar_fall(radar_fall(), observed_at=1.0)
        )
        aggregator.observe(
            prediction(100, 0.93),
            observed_at=5.0,
            detected_at="2026-08-16T00:00:05Z",
        )

        events = aggregator.expire(6.1)

        self.assertEqual(
            [event.event_type for event in events],
            ["ml_fall_candidate", "fall_suspected"],
        )
        self.assertEqual(events[1].event_id, "radar-fall-1")
        self.assertEqual(events[1].source, "recall_first_soft_fusion")

    def test_radar_before_ml_outside_window_stays_candidate_only(self):
        aggregator = ActivityEventAggregator(
            fall_score_threshold=0.8,
            episode_gap_seconds=1.0,
            radar_correlation_seconds=15.0,
        )
        aggregator.fuse_radar_fall(radar_fall(), observed_at=1.0)
        aggregator.observe(
            prediction(100, 0.93),
            observed_at=20.0,
            detected_at="2026-08-16T00:00:20Z",
        )

        events = aggregator.expire(21.1)

        self.assertEqual([event.event_type for event in events], ["ml_fall_candidate"])

    def test_high_confidence_radar_can_fallback_after_ml_wait_window(self):
        aggregator = ActivityEventAggregator(
            radar_correlation_seconds=15.0,
            radar_fallback_confidence_threshold=0.9,
            radar_fallback_impact_ratio=5.0,
        )
        strong_radar = radar_fall(confidence=0.96, impact_ratio=8.4)
        aggregator.fuse_radar_fall(strong_radar, observed_at=1.0)

        self.assertEqual(aggregator.expire(15.9), [])
        events = aggregator.expire(16.1)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "fall_suspected")
        self.assertEqual(events[0].source, "radar_high_confidence_fallback")
        self.assertEqual(
            events[0].evidence["fusion_rule"],
            "radar_high_confidence_fallback_v1",
        )
        self.assertFalse(events[0].evidence["ml_confirmation"])
        self.assertEqual(aggregator.expire(17.0), [])

    def test_radar_fallback_rejects_weak_confidence_or_impact(self):
        aggregator = ActivityEventAggregator(
            radar_correlation_seconds=15.0,
            radar_fallback_confidence_threshold=0.9,
            radar_fallback_impact_ratio=5.0,
        )
        aggregator.fuse_radar_fall(
            radar_fall(confidence=0.89, impact_ratio=9.0),
            observed_at=1.0,
        )
        aggregator.fuse_radar_fall(
            replace(
                radar_fall(confidence=0.96, impact_ratio=4.9),
                event_id="radar-fall-2",
            ),
            observed_at=2.0,
        )

        self.assertEqual(aggregator.expire(18.0), [])

    def test_radar_fallback_is_disabled_by_default(self):
        aggregator = ActivityEventAggregator(radar_correlation_seconds=15.0)
        aggregator.fuse_radar_fall(
            radar_fall(confidence=0.99, impact_ratio=12.0),
            observed_at=1.0,
        )

        self.assertEqual(aggregator.expire(20.0), [])


if __name__ == "__main__":
    unittest.main()
