"""Independent implementations of the equations cited in docs/methods/learned-*.

No source from the unlicensed author repositories is vendored or translated.
"""

from __future__ import annotations

import torch
from torch import nn


class SpatialRegressor(nn.Module):
    def __init__(self, inputs: int, widths: list[int], dropout: float = 0):
        super().__init__()
        layers = []
        for width in widths:
            layers.extend([nn.Linear(inputs, width), nn.ReLU(), nn.Dropout(dropout)])
            inputs = width
        layers.append(nn.Linear(inputs, 1))
        self.network = nn.Sequential(*layers)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.network(features).squeeze(-1)


class LocalGraphRegressor(nn.Module):
    def __init__(self, width: int):
        super().__init__()
        self.first = nn.Linear(8, width)
        self.second = nn.Linear(width, width)
        self.head = nn.Linear(width, 1)

    def forward(self, features: torch.Tensor, adjacency: torch.Tensor,
                valid: torch.Tensor) -> torch.Tensor:
        mask = valid.unsqueeze(-1)
        hidden = torch.relu(self.first(torch.bmm(adjacency, features))) * mask
        hidden = torch.relu(self.second(torch.bmm(adjacency, hidden))) * mask
        return self.head(hidden[:, 0]).squeeze(-1)


class GeochemicalAutoencoder(nn.Module):
    def __init__(self, features: int, latent: int):
        super().__init__()
        if latent >= features:
            raise ValueError("latent space must be a real bottleneck")
        self.encoder = nn.Sequential(nn.Linear(features, 32), nn.ReLU(), nn.Linear(32, 8),
                                     nn.ReLU(), nn.Linear(8, latent))
        self.decoder = nn.Sequential(nn.Linear(latent, 8), nn.ReLU(), nn.Linear(8, 32),
                                     nn.ReLU(), nn.Linear(32, features))

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.decoder(self.encoder(features))


class NativeRegressor(nn.Module):
    def __init__(self, model: nn.Module, mean: float, scale: float):
        super().__init__()
        self.model = model
        self.register_buffer("mean", torch.tensor(mean, dtype=torch.float32))
        self.register_buffer("scale", torch.tensor(scale, dtype=torch.float32))

    def forward(self, *inputs: torch.Tensor) -> torch.Tensor:
        return self.mean + self.scale * self.model(*inputs)


class GeochemicalExport(nn.Module):
    def __init__(self, model: GeochemicalAutoencoder, median: list[float], scale: list[float]):
        super().__init__()
        self.model = model
        self.register_buffer("median", torch.tensor(median, dtype=torch.float32))
        self.register_buffer("scale", torch.tensor(scale, dtype=torch.float32))

    def forward(self, values: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        transformed = torch.asinh((values - self.median) / self.scale)
        latent = self.model.encoder(transformed)
        residual = (transformed - self.model.decoder(latent)) ** 2
        return latent, residual, residual.mean(dim=-1)
