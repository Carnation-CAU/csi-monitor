"""Public CSI HAR loaders with common [time, subcarrier] model inputs."""
from __future__ import annotations
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
import numpy as np

TARGET_NAMES = ("fall", "walking", "other_motion")
UT_HAR_LABELS = {0:"lie_down", 1:"fall", 2:"walking", 3:"pickup", 4:"run", 5:"sit_down", 6:"stand_up"}

def target_label(activity: str) -> int | None:
    name = activity.strip().lower().replace(" ", "_")
    if name in {"no_person", "no_activity", "background"}: return None
    if name == "fall": return 0
    if name in {"walk", "walking"}: return 1
    return 2

def resize_csi(x: np.ndarray, time_steps: int = 250, subcarriers: int = 90) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if x.ndim != 2: raise ValueError(f"expected [time, subcarrier], got {x.shape}")
    old_t, new_t = np.linspace(0,1,x.shape[0]), np.linspace(0,1,time_steps)
    tmp = np.stack([np.interp(new_t, old_t, x[:,j]) for j in range(x.shape[1])], axis=1)
    old_s, new_s = np.linspace(0,1,x.shape[1]), np.linspace(0,1,subcarriers)
    return np.stack([np.interp(new_s, old_s, row) for row in tmp]).astype(np.float32)

def normalize_per_sample(x: np.ndarray, epsilon: float = 1e-6) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    return (x-x.mean(0,keepdims=True))/np.maximum(x.std(0,keepdims=True),epsilon)

def load_ut_har(root: Path | str, split: str) -> tuple[np.ndarray,np.ndarray,np.ndarray]:
    if split not in {"train","val","test"}: raise ValueError("split must be train, val, or test")
    root = Path(root)
    x = np.load(root/"data"/f"X_{split}.csv", mmap_mode="r")
    source_y = np.load(root/"label"/f"y_{split}.csv", mmap_mode="r")
    if x.ndim != 3 or x.shape[1:] != (250,90): raise ValueError(f"unexpected UT-HAR shape: {x.shape}")
    y = np.asarray([target_label(UT_HAR_LABELS[int(v)]) for v in source_y], dtype=np.int64)
    return x,y,np.asarray(source_y)

@dataclass(frozen=True)
class CsiHarWindow:
    x: np.ndarray
    y: int
    activity: str
    room: str
    session: str
    start: int

def _read_csi_har_session(session: Path, amplitude_columns: int = 570) -> tuple[np.ndarray,list[str]]:
    data=np.loadtxt(session/"data.csv",delimiter=",",skiprows=1,dtype=np.float32)
    if data.ndim != 2 or data.shape[1] < amplitude_columns: raise ValueError(f"unexpected data shape in {session}: {data.shape}")
    # label.csv has no header; its first row is already ``0,standing``.
    with (session/"label.csv").open(encoding="utf-8-sig",newline="") as f: rows=list(csv.reader(f))
    labels=[row[-1].strip() for row in rows if row]
    if len(labels)!=len(data): raise ValueError(f"data/label mismatch in {session}: {len(data)} != {len(labels)}")
    amp=data[:,:amplitude_columns].reshape(len(data),-1,114).mean(axis=1)
    return amp,labels

def iter_csi_har_windows(root: Path | str, window: int=250, stride: int=125, purity: float=.9) -> Iterator[CsiHarWindow]:
    for session in sorted(Path(root).glob("room_*/*")):
        if not (session/"data.csv").exists(): continue
        amp,labels=_read_csi_har_session(session)
        for start in range(0,len(labels)-window+1,stride):
            chunk=labels[start:start+window]
            values,counts=np.unique(chunk,return_counts=True)
            activity=str(values[int(np.argmax(counts))])
            if counts.max()/window < purity: continue
            y=target_label(activity)
            if y is None: continue
            yield CsiHarWindow(amp[start:start+window],y,activity,session.parent.name,session.name,start)
