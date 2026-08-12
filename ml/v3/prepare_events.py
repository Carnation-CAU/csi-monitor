"""Convert gateway JSONL sessions into model-ready moving events.

This module intentionally lives below ml/ and does not import or modify gateway code.
The same pure transformation can be called for stored training sessions and inference
buffers, preventing training/serving preprocessing skew.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Iterable

import numpy as np

SCHEMA_VERSION = "ml-event-v1"
DEFAULT_OUTPUT = Path("ml/v3/output")
KNOWN_LABELS = {
    "empty_room", "standing_static", "walking_slow", "lie_down_slow",
    "lying_static", "turn_in_bed", "get_up_from_bed", "sit_down_fast",
    "pick_up_object", "fall_simulated_mattress",
}


@dataclass(frozen=True)
class SegmentConfig:
    max_moving_gap_seconds: float = 1.0
    pre_context_seconds: float = 1.5
    post_context_seconds: float = 2.0
    min_moving_samples: int = 2
    fixed_length: int = 64


@dataclass(frozen=True)
class RadarPoint:
    received_at: datetime
    sequence: int
    device_timestamp: str
    wander: float
    someone_threshold: float
    someone: bool
    jitter: float
    move_threshold: float
    moving: bool
    rssi: float | None = None
    packet_hz: float | None = None


@dataclass(frozen=True)
class ParsedSession:
    points: list[RadarPoint]
    total_records: int
    invalid_json_records: int
    invalid_timestamp_records: int
    invalid_radar_records: int
    radar_records: int
    link_records: int


@dataclass(frozen=True)
class EventBounds:
    context_start: int
    core_start: int
    core_end: int
    context_end: int


RADAR_MARKER = "RADAR_DADA,"
LINK_PATTERN = re.compile(r"esp_radar:.*?\brssi:\s*(-?\d+).*?\bfreq:\s*(\d+)Hz")


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_radar(raw: str, received_at: datetime, rssi: float | None,
                packet_hz: float | None) -> RadarPoint | None:
    marker = raw.find(RADAR_MARKER)
    if marker < 0:
        return None
    fields = raw[marker:].strip().split(",")
    if len(fields) != 11:
        return None
    try:
        return RadarPoint(
            received_at=received_at,
            sequence=int(fields[1]),
            device_timestamp=fields[2],
            wander=float(fields[3]),
            someone_threshold=float(fields[5]),
            someone=bool(int(fields[6])),
            jitter=float(fields[7]),
            move_threshold=float(fields[9]),
            moving=bool(int(fields[10])),
            rssi=rssi,
            packet_hz=packet_hz,
        )
    except ValueError:
        return None


def read_gateway_jsonl(path: Path) -> ParsedSession:
    points: list[RadarPoint] = []
    total = invalid_json = invalid_timestamp = invalid_radar = radar_records = link_records = 0
    latest_rssi: float | None = None
    latest_hz: float | None = None
    with path.open(encoding="utf-8-sig") as source:
        for line in source:
            if not line.strip():
                continue
            total += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                invalid_json += 1
                continue
            try:
                received_at = parse_utc(str(record["timestampUtc"]))
            except (KeyError, TypeError, ValueError):
                invalid_timestamp += 1
                continue
            raw = str(record.get("raw", ""))
            link = LINK_PATTERN.search(raw)
            if link is not None:
                latest_rssi = float(link.group(1))
                latest_hz = float(link.group(2))
                link_records += 1
            if RADAR_MARKER not in raw:
                continue
            radar_records += 1
            point = parse_radar(raw, received_at, latest_rssi, latest_hz)
            if point is None:
                invalid_radar += 1
            else:
                points.append(point)
    points.sort(key=lambda point: point.received_at)
    return ParsedSession(
        points=points, total_records=total, invalid_json_records=invalid_json,
        invalid_timestamp_records=invalid_timestamp, invalid_radar_records=invalid_radar,
        radar_records=radar_records, link_records=link_records,
    )


def seconds_between(first: datetime, second: datetime) -> float:
    return (second - first).total_seconds()


def segment_moving_events(points: list[RadarPoint], config: SegmentConfig) -> list[EventBounds]:
    if not points:
        return []
    moving_indices = [index for index, point in enumerate(points) if point.moving]
    if not moving_indices:
        return []

    groups: list[list[int]] = [[moving_indices[0]]]
    for index in moving_indices[1:]:
        previous = groups[-1][-1]
        gap = seconds_between(points[previous].received_at, points[index].received_at)
        if gap <= config.max_moving_gap_seconds:
            groups[-1].append(index)
        else:
            groups.append([index])

    events = []
    for group in groups:
        if len(group) < config.min_moving_samples:
            continue
        core_start, core_end = group[0], group[-1]
        start_time = points[core_start].received_at
        end_time = points[core_end].received_at
        context_start = core_start
        while (
            context_start > 0
            and seconds_between(points[context_start - 1].received_at, start_time)
            <= config.pre_context_seconds
        ):
            context_start -= 1
        context_end = core_end
        while (
            context_end + 1 < len(points)
            and seconds_between(end_time, points[context_end + 1].received_at)
            <= config.post_context_seconds
        ):
            context_end += 1
        events.append(EventBounds(context_start, core_start, core_end, context_end))
    return events


def relative(value: float, threshold: float) -> float:
    return value / threshold if abs(threshold) > 1e-12 else 0.0


def resample(times: np.ndarray, values: np.ndarray, length: int) -> np.ndarray:
    if not len(values):
        return np.zeros(length, dtype=float)
    if len(values) == 1 or times[-1] <= times[0]:
        return np.full(length, float(values[0]))
    target = np.linspace(times[0], times[-1], length)
    return np.interp(target, times, values)


def finite_fill(values: Iterable[float | None]) -> tuple[np.ndarray, float]:
    raw = np.asarray([np.nan if value is None else float(value) for value in values])
    available = np.isfinite(raw)
    ratio = float(available.mean()) if len(raw) else 0.0
    if not np.any(available):
        return np.zeros(len(raw), dtype=float), ratio
    filled = raw.copy()
    positions = np.arange(len(raw))
    filled[~available] = np.interp(positions[~available], positions[available], raw[available])
    return filled, ratio


def basic_stats(prefix: str, values: np.ndarray) -> dict[str, float]:
    if not len(values):
        return {f"{prefix}_{name}": 0.0 for name in (
            "mean", "std", "min", "max", "range", "p50", "p90", "p95",
        )}
    return {
        f"{prefix}_mean": float(values.mean()),
        f"{prefix}_std": float(values.std()),
        f"{prefix}_min": float(values.min()),
        f"{prefix}_max": float(values.max()),
        f"{prefix}_range": float(np.ptp(values)),
        f"{prefix}_p50": float(np.percentile(values, 50)),
        f"{prefix}_p90": float(np.percentile(values, 90)),
        f"{prefix}_p95": float(np.percentile(values, 95)),
    }


def temporal_features(signal: np.ndarray) -> dict[str, float]:
    delta = np.diff(signal)
    result = {
        "motion_abs_delta_mean": float(np.mean(np.abs(delta))) if len(delta) else 0.0,
        "motion_abs_delta_max": float(np.max(np.abs(delta))) if len(delta) else 0.0,
        "motion_rise_max": float(np.max(delta)) if len(delta) else 0.0,
        "motion_fall_max": float(-np.min(delta)) if len(delta) else 0.0,
    }
    threshold = float(signal.mean() + 0.5 * signal.std())
    peaks = [
        index for index in range(1, len(signal) - 1)
        if signal[index] > signal[index - 1]
        and signal[index] >= signal[index + 1]
        and signal[index] > threshold
    ]
    result["motion_peak_count"] = float(len(peaks))
    centered = signal - signal.mean()
    denominator = float(np.dot(centered, centered)) + 1e-12
    for lag in (4, 8, 16):
        result[f"motion_autocorrelation_lag_{lag}"] = (
            float(np.dot(centered[:-lag], centered[lag:]) / denominator)
            if len(signal) > lag else 0.0
        )
    spectrum = np.abs(np.fft.rfft(centered)) ** 2
    frequencies = np.fft.rfftfreq(len(centered))
    total = float(spectrum[1:].sum()) + 1e-12
    for name, low, high in (
        ("low", 0.0, 0.15), ("mid", 0.15, 0.30), ("high", 0.30, 0.501),
    ):
        mask = (frequencies >= low) & (frequencies < high)
        result[f"motion_spectral_{name}_ratio"] = float(spectrum[mask].sum() / total)
    for index, block in enumerate(np.array_split(signal, 8)):
        result[f"motion_block_{index:02d}"] = float(block.mean())
    return result


def target_label(label: str) -> str:
    if label == "walking_slow":
        return "walking"
    if label == "fall_simulated_mattress":
        return "fall_suspected"
    if label in KNOWN_LABELS:
        return "other_motion"
    return "unknown"


def make_event_record(
    *, points: list[RadarPoint], bounds: EventBounds, event_id: str,
    session_id: str, profile_id: str, source_file: str, label: str,
    event_at_utc: str | None, config: SegmentConfig,
) -> tuple[dict, dict[str, str | float | int]]:
    selected = points[bounds.context_start:bounds.context_end + 1]
    first = selected[0].received_at
    times = np.asarray([seconds_between(first, point.received_at) for point in selected])
    core_start_time = points[bounds.core_start].received_at
    core_end_time = points[bounds.core_end].received_at
    core_mask = np.asarray([
        core_start_time <= point.received_at <= core_end_time for point in selected
    ])
    post_mask = np.asarray([point.received_at > core_end_time for point in selected])

    wander = np.asarray([point.wander for point in selected], dtype=float)
    jitter = np.asarray([point.jitter for point in selected], dtype=float)
    wander_relative = np.asarray([
        relative(point.wander, point.someone_threshold) for point in selected
    ])
    jitter_relative = np.asarray([
        relative(point.jitter, point.move_threshold) for point in selected
    ])
    moving = np.asarray([float(point.moving) for point in selected])
    someone = np.asarray([float(point.someone) for point in selected])
    rssi, rssi_available_ratio = finite_fill(point.rssi for point in selected)
    packet_hz, packet_hz_available_ratio = finite_fill(point.packet_hz for point in selected)

    fixed = {
        "elapsed_fraction": np.linspace(0.0, 1.0, config.fixed_length).tolist(),
        "wander_relative": resample(times, wander_relative, config.fixed_length).tolist(),
        "jitter_relative": resample(times, jitter_relative, config.fixed_length).tolist(),
        "moving": resample(times, moving, config.fixed_length).tolist(),
        "someone": resample(times, someone, config.fixed_length).tolist(),
        "rssi": resample(times, rssi, config.fixed_length).tolist(),
    }
    motion_fixed = np.asarray(fixed["jitter_relative"])
    feature: dict[str, str | float | int] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "session_id": session_id,
        "profile_id": profile_id,
        "source_file": source_file,
        "original_label": label,
        "target_label": target_label(label),
        "context_started_at_utc": iso_utc(selected[0].received_at),
        "core_started_at_utc": iso_utc(core_start_time),
        "core_finished_at_utc": iso_utc(core_end_time),
        "context_finished_at_utc": iso_utc(selected[-1].received_at),
        "context_duration_seconds": seconds_between(selected[0].received_at, selected[-1].received_at),
        "core_duration_seconds": seconds_between(core_start_time, core_end_time),
        "radar_sample_count": len(selected),
        "core_sample_count": int(core_mask.sum()),
        "moving_sample_count": int(moving.sum()),
        "moving_ratio": float(moving.mean()),
        "someone_ratio": float(someone.mean()),
        "post_inactive_ratio": float(np.mean(moving[post_mask] == 0)) if np.any(post_mask) else 0.0,
        "post_context_seconds": seconds_between(core_end_time, selected[-1].received_at),
        "rssi_available_ratio": rssi_available_ratio,
        "packet_hz_available_ratio": packet_hz_available_ratio,
        "rssi_mean": float(rssi.mean()) if len(rssi) else 0.0,
        "rssi_std": float(rssi.std()) if len(rssi) else 0.0,
        "packet_hz_mean": float(packet_hz.mean()) if len(packet_hz) else 0.0,
    }
    intervals = np.diff(times)
    feature.update({
        "sample_interval_median_seconds": float(median(intervals)) if len(intervals) else 0.0,
        "sample_interval_p95_seconds": float(np.percentile(intervals, 95)) if len(intervals) else 0.0,
        "sample_gap_max_seconds": float(intervals.max()) if len(intervals) else 0.0,
    })
    for prefix, values in (
        ("wander", wander), ("jitter", jitter),
        ("wander_relative", wander_relative), ("jitter_relative", jitter_relative),
    ):
        feature.update(basic_stats(prefix, values))
    feature.update(temporal_features(motion_fixed))
    feature.update({
        "pre_jitter_relative_mean": float(jitter_relative[~core_mask & ~post_mask].mean())
        if np.any(~core_mask & ~post_mask) else 0.0,
        "core_jitter_relative_mean": float(jitter_relative[core_mask].mean()),
        "post_jitter_relative_mean": float(jitter_relative[post_mask].mean())
        if np.any(post_mask) else 0.0,
    })

    cue_offset: float | None = None
    if event_at_utc:
        try:
            cue_offset = seconds_between(core_start_time, parse_utc(event_at_utc))
        except ValueError:
            cue_offset = None
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "eventId": event_id,
        "sessionId": session_id,
        "profileId": profile_id,
        "sourceFile": source_file,
        "originalLabel": label,
        "targetLabel": target_label(label),
        "trigger": "radar_moving",
        "contextStartedAtUtc": feature["context_started_at_utc"],
        "coreStartedAtUtc": feature["core_started_at_utc"],
        "coreFinishedAtUtc": feature["core_finished_at_utc"],
        "contextFinishedAtUtc": feature["context_finished_at_utc"],
        "actionCueOffsetFromCoreSeconds": cue_offset,
        "features": {
            key: value for key, value in feature.items()
            if key not in {
                "schema_version", "event_id", "session_id", "profile_id", "source_file",
                "original_label", "target_label", "context_started_at_utc",
                "core_started_at_utc", "core_finished_at_utc", "context_finished_at_utc",
            }
        },
        "fixedLengthSignals": fixed,
    }
    return record, feature


def prepare_session(
    raw_path: Path, manifest: dict, config: SegmentConfig
) -> tuple[list[dict], list[dict], dict]:
    parsed = read_gateway_jsonl(raw_path)
    bounds = segment_moving_events(parsed.points, config)
    session_id = str(manifest.get("sessionId") or raw_path.stem)
    profile_id = str(manifest.get("profileId") or "unknown")
    label = str(manifest.get("label") or "unlabeled")
    event_at = manifest.get("eventAtUtc")
    records, features = [], []
    for number, event_bounds in enumerate(bounds, start=1):
        event_id = f"{session_id}-e{number:04d}"
        record, feature = make_event_record(
            points=parsed.points, bounds=event_bounds, event_id=event_id,
            session_id=session_id, profile_id=profile_id,
            source_file=raw_path.as_posix(), label=label,
            event_at_utc=str(event_at) if event_at else None, config=config,
        )
        records.append(record)
        features.append(feature)
    diagnostic = {
        "sessionId": session_id, "rawFile": raw_path.as_posix(), "label": label,
        "targetLabel": target_label(label), "events": len(records),
        "totalRecords": parsed.total_records, "radarRecords": parsed.radar_records,
        "parsedRadarRecords": len(parsed.points), "linkRecords": parsed.link_records,
        "invalidJsonRecords": parsed.invalid_json_records,
        "invalidTimestampRecords": parsed.invalid_timestamp_records,
        "invalidRadarRecords": parsed.invalid_radar_records,
    }
    return records, features, diagnostic


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def write_feature_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def discover_valid_sessions(project_root: Path) -> list[tuple[Path, dict]]:
    sessions = []
    manifest_root = project_root / "data" / "manifests"
    for manifest_path in sorted(manifest_root.glob("*.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if manifest.get("valid") is not True or manifest.get("label") == "unlabeled":
            continue
        raw_file = manifest.get("rawFile")
        if not raw_file:
            continue
        raw_path = project_root / str(raw_file)
        if raw_path.is_file():
            sessions.append((raw_path, manifest))
    return sessions


def run(project_root: Path, output: Path, config: SegmentConfig) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    events: list[dict] = []
    features: list[dict] = []
    diagnostics: list[dict] = []
    sessions = discover_valid_sessions(project_root)
    for raw_path, manifest in sessions:
        new_events, new_features, diagnostic = prepare_session(raw_path, manifest, config)
        events.extend(new_events)
        features.extend(new_features)
        diagnostics.append(diagnostic)
    write_jsonl(output / "events.jsonl", events)
    write_feature_csv(output / "features.csv", features)
    summary = {
        "schemaVersion": SCHEMA_VERSION,
        "projectRoot": project_root.resolve().as_posix(),
        "config": asdict(config),
        "sessions": len(sessions), "events": len(events),
        "eventsByTargetLabel": dict(Counter(row["targetLabel"] for row in events)),
        "sessionsWithoutMovingEvents": sum(row["events"] == 0 for row in diagnostics),
        "diagnostics": diagnostics,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-moving-gap", type=float, default=1.0)
    parser.add_argument("--pre-context", type=float, default=1.5)
    parser.add_argument("--post-context", type=float, default=2.0)
    parser.add_argument("--min-moving-samples", type=int, default=2)
    parser.add_argument("--fixed-length", type=int, default=64)
    args = parser.parse_args()
    config = SegmentConfig(
        max_moving_gap_seconds=args.max_moving_gap,
        pre_context_seconds=args.pre_context,
        post_context_seconds=args.post_context,
        min_moving_samples=args.min_moving_samples,
        fixed_length=args.fixed_length,
    )
    summary = run(args.project_root, args.output, config)
    print(
        f"sessions={summary['sessions']}, events={summary['events']}, "
        f"sessions_without_events={summary['sessionsWithoutMovingEvents']}"
    )
    print(f"output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
