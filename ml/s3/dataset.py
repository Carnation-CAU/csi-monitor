"""ESP32-S3 session loader and physically bounded CSI window preprocessing."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from csi_gateway.collection import FALL_LABELS
from csi_gateway.csi import parse_csi_line


def _epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


@dataclass(frozen=True)
class WindowConfig:
    sample_rate_hz: float = 100.0
    pre_event_seconds: float = 2.0
    post_event_seconds: float = 3.0
    stride_seconds: float = 0.25
    positive_alignment_seconds: float = 0.75
    use_phase: bool = True

    @property
    def frames(self) -> int:
        return int(round((self.pre_event_seconds + self.post_event_seconds) * self.sample_rate_hz))

    @property
    def stride_frames(self) -> int:
        return max(1, int(round(self.stride_seconds * self.sample_rate_hz)))


@dataclass(frozen=True)
class SessionMetadata:
    session_id: str
    label: str
    room_id: str
    person_id: str
    position_id: str
    activity_id: str
    device_id: str
    device_family: str
    channel: int
    bandwidth: str
    raw_path: str
    event_at_seconds: float | None

    @property
    def is_fall(self) -> bool:
        return self.label in FALL_LABELS or self.label.startswith("fall_")


@dataclass(frozen=True)
class S3Session:
    metadata: SessionMetadata
    timestamps: np.ndarray
    amplitude: np.ndarray
    phase: np.ndarray
    valid_mask: np.ndarray
    rssi: np.ndarray
    noise_floor: np.ndarray


@dataclass(frozen=True)
class S3Window:
    features: np.ndarray  # channels x time x subcarrier
    is_fall: bool
    session_id: str
    room_id: str
    person_id: str
    position_id: str
    channel: int
    label: str
    start_seconds: float
    event_at_seconds: float | None


def _manifest_metadata(manifest: dict[str, object], raw_path: Path) -> SessionMetadata:
    event = manifest.get("eventAtUtc")
    started = manifest.get("startedAtUtc")
    event_offset = None
    if event and started:
        event_offset = _epoch(str(event)) - _epoch(str(started))
    device_id = str(manifest.get("deviceId") or "unknown")
    family = str(manifest.get("deviceFamily") or ("ESP32-S3" if "s3" in device_id.lower() else "unknown"))
    return SessionMetadata(
        session_id=str(manifest["sessionId"]),
        label=str(manifest.get("label") or "unlabeled"),
        room_id=str(manifest.get("roomId") or "unknown"),
        person_id=str(manifest.get("personId") or "unknown"),
        position_id=str(manifest.get("positionId") or "unknown"),
        activity_id=str(manifest.get("activityId") or manifest.get("label") or "unknown"),
        device_id=device_id,
        device_family=family,
        channel=int(manifest.get("channel") or 0),
        bandwidth=str(manifest.get("bandwidth") or manifest.get("configuredBandwidth") or "HT20"),
        raw_path=raw_path.as_posix(),
        event_at_seconds=event_offset,
    )


def load_s3_session(project_root: Path, manifest_path: Path) -> S3Session | None:
    """Load lossless IQ from one valid S3 manifest; never substitutes Radar features."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if manifest.get("valid") is not True or not manifest.get("rawFile"):
        return None
    raw_path = project_root / str(manifest["rawFile"])
    if not raw_path.is_file():
        return None
    metadata = _manifest_metadata(manifest, raw_path.relative_to(project_root))
    if metadata.device_family.lower() not in {"esp32-s3", "s3"}:
        return None

    times: list[float] = []
    amplitudes: list[np.ndarray] = []
    phases: list[np.ndarray] = []
    masks: list[np.ndarray] = []
    rssis: list[float] = []
    noises: list[float] = []
    origin: float | None = None
    for line in raw_path.open(encoding="utf-8-sig", errors="replace"):
        try:
            record = json.loads(line)
            received_at = _epoch(str(record["timestampUtc"]))
            sample = parse_csi_line(str(record.get("raw", "")))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        if sample is None or sample.iq.shape != (52, 2):
            continue
        if origin is None:
            origin = received_at
        times.append(received_at - origin)
        amplitudes.append(sample.amplitude.astype(np.float32))
        phases.append(sample.phase.astype(np.float32))
        masks.append(sample.valid_subcarrier_mask.astype(bool))
        rssis.append(float(sample.rssi))
        noises.append(float(sample.noise_floor))
    if len(times) < 2:
        return None
    # Manifest event time is relative to startedAtUtc; align it to the first CSI.
    if metadata.event_at_seconds is not None and origin is not None:
        started_epoch = _epoch(str(manifest["startedAtUtc"]))
        metadata = SessionMetadata(
            **{
                **metadata.__dict__,
                "event_at_seconds": metadata.event_at_seconds - (origin - started_epoch),
            }
        )
    return S3Session(
        metadata=metadata,
        timestamps=np.asarray(times, dtype=np.float64),
        amplitude=np.stack(amplitudes),
        phase=np.stack(phases),
        valid_mask=np.stack(masks),
        rssi=np.asarray(rssis, dtype=np.float32),
        noise_floor=np.asarray(noises, dtype=np.float32),
    )


def discover_s3_sessions(project_root: Path) -> tuple[list[S3Session], list[dict[str, str]]]:
    sessions: list[S3Session] = []
    skipped: list[dict[str, str]] = []
    manifest_root = project_root / "data" / "manifests"
    for path in sorted(manifest_root.glob("*.json")):
        session = load_s3_session(project_root, path)
        if session is None:
            skipped.append({"manifest": path.name, "reason": "invalid_missing_or_non_s3_iq"})
        else:
            sessions.append(session)
    return sessions, skipped


def _interpolate_matrix(
    times: np.ndarray,
    values: np.ndarray,
    target: np.ndarray,
    *,
    unwrap_phase: bool = False,
) -> np.ndarray:
    result = np.empty((len(target), values.shape[1]), dtype=np.float32)
    for carrier in range(values.shape[1]):
        column = values[:, carrier]
        finite = np.isfinite(column)
        if np.count_nonzero(finite) < 2:
            result[:, carrier] = 0.0
        else:
            source = column[finite]
            if unwrap_phase:
                source = np.unwrap(source)
            result[:, carrier] = np.interp(target, times[finite], source)
    return result


def preprocess_session(session: S3Session, config: WindowConfig) -> tuple[np.ndarray, np.ndarray]:
    """Resample and return change-centered channels plus the fixed time axis."""
    start = float(session.timestamps[0])
    stop = float(session.timestamps[-1])
    target = np.arange(start, stop + 0.5 / config.sample_rate_hz, 1.0 / config.sample_rate_hz)
    valid = session.valid_mask.astype(bool)
    amplitude = np.where(valid, session.amplitude, np.nan)
    per_packet_scale = np.nanmedian(amplitude, axis=1, keepdims=True)
    relative = amplitude / np.maximum(per_packet_scale, 1e-6)
    aligned = _interpolate_matrix(session.timestamps, relative, target)

    event_at = session.metadata.event_at_seconds
    baseline_stop = (event_at - config.pre_event_seconds) if event_at is not None else start + 5.0
    baseline = aligned[target <= baseline_stop]
    if len(baseline) < int(config.sample_rate_hz):
        baseline = aligned[: min(len(aligned), int(config.sample_rate_hz * 5))]
    center = np.median(baseline, axis=0, keepdims=True)
    scale = np.maximum(1.4826 * np.median(np.abs(baseline - center), axis=0, keepdims=True), 0.02)
    normalized = np.clip((aligned - center) / scale, -12.0, 12.0)
    delta = np.diff(normalized, axis=0, prepend=normalized[:1])
    delta2 = np.diff(delta, axis=0, prepend=delta[:1])

    channels = [normalized, delta, delta2]
    if config.use_phase:
        phase = np.where(valid, session.phase, np.nan)
        phase_unwrapped = _interpolate_matrix(
            session.timestamps, phase, target, unwrap_phase=True
        )
        phase_unwrapped -= np.median(phase_unwrapped, axis=1, keepdims=True)
        phase_delta = np.diff(phase_unwrapped, axis=0, prepend=phase_unwrapped[:1])
        channels.append(np.clip(phase_delta, -np.pi, np.pi))
    return np.stack(channels).astype(np.float32), target


def build_windows(session: S3Session, config: WindowConfig = WindowConfig()) -> list[S3Window]:
    features, times = preprocess_session(session, config)
    if features.shape[1] < config.frames:
        return []
    windows: list[S3Window] = []
    event = session.metadata.event_at_seconds
    for first in range(0, features.shape[1] - config.frames + 1, config.stride_frames):
        start = float(times[first])
        impact_alignment = start + config.pre_event_seconds
        is_positive = event is not None and abs(impact_alignment - event) <= config.positive_alignment_seconds
        # Do not teach windows close to a known fall as negatives. They contain
        # transition/recovery signal even when the nominal impact is misaligned.
        if event is not None and not is_positive and start - 1.0 <= event <= start + config.pre_event_seconds + config.post_event_seconds + 1.0:
            continue
        windows.append(
            S3Window(
                features=features[:, first : first + config.frames].copy(),
                is_fall=is_positive,
                session_id=session.metadata.session_id,
                room_id=session.metadata.room_id,
                person_id=session.metadata.person_id,
                position_id=session.metadata.position_id,
                channel=session.metadata.channel,
                label=session.metadata.label,
                start_seconds=start,
                event_at_seconds=event,
            )
        )
    return windows


def augment_window(
    features: np.ndarray,
    rng: np.random.Generator,
    *,
    max_packet_dropout: float = 0.05,
    max_subcarrier_dropout: float = 0.10,
) -> np.ndarray:
    """Apply bounded RF-like variation without changing the physical event order."""
    x = np.asarray(features, dtype=np.float32).copy()
    x *= float(rng.uniform(0.90, 1.10))
    x += rng.normal(0.0, rng.uniform(0.0, 0.03), size=x.shape).astype(np.float32)
    x[0] += float(rng.uniform(-0.10, 0.10))
    packet_count = int(x.shape[1] * rng.uniform(0.0, max_packet_dropout))
    if packet_count:
        indices = rng.choice(x.shape[1], packet_count, replace=False)
        for index in indices:
            left = max(0, index - 1)
            right = min(x.shape[1] - 1, index + 1)
            x[:, index] = (x[:, left] + x[:, right]) * 0.5
    carrier_count = int(x.shape[2] * rng.uniform(0.0, max_subcarrier_dropout))
    if carrier_count:
        carriers = rng.choice(x.shape[2], carrier_count, replace=False)
        x[:, :, carriers] = 0.0
    shift = int(rng.integers(-max(1, x.shape[1] // 50), max(2, x.shape[1] // 50 + 1)))
    if shift:
        x = np.roll(x, shift, axis=1)
        x[:, : max(shift, 0)] = 0.0
        if shift < 0:
            x[:, shift:] = 0.0
    return x


def dataset_inventory(sessions: Sequence[S3Session]) -> dict[str, object]:
    falls = [session for session in sessions if session.metadata.is_fall]
    known = lambda values: sorted(
        {
            value
            for value in values
            if value and not value.lower().startswith("unknown")
        }
    )
    return {
        "sessionCount": len(sessions),
        "fallEventCount": len(falls),
        "nonFallSessionCount": len(sessions) - len(falls),
        "rooms": known(session.metadata.room_id for session in sessions),
        "people": known(session.metadata.person_id for session in sessions),
        "positions": known(session.metadata.position_id for session in sessions),
        "channels": sorted({session.metadata.channel for session in sessions if session.metadata.channel}),
        "labels": known(session.metadata.label for session in sessions),
    }


def validate_training_inventory(
    inventory: dict[str, object],
    *,
    min_fall_events: int = 20,
    min_rooms: int = 3,
    min_people: int = 3,
    min_channels: int = 2,
) -> list[str]:
    """Return blockers; callers must not publish metrics while blockers remain."""
    blockers: list[str] = []
    checks = (
        (int(inventory["fallEventCount"]), min_fall_events, "fall events"),
        (len(inventory["rooms"]), min_rooms, "known rooms"),
        (len(inventory["people"]), min_people, "known people"),
        (len(inventory["channels"]), min_channels, "channels"),
    )
    for actual, required, label in checks:
        if actual < required:
            blockers.append(f"{label}: {actual} < required {required}")
    if int(inventory["nonFallSessionCount"]) < 1:
        blockers.append("non-fall sessions: none")
    return blockers
