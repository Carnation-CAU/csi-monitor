"""Recall-first window and physical-event evaluation utilities."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median
from typing import Iterable, Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class TimedEvent:
    event_id: str
    session_id: str
    occurred_at: float
    label: str = "fall"


@dataclass(frozen=True)
class ScoredEvent:
    event_id: str
    session_id: str
    detected_at: float
    score: float


@dataclass(frozen=True)
class EventMetrics:
    fall_recall: float
    fall_precision: float
    f1: float
    false_negative_count: int
    false_positive_count: int
    true_positive_count: int
    detection_latency_mean_seconds: float | None
    detection_latency_median_seconds: float | None
    detection_latency_p95_seconds: float | None


def evaluate_events(
    actual: Sequence[TimedEvent],
    predicted: Sequence[ScoredEvent],
    *,
    early_tolerance_seconds: float = 2.0,
    late_tolerance_seconds: float = 15.0,
) -> tuple[EventMetrics, list[dict[str, object]]]:
    """Match at most one prediction to each physical fall event."""
    unused = set(range(len(predicted)))
    matches: list[dict[str, object]] = []
    latencies: list[float] = []
    true_positives = 0
    for event in actual:
        candidates = [
            index
            for index in unused
            if predicted[index].session_id == event.session_id
            and event.occurred_at - early_tolerance_seconds
            <= predicted[index].detected_at
            <= event.occurred_at + late_tolerance_seconds
        ]
        if not candidates:
            matches.append(
                {"actualEventId": event.event_id, "detected": False, "latencySeconds": None}
            )
            continue
        selected = min(candidates, key=lambda index: predicted[index].detected_at)
        unused.remove(selected)
        result = predicted[selected]
        latency = result.detected_at - event.occurred_at
        latencies.append(latency)
        true_positives += 1
        matches.append(
            {
                "actualEventId": event.event_id,
                "detected": True,
                "predictedEventId": result.event_id,
                "score": result.score,
                "latencySeconds": latency,
            }
        )
    false_negatives = len(actual) - true_positives
    false_positives = len(unused)
    recall = true_positives / len(actual) if actual else 0.0
    precision = (
        true_positives / (true_positives + false_positives)
        if true_positives + false_positives
        else 0.0
    )
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    sorted_latency = sorted(latencies)
    metrics = EventMetrics(
        fall_recall=recall,
        fall_precision=precision,
        f1=f1,
        false_negative_count=false_negatives,
        false_positive_count=false_positives,
        true_positive_count=true_positives,
        detection_latency_mean_seconds=mean(latencies) if latencies else None,
        detection_latency_median_seconds=median(latencies) if latencies else None,
        detection_latency_p95_seconds=(
            float(np.percentile(sorted_latency, 95)) if latencies else None
        ),
    )
    return metrics, matches


def binary_window_metrics(
    actual_fall: Sequence[bool], scores: Sequence[float], threshold: float
) -> dict[str, float | int]:
    actual = np.asarray(actual_fall, dtype=bool)
    score = np.asarray(scores, dtype=np.float64)
    predicted = score >= threshold
    tp = int(np.sum(actual & predicted))
    fn = int(np.sum(actual & ~predicted))
    fp = int(np.sum(~actual & predicted))
    tn = int(np.sum(~actual & ~predicted))
    recall = tp / (tp + fn) if tp + fn else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    return {
        "threshold": threshold,
        "fall_recall": recall,
        "fall_precision": precision,
        "f1": f1,
        "false_negative_count": fn,
        "false_positive_count": fp,
        "true_positive_count": tp,
        "true_negative_count": tn,
    }


def threshold_curve(
    actual_fall: Sequence[bool], scores: Sequence[float]
) -> list[dict[str, float | int]]:
    thresholds = sorted({0.0, 1.0, *(float(value) for value in scores)}, reverse=True)
    return [binary_window_metrics(actual_fall, scores, value) for value in thresholds]


def pr_roc_curve(
    actual_fall: Sequence[bool], scores: Sequence[float]
) -> list[dict[str, float | int]]:
    """Return a serializable combined PR/ROC curve without row-level leakage."""
    actual = np.asarray(actual_fall, dtype=bool)
    negatives = int(np.count_nonzero(~actual))
    rows: list[dict[str, float | int]] = []
    for row in threshold_curve(actual_fall, scores):
        fp = int(row["false_positive_count"])
        rows.append(
            {
                **row,
                "true_positive_rate": float(row["fall_recall"]),
                "false_positive_rate": fp / negatives if negatives else 0.0,
            }
        )
    return rows


def choose_recall_threshold(
    actual_fall: Sequence[bool],
    scores: Sequence[float],
    *,
    target_recall: float = 0.95,
) -> dict[str, float | int] | None:
    """Pick the highest-precision threshold that satisfies target recall."""
    if not 0 < target_recall <= 1:
        raise ValueError("target_recall must be in (0, 1]")
    eligible = [
        row
        for row in threshold_curve(actual_fall, scores)
        if float(row["fall_recall"]) >= target_recall
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda row: (
            float(row["fall_precision"]),
            float(row["threshold"]),
        ),
    )


def leave_one_group_out(
    rows: Sequence[Mapping[str, object]], group_key: str
) -> list[tuple[list[int], list[int], str]]:
    groups = sorted({str(row.get(group_key, "")) for row in rows if row.get(group_key)})
    return [
        (
            [index for index, row in enumerate(rows) if str(row.get(group_key, "")) != group],
            [index for index, row in enumerate(rows) if str(row.get(group_key, "")) == group],
            group,
        )
        for group in groups
    ]


def save_experiment_record(
    output_path: Path,
    *,
    experiment_id: str,
    dataset_version: str,
    configuration: Mapping[str, object],
    metrics: Mapping[str, object] | EventMetrics,
    notes: Iterable[str] = (),
) -> Path:
    payload = {
        "experimentId": experiment_id,
        "datasetVersion": dataset_version,
        "configuration": dict(configuration),
        "metrics": asdict(metrics) if isinstance(metrics, EventMetrics) else dict(metrics),
        "notes": list(notes),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output_path
