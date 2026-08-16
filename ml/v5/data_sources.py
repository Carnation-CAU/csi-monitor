"""Common samples and four-fold definitions for all installed public datasets."""
from __future__ import annotations
import sys
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from scipy.io import loadmat
import torch
from sklearn.model_selection import GroupKFold,GroupShuffleSplit,StratifiedKFold,StratifiedShuffleSplit
from torch.utils.data import Dataset
try:
    from .dataset import index_espfi
except ImportError:
    from dataset import index_espfi

HERE=Path(__file__).resolve().parent
RAW=HERE.parent/"dataset"/"raw"
PUBLIC_LOADERS=HERE.parent/"dataset"
if str(PUBLIC_LOADERS) not in sys.path: sys.path.insert(0,str(PUBLIC_LOADERS))
from public_datasets import iter_csi_har_windows,load_ut_har  # noqa: E402

@dataclass(frozen=True)
class Sample:
    label: int
    group: str
    sample_id: str
    array: np.ndarray | None = None
    path: Path | None = None

@dataclass(frozen=True)
class Fold:
    number: int
    train: list[Sample]
    val: list[Sample]
    test: list[Sample]

@dataclass(frozen=True)
class DatasetSpec:
    name: str
    label_names: tuple[str,...]
    folds: list[Fold]
    note: str

def _augment(x: np.ndarray) -> np.ndarray:
    x=x*np.random.uniform(.9,1.1)
    x=x+np.random.normal(0,.01,x.shape).astype(np.float32)
    return np.roll(x,np.random.randint(-20,21),axis=0)

class PublicCsiDataset(Dataset):
    def __init__(self,samples: list[Sample],augment: bool=False): self.samples=samples; self.augment=augment
    def __len__(self): return len(self.samples)
    def __getitem__(self,index):
        sample=self.samples[index]
        if sample.array is not None: x=np.asarray(sample.array,dtype=np.float32)
        elif sample.path is not None: x=np.asarray(loadmat(sample.path)["CSIamp"],dtype=np.float32)
        else: raise ValueError(f"sample has no data: {sample.sample_id}")
        if x.shape == (52,950): x=x.T
        if x.ndim != 2: raise ValueError(f"expected 2-D CSI, got {x.shape}: {sample.sample_id}")
        x=(x-x.mean(0,keepdims=True))/np.maximum(x.std(0,keepdims=True),1e-6)
        if self.augment: x=_augment(x)
        return torch.from_numpy(np.ascontiguousarray(x[None],dtype=np.float32)),sample.label,index

def _select(items,indices): return [items[int(i)] for i in indices]

def espfi_folds(root: Path=RAW/"ESP-Fi-HAR-full") -> DatasetSpec:
    records=index_espfi(root)
    samples=[Sample(r.label,str(r.participant),r.path.stem,path=r.path) for r in records]
    pairs=({1,2},{3,4},{5,6},{7,8}); folds=[]
    for i,test_users in enumerate(pairs):
        val_users=pairs[(i+1)%4]
        folds.append(Fold(i+1,[s for s in samples if int(s.group) not in test_users|val_users],
            [s for s in samples if int(s.group) in val_users],[s for s in samples if int(s.group) in test_users]))
    return DatasetSpec("espfi",("fall","walking","other_motion"),folds,"participant-pair grouped 4-fold")

def ut_har_folds(root: Path=RAW/"UT-HAR"/"UT_HAR",seed: int=42) -> DatasetSpec:
    samples=[]
    for split in ("train","val"):
        x,y,_=load_ut_har(root,split)
        samples.extend(Sample(int(label),split,f"{split}-{i}",array=x[i]) for i,label in enumerate(y))
    labels=np.asarray([s.label for s in samples]); outer=StratifiedKFold(4,shuffle=True,random_state=seed); folds=[]
    for number,(remain,test) in enumerate(outer.split(np.zeros(len(labels)),labels),1):
        inner=StratifiedShuffleSplit(1,test_size=.15,random_state=seed+number)
        train_pos,val_pos=next(inner.split(np.zeros(len(remain)),labels[remain]))
        folds.append(Fold(number,_select(samples,remain[train_pos]),_select(samples,remain[val_pos]),_select(samples,test)))
    return DatasetSpec("ut_har",("fall","walking","other_motion"),folds,
        "stratified 4-fold on official train+val; official test remains locked")

def csi_har_folds(root: Path=RAW/"CSI-HAR-3room",seed: int=42) -> DatasetSpec:
    samples=[]
    for item in iter_csi_har_windows(root):
        # CSI-HAR has no fall: remap walking 1->0 and other_motion 2->1.
        label=0 if item.y==1 else 1
        group=f"{item.room}/{item.session}"
        samples.append(Sample(label,group,f"{group}-{item.start}",array=item.x))
    labels=np.asarray([s.label for s in samples]); groups=np.asarray([s.group for s in samples]); folds=[]
    outer=GroupKFold(4)
    for number,(remain,test) in enumerate(outer.split(np.zeros(len(labels)),labels,groups),1):
        inner=GroupShuffleSplit(1,test_size=.25,random_state=seed+number)
        train_pos,val_pos=next(inner.split(np.zeros(len(remain)),labels[remain],groups[remain]))
        folds.append(Fold(number,_select(samples,remain[train_pos]),_select(samples,remain[val_pos]),_select(samples,test)))
    return DatasetSpec("csi_har",("walking","other_motion"),folds,
        "session-grouped 4-fold; room leave-one-out is a separate 3-fold evaluation")

def load_spec(name: str,seed: int=42) -> DatasetSpec:
    if name=="espfi": return espfi_folds()
    if name=="ut_har": return ut_har_folds(seed=seed)
    if name=="csi_har": return csi_har_folds(seed=seed)
    raise ValueError(f"unknown dataset: {name}")
