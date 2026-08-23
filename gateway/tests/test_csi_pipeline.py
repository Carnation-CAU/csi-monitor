import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from csi_gateway.csi import parse_csi_line
from csi_gateway.csi_pipeline import (
    AdaptiveCsiBaseline,
    CsiRealtimePipeline,
    HighRecallEventDetector,
    PacketTimingTracker,
)
from csi_gateway.event_clips import EventClipRecorder


def csi_sample(sequence=1, timestamp_us=1_000_000, channel=6, level=10):
    fields = [
        "CSI_DATA", str(sequence), "1", "0", "unknown",
        "1a:00:00:00:00:00", "-55", "11", "1", "0", "0", "1", "1",
        "0", "0", "0", "1", "-98", "0", str(channel), "0",
        str(timestamp_us), "0", "44", "0", "35", "-14", "104", "0",
    ]
    iq = [level if index % 2 else -level for index in range(104)]
    fields.append('"' + json.dumps(iq, separators=(",", ":")) + '"')
    sample = parse_csi_line(",".join(fields))
    assert sample is not None
    return sample


class CsiPipelineTests(unittest.TestCase):
    def test_sustained_energy_is_one_proposal_until_quiet_rearm(self):
        detector = HighRecallEventDetector()
        mask = np.ones(52, dtype=bool)
        zero = np.zeros(52, dtype=np.float32)
        high = np.full(52, 0.5, dtype=np.float32)
        for index in range(100):
            detector.update(
                amplitude_delta=zero,
                phase_delta=zero,
                mask=mask,
                observed_at=index / 100.0,
                signal_quality=1.0,
                baseline_ready=True,
                channel_changed=False,
            )
        proposal_ids = set()
        for index in range(700):
            evidence = detector.update(
                amplitude_delta=high,
                phase_delta=zero,
                mask=mask,
                observed_at=1.0 + index / 100.0,
                signal_quality=1.0,
                baseline_ready=True,
                channel_changed=False,
            )
            if evidence.proposal_id:
                proposal_ids.add(evidence.proposal_id)
        self.assertEqual(len(proposal_ids), 1)

        for index in range(200):
            detector.update(
                amplitude_delta=zero,
                phase_delta=zero,
                mask=mask,
                observed_at=8.0 + index / 100.0,
                signal_quality=1.0,
                baseline_ready=True,
                channel_changed=False,
            )
        rearmed = detector.update(
            amplitude_delta=high,
            phase_delta=zero,
            mask=mask,
            observed_at=10.1,
            signal_quality=1.0,
            baseline_ready=True,
            channel_changed=False,
        )
        self.assertIsNotNone(rearmed.proposal_id)
        self.assertNotIn(rearmed.proposal_id, proposal_ids)

    def test_parser_preserves_iq_phase_metadata_and_masks_pilots(self):
        sample = csi_sample()
        self.assertEqual(sample.iq.shape, (52, 2))
        self.assertEqual(sample.csi_length, 104)
        self.assertEqual(sample.noise_floor, -98)
        self.assertEqual(sample.agc_gain, 35)
        self.assertEqual(int(sample.valid_subcarrier_mask.sum()), 48)
        self.assertEqual(sample.training_record()["iqOrder"], ["imag", "real"])
        self.assertEqual(len(sample.training_record()["amplitude"]), 52)
        self.assertEqual(len(sample.training_record()["phase"]), 52)
        self.assertTrue(np.all(np.isfinite(sample.phase)))

    def test_packet_timing_reports_rate_gaps_and_loss(self):
        tracker = PacketTimingTracker()
        for sequence, timestamp in ((1, 0), (2, 10_000), (4, 40_000)):
            tracker.observe(csi_sample(sequence, timestamp))
        stats = tracker.stats()
        self.assertAlmostEqual(stats.rate_hz, 50.0)
        self.assertEqual(stats.gap_count, 1)
        self.assertEqual(stats.missing_sequence_count, 1)
        self.assertGreater(stats.signal_quality_score, 0.0)

    def test_robust_baseline_normalizes_and_freezes_during_motion(self):
        baseline = AdaptiveCsiBaseline(adaptive_alpha=0.01)
        baseline.start_calibration()
        original = csi_sample()
        for index in range(220):
            amplitude = np.full(52, 20.0 + (index % 3 - 1) * 0.1, np.float32)
            baseline.observe_calibration(replace(original, amplitude=amplitude))
        self.assertTrue(baseline.finalize_calibration())
        normalized, mask = baseline.normalize(
            replace(original, amplitude=np.full(52, 20.2, np.float32))
        )
        self.assertEqual(int(mask.sum()), 48)
        self.assertLess(float(np.median(np.abs(normalized[mask]))), 5.0)
        before = baseline.mean.copy()
        self.assertFalse(
            baseline.adaptive_update(
                replace(original, amplitude=np.full(52, 30.0, np.float32)),
                no_motion_confidence=1.0,
                fall_candidate=True,
            )
        )
        np.testing.assert_array_equal(before, baseline.mean)

    def test_realtime_pipeline_emits_scores_without_gating_on_quality(self):
        pipeline = CsiRealtimePipeline()
        first = csi_sample(1, 0, level=10)
        second = csi_sample(2, 10_000, level=40)
        pipeline.observe(first, observed_at=0.0)
        evidence = pipeline.observe(second, observed_at=0.01)
        self.assertGreaterEqual(evidence.motion_score, 0.0)
        self.assertIn(
            evidence.state,
            {"IDLE", "MOVEMENT", "HIGH_ENERGY_EVENT", "POST_EVENT_MONITORING"},
        )
        self.assertGreater(pipeline.timing.stats().rate_hz, 0.0)

    def test_event_clip_keeps_pre_and_post_frames(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = EventClipRecorder(Path(temp_dir), pre_seconds=1, post_seconds=1)
            recorder.observe(raw_line=b"CSI_DATA,pre\n", observed_at=0.0, timestamp_utc="t0")
            path = recorder.trigger({"event_id": "fall-1"}, observed_at=0.5)
            recorder.trigger(
                {"event_id": "fall-1", "event_type": "fall_suspected"},
                observed_at=0.6,
            )
            ready = recorder.observe(
                raw_line=b"CSI_DATA,post\n", observed_at=1.7, timestamp_utc="t1"
            )
            self.assertEqual(ready, [path])
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(records[0]["recordType"], "event")
            self.assertEqual(records[0]["event"]["event_type"], "fall_suspected")
            self.assertEqual([row["raw"] for row in records[1:]], ["CSI_DATA,pre", "CSI_DATA,post"])


if __name__ == "__main__":
    unittest.main()
