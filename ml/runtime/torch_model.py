"""PyTorch checkpoint adapter for the stable gateway ActivityModel contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from csi_gateway.activity import ActivityPrediction, ActivityWindow
from ml.v5.models import make_model


class ActivityModelLoadError(RuntimeError):
    """Raised when a deployed activity checkpoint does not match its contract."""


def select_inference_device(requested: str | None = None) -> torch.device:
    if requested:
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TorchCnnActivityModel:
    def __init__(
        self,
        checkpoint_path: str | Path,
        device: str | None = None,
        *,
        verify_spec: bool = True,
    ) -> None:
        self.path = Path(checkpoint_path).resolve()
        if not self.path.is_file():
            raise ActivityModelLoadError(f"모델 파일을 찾을 수 없습니다: {self.path}")

        self.spec = self._load_spec() if verify_spec else None
        if self.spec is not None:
            expected_hash = str(self.spec.get("model_sha256", "")).lower()
            actual_hash = sha256_file(self.path)
            if expected_hash and actual_hash != expected_hash:
                raise ActivityModelLoadError(
                    "모델 SHA-256이 MODEL_SPEC.json과 일치하지 않습니다. "
                    f"expected={expected_hash}, actual={actual_hash}"
                )

        self.device = select_inference_device(device)
        try:
            checkpoint = torch.load(
                self.path,
                map_location=self.device,
                weights_only=False,
            )
            self.labels = tuple(checkpoint["labels"])
            self.window_frames = int(checkpoint.get("input_frames", 950))
            self.model_name = str(checkpoint["model_name"])
            self.model = make_model(self.model_name, len(self.labels))
            self.model.load_state_dict(checkpoint["model_state"])
            self.model.to(self.device).eval()
            self.model_version = str(
                checkpoint.get("model_version", self.path.stem)
            )
        except Exception as exc:
            raise ActivityModelLoadError(
                f"PyTorch checkpoint를 불러오지 못했습니다: {exc}"
            ) from exc
        self._verify_loaded_contract()

    def _load_spec(self) -> dict[str, object] | None:
        spec_path = self.path.with_name("MODEL_SPEC.json")
        if not spec_path.is_file():
            return None
        try:
            return json.loads(spec_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ActivityModelLoadError(
                f"MODEL_SPEC.json을 읽지 못했습니다: {exc}"
            ) from exc

    def _verify_loaded_contract(self) -> None:
        if self.labels != ("fall", "walking", "other_motion"):
            raise ActivityModelLoadError(
                f"지원하지 않는 모델 라벨입니다: {self.labels}"
            )
        if self.spec is None:
            return
        input_spec = self.spec.get("input", {})
        expected_shape = input_spec.get("shape") if isinstance(input_spec, dict) else None
        if expected_shape != [self.window_frames, 52]:
            raise ActivityModelLoadError(
                "checkpoint 입력 크기와 MODEL_SPEC.json이 일치하지 않습니다: "
                f"checkpoint={[self.window_frames, 52]}, spec={expected_shape}"
            )
        expected_version = str(self.spec.get("model_version", ""))
        if expected_version and self.model_version != expected_version:
            raise ActivityModelLoadError(
                "checkpoint 모델 버전과 MODEL_SPEC.json이 일치하지 않습니다: "
                f"checkpoint={self.model_version}, spec={expected_version}"
            )
        expected_architecture = str(self.spec.get("architecture", ""))
        if expected_architecture and self.model_name != expected_architecture:
            raise ActivityModelLoadError(
                "checkpoint architecture와 MODEL_SPEC.json이 일치하지 않습니다: "
                f"checkpoint={self.model_name}, spec={expected_architecture}"
            )

    def predict(self, window: ActivityWindow) -> ActivityPrediction:
        x = np.asarray(window.amplitude, dtype=np.float32)
        if x.shape != (self.window_frames, 52):
            raise ValueError(
                f"expected ({self.window_frames},52), got {x.shape}"
            )
        x = (x - x.mean(0, keepdims=True)) / np.maximum(
            x.std(0, keepdims=True), 1e-6
        )
        try:
            probabilities = self._probabilities(x)
        except RuntimeError:
            if self.device.type != "mps":
                raise
            # Some PyTorch/torchvision combinations expose MPS but lack an
            # operator used by EfficientNet. Keep macOS usable via CPU.
            self.device = torch.device("cpu")
            self.model.to(self.device).eval()
            probabilities = self._probabilities(x)
        scores = {
            self._external(name): float(value)
            for name, value in zip(self.labels, probabilities)
        }
        label = max(scores, key=scores.get)
        return ActivityPrediction(
            label,
            scores,
            scores[label],
            window.first_sequence,
            window.last_sequence,
            window.finished_at,
            self.model_version,
            "amplitude-zscore-v1",
        )

    def _probabilities(self, x: np.ndarray) -> np.ndarray:
        tensor = torch.from_numpy(x[None, None]).to(self.device)
        with torch.inference_mode(), torch.amp.autocast(
            device_type=self.device.type,
            enabled=self.device.type == "cuda",
        ):
            return self.model(tensor).softmax(1)[0].float().cpu().numpy()

    @staticmethod
    def _external(label: str) -> str:
        return "fall_suspected" if label == "fall" else label
