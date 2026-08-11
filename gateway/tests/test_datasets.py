import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from csi_gateway.datasets import (
    DatasetError,
    attach_dataset_to_profile,
    detach_dataset_from_profile,
    export_profile_dataset,
    import_dataset_bundle,
    list_datasets,
)
from csi_gateway.features import build_profile_feature_rows, extract_session_features
from csi_gateway.profiles import create_profile, load_profile


class DatasetLibraryTests(unittest.TestCase):
    def create_session(self, root: Path, profile_id: str, session_id: str) -> None:
        raw_dir = root / "data" / "raw"
        manifest_dir = root / "data" / "manifests"
        raw_dir.mkdir(parents=True, exist_ok=True)
        manifest_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"{session_id}.jsonl"
        records = [
            {
                "sessionId": session_id,
                "label": "lying_static",
                "raw": "RADAR_DADA,1,1,0.2,0,0.1,1,0.04,0,0.02,1",
            },
            {
                "sessionId": session_id,
                "label": "lying_static",
                "raw": "RADAR_DADA,2,2,0.1,0,0.1,1,0.02,0,0.02,0",
            },
        ]
        raw_path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )
        manifest = {
            "schemaVersion": "1.0.0",
            "sessionId": session_id,
            "profileId": profile_id,
            "label": "lying_static",
            "valid": True,
            "rawFile": raw_path.relative_to(root).as_posix(),
        }
        (manifest_dir / f"{session_id}.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    def export_fixture(self, root: Path) -> tuple[dict, Path]:
        profile = create_profile(
            root,
            display_name="공유 침실",
            placement_description="침대 대각선",
            distance_meters=1.8,
            channel=6,
            tx_mac="aa:bb:cc:dd:ee:01",
            rx_mac="aa:bb:cc:dd:ee:02",
        )
        self.create_session(root, profile["profileId"], "session-001")
        bundle_path = root / "exports" / "bedroom.csi-dataset.zip"
        export_profile_dataset(root, profile["profileId"], bundle_path)
        return profile, bundle_path

    def test_relative_features_use_radar_thresholds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_path = root / "sample.jsonl"
            raw_path.write_text(
                json.dumps(
                    {
                        "raw": "RADAR_DADA,1,1,0.2,0,0.1,1,0.04,0,0.02,1"
                    }
                ),
                encoding="utf-8",
            )
            features = extract_session_features(raw_path)
            self.assertAlmostEqual(features["wander_relative_mean"], 2.0)
            self.assertAlmostEqual(features["jitter_relative_mean"], 2.0)

    def test_native_bundle_round_trip_and_profile_attachment(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            source_root = Path(source_dir)
            source_profile, bundle_path = self.export_fixture(source_root)
            target_root = Path(target_dir)
            target_profile = create_profile(
                target_root,
                display_name="새 침실",
                placement_description="새 배치",
                distance_meters=2.0,
                channel=1,
            )

            dataset = import_dataset_bundle(target_root, bundle_path)
            attach_dataset_to_profile(
                target_root, target_profile, str(dataset["datasetId"])
            )
            restored = load_profile(target_root, target_profile["profileId"])
            rows = build_profile_feature_rows(target_root, restored["profileId"])

            self.assertEqual(len(list_datasets(target_root)), 1)
            self.assertEqual(len(restored["referenceDatasets"]), 1)
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["reference"])
            self.assertEqual(rows[0]["source_profile_id"], source_profile["profileId"])
            self.assertEqual(rows[0]["label"], "lying_static")

            detach_dataset_from_profile(
                target_root, restored, str(dataset["datasetId"])
            )
            self.assertEqual(
                load_profile(target_root, restored["profileId"])["referenceDatasets"],
                [],
            )

    def test_export_does_not_include_placement_or_device_macs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _, bundle_path = self.export_fixture(root)
            with ZipFile(bundle_path) as archive:
                metadata = json.loads(archive.read("dataset.json"))
            serialized = json.dumps(metadata)
            self.assertNotIn("placement", metadata)
            self.assertNotIn("devices", metadata)
            self.assertNotIn("aa:bb:cc:dd:ee:01", serialized)

    def test_import_rejects_tampered_session(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            root = Path(source_dir)
            _, bundle_path = self.export_fixture(root)
            tampered_path = root / "exports" / "tampered.zip"
            with ZipFile(bundle_path) as source, ZipFile(
                tampered_path, "w", compression=ZIP_DEFLATED
            ) as target:
                for name in source.namelist():
                    data = source.read(name)
                    if name.startswith("raw/"):
                        data += b"{}\n"
                    target.writestr(name, data)
            with self.assertRaisesRegex(DatasetError, "체크섬"):
                import_dataset_bundle(Path(target_dir), tampered_path)

    def test_import_rejects_unsafe_archive_member(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            root = Path(source_dir)
            _, bundle_path = self.export_fixture(root)
            unsafe_path = root / "exports" / "unsafe.zip"
            with ZipFile(bundle_path) as source, ZipFile(
                unsafe_path, "w", compression=ZIP_DEFLATED
            ) as target:
                for name in source.namelist():
                    target.writestr(name, source.read(name))
                target.writestr("../outside.txt", "unsafe")
            with self.assertRaisesRegex(DatasetError, "안전하지 않은"):
                import_dataset_bundle(Path(target_dir), unsafe_path)


if __name__ == "__main__":
    unittest.main()
