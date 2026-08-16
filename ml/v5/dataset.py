"""ESP-Fi HAR indexing, leakage-safe splits, and PyTorch dataset."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from scipy.io import loadmat
import torch
from torch.utils.data import Dataset

ACTIVITY_BY_ID={"1":"run","2":"walk","3":"jump","4":"squat","5":"arm_wave","6":"turn","7":"fall"}
LABEL_NAMES=("fall","walking","other_motion")

def collapse_label(activity: str) -> int:
    if activity == "fall": return 0
    if activity == "walk": return 1
    return 2

@dataclass(frozen=True)
class Record:
    path: Path; environment: int; participant: int; activity: str; trial: int; label: int

def index_espfi(root: Path | str) -> list[Record]:
    records=[]
    for path in sorted(Path(root).rglob("*.mat")):
        env,participant,activity_id,trial=path.stem.split("-")
        activity=ACTIVITY_BY_ID.get(activity_id)
        if activity is None: raise ValueError(f"unknown activity id in {path}")
        records.append(Record(path,int(env),int(participant),activity,int(trial),collapse_label(activity)))
    if not records: raise FileNotFoundError(f"no .mat files below {root}")
    return records

def split_records(records: list[Record], protocol: str="participant") -> dict[str,list[Record]]:
    if protocol == "participant":
        groups={"train":{1,2,3,4,5},"val":{6},"test":{7,8}}
        key=lambda r:r.participant
    elif protocol == "environment":
        groups={"train":{1,2},"val":{3},"test":{4}}
        key=lambda r:r.environment
    else: raise ValueError("protocol must be participant or environment")
    splits={name:[r for r in records if key(r) in values] for name,values in groups.items()}
    if any(not rows for rows in splits.values()): raise ValueError(f"empty split: { {k:len(v) for k,v in splits.items()} }")
    paths=[{r.path for r in rows} for rows in splits.values()]
    if any(paths[i]&paths[j] for i in range(3) for j in range(i+1,3)): raise AssertionError("split leakage")
    return splits

def load_amplitude(path: Path) -> np.ndarray:
    x=np.asarray(loadmat(path)["CSIamp"],dtype=np.float32)
    if x.shape == (52,950): x=x.T
    if x.shape != (950,52): raise ValueError(f"expected (950,52), got {x.shape}: {path}")
    return x

class EspFiDataset(Dataset):
    def __init__(self, records: list[Record], augment: bool=False): self.records=records; self.augment=augment
    def __len__(self): return len(self.records)
    def __getitem__(self,index):
        record=self.records[index]; x=load_amplitude(record.path)
        # Per-sample, per-subcarrier normalization cannot leak test statistics.
        x=(x-x.mean(axis=0,keepdims=True))/np.maximum(x.std(axis=0,keepdims=True),1e-6)
        if self.augment:
            x=x*np.random.uniform(.9,1.1)
            x=x+np.random.normal(0,.01,x.shape).astype(np.float32)
            x=np.roll(x,np.random.randint(-20,21),axis=0)
        return torch.from_numpy(np.ascontiguousarray(x[None],dtype=np.float32)), record.label, index

