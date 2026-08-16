from __future__ import annotations

import json
from pathlib import Path
from statistics import fmean, pstdev

from .collection import COLLECTION_LABELS
from .datasets import dataset_path, load_dataset
from .profiles import load_profile
from .radar import LinkSample, RadarSample, parse_link_line, parse_radar_line


def _mean(values: list[float]) -> float:
    return fmean(values) if values else 0.0


def _std(values: list[float]) -> float:
    return pstdev(values) if len(values) > 1 else 0.0


def _relative(value: float, threshold: float) -> float:
    return value / threshold if abs(threshold) > 1e-12 else 0.0


def extract_radar_features(
    radar_samples: list[RadarSample],
    link_samples: list[LinkSample] | None = None,
) -> dict[str, float]:
    """세션 파일과 실시간 창이 공유하는 행동 특징을 계산한다."""
    link_samples = link_samples or []
    wanders = [sample.wander for sample in radar_samples]
    jitters = [sample.jitter for sample in radar_samples]
    relative_wanders = [
        _relative(sample.wander, sample.someone_threshold)
        for sample in radar_samples
    ]
    relative_jitters = [
        _relative(sample.jitter, sample.move_threshold) for sample in radar_samples
    ]
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
        "wander_relative_mean": _mean(relative_wanders),
        "wander_relative_std": _std(relative_wanders),
        "wander_relative_max": max(relative_wanders, default=0.0),
        "jitter_relative_mean": _mean(relative_jitters),
        "jitter_relative_std": _std(relative_jitters),
        "jitter_relative_max": max(relative_jitters, default=0.0),
        "moving_ratio": _mean([float(sample.moving) for sample in radar_samples]),
        "someone_ratio": _mean([float(sample.someone) for sample in radar_samples]),
        "first_half_jitter_mean": _mean(jitters[:midpoint]),
        "second_half_jitter_mean": _mean(jitters[midpoint:]),
        "first_half_jitter_relative_mean": _mean(relative_jitters[:midpoint]),
        "second_half_jitter_relative_mean": _mean(relative_jitters[midpoint:]),
        "rssi_mean": _mean(rssis),
        "rssi_std": _std(rssis),
        "packet_hz_mean": _mean(frequencies),
        "packet_hz_min": min(frequencies, default=0.0),
    }


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
    return extract_radar_features(radar_samples, link_samples)


def build_dataset_feature_rows(
    project_root: Path, dataset_id: str
) -> list[dict[str, str | float | bool]]:
    dataset = load_dataset(project_root, dataset_id)
    root = dataset_path(project_root, dataset_id)
    rows: list[dict[str, str | float | bool]] = []
    for session in dataset.get("sessions", []):
        raw_path = root / str(session["rawPath"])
        if not raw_path.is_file() or session.get("label") not in COLLECTION_LABELS:
            continue
        rows.append(
            {
                "session_id": str(session["sessionId"]),
                "profile_id": str(dataset.get("sourceProfileId", "unknown")),
                "source_profile_id": str(dataset.get("sourceProfileId", "unknown")),
                "dataset_id": dataset_id,
                "reference": True,
                "label": str(session["label"]),
                **extract_session_features(raw_path),
            }
        )
    return rows


def build_profile_feature_rows(
    project_root: Path, profile_id: str
) -> list[dict[str, str | float | bool]]:
    rows: list[dict[str, str | float | bool]] = []
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
                "source_profile_id": profile_id,
                "dataset_id": "native",
                "reference": False,
                "label": str(manifest.get("label", "unlabeled")),
                **extract_session_features(raw_path),
            }
        )
    profile = load_profile(project_root, profile_id)
    for reference in profile.get("referenceDatasets", []):
        dataset_id = str(reference.get("datasetId", ""))
        if not dataset_id:
            continue
        try:
            rows.extend(build_dataset_feature_rows(project_root, dataset_id))
        except FileNotFoundError:
            continue
    return rows


def build_current_calibration_presence_rows(
    project_root: Path, profile_id: str
) -> list[dict[str, str | float | bool]]:
    """현재 공간 보정 이후 수집한 로컬 빈방·정지 재실 특징만 반환한다."""
    profile = load_profile(project_root, profile_id)
    calibration = profile.get("calibration") or {}
    calibrated_at = str(calibration.get("calibratedAtUtc", ""))
    if not calibrated_at or profile.get("needsCalibration", True):
        return []

    rows: list[dict[str, str | float | bool]] = []
    allowed_labels = {"empty_room", "standing_static", "lying_static"}
    for manifest_path in sorted((project_root / "data" / "manifests").glob("*.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("profileId") != profile_id or manifest.get("valid") is not True:
            continue
        if manifest.get("label") not in allowed_labels:
            continue
        if str(manifest.get("startedAtUtc", "")) < calibrated_at:
            continue
        raw_file = manifest.get("rawFile")
        if not raw_file:
            continue
        raw_path = project_root / str(raw_file)
        if not raw_path.is_file():
            continue
        rows.append(
            {
                "session_id": str(manifest["sessionId"]),
                "profile_id": profile_id,
                "source_profile_id": profile_id,
                "dataset_id": "native",
                "reference": False,
                "label": str(manifest["label"]),
                **extract_session_features(raw_path),
            }
        )
    return rows
