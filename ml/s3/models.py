"""Temporal S3 model candidates and recall-oriented losses."""
from __future__ import annotations

import torch
from torch import nn


class FocalLoss(nn.Module):
    def __init__(self, *, gamma: float = 2.0, positive_weight: float = 1.0) -> None:
        super().__init__()
        self.gamma = gamma
        self.register_buffer("class_weight", torch.tensor([1.0, positive_weight]))

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        cross_entropy = nn.functional.cross_entropy(logits, target, weight=self.class_weight, reduction="none")
        probability = torch.exp(-cross_entropy)
        return (((1.0 - probability) ** self.gamma) * cross_entropy).mean()


class TemporalResidualBlock(nn.Module):
    def __init__(self, channels: int, dilation: int, dropout: float) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv1d(channels, channels, 5, padding=2 * dilation, dilation=dilation, bias=False),
            nn.BatchNorm1d(channels),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Conv1d(channels, channels, 3, padding=dilation, dilation=dilation, bias=False),
            nn.BatchNorm1d(channels),
        )
        self.activation = nn.GELU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.activation(x + self.body(x))


class S3Tcn(nn.Module):
    """Model B: temporal convolutions over all selected subcarriers."""
    def __init__(self, input_channels: int = 4, subcarriers: int = 52, hidden: int = 96, dropout: float = 0.25) -> None:
        super().__init__()
        self.input_channels = input_channels
        self.subcarriers = subcarriers
        self.projection = nn.Sequential(
            nn.Conv1d(input_channels * subcarriers, hidden, 1, bias=False),
            nn.BatchNorm1d(hidden),
            nn.GELU(),
        )
        self.temporal = nn.Sequential(
            TemporalResidualBlock(hidden, 1, dropout),
            TemporalResidualBlock(hidden, 2, dropout),
            TemporalResidualBlock(hidden, 4, dropout),
            TemporalResidualBlock(hidden, 8, dropout),
        )
        self.head = nn.Sequential(
            nn.AdaptiveMaxPool1d(1),
            nn.Flatten(),
            nn.Dropout(dropout),
            nn.Linear(hidden, 2),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 4:
            raise ValueError("expected [batch, channels, time, subcarrier]")
        batch, channels, time, carriers = x.shape
        if channels != self.input_channels or carriers != self.subcarriers:
            raise ValueError(f"expected channels={self.input_channels}, subcarriers={self.subcarriers}")
        flattened = x.permute(0, 1, 3, 2).reshape(batch, channels * carriers, time)
        return self.head(self.temporal(self.projection(flattened)))


class S3CnnGru(nn.Module):
    """Model C: local CSI feature extractor followed by bidirectional GRU."""
    def __init__(self, input_channels: int = 4, hidden: int = 96, dropout: float = 0.25) -> None:
        super().__init__()
        self.input_channels = input_channels
        self.local = nn.Sequential(
            nn.Conv2d(input_channels, 32, (7, 5), padding=(3, 2), bias=False),
            nn.BatchNorm2d(32),
            nn.GELU(),
            nn.MaxPool2d((2, 2)),
            nn.Conv2d(32, 64, (5, 3), padding=(2, 1), bias=False),
            nn.BatchNorm2d(64),
            nn.GELU(),
            nn.MaxPool2d((2, 2)),
        )
        self.gru = nn.GRU(64, hidden, num_layers=2, batch_first=True, bidirectional=True, dropout=dropout)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(hidden * 2, 2))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 4 or x.shape[1] != self.input_channels:
            raise ValueError(f"expected [batch, {self.input_channels}, time, subcarrier]")
        local = self.local(x).mean(dim=3).transpose(1, 2)
        sequence, _ = self.gru(local)
        return self.head(sequence.amax(dim=1))


class S3Lightweight2dCnn(nn.Module):
    """Optional time×subcarrier ablation candidate."""
    def __init__(self, input_channels: int = 4, dropout: float = 0.25) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(input_channels, 32, 5, padding=2, bias=False),
            nn.BatchNorm2d(32),
            nn.GELU(),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1, bias=False),
            nn.BatchNorm2d(64),
            nn.GELU(),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1, bias=False),
            nn.BatchNorm2d(128),
            nn.GELU(),
        )
        self.head = nn.Sequential(nn.AdaptiveMaxPool2d(1), nn.Flatten(), nn.Dropout(dropout), nn.Linear(128, 2))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.features(x))


def make_s3_model(name: str, *, input_channels: int = 4, subcarriers: int = 52) -> nn.Module:
    if name == "tcn":
        return S3Tcn(input_channels=input_channels, subcarriers=subcarriers)
    if name == "cnn_gru":
        return S3CnnGru(input_channels=input_channels)
    if name == "cnn2d":
        return S3Lightweight2dCnn(input_channels=input_channels)
    raise ValueError(f"unknown S3 model: {name}")
