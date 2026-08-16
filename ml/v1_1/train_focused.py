"""Evaluate excluding jump and squat from the primary ESP-Fi HAR task."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.metrics import confusion_matrix

V1_DIR = Path(__file__).resolve().parents[1] / "v1"
sys.path.insert(0, str(V1_DIR))
from train_hierarchical import (  # noqa: E402
    META,
    TARGET_LABELS,
    classifier,
    collapse_predictions,
    load_or_extract,
    score,
    write_csv,
)

DEFAULT_DATA = Path("ml/dataset/raw/ESP-Fi-HAR-full")
DEFAULT_FEATURES = Path("ml/v1/output/features.csv")
DEFAULT_OUTPUT = Path("ml/v1_1/output")
EXCLUDED_ACTIONS = frozenset({"jump", "squat"})
CORE_ACTIONS = frozenset({"fall", "walk", "run", "turn", "arm_wave"})
STRATEGIES = ("all_7_actions", "focused_5_actions")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def load_rows(data: Path, features: Path, output: Path) -> list[dict]:
    if features.exists():
        rows = read_csv(features)
        if rows and "raw_duplicate_packet_count" in rows[0]:
            return rows
    return load_or_extract(data, output / "features.csv")


def feature_columns(row: dict) -> list[str]:
    excluded = {
        "tail_quiet_fraction", "post_peak_longest_quiet_fraction",
        "post_peak_longest_quiet_seconds", "tail_to_p90_energy_ratio",
        "strongest_peak_position", "raw_packet_count", "raw_duration_seconds",
        "raw_sampling_rate_hz", "raw_interval_p95_ms", "raw_invalid_row_count",
        "raw_duplicate_packet_count", "raw_nonmonotonic_packet_count",
        "inactivity_available",
    }
    return [
        name for name in row
        if name not in META and not name.startswith("inactivity") and name not in excluded
    ]


def core_mask(original: np.ndarray) -> np.ndarray:
    return np.asarray([label not in EXCLUDED_ACTIONS for label in original], dtype=bool)


def summarize_folds(rows: list[dict]) -> list[dict]:
    metrics = (
        "accuracy", "macro_f1", "balanced_accuracy", "fall_precision",
        "fall_recall", "fall_f1", "walking_f1",
    )
    summaries = []
    for protocol in sorted({row["protocol"] for row in rows}):
        for strategy in STRATEGIES:
            selected = [
                row for row in rows
                if row["protocol"] == protocol and row["strategy"] == strategy
            ]
            summary = {"protocol": protocol, "strategy": strategy, "folds": len(selected)}
            for metric in metrics:
                values = np.asarray([float(row[metric]) for row in selected])
                summary[f"{metric}_mean"] = float(values.mean())
                summary[f"{metric}_std"] = float(values.std())
            summaries.append(summary)
    return summaries


def summarize_ood(predictions: list[dict]) -> list[dict]:
    summaries = []
    protocols = sorted({row["protocol"] for row in predictions})
    for protocol in protocols:
        protocol_rows = [row for row in predictions if row["protocol"] == protocol]
        for label in ("jump", "squat", "combined"):
            selected = protocol_rows if label == "combined" else [
                row for row in protocol_rows if row["original_label"] == label
            ]
            counts = Counter(row["prediction"] for row in selected)
            total = len(selected)
            summaries.append({
                "protocol": protocol,
                "original_label": label,
                "samples": total,
                "fall_suspected_count": counts["fall_suspected"],
                "fall_suspected_rate": counts["fall_suspected"] / total,
                "walking_count": counts["walking"],
                "walking_rate": counts["walking"] / total,
                "other_motion_count": counts["other_motion"],
                "other_motion_rate": counts["other_motion"] / total,
            })
    return summaries


def evaluate_protocol(
    protocol: str,
    groups: np.ndarray,
    x: np.ndarray,
    target: np.ndarray,
    original: np.ndarray,
    metadata: list[dict],
    output: Path,
) -> tuple[list[dict], list[dict], list[dict]]:
    core = core_mask(original)
    fold_rows: list[dict] = []
    core_predictions: list[dict] = []
    ood_predictions: list[dict] = []
    complete_predictions = {
        strategy: np.empty(int(core.sum()), dtype=object) for strategy in STRATEGIES
    }
    core_indices = np.flatnonzero(core)
    core_position = {index: position for position, index in enumerate(core_indices)}

    for held_out in sorted(set(groups), key=str):
        train_group = groups != held_out
        test_group = ~train_group
        core_test = test_group & core
        focused_train = train_group & core

        models = {
            "all_7_actions": classifier().fit(x[train_group], original[train_group]),
            "focused_5_actions": classifier().fit(x[focused_train], original[focused_train]),
        }
        for strategy, model in models.items():
            prediction = collapse_predictions(model.predict(x[core_test]))
            positions = [core_position[index] for index in np.flatnonzero(core_test)]
            complete_predictions[strategy][positions] = prediction
            fold_rows.append({
                "protocol": protocol,
                "held_out": held_out,
                "strategy": strategy,
                "train_samples": int(train_group.sum() if strategy == "all_7_actions" else focused_train.sum()),
                "test_samples": int(core_test.sum()),
                **score(target[core_test], prediction),
            })
            for index, predicted in zip(np.flatnonzero(core_test), prediction):
                core_predictions.append({
                    "protocol": protocol, "held_out": held_out, "strategy": strategy,
                    "scenario": metadata[index]["scenario"],
                    "participant": metadata[index]["participant"],
                    "original_label": original[index], "target_label": target[index],
                    "prediction": predicted, "path": metadata[index]["path"],
                })

        ood_test = test_group & ~core
        ood_prediction = collapse_predictions(models["focused_5_actions"].predict(x[ood_test]))
        for index, predicted in zip(np.flatnonzero(ood_test), ood_prediction):
            ood_predictions.append({
                "protocol": protocol, "held_out": held_out,
                "scenario": metadata[index]["scenario"],
                "participant": metadata[index]["participant"],
                "original_label": original[index], "prediction": predicted,
                "path": metadata[index]["path"],
            })

    for strategy, prediction in complete_predictions.items():
        matrix = confusion_matrix(target[core], prediction, labels=TARGET_LABELS)
        write_csv(output / f"confusion_{protocol}_{strategy}.csv", [
            {
                "actual": label,
                **{predicted: int(value) for predicted, value in zip(TARGET_LABELS, values)},
            }
            for label, values in zip(TARGET_LABELS, matrix)
        ])
    return fold_rows, core_predictions, ood_predictions


def run(data: Path, features: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    rows = load_rows(data, features, output)
    names = feature_columns(rows[0])
    x = np.asarray([[float(row[name]) for name in names] for row in rows])
    target = np.asarray([str(row["label"]) for row in rows])
    original = np.asarray([str(row["original_label"]) for row in rows])
    participant = np.asarray([str(row["participant"]) for row in rows])
    scenario = np.asarray([str(row["scenario"]) for row in rows])

    if set(original) != CORE_ACTIONS | EXCLUDED_ACTIONS:
        raise ValueError(f"unexpected action set: {sorted(set(original))}")

    folds: list[dict] = []
    predictions: list[dict] = []
    ood_predictions: list[dict] = []
    for protocol, groups in (
        ("leave_one_participant_out", participant),
        ("leave_one_environment_out", scenario),
    ):
        protocol_folds, protocol_predictions, protocol_ood = evaluate_protocol(
            protocol, groups, x, target, original, rows, output,
        )
        folds.extend(protocol_folds)
        predictions.extend(protocol_predictions)
        ood_predictions.extend(protocol_ood)

    summaries = summarize_folds(folds)
    ood_summaries = summarize_ood(ood_predictions)
    write_csv(output / "fold_metrics.csv", folds)
    write_csv(output / "model_summary.csv", summaries)
    write_csv(output / "predictions.csv", predictions)
    write_csv(output / "ood_predictions.csv", ood_predictions)
    write_csv(output / "ood_summary.csv", ood_summaries)

    core = core_mask(original)
    result = {
        "dataset": "ESP-Fi HAR complete archive",
        "total_samples": len(rows),
        "primary_evaluation_samples": int(core.sum()),
        "ood_safety_samples": int((~core).sum()),
        "included_actions": sorted(CORE_ACTIONS),
        "excluded_actions": sorted(EXCLUDED_ACTIONS),
        "target_labels": dict(Counter(target[core])),
        "feature_count": len(names),
        "classifier": "class-balanced multinomial LogisticRegression",
        "summary": summaries,
        "ood_summary": ood_summaries,
    }
    (output / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.input, args.features, args.output)
    for row in result["summary"]:
        print(
            f"{row['protocol']} / {row['strategy']}: "
            f"accuracy={100 * row['accuracy_mean']:.2f}%, "
            f"macro_f1={100 * row['macro_f1_mean']:.2f}%, "
            f"fall_p/r/f1={100 * row['fall_precision_mean']:.2f}/"
            f"{100 * row['fall_recall_mean']:.2f}/{100 * row['fall_f1_mean']:.2f}%, "
            f"walking_f1={100 * row['walking_f1_mean']:.2f}%"
        )
    for row in result["ood_summary"]:
        if row["original_label"] == "combined":
            print(
                f"{row['protocol']} / excluded OOD: "
                f"fall_false_alarm={100 * row['fall_suspected_rate']:.2f}%"
            )
    print(f"output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

