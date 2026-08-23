"""Replay identical labeled S3 sessions through legacy and recall-first rules.

This is intentionally an event-level comparison. It refuses to manufacture a
Recall number when no labeled S3 fall with usable IQ is available.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_SRC = PROJECT_ROOT / "gateway" / "src"
for entry in (str(PROJECT_ROOT), str(GATEWAY_SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from csi_gateway.activity import ActivityFrame, ActivityPrediction, FrameWindowEngine
from csi_gateway.activity_events import (
    ActivityEventAggregator,
    DEFAULT_FALL_CANDIDATE_THRESHOLD,
    recall_first_fusion_score,
)
from csi_gateway.collection import FALL_LABELS
from csi_gateway.csi import CsiFrameSample, parse_csi_line
from csi_gateway.csi_pipeline import CsiRealtimePipeline, SignalEvidence
from csi_gateway.live_detection import LiveActionDetector
from csi_gateway.radar import RadarSample, parse_radar_line
from ml.runtime import TorchCnnActivityModel
from ml.s3.evaluation import ScoredEvent, TimedEvent, evaluate_events, threshold_curve


def epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


@dataclass
class ReplaySession:
    session_id: str
    label: str
    event_at: float | None
    csi: list[tuple[float, CsiFrameSample]]
    radar: list[tuple[float, RadarSample]]
    signal: list[tuple[float, SignalEvidence]]
    raw_path: str


def load_session(root: Path, manifest: dict[str, object]) -> ReplaySession | None:
    raw_value = manifest.get("rawFile")
    if not raw_value:
        return None
    raw_path = root / str(raw_value)
    if not raw_path.is_file():
        return None
    rows: list[tuple[float, str]] = []
    for line in raw_path.open(encoding="utf-8-sig", errors="replace"):
        try:
            record = json.loads(line)
            rows.append((epoch(str(record["timestampUtc"])), str(record.get("raw", ""))))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    if not rows:
        return None
    origin = rows[0][0]
    pipeline = CsiRealtimePipeline()
    csi: list[tuple[float, CsiFrameSample]] = []
    radar: list[tuple[float, RadarSample]] = []
    signal: list[tuple[float, SignalEvidence]] = []
    for received_at, raw in rows:
        relative = received_at - origin
        frame = parse_csi_line(raw)
        if frame is not None and len(frame.amplitude) == 52:
            csi.append((relative, frame))
            signal.append((relative, pipeline.observe(frame, observed_at=relative)))
        radar_sample = parse_radar_line(raw)
        if radar_sample is not None:
            radar.append((relative, radar_sample))
    event_value = manifest.get("eventAtUtc")
    return ReplaySession(
        session_id=str(manifest["sessionId"]),
        label=str(manifest.get("label", "")),
        event_at=epoch(str(event_value)) - origin if event_value else None,
        csi=csi,
        radar=radar,
        signal=signal,
        raw_path=raw_path.relative_to(root).as_posix(),
    )


def radar_falls(session: ReplaySession) -> list[tuple[float, object]]:
    detector = LiveActionDetector()
    result: list[tuple[float, object]] = []
    for observed_at, sample in session.radar:
        events = detector.update(
            sample,
            observed_at=observed_at,
            detected_at=str(observed_at),
            presence_state="unknown",
            presence_probability=0.0,
        )
        result.extend(
            (observed_at, event)
            for event in events
            if event.event_type == "fall_suspected"
        )
    return result


def model_scores(
    session: ReplaySession,
    model: TorchCnnActivityModel,
    *,
    stride_frames: int,
) -> list[tuple[float, ActivityPrediction]]:
    engine = FrameWindowEngine(
        model,
        window_frames=model.window_frames,
        inference_hz=100,
        target_rate_hz=100,
    )
    scores: list[tuple[float, ActivityPrediction]] = []
    for index, (observed_at, sample) in enumerate(session.csi):
        engine.append(
            ActivityFrame(
                sample.sequence,
                sample.timestamp,
                sample.amplitude,
                sample.local_timestamp_us,
            )
        )
        if not engine.ready or index % stride_frames:
            continue
        prediction = model.predict(engine.snapshot())
        scores.append((observed_at, prediction))
    return scores


def nearest_signal(session: ReplaySession, observed_at: float) -> SignalEvidence | None:
    if not session.signal:
        return None
    _, evidence = min(session.signal, key=lambda item: abs(item[0] - observed_at))
    return evidence


def legacy_detection(
    session: ReplaySession,
    scores: list[tuple[float, ActivityPrediction]],
    radar_events: list[tuple[float, object]],
) -> tuple[float, float] | None:
    # Production v1: model runs only while Radar moving or during its 3 s tail,
    # ML >= .8, then a Radar fall must exist inside the 15 s correlation window.
    gated = [
        (observed_at, float(prediction.scores.get("fall_suspected", 0.0)))
        for observed_at, prediction in scores
        if float(prediction.scores.get("fall_suspected", 0.0)) >= 0.80
        and any(
            sample.moving and 0 <= observed_at - radar_at <= 3.0
            for radar_at, sample in session.radar
        )
    ]
    candidates = [
        (max(ml_at, radar_at), min(score, radar_event.confidence))
        for ml_at, score in gated
        for radar_at, radar_event in radar_events
        if abs(ml_at - radar_at) <= 15.0
    ]
    return min(candidates, default=None, key=lambda item: item[0])


def recall_first_detection(
    session: ReplaySession,
    scores: list[tuple[float, ActivityPrediction]],
    radar_events: list[tuple[float, object]],
) -> tuple[float, float, dict[str, object]] | None:
    """Replay the production aggregator on the same chronological event stream."""
    aggregator = ActivityEventAggregator()
    stream: list[tuple[float, int, object]] = []
    stream.extend((at, 0, evidence) for at, evidence in session.signal)
    stream.extend((at, 1, sample) for at, sample in session.radar)
    stream.extend((at, 2, event) for at, event in radar_events)
    stream.extend((at, 3, prediction) for at, prediction in scores)
    detections: list[tuple[float, float, dict[str, object]]] = []

    def collect(at: float, events: list[object]) -> None:
        for event in events:
            if getattr(event, "event_type", "") != "fall_suspected":
                continue
            detections.append(
                (
                    at,
                    float(getattr(event, "confidence")),
                    dict(getattr(event, "evidence")),
                )
            )

    last_at = 0.0
    for observed_at, kind, value in sorted(stream, key=lambda row: (row[0], row[1])):
        last_at = max(last_at, observed_at)
        if kind == 0:
            aggregator.observe_signal(value, observed_at=observed_at)
            collect(observed_at, aggregator.expire(observed_at))
        elif kind == 1:
            aggregator.observe_radar_motion(
                moving=value.moving,
                observed_at=observed_at,
            )
        elif kind == 2:
            fused = aggregator.fuse_radar_fall(value, observed_at=observed_at)
            collect(observed_at, [fused] if fused is not None else [])
        else:
            collect(
                observed_at,
                aggregator.observe(
                    value,
                    observed_at=observed_at,
                    detected_at=value.window_finished_at,
                ),
            )
    collect(last_at + 2.1, aggregator.expire(last_at + 2.1))
    return min(detections, default=None, key=lambda item: item[0])


def recall_first_audit(
    session: ReplaySession,
    scores: list[tuple[float, ActivityPrediction]],
) -> list[dict[str, object]]:
    """Expose rejected episode scores so false negatives remain diagnosable."""
    candidates = [
        (at, float(prediction.scores.get("fall_suspected", 0.0)))
        for at, prediction in scores
        if float(prediction.scores.get("fall_suspected", 0.0))
        >= DEFAULT_FALL_CANDIDATE_THRESHOLD
    ]
    episodes: list[list[tuple[float, float]]] = []
    for row in candidates:
        if not episodes or row[0] - episodes[-1][-1][0] > 2.0:
            episodes.append([row])
        else:
            episodes[-1].append(row)
    result: list[dict[str, object]] = []
    session_end = max((at for at, _ in session.signal), default=0.0)
    for episode in episodes:
        last_at = episode[-1][0]
        expires_at = min(session_end, last_at + 2.0)
        signal_rows = [
            evidence
            for at, evidence in session.signal
            if expires_at - 15.0 <= at <= expires_at
            and abs(at - last_at) <= 15.0
        ]
        ml_score = max(score for _, score in episode)
        final, proposal, components, weights = recall_first_fusion_score(
            ml_score,
            signal_rows=signal_rows,
        )
        proposal_groups: dict[str, list[tuple[float, SignalEvidence]]] = {}
        for at, evidence in session.signal:
            if (
                evidence.proposal_id
                and evidence.baseline_ready
                and evidence.proposal_started_at is not None
                and evidence.proposal_started_at
                - (at - evidence.baseline_age_seconds)
                >= 3.0
                and abs(at - last_at) <= 15.0
            ):
                proposal_groups.setdefault(evidence.proposal_id, []).append(
                    (at, evidence)
                )
        proposal_audit = []
        for proposal_id, group in proposal_groups.items():
            group_final, group_score, group_components, _ = (
                recall_first_fusion_score(
                    ml_score,
                    signal_rows=[evidence for _, evidence in group],
                )
            )
            proposal_audit.append(
                {
                    "proposalId": proposal_id,
                    "firstAt": group[0][0],
                    "lastAt": group[-1][0],
                    "rowCount": len(group),
                    "proposalScore": group_score,
                    "finalScore": group_final,
                    "components": group_components,
                }
            )
        result.append(
            {
                "firstAt": episode[0][0],
                "lastAt": last_at,
                "windowCount": len(episode),
                "maxMlFallScore": ml_score,
                "proposalScore": proposal,
                "finalScore": final,
                "components": components,
                "proposalWeights": weights,
                "eligibleSignalProposals": proposal_audit,
            }
        )
    return result


def discover_sessions(root: Path) -> tuple[list[ReplaySession], list[dict[str, str]]]:
    sessions: list[ReplaySession] = []
    skipped: list[dict[str, str]] = []
    for path in sorted((root / "data" / "manifests").glob("*.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            skipped.append({"manifest": path.name, "reason": "invalid_manifest"})
            continue
        if manifest.get("valid") is not True:
            continue
        session = load_session(root, manifest)
        if session is None:
            skipped.append({"manifest": path.name, "reason": "missing_raw"})
        elif len(session.csi) < 950:
            skipped.append({"manifest": path.name, "reason": "fewer_than_950_csi"})
        else:
            sessions.append(session)
    return sessions, skipped


def compare(args: argparse.Namespace) -> dict[str, object]:
    root = Path(args.project_root).resolve()
    model_path = Path(args.model)
    if not model_path.is_absolute():
        model_path = root / model_path
    sessions, skipped = discover_sessions(root)
    falls = [session for session in sessions if session.label in FALL_LABELS]
    if not falls:
        raise RuntimeError("유효한 labeled ESP32-S3 fall IQ 세션이 없어 Recall을 계산할 수 없습니다.")
    model = TorchCnnActivityModel(model_path, device=args.device)
    actual = [
        TimedEvent(f"actual-{session.session_id}", session.session_id, session.event_at)
        for session in falls
        if session.event_at is not None
    ]
    before_events: list[ScoredEvent] = []
    after_events: list[ScoredEvent] = []
    session_rows: list[dict[str, object]] = []
    session_actual: list[bool] = []
    session_scores: list[float] = []
    for session in sessions:
        scores = model_scores(session, model, stride_frames=args.stride_frames)
        radar_events = radar_falls(session)
        before = legacy_detection(session, scores, radar_events)
        after = recall_first_detection(session, scores, radar_events)
        fusion_audit = recall_first_audit(session, scores)
        if before is not None:
            before_events.append(
                ScoredEvent(f"before-{session.session_id}", session.session_id, *before)
            )
        if after is not None:
            after_events.append(
                ScoredEvent(
                    f"after-{session.session_id}",
                    session.session_id,
                    after[0],
                    after[1],
                )
            )
        maximum = max(
            (
                float(prediction.scores.get("fall_suspected", 0.0))
                for _, prediction in scores
            ),
            default=0.0,
        )
        session_actual.append(session.label in FALL_LABELS)
        session_scores.append(maximum)
        session_rows.append(
            {
                "sessionId": session.session_id,
                "label": session.label,
                "rawFile": session.raw_path,
                "csiFrames": len(session.csi),
                "radarSamples": len(session.radar),
                "modelWindows": len(scores),
                "maxMlFallScore": maximum,
                "radarFallEvents": len(radar_events),
                "beforeDetection": before,
                "afterDetection": (
                    {"detectedAt": after[0], "score": after[1], "evidence": after[2]}
                    if after is not None
                    else None
                ),
                "fusionAudit": fusion_audit,
            }
        )
    before_metrics, before_matches = evaluate_events(actual, before_events)
    after_metrics, after_matches = evaluate_events(actual, after_events)
    result = {
        "schemaVersion": "s3-replay-comparison-v1",
        "warning": (
            "Small local replay, not a production validation. Scores from the C3 model "
            "are uncalibrated and must not be reported as general S3 performance."
        ),
        "model": str(model_path),
        "modelVersion": model.model_version,
        "strideFrames": args.stride_frames,
        "evaluatedSessionCount": len(sessions),
        "actualFallEventCount": len(actual),
        "skipped": skipped,
        "before": {"metrics": asdict(before_metrics), "matches": before_matches},
        "after": {"metrics": asdict(after_metrics), "matches": after_matches},
        "sessionScoreCurve": threshold_curve(session_actual, session_scores),
        "sessions": session_rows,
    }
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--model", default="ml/v_main/model.pt")
    parser.add_argument("--device")
    parser.add_argument("--stride-frames", type=int, default=20)
    parser.add_argument("--output", default="data/processed/s3-before-after.json")
    args = parser.parse_args(argv)
    try:
        result = compare(args)
    except Exception as exc:
        print(f"S3 replay comparison failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"before": result["before"], "after": result["after"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
