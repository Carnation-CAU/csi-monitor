from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from time import perf_counter
from uuid import uuid4

from .profiles import FIXED_WIFI_BANDWIDTH

SCHEMA_VERSION = "2.0.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def available_ports() -> list[dict[str, str]]:
    from serial.tools import list_ports

    return [
        {
            "device": port.device,
            "description": port.description or "",
            "hwid": port.hwid or "",
        }
        for port in list_ports.comports()
    ]


def create_session_paths(
    root: Path, session_id: str, *, label: str | None = None
) -> tuple[Path, Path]:
    raw_dir = root / "data" / "raw"
    if label is not None:
        from .collection import is_valid_collection_label

        if not is_valid_collection_label(label):
            raise ValueError(f"안전하지 않은 행동 라벨: {label}")
        raw_dir /= label
    manifest_dir = root / "data" / "manifests"
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir / f"{session_id}.jsonl", manifest_dir / f"{session_id}.json"


def relocate_session_raw(
    root: Path, raw_path: Path, session_id: str, label: str
) -> Path:
    """Move a completed session under the folder for its confirmed action."""
    target_path, _ = create_session_paths(root, session_id, label=label)
    if raw_path.resolve() == target_path.resolve():
        return raw_path
    if target_path.exists():
        raise FileExistsError(f"같은 행동 세션 원본이 이미 있습니다: {target_path}")
    raw_path.replace(target_path)
    try:
        raw_path.parent.rmdir()
    except OSError:
        pass
    return target_path


def build_record(
    *,
    session_id: str,
    sample_id: int,
    device_id: str,
    raw_line: bytes,
    label: str,
) -> dict[str, object]:
    decoded = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
    record: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "sessionId": session_id,
        "sampleId": sample_id,
        "timestampUtc": utc_now(),
        "deviceId": device_id,
        "label": label,
        "encoding": "utf-8-replace",
        "raw": decoded,
    }
    # Keep the byte-for-byte decoded UART row and add a machine-readable,
    # lossless CSI view. IQ remains authoritative even though inspectable
    # amplitude/phase derivatives are included in schema v2.
    from .csi import parse_csi_line

    csi = parse_csi_line(decoded)
    if csi is not None:
        record["recordType"] = "csi"
        record["csi"] = csi.training_record()
    elif "RADAR_DADA," in decoded:
        record["recordType"] = "radar"
    else:
        record["recordType"] = "log"
    return record


def write_json_line(file_handle, record: dict[str, object]) -> None:
    file_handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    file_handle.flush()


def collect(args: argparse.Namespace) -> int:
    from serial import Serial

    from .csi import RAW_CSI_ENABLE_COMMAND, parse_csi_line
    from .csi_pipeline import PacketTimingTracker

    project_root = Path(args.project_root).resolve()
    session_id = args.session_id or (
        datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    )
    raw_path, manifest_path = create_session_paths(
        project_root, session_id, label=args.label
    )
    started_at = utc_now()
    sample_count = 0
    csi_count = 0
    timing = PacketTimingTracker()
    deadline = monotonic() + args.duration if args.duration else None

    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "sessionId": session_id,
        "startedAtUtc": started_at,
        "finishedAtUtc": None,
        "deviceId": args.device_id,
        "roomId": args.room_id,
        "personId": args.person_id,
        "positionId": args.position_id,
        "activityId": args.activity_id or args.label,
        "deviceFamily": "ESP32-S3",
        "label": args.label,
        "serialPort": args.port,
        "baudRate": args.baud,
        "bandwidth": FIXED_WIFI_BANDWIDTH,
        "platform": platform.platform(),
        "pythonVersion": platform.python_version(),
        "sampleCount": 0,
        "csiSampleCount": 0,
        "rawFile": raw_path.relative_to(project_root).as_posix(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Collecting {args.port} -> {raw_path}")
    try:
        with Serial(args.port, args.baud, timeout=1) as serial_port:
            serial_port.write(f"{RAW_CSI_ENABLE_COMMAND}\r\n".encode("utf-8"))
            with raw_path.open("w", encoding="utf-8", newline="\n") as output:
                while deadline is None or monotonic() < deadline:
                    raw_line = serial_port.readline()
                    if not raw_line:
                        continue
                    sample_count += 1
                    csi = parse_csi_line(raw_line)
                    if csi is not None:
                        csi_count += 1
                        timing.observe(csi)
                    write_json_line(
                        output,
                        build_record(
                            session_id=session_id,
                            sample_id=sample_count,
                            device_id=args.device_id,
                            raw_line=raw_line,
                            label=args.label,
                        ),
                    )
    except KeyboardInterrupt:
        print("Collection stopped by user.")
    finally:
        manifest["finishedAtUtc"] = utc_now()
        manifest["sampleCount"] = sample_count
        manifest["csiSampleCount"] = csi_count
        manifest["csiTiming"] = timing.stats().to_record()
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(f"Saved {sample_count} records and manifest {manifest_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ESP32 CSI serial gateway")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("ports", help="List available serial ports")

    collect_parser = subparsers.add_parser("collect", help="Collect raw serial lines")
    collect_parser.add_argument("--port", required=True)
    collect_parser.add_argument("--baud", type=int, default=2_000_000)
    collect_parser.add_argument("--duration", type=float, default=0)
    collect_parser.add_argument("--session-id")
    collect_parser.add_argument("--device-id", default="rx-s3-001")
    collect_parser.add_argument("--room-id", default="room-01")
    collect_parser.add_argument("--person-id", default="unknown-person")
    collect_parser.add_argument("--position-id", default="unknown-position")
    collect_parser.add_argument("--activity-id")
    collect_parser.add_argument("--label", default="unlabeled")
    collect_parser.add_argument("--project-root", default=".")

    monitor_parser = subparsers.add_parser(
        "monitor", help="Show a live movement monitor"
    )
    monitor_parser.add_argument("--port", required=True)
    monitor_parser.add_argument("--baud", type=int, default=2_000_000)
    monitor_parser.add_argument("--project-root", default=".")
    monitor_parser.add_argument("--activity-model", help="Optional CNN checkpoint (.pt)")
    monitor_parser.add_argument("--activity-hz", type=float, default=5.0)
    monitor_parser.add_argument("--activity-window-frames", type=int)
    monitor_parser.add_argument("--activity-tail-seconds", type=float, default=3.0)
    monitor_parser.add_argument(
        "--activity-fall-threshold",
        type=float,
        default=0.10,
        help="High-recall ML candidate threshold; not the final alert threshold",
    )
    monitor_parser.add_argument("--fusion-decision-threshold", type=float, default=0.72)
    monitor_parser.add_argument("--ml-direct-threshold", type=float, default=0.85)

    model_check_parser = subparsers.add_parser(
        "activity-model-check",
        help="Validate the local activity checkpoint and run one inference",
    )
    model_check_parser.add_argument(
        "--model", default="ml/v_main/model.pt", help="Checkpoint path"
    )
    model_check_parser.add_argument("--device", help="cpu, cuda, or mps")
    model_check_parser.add_argument("--project-root", default=".")

    fall_alert_test_parser = subparsers.add_parser(
        "fall-alert-test", help="Send one test fall event to the app server"
    )
    fall_alert_test_parser.add_argument("--server", required=True)
    fall_alert_test_parser.add_argument("--room-id", default="room-01")

    features_parser = subparsers.add_parser(
        "features", help="Build session-level Radar features"
    )
    features_parser.add_argument("--profile-id", required=True)
    features_parser.add_argument("--project-root", default=".")
    features_parser.add_argument("--output")

    dataset_export_parser = subparsers.add_parser(
        "dataset-export", help="Export one profile as a native dataset bundle"
    )
    dataset_export_parser.add_argument("--profile-id", required=True)
    dataset_export_parser.add_argument("--output", required=True)
    dataset_export_parser.add_argument("--name")
    dataset_export_parser.add_argument("--project-root", default=".")

    dataset_import_parser = subparsers.add_parser(
        "dataset-import", help="Import a native dataset bundle"
    )
    dataset_import_parser.add_argument("--bundle", required=True)
    dataset_import_parser.add_argument("--project-root", default=".")

    dataset_list_parser = subparsers.add_parser(
        "dataset-list", help="List imported datasets"
    )
    dataset_list_parser.add_argument("--project-root", default=".")

    for command, help_text in (
        ("dataset-attach", "Attach a reference dataset to a profile"),
        ("dataset-detach", "Detach a reference dataset from a profile"),
    ):
        dataset_profile_parser = subparsers.add_parser(command, help=help_text)
        dataset_profile_parser.add_argument("--profile-id", required=True)
        dataset_profile_parser.add_argument("--dataset-id", required=True)
        dataset_profile_parser.add_argument("--project-root", default=".")
    return parser


def send_test_fall_alert(args: argparse.Namespace) -> int:
    from .fall_alert import FallAlertError, build_collection_fall_event, send_fall_event

    window_id = f"manual-test-{uuid4().hex}"
    event = build_collection_fall_event(
        session_id=window_id,
        detected_at=utc_now(),
        room_id=args.room_id,
    )
    try:
        send_fall_event(args.server, event)
    except (FallAlertError, ValueError) as exc:
        print(f"테스트 이벤트 전송 실패: {exc}", file=sys.stderr)
        return 1
    print(f"앱 서버가 테스트 이벤트를 접수했습니다: {window_id}")
    return 0


def check_activity_model(args: argparse.Namespace) -> int:
    """Load the production checkpoint and exercise its real inference path."""
    import numpy as np

    from .activity import ActivityWindow

    project_root = Path(args.project_root).resolve()
    model_path = Path(args.model)
    if not model_path.is_absolute():
        model_path = project_root / model_path
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        from ml.runtime import TorchCnnActivityModel

        model = TorchCnnActivityModel(model_path, device=args.device)
        # This deterministic input checks deployment compatibility only. It is
        # deliberately not presented as a classification-accuracy result.
        synthetic = np.linspace(
            -1.0,
            1.0,
            num=model.window_frames * 52,
            dtype=np.float32,
        ).reshape(model.window_frames, 52)
        window = ActivityWindow(
            synthetic,
            first_sequence=1,
            last_sequence=model.window_frames,
            finished_at=utc_now(),
        )
        started = perf_counter()
        prediction = model.predict(window)
        elapsed_ms = (perf_counter() - started) * 1000
    except Exception as exc:
        print(f"행동 모델 점검 실패: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "model": str(model_path.resolve()),
                "modelVersion": prediction.model_version,
                "device": str(model.device),
                "inputShape": [model.window_frames, 52],
                "preprocessing": prediction.preprocessing_version,
                "syntheticPrediction": prediction.label,
                "scores": prediction.scores,
                "inferenceMilliseconds": round(elapsed_ms, 2),
                "note": "인공 입력 런타임 점검이며 실제 행동 정확도 평가가 아닙니다.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def export_features(args: argparse.Namespace) -> int:
    from .features import build_profile_feature_rows

    project_root = Path(args.project_root).resolve()
    rows = build_profile_feature_rows(project_root, args.profile_id)
    output_path = (
        Path(args.output).resolve()
        if args.output
        else project_root / "data" / "processed" / f"{args.profile_id}-features.csv"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        print("No valid sessions found for this profile.")
        return 1
    with output_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} session feature rows to {output_path}")
    return 0


def manage_dataset(args: argparse.Namespace) -> int:
    from .datasets import (
        attach_dataset_to_profile,
        detach_dataset_from_profile,
        export_profile_dataset,
        import_dataset_bundle,
        list_datasets,
    )
    from .profiles import load_profile

    project_root = Path(args.project_root).resolve()
    if args.command == "dataset-export":
        output = export_profile_dataset(
            project_root,
            args.profile_id,
            Path(args.output),
            display_name=args.name,
        )
        print(output)
        return 0
    if args.command == "dataset-import":
        dataset = import_dataset_bundle(project_root, Path(args.bundle))
        print(json.dumps(dataset, ensure_ascii=False, indent=2))
        return 0
    if args.command == "dataset-list":
        print(json.dumps(list_datasets(project_root), ensure_ascii=False, indent=2))
        return 0

    profile = load_profile(project_root, args.profile_id)
    if args.command == "dataset-attach":
        attach_dataset_to_profile(project_root, profile, args.dataset_id)
    else:
        detach_dataset_from_profile(project_root, profile, args.dataset_id)
    print(f"{args.command}: {args.dataset_id} -> {args.profile_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "ports":
        ports = available_ports()
        print(json.dumps(ports, ensure_ascii=False, indent=2))
        return 0 if ports else 1
    if args.command == "collect":
        return collect(args)
    if args.command == "monitor":
        from .monitor import run_monitor

        return run_monitor(
            args.port,
            args.baud,
            args.project_root,
            activity_model=args.activity_model,
            activity_hz=args.activity_hz,
            activity_window_frames=args.activity_window_frames,
            activity_tail_seconds=args.activity_tail_seconds,
            activity_fall_threshold=args.activity_fall_threshold,
            fusion_decision_threshold=args.fusion_decision_threshold,
            ml_direct_threshold=args.ml_direct_threshold,
        )
    if args.command == "fall-alert-test":
        return send_test_fall_alert(args)
    if args.command == "activity-model-check":
        return check_activity_model(args)
    if args.command == "features":
        return export_features(args)
    if args.command.startswith("dataset-"):
        return manage_dataset(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
