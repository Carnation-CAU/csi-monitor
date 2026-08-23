"""Recall-first ESP32-S3 CSI preprocessing and real-time signal evidence.

This module is model-neutral. It keeps timestamp quality, environment-relative
amplitude, sanitized phase and event-proposal scores separate from the legacy
C3 checkpoint so the same transforms can be reused by S3 training/evaluation.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp
from statistics import median
from typing import Iterable
from uuid import uuid4

import numpy as np

from .csi import CsiFrameSample


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


def _percentile(values: Iterable[float], percentile: float) -> float:
    array = np.asarray(tuple(values), dtype=np.float64)
    return float(np.percentile(array, percentile)) if len(array) else 0.0


@dataclass(frozen=True)
class PacketTimingStats:
    packet_count: int
    rate_hz: float
    mean_interval_ms: float
    median_interval_ms: float
    p95_interval_ms: float
    max_interval_ms: float
    gap_count: int
    missing_sequence_count: int
    packet_loss_ratio: float
    valid_subcarrier_ratio: float
    mean_rssi: float
    mean_noise_floor: float
    signal_quality_score: float

    def to_record(self) -> dict[str, float | int]:
        return {
            "packetCount": self.packet_count,
            "packetsPerSecond": self.rate_hz,
            "meanIntervalMs": self.mean_interval_ms,
            "medianIntervalMs": self.median_interval_ms,
            "p95IntervalMs": self.p95_interval_ms,
            "maxIntervalMs": self.max_interval_ms,
            "gapCount": self.gap_count,
            "missingSequenceCount": self.missing_sequence_count,
            "packetLossRatio": self.packet_loss_ratio,
            "validSubcarrierRatio": self.valid_subcarrier_ratio,
            "meanRssi": self.mean_rssi,
            "meanNoiseFloor": self.mean_noise_floor,
            "signalQualityScore": self.signal_quality_score,
        }


class PacketTimingTracker:
    """Measure device-timestamp density without treating low quality as a gate."""

    def __init__(
        self,
        *,
        target_rate_hz: float = 100.0,
        history_seconds: float = 10.0,
        gap_factor: float = 2.0,
    ) -> None:
        if target_rate_hz <= 0 or history_seconds <= 0 or gap_factor <= 1:
            raise ValueError("invalid packet timing configuration")
        self.target_rate_hz = target_rate_hz
        self.gap_threshold_ms = gap_factor * 1000.0 / target_rate_hz
        self._maxlen = max(20, int(target_rate_hz * history_seconds))
        self._intervals_ms: deque[float] = deque(maxlen=self._maxlen)
        self._valid_ratios: deque[float] = deque(maxlen=self._maxlen)
        self._rssis: deque[float] = deque(maxlen=self._maxlen)
        self._noise_floors: deque[float] = deque(maxlen=self._maxlen)
        self._packet_count = 0
        self._missing_sequences: deque[int] = deque(maxlen=self._maxlen)
        self._last_sequence: int | None = None
        self._last_timestamp_us: int | None = None

    def reset(self) -> None:
        self.__init__(
            target_rate_hz=self.target_rate_hz,
            history_seconds=self._maxlen / self.target_rate_hz,
            gap_factor=self.gap_threshold_ms * self.target_rate_hz / 1000.0,
        )

    def observe(self, sample: CsiFrameSample) -> PacketTimingStats:
        self._packet_count += 1
        if self._last_timestamp_us is not None:
            delta = sample.local_timestamp_us - self._last_timestamp_us
            if delta < 0:
                delta += 2**32
            if 0 < delta < 10_000_000:
                self._intervals_ms.append(delta / 1000.0)
        missing = 0
        if self._last_sequence is not None:
            sequence_delta = sample.sequence - self._last_sequence
            if sequence_delta > 1:
                missing = sequence_delta - 1
        self._missing_sequences.append(missing)
        self._last_sequence = sample.sequence
        self._last_timestamp_us = sample.local_timestamp_us
        self._valid_ratios.append(float(np.mean(sample.valid_subcarrier_mask)))
        self._rssis.append(float(sample.rssi))
        self._noise_floors.append(float(sample.noise_floor))
        return self.stats()

    def stats(self) -> PacketTimingStats:
        intervals = np.asarray(self._intervals_ms, dtype=np.float64)
        mean_ms = float(intervals.mean()) if len(intervals) else 0.0
        rate_hz = 1000.0 / mean_ms if mean_ms > 0 else 0.0
        missing = int(sum(self._missing_sequences))
        observed = max(1, len(self._missing_sequences))
        valid_ratio = float(np.mean(self._valid_ratios)) if self._valid_ratios else 0.0
        mean_rssi = float(np.mean(self._rssis)) if self._rssis else -100.0
        mean_noise = (
            float(np.mean(self._noise_floors)) if self._noise_floors else -110.0
        )
        loss_ratio = missing / (observed + missing)
        rate_score = _clamp(rate_hz / self.target_rate_hz)
        gap_ratio = (
            float(np.mean(intervals > self.gap_threshold_ms)) if len(intervals) else 1.0
        )
        gap_score = _clamp(1.0 - 4.0 * gap_ratio)
        loss_score = _clamp(1.0 - 5.0 * loss_ratio)
        rssi_score = _clamp((mean_rssi + 90.0) / 45.0)
        quality = (
            0.35 * rate_score
            + 0.25 * gap_score
            + 0.15 * loss_score
            + 0.15 * valid_ratio
            + 0.10 * rssi_score
        )
        return PacketTimingStats(
            packet_count=self._packet_count,
            rate_hz=rate_hz,
            mean_interval_ms=mean_ms,
            median_interval_ms=float(np.median(intervals)) if len(intervals) else 0.0,
            p95_interval_ms=float(np.percentile(intervals, 95)) if len(intervals) else 0.0,
            max_interval_ms=float(intervals.max()) if len(intervals) else 0.0,
            gap_count=int(np.sum(intervals > self.gap_threshold_ms)),
            missing_sequence_count=missing,
            packet_loss_ratio=loss_ratio,
            valid_subcarrier_ratio=valid_ratio,
            mean_rssi=mean_rssi,
            mean_noise_floor=mean_noise,
            signal_quality_score=quality,
        )


class AdaptiveCsiBaseline:
    """Per-subcarrier S3 baseline with movement-safe EMA adaptation."""

    VERSION = "s3-robust-baseline-v1"

    def __init__(self, *, adaptive_alpha: float = 0.0005) -> None:
        if not 0 < adaptive_alpha < 1:
            raise ValueError("adaptive_alpha must be in (0, 1)")
        self.adaptive_alpha = adaptive_alpha
        self.mean: np.ndarray | None = None
        self.std: np.ndarray | None = None
        self.stable_mask: np.ndarray | None = None
        self.channel: int | None = None
        self.bandwidth: str | None = None
        self.sample_count = 0
        self.calibrated_at_utc: str | None = None
        self._calibration_frames: list[np.ndarray] = []
        self._calibration_masks: list[np.ndarray] = []

    @property
    def ready(self) -> bool:
        return self.mean is not None and self.std is not None and self.stable_mask is not None

    def invalidate(self) -> None:
        self.mean = self.std = self.stable_mask = None
        self.channel = None
        self.bandwidth = None
        self.sample_count = 0
        self.calibrated_at_utc = None
        self._calibration_frames.clear()
        self._calibration_masks.clear()

    def compatible(self, sample: CsiFrameSample) -> bool:
        return bool(
            self.ready
            and self.channel == sample.channel
            and self.bandwidth == sample.bandwidth
            and len(self.mean) == len(sample.amplitude)
        )

    def start_calibration(self) -> None:
        self.invalidate()

    @staticmethod
    def relative_amplitude(sample: CsiFrameSample) -> np.ndarray:
        amplitude = np.asarray(sample.amplitude, dtype=np.float32)
        valid = sample.valid_subcarrier_mask & np.isfinite(amplitude)
        scale = float(np.median(amplitude[valid])) if np.any(valid) else 1.0
        return amplitude / max(scale, 1e-3)

    def observe_calibration(self, sample: CsiFrameSample) -> None:
        if self._calibration_frames and len(self._calibration_frames[0]) != len(sample.amplitude):
            self._calibration_frames.clear()
            self._calibration_masks.clear()
        self.channel = sample.channel
        self.bandwidth = sample.bandwidth
        self._calibration_frames.append(self.relative_amplitude(sample).copy())
        self._calibration_masks.append(sample.valid_subcarrier_mask.copy())

    def finalize_calibration(self, *, minimum_frames: int = 200) -> bool:
        if len(self._calibration_frames) < minimum_frames:
            return False
        frames = np.stack(self._calibration_frames)
        median_amplitude = np.median(frames, axis=0)
        mad = np.median(np.abs(frames - median_amplitude), axis=0)
        robust_std = np.maximum(1.4826 * mad, 0.05)
        valid = np.logical_and.reduce(self._calibration_masks)
        finite = np.isfinite(median_amplitude) & np.isfinite(robust_std)
        candidate_std = robust_std[valid & finite]
        if not len(candidate_std):
            return False
        # Mask only extreme noisy carriers; never silently reduce below 16.
        noisy_limit = max(float(np.median(candidate_std)) * 4.0, 0.25)
        stable = valid & finite & (robust_std <= noisy_limit) & (median_amplitude > 0)
        if int(stable.sum()) < 16:
            stable = valid & finite & (median_amplitude > 0)
        self.mean = median_amplitude.astype(np.float32)
        self.std = robust_std.astype(np.float32)
        self.stable_mask = stable
        self.sample_count = len(frames)
        self.calibrated_at_utc = datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        self._calibration_frames.clear()
        self._calibration_masks.clear()
        return True

    def normalize(self, sample: CsiFrameSample) -> tuple[np.ndarray, np.ndarray]:
        amplitude = self.relative_amplitude(sample)
        if self.compatible(sample):
            normalized = (amplitude - self.mean) / np.maximum(self.std, 0.05)
            mask = self.stable_mask & sample.valid_subcarrier_mask
        else:
            # Environment-independent fallback while automatic stabilization
            # is pending: per-frame relative amplitude, not absolute CSI.
            valid = sample.valid_subcarrier_mask
            normalized = amplitude - 1.0
            mask = valid
        return np.clip(normalized, -12.0, 12.0), mask

    def adaptive_update(
        self,
        sample: CsiFrameSample,
        *,
        no_motion_confidence: float,
        fall_candidate: bool,
    ) -> bool:
        if (
            not self.compatible(sample)
            or no_motion_confidence < 0.90
            or fall_candidate
        ):
            return False
        alpha = self.adaptive_alpha
        value = self.relative_amplitude(sample)
        residual = value - self.mean
        self.mean = (1.0 - alpha) * self.mean + alpha * value
        variance = np.maximum(self.std, 0.05) ** 2
        variance = (1.0 - alpha) * variance + alpha * residual**2
        self.std = np.sqrt(np.maximum(variance, 0.05**2)).astype(np.float32)
        self.sample_count += 1
        return True

    def to_record(self) -> dict[str, object] | None:
        if not self.ready:
            return None
        return {
            "version": self.VERSION,
            "channel": self.channel,
            "bandwidth": self.bandwidth,
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
            "stableSubcarrierMask": self.stable_mask.tolist(),
            "sampleCount": self.sample_count,
            "adaptiveAlpha": self.adaptive_alpha,
            "calibratedAtUtc": self.calibrated_at_utc,
        }

    @classmethod
    def from_record(cls, record: object) -> "AdaptiveCsiBaseline":
        if not isinstance(record, dict) or record.get("version") != cls.VERSION:
            return cls()
        baseline = cls(adaptive_alpha=float(record.get("adaptiveAlpha", 0.0005)))
        try:
            baseline.mean = np.asarray(record["mean"], dtype=np.float32)
            baseline.std = np.asarray(record["std"], dtype=np.float32)
            baseline.stable_mask = np.asarray(
                record["stableSubcarrierMask"], dtype=bool
            )
            if not (
                baseline.mean.ndim == 1
                and baseline.mean.shape == baseline.std.shape == baseline.stable_mask.shape
            ):
                raise ValueError("baseline shape mismatch")
            baseline.channel = int(record["channel"])
            baseline.bandwidth = str(record["bandwidth"])
            baseline.sample_count = int(record.get("sampleCount", 0))
            baseline.calibrated_at_utc = str(record.get("calibratedAtUtc") or "")
        except (KeyError, TypeError, ValueError):
            baseline.invalidate()
        return baseline


@dataclass(frozen=True)
class SignalEvidence:
    state: str
    motion_energy: float
    phase_energy: float
    motion_score: float
    impact_score: float
    post_event_score: float
    signal_quality_score: float
    baseline_ready: bool
    baseline_adapted: bool
    channel_changed: bool
    observed_at: float
    proposal_id: str | None = None
    proposal_started_at: float | None = None
    proposal_active: bool = False
    baseline_age_seconds: float = 0.0

    def to_record(self) -> dict[str, float | bool | str]:
        quality_state = (
            "LOW"
            if self.signal_quality_score < 0.55
            else "DEGRADED"
            if self.signal_quality_score < 0.75
            else "GOOD"
        )
        return {
            "signal_state": self.state,
            "motion_energy": self.motion_energy,
            "phase_energy": self.phase_energy,
            "motion_score": self.motion_score,
            "impact_score": self.impact_score,
            "post_event_score": self.post_event_score,
            "signal_quality_score": self.signal_quality_score,
            "signal_quality_state": quality_state,
            "baseline_ready": self.baseline_ready,
            "baseline_adapted": self.baseline_adapted,
            "channel_changed": self.channel_changed,
            "signal_proposal_id": self.proposal_id or "",
            "signal_proposal_started_at": self.proposal_started_at or 0.0,
            "signal_proposal_active": self.proposal_active,
            "baseline_age_seconds": self.baseline_age_seconds,
        }


class HighRecallEventDetector:
    """Generate scores and temporal state; no output here can veto ML."""

    def __init__(self) -> None:
        self._quiet_energy: deque[float] = deque(maxlen=500)
        self._recent_motion: deque[tuple[float, float]] = deque()
        self._peak_at: float | None = None
        self._peak_score = 0.0
        self._proposal_id: str | None = None
        self._armed = True
        self._quiet_since: float | None = None
        self.state = "IDLE"

    def reset(self) -> None:
        self._quiet_energy.clear()
        self._recent_motion.clear()
        self._peak_at = None
        self._peak_score = 0.0
        self._proposal_id = None
        self._armed = True
        self._quiet_since = None
        self.state = "IDLE"

    def update(
        self,
        *,
        amplitude_delta: np.ndarray,
        phase_delta: np.ndarray,
        mask: np.ndarray,
        observed_at: float,
        signal_quality: float,
        baseline_ready: bool,
        channel_changed: bool,
        baseline_age_seconds: float = 0.0,
    ) -> SignalEvidence:
        selected = np.abs(amplitude_delta[mask])
        phase_selected = np.abs(phase_delta[mask])
        motion_energy = float(np.median(selected)) if len(selected) else 0.0
        phase_energy = float(np.median(phase_selected)) if len(phase_selected) else 0.0
        if len(self._quiet_energy) < 50:
            self._quiet_energy.append(motion_energy)
        quiet_median = median(self._quiet_energy) if self._quiet_energy else 0.0
        quiet_mad = (
            median(abs(value - quiet_median) for value in self._quiet_energy)
            if self._quiet_energy
            else 0.0
        )
        noise_scale = max(1.4826 * quiet_mad, 0.02 if baseline_ready else 0.002)
        z_score = (motion_energy - quiet_median) / noise_scale
        motion_score = _clamp((z_score - 0.5) / 5.0)
        impact_score = _clamp((z_score - 2.0) / 8.0)
        self._recent_motion.append((observed_at, motion_score))
        while self._recent_motion and observed_at - self._recent_motion[0][0] > 5.0:
            self._recent_motion.popleft()

        if self._proposal_id is not None and self._peak_at is not None:
            elapsed = observed_at - self._peak_at
            if elapsed <= 5.0:
                self._peak_score = max(self._peak_score, impact_score)
                self.state = (
                    "HIGH_ENERGY_EVENT"
                    if elapsed <= 0.5
                    else "POST_EVENT_MONITORING"
                )
            else:
                # A sustained noisy period is one event, not a new impact on
                # every frame. Require a real quiet interval before re-arming.
                self._proposal_id = None
                self._peak_at = None
                self._peak_score = 0.0
                self._armed = False

        if self._proposal_id is None:
            if motion_score < 0.15:
                if self._quiet_since is None:
                    self._quiet_since = observed_at
                elif observed_at - self._quiet_since >= 1.5:
                    self._armed = True
            else:
                self._quiet_since = None
            if self._armed and impact_score >= 0.35:
                self._proposal_id = f"csi-event-{uuid4().hex}"
                self._peak_at = observed_at
                self._peak_score = impact_score
                self._quiet_since = None
                self.state = "HIGH_ENERGY_EVENT"
            elif motion_score >= 0.15:
                self.state = "MOVEMENT"
            else:
                self.state = "IDLE"

        after_peak = [
            score
            for timestamp, score in self._recent_motion
            if self._proposal_id is not None
            and self._peak_at is not None
            and timestamp > self._peak_at
        ]
        post_score = 1.0 - float(np.mean(after_peak)) if after_peak else 0.0
        fall_candidate = (
            self._proposal_id is not None
            and self._peak_at is not None
            and observed_at - self._peak_at <= 5.0
        )
        no_motion_confidence = 1.0 - motion_score
        if not fall_candidate and no_motion_confidence >= 0.95:
            # Only a low-energy tail enters the adaptive noise estimator.
            self._quiet_energy.append(motion_energy)
        return SignalEvidence(
            state=self.state,
            motion_energy=motion_energy,
            phase_energy=phase_energy,
            motion_score=motion_score,
            impact_score=max(impact_score, self._peak_score if fall_candidate else 0.0),
            post_event_score=_clamp(post_score),
            signal_quality_score=signal_quality,
            baseline_ready=baseline_ready,
            baseline_adapted=False,
            channel_changed=channel_changed,
            observed_at=observed_at,
            proposal_id=self._proposal_id,
            proposal_started_at=self._peak_at,
            proposal_active=fall_candidate,
            baseline_age_seconds=baseline_age_seconds,
        )


class CsiRealtimePipeline:
    """Combine quality, robust normalization, phase sanitation and proposals."""

    def __init__(self, baseline: AdaptiveCsiBaseline | None = None) -> None:
        self.baseline = baseline or AdaptiveCsiBaseline()
        self.timing = PacketTimingTracker()
        self.detector = HighRecallEventDetector()
        self.previous_amplitude: np.ndarray | None = None
        self.previous_phase: np.ndarray | None = None
        self._amplitude_filter: deque[np.ndarray] = deque(maxlen=3)
        self.last_evidence: SignalEvidence | None = None
        self._stabilization_frames: list[np.ndarray] = []
        self._stabilization_masks: list[np.ndarray] = []
        self._stabilization_channel: int | None = None
        self._baseline_ready_state = self.baseline.ready
        self._baseline_ready_at: float | None = None

    @staticmethod
    def sanitize_phase(phase: np.ndarray, mask: np.ndarray) -> np.ndarray:
        unwrapped = np.unwrap(np.asarray(phase, dtype=np.float32))
        positions = np.arange(len(unwrapped), dtype=np.float32)
        valid = mask & np.isfinite(unwrapped)
        if int(valid.sum()) >= 3:
            slope, intercept = np.polyfit(positions[valid], unwrapped[valid], 1)
            unwrapped = unwrapped - (slope * positions + intercept)
        else:
            unwrapped = unwrapped - float(np.nanmedian(unwrapped))
        return unwrapped.astype(np.float32)

    def _observe_automatic_stabilization(
        self, sample: CsiFrameSample, relative_delta_energy: float
    ) -> None:
        if self.baseline.compatible(sample):
            self._stabilization_frames.clear()
            self._stabilization_masks.clear()
            return
        if self._stabilization_channel != sample.channel:
            self._stabilization_frames.clear()
            self._stabilization_masks.clear()
            self._stabilization_channel = sample.channel
        if relative_delta_energy > 0.08:
            self._stabilization_frames.clear()
            self._stabilization_masks.clear()
            return
        self._stabilization_frames.append(sample.amplitude.copy())
        self._stabilization_masks.append(sample.valid_subcarrier_mask.copy())
        if len(self._stabilization_frames) < 300:
            return
        self.baseline.start_calibration()
        for amplitude, mask in zip(
            self._stabilization_frames, self._stabilization_masks
        ):
            synthetic = _sample_with_amplitude(sample, amplitude, mask)
            self.baseline.observe_calibration(synthetic)
        self.baseline.finalize_calibration(minimum_frames=300)
        self._stabilization_frames.clear()
        self._stabilization_masks.clear()

    def observe(self, sample: CsiFrameSample, *, observed_at: float) -> SignalEvidence:
        channel_changed = bool(
            self.baseline.ready
            and not self.baseline.compatible(sample)
            and self.baseline.channel != sample.channel
        )
        timing = self.timing.observe(sample)
        baseline_ready = self.baseline.compatible(sample)
        if baseline_ready:
            if self._baseline_ready_at is None:
                self._baseline_ready_at = observed_at
        else:
            self._baseline_ready_at = None
        if baseline_ready != self._baseline_ready_state:
            # Noise energy has a different numerical scale before/after
            # environment z-normalization; never reuse the old scale.
            self.detector.reset()
            self.previous_amplitude = None
            self.previous_phase = None
            self._amplitude_filter.clear()
            self._baseline_ready_state = baseline_ready
        normalized, mask = self.baseline.normalize(sample)
        self._amplitude_filter.append(normalized)
        filtered_amplitude = np.median(
            np.stack(self._amplitude_filter), axis=0
        ).astype(np.float32)
        phase = self.sanitize_phase(sample.phase, mask)
        if self.previous_amplitude is None or len(self.previous_amplitude) != len(filtered_amplitude):
            amplitude_delta = np.zeros_like(filtered_amplitude)
            phase_delta = np.zeros_like(phase)
            relative_delta = 0.0
        else:
            amplitude_delta = filtered_amplitude - self.previous_amplitude
            phase_delta = np.angle(np.exp(1j * (phase - self.previous_phase))).astype(
                np.float32
            )
            relative_delta = (
                float(np.median(np.abs(amplitude_delta[mask])))
                if np.any(mask)
                else 0.0
            )
        self.previous_amplitude = filtered_amplitude
        self.previous_phase = phase
        self._observe_automatic_stabilization(sample, relative_delta)
        # Automatic stabilization finalizes after this frame. The next frame
        # observes the transition and resets the proposal noise estimator.
        evidence = self.detector.update(
            amplitude_delta=amplitude_delta,
            phase_delta=phase_delta,
            mask=mask,
            observed_at=observed_at,
            signal_quality=timing.signal_quality_score,
            baseline_ready=self.baseline.compatible(sample),
            channel_changed=channel_changed,
            baseline_age_seconds=(
                observed_at - self._baseline_ready_at
                if self._baseline_ready_at is not None
                else 0.0
            ),
        )
        adapted = self.baseline.adaptive_update(
            sample,
            no_motion_confidence=1.0 - evidence.motion_score,
            fall_candidate=evidence.state
            in {"HIGH_ENERGY_EVENT", "POST_EVENT_MONITORING"},
        )
        if adapted:
            evidence = SignalEvidence(
                **{
                    **evidence.__dict__,
                    "baseline_adapted": True,
                }
            )
        self.last_evidence = evidence
        return evidence


def _sample_with_amplitude(
    template: CsiFrameSample, amplitude: np.ndarray, mask: np.ndarray
) -> CsiFrameSample:
    """Internal immutable-sample helper used only by auto stabilization."""
    values = dict(template.__dict__)
    values["amplitude"] = amplitude
    values["valid_subcarrier_mask"] = mask
    return CsiFrameSample(**values)
