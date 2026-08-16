"""CSI-specific 2-D CNN baselines."""
from __future__ import annotations
import torch
from torch import nn

class ConvBlock(nn.Sequential):
    def __init__(self, in_channels: int, out_channels: int, stride: int = 1):
        super().__init__(
            nn.Conv2d(in_channels, out_channels, 3, stride=stride, padding=1, bias=False),
            nn.BatchNorm2d(out_channels), nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
        )

class SimpleCsiCnn(nn.Module):
    def __init__(self, num_classes: int = 3, dropout: float = 0.3):
        super().__init__()
        self.features = nn.Sequential(ConvBlock(1,32,2), ConvBlock(32,64), ConvBlock(64,128))
        self.head = nn.Sequential(nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Dropout(dropout), nn.Linear(128,num_classes))
    def forward(self, x): return self.head(self.features(x))

class BasicBlock(nn.Module):
    expansion = 1
    def __init__(self, in_channels: int, out_channels: int, stride: int = 1):
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv2d(in_channels,out_channels,3,stride,padding=1,bias=False), nn.BatchNorm2d(out_channels), nn.ReLU(inplace=True),
            nn.Conv2d(out_channels,out_channels,3,padding=1,bias=False), nn.BatchNorm2d(out_channels),
        )
        self.skip = nn.Identity() if stride == 1 and in_channels == out_channels else nn.Sequential(
            nn.Conv2d(in_channels,out_channels,1,stride,bias=False), nn.BatchNorm2d(out_channels)
        )
        self.relu = nn.ReLU(inplace=True)
    def forward(self, x): return self.relu(self.body(x) + self.skip(x))

class CsiResNet18(nn.Module):
    """ResNet-18 with a 3x3 CSI stem instead of the ImageNet 7x7 stem."""
    def __init__(self, num_classes: int = 3, dropout: float = 0.3):
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(1,64,7,stride=2,padding=3,bias=False), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.MaxPool2d(3,stride=2,padding=1),
        )
        self.in_channels = 64
        self.layers = nn.Sequential(self._layer(64,2,1), self._layer(128,2,2), self._layer(256,2,2), self._layer(512,2,2))
        self.head = nn.Sequential(nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Dropout(dropout), nn.Linear(512,num_classes))
        self.apply(self._init)
    def _layer(self, channels, blocks, stride):
        result=[BasicBlock(self.in_channels,channels,stride)]; self.in_channels=channels
        result.extend(BasicBlock(channels,channels) for _ in range(1,blocks))
        return nn.Sequential(*result)
    @staticmethod
    def _init(module):
        if isinstance(module,nn.Conv2d): nn.init.kaiming_normal_(module.weight,mode="fan_out",nonlinearity="relu")
        elif isinstance(module,(nn.BatchNorm1d,nn.BatchNorm2d)): nn.init.ones_(module.weight); nn.init.zeros_(module.bias)
    def forward(self, x): return self.head(self.layers(self.stem(x)))

def make_model(name: str, num_classes: int = 3, dropout: float = 0.3) -> nn.Module:
    if name == "simple_cnn": return SimpleCsiCnn(num_classes,dropout)
    if name == "resnet18": return CsiResNet18(num_classes,dropout)
    raise ValueError(f"unknown model: {name}")
