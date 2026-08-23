"""Bounded pre/post CSI capture for fall-candidate replay and hard negatives."""
from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class _PendingClip:
    event: dict[str, object]
    deadline: float
    path: Path
    frames: list[dict[str, object]] = field(default_factory=list)


class EventClipRecorder:
    """Keep a RAM ring buffer and persist candidate-centered UART evidence."""

    def __init__(
        self,
        project_root: Path,
        *,
        pre_seconds: float = 5.0,
        post_seconds: float = 5.0,
    ) -> None:
        if pre_seconds <= 0 or post_seconds <= 0:
            raise ValueError("clip durations must be positive")
        self.project_root = project_root
        self.clip_dir = project_root / "data" / "events" / "clips"
        self.pre_seconds = pre_seconds
        self.post_seconds = post_seconds
        self._recent: deque[tuple[float, dict[str, object]]] = deque()
        self._pending: dict[str, _PendingClip] = {}

    def observe(
        self,
        *,
        raw_line: bytes,
        observed_at: float,
        timestamp_utc: str,
    ) -> list[Path]:
        frame = {
            "recordType": "csi_uart",
            "timestampUtc": timestamp_utc,
            "relativeClock": observed_at,
            "raw": raw_line.decode("utf-8", errors="replace").rstrip("\r\n"),
        }
        self._recent.append((observed_at, frame))
        cutoff = observed_at - self.pre_seconds
        while self._recent and self._recent[0][0] < cutoff:
            self._recent.popleft()
        for pending in self._pending.values():
            pending.frames.append(frame)
        ready = [
            event_id
            for event_id, pending in self._pending.items()
            if observed_at >= pending.deadline
        ]
        return [self._finish(event_id) for event_id in ready]

    def trigger(
        self,
        event: dict[str, object],
        *,
        observed_at: float,
    ) -> Path:
        event_id = str(event.get("event_id") or "event")
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", event_id)[:128]
        path = self.clip_dir / f"{safe_id}.jsonl"
        if event_id in self._pending:
            pending = self._pending[event_id]
            pending.event = dict(event)
            pending.deadline = max(pending.deadline, observed_at + self.post_seconds)
        elif path.exists():
            # A later final decision can arrive after the candidate clip's
            # post-window closed. Preserve it without overwriting raw frames.
            with path.open("a", encoding="utf-8", newline="\n") as output:
                output.write(
                    json.dumps(
                        {"recordType": "decision", "event": dict(event)},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
        else:
            self._pending[event_id] = _PendingClip(
                event=dict(event),
                deadline=observed_at + self.post_seconds,
                path=path,
                frames=[frame for _, frame in self._recent],
            )
        return path

    def close(self) -> list[Path]:
        return [self._finish(event_id) for event_id in list(self._pending)]

    def _finish(self, event_id: str) -> Path:
        pending = self._pending.pop(event_id)
        pending.path.parent.mkdir(parents=True, exist_ok=True)
        with pending.path.open("w", encoding="utf-8", newline="\n") as output:
            output.write(
                json.dumps(
                    {
                        "schemaVersion": "fall-event-clip-v1",
                        "recordType": "event",
                        "preSeconds": self.pre_seconds,
                        "postSeconds": self.post_seconds,
                        "event": pending.event,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            for frame in pending.frames:
                output.write(
                    json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
        return pending.path
