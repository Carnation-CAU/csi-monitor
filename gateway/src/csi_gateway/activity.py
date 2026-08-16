"""Stable model-neutral contracts and recent-frame inference engine."""
from __future__ import annotations
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

@dataclass(frozen=True)
class ActivityWindow:
    amplitude: np.ndarray
    first_sequence: int
    last_sequence: int
    finished_at: str

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

class FrameWindowEngine:
    """Keep recent frames and call a model at a bounded 10-30 Hz rate."""
    def __init__(self,model: ActivityModel,window_frames: int=950,inference_hz: float=20.0):
        if window_frames<=0: raise ValueError("window_frames must be positive")
        if not 1<=inference_hz<=100: raise ValueError("inference_hz must be between 1 and 100")
        self.model=model; self.window_frames=window_frames; self.interval=1.0/inference_hz
        self._frames: list[ActivityFrame]=[]; self._last_inference=-float("inf")
    @property
    def ready(self): return len(self._frames)>=self.window_frames
    @property
    def buffered_frames(self): return len(self._frames)
    def append(self,frame: ActivityFrame) -> None:
        x=np.asarray(frame.amplitude,dtype=np.float32)
        if x.shape!=(52,): raise ValueError(f"expected 52 amplitudes, got {x.shape}")
        self._frames.append(ActivityFrame(frame.sequence,frame.captured_at,x.copy()))
        if len(self._frames)>self.window_frames: del self._frames[:len(self._frames)-self.window_frames]
    def snapshot(self) -> ActivityWindow:
        if not self.ready: raise RuntimeError(f"need {self.window_frames-len(self._frames)} more frames")
        frames=self._frames[-self.window_frames:]
        return ActivityWindow(np.stack([f.amplitude for f in frames]),frames[0].sequence,frames[-1].sequence,frames[-1].captured_at)
    def clear(self) -> None:
        self._frames.clear()
        self._last_inference=-float("inf")
    def push(self,frame: ActivityFrame,*,moving: bool,now: float|None=None) -> ActivityPrediction|None:
        self.append(frame); current=monotonic() if now is None else now
        if not moving or not self.ready or current-self._last_inference<self.interval: return None
        self._last_inference=current
        return self.model.predict(self.snapshot())

class AsyncFrameWindowEngine:
    """Run GPU inference away from the serial/UI thread and drop stale requests."""
    def __init__(self,model: ActivityModel,window_frames: int=950,inference_hz: float=20.0,tail_seconds: float=3.0):
        self.window=FrameWindowEngine(model,window_frames,inference_hz); self._pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix="csi-cnn")
        self._future: Future|None=None; self._result: ActivityPrediction|None=None; self._lock=Lock(); self._last_submit=-float("inf")
        self._gate=MotionInferenceGate(tail_seconds); self._discard_pending=False
    def submit(self,frame: ActivityFrame,*,moving: bool,now: float|None=None) -> None:
        self.window.append(frame); current=monotonic() if now is None else now
        inference_active=self._gate.update(moving=moving,now=current)
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
