"""Error analysis and small strategy comparison for ESP-Fi HAR v0."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.io import loadmat
from sklearn.base import clone
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)

V0_DIR = Path(__file__).resolve().parents[1] / "v0"
sys.path.insert(0, str(V0_DIR))

from analyze_feasibility import DEFAULT_DATA, load_rows, models, write_csv  # noqa: E402

DEFAULT_OUTPUT = Path("ml/v0_1/output")
TARGET_LABELS = ["fall_suspected", "other_motion", "walking"]
META_COLUMNS = {
    "scenario", "participant", "activity_id", "trial", "original_label",
    "label", "source_split", "path",
}


def collapse_label(label: str) -> str:
    if label == "walk":
        return "walking"
    if label == "fall":
        return "fall_suspected"
    return "other_motion"


def temporal_feature_names() -> list[str]:
    names = ["peak_position", "peak_to_median"]
    for width in (25, 50, 100, 200):
        names.extend([
            f"pre_peak_mean_{width}", f"post_peak_mean_{width}",
            f"post_pre_ratio_{width}", f"pre_post_contrast_{width}",
        ])
    names.extend([
        "energy_q10_position", "energy_q25_position", "energy_q50_position",
        "energy_q75_position", "energy_q90_position", "energy_width_80",
        "energy_width_50", "energy_entropy", "active_fraction",
    ])
    names.extend(f"peak_aligned_block_{offset:+03d}" for offset in range(-10, 11))
    return names


def temporal_features(amplitude: np.ndarray) -> np.ndarray:
    """Describe event timing around the strongest smoothed CSI change."""
    x = np.asarray(amplitude, dtype=np.float64)
    if x.shape == (52, 950):
        x = x.T
    if x.shape != (950, 52):
        raise ValueError(f"expected (950, 52), got {x.shape}")
    x = (x - x.mean()) / (x.std() + 1e-8)
    energy = np.mean(np.abs(np.diff(x, axis=0)), axis=1)
    smooth = np.convolve(energy, np.ones(15) / 15, mode="same")
    length = len(smooth)
    peak = int(np.argmax(smooth))
    median = float(np.median(smooth))
    values = [peak / (length - 1), float(smooth[peak] / (median + 1e-8))]

    for width in (25, 50, 100, 200):
        before = smooth[max(0, peak - width):peak]
        after = smooth[peak + 1:min(length, peak + 1 + width)]
        pre = float(before.mean()) if len(before) else float(smooth[peak])
        post = float(after.mean()) if len(after) else float(smooth[peak])
        values.extend([pre, post, post / (pre + 1e-8), (pre - post) / (pre + post + 1e-8)])

    weights = smooth / (smooth.sum() + 1e-12)
    cumulative = np.cumsum(weights)
    positions = [float(np.searchsorted(cumulative, q) / (length - 1)) for q in (.10, .25, .50, .75, .90)]
    entropy = float(-(weights * np.log(weights + 1e-12)).sum() / np.log(length))
    active = float(np.mean(smooth > median + np.std(smooth)))
    values.extend(positions + [positions[4] - positions[0], positions[3] - positions[1], entropy, active])

    for offset in range(-10, 11):
        start = peak + offset * 25
        stop = start + 25
        block = smooth[max(0, start):min(length, stop)]
        values.append(float(block.mean()) if len(block) else median)
    return np.asarray(values, dtype=np.float64)


def temporal_matrix(rows: list[dict]) -> np.ndarray:
    return np.asarray([temporal_features(loadmat(str(row["path"]))["CSIamp"]) for row in rows])


def score(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    precision, recall, f1, _ = precision_recall_fscore_support(
        actual, predicted, labels=TARGET_LABELS, zero_division=0,
    )
    fall_index = TARGET_LABELS.index("fall_suspected")
    return {
        "accuracy": float(accuracy_score(actual, predicted)),
        "macro_f1": float(f1_score(actual, predicted, average="macro")),
        "balanced_accuracy": float(balanced_accuracy_score(actual, predicted)),
        "fall_precision": float(precision[fall_index]),
        "fall_recall": float(recall[fall_index]),
        "fall_f1": float(f1[fall_index]),
    }


def run(input_dir: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    rows = load_rows(input_dir)
    base_names = [name for name in rows[0] if name not in META_COLUMNS]
    base = np.asarray([[float(row[name]) for name in base_names] for row in rows])
    temporal = temporal_matrix(rows)
    target = np.asarray([str(row["label"]) for row in rows])
    original = np.asarray([str(row["original_label"]) for row in rows])
    participants = np.asarray([str(row["participant"]) for row in rows])
    people = sorted(set(participants), key=int)

    strategies = {
        "direct_3class_base45": (base, target, False),
        "train_7class_then_collapse_base45": (base, original, True),
        "direct_3class_plus_temporal": (np.column_stack([base, temporal]), target, False),
        "train_7class_then_collapse_plus_temporal": (np.column_stack([base, temporal]), original, True),
    }
    estimators = {name: estimator for name, estimator in models().items() if name != "nearest_centroid"}
    prediction_rows: list[dict] = []
    fold_rows: list[dict] = []
    summary_rows: list[dict] = []

    for strategy, (features, training_labels, collapse) in strategies.items():
        for model_name, estimator in estimators.items():
            oof = np.empty(len(rows), dtype=object)
            for held_out in people:
                train = participants != held_out
                test = ~train
                raw = clone(estimator).fit(features[train], training_labels[train]).predict(features[test])
                predicted = np.asarray([collapse_label(str(value)) for value in raw]) if collapse else raw
                oof[test] = predicted
                fold_rows.append({
                    "strategy": strategy, "model": model_name,
                    "held_out_participant": held_out, **score(target[test], predicted),
                })

            selected_folds = [row for row in fold_rows if row["strategy"] == strategy and row["model"] == model_name]
            pooled = score(target, oof)
            pooled.update({
                "strategy": strategy, "model": model_name,
                "feature_count": int(features.shape[1]),
                "fold_macro_f1_mean": float(np.mean([row["macro_f1"] for row in selected_folds])),
                "fold_macro_f1_std": float(np.std([row["macro_f1"] for row in selected_folds])),
            })
            summary_rows.append(pooled)
            for row, prediction in zip(rows, oof):
                prediction_rows.append({
                    "strategy": strategy, "model": model_name,
                    "participant": row["participant"], "trial": row["trial"],
                    "original_label": row["original_label"], "target_label": row["label"],
                    "prediction": prediction, "path": row["path"],
                })

            matrix = confusion_matrix(target, oof, labels=TARGET_LABELS)
            write_csv(output / f"confusion_{strategy}_{model_name}.csv", [
                {"actual": label, **{predicted: int(value) for predicted, value in zip(TARGET_LABELS, values)}}
                for label, values in zip(TARGET_LABELS, matrix)
            ])

    false_positive_rows = []
    for summary in summary_rows:
        chosen = [row for row in prediction_rows if row["strategy"] == summary["strategy"] and row["model"] == summary["model"]]
        counts = Counter(
            str(row["original_label"]) for row in chosen
            if row["prediction"] == "fall_suspected" and row["target_label"] != "fall_suspected"
        )
        for original_label in sorted(set(original)):
            if original_label != "fall":
                false_positive_rows.append({
                    "strategy": summary["strategy"], "model": summary["model"],
                    "original_label": original_label, "false_positive_fall_count": counts[original_label],
                })

    best = max(summary_rows, key=lambda row: row["fall_f1"])
    best_predictions = [
        row for row in prediction_rows
        if row["strategy"] == best["strategy"] and row["model"] == best["model"]
    ]
    participant_rows = []
    for person in people:
        chosen = [row for row in best_predictions if row["participant"] == person]
        participant_rows.append({
            "strategy": best["strategy"], "model": best["model"], "participant": person,
            **score(np.asarray([row["target_label"] for row in chosen]), np.asarray([row["prediction"] for row in chosen])),
        })

    temporal_rows = []
    temporal_names = temporal_feature_names()
    for label in sorted(set(original)):
        selected = temporal[original == label]
        temporal_rows.append({
            "original_label": label, "samples": len(selected),
            **{name: float(value) for name, value in zip(temporal_names, np.median(selected, axis=0))},
        })

    write_csv(output / "strategy_summary.csv", summary_rows)
    write_csv(output / "fold_metrics.csv", fold_rows)
    write_csv(output / "predictions.csv", prediction_rows)
    write_csv(output / "fall_false_positives_by_original_label.csv", false_positive_rows)
    write_csv(output / "best_strategy_fall_by_participant.csv", participant_rows)
    write_csv(output / "temporal_feature_medians.csv", temporal_rows)
    result = {
        "dataset": "ESP-Fi HAR scenario 3 processed amplitude subset",
        "samples": len(rows), "scenarios": dict(Counter(str(row["scenario"]) for row in rows)),
        "participants": people, "original_labels": dict(Counter(original)),
        "target_labels": dict(Counter(target)), "base_feature_count": len(base_names),
        "added_temporal_feature_count": len(temporal_names),
        "summary": summary_rows, "best_fall_f1_strategy": best,
    }
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.input, args.output)
    for row in result["summary"]:
        print(
            f"{row['strategy']} / {row['model']}: "
            f"macro_f1={100 * row['macro_f1']:.2f}%, "
            f"fall_p/r/f1={100 * row['fall_precision']:.2f}/"
            f"{100 * row['fall_recall']:.2f}/{100 * row['fall_f1']:.2f}%"
        )
    print(f"output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
