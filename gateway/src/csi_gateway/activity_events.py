"""Aggregate overlapping ML windows and fuse them with Radar fall evidence."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from uuid import uuid4

from .activity import ActivityPrediction
from .live_detection import DetectionEvent


@dataclass
class _FallEpisode:
    episode_id: str
    detected_at: str
    first_sequence: int
    last_sequence: int
    last_observed_at: float
    max_fall_score: float
    fall_score_sum: float
    window_count: int
    model_version: str
    preprocessing_version: str
    consumed: bool = False

    @property
    def mean_fall_score(self) -> float:
        return self.fall_score_sum / self.window_count

    def update(self, prediction: ActivityPrediction, observed_at: float) -> None:
        fall_score = float(prediction.scores.get("fall_suspected", 0.0))
        self.last_sequence = max(self.last_sequence, prediction.last_sequence)
        self.last_observed_at = observed_at
        self.max_fall_score = max(self.max_fall_score, fall_score)
        self.fall_score_sum += fall_score
        self.window_count += 1

    def evidence(self, threshold: float) -> dict[str, float | int | bool | str]:
        return {
            "ml_episode_id": self.episode_id,
            "ml_fall_score_max": self.max_fall_score,
            "ml_fall_score_mean": self.mean_fall_score,
            "ml_window_count": self.window_count,
            "ml_first_sequence": self.first_sequence,
            "ml_last_sequence": self.last_sequence,
            "ml_fall_threshold": threshold,
            "model_version": self.model_version,
            "preprocessing_version": self.preprocessing_version,
            "model_score_calibrated": False,
        }


@dataclass
class _RadarFall:
    event: DetectionEvent
    observed_at: float
    consumed: bool = False


class ActivityEventAggregator:
    """Treat many overlapping fall windows as one physical action episode."""

    def __init__(
        self,
        *,
        fall_score_threshold: float = 0.80,
        episode_gap_seconds: float = 2.0,
        radar_correlation_seconds: float = 15.0,
        radar_fallback_confidence_threshold: float | None = None,
        radar_fallback_impact_ratio: float = 5.0,
    ) -> None:
        if not 0.0 < fall_score_threshold <= 1.0:
            raise ValueError("fall_score_threshold must be in (0, 1]")
        if episode_gap_seconds <= 0 or radar_correlation_seconds <= 0:
            raise ValueError("episode timing values must be positive")
        if radar_fallback_impact_ratio <= 0:
            raise ValueError("radar_fallback_impact_ratio must be positive")
        self.fall_score_threshold = fall_score_threshold
        self.episode_gap_seconds = episode_gap_seconds
        self.radar_correlation_seconds = radar_correlation_seconds
        self.radar_fallback_impact_ratio = radar_fallback_impact_ratio
        self.radar_fallback_confidence_threshold: float | None = None
        self.set_radar_fallback_threshold(radar_fallback_confidence_threshold)
        self._current: _FallEpisode | None = None
        self._recent: deque[_FallEpisode] = deque(maxlen=8)
        self._recent_radar: deque[_RadarFall] = deque(maxlen=8)

    def reset(self) -> None:
        self._current = None
        self._recent.clear()
        self._recent_radar.clear()

    def set_radar_fallback_threshold(self, threshold: float | None) -> None:
        if threshold is not None and not 0.0 < threshold <= 1.0:
            raise ValueError("radar fallback threshold must be in (0, 1]")
        self.radar_fallback_confidence_threshold = threshold

    def observe(
        self,
        prediction: ActivityPrediction,
        *,
        observed_at: float,
        detected_at: str,
    ) -> list[DetectionEvent]:
        events = self.expire(observed_at)
        fall_score = float(prediction.scores.get("fall_suspected", 0.0))
        if fall_score < self.fall_score_threshold:
            return events

        if self._current is None:
            self._current = _FallEpisode(
                episode_id=f"ml-fall-{uuid4().hex}",
                detected_at=detected_at,
                first_sequence=prediction.first_sequence,
                last_sequence=prediction.last_sequence,
                last_observed_at=observed_at,
                max_fall_score=fall_score,
                fall_score_sum=fall_score,
                window_count=1,
                model_version=prediction.model_version,
                preprocessing_version=prediction.preprocessing_version,
            )
        else:
            self._current.update(prediction, observed_at)
        return events

    def expire(self, observed_at: float) -> list[DetectionEvent]:
        events: list[DetectionEvent] = []
        if (
            self._current is not None
            and observed_at - self._current.last_observed_at
            >= self.episode_gap_seconds
        ):
            episode = self._finish_current()
            events.append(self._candidate_event(episode))
            radar = self._matching_radar(episode)
            if radar is not None:
                events.append(self._fused_event(episode, radar))
        events.extend(self._radar_fallback_events(observed_at))
        self._prune(observed_at)
        return events

    def fuse_radar_fall(
        self,
        radar_event: DetectionEvent,
        *,
        observed_at: float,
    ) -> DetectionEvent | None:
        if radar_event.event_type != "fall_suspected":
            raise ValueError("radar_event must be fall_suspected")
        if self._current is not None:
            self._finish_current()
        self._prune(observed_at)
        radar = next(
            (
                candidate
                for candidate in self._recent_radar
                if candidate.event.event_id == radar_event.event_id
            ),
            None,
        )
        if radar is None:
            radar = _RadarFall(radar_event, observed_at)
            self._recent_radar.append(radar)
        if radar.consumed:
            return None
        episode = next(
            (
                candidate
                for candidate in reversed(self._recent)
                if not candidate.consumed
                and abs(observed_at - candidate.last_observed_at)
                <= self.radar_correlation_seconds
            ),
            None,
        )
        if episode is None:
            return None
        return self._fused_event(episode, radar)

    def _fused_event(
        self,
        episode: _FallEpisode,
        radar: _RadarFall,
    ) -> DetectionEvent:
        episode.consumed = True
        radar.consumed = True
        evidence = dict(radar.event.evidence)
        evidence.update(episode.evidence(self.fall_score_threshold))
        evidence["fusion_rule"] = "ml_and_radar_v1"
        return DetectionEvent(
            event_id=radar.event.event_id,
            event_type="fall_suspected",
            label="fall_like",
            detected_at=radar.event.detected_at,
            confidence=min(radar.event.confidence, episode.max_fall_score),
            source="ml_radar_fusion",
            evidence=evidence,
        )

    def _matching_radar(self, episode: _FallEpisode) -> _RadarFall | None:
        return next(
            (
                candidate
                for candidate in reversed(self._recent_radar)
                if not candidate.consumed
                and abs(episode.last_observed_at - candidate.observed_at)
                <= self.radar_correlation_seconds
            ),
            None,
        )

    def _radar_fallback_events(self, observed_at: float) -> list[DetectionEvent]:
        threshold = self.radar_fallback_confidence_threshold
        if threshold is None:
            return []
        events: list[DetectionEvent] = []
        for radar in self._recent_radar:
            if radar.consumed:
                continue
            if observed_at - radar.observed_at < self.radar_correlation_seconds:
                continue
            if (
                self._current is not None
                and abs(self._current.last_observed_at - radar.observed_at)
                <= self.radar_correlation_seconds
            ):
                continue
            raw_impact_ratio = radar.event.evidence.get("impact_ratio", 0.0)
            impact_ratio = (
                float(raw_impact_ratio)
                if isinstance(raw_impact_ratio, (int, float))
                else 0.0
            )
            if (
                radar.event.confidence < threshold
                or impact_ratio < self.radar_fallback_impact_ratio
            ):
                continue
            radar.consumed = True
            evidence = dict(radar.event.evidence)
            evidence.update(
                {
                    "fusion_rule": "radar_high_confidence_fallback_v1",
                    "ml_confirmation": False,
                    "radar_fallback_confidence_threshold": threshold,
                    "radar_fallback_impact_ratio": self.radar_fallback_impact_ratio,
                    "fallback_delay_seconds": self.radar_correlation_seconds,
                }
            )
            events.append(
                replace(
                    radar.event,
                    source="radar_high_confidence_fallback",
                    evidence=evidence,
                )
            )
        return events

    @staticmethod
    def radar_candidate(radar_event: DetectionEvent) -> DetectionEvent:
        return replace(radar_event, event_type="radar_fall_candidate")

    def _finish_current(self) -> _FallEpisode:
        if self._current is None:
            raise RuntimeError("no current ML fall episode")
        episode = self._current
        self._current = None
        self._recent.append(episode)
        return episode

    def _prune(self, observed_at: float) -> None:
        while (
            self._recent
            and observed_at - self._recent[0].last_observed_at
            > self.radar_correlation_seconds
        ):
            self._recent.popleft()
        radar_retention = self.radar_correlation_seconds + self.episode_gap_seconds
        while (
            self._recent_radar
            and observed_at - self._recent_radar[0].observed_at > radar_retention
        ):
            self._recent_radar.popleft()

    def _candidate_event(self, episode: _FallEpisode) -> DetectionEvent:
        return DetectionEvent(
            event_id=episode.episode_id,
            event_type="ml_fall_candidate",
            label="fall_suspected",
            detected_at=episode.detected_at,
            confidence=episode.max_fall_score,
            source="cnn_activity_model",
            evidence=episode.evidence(self.fall_score_threshold),
        )
