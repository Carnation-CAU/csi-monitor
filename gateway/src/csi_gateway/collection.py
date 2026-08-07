from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from .radar import LinkSample, RadarSample


COLLECTION_LABELS = [
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
    "lie_down_slow",
    "get_up_from_bed",
    "sit_down_fast",
    "pick_up_object",
    "fall_simulated_mattress",
}
FALL_LABELS = {"fall_simulated_mattress"}


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
