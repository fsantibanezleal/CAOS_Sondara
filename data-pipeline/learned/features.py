"""Train-only transforms and the NumPy oracles of the learned methods.

The fitted models compute their own features inside the graph (``learned/networks.py``); the functions here fit the
transforms on training rows only and give an independent NumPy reference for the tests. Design:
docs/design/features/learned-regression/design.md, sections 2 to 4.
"""

from __future__ import annotations

import itertools

import numpy as np
from scipy.spatial.distance import cdist

#: DeepKriging knot levels per axis: the contract's compact levels and the paper's first two, (9 * 2^(h-1) + 1).
KNOT_LEVELS = {"compact-3-5-9": (3, 5, 9), "paper-10-19": (10, 19)}
#: The radius of a knot level in knot spacings (Chen et al.: "2.5 times the associated knots spacing").
RADIUS_SPACINGS = 2.5
#: The scale of an axis with zero training extent, in metres.
DEGENERATE_SCALE = 1.0


def coordinate_transform(train_xyz: np.ndarray) -> dict:
    """The training box: origin at the minimum, one scale per axis (its extent, or one metre when it is zero)."""
    xyz = np.asarray(train_xyz, dtype=np.float64)
    origin = xyz.min(axis=0)
    extent = xyz.max(axis=0) - origin
    return {"origin": origin.tolist(), "scale": np.where(extent > 0, extent, DEGENERATE_SCALE).tolist(),
            "degenerate": (extent == 0).tolist()}


def local(xyz: np.ndarray, transform: dict) -> np.ndarray:
    """Positions minus the frozen origin, in metres, subtracted in float64 (the exported graph's input)."""
    return np.asarray(xyz, dtype=np.float64) - np.asarray(transform["origin"])


def normalize(xyz: np.ndarray, transform: dict) -> np.ndarray:
    return local(xyz, transform) / np.asarray(transform["scale"])


def outside_box(xyz: np.ndarray, transform: dict) -> np.ndarray:
    """True where a position lies outside the training box on any axis (it is never clipped)."""
    u = normalize(xyz, transform)
    return np.any((u < 0) | (u > 1), axis=1)


def wendland(r: np.ndarray) -> np.ndarray:
    distance = np.asarray(r, dtype=np.float64)
    if np.any(distance < 0):
        raise ValueError("a radial distance cannot be negative")
    return np.maximum(1.0 - distance, 0.0) ** 6 * (35 * distance**2 + 18 * distance + 3) / 3


def fit_basis(train_xyz: np.ndarray, levels: tuple[int, ...]) -> dict:
    """Knots on rectangular levels over the training box; a knot whose column is zero on every training row is dropped."""
    transform = coordinate_transform(train_xyz)
    u = normalize(train_xyz, transform)
    knots, radii, level_of, candidates = [], [], [], 0
    for count in levels:
        grid = np.asarray(list(itertools.product(np.linspace(0.0, 1.0, count), repeat=3)))
        radius = RADIUS_SPACINGS / (count - 1)
        candidates += len(grid)
        active = np.any(wendland(cdist(u, grid) / radius) > 0, axis=0)
        knots.extend(grid[active].tolist())
        radii.extend([radius] * int(active.sum()))
        level_of.extend([count] * int(active.sum()))
    return {"coordinates": transform, "levels": list(levels), "knots": knots, "radii": radii, "knotLevel": level_of,
            "candidateColumns": candidates, "removedZeroColumns": candidates - len(knots)}


def basis_features(xyz: np.ndarray, basis: dict, coordinate_only: bool = False) -> np.ndarray:
    """The NumPy oracle of the DeepKriging input: normalized position, then every retained basis column."""
    u = normalize(xyz, basis["coordinates"])
    if coordinate_only or not basis["knots"]:
        return u
    radial = wendland(cdist(u, np.asarray(basis["knots"])) / np.asarray(basis["radii"]))
    return np.concatenate([u, radial], axis=1)


def target_transform(y_train: np.ndarray) -> dict:
    y = np.asarray(y_train, dtype=np.float64)
    standard = float(np.std(y))
    return {"mean": float(np.mean(y)), "scale": standard if standard > 0 else 1.0, "constant": standard == 0}


def select_neighbours(query_xyz: np.ndarray, query_holes, conditioning: dict, k: int, *, per_hole: int = 4,
                      min_holes: int = 2) -> tuple[np.ndarray, np.ndarray, list[str | None]]:
    """The KCN neighbour search, in metres: stable order (distance, then row id), the query's own hole excluded, at
    most ``per_hole`` rows from one hole, and at least ``min_holes`` distinct holes.

    Returns the selected conditioning indices (padded with -1), whether each query is supported, and the reason when
    it is not.
    """
    if k < min_holes or per_hole < 1:
        raise ValueError("inconsistent neighbourhood policy")
    distance = cdist(np.asarray(query_xyz, dtype=np.float64), conditioning["xyz"])
    order_key = conditioning["order"]
    selected = np.full((len(distance), k), -1, dtype=np.int64)
    supported = np.zeros(len(distance), dtype=bool)
    reasons: list[str | None] = []
    for row, values in enumerate(distance):
        counts: dict[str, int] = {}
        take = []
        for index in np.lexsort((order_key, values)):
            hole = conditioning["holes"][index]
            if hole == query_holes[row] or counts.get(hole, 0) >= per_hole:
                continue
            take.append(index)
            counts[hole] = counts.get(hole, 0) + 1
            if len(take) == k:
                break
        selected[row, :len(take)] = take
        if len(counts) >= min_holes:
            supported[row] = True
            reasons.append(None)
        else:
            reasons.append(f"{len(counts)} distinct conditioning hole(s) within reach; {min_holes} required")
    return selected, supported, reasons


def neighbour_scale(query_xyz: np.ndarray, selected: np.ndarray, conditioning_xyz: np.ndarray) -> float:
    """The median, over queries, of the distances to their selected neighbours (the KCN distance scale)."""
    distances = []
    for q, index in zip(np.asarray(query_xyz, dtype=np.float64), selected, strict=True):
        use = index[index >= 0]
        if len(use):
            distances.append(np.linalg.norm(conditioning_xyz[use] - q, axis=1))
    if not distances:
        raise ValueError("no query has a neighbour")
    return float(np.median(np.concatenate(distances)))


def graph_inputs(query: dict, conditioning: dict, selected: np.ndarray) -> dict:
    """The raw KCN inputs, row 0 the query: positions relative to the query (metres), native values, known flags,
    support lengths, trajectory kinds and validity. The model builds its features and graph from these."""
    n, k = selected.shape
    safe = np.maximum(selected, 0)
    real = selected >= 0
    positions = np.zeros((n, k + 1, 3))
    positions[:, 1:] = (conditioning["xyz"][safe] - np.asarray(query["xyz"], dtype=np.float64)[:, None, :]) * real[..., None]
    values = np.zeros((n, k + 1))
    values[:, 1:] = conditioning["y"][safe] * real
    known = np.zeros((n, k + 1))
    known[:, 1:] = real
    lengths = np.zeros((n, k + 1))
    lengths[:, 0] = query["length"]
    lengths[:, 1:] = conditioning["length"][safe] * real
    trajectory = np.zeros((n, k + 1))
    trajectory[:, 0] = query["trajectory"]
    trajectory[:, 1:] = conditioning["trajectory"][safe] * real
    valid = np.zeros((n, k + 1))
    valid[:, 0] = 1
    valid[:, 1:] = real
    return {"positions": positions, "values": values, "known": known, "lengths": lengths,
            "trajectory": trajectory, "valid": valid}


def graph_oracle(inputs: dict, mean: float, scale: float, dbar: float, length_scale: float, phi: float) -> dict:
    """NumPy reference of the KCN node features and normalized adjacency (Appleby et al. 2020, eqs. 9, 10 and 3)."""
    valid = inputs["valid"]
    known = inputs["known"]
    features = np.stack([(inputs["values"] - mean) / scale * known, known, valid * (1 - known),
                         inputs["positions"][..., 0] / dbar, inputs["positions"][..., 1] / dbar,
                         inputs["positions"][..., 2] / dbar, inputs["lengths"] / length_scale,
                         inputs["trajectory"]], axis=-1) * valid[..., None]
    delta = inputs["positions"][:, :, None, :] - inputs["positions"][:, None, :, :]
    a = np.exp(-np.sum(delta**2, axis=-1) / (2 * phi**2)) * valid[:, :, None] * valid[:, None, :]
    eye = np.eye(valid.shape[1])[None] * valid[:, :, None]
    degree = a.sum(axis=-1) + valid
    inverse = np.where(valid > 0, 1 / np.sqrt(np.where(degree > 0, degree, 1)), 0)
    return {"features": features, "adjacency": inverse[:, :, None] * (a + eye) * inverse[:, None, :]}


def fit_geochemistry(train: np.ndarray, properties: list[str]) -> dict:
    median = np.median(train, axis=0)
    scale = np.quantile(train, .75, axis=0) - np.quantile(train, .25, axis=0)
    active = scale > 0
    if active.sum() < 3:
        raise ValueError("geochemistry requires three nonconstant complete properties")
    return {"properties": [p for p, flag in zip(properties, active, strict=True) if flag],
            "indices": np.flatnonzero(active).tolist(), "median": median[active].tolist(),
            "scale": scale[active].tolist(),
            "removedZeroIqr": [p for p, flag in zip(properties, active, strict=True) if not flag]}


def geochemical_features(values: np.ndarray, transform: dict) -> np.ndarray:
    subset = np.asarray(values, dtype=np.float64)[:, transform["indices"]]
    if not np.isfinite(subset).all():
        raise ValueError("incomplete geochemical record")
    return np.arcsinh((subset - transform["median"]) / transform["scale"]).astype(np.float32)
