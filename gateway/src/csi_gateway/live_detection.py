from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol
from uuid import uuid4

from .features import extract_radar_features
from .prototype import predict_action
from .radar import RadarSample


FALL_HISTORY_EVENT_TYPES = {
    "fall_suspected",
    "ml_fall_candidate",
    "radar_fall_candidate",
    "fall_alert_delivery",
}


def format_fall_history_record(record: dict[str, object]) -> str:
    """Render one persisted fall-related record for the monitor history."""
    timestamp = str(record.get("detected_at") or record.get("recorded_at") or "")
    try:
        detected = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        display_time = detected.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        display_time = timestamp or "시각 없음"

    event_type = str(record.get("event_type") or "")
    labels = {
        "fall_suspected": "최종 낙상 의심",
        "ml_fall_candidate": "ML 낙상 후보",
        "radar_fall_candidate": "Radar 낙상 후보",
        "fall_alert_delivery": "앱 알림 전달",
    }
    parts = [display_time, labels.get(event_type, event_type)]

    confidence = record.get("confidence")
    if isinstance(confidence, (int, float)):
        parts.append(f"신뢰 지표 {float(confidence) * 100:.1f}%")
    source = record.get("source")
    if source:
        parts.append(f"근거 {source}")

    evidence = record.get("evidence")
    if isinstance(evidence, dict):
        impact_ratio = evidence.get("impact_ratio")
        if isinstance(impact_ratio, (int, float)):
            parts.append(f"충격비 {float(impact_ratio):.2f}")
        no_recovery = evidence.get("no_recovery_sec")
        if isinstance(no_recovery, (int, float)):
            parts.append(f"무회복 {float(no_recovery):.1f}초")
        ml_score = evidence.get("ml_fall_score_max")
        if isinstance(ml_score, (int, float)):
            parts.append(f"ML {float(ml_score) * 100:.1f}%")

    status = record.get("status")
    if status:
        parts.append(f"전달 {status}")
    message = record.get("message")
    if message:
        parts.append(str(message))
    event_id = record.get("event_id") or record.get("window_id")
    if event_id:
        parts.append(f"ID {event_id}")
    return " | ".join(parts)


@dataclass(frozen=True)
class LiveDetectionConfig:
    window_seconds: float = 8.0
    min_samples: int = 8
    classification_interval_seconds: float = 2.0
    prediction_confirmations: int = 2
    moving_ratio_threshold: float = 0.6
    static_ratio_threshold: float = 0.2
    fall_impact_ratio: float = 2.5
    fall_no_recovery_seconds: float = 8.0
    fall_max_moving_ratio: float = 0.2
    fall_cooldown_seconds: float = 60.0


@dataclass(frozen=True)
class DetectionEvent:
    event_id: str
    event_type: str
    label: str
    detected_at: str
    confidence: float
    source: str
    evidence: dict[str, float | int | bool | str | None]

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ActionPrediction:
    label: str
    confidence: float
    source: str
    evidence: dict[str, float | int | bool | str | None]


class WindowClassifier(Protocol):
    """Radar 파생 특징 기반 분류기가 구현할 선택적 실시간 계약.

    raw CSI 모델 서버는 별도의 CSI ring buffer 클라이언트에서 예측을 만든 뒤
    동일한 DetectionEvent 기록·알림 경로로 합류시킨다.
    """

    def predict(self, samples: list[RadarSample]) -> ActionPrediction | None: ...


class PrototypeWindowClassifier:
    """기존 라벨 세션의 중심점과 현재 실시간 창을 비교한다.

    공개 데이터로 학습한 모델이 준비되면 같은 ``predict`` 반환 계약을 구현해
    LiveActionDetector에 주입하면 된다.
    """

    def __init__(self, reference_rows: Iterable[dict[str, str | float | bool]]) -> None:
        self.reference_rows = list(reference_rows)

    @property
    def ready(self) -> bool:
        return len({str(row["label"]) for row in self.reference_rows}) >= 2

    def predict(self, samples: list[RadarSample]) -> ActionPrediction | None:
        if not self.ready:
            return None
        prediction = predict_action(
            extract_radar_features(samples),
            self.reference_rows,
        )
        if prediction is None:
            return None
        return ActionPrediction(
            label=prediction.label,
            confidence=min(1.0, prediction.separation_percent / 100.0),
            source="prototype_similarity",
            evidence={
                "separation_percent": prediction.separation_percent,
                "distance": prediction.distance,
                "compared_labels": prediction.compared_labels,
                "experimental": True,
            },
        )


class EventJournal:
    """자동 감지와 알림 전달 결과를 날짜별 JSON Lines로 영구 기록한다."""

    def __init__(self, project_root: Path) -> None:
        self.event_dir = project_root / "data" / "events"

    def append(self, record: dict[str, object]) -> Path:
        timestamp = str(record.get("detected_at") or record.get("recorded_at") or "")
        try:
            day = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
        except ValueError:
            day = datetime.now(timezone.utc).date()
        self.event_dir.mkdir(parents=True, exist_ok=True)
        path = self.event_dir / f"{day.isoformat()}.jsonl"
        with path.open("a", encoding="utf-8", newline="\n") as output:
            output.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
        return path

    def recent_fall_records(self, limit: int = 20) -> list[dict[str, object]]:
        """Return newest persisted fall candidates, detections and deliveries."""
        if limit <= 0 or not self.event_dir.is_dir():
            return []
        records: list[dict[str, object]] = []
        for path in sorted(self.event_dir.glob("*.jsonl"), reverse=True):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(record, dict)
                    and record.get("event_type") in FALL_HISTORY_EVENT_TYPES
                ):
                    records.append(record)
                    if len(records) >= limit:
                        return records
        return records


class LiveActionDetector:
    """평상시 Radar 표본에서 행동 전이와 보수적인 낙상 후보를 찾는다."""

    def __init__(
        self,
        *,
        config: LiveDetectionConfig | None = None,
        classifier: WindowClassifier | None = None,
    ) -> None:
        self.config = config or LiveDetectionConfig()
        self.classifier = classifier
        self.samples: deque[tuple[float, RadarSample]] = deque()
        self.last_classified_at: float | None = None
        self.pending_label: str | None = None
        self.pending_count = 0
        self.current_label: str | None = None
        self.impact_at: float | None = None
        self.impact_ratio = 0.0
        self.impact_detected_at: str | None = None
        self.last_fall_at: float | None = None

    def reset(self) -> None:
        self.samples.clear()
        self.last_classified_at = None
        self.pending_label = None
        self.pending_count = 0
        self.current_label = None
        self.impact_at = None
        self.impact_ratio = 0.0
        self.impact_detected_at = None

    def update(
        self,
        sample: RadarSample,
        *,
        observed_at: float,
        detected_at: str,
        presence_state: str,
        presence_probability: float,
    ) -> list[DetectionEvent]:
        self.samples.append((observed_at, sample))
        cutoff = observed_at - self.config.window_seconds
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

        events: list[DetectionEvent] = []
        fall = self._update_fall(
            sample,
            observed_at=observed_at,
            detected_at=detected_at,
            presence_state=presence_state,
            presence_probability=presence_probability,
        )
        if fall is not None:
            events.append(fall)

        if len(self.samples) < self.config.min_samples:
            return events
        if (
            self.last_classified_at is not None
            and observed_at - self.last_classified_at
            < self.config.classification_interval_seconds
        ):
            return events
        self.last_classified_at = observed_at

        prediction = self._predict_window()
        if prediction is None:
            return events
        if prediction.label == self.pending_label:
            self.pending_count += 1
        else:
            self.pending_label = prediction.label
            self.pending_count = 1
        if self.pending_count < self.config.prediction_confirmations:
            return events
        if prediction.label == self.current_label:
            return events

        self.current_label = prediction.label
        events.append(
            DetectionEvent(
                event_id=f"activity-{uuid4().hex}",
                event_type="activity_detected",
                label=prediction.label,
                detected_at=detected_at,
                confidence=prediction.confidence,
                source=prediction.source,
                evidence=prediction.evidence,
            )
        )
        return events

    def _predict_window(self) -> ActionPrediction | None:
        samples = [sample for _, sample in self.samples]
        if self.classifier is not None:
            prediction = self.classifier.predict(samples)
            if prediction is not None:
                return prediction

        moving_ratio = sum(sample.moving for sample in samples) / len(samples)
        if moving_ratio >= self.config.moving_ratio_threshold:
            label = "moving"
            confidence = moving_ratio
        elif moving_ratio <= self.config.static_ratio_threshold:
            label = "static"
            confidence = 1.0 - moving_ratio
        else:
            return None
        return ActionPrediction(
            label=label,
            confidence=confidence,
            source="radar_rule",
            evidence={
                "moving_ratio": moving_ratio,
                "sample_count": len(samples),
                "window_seconds": self.config.window_seconds,
            },
        )

    def _update_fall(
        self,
        sample: RadarSample,
        *,
        observed_at: float,
        detected_at: str,
        presence_state: str,
        presence_probability: float,
    ) -> DetectionEvent | None:
        relative_jitter = (
            sample.jitter / sample.move_threshold
            if abs(sample.move_threshold) > 1e-12
            else 0.0
        )
        cooldown_ready = (
            self.last_fall_at is None
            or observed_at - self.last_fall_at >= self.config.fall_cooldown_seconds
        )
        if (
            cooldown_ready
            and sample.moving
            and relative_jitter >= self.config.fall_impact_ratio
            and (self.impact_at is None or relative_jitter > self.impact_ratio)
        ):
            self.impact_at = observed_at
            self.impact_ratio = relative_jitter
            self.impact_detected_at = detected_at

        if self.impact_at is None:
            return None
        no_recovery_seconds = observed_at - self.impact_at
        if no_recovery_seconds < self.config.fall_no_recovery_seconds:
            return None

        post_impact = [
            candidate
            for candidate_at, candidate in self.samples
            if candidate_at > self.impact_at
        ]
        moving_ratio = (
            sum(candidate.moving for candidate in post_impact) / len(post_impact)
            if post_impact
            else 1.0
        )
        impact_ratio = self.impact_ratio
        impact_detected_at = self.impact_detected_at or detected_at
        self.impact_at = None
        self.impact_ratio = 0.0
        self.impact_detected_at = None
        if moving_ratio > self.config.fall_max_moving_ratio:
            return None

        self.last_fall_at = observed_at
        motion_confidence = min(1.0, impact_ratio / (self.config.fall_impact_ratio * 2))
        recovery_confidence = 1.0 - moving_ratio
        confidence = 0.6 * motion_confidence + 0.4 * recovery_confidence
        return DetectionEvent(
            event_id=f"fall-{uuid4().hex}",
            event_type="fall_suspected",
            label="fall_like",
            detected_at=impact_detected_at,
            confidence=confidence,
            source="impact_then_no_recovery_rule",
            evidence={
                "impact_ratio": impact_ratio,
                "post_impact_moving_ratio": moving_ratio,
                "no_recovery_sec": no_recovery_seconds,
                "presence_state": presence_state,
                "presence_probability": presence_probability,
                "sample_count": len(post_impact),
            },
        )
