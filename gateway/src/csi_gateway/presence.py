from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from time import monotonic

from .radar import RadarSample


STATIC_PRESENCE_LABELS = {"standing_static", "lying_static"}


class PresenceState(str, Enum):
    UNKNOWN = "UNKNOWN"
    ABSENT = "ABSENT"
    PRESENT_STATIC = "PRESENT_STATIC"
    PRESENT_ACTIVE = "PRESENT_ACTIVE"


@dataclass(frozen=True)
class PresenceDecision:
    state: PresenceState
    presence_ratio: float
    movement_ratio: float
    sample_count: int
    reason: str


@dataclass(frozen=True)
class StaticPresenceBaseline:
    empty_anchor: float
    present_anchor: float
    empty_sessions: int
    present_sessions: int

    def normalize(self, relative_wander: float) -> float:
        span = self.present_anchor - self.empty_anchor
        empty_limit = self.empty_anchor + span * 0.25
        present_limit = self.present_anchor - span * 0.25
        return min(
            1.0,
            max(0.0, (relative_wander - empty_limit) / (present_limit - empty_limit)),
        )


def build_static_presence_baseline(
    feature_rows: list[dict[str, object]],
) -> StaticPresenceBaseline | None:
    empty_values = [
        float(row["wander_relative_mean"])
        for row in feature_rows
        if row.get("label") == "empty_room"
    ]
    present_values = [
        float(row["wander_relative_mean"])
        for row in feature_rows
        if row.get("label") in STATIC_PRESENCE_LABELS
    ]
    if not empty_values or not present_values:
        return None

    empty_anchor = max(empty_values)
    present_anchor = min(present_values)
    minimum_gap = max(0.5, empty_anchor * 0.25)
    if present_anchor - empty_anchor < minimum_gap:
        return None
    return StaticPresenceBaseline(
        empty_anchor=empty_anchor,
        present_anchor=present_anchor,
        empty_sessions=len(empty_values),
        present_sessions=len(present_values),
    )


class PresenceDetector:
    """Espressif Radar 결과를 보수적인 재실 상태로 안정화한다.

    움직임은 사람이 있다는 강한 증거로 즉시 사용한다. 반대로 부재는 최근
    시간 창에서 `someone`과 `moving`이 모두 낮은 상태가 일정 시간 이어진
    경우에만 확정한다. 사람의 장시간 정지를 부재로 오인하지 않기 위해서다.
    """

    PRESENT_STATES = {
        PresenceState.PRESENT_STATIC,
        PresenceState.PRESENT_ACTIVE,
    }

    def __init__(
        self,
        *,
        window_seconds: float = 5.0,
        min_samples: int = 8,
        present_ratio: float = 0.60,
        absent_ratio: float = 0.20,
        active_ratio: float = 0.20,
        presence_confirm_seconds: float = 1.0,
        absence_confirm_seconds: float = 15.0,
        link_timeout_seconds: float = 10.0,
        static_baseline: StaticPresenceBaseline | None = None,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if min_samples <= 0:
            raise ValueError("min_samples must be positive")
        if not 0 <= absent_ratio < present_ratio <= 1:
            raise ValueError("presence ratios must satisfy 0 <= absent < present <= 1")
        if not 0 <= active_ratio <= 1:
            raise ValueError("active_ratio must be between 0 and 1")
        if min(presence_confirm_seconds, absence_confirm_seconds) < 0:
            raise ValueError("confirmation durations cannot be negative")
        if link_timeout_seconds <= 0:
            raise ValueError("link_timeout_seconds must be positive")

        self.window_seconds = window_seconds
        self.min_samples = min_samples
        self.present_ratio = present_ratio
        self.absent_ratio = absent_ratio
        self.active_ratio = active_ratio
        self.presence_confirm_seconds = presence_confirm_seconds
        self.absence_confirm_seconds = absence_confirm_seconds
        self.link_timeout_seconds = link_timeout_seconds
        self.static_baseline = static_baseline

        self._observations: deque[tuple[float, float, bool]] = deque()
        self._last_observed_at: float | None = None
        self._candidate: str | None = None
        self._candidate_since: float | None = None
        self._decision = PresenceDecision(
            PresenceState.UNKNOWN,
            presence_ratio=0.0,
            movement_ratio=0.0,
            sample_count=0,
            reason="waiting_for_samples",
        )

    @property
    def decision(self) -> PresenceDecision:
        return self._decision

    def set_static_baseline(
        self, baseline: StaticPresenceBaseline | None
    ) -> None:
        self.static_baseline = baseline

    def reset(self, reason: str = "waiting_for_samples") -> PresenceDecision:
        self._observations.clear()
        self._last_observed_at = None
        self._candidate = None
        self._candidate_since = None
        self._decision = PresenceDecision(
            PresenceState.UNKNOWN,
            presence_ratio=0.0,
            movement_ratio=0.0,
            sample_count=0,
            reason=reason,
        )
        return self._decision

    def update(
        self,
        sample: RadarSample,
        *,
        calibrated: bool,
        observed_at: float | None = None,
    ) -> PresenceDecision:
        if not calibrated:
            return self.reset("calibration_required")

        now = monotonic() if observed_at is None else observed_at
        if self._last_observed_at is not None and now < self._last_observed_at:
            raise ValueError("observed_at cannot move backwards")

        self._last_observed_at = now
        if self.static_baseline is not None and sample.someone_threshold > 0:
            relative_wander = sample.wander / sample.someone_threshold
            presence_signal = self.static_baseline.normalize(relative_wander)
        else:
            presence_signal = float(sample.someone or sample.moving)
        if sample.moving:
            presence_signal = 1.0
        self._observations.append((now, presence_signal, sample.moving))
        self._prune(now)
        return self._evaluate(now, immediate_movement=sample.moving)

    def health(
        self,
        *,
        calibrated: bool,
        observed_at: float | None = None,
    ) -> PresenceDecision:
        if not calibrated:
            return self.reset("calibration_required")

        now = monotonic() if observed_at is None else observed_at
        if self._last_observed_at is None:
            return self._decision
        if now < self._last_observed_at:
            raise ValueError("observed_at cannot move backwards")
        if now - self._last_observed_at > self.link_timeout_seconds:
            return self.reset("radar_timeout")
        return self._decision

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._observations and self._observations[0][0] < cutoff:
            self._observations.popleft()

    def _evaluate(
        self, now: float, *, immediate_movement: bool
    ) -> PresenceDecision:
        sample_count = len(self._observations)
        presence_ratio = (
            sum(signal for _, signal, _ in self._observations) / sample_count
        )
        movement_ratio = (
            sum(float(moving) for _, _, moving in self._observations) / sample_count
        )

        if sample_count < self.min_samples:
            self._candidate = None
            self._candidate_since = None
            return self._set_decision(
                PresenceState.UNKNOWN,
                presence_ratio,
                movement_ratio,
                sample_count,
                "warming_up",
            )

        if immediate_movement or presence_ratio >= self.present_ratio:
            return self._handle_present(
                now,
                presence_ratio,
                movement_ratio,
                sample_count,
                immediate_movement=immediate_movement,
            )

        if presence_ratio <= self.absent_ratio and movement_ratio == 0:
            return self._handle_absent(
                now, presence_ratio, movement_ratio, sample_count
            )

        self._candidate = None
        self._candidate_since = None
        if self._decision.state == PresenceState.UNKNOWN:
            return self._set_decision(
                PresenceState.UNKNOWN,
                presence_ratio,
                movement_ratio,
                sample_count,
                "ambiguous_signal",
            )
        return self._set_decision(
            self._decision.state,
            presence_ratio,
            movement_ratio,
            sample_count,
            "holding_previous_state",
        )

    def _handle_present(
        self,
        now: float,
        presence_ratio: float,
        movement_ratio: float,
        sample_count: int,
        *,
        immediate_movement: bool,
    ) -> PresenceDecision:
        target = (
            PresenceState.PRESENT_ACTIVE
            if immediate_movement or movement_ratio >= self.active_ratio
            else PresenceState.PRESENT_STATIC
        )

        if immediate_movement or self._decision.state in self.PRESENT_STATES:
            self._candidate = None
            self._candidate_since = None
            return self._set_decision(
                target,
                presence_ratio,
                movement_ratio,
                sample_count,
                "movement_detected" if immediate_movement else "presence_confirmed",
            )

        if self._candidate != "present":
            self._candidate = "present"
            self._candidate_since = now

        if now - self._candidate_since >= self.presence_confirm_seconds:
            self._candidate = None
            self._candidate_since = None
            return self._set_decision(
                target,
                presence_ratio,
                movement_ratio,
                sample_count,
                "presence_confirmed",
            )

        return self._hold_or_unknown(
            presence_ratio,
            movement_ratio,
            sample_count,
            "confirming_presence",
        )

    def _handle_absent(
        self,
        now: float,
        presence_ratio: float,
        movement_ratio: float,
        sample_count: int,
    ) -> PresenceDecision:
        if self._decision.state == PresenceState.ABSENT:
            self._candidate = None
            self._candidate_since = None
            return self._set_decision(
                PresenceState.ABSENT,
                presence_ratio,
                movement_ratio,
                sample_count,
                "absence_confirmed",
            )

        if self._candidate != "absent":
            self._candidate = "absent"
            self._candidate_since = now

        if now - self._candidate_since >= self.absence_confirm_seconds:
            self._candidate = None
            self._candidate_since = None
            return self._set_decision(
                PresenceState.ABSENT,
                presence_ratio,
                movement_ratio,
                sample_count,
                "absence_confirmed",
            )

        return self._hold_or_unknown(
            presence_ratio,
            movement_ratio,
            sample_count,
            "confirming_absence",
        )

    def _hold_or_unknown(
        self,
        presence_ratio: float,
        movement_ratio: float,
        sample_count: int,
        reason: str,
    ) -> PresenceDecision:
        state = self._decision.state
        return self._set_decision(
            state,
            presence_ratio,
            movement_ratio,
            sample_count,
            reason,
        )

    def _set_decision(
        self,
        state: PresenceState,
        presence_ratio: float,
        movement_ratio: float,
        sample_count: int,
        reason: str,
    ) -> PresenceDecision:
        self._decision = PresenceDecision(
            state=state,
            presence_ratio=presence_ratio,
            movement_ratio=movement_ratio,
            sample_count=sample_count,
            reason=reason,
        )
        return self._decision
