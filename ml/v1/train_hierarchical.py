"""Classical-ML evaluation on the complete four-environment ESP-Fi HAR data."""
from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.io import loadmat
from sklearn.base import clone
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

V0_DIR = Path(__file__).resolve().parents[1] / "v0"
sys.path.insert(0, str(V0_DIR))
from analyze_feasibility import extract_features, write_csv  # noqa: E402

DEFAULT_DATA = Path("ml/dataset/raw/ESP-Fi-HAR-full")
DEFAULT_OUTPUT = Path("ml/v1/output")
SEED = 42

# Verified by exact array equality against scenario-3 benchmark label folders.
# The repository README's numeric action mapping does not match the archive.
ACTIVITY_BY_ID = {
    "1": "run", "2": "walk", "3": "jump", "4": "squat",
    "5": "arm_wave", "6": "turn", "7": "fall",
}
TARGET_LABELS = ["fall_suspected", "other_motion", "walking"]
META = {"scenario", "participant", "activity_id", "trial", "original_label", "label", "path"}


def collapse_label(label: str) -> str:
    if label == "fall":
        return "fall_suspected"
    if label == "walk":
        return "walking"
    return "other_motion"


def longest_true_run(values: np.ndarray) -> int:
    best = current = 0
    for value in values:
        current = current + 1 if value else 0
        best = max(best, current)
    return best


def inactivity_features(amplitude: np.ndarray, timestamps_us: np.ndarray | None = None) -> dict[str, float]:
    """Quietness after the strongest motion change; time-aware when timestamps exist."""
    x = np.asarray(amplitude, dtype=np.float64)
    if x.shape == (52, 950):
        x = x.T
    if x.ndim != 2 or x.shape[1] != 52 or x.shape[0] < 100:
        raise ValueError(f"expected time x 52 amplitude, got {x.shape}")
    x = (x - x.mean()) / (x.std() + 1e-8)
    energy = np.mean(np.abs(np.diff(x, axis=0)), axis=1)
    smooth = np.convolve(energy, np.ones(15) / 15, mode="same")
    length = len(smooth)
    peak = int(np.argmax(smooth))
    quiet_threshold = float(np.median(smooth) + 0.5 * np.std(smooth))
    if timestamps_us is None:
        timestamps_us = np.arange(len(x), dtype=float) * 10_000.0
    timestamps_us = np.asarray(timestamps_us, dtype=float)
    if len(timestamps_us) != len(x) or np.any(np.diff(timestamps_us) <= 0):
        raise ValueError("timestamps must be strictly increasing and match amplitude")
    energy_time_us = timestamps_us[1:]
    tail_start_us = energy_time_us[-1] - 1_000_000.0
    tail = smooth[energy_time_us >= tail_start_us]
    post_start_us = energy_time_us[peak] + 200_000.0
    post_mask = energy_time_us >= post_start_us
    post = smooth[post_mask]
    if not len(post):
        post = smooth[-1:]
    tail_quiet = float(np.mean(tail <= quiet_threshold))
    median_interval_seconds = float(np.median(np.diff(timestamps_us)) / 1_000_000.0)
    post_longest_seconds = float(longest_true_run(post <= quiet_threshold) * median_interval_seconds)
    post_longest = min(post_longest_seconds / 2.0, 1.0)
    tail_ratio = float(tail.mean() / (np.percentile(smooth, 90) + 1e-8))
    inactivity = 0.5 * tail_quiet + 0.5 * post_longest
    return {
        "inactivity_score": inactivity,
        "tail_quiet_fraction": tail_quiet,
        "post_peak_longest_quiet_fraction": post_longest,
        "post_peak_longest_quiet_seconds": post_longest_seconds,
        "tail_to_p90_energy_ratio": tail_ratio,
        "strongest_peak_position": peak / (length - 1),
    }


def raw_csv_features(path: Path) -> dict[str, float]:
    """Read raw IQ, remove duplicated packets, and measure device-time quietness."""
    amplitudes = []
    timestamps = []
    invalid_rows = 0
    duplicate_rows = 0
    seen_packets = set()
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            raw_data = (row.get("data") or "").strip()
            if not raw_data.startswith("["):
                invalid_rows += 1
                continue
            packet_key = (row.get("seq"), row.get("local_timestamp"))
            if packet_key in seen_packets:
                duplicate_rows += 1
                continue
            seen_packets.add(packet_key)
            iq = np.asarray(ast.literal_eval(raw_data), dtype=np.float64)
            if len(iq) != 104:
                invalid_rows += 1
                continue
            pairs = iq.reshape(52, 2)
            amplitudes.append(np.hypot(pairs[:, 0], pairs[:, 1]))
            timestamps.append(float(row["local_timestamp"]))
    clean_amplitudes = []
    clean_timestamps = []
    timestamp_drops = 0
    timestamp_offset = 0.0
    previous = -np.inf
    for amplitude_row, raw_timestamp in zip(amplitudes, timestamps):
        candidate = raw_timestamp + timestamp_offset
        if candidate <= previous and previous - candidate > 1_000_000_000.0:
            timestamp_offset += float(2 ** 32)
            candidate = raw_timestamp + timestamp_offset
        if candidate <= previous:
            timestamp_drops += 1
            continue
        clean_amplitudes.append(amplitude_row)
        clean_timestamps.append(candidate)
        previous = candidate
    amplitude = np.asarray(clean_amplitudes)
    timestamps_us = np.asarray(clean_timestamps)
    if len(amplitude) < 100:
        raise ValueError(f"too few valid CSI rows: {path}")
    timing = np.diff(timestamps_us) / 1_000_000.0
    result = inactivity_features(amplitude, timestamps_us)
    result.update({
        "raw_packet_count": float(len(amplitude)),
        "raw_duration_seconds": float((timestamps_us[-1] - timestamps_us[0]) / 1_000_000.0),
        "raw_sampling_rate_hz": float(1.0 / np.median(timing)),
        "raw_interval_p95_ms": float(1_000.0 * np.percentile(timing, 95)),
        "raw_invalid_row_count": float(invalid_rows),
        "raw_duplicate_packet_count": float(duplicate_rows),
        "raw_nonmonotonic_packet_count": float(timestamp_drops),
        "inactivity_available": float(len(amplitude) >= 950),
    })
    return result


def parse_metadata(path: Path) -> dict[str, str]:
    scenario, participant, activity_id, trial = path.stem.split("-")
    if activity_id not in ACTIVITY_BY_ID:
        raise ValueError(f"unknown activity id {activity_id}: {path}")
    original = ACTIVITY_BY_ID[activity_id]
    return {
        "scenario": scenario, "participant": participant,
        "activity_id": activity_id, "trial": trial,
        "original_label": original, "label": collapse_label(original),
        "path": str(path),
    }


def load_or_extract(data: Path, cache: Path) -> list[dict[str, str | float]]:
    paths = sorted(data.rglob("*.mat"))
    if not paths:
        raise ValueError(f"no MAT data below {data}")
    if cache.exists():
        with cache.open(encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))
        if len(rows) == len(paths) and "raw_duplicate_packet_count" in rows[0]:
            return rows

    rows: list[dict[str, str | float]] = []
    for index, path in enumerate(paths, start=1):
        mat = loadmat(path)
        if set(key for key in mat if not key.startswith("__")) != {"CSIamp"}:
            raise ValueError(f"unexpected MAT variables: {path}")
        amplitude = mat["CSIamp"]
        raw_path = path.parent.parent / "csv" / f"{path.stem}.csv"
        if not raw_path.exists():
            raise ValueError(f"raw CSV missing for {path}")
        rows.append({**parse_metadata(path), **extract_features(amplitude), **raw_csv_features(raw_path)})
        if index % 280 == 0:
            print(f"features: {index}/{len(paths)}")
    write_csv(cache, rows)
    return rows


def classifier() -> object:
    return make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=5000, class_weight="balanced", random_state=SEED),
    )


def score(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    precision, recall, f1, _ = precision_recall_fscore_support(
        actual, predicted, labels=TARGET_LABELS, zero_division=0,
    )
    fall = TARGET_LABELS.index("fall_suspected")
    walk = TARGET_LABELS.index("walking")
    return {
        "accuracy": float(accuracy_score(actual, predicted)),
        "macro_f1": float(f1_score(actual, predicted, average="macro")),
        "balanced_accuracy": float(balanced_accuracy_score(actual, predicted)),
        "fall_precision": float(precision[fall]), "fall_recall": float(recall[fall]),
        "fall_f1": float(f1[fall]), "walking_f1": float(f1[walk]),
    }


def binary_fall_probabilities(x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray) -> np.ndarray:
    binary = np.where(y_train == "fall_suspected", "fall", "non_fall")
    fitted = classifier().fit(x_train, binary)
    index = list(fitted.classes_).index("fall")
    return fitted.predict_proba(x_test)[:, index]


def walking_probabilities(x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray) -> np.ndarray:
    keep = y_train != "fall_suspected"
    binary = np.where(y_train[keep] == "walking", "walking", "other_motion")
    fitted = classifier().fit(x_train[keep], binary)
    index = list(fitted.classes_).index("walking")
    return fitted.predict_proba(x_test)[:, index]


def hierarchical_prediction(fall_probability: np.ndarray, walk_probability: np.ndarray,
                            inactivity: np.ndarray, probability_threshold: float = 0.5,
                            inactivity_threshold: float = 0.0,
                            inactivity_available: np.ndarray | None = None) -> np.ndarray:
    predicted = np.where(walk_probability >= 0.5, "walking", "other_motion").astype(object)
    if inactivity_available is None:
        inactivity_available = np.ones(len(inactivity), dtype=bool)
    quiet_gate = (inactivity >= inactivity_threshold) | ~np.asarray(inactivity_available, dtype=bool)
    predicted[(fall_probability >= probability_threshold) & quiet_gate] = "fall_suspected"
    return predicted


def inner_oof(x: np.ndarray, y: np.ndarray, groups: np.ndarray) -> np.ndarray:
    probabilities = np.zeros(len(y), dtype=float)
    for held_out in sorted(set(groups), key=str):
        train = groups != held_out
        test = ~train
        probabilities[test] = binary_fall_probabilities(x[train], y[train], x[test])
    return probabilities


def tune_fall_gate(x: np.ndarray, y: np.ndarray, groups: np.ndarray,
                   inactivity: np.ndarray, inactivity_available: np.ndarray,
                   use_inactivity: bool) -> tuple[float, float, dict[str, float]]:
    probability = inner_oof(x, y, groups)
    actual = y == "fall_suspected"
    quiet_candidates = [0.0]
    if use_inactivity and np.any(inactivity_available):
        quiet_candidates += [float(value) for value in np.unique(
            np.quantile(inactivity[inactivity_available], np.linspace(.1, .9, 9))
        )]
    best: tuple[tuple[float, float, float], float, float, dict[str, float]] | None = None
    for p_threshold in np.linspace(.10, .90, 17):
        for q_threshold in quiet_candidates:
            quiet_gate = (inactivity >= q_threshold) | ~inactivity_available
            predicted = (probability >= p_threshold) & quiet_gate
            precision, recall, f1, _ = precision_recall_fscore_support(
                actual, predicted, labels=[True], zero_division=0,
            )
            metrics = {"inner_fall_precision": float(precision[0]),
                       "inner_fall_recall": float(recall[0]), "inner_fall_f1": float(f1[0])}
            rank = (metrics["inner_fall_f1"], metrics["inner_fall_recall"], metrics["inner_fall_precision"])
            if best is None or rank > best[0]:
                best = (rank, float(p_threshold), q_threshold, metrics)
    assert best is not None
    return best[1], best[2], best[3]


def collapse_predictions(predicted: np.ndarray) -> np.ndarray:
    return np.asarray([collapse_label(str(label)) for label in predicted])


def evaluate_protocol(name: str, group: np.ndarray, x: np.ndarray, target: np.ndarray,
                      original: np.ndarray, inactivity: np.ndarray,
                      inactivity_available: np.ndarray, metadata_rows: list[dict],
                      output: Path) -> tuple[list[dict], list[dict]]:
    fold_rows: list[dict] = []
    prediction_rows: list[dict] = []
    strategies = (
        "auxiliary_7class", "hierarchical_fixed_threshold",
        "hierarchical_tuned_probability", "hierarchical_inactivity_gate",
    )
    all_predictions = {strategy: np.empty(len(target), dtype=object) for strategy in strategies}

    for held_out in sorted(set(group), key=str):
        train = group != held_out
        test = ~train
        auxiliary = classifier().fit(x[train], original[train])
        all_predictions["auxiliary_7class"][test] = collapse_predictions(auxiliary.predict(x[test]))

        fall_probability = binary_fall_probabilities(x[train], target[train], x[test])
        walk_probability = walking_probabilities(x[train], target[train], x[test])
        all_predictions["hierarchical_fixed_threshold"][test] = hierarchical_prediction(
            fall_probability, walk_probability, inactivity[test],
            inactivity_available=inactivity_available[test],
        )

        p_only, _, p_tuning = tune_fall_gate(
            x[train], target[train], group[train], inactivity[train],
            inactivity_available[train], False,
        )
        all_predictions["hierarchical_tuned_probability"][test] = hierarchical_prediction(
            fall_probability, walk_probability, inactivity[test], p_only, 0.0,
            inactivity_available[test],
        )
        p_threshold, q_threshold, tuning = tune_fall_gate(
            x[train], target[train], group[train], inactivity[train],
            inactivity_available[train], True,
        )
        all_predictions["hierarchical_inactivity_gate"][test] = hierarchical_prediction(
            fall_probability, walk_probability, inactivity[test], p_threshold, q_threshold,
            inactivity_available[test],
        )

        for strategy in strategies:
            row = {
                "protocol": name, "held_out": held_out, "strategy": strategy,
                "train_samples": int(train.sum()), "test_samples": int(test.sum()),
                "fall_probability_threshold": "", "inactivity_threshold": "",
                "inner_fall_precision": "", "inner_fall_recall": "", "inner_fall_f1": "",
                **score(target[test], all_predictions[strategy][test]),
            }
            if strategy == "hierarchical_tuned_probability":
                row.update({"fall_probability_threshold": p_only,
                            "inactivity_threshold": 0.0, **p_tuning})
            elif strategy == "hierarchical_inactivity_gate":
                row.update({"fall_probability_threshold": p_threshold,
                            "inactivity_threshold": q_threshold, **tuning})
            fold_rows.append(row)

        for index in np.flatnonzero(test):
            for strategy in strategies:
                prediction_rows.append({
                    "protocol": name, "held_out": held_out, "strategy": strategy,
                    "scenario": metadata_rows[index]["scenario"],
                    "participant": metadata_rows[index]["participant"],
                    "original_label": original[index], "target_label": target[index],
                    "prediction": all_predictions[strategy][index],
                    "inactivity_score": float(inactivity[index]),
                    "inactivity_available": int(inactivity_available[index]),
                    "path": metadata_rows[index]["path"],
                })

    for strategy in strategies:
        matrix = confusion_matrix(target, all_predictions[strategy], labels=TARGET_LABELS)
        write_csv(output / f"confusion_{name}_{strategy}.csv", [
            {"actual": label, **{prediction: int(value) for prediction, value in zip(TARGET_LABELS, values)}}
            for label, values in zip(TARGET_LABELS, matrix)
        ])
    return fold_rows, prediction_rows


def summarize(folds: list[dict]) -> list[dict]:
    result = []
    for protocol in sorted(set(row["protocol"] for row in folds)):
        for strategy in sorted(set(row["strategy"] for row in folds)):
            chosen = [row for row in folds if row["protocol"] == protocol and row["strategy"] == strategy]
            summary = {"protocol": protocol, "strategy": strategy, "folds": len(chosen)}
            for metric in ("accuracy", "macro_f1", "balanced_accuracy", "fall_precision", "fall_recall", "fall_f1", "walking_f1"):
                values = np.asarray([float(row[metric]) for row in chosen])
                summary[f"{metric}_mean"] = float(values.mean())
                summary[f"{metric}_std"] = float(values.std())
            result.append(summary)
    return result


def run(data: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    rows = load_or_extract(data, output / "features.csv")
    feature_names = [name for name in rows[0] if name not in META and not name.startswith("inactivity")
                     and name not in {"tail_quiet_fraction", "post_peak_longest_quiet_fraction",
                                      "post_peak_longest_quiet_seconds", "tail_to_p90_energy_ratio",
                                      "strongest_peak_position", "raw_packet_count", "raw_duration_seconds",
                                      "raw_sampling_rate_hz", "raw_interval_p95_ms", "raw_invalid_row_count",
                                      "raw_duplicate_packet_count", "raw_nonmonotonic_packet_count",
                                      "inactivity_available"}]
    x = np.asarray([[float(row[name]) for name in feature_names] for row in rows])
    target = np.asarray([str(row["label"]) for row in rows])
    original = np.asarray([str(row["original_label"]) for row in rows])
    participant = np.asarray([str(row["participant"]) for row in rows])
    scenario = np.asarray([str(row["scenario"]) for row in rows])
    inactivity = np.asarray([float(row["inactivity_score"]) for row in rows])
    inactivity_available = np.asarray([bool(float(row["inactivity_available"])) for row in rows])

    fold_rows: list[dict] = []
    prediction_rows: list[dict] = []
    for protocol, groups in (("leave_one_participant_out", participant), ("leave_one_environment_out", scenario)):
        folds, predictions = evaluate_protocol(
            protocol, groups, x, target, original, inactivity, inactivity_available, rows, output,
        )
        fold_rows.extend(folds)
        prediction_rows.extend(predictions)
    summary = summarize(fold_rows)

    inactivity_rows = []
    for label in sorted(set(original)):
        selected = (original == label) & inactivity_available
        values = inactivity[selected]
        inactivity_rows.append({
            "original_label": label, "samples": int(np.sum(original == label)),
            "available_samples": len(values), "mean": float(values.mean()),
            "median": float(np.median(values)), "p10": float(np.percentile(values, 10)),
            "p90": float(np.percentile(values, 90)),
        })
    write_csv(output / "fold_metrics.csv", fold_rows)
    write_csv(output / "model_summary.csv", summary)
    write_csv(output / "predictions.csv", prediction_rows)
    write_csv(output / "inactivity_by_action.csv", inactivity_rows)
    result = {
        "dataset": "ESP-Fi HAR complete archive", "samples": len(rows),
        "scenarios": dict(Counter(scenario)), "participants": dict(Counter(participant)),
        "original_labels": dict(Counter(original)), "target_labels": dict(Counter(target)),
        "activity_id_mapping": ACTIVITY_BY_ID, "feature_count": len(feature_names),
        "classifier": "class-balanced multinomial/binary LogisticRegression",
        "raw_capture": {
            "duration_seconds_median": float(np.median([float(row["raw_duration_seconds"]) for row in rows])),
            "sampling_rate_hz_median": float(np.median([float(row["raw_sampling_rate_hz"]) for row in rows])),
            "packet_count_median": float(np.median([float(row["raw_packet_count"]) for row in rows])),
            "inactivity_available_samples": int(inactivity_available.sum()),
        },
        "summary": summary,
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
            f"{row['protocol']} / {row['strategy']}: "
            f"macro_f1={100 * row['macro_f1_mean']:.2f}%, "
            f"fall_p/r/f1={100 * row['fall_precision_mean']:.2f}/"
            f"{100 * row['fall_recall_mean']:.2f}/{100 * row['fall_f1_mean']:.2f}%, "
            f"walking_f1={100 * row['walking_f1_mean']:.2f}%"
        )
    print(f"output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
