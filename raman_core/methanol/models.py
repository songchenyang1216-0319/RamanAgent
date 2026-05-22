"""神经网络模型定义。"""

from __future__ import annotations

import torch
import torch.nn as nn


TARGET_LENGTH = 1024
BASELINE_POWER = 1.0


class ConvAutoEncoder(nn.Module):
    """用于光谱去噪的 1D 卷积自编码器。"""

    def __init__(self, input_length: int = TARGET_LENGTH):
        super().__init__()
        self.input_length = input_length
        self.encoder = nn.Sequential(
            nn.Conv1d(1, 16, kernel_size=5, padding=2),
            nn.ReLU(inplace=True),
            nn.MaxPool1d(2),
            nn.Conv1d(16, 32, kernel_size=5, padding=2),
            nn.ReLU(inplace=True),
            nn.MaxPool1d(2),
            nn.Conv1d(32, 64, kernel_size=5, padding=2),
            nn.ReLU(inplace=True),
        )
        self.decoder = nn.Sequential(
            nn.ConvTranspose1d(64, 32, kernel_size=4, stride=2, padding=1),
            nn.ReLU(inplace=True),
            nn.ConvTranspose1d(32, 16, kernel_size=4, stride=2, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv1d(16, 1, kernel_size=5, padding=2),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = self.encoder(x)
        out = self.decoder(z)
        return out

    def encode_vector(self, x: torch.Tensor) -> torch.Tensor:
        z = self.encoder(x)
        return z.mean(dim=2)


class CAEPlusBaseline(nn.Module):
    """用于估计基线背景的 CAE+ 网络。"""

    def __init__(self, baseline_power: float = BASELINE_POWER):
        super().__init__()
        self.baseline_power = baseline_power

        self.encoder = nn.Sequential(
            nn.Conv1d(1, 32, kernel_size=5, padding=2),
            nn.ReLU(inplace=True),
            nn.MaxPool1d(2),
            nn.Conv1d(32, 64, kernel_size=5, padding=2),
            nn.ReLU(inplace=True),
            nn.MaxPool1d(2),
            nn.Conv1d(64, 64, kernel_size=5, padding=2),
            nn.ReLU(inplace=True),
            nn.MaxPool1d(2),
            nn.Conv1d(64, 128, kernel_size=5, padding=2),
            nn.ReLU(inplace=True),
            nn.MaxPool1d(2),
        )

        self.bottleneck = nn.Sequential(
            nn.Conv1d(128, 64, kernel_size=5, padding=2),
            nn.ReLU(inplace=True),
            nn.Conv1d(64, 32, kernel_size=5, padding=2),
            nn.ReLU(inplace=True),
            nn.Conv1d(32, 32, kernel_size=5, padding=2),
            nn.ReLU(inplace=True),
            nn.Conv1d(32, 64, kernel_size=5, padding=2),
            nn.ReLU(inplace=True),
        )

        self.decoder = nn.Sequential(
            nn.ConvTranspose1d(64, 64, kernel_size=4, stride=2, padding=1),
            nn.ReLU(inplace=True),
            nn.ConvTranspose1d(64, 64, kernel_size=4, stride=2, padding=1),
            nn.ReLU(inplace=True),
            nn.ConvTranspose1d(64, 32, kernel_size=4, stride=2, padding=1),
            nn.ReLU(inplace=True),
            nn.ConvTranspose1d(32, 16, kernel_size=4, stride=2, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv1d(16, 1, kernel_size=5, padding=2),
            nn.Sigmoid(),
        )

    def comparison_function(self, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        x = torch.clamp(x, 0.0, 1.0)
        y = torch.clamp(y, 0.0, 1.0)
        est = torch.minimum(x, y)
        if self.baseline_power != 1.0:
            est = torch.pow(torch.clamp(est, min=1e-8), self.baseline_power)
        return est

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = self.encoder(x)
        feat = self.bottleneck(feat)
        decoded = self.decoder(feat)
        baseline = self.comparison_function(x, decoded)
        return baseline
