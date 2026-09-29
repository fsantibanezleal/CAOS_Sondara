"""Independent implementations of the published equations; no source from the authors' unlicensed repositories.

DeepKriging (Chen, Li, Reich and Sun, Statistica Sinica 2024) and KCN (Appleby, Liu and Liu, AAAI 2020) take raw
inputs and compute their features inside the graph, so the exported ONNX model and the PyTorch model are one
computation. Both return native units: ``mean + scale * f``. Design: docs/design/features/learned-regression/design.md.
"""

from __future__ import annotations

import torch
from torch import nn


def _dense(inputs: int, widths: list[int], dropout: float) -> nn.Sequential:
    layers: list[nn.Module] = []
    for width in widths:
        layers.extend([nn.Linear(inputs, width), nn.ReLU(), nn.Dropout(dropout)])
        inputs = width
    layers.append(nn.Linear(inputs, 1))
    return nn.Sequential(*layers)


class DeepKriging(nn.Module):
    """Input: positions minus the frozen origin, in metres, shape (batch, 3). Output: native values, shape (batch,)."""

    def __init__(self, basis: dict, widths: list[int], dropout: float, mean: float, scale: float,
                 coordinate_only: bool = False):
        super().__init__()
        knots = [] if coordinate_only else basis["knots"]
        self.register_buffer("axis_scale", torch.tensor(basis["coordinates"]["scale"], dtype=torch.float32))
        self.register_buffer("knots", torch.tensor(knots, dtype=torch.float32).reshape(-1, 3))
        self.register_buffer("radii", torch.tensor([] if coordinate_only else basis["radii"], dtype=torch.float32))
        self.register_buffer("mean", torch.tensor(mean, dtype=torch.float32))
        self.register_buffer("scale", torch.tensor(scale, dtype=torch.float32))
        self.basis_columns = len(knots)
        self.regressor = _dense(3 + len(knots), widths, dropout)

    def features(self, local: torch.Tensor) -> torch.Tensor:
        u = local / self.axis_scale
        if self.basis_columns == 0:
            return u
        delta = u[:, None, :] - self.knots[None, :, :]
        r = torch.sqrt(torch.sum(delta * delta, dim=-1)) / self.radii
        c = torch.clamp(1.0 - r, min=0.0)
        phi = c**6 * (35.0 * r * r + 18.0 * r + 3.0) / 3.0
        return torch.cat([u, phi], dim=1)

    def forward(self, local: torch.Tensor) -> torch.Tensor:
        return self.mean + self.scale * self.regressor(self.features(local)).squeeze(-1)


class KCN(nn.Module):
    """Inputs, row 0 the query, shape (batch, K+1[, 3]): positions relative to the query (metres), native values,
    known flags, support lengths (metres), trajectory kinds, validity. Output: native values, shape (batch,)."""

    FEATURES = 8

    def __init__(self, width: int, mean: float, scale: float, dbar: float, length_scale: float, phi: float):
        super().__init__()
        for name, value in (("mean", mean), ("scale", scale), ("dbar", dbar), ("length_scale", length_scale),
                            ("phi", phi)):
            self.register_buffer(name, torch.tensor(value, dtype=torch.float32))
        self.first = nn.Linear(self.FEATURES, width)
        self.second = nn.Linear(width, width)
        self.head = nn.Linear(width, 1)

    def graph(self, positions, values, known, lengths, trajectory, valid):
        """Node features (eq. 10, adapted) and the normalized adjacency (eqs. 9 and 3), padding masked out."""
        query = valid * (1.0 - known)
        relative = positions / self.dbar
        features = torch.stack([(values - self.mean) / self.scale * known, known, query, relative[..., 0],
                                relative[..., 1], relative[..., 2], lengths / self.length_scale, trajectory], dim=-1)
        features = features * valid.unsqueeze(-1)
        delta = positions.unsqueeze(2) - positions.unsqueeze(1)
        pair = valid.unsqueeze(2) * valid.unsqueeze(1)
        a = torch.exp(-torch.sum(delta * delta, dim=-1) / (2.0 * self.phi * self.phi)) * pair
        # (A + I) over the valid nodes: A already holds exp(0) = 1 on its diagonal, so the self weight is 2.
        eye = torch.diag_embed(valid)
        degree = torch.sum(a, dim=-1) + valid
        inverse = valid / torch.sqrt(degree + (1.0 - valid))
        adjacency = inverse.unsqueeze(2) * (a + eye) * inverse.unsqueeze(1)
        return features, adjacency

    def forward(self, positions, values, known, lengths, trajectory, valid) -> torch.Tensor:
        features, adjacency = self.graph(positions, values, known, lengths, trajectory, valid)
        mask = valid.unsqueeze(-1)
        hidden = torch.relu(self.first(torch.bmm(adjacency, features))) * mask
        hidden = torch.relu(self.second(torch.bmm(adjacency, hidden))) * mask
        return self.mean + self.scale * self.head(hidden[:, 0]).squeeze(-1)


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
