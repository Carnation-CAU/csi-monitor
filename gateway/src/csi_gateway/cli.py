from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from uuid import uuid4

SCHEMA_VERSION = "1.0.0"


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


def create_session_paths(root: Path, session_id: str) -> tuple[Path, Path]:
    raw_dir = root / "data" / "raw"
    manifest_dir = root / "data" / "manifests"
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir / f"{session_id}.jsonl", manifest_dir / f"{session_id}.json"


def build_record(
    *,
    session_id: str,
    sample_id: int,
    device_id: str,
    raw_line: bytes,
    label: str,
) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sessionId": session_id,
        "sampleId": sample_id,
        "timestampUtc": utc_now(),
        "deviceId": device_id,
        "label": label,
        "encoding": "utf-8-replace",
        "raw": raw_line.decode("utf-8", errors="replace").rstrip("\r\n"),
    }


def write_json_line(file_handle, record: dict[str, object]) -> None:
    file_handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    file_handle.flush()


def collect(args: argparse.Namespace) -> int:
    from serial import Serial

    project_root = Path(args.project_root).resolve()
    session_id = args.session_id or (
        datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    )
    raw_path, manifest_path = create_session_paths(project_root, session_id)
    started_at = utc_now()
    sample_count = 0
    deadline = monotonic() + args.duration if args.duration else None

    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "sessionId": session_id,
        "startedAtUtc": started_at,
        "finishedAtUtc": None,
        "deviceId": args.device_id,
        "roomId": args.room_id,
        "label": args.label,
        "serialPort": args.port,
        "baudRate": args.baud,
        "platform": platform.platform(),
        "pythonVersion": platform.python_version(),
        "sampleCount": 0,
        "rawFile": raw_path.relative_to(project_root).as_posix(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Collecting {args.port} -> {raw_path}")
    try:
        with Serial(args.port, args.baud, timeout=1) as serial_port:
            with raw_path.open("w", encoding="utf-8", newline="\n") as output:
                while deadline is None or monotonic() < deadline:
                    raw_line = serial_port.readline()
                    if not raw_line:
                        continue
                    sample_count += 1
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
    collect_parser.add_argument("--baud", type=int, default=921600)
    collect_parser.add_argument("--duration", type=float, default=0)
    collect_parser.add_argument("--session-id")
    collect_parser.add_argument("--device-id", default="rx-s3-001")
    collect_parser.add_argument("--room-id", default="room-01")
    collect_parser.add_argument("--label", default="unlabeled")
    collect_parser.add_argument("--project-root", default=".")

    monitor_parser = subparsers.add_parser(
        "monitor", help="Show a live movement monitor"
    )
    monitor_parser.add_argument("--port", required=True)
    monitor_parser.add_argument("--baud", type=int, default=2_000_000)
    monitor_parser.add_argument("--project-root", default=".")

    features_parser = subparsers.add_parser(
        "features", help="Build session-level Radar features"
    )
    features_parser.add_argument("--profile-id", required=True)
    features_parser.add_argument("--project-root", default=".")
    features_parser.add_argument("--output")
    return parser


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

        return run_monitor(args.port, args.baud, args.project_root)
    if args.command == "features":
        return export_features(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
