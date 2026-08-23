"""Grouped S3 training protocol for XGBoost, TCN and CNN+GRU candidates."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from .dataset import (
    S3Window,
    WindowConfig,
    augment_window,
    build_windows,
    dataset_inventory,
    discover_s3_sessions,
    validate_training_inventory,
)
from .evaluation import (
    ScoredEvent,
    TimedEvent,
    binary_window_metrics,
    choose_recall_threshold,
    evaluate_events,
    pr_roc_curve,
)
from .features import extract_handcrafted_features


@dataclass(frozen=True)
class TrainingConfig:
    model: str = "tcn"
    group_key: str = "room_id"
    epochs: int = 30
    batch_size: int = 32
    learning_rate: float = 3e-4
    target_recall: float = 0.95
    seed: int = 20260824


def nested_group_folds(windows: Sequence[S3Window], group_key: str) -> list[tuple[list[int], list[int], list[int], str, str]]:
    """Use different groups for train, threshold validation and locked test."""
    groups = sorted({str(getattr(window, group_key)) for window in windows if str(getattr(window, group_key)) != "unknown"})
    if len(groups) < 3:
        return []
    folds = []
    for index, test_group in enumerate(groups):
        validation_group = groups[(index + 1) % len(groups)]
        train = [row for row, window in enumerate(windows) if str(getattr(window, group_key)) not in {test_group, validation_group}]
        validation = [row for row, window in enumerate(windows) if str(getattr(window, group_key)) == validation_group]
        test = [row for row, window in enumerate(windows) if str(getattr(window, group_key)) == test_group]
        if train and validation and test:
            folds.append((train, validation, test, validation_group, test_group))
    return folds


def _event_predictions(
    windows: Sequence[S3Window], scores: Sequence[float], threshold: float, config: WindowConfig
) -> tuple[list[TimedEvent], list[ScoredEvent]]:
    actual_by_session: dict[str, TimedEvent] = {}
    predicted: list[ScoredEvent] = []
    rows: dict[str, list[tuple[float, float]]] = {}
    for window, score in zip(windows, scores):
        if window.event_at_seconds is not None and window.is_fall:
            actual_by_session.setdefault(
                window.session_id,
                TimedEvent(f"actual-{window.session_id}", window.session_id, window.event_at_seconds),
            )
        if score >= threshold:
            # A [-2,+3] classifier cannot report before the post-event data exists.
            detected_at = window.start_seconds + config.pre_event_seconds + config.post_event_seconds
            rows.setdefault(window.session_id, []).append((detected_at, float(score)))
    for session_id, session_rows in rows.items():
        session_rows.sort()
        episodes: list[list[tuple[float, float]]] = []
        for row in session_rows:
            if not episodes or row[0] - episodes[-1][-1][0] > 2.0:
                episodes.append([row])
            else:
                episodes[-1].append(row)
        for index, episode in enumerate(episodes):
            predicted.append(
                ScoredEvent(
                    f"predicted-{session_id}-{index}",
                    session_id,
                    episode[0][0],
                    max(score for _, score in episode),
                )
            )
    return list(actual_by_session.values()), predicted


def evaluate_fold(
    windows: Sequence[S3Window],
    scores: Sequence[float],
    threshold: float,
    window_config: WindowConfig,
) -> dict[str, object]:
    labels = [window.is_fall for window in windows]
    actual, predicted = _event_predictions(windows, scores, threshold, window_config)
    event_metrics, matches = evaluate_events(actual, predicted)
    return {
        "windowMetrics": binary_window_metrics(labels, scores, threshold),
        "confusionMatrix": {
            "truePositive": int(sum(label and score >= threshold for label, score in zip(labels, scores))),
            "falseNegative": int(sum(label and score < threshold for label, score in zip(labels, scores))),
            "falsePositive": int(sum(not label and score >= threshold for label, score in zip(labels, scores))),
            "trueNegative": int(sum(not label and score < threshold for label, score in zip(labels, scores))),
        },
        "prRocCurve": pr_roc_curve(labels, scores),
        "eventMetrics": asdict(event_metrics),
        "eventMatches": matches,
    }


def _train_xgboost(
    windows: Sequence[S3Window], train: Sequence[int], validation: Sequence[int], test: Sequence[int], seed: int
) -> tuple[np.ndarray, np.ndarray]:
    try:
        from xgboost import XGBClassifier
    except ImportError as exc:
        raise RuntimeError("XGBoost baseline requires the 'ml-training' optional dependencies") from exc
    matrix = np.stack([extract_handcrafted_features(window.features) for window in windows])
    labels = np.asarray([window.is_fall for window in windows], dtype=np.int64)
    positives = max(1, int(np.sum(labels[list(train)])))
    negatives = max(1, len(train) - positives)
    model = XGBClassifier(
        n_estimators=500,
        max_depth=5,
        learning_rate=0.04,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=negatives / positives,
        objective="binary:logistic",
        eval_metric="logloss",
        random_state=seed,
        n_jobs=-1,
    )
    model.fit(matrix[list(train)], labels[list(train)], eval_set=[(matrix[list(validation)], labels[list(validation)])], verbose=False)
    return model.predict_proba(matrix[list(validation)])[:, 1], model.predict_proba(matrix[list(test)])[:, 1]


def _train_torch(
    windows: Sequence[S3Window], train: Sequence[int], validation: Sequence[int], test: Sequence[int], config: TrainingConfig
) -> tuple[np.ndarray, np.ndarray]:
    try:
        import torch
        from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

        from .models import FocalLoss, make_s3_model
    except ImportError as exc:
        raise RuntimeError("Temporal models require the 'ml-training' optional dependencies") from exc

    rng = np.random.default_rng(config.seed)

    class WindowDataset(Dataset):
        def __init__(self, indices: Sequence[int], training: bool) -> None:
            self.indices = list(indices)
            self.training = training

        def __len__(self) -> int:
            return len(self.indices)

        def __getitem__(self, index: int):
            window = windows[self.indices[index]]
            values = augment_window(window.features, rng) if self.training else window.features
            return torch.from_numpy(values), torch.tensor(int(window.is_fall), dtype=torch.long)

    labels = np.asarray([int(windows[index].is_fall) for index in train])
    counts = np.maximum(np.bincount(labels, minlength=2), 1)
    sample_weights = np.asarray([1.0 / counts[label] for label in labels])
    sampler = WeightedRandomSampler(sample_weights, len(sample_weights), replacement=True)
    train_loader = DataLoader(WindowDataset(train, True), batch_size=config.batch_size, sampler=sampler)
    validation_loader = DataLoader(WindowDataset(validation, False), batch_size=config.batch_size)
    test_loader = DataLoader(WindowDataset(test, False), batch_size=config.batch_size)
    device = torch.device("cuda" if torch.cuda.is_available() else "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu")
    model = make_s3_model(config.model, input_channels=windows[0].features.shape[0], subcarriers=windows[0].features.shape[2]).to(device)
    loss_function = FocalLoss(positive_weight=float(counts[0] / counts[1])).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate, weight_decay=1e-4)
    best_state = None
    best_validation_recall = -1.0
    best_validation_loss = float("inf")
    for _ in range(config.epochs):
        model.train()
        for values, target in train_loader:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_function(model(values.to(device)), target.to(device))
            loss.backward()
            optimizer.step()
        model.eval()
        validation_losses: list[float] = []
        validation_scores: list[float] = []
        validation_targets: list[int] = []
        with torch.inference_mode():
            for values, target in validation_loader:
                logits = model(values.to(device))
                validation_losses.append(float(loss_function(logits, target.to(device)).cpu()))
                validation_scores.extend(logits.softmax(1)[:, 1].cpu().tolist())
                validation_targets.extend(target.tolist())
        threshold_row = choose_recall_threshold(validation_targets, validation_scores, target_recall=config.target_recall)
        recall = float(threshold_row["fall_recall"]) if threshold_row else 0.0
        mean_loss = float(np.mean(validation_losses)) if validation_losses else float("inf")
        if (recall, -mean_loss) > (best_validation_recall, -best_validation_loss):
            best_validation_recall, best_validation_loss = recall, mean_loss
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
    if best_state is None:
        raise RuntimeError("training produced no checkpoint")
    model.load_state_dict(best_state)
    model.eval()

    def predict(loader) -> np.ndarray:
        result: list[float] = []
        with torch.inference_mode():
            for values, _ in loader:
                result.extend(model(values.to(device)).softmax(1)[:, 1].cpu().tolist())
        return np.asarray(result, dtype=np.float64)

    return predict(validation_loader), predict(test_loader)


def run_training(project_root: Path, config: TrainingConfig, *, allow_smoke_test: bool = False) -> dict[str, object]:
    sessions, skipped = discover_s3_sessions(project_root)
    inventory = dataset_inventory(sessions)
    blockers = validate_training_inventory(inventory)
    result: dict[str, object] = {
        "schemaVersion": "s3-training-experiment-v1",
        "configuration": asdict(config),
        "windowConfiguration": asdict(WindowConfig()),
        "inventory": inventory,
        "skipped": skipped,
        "validationBlockers": blockers,
        "publishable": not blockers,
        "folds": [],
    }
    if blockers and not allow_smoke_test:
        result["status"] = "blocked_insufficient_s3_data"
        return result
    windows = [window for session in sessions for window in build_windows(session)]
    folds = nested_group_folds(windows, config.group_key)
    if not folds:
        result["status"] = "blocked_group_split_requires_three_known_groups"
        result["publishable"] = False
        return result
    for fold_index, (train, validation, test, validation_group, test_group) in enumerate(folds):
        if config.model == "xgboost":
            validation_scores, test_scores = _train_xgboost(windows, train, validation, test, config.seed + fold_index)
        else:
            validation_scores, test_scores = _train_torch(windows, train, validation, test, config)
        threshold_row = choose_recall_threshold(
            [windows[index].is_fall for index in validation],
            validation_scores,
            target_recall=config.target_recall,
        )
        if threshold_row is None:
            threshold = 0.0
        else:
            threshold = float(threshold_row["threshold"])
        result["folds"].append(
            {
                "fold": fold_index,
                "validationGroup": validation_group,
                "lockedTestGroup": test_group,
                "thresholdSelectedOnValidationOnly": threshold,
                "validation": evaluate_fold([windows[index] for index in validation], validation_scores, threshold, WindowConfig()),
                "test": evaluate_fold([windows[index] for index in test], test_scores, threshold, WindowConfig()),
            }
        )
    result["status"] = "complete"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--model", choices=("xgboost", "tcn", "cnn_gru", "cnn2d"), default="tcn")
    parser.add_argument("--group-key", choices=("room_id", "person_id", "channel"), default="room_id")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--allow-smoke-test", action="store_true")
    parser.add_argument("--output", default="data/processed/s3-training-experiment.json")
    args = parser.parse_args(argv)
    config = TrainingConfig(model=args.model, group_key=args.group_key, epochs=args.epochs)
    result = run_training(Path(args.project_root).resolve(), config, allow_smoke_test=args.allow_smoke_test)
    output = Path(args.output)
    if not output.is_absolute():
        output = Path(args.project_root).resolve() / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "publishable": result["publishable"], "inventory": result["inventory"], "validationBlockers": result["validationBlockers"]}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
