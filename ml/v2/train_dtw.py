"""DTW-only and DTW-plus-statistical-feature experiments for ESP-Fi HAR."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.io import loadmat
from sklearn.metrics import confusion_matrix

V1_DIR = Path(__file__).resolve().parents[1] / "v1"
V1_1_DIR = Path(__file__).resolve().parents[1] / "v1_1"
sys.path.insert(0, str(V1_DIR))
sys.path.insert(0, str(V1_1_DIR))
from train_hierarchical import (  # noqa: E402
    classifier,
    collapse_predictions,
    score,
    write_csv,
)
from train_focused import (  # noqa: E402
    CORE_ACTIONS,
    EXCLUDED_ACTIONS,
    feature_columns,
    load_rows,
)

DEFAULT_DATA = Path("ml/dataset/raw/ESP-Fi-HAR-full")
DEFAULT_FEATURES = Path("ml/v1/output/features.csv")
DEFAULT_OUTPUT = Path("ml/v2/output")
METHODS = ("v2_a_dtw", "v2_b_stats_plus_dtw")
TRAINING_VARIANTS = ("all_7_actions", "focused_5_actions")
WAVEFORM_LENGTH = 64
DTW_WINDOW = 10


def motion_waveform(amplitude: np.ndarray, length: int = WAVEFORM_LENGTH) -> np.ndarray:
    """Create a fixed-size, shape-normalized motion-energy waveform."""
    x = np.asarray(amplitude, dtype=np.float64)
    if x.shape == (52, 950):
        x = x.T
    if x.shape != (950, 52):
        raise ValueError(f"expected (950, 52), got {x.shape}")
    if not np.isfinite(x).all():
        raise ValueError("non-finite amplitude")

    x = (x - x.mean()) / (x.std() + 1e-8)
    energy = np.mean(np.abs(np.diff(x, axis=0)), axis=1)
    smooth = np.convolve(energy, np.ones(15, dtype=float) / 15.0, mode="same")
    # Block averaging reduces noise without assigning an unverified physical sampling rate.
    boundaries = np.linspace(0, len(smooth), length + 1, dtype=int)
    waveform = np.asarray([
        smooth[boundaries[index]:boundaries[index + 1]].mean()
        for index in range(length)
    ])
    return (waveform - waveform.mean()) / (waveform.std() + 1e-8)


def load_waveforms(rows: list[dict], cache: Path) -> np.ndarray:
    if cache.exists():
        waveforms = np.load(cache)["waveforms"]
        if waveforms.shape == (len(rows), WAVEFORM_LENGTH):
            return waveforms
    values = []
    for index, row in enumerate(rows, start=1):
        path = Path(str(row["path"]))
        mat = loadmat(path)
        values.append(motion_waveform(mat["CSIamp"]))
        if index % 280 == 0:
            print(f"waveforms: {index}/{len(rows)}")
    waveforms = np.asarray(values)
    np.savez_compressed(cache, waveforms=waveforms)
    return waveforms


def dtw_distance(first: np.ndarray, second: np.ndarray, window: int = DTW_WINDOW) -> float:
    """Sakoe-Chiba constrained DTW distance for two one-dimensional series."""
    a = np.asarray(first, dtype=float)
    b = np.asarray(second, dtype=float)
    n, m = len(a), len(b)
    width = max(window, abs(n - m))
    previous = np.full(m + 1, np.inf)
    previous[0] = 0.0
    for i in range(1, n + 1):
        current = np.full(m + 1, np.inf)
        start = max(1, i - width)
        stop = min(m, i + width)
        for j in range(start, stop + 1):
            cost = (a[i - 1] - b[j - 1]) ** 2
            current[j] = cost + min(current[j - 1], previous[j], previous[j - 1])
        previous = current
    return float(np.sqrt(previous[m] / (n + m)))


def build_templates(
    waveforms: np.ndarray, labels: np.ndarray, train: np.ndarray, actions: list[str]
) -> dict[str, np.ndarray]:
    templates = {}
    for action in actions:
        selected = waveforms[train & (labels == action)]
        if not len(selected):
            raise ValueError(f"no training waveform for {action}")
        template = np.median(selected, axis=0)
        templates[action] = (template - template.mean()) / (template.std() + 1e-8)
    return templates


def distance_matrix(
    waveforms: np.ndarray, templates: dict[str, np.ndarray], indices: np.ndarray
) -> np.ndarray:
    actions = list(templates)
    return np.asarray([
        [dtw_distance(waveforms[index], templates[action]) for action in actions]
        for index in indices
    ])


def nearest_template_predictions(distances: np.ndarray, actions: list[str]) -> np.ndarray:
    original = np.asarray([actions[index] for index in np.argmin(distances, axis=1)])
    return collapse_predictions(original)


def summarize_folds(rows: list[dict]) -> list[dict]:
    metrics = (
        "accuracy", "macro_f1", "balanced_accuracy", "fall_precision",
        "fall_recall", "fall_f1", "walking_f1",
    )
    summaries = []
    protocols = sorted({row["protocol"] for row in rows})
    for protocol in protocols:
        for method in METHODS:
            for variant in TRAINING_VARIANTS:
                selected = [
                    row for row in rows
                    if row["protocol"] == protocol and row["method"] == method
                    and row["training_variant"] == variant
                ]
                summary = {
                    "protocol": protocol, "method": method,
                    "training_variant": variant, "folds": len(selected),
                }
                for metric in metrics:
                    values = np.asarray([float(row[metric]) for row in selected])
                    summary[f"{metric}_mean"] = float(values.mean())
                    summary[f"{metric}_std"] = float(values.std())
                summaries.append(summary)
    return summaries


def summarize_ood(rows: list[dict]) -> list[dict]:
    summaries = []
    protocols = sorted({row["protocol"] for row in rows})
    for protocol in protocols:
        for method in METHODS:
            method_rows = [
                row for row in rows
                if row["protocol"] == protocol and row["method"] == method
            ]
            for label in ("jump", "squat", "combined"):
                selected = method_rows if label == "combined" else [
                    row for row in method_rows if row["original_label"] == label
                ]
                counts = Counter(row["prediction"] for row in selected)
                total = len(selected)
                summaries.append({
                    "protocol": protocol, "method": method, "original_label": label,
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
    stats: np.ndarray,
    waveforms: np.ndarray,
    target: np.ndarray,
    original: np.ndarray,
    metadata: list[dict],
    output: Path,
) -> tuple[list[dict], list[dict], list[dict]]:
    core = np.asarray([label not in EXCLUDED_ACTIONS for label in original])
    core_indices = np.flatnonzero(core)
    core_position = {index: position for position, index in enumerate(core_indices)}
    all_predictions = {
        (method, variant): np.empty(len(core_indices), dtype=object)
        for method in METHODS for variant in TRAINING_VARIANTS
    }
    folds: list[dict] = []
    predictions: list[dict] = []
    ood_predictions: list[dict] = []

    for held_out in sorted(set(groups), key=str):
        train_group = groups != held_out
        test_group = ~train_group
        core_test = test_group & core
        ood_test = test_group & ~core

        for variant in TRAINING_VARIANTS:
            train = train_group if variant == "all_7_actions" else train_group & core
            actions = sorted(set(original[train]))
            templates = build_templates(waveforms, original, train, actions)
            train_indices = np.flatnonzero(train)
            core_test_indices = np.flatnonzero(core_test)
            train_distances = distance_matrix(waveforms, templates, train_indices)
            test_distances = distance_matrix(waveforms, templates, core_test_indices)

            method_predictions = {
                "v2_a_dtw": nearest_template_predictions(test_distances, actions),
            }
            hybrid_train = np.column_stack((stats[train], train_distances))
            hybrid_test = np.column_stack((stats[core_test], test_distances))
            hybrid_model = classifier().fit(hybrid_train, original[train])
            method_predictions["v2_b_stats_plus_dtw"] = collapse_predictions(
                hybrid_model.predict(hybrid_test)
            )

            positions = [core_position[index] for index in core_test_indices]
            for method, predicted in method_predictions.items():
                all_predictions[(method, variant)][positions] = predicted
                folds.append({
                    "protocol": protocol, "held_out": held_out, "method": method,
                    "training_variant": variant, "train_samples": int(train.sum()),
                    "test_samples": int(core_test.sum()), **score(target[core_test], predicted),
                })
                for index, value in zip(core_test_indices, predicted):
                    predictions.append({
                        "protocol": protocol, "held_out": held_out, "method": method,
                        "training_variant": variant,
                        "scenario": metadata[index]["scenario"],
                        "participant": metadata[index]["participant"],
                        "original_label": original[index], "target_label": target[index],
                        "prediction": value, "path": metadata[index]["path"],
                    })

            if variant == "focused_5_actions":
                ood_indices = np.flatnonzero(ood_test)
                ood_distances = distance_matrix(waveforms, templates, ood_indices)
                ood_method_predictions = {
                    "v2_a_dtw": nearest_template_predictions(ood_distances, actions),
                    "v2_b_stats_plus_dtw": collapse_predictions(hybrid_model.predict(
                        np.column_stack((stats[ood_test], ood_distances))
                    )),
                }
                for method, predicted in ood_method_predictions.items():
                    for index, value in zip(ood_indices, predicted):
                        ood_predictions.append({
                            "protocol": protocol, "held_out": held_out, "method": method,
                            "scenario": metadata[index]["scenario"],
                            "participant": metadata[index]["participant"],
                            "original_label": original[index], "prediction": value,
                            "path": metadata[index]["path"],
                        })

    for (method, variant), predicted in all_predictions.items():
        matrix = confusion_matrix(target[core], predicted, labels=[
            "fall_suspected", "other_motion", "walking",
        ])
        labels = ["fall_suspected", "other_motion", "walking"]
        write_csv(output / f"confusion_{protocol}_{method}_{variant}.csv", [
            {
                "actual": label,
                **{prediction: int(value) for prediction, value in zip(labels, values)},
            }
            for label, values in zip(labels, matrix)
        ])
    return folds, predictions, ood_predictions


def run(data: Path, features: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    rows = load_rows(data, features, output)
    names = feature_columns(rows[0])
    stats = np.asarray([[float(row[name]) for name in names] for row in rows])
    target = np.asarray([str(row["label"]) for row in rows])
    original = np.asarray([str(row["original_label"]) for row in rows])
    participant = np.asarray([str(row["participant"]) for row in rows])
    scenario = np.asarray([str(row["scenario"]) for row in rows])
    if set(original) != CORE_ACTIONS | EXCLUDED_ACTIONS:
        raise ValueError(f"unexpected action set: {sorted(set(original))}")
    waveforms = load_waveforms(rows, output / "waveforms.npz")

    folds: list[dict] = []
    predictions: list[dict] = []
    ood_predictions: list[dict] = []
    for protocol, groups in (
        ("leave_one_participant_out", participant),
        ("leave_one_environment_out", scenario),
    ):
        new_folds, new_predictions, new_ood = evaluate_protocol(
            protocol, groups, stats, waveforms, target, original, rows, output,
        )
        folds.extend(new_folds)
        predictions.extend(new_predictions)
        ood_predictions.extend(new_ood)

    summary = summarize_folds(folds)
    ood_summary = summarize_ood(ood_predictions)
    write_csv(output / "fold_metrics.csv", folds)
    write_csv(output / "model_summary.csv", summary)
    write_csv(output / "predictions.csv", predictions)
    write_csv(output / "ood_predictions.csv", ood_predictions)
    write_csv(output / "ood_summary.csv", ood_summary)
    result = {
        "dataset": "ESP-Fi HAR complete archive",
        "samples": len(rows), "waveform_length": WAVEFORM_LENGTH,
        "dtw_window": DTW_WINDOW, "statistical_feature_count": len(names),
        "methods": list(METHODS), "training_variants": list(TRAINING_VARIANTS),
        "summary": summary, "ood_summary": ood_summary,
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
            f"{row['protocol']} / {row['method']} / {row['training_variant']}: "
            f"macro_f1={100 * row['macro_f1_mean']:.2f}%, "
            f"fall_p/r/f1={100 * row['fall_precision_mean']:.2f}/"
            f"{100 * row['fall_recall_mean']:.2f}/{100 * row['fall_f1_mean']:.2f}%, "
            f"walking_f1={100 * row['walking_f1_mean']:.2f}%"
        )
    print(f"output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

