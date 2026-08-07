from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import fmean, pstdev


REFERENCE_FEATURES = (
    "wander_mean",
    "wander_std",
    "wander_max",
    "jitter_mean",
    "jitter_std",
    "jitter_max",
    "moving_ratio",
    "someone_ratio",
    "first_half_jitter_mean",
    "second_half_jitter_mean",
)


@dataclass(frozen=True)
class PrototypePrediction:
    label: str
    separation_percent: float
    distance: float
    compared_labels: int


def predict_action(
    current: dict[str, float],
    reference_rows: list[dict[str, str | float]],
) -> PrototypePrediction | None:
    labels = sorted({str(row["label"]) for row in reference_rows})
    if len(labels) < 2:
        return None

    centroids: dict[str, dict[str, float]] = {}
    for label in labels:
        label_rows = [row for row in reference_rows if row["label"] == label]
        centroids[label] = {
            feature: fmean(float(row[feature]) for row in label_rows)
            for feature in REFERENCE_FEATURES
        }

    scales = {
        feature: pstdev(centroids[label][feature] for label in labels)
        for feature in REFERENCE_FEATURES
    }
    distances = []
    for label in labels:
        squared = 0.0
        for feature in REFERENCE_FEATURES:
            scale = scales[feature] or 1.0
            difference = (current[feature] - centroids[label][feature]) / scale
            squared += difference * difference
        distances.append((sqrt(squared), label))
    distances.sort()
    nearest_distance, nearest_label = distances[0]
    second_distance = distances[1][0]
    separation = (
        100.0 * (second_distance - nearest_distance) / second_distance
        if second_distance > 0
        else 0.0
    )
    return PrototypePrediction(
        label=nearest_label,
        separation_percent=max(0.0, separation),
        distance=nearest_distance,
        compared_labels=len(labels),
    )
