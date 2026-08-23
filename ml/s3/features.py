"""Hand-crafted, change-centered features for the S3 XGBoost baseline."""
from __future__ import annotations

import numpy as np


def handcrafted_feature_names() -> tuple[str, ...]:
    names: list[str] = []
    for channel in ("amplitude", "delta", "acceleration", "phase_delta"):
        names.extend(
            f"{channel}_{metric}"
            for metric in (
                "mean_abs",
                "std",
                "p90_abs",
                "p99_abs",
                "peak",
                "energy",
                "short_energy_peak",
                "temporal_peak_count",
                "subcarrier_variance",
                "subcarrier_correlation",
                "low_spectral_ratio",
                "high_spectral_ratio",
            )
        )
    names.extend(("motion_decay_ratio", "post_event_energy", "pre_event_energy", "impact_to_pre_ratio"))
    return tuple(names)


def _channel_features(values: np.ndarray) -> list[float]:
    x = np.asarray(values, dtype=np.float64)
    absolute = np.abs(x)
    energy_t = np.mean(x * x, axis=1)
    kernel = max(3, min(25, len(energy_t) // 10))
    rolling = np.convolve(energy_t, np.ones(kernel) / kernel, mode="valid")
    threshold = np.median(energy_t) + 3.0 * np.maximum(
        1.4826 * np.median(np.abs(energy_t - np.median(energy_t))), 1e-9
    )
    peak_count = int(np.count_nonzero((energy_t[1:-1] > energy_t[:-2]) & (energy_t[1:-1] >= energy_t[2:]) & (energy_t[1:-1] > threshold)))
    carrier_means = np.mean(x, axis=0)
    if x.shape[1] > 1:
        adjacent = [
            np.corrcoef(x[:, index], x[:, index + 1])[0, 1]
            for index in range(x.shape[1] - 1)
            if np.std(x[:, index]) > 1e-9 and np.std(x[:, index + 1]) > 1e-9
        ]
        correlation = float(np.nanmean(adjacent)) if adjacent else 0.0
    else:
        correlation = 0.0
    spectrum = np.abs(np.fft.rfft(x, axis=0)) ** 2
    total = float(np.sum(spectrum)) + 1e-9
    low_end = max(2, spectrum.shape[0] // 10)
    high_start = max(low_end, spectrum.shape[0] // 3)
    return [
        float(np.mean(absolute)),
        float(np.std(x)),
        float(np.percentile(absolute, 90)),
        float(np.percentile(absolute, 99)),
        float(np.max(absolute)),
        float(np.mean(x * x)),
        float(np.max(rolling)) if len(rolling) else float(np.max(energy_t)),
        float(peak_count),
        float(np.var(carrier_means)),
        correlation,
        float(np.sum(spectrum[1:low_end]) / total),
        float(np.sum(spectrum[high_start:]) / total),
    ]


def extract_handcrafted_features(features: np.ndarray) -> np.ndarray:
    """Return a fixed vector for 3- or 4-channel time×subcarrier input."""
    x = np.asarray(features, dtype=np.float32)
    if x.ndim != 3 or x.shape[0] not in {3, 4}:
        raise ValueError("expected [3|4, time, subcarrier]")
    if x.shape[0] == 3:
        x = np.concatenate((x, np.zeros_like(x[:1])), axis=0)
    result: list[float] = []
    for channel in x:
        result.extend(_channel_features(channel))
    energy = np.mean(x[1] * x[1], axis=1)
    split_pre = max(1, int(len(energy) * 0.40))
    split_post = max(split_pre + 1, int(len(energy) * 0.65))
    pre = float(np.mean(energy[:split_pre]))
    impact = float(np.max(energy[split_pre:split_post]))
    post = float(np.mean(energy[split_post:]))
    result.extend(
        (
            post / (impact + 1e-9),
            post,
            pre,
            impact / (pre + 1e-9),
        )
    )
    return np.asarray(result, dtype=np.float32)
