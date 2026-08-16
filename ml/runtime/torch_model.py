"""PyTorch checkpoint adapter for the stable gateway ActivityModel contract."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import torch
from csi_gateway.activity import ActivityPrediction,ActivityWindow
from ml.v5.models import make_model

class TorchCnnActivityModel:
    def __init__(self,checkpoint_path: str|Path,device: str|None=None):
        self.path=Path(checkpoint_path); self.device=torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        checkpoint=torch.load(self.path,map_location=self.device,weights_only=False)
        self.labels=tuple(checkpoint["labels"]); self.window_frames=int(checkpoint.get("input_frames",950))
        self.model=make_model(checkpoint["model_name"],len(self.labels)); self.model.load_state_dict(checkpoint["model_state"])
        self.model.to(self.device).eval(); self.model_version=str(checkpoint.get("model_version",self.path.stem))
    def predict(self,window: ActivityWindow) -> ActivityPrediction:
        x=np.asarray(window.amplitude,dtype=np.float32)
        if x.shape!=(self.window_frames,52): raise ValueError(f"expected ({self.window_frames},52), got {x.shape}")
        x=(x-x.mean(0,keepdims=True))/np.maximum(x.std(0,keepdims=True),1e-6)
        tensor=torch.from_numpy(x[None,None]).to(self.device)
        with torch.inference_mode(),torch.amp.autocast(device_type=self.device.type,enabled=self.device.type=="cuda"):
            probabilities=self.model(tensor).softmax(1)[0].float().cpu().numpy()
        scores={self._external(name):float(value) for name,value in zip(self.labels,probabilities)}
        label=max(scores,key=scores.get)
        return ActivityPrediction(label,scores,scores[label],window.first_sequence,window.last_sequence,
            window.finished_at,self.model_version,"amplitude-zscore-v1")
    @staticmethod
    def _external(label: str) -> str: return "fall_suspected" if label=="fall" else label

