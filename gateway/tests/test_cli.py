import io
import json
import tempfile
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath

from csi_gateway.cli import build_record, create_session_paths, write_json_line
from csi_gateway.collection import (
    COLLECTION_LABELS,
    TRANSITION_LABELS,
    render_korean_summary,
    summarize_collection,
)
from csi_gateway.features import extract_session_features
from csi_gateway.prototype import REFERENCE_FEATURES, predict_action
from csi_gateway.radar import (
    CalibrationSample,
    LinkSample,
    RadarSample,
    parse_channel_line,
    parse_calibration_line,
    parse_device_mac_line,
    parse_link_line,
    parse_radar_line,
)
from csi_gateway.profiles import (
    append_profile_session,
    archive_profile,
    create_profile,
    list_profiles,
    load_profile,
    load_or_create_profile,
    update_profile_calibration,
    update_profile_rx_mac,
)


class CollectorTests(unittest.TestCase):
    def test_prototype_prediction_uses_nearest_standardized_action(self):
        def row(label: str, value: float):
            return {"label": label, **{feature: value for feature in REFERENCE_FEATURES}}

        prediction = predict_action(
            {feature: 0.1 for feature in REFERENCE_FEATURES},
            [row("static", 0.0), row("walking", 10.0), row("turning", 5.0)],
        )
        self.assertIsNotNone(prediction)
        self.assertEqual(prediction.label, "static")
        self.assertGreater(prediction.separation_percent, 0)

    def test_extract_session_radar_features(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_path = Path(temp_dir) / "sample.jsonl"
            records = [
                {"raw": "RADAR_DADA,1,1,0.1,0,0,0,0.01,0,0,0"},
                {"raw": "RADAR_DADA,2,2,0.3,0,0,1,0.03,0,0,1"},
                {"raw": "I (1) esp_radar: rssi: -60, freq: 80Hz"},
            ]
            raw_path.write_text(
                "\n".join(json.dumps(record) for record in records),
                encoding="utf-8",
            )
            features = extract_session_features(raw_path)
            self.assertEqual(features["radar_count"], 2.0)
            self.assertAlmostEqual(features["jitter_mean"], 0.02)
            self.assertEqual(features["moving_ratio"], 0.5)
            self.assertEqual(features["rssi_mean"], -60.0)
    def test_fall_and_similar_actions_are_collection_labels(self):
        expected = {
            "sit_down_fast",
            "pick_up_object",
            "fall_simulated_mattress",
        }
        self.assertTrue(expected.issubset(COLLECTION_LABELS))
        self.assertTrue(expected.issubset(TRANSITION_LABELS))

    def test_record_preserves_unicode_and_replaces_invalid_bytes(self):
        record = build_record(
            session_id="session-1",
            sample_id=1,
            device_id="rx-1",
            raw_line=b"CSI_DATA,\xff\r\n",
            label="walking",
        )
        self.assertEqual(record["raw"], "CSI_DATA,\ufffd")
        self.assertEqual(record["label"], "walking")

    def test_json_lines_are_utf8_compatible(self):
        output = io.StringIO()
        write_json_line(output, {"label": "빈 방"})
        self.assertEqual(json.loads(output.getvalue())["label"], "빈 방")

    def test_session_paths_are_created_inside_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw, manifest = create_session_paths(Path(temp_dir), "session-1")
            self.assertTrue(raw.parent.is_dir())
            self.assertTrue(manifest.parent.is_dir())
            self.assertEqual(raw.name, "session-1.jsonl")

    def test_relative_data_path_is_platform_neutral(self):
        self.assertEqual(
            PureWindowsPath("data", "raw", "a.jsonl").as_posix(),
            PurePosixPath("data/raw/a.jsonl").as_posix(),
        )

    def test_parse_radar_line(self):
        sample = parse_radar_line(
            b"RADAR_DADA,12,1234,0.0,0.0,0.1,0,0.025,0.01,0.02,1\r\n"
        )
        self.assertIsNotNone(sample)
        self.assertEqual(sample.sequence, 12)
        self.assertAlmostEqual(sample.jitter, 0.025)
        self.assertTrue(sample.moving)

    def test_parse_radar_line_ignores_unrelated_or_partial_data(self):
        self.assertIsNone(parse_radar_line(b"I (100) booted\r\n"))
        self.assertIsNone(parse_radar_line(b"RADAR_DADA,1,2\r\n"))

    def test_parse_link_line(self):
        sample = parse_link_line(
            b"I (1411) esp_radar: time: 500/2, rssi: -75, jitter: 0, freq: 58Hz\r\n"
        )
        self.assertIsNotNone(sample)
        self.assertEqual(sample.rssi, -75)
        self.assertEqual(sample.frequency_hz, 58)

    def test_parse_channel_line(self):
        sample = parse_channel_line(b"RF_CHANNEL,6\r\n")
        self.assertIsNotNone(sample)
        self.assertEqual(sample.channel, 6)
        self.assertIsNone(parse_channel_line(b"RF_CHANNEL,3\r\n"))

    def test_parse_calibration_line(self):
        sample = parse_calibration_line(
            b"RADAR_DADA,0,0,0,0.123,0,0,0.456,0\r\n"
        )
        self.assertEqual(sample, CalibrationSample(0.123, 0.456))
        self.assertIsNone(parse_calibration_line(b"RADAR_DADA,1,2\r\n"))

    def test_space_profile_persists_calibration_and_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = load_or_create_profile(root)
            self.assertTrue(profile["needsCalibration"])
            update_profile_calibration(
                root,
                profile,
                someone_threshold=0.123,
                move_threshold=0.456,
            )
            append_profile_session(root, profile, "session-1")
            restored = load_or_create_profile(root)
            self.assertFalse(restored["needsCalibration"])
            self.assertEqual(restored["calibration"]["moveThreshold"], 0.456)
            self.assertIn("session-1", restored["sessionIds"])

    def test_multiple_space_profiles_can_be_created_and_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = load_or_create_profile(root)
            second = create_profile(
                root,
                display_name="부모님 집 거실",
                placement_description="소파와 TV 사이",
                distance_meters=2.5,
                channel=6,
            )
            profiles = list_profiles(root)
            self.assertEqual(len(profiles), 2)
            self.assertNotEqual(first["profileId"], second["profileId"])
            restored = load_profile(root, second["profileId"])
            self.assertEqual(restored["displayName"], "부모님 집 거실")
            self.assertEqual(restored["radio"]["channel"], 6)
            self.assertTrue(restored["needsCalibration"])

    def test_new_profile_does_not_record_borrowed_board_macs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            load_or_create_profile(root)
            profile = create_profile(
                root,
                display_name="시험 공간 A",
                placement_description="두 보드를 마주보게 배치",
                distance_meters=2.0,
                channel=6,
            )
            restored = load_profile(root, profile["profileId"])
            self.assertIsNone(restored["devices"]["txMac"])
            self.assertIsNone(restored["devices"]["rxMac"])

    def test_new_profile_keeps_explicitly_given_macs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            load_or_create_profile(root)
            profile = create_profile(
                root,
                display_name="시험 공간",
                placement_description="시험 배치",
                distance_meters=1.5,
                channel=1,
                tx_mac="aa:bb:cc:dd:ee:01",
                rx_mac="aa:bb:cc:dd:ee:02",
            )
            restored = load_profile(root, profile["profileId"])
            self.assertEqual(restored["devices"]["txMac"], "aa:bb:cc:dd:ee:01")
            self.assertEqual(restored["devices"]["rxMac"], "aa:bb:cc:dd:ee:02")

    def test_observed_rx_mac_fills_empty_value_but_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            load_or_create_profile(root)
            profile = create_profile(
                root,
                display_name="관측 시험",
                placement_description="시험 배치",
                distance_meters=1.0,
                channel=6,
            )
            self.assertIsNotNone(update_profile_rx_mac(root, profile, "aa:bb:cc:dd:ee:02"))
            self.assertEqual(
                load_profile(root, profile["profileId"])["devices"]["rxMac"],
                "aa:bb:cc:dd:ee:02",
            )

            # 이미 값이 있으면 다른 보드를 관측해도 덮어쓰지 않는다.
            self.assertIsNone(update_profile_rx_mac(root, profile, "ff:ee:dd:cc:bb:aa"))
            self.assertEqual(
                load_profile(root, profile["profileId"])["devices"]["rxMac"],
                "aa:bb:cc:dd:ee:02",
            )

    def test_device_mac_is_parsed_from_boot_log_only(self):
        self.assertEqual(
            parse_device_mac_line("I (850) wifi:mode : sta (aa:bb:cc:dd:ee:02)").mac,
            "aa:bb:cc:dd:ee:02",
        )
        self.assertEqual(
            parse_device_mac_line(b"I (623) wifi:mode : sta (AA:BB:CC:DD:EE:01)").mac,
            "aa:bb:cc:dd:ee:01",
        )
        # CSI_DATA의 MAC 필드는 ESP-NOW 브로드캐스트 송신 주소이며 보드 식별자가 아니다.
        self.assertIsNone(
            parse_device_mac_line(
                "CSI_DATA,29077,514770,0,unknown,1a:00:00:00:00:00,-67,11,1,0"
            )
        )
        self.assertIsNone(parse_device_mac_line("I (467) system_api: Base MAC address is not set"))
        self.assertIsNone(parse_device_mac_line("RADAR_DADA,1,2,3,4,5,6,7,8,9,10"))

    def test_archived_profile_disappears_without_deleting_its_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            load_or_create_profile(root)
            profile = create_profile(
                root,
                display_name="삭제 시험",
                placement_description="시험 배치",
                distance_meters=1.0,
                channel=1,
            )
            archived = archive_profile(root, profile["profileId"])
            self.assertTrue(archived.exists())
            self.assertFalse((root / "data" / "profiles" / f"{profile['profileId']}.json").exists())
            self.assertEqual(len(list_profiles(root)), 1)

    def test_collection_summary(self):
        radar = [
            RadarSample(1, "1", 0, 0, False, 0.01, 0.02, False),
            RadarSample(2, "2", 0, 0, False, 0.03, 0.02, True),
        ]
        link = [LinkSample(-70, 60), LinkSample(-60, 80)]
        summary = summarize_collection(radar, link)
        self.assertEqual(summary.radar_count, 2)
        self.assertEqual(summary.moving_count, 1)
        self.assertEqual(summary.moving_ratio, 50.0)
        self.assertEqual(summary.average_rssi, -65.0)
        self.assertEqual(summary.minimum_hz, 60)

    def test_korean_collection_summary_contains_session_data(self):
        summary = summarize_collection([], [])
        text = render_korean_summary(
            session_id="session-1",
            label="lying_static",
            duration_seconds=60,
            valid=True,
            event_at_utc=None,
            channel=1,
            summary=summary,
            raw_file="data/raw/session-1.jsonl",
            manifest_file="data/manifests/session-1.json",
        )
        self.assertIn("행동 수집 결과", text)
        self.assertIn("유효 여부: 유효", text)
        self.assertIn("Wi-Fi 채널: 1", text)


if __name__ == "__main__":
    unittest.main()
