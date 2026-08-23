from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean

from .radar import LinkSample, RadarSample


COLLECTION_LABELS = [
    "walk",
    "fall",
    "run",
    "jump",
    "squat",
    "arm_wave",
    "turn",
    "empty_room",
    "standing_static",
    "walking_slow",
    "lie_down_slow",
    "lying_static",
    "turn_in_bed",
    "get_up_from_bed",
    "sit_down_fast",
    "pick_up_object",
    "fall_simulated_mattress",
]
TRANSITION_LABELS = {
    "fall",
    "jump",
    "squat",
    "turn",
    "lie_down_slow",
    "get_up_from_bed",
    "sit_down_fast",
    "pick_up_object",
    "fall_simulated_mattress",
}
FALL_LABELS = {"fall", "fall_simulated_mattress"}
UNLABELED = "unlabeled"
LABEL_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
CUSTOM_LABELS_FILE = Path("data") / "collection-labels.json"


def is_valid_collection_label(label: object) -> bool:
    """Return whether a label is safe for metadata and a raw-data folder name."""
    return isinstance(label, str) and LABEL_PATTERN.fullmatch(label) is not None


def load_collection_labels(project_root: Path) -> list[str]:
    """Load built-in labels followed by locally configured custom labels."""
    labels = list(COLLECTION_LABELS)
    path = project_root / CUSTOM_LABELS_FILE
    if not path.is_file():
        return labels
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return labels
    custom_labels = payload.get("labels", []) if isinstance(payload, dict) else []
    if not isinstance(custom_labels, list):
        return labels
    for label in custom_labels:
        if is_valid_collection_label(label) and label not in labels:
            labels.append(label)
    return labels


def add_custom_collection_label(project_root: Path, label: str) -> list[str]:
    """Persist one custom label and return the complete collection-label list."""
    normalized = label.strip().lower()
    if not is_valid_collection_label(normalized) or normalized == UNLABELED:
        raise ValueError(
            "행동 라벨은 영문 소문자로 시작하고 영문 소문자, 숫자, 밑줄만 "
            "사용해 64자 이내로 입력하세요."
        )
    labels = load_collection_labels(project_root)
    if normalized in labels:
        return labels
    custom_labels = [item for item in labels if item not in COLLECTION_LABELS]
    custom_labels.append(normalized)
    path = project_root / CUSTOM_LABELS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"schemaVersion": "1.0.0", "labels": custom_labels},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return load_collection_labels(project_root)


@dataclass(frozen=True)
class CollectionLabelDecision:
    label: str
    confirmed: bool
    corrected: bool
    invalid_reason: str | None


def finalize_collection_label(
    *,
    planned_label: str | None,
    actual_label: str | None,
    safety_confirmed: bool,
    available_labels: list[str] | None = None,
) -> CollectionLabelDecision:
    """수집 종료 후 실제 행동 라벨과 유효성 정책을 결정한다."""
    labels = available_labels if available_labels is not None else COLLECTION_LABELS
    if planned_label is not None and planned_label not in labels:
        raise ValueError(f"지원하지 않는 예정 라벨: {planned_label}")
    if actual_label is None:
        return CollectionLabelDecision(
            label=UNLABELED,
            confirmed=False,
            corrected=False,
            invalid_reason="실제 행동 라벨 미확정",
        )
    if actual_label not in labels:
        raise ValueError(f"지원하지 않는 실제 라벨: {actual_label}")

    invalid_reason = None
    if actual_label in FALL_LABELS and not safety_confirmed:
        invalid_reason = "사전 안전 확인 없이 모의 낙상 라벨 선택"

    return CollectionLabelDecision(
        label=actual_label,
        confirmed=True,
        corrected=planned_label is not None and planned_label != actual_label,
        invalid_reason=invalid_reason,
    )


@dataclass(frozen=True)
class CollectionSummary:
    radar_count: int
    moving_count: int
    moving_ratio: float
    average_jitter: float | None
    maximum_jitter: float | None
    average_rssi: float | None
    average_hz: float | None
    minimum_hz: int | None


def summarize_collection(
    radar_samples: list[RadarSample], link_samples: list[LinkSample]
) -> CollectionSummary:
    moving_count = sum(sample.moving for sample in radar_samples)
    jitters = [sample.jitter for sample in radar_samples]
    rssis = [sample.rssi for sample in link_samples]
    frequencies = [sample.frequency_hz for sample in link_samples]
    return CollectionSummary(
        radar_count=len(radar_samples),
        moving_count=moving_count,
        moving_ratio=(100 * moving_count / len(radar_samples)) if radar_samples else 0.0,
        average_jitter=fmean(jitters) if jitters else None,
        maximum_jitter=max(jitters) if jitters else None,
        average_rssi=fmean(rssis) if rssis else None,
        average_hz=fmean(frequencies) if frequencies else None,
        minimum_hz=min(frequencies) if frequencies else None,
    )


def render_korean_summary(
    *,
    session_id: str,
    label: str,
    duration_seconds: int,
    valid: bool,
    event_at_utc: str | None,
    channel: int | None,
    summary: CollectionSummary,
    raw_file: str,
    manifest_file: str,
) -> str:
    def number(value: float | int | None, digits: int = 1) -> str:
        if value is None:
            return "기록 없음"
        return f"{value:.{digits}f}" if isinstance(value, float) else str(value)

    return f"""# 행동 수집 결과: {label}

## 세션

- 세션 ID: `{session_id}`
- 라벨: `{label}`
- 수집 시간: {duration_seconds}초
- 유효 여부: {"유효" if valid else "무효"}
- Wi-Fi 채널: {channel if channel is not None else "확인 안 됨"}
- 행동 신호 시각(UTC): {event_at_utc or "사용 안 함"}

## 자동 요약

| 지표 | 값 |
|---|---:|
| Radar 표본 | {summary.radar_count}개 |
| 움직임 판정 | {summary.moving_count}개 |
| 움직임 판정 비율 | {number(summary.moving_ratio)}% |
| 평균 jitter | {number(summary.average_jitter, 6)} |
| 최대 jitter | {number(summary.maximum_jitter, 6)} |
| 평균 RSSI | {number(summary.average_rssi)}dBm |
| 평균 패킷률 | {number(summary.average_hz)}Hz |
| 최저 패킷률 | {number(summary.minimum_hz)}Hz |

이 결과는 해당 세션의 자동 요약이며 모델 정확도를 의미하지 않는다.

## 파일

- 원본: `{raw_file}`
- 세션 정보: `{manifest_file}`
"""
