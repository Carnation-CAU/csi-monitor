import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from csi_gateway.fall_alert import (
    FallAlertError,
    build_collection_fall_event,
    build_detected_fall_event,
    normalize_event_endpoint,
    send_fall_event,
)
from csi_gateway.cli import build_parser


class FakeResponse:
    status = 201

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return b'{"window_id":"trial-01"}'


class FallAlertTest(unittest.TestCase):
    def test_builds_live_detection_contract_event(self):
        event = build_detected_fall_event(
            window_id="fall-live-01",
            detected_at="2026-08-16T15:30:00+09:00",
            room_id="living-room",
            risk_score=0.81,
            motion_confidence=0.84,
            presence_state="present",
            presence_probability=0.78,
            no_recovery_sec=8.0,
        )

        self.assertEqual(event["window_id"], "fall-live-01")
        self.assertEqual(event["risk_score"], 0.81)
        self.assertEqual(event["evidence"]["no_recovery_sec"], 8.0)

    def test_rejects_out_of_range_live_confidence(self):
        with self.assertRaisesRegex(ValueError, "risk_score"):
            build_detected_fall_event(
                window_id="fall-live-01",
                detected_at="2026-08-16T15:30:00+09:00",
                room_id="living-room",
                risk_score=1.1,
                motion_confidence=0.8,
                presence_state="present",
                presence_probability=0.8,
                no_recovery_sec=8.0,
            )

    def test_builds_contract_event_from_confirmed_collection(self):
        event = build_collection_fall_event(
            session_id="trial-01",
            detected_at="2026-08-16T15:30:00+09:00",
            room_id="living-room",
        )

        self.assertEqual(event["schema_version"], "1.0")
        self.assertEqual(event["event_type"], "fall_suspected")
        self.assertEqual(event["window_id"], "trial-01")
        self.assertEqual(event["evidence"]["motion_label"], "fall_like")
        self.assertEqual(event["evidence"]["presence_state"], "unknown")

    def test_rejects_timestamp_without_timezone(self):
        with self.assertRaisesRegex(ValueError, "타임존"):
            build_collection_fall_event(
                session_id="trial-01",
                detected_at="2026-08-16T15:30:00",
                room_id="living-room",
            )

    def test_normalizes_server_base_url(self):
        self.assertEqual(
            normalize_event_endpoint("http://192.168.0.5:8080/"),
            "http://192.168.0.5:8080/api/v1/events",
        )

    def test_cli_accepts_manual_fall_alert_test(self):
        args = build_parser().parse_args(
            [
                "fall-alert-test",
                "--server",
                "http://localhost:8080",
                "--room-id",
                "living-room",
            ]
        )

        self.assertEqual(args.command, "fall-alert-test")
        self.assertEqual(args.room_id, "living-room")
        self.assertEqual(
            normalize_event_endpoint("http://192.168.0.5:8080/api/v1/events"),
            "http://192.168.0.5:8080/api/v1/events",
        )
        self.assertEqual(
            normalize_event_endpoint("http://192.168.0.5:8080/health"),
            "http://192.168.0.5:8080/api/v1/events",
        )

    @patch("csi_gateway.fall_alert.urlopen", return_value=FakeResponse())
    def test_posts_contract_json(self, mocked_urlopen):
        event = build_collection_fall_event(
            session_id="trial-01",
            detected_at="2026-08-16T15:30:00+09:00",
            room_id="living-room",
        )

        send_fall_event("http://localhost:8080", event)

        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:8080/api/v1/events")
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data), event)

    @patch("csi_gateway.fall_alert.urlopen")
    def test_surfaces_server_contract_message(self, mocked_urlopen):
        mocked_urlopen.side_effect = HTTPError(
            "http://localhost:8080/api/v1/events",
            422,
            "contract violation",
            {},
            BytesIO(
                json.dumps(
                    {"code": "contract_violation", "message": "risk_score 오류"}
                ).encode("utf-8")
            ),
        )

        with self.assertRaisesRegex(FallAlertError, "risk_score 오류"):
            send_fall_event("http://localhost:8080", {})

    @patch("csi_gateway.fall_alert.urlopen")
    def test_surfaces_connection_failure(self, mocked_urlopen):
        mocked_urlopen.side_effect = URLError("connection refused")

        with self.assertRaisesRegex(FallAlertError, "connection refused"):
            send_fall_event("http://localhost:8080", {})


if __name__ == "__main__":
    unittest.main()
