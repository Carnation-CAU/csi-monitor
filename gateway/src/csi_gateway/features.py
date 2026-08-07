from __future__ import annotations

import json
from pathlib import Path
from statistics import fmean, pstdev

from .collection import COLLECTION_LABELS
from .radar import parse_link_line, parse_radar_line


def _mean(values: list[float]) -> float:
    return fmean(values) if values else 0.0


def _std(values: list[float]) -> float:
    return pstdev(values) if len(values) > 1 else 0.0


def extract_session_features(raw_path: Path) -> dict[str, float]:
    radar_samples = []
    link_samples = []
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        raw = str(record.get("raw", ""))
        radar = parse_radar_line(raw)
        if radar is not None:
            radar_samples.append(radar)
        link = parse_link_line(raw)
        if link is not None:
            link_samples.append(link)

    wanders = [sample.wander for sample in radar_samples]
    jitters = [sample.jitter for sample in radar_samples]
    rssis = [float(sample.rssi) for sample in link_samples]
    frequencies = [float(sample.frequency_hz) for sample in link_samples]
    midpoint = len(jitters) // 2
    return {
        "radar_count": float(len(radar_samples)),
        "wander_mean": _mean(wanders),
        "wander_std": _std(wanders),
        "wander_max": max(wanders, default=0.0),
        "jitter_mean": _mean(jitters),
        "jitter_std": _std(jitters),
        "jitter_max": max(jitters, default=0.0),
        "moving_ratio": _mean([float(sample.moving) for sample in radar_samples]),
        "someone_ratio": _mean([float(sample.someone) for sample in radar_samples]),
        "first_half_jitter_mean": _mean(jitters[:midpoint]),
        "second_half_jitter_mean": _mean(jitters[midpoint:]),
        "rssi_mean": _mean(rssis),
        "rssi_std": _std(rssis),
        "packet_hz_mean": _mean(frequencies),
        "packet_hz_min": min(frequencies, default=0.0),
    }


def build_profile_feature_rows(
    project_root: Path, profile_id: str
) -> list[dict[str, str | float]]:
    rows: list[dict[str, str | float]] = []
    for manifest_path in sorted((project_root / "data" / "manifests").glob("*.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("profileId") != profile_id or manifest.get("valid") is False:
            continue
        if manifest.get("label") not in COLLECTION_LABELS:
            continue
        raw_file = manifest.get("rawFile")
        if not raw_file:
            continue
        raw_path = project_root / str(raw_file)
        if not raw_path.exists():
            continue
        rows.append(
            {
                "session_id": str(manifest["sessionId"]),
                "profile_id": profile_id,
                "label": str(manifest.get("label", "unlabeled")),
                **extract_session_features(raw_path),
            }
        )
    return rows
