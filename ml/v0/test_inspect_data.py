from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from inspect_data import inspect_jsonl, parse_csi_array, parse_radar


class InspectDataTests(unittest.TestCase):
    def test_parses_csi_iq_array(self) -> None:
        raw = 'CSI_DATA,1,aa:bb,-40,0,"[1,2,-3,4]"'
        self.assertEqual(parse_csi_array(raw), [1.0, 2.0, -3.0, 4.0])

    def test_parses_radar_line(self) -> None:
        raw = "RADAR_DADA,1,123,0.1,0,0.2,1,0.3,0,0.25,1"
        self.assertEqual(
            parse_radar(raw),
            {
                "wander": 0.1,
                "jitter": 0.3,
                "move_threshold": 0.25,
                "moving": 1.0,
            },
        )

    def test_inspects_project_jsonl(self) -> None:
        records = [
            {"label": "walking", "raw": 'CSI_DATA,1,x,"[1,2,3,4]"'},
            {"label": "walking", "raw": "RADAR_DADA,1,2,0.1,0,0.2,1,0.3,0,0.25,1"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.jsonl"
            path.write_text(
                "\n".join(json.dumps(record) for record in records),
                encoding="utf-8",
            )
            result = inspect_jsonl(path)

        self.assertEqual(result["records"], 2)
        self.assertEqual(result["csi_frames"], 1)
        self.assertEqual(result["radar_frames"], 1)
        self.assertEqual(result["labels"], {"walking": 2})


if __name__ == "__main__":
    unittest.main()
