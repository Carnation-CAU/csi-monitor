"""Stable model-neutral contracts and recent-frame inference engine."""
from __future__ import annotations
from collections import deque
from concurrent.futures import Future,ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Mapping,Protocol
import numpy as np

@dataclass(frozen=True)
class ActivityFrame:
    sequence: int
    captured_at: str
    amplitude: np.ndarray
    device_timestamp_us: int | None = None

@dataclass(frozen=True)
class ActivityWindow:
    amplitude: np.ndarray
    first_sequence: int
    last_sequence: int
    finished_at: str
    resampled: bool = False
    observed_rate_hz: float | None = None

@dataclass(frozen=True)
class ActivityPrediction:
    label: str
    scores: Mapping[str,float]
    confidence: float
    first_sequence: int
    last_sequence: int
    window_finished_at: str
    model_version: str
    preprocessing_version: str

class ActivityModel(Protocol):
    """Any future CNN/ONNX model only needs to satisfy this contract."""
    def predict(self,window: ActivityWindow) -> ActivityPrediction: ...


class MotionInferenceGate:
    """Keep inference active briefly after Radar moving returns to false."""

    def __init__(self, tail_seconds: float = 3.0) -> None:
        if tail_seconds < 0:
            raise ValueError("tail_seconds cannot be negative")
        self.tail_seconds = tail_seconds
        self._active_until = -float("inf")

    def update(self, *, moving: bool, now: float) -> bool:
        if moving:
            self._active_until = max(self._active_until, now + self.tail_seconds)
        return now <= self._active_until

    def reset(self) -> None:
        self._active_until = -float("inf")


class ActivityPredictionDisplaySmoother:
    """Average recent scores and rate-limit UI-only prediction updates."""

    def __init__(self, history_size: int = 5, refresh_seconds: float = 1.0) -> None:
        if history_size <= 0:
            raise ValueError("history_size must be positive")
        if refresh_seconds <= 0:
            raise ValueError("refresh_seconds must be positive")
        self._scores: deque[dict[str, float]] = deque(maxlen=history_size)
        self.refresh_seconds = refresh_seconds
        self._last_rendered_at = -float("inf")
        self._last_observed_at = -float("inf")
        self._displayed_label: str | None = None

    def observe(
        self,
        prediction: ActivityPrediction,
        *,
        now: float,
    ) -> tuple[str, dict[str, float]] | None:
        self._scores.append(dict(prediction.scores))
        self._last_observed_at = now
        urgent_fall = (
            prediction.label == "fall_suspected"
            and self._displayed_label != "fall_suspected"
        )
        if not urgent_fall and now - self._last_rendered_at < self.refresh_seconds:
            return None

        if urgent_fall:
            averaged = dict(prediction.scores)
            label = "fall_suspected"
        else:
            labels = tuple(prediction.scores)
            averaged = {
                label: sum(scores.get(label, 0.0) for scores in self._scores)
                / len(self._scores)
                for label in labels
            }
            label = max(averaged, key=averaged.get)
        self._last_rendered_at = now
        self._displayed_label = label
        return label, averaged

    def is_fresh(self, *, now: float, hold_seconds: float = 5.0) -> bool:
        if hold_seconds < 0:
            raise ValueError("hold_seconds cannot be negative")
        return now - self._last_observed_at <= hold_seconds

    def reset(self) -> None:
        self._scores.clear()
        self._last_rendered_at = -float("inf")
        self._last_observed_at = -float("inf")
        self._displayed_label = None

class FrameWindowEngine:
    """Keep recent frames, time-align them and call a model at a bounded rate."""
    def __init__(self,model: ActivityModel,window_frames: int=950,inference_hz: float=20.0,target_rate_hz: float=100.0):
        if window_frames<=0: raise ValueError("window_frames must be positive")
        if not 1<=inference_hz<=100: raise ValueError("inference_hz must be between 1 and 100")
        if target_rate_hz<=0: raise ValueError("target_rate_hz must be positive")
        self.model=model; self.window_frames=window_frames; self.interval=1.0/inference_hz; self.target_rate_hz=target_rate_hz
        # Extra frames preserve enough time coverage when packets arrive above
        # target rate or short gaps occur.
        self._frames: deque[ActivityFrame]=deque(maxlen=max(window_frames+32,int(window_frames*1.25))); self._last_inference=-float("inf")
    @property
    def ready(self): return len(self._frames)>=self.window_frames
    @property
    def buffered_frames(self): return len(self._frames)
    def append(self,frame: ActivityFrame) -> None:
        x=np.asarray(frame.amplitude,dtype=np.float32)
        if x.shape!=(52,): raise ValueError(f"expected 52 amplitudes, got {x.shape}")
        self._frames.append(ActivityFrame(frame.sequence,frame.captured_at,x.copy(),frame.device_timestamp_us))
    def snapshot(self) -> ActivityWindow:
        if not self.ready: raise RuntimeError(f"need {self.window_frames-len(self._frames)} more frames")
        frames=list(self._frames)
        timestamped=[f for f in frames if f.device_timestamp_us is not None]
        if len(timestamped)>=self.window_frames:
            times=self._unwrap_timestamps(timestamped)
            duration_us=(self.window_frames-1)*1_000_000.0/self.target_rate_hz
            target_end=times[-1]; target_start=target_end-duration_us
            first=int(np.searchsorted(times,target_start,side="right")-1); first=max(0,first)
            source=timestamped[first:]; source_times=times[first:]
            if len(source)>=2 and source_times[0]<=target_start:
                target=np.linspace(target_start,target_end,self.window_frames)
                values=np.stack([f.amplitude for f in source])
                aligned=np.empty((self.window_frames,52),dtype=np.float32)
                for carrier in range(52): aligned[:,carrier]=np.interp(target,source_times,values[:,carrier])
                intervals=np.diff(source_times)
                observed_rate=1_000_000.0/float(np.mean(intervals)) if len(intervals) and float(np.mean(intervals))>0 else None
                return ActivityWindow(aligned,source[0].sequence,source[-1].sequence,source[-1].captured_at,True,observed_rate)
        selected=frames[-self.window_frames:]
        return ActivityWindow(np.stack([f.amplitude for f in selected]),selected[0].sequence,selected[-1].sequence,selected[-1].captured_at)

    @staticmethod
    def _unwrap_timestamps(frames: list[ActivityFrame]) -> np.ndarray:
        result=[]; offset=0; previous=None
        for frame in frames:
            current=int(frame.device_timestamp_us or 0)
            if previous is not None and current+offset<previous:
                offset+=2**32
            value=current+offset; result.append(value); previous=value
        return np.asarray(result,dtype=np.float64)
    def clear(self) -> None:
        self._frames.clear()
        self._last_inference=-float("inf")
    def push(self,frame: ActivityFrame,*,moving: bool,now: float|None=None) -> ActivityPrediction|None:
        self.append(frame); current=monotonic() if now is None else now
        if not moving or not self.ready or current-self._last_inference<self.interval: return None
        self._last_inference=current
        return self.model.predict(self.snapshot())

class AsyncFrameWindowEngine:
    """Run inference off-thread; continuous mode prevents a Radar hard gate."""
    def __init__(self,model: ActivityModel,window_frames: int=950,inference_hz: float=20.0,tail_seconds: float=3.0,continuous_inference: bool=True):
        self.window=FrameWindowEngine(model,window_frames,inference_hz); self._pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix="csi-cnn")
        self._future: Future|None=None; self._result: ActivityPrediction|None=None; self._lock=Lock(); self._last_submit=-float("inf")
        self._gate=MotionInferenceGate(tail_seconds); self._discard_pending=False; self.continuous_inference=continuous_inference
    def submit(self,frame: ActivityFrame,*,moving: bool,now: float|None=None) -> None:
        self.window.append(frame); current=monotonic() if now is None else now
        # ``moving`` is retained for API compatibility and diagnostics only in
        # the recall-first default. A missed Radar flag cannot suppress ML.
        inference_active=self.continuous_inference or self._gate.update(moving=moving,now=current)
        with self._lock:
            if not inference_active or not self.window.ready or self._future is not None or current-self._last_submit<self.window.interval: return
            snapshot=self.window.snapshot(); self._last_submit=current; self._discard_pending=False; self._future=self._pool.submit(self.window.model.predict,snapshot)
    def poll(self) -> ActivityPrediction|None:
        with self._lock:
            if self._future is not None and self._future.done():
                finished=self._future; self._future=None
                if self._discard_pending:
                    self._discard_pending=False
                else:
                    self._result=finished.result()
            result=self._result; self._result=None; return result
    def deactivate(self, *, clear_frames: bool = False) -> None:
        self._gate.reset()
        with self._lock:
            self._result=None
            self._discard_pending=self._future is not None
        if clear_frames:
            self.window.clear()
    def close(self): self._pool.shutdown(wait=True,cancel_futures=True)
