"""Compare classical classifiers with/without DTW and excluded actions."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

# Prevent joblib's deprecated WMIC core probe on non-English Windows.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import confusion_matrix
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

V1_DIR = Path(__file__).resolve().parents[1] / "v1"
V1_1_DIR = Path(__file__).resolve().parents[1] / "v1_1"
V2_DIR = Path(__file__).resolve().parents[1] / "v2"
for module_dir in (V1_DIR, V1_1_DIR, V2_DIR):
    sys.path.insert(0, str(module_dir))

from train_hierarchical import collapse_predictions, score, write_csv  # noqa: E402
from train_focused import (  # noqa: E402
    CORE_ACTIONS,
    EXCLUDED_ACTIONS,
    feature_columns,
    load_rows,
)
from train_dtw import (  # noqa: E402
    build_templates,
    distance_matrix,
    load_waveforms,
)

DEFAULT_DATA = Path("ml/dataset/raw/ESP-Fi-HAR-full")
DEFAULT_FEATURES = Path("ml/v1/output/features.csv")
DEFAULT_WAVEFORMS = Path("ml/v2/output/waveforms.npz")
DEFAULT_OUTPUT = Path("ml/v4/output")
SEED = 42
MODEL_NAMES = ("random_forest", "hist_gradient_boosting", "rbf_svm")
FEATURE_VARIANTS = ("stats_only", "stats_plus_dtw")
TRAINING_VARIANTS = ("all_7_actions", "focused_5_actions")
TARGET_LABELS = ("fall_suspected", "other_motion", "walking")


def make_model(name: str):
    if name == "random_forest":
        return RandomForestClassifier(
            n_estimators=300,
            min_samples_leaf=2,
            max_features="sqrt",
            class_weight="balanced_subsample",
            random_state=SEED,
            # Process spawning is slower and emits WMIC encoding warnings on this
            # Windows environment; one process is deterministic and faster here.
            n_jobs=1,
        )
    if name == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=250,
            max_leaf_nodes=15,
            min_samples_leaf=20,
            l2_regularization=1.0,
            class_weight="balanced",
            random_state=SEED,
        )
    if name == "rbf_svm":
        return make_pipeline(
            StandardScaler(),
            SVC(C=1.0, kernel="rbf", gamma="scale", class_weight="balanced"),
        )
    raise ValueError(f"unknown model: {name}")


def model_parameters() -> dict[str, dict]:
    return {
        "random_forest": {
            "n_estimators": 300, "min_samples_leaf": 2,
            "max_features": "sqrt", "class_weight": "balanced_subsample",
            "n_jobs": 1,
        },
        "hist_gradient_boosting": {
            "learning_rate": 0.05, "max_iter": 250, "max_leaf_nodes": 15,
            "min_samples_leaf": 20, "l2_regularization": 1.0,
            "class_weight": "balanced",
        },
        "rbf_svm": {
            "scaler": "StandardScaler", "C": 1.0, "kernel": "rbf",
            "gamma": "scale", "class_weight": "balanced",
        },
    }


def combine_features(
    stats: np.ndarray,
    distances: np.ndarray,
    indices: np.ndarray,
    variant: str,
) -> np.ndarray:
    if variant == "stats_only":
        return stats[indices]
    if variant == "stats_plus_dtw":
        return np.column_stack((stats[indices], distances))
    raise ValueError(f"unknown feature variant: {variant}")


def summarize_folds(rows: list[dict]) -> list[dict]:
    metrics = (
        "accuracy", "macro_f1", "balanced_accuracy", "fall_precision",
        "fall_recall", "fall_f1", "walking_f1",
    )
    result = []
    protocols = sorted({row["protocol"] for row in rows})
    for protocol in protocols:
        for model_name in MODEL_NAMES:
            for feature_variant in FEATURE_VARIANTS:
                for training_variant in TRAINING_VARIANTS:
                    selected = [
                        row for row in rows
                        if row["protocol"] == protocol
                        and row["model"] == model_name
                        and row["feature_variant"] == feature_variant
                        and row["training_variant"] == training_variant
                    ]
                    summary = {
                        "protocol": protocol, "model": model_name,
                        "feature_variant": feature_variant,
                        "training_variant": training_variant,
                        "folds": len(selected),
                    }
                    for metric in metrics:
                        values = np.asarray([float(row[metric]) for row in selected])
                        summary[f"{metric}_mean"] = float(values.mean())
                        summary[f"{metric}_std"] = float(values.std())
                    result.append(summary)
    return result


def summarize_ood(rows: list[dict]) -> list[dict]:
    result = []
    protocols = sorted({row["protocol"] for row in rows})
    for protocol in protocols:
        for model_name in MODEL_NAMES:
            for feature_variant in FEATURE_VARIANTS:
                method_rows = [
                    row for row in rows
                    if row["protocol"] == protocol
                    and row["model"] == model_name
                    and row["feature_variant"] == feature_variant
                ]
                for label in ("jump", "squat", "combined"):
                    selected = method_rows if label == "combined" else [
                        row for row in method_rows if row["original_label"] == label
                    ]
                    counts = Counter(row["prediction"] for row in selected)
                    total = len(selected)
                    result.append({
                        "protocol": protocol, "model": model_name,
                        "feature_variant": feature_variant,
                        "original_label": label, "samples": total,
                        "fall_suspected_count": counts["fall_suspected"],
                        "fall_suspected_rate": counts["fall_suspected"] / total,
                        "walking_count": counts["walking"],
                        "walking_rate": counts["walking"] / total,
                        "other_motion_count": counts["other_motion"],
                        "other_motion_rate": counts["other_motion"] / total,
                    })
    return result


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
        (model, feature, training): np.empty(len(core_indices), dtype=object)
        for model in MODEL_NAMES
        for feature in FEATURE_VARIANTS
        for training in TRAINING_VARIANTS
    }
    folds: list[dict] = []
    predictions: list[dict] = []
    ood_predictions: list[dict] = []

    for held_out in sorted(set(groups), key=str):
        train_group = groups != held_out
        test_group = ~train_group
        core_test = test_group & core
        core_test_indices = np.flatnonzero(core_test)
        ood_test = test_group & ~core
        ood_indices = np.flatnonzero(ood_test)

        for training_variant in TRAINING_VARIANTS:
            train = train_group if training_variant == "all_7_actions" else train_group & core
            train_indices = np.flatnonzero(train)
            actions = sorted(set(original[train]))
            templates = build_templates(waveforms, original, train, actions)
            train_distances = distance_matrix(waveforms, templates, train_indices)
            test_distances = distance_matrix(waveforms, templates, core_test_indices)
            ood_distances = (
                distance_matrix(waveforms, templates, ood_indices)
                if training_variant == "focused_5_actions" else None
            )

            for feature_variant in FEATURE_VARIANTS:
                x_train = combine_features(stats, train_distances, train_indices, feature_variant)
                x_test = combine_features(stats, test_distances, core_test_indices, feature_variant)
                x_ood = (
                    combine_features(stats, ood_distances, ood_indices, feature_variant)
                    if ood_distances is not None else None
                )

                for model_name in MODEL_NAMES:
                    fitted = make_model(model_name).fit(x_train, original[train])
                    predicted = collapse_predictions(fitted.predict(x_test))
                    positions = [core_position[index] for index in core_test_indices]
                    all_predictions[(model_name, feature_variant, training_variant)][positions] = predicted
                    folds.append({
                        "protocol": protocol, "held_out": held_out,
                        "model": model_name, "feature_variant": feature_variant,
                        "training_variant": training_variant,
                        "train_samples": int(train.sum()), "test_samples": int(core_test.sum()),
                        **score(target[core_test], predicted),
                    })
                    for index, value in zip(core_test_indices, predicted):
                        predictions.append({
                            "protocol": protocol, "held_out": held_out,
                            "model": model_name, "feature_variant": feature_variant,
                            "training_variant": training_variant,
                            "scenario": metadata[index]["scenario"],
                            "participant": metadata[index]["participant"],
                            "original_label": original[index], "target_label": target[index],
                            "prediction": value, "path": metadata[index]["path"],
                        })
                    if training_variant == "focused_5_actions":
                        assert x_ood is not None
                        ood_predicted = collapse_predictions(fitted.predict(x_ood))
                        for index, value in zip(ood_indices, ood_predicted):
                            ood_predictions.append({
                                "protocol": protocol, "held_out": held_out,
                                "model": model_name, "feature_variant": feature_variant,
                                "scenario": metadata[index]["scenario"],
                                "participant": metadata[index]["participant"],
                                "original_label": original[index], "prediction": value,
                                "path": metadata[index]["path"],
                            })

    for (model_name, feature_variant, training_variant), predicted in all_predictions.items():
        matrix = confusion_matrix(target[core], predicted, labels=TARGET_LABELS)
        write_csv(
            output / (
                f"confusion_{protocol}_{model_name}_{feature_variant}_"
                f"{training_variant}.csv"
            ),
            [
                {
                    "actual": label,
                    **{prediction: int(value) for prediction, value in zip(TARGET_LABELS, values)},
                }
                for label, values in zip(TARGET_LABELS, matrix)
            ],
        )
    return folds, predictions, ood_predictions


def run(data: Path, features: Path, waveforms_path: Path, output: Path) -> dict:
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
    waveforms = load_waveforms(rows, waveforms_path)

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
        "dataset": "ESP-Fi HAR complete archive", "samples": len(rows),
        "statistical_feature_count": len(names), "models": model_parameters(),
        "feature_variants": list(FEATURE_VARIANTS),
        "training_variants": list(TRAINING_VARIANTS), "random_seed": SEED,
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
    parser.add_argument("--waveforms", type=Path, default=DEFAULT_WAVEFORMS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.input, args.features, args.waveforms, args.output)
    for row in result["summary"]:
        print(
            f"{row['protocol']} / {row['model']} / {row['feature_variant']} / "
            f"{row['training_variant']}: macro_f1={100 * row['macro_f1_mean']:.2f}%, "
            f"fall_p/r/f1={100 * row['fall_precision_mean']:.2f}/"
            f"{100 * row['fall_recall_mean']:.2f}/{100 * row['fall_f1_mean']:.2f}%, "
            f"walking_f1={100 * row['walking_f1_mean']:.2f}%"
        )
    print(f"output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
