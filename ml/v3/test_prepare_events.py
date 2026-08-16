import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prepare_events import (  # noqa: E402
    SegmentConfig,
    make_event_record,
    prepare_session,
    read_gateway_jsonl,
    resample,
    run,
    segment_moving_events,
    target_label,
)


def record(timestamp, raw, sample_id):
    return json.dumps({
        "schemaVersion": "1.0.0", "sessionId": "s1", "sampleId": sample_id,
        "timestampUtc": timestamp.isoformat().replace("+00:00", "Z"),
        "deviceId": "rx-s3-001", "label": "unlabeled",
        "encoding": "utf-8", "raw": raw,
    })


def radar_line(sequence, moving, jitter=2.0):
    return f"RADAR_DADA,{sequence},device-ts,{10 + sequence},0,5,1,{jitter},0,1,{int(moving)}"


class PrepareEventsTests(unittest.TestCase):
    def make_session(self, moving_indices):
        start = datetime(2026, 8, 12, tzinfo=timezone.utc)
        temporary = tempfile.TemporaryDirectory()
        path = Path(temporary.name) / "session.jsonl"
        lines = [record(start, "I (1) esp_radar: rssi: -45, freq: 100Hz", 1)]
        for index in range(20):
            lines.append(record(
                start + timedelta(seconds=0.25 * index),
                radar_line(index, index in moving_indices), index + 2,
            ))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return temporary, path

    def test_parser_attaches_latest_link_values(self):
        temporary, path = self.make_session({4, 5})
        with temporary:
            parsed = read_gateway_jsonl(path)
        self.assertEqual(len(parsed.points), 20)
        self.assertEqual(parsed.link_records, 1)
        self.assertEqual(parsed.points[0].rssi, -45)
        self.assertEqual(parsed.points[0].packet_hz, 100)

    def test_short_false_gap_is_merged_and_long_gap_is_split(self):
        temporary, path = self.make_session({2, 3, 5, 6, 14, 15})
        with temporary:
            points = read_gateway_jsonl(path).points
        events = segment_moving_events(points, SegmentConfig(
            max_moving_gap_seconds=0.6, pre_context_seconds=0.5,
            post_context_seconds=0.5, min_moving_samples=2,
        ))
        self.assertEqual(len(events), 2)
        self.assertEqual((events[0].core_start, events[0].core_end), (2, 6))
        self.assertEqual((events[1].core_start, events[1].core_end), (14, 15))

    def test_single_moving_sample_is_filtered_by_default(self):
        temporary, path = self.make_session({5})
        with temporary:
            points = read_gateway_jsonl(path).points
        self.assertEqual(segment_moving_events(points, SegmentConfig()), [])

    def test_prepare_session_outputs_fixed_model_input(self):
        temporary, path = self.make_session({5, 6, 7})
        with temporary:
            events, features, diagnostic = prepare_session(path, {
                "sessionId": "session-1", "profileId": "room-a",
                "label": "walking_slow", "eventAtUtc": "2026-08-12T00:00:01.5Z",
            }, SegmentConfig(pre_context_seconds=0.5, post_context_seconds=0.5))
        self.assertEqual(len(events), 1)
        self.assertEqual(len(features), 1)
        self.assertEqual(events[0]["targetLabel"], "walking")
        self.assertEqual(len(events[0]["fixedLengthSignals"]["jitter_relative"]), 64)
        self.assertEqual(diagnostic["events"], 1)
        self.assertTrue(np.isfinite(list(features[0].values())[-1]))

    def test_resample_handles_one_value(self):
        result = resample(np.asarray([0.0]), np.asarray([3.0]), 4)
        self.assertEqual(result.tolist(), [3.0, 3.0, 3.0, 3.0])

    def test_target_label_mapping(self):
        self.assertEqual(target_label("walking_slow"), "walking")
        self.assertEqual(target_label("fall_simulated_mattress"), "fall_suspected")
        self.assertEqual(target_label("sit_down_fast"), "other_motion")
        self.assertEqual(target_label("unlabeled"), "unknown")

    def test_empty_project_still_writes_valid_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data" / "manifests").mkdir(parents=True)
            output = root / "output"
            summary = run(root, output, SegmentConfig())
            self.assertEqual(summary["sessions"], 0)
            self.assertEqual(summary["events"], 0)
            self.assertTrue((output / "summary.json").is_file())
            self.assertTrue((output / "events.jsonl").is_file())
            self.assertTrue((output / "features.csv").is_file())


if __name__ == "__main__":
    unittest.main()
