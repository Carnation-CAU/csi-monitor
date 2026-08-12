"""Participant-independent feasibility test for ESP-Fi HAR CSI amplitude."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.io import loadmat
from scipy.signal import find_peaks
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score
from sklearn.neighbors import NearestCentroid
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

DEFAULT_DATA = Path("ml/dataset/raw/ESP-Fi-HAR/Model Code/Data")
DEFAULT_OUTPUT = Path("ml/v0/output/feasibility")
SEED = 42
TARGET_LABELS = {"walk": "walking", "fall": "fall_suspected"}


def stats(prefix: str, x: np.ndarray) -> dict[str, float]:
    return {
        f"{prefix}_mean": float(x.mean()),
        f"{prefix}_std": float(x.std()),
        f"{prefix}_max": float(x.max()),
        **{f"{prefix}_p{q}": float(np.percentile(x, q)) for q in (50, 75, 90, 95, 99)},
    }


def extract_features(amplitude: np.ndarray) -> dict[str, float]:
    """Convert time x subcarrier amplitude to common motion features."""
    x = np.asarray(amplitude, dtype=np.float64)
    if x.shape == (52, 950):
        x = x.T
    if x.shape != (950, 52):
        raise ValueError(f"expected (950, 52), got {x.shape}")
    if not np.isfinite(x).all():
        raise ValueError("non-finite amplitude")

    # The source loader confirms 950=time and applies per-sample Z-score.
    x = (x - x.mean()) / (x.std() + 1e-8)
    delta = np.diff(x, axis=0)
    energy = np.mean(np.abs(delta), axis=1)
    acceleration = np.mean(np.abs(np.diff(delta, axis=0)), axis=1)
    result = {**stats("motion", energy), **stats("acceleration", acceleration)}
    result.update(stats("subcarrier_temporal_std", np.std(x, axis=0)))

    prominence = max(float(energy.std()) * 0.5, 1e-8)
    peaks, props = find_peaks(energy, prominence=prominence)
    result["peak_count"] = float(len(peaks))
    result["peak_prominence_mean"] = float(props["prominences"].mean()) if len(peaks) else 0.0
    result["peak_prominence_max"] = float(props["prominences"].max()) if len(peaks) else 0.0

    centered = energy - energy.mean()
    denom = float(np.dot(centered, centered)) + 1e-12
    for lag in (5, 10, 20, 50):
        result[f"autocorrelation_lag_{lag}"] = float(np.dot(centered[:-lag], centered[lag:]) / denom)

    spectrum = np.abs(np.fft.rfft(centered)) ** 2
    frequency = np.fft.rfftfreq(len(centered))
    total = float(spectrum[1:].sum()) + 1e-12
    for name, low, high in (("very_low", 0, .05), ("low", .05, .15), ("mid", .15, .30), ("high", .30, .501)):
        mask = (frequency >= low) & (frequency < high)
        result[f"spectral_{name}_ratio"] = float(spectrum[mask].sum() / total)

    for index, block in enumerate(np.array_split(energy, 10)):
        result[f"motion_block_{index:02d}"] = float(block.mean())
    return result


def metadata(path: Path) -> dict[str, str]:
    scenario, participant, activity_id, trial = path.stem.split("-")
    original_label = path.parent.name
    return {
        "scenario": scenario, "participant": participant, "activity_id": activity_id,
        "trial": trial, "original_label": original_label,
        "label": TARGET_LABELS.get(original_label, "other_motion"),
        "source_split": "train" if "train_amp" in path.parts else "test", "path": str(path),
    }


def load_rows(root: Path) -> list[dict[str, str | float]]:
    rows = []
    for path in sorted(root.rglob("*.mat")):
        mat = loadmat(path)
        if "CSIamp" not in mat:
            raise ValueError(f"missing CSIamp: {path}")
        rows.append({**metadata(path), **extract_features(mat["CSIamp"])})
    if not rows:
        raise ValueError(f"no .mat files under {root}")
    return rows


def models():
    return {
        "nearest_centroid": make_pipeline(StandardScaler(), NearestCentroid()),
        "logistic_regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=5000, class_weight="balanced", random_state=SEED)),
        "random_forest": RandomForestClassifier(n_estimators=300, min_samples_leaf=2, max_features="sqrt", class_weight="balanced", random_state=SEED, n_jobs=-1),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def run(root: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    rows = load_rows(root)
    meta = {"scenario", "participant", "activity_id", "trial", "original_label", "label", "source_split", "path"}
    names = [name for name in rows[0] if name not in meta]
    labels = sorted({str(row["label"]) for row in rows})
    people = sorted({str(row["participant"]) for row in rows}, key=int)
    x = np.asarray([[float(row[name]) for name in names] for row in rows])
    y = np.asarray([str(row["label"]) for row in rows])
    group = np.asarray([str(row["participant"]) for row in rows])
    fold_rows = []
    matrices = {name: np.zeros((len(labels), len(labels)), dtype=int) for name in models()}

    # Leave one entire participant out: 490 train, 70 test per fold.
    for held_out in people:
        train, test = group != held_out, group == held_out
        for model_name, estimator in models().items():
            fitted = clone(estimator).fit(x[train], y[train])
            prediction = fitted.predict(x[test])
            matrices[model_name] += confusion_matrix(y[test], prediction, labels=labels)
            fold_rows.append({
                "model": model_name, "held_out_participant": held_out,
                "train_samples": int(train.sum()), "test_samples": int(test.sum()),
                "accuracy": float(accuracy_score(y[test], prediction)),
                "macro_f1": float(f1_score(y[test], prediction, average="macro")),
                "balanced_accuracy": float(balanced_accuracy_score(y[test], prediction)),
            })

    summary = []
    for model_name in models():
        selected = [row for row in fold_rows if row["model"] == model_name]
        accuracy = np.asarray([row["accuracy"] for row in selected])
        macro_f1 = np.asarray([row["macro_f1"] for row in selected])
        balanced = np.asarray([row["balanced_accuracy"] for row in selected])
        summary.append({
            "model": model_name, "folds": len(selected),
            "accuracy_mean": float(accuracy.mean()), "accuracy_std": float(accuracy.std()),
            "macro_f1_mean": float(macro_f1.mean()), "macro_f1_std": float(macro_f1.std()),
            "balanced_accuracy_mean": float(balanced.mean()), "balanced_accuracy_std": float(balanced.std()),
        })

    write_csv(output / "features.csv", rows)
    write_csv(output / "fold_metrics.csv", fold_rows)
    write_csv(output / "model_summary.csv", summary)
    for model_name, matrix in matrices.items():
        write_csv(output / f"confusion_{model_name}.csv", [
            {"actual": label, **{pred: int(value) for pred, value in zip(labels, values)}}
            for label, values in zip(labels, matrix)
        ])
    majority_label, majority_count = Counter(y).most_common(1)[0]
    majority_prediction = np.full_like(y, majority_label)
    result = {
        "dataset": "ESP-Fi HAR processed scenario 3 subset", "samples": len(rows),
        "labels": dict(Counter(y)),
        "original_labels": dict(Counter(str(row["original_label"]) for row in rows)),
        "participants": people, "feature_count": len(names), "features": names,
        "evaluation": "leave-one-participant-out (8 folds)",
        "uniform_chance_accuracy": 1 / len(labels),
        "majority_baseline": {
            "label": majority_label,
            "accuracy": majority_count / len(y),
            "macro_f1": float(f1_score(y, majority_prediction, average="macro")),
            "balanced_accuracy": float(balanced_accuracy_score(y, majority_prediction)),
        },
        "model_summary": summary,
    }
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.input, args.output)
    print(f"samples={result['samples']}, features={result['feature_count']}, uniform_chance={100*result['uniform_chance_accuracy']:.2f}%")
    print(f"majority({result['majority_baseline']['label']}): accuracy={100*result['majority_baseline']['accuracy']:.2f}%, macro_f1={100*result['majority_baseline']['macro_f1']:.2f}%")
    for row in result["model_summary"]:
        print(f"{row['model']}: accuracy={100*row['accuracy_mean']:.2f}% +/- {100*row['accuracy_std']:.2f}, macro_f1={100*row['macro_f1_mean']:.2f}%, balanced={100*row['balanced_accuracy_mean']:.2f}%")
    print(f"results={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())