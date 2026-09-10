"""Train-only feature transforms and explicit conditioning identities."""

from __future__ import annotations

import itertools

import numpy as np
from scipy.spatial.distance import cdist


def coordinate_transform(train_xyz: np.ndarray) -> dict:
    origin = train_xyz.min(axis=0)
    extent = train_xyz.max(axis=0) - origin
    return {"origin": origin.tolist(), "scale": np.where(extent > 0, extent, 1.0).tolist(),
            "degenerate": (extent == 0).tolist(), "maximum": train_xyz.max(axis=0).tolist()}


def normalize(xyz: np.ndarray, transform: dict) -> np.ndarray:
    return (np.asarray(xyz, dtype=np.float64) - transform["origin"]) / transform["scale"]


def wendland(r: np.ndarray) -> np.ndarray:
    distance = np.asarray(r, dtype=np.float64)
    if np.any(distance < 0):
        raise ValueError("a radial distance cannot be negative")
    return np.maximum(1.0 - distance, 0.0) ** 6 * (35 * distance**2 + 18 * distance + 3) / 3


def fit_basis(train_xyz: np.ndarray) -> dict:
    transform = coordinate_transform(train_xyz)
    normalized = normalize(train_xyz, transform)
    knots, radii, levels = [], [], []
    for count in (3, 5, 9):
        level = np.asarray(list(itertools.product(np.linspace(0, 1, count), repeat=3)))
        radius = 2.5 / (count - 1)
        active = np.any(wendland(cdist(normalized, level) / radius) > 0, axis=0)
        knots.extend(level[active].tolist())
        radii.extend([radius] * int(active.sum()))
        levels.extend([count] * int(active.sum()))
    return {"coordinates": transform, "knots": knots, "radii": radii, "levels": levels,
            "candidateColumns": 881, "removedZeroColumns": 881 - len(knots)}


def basis_features(xyz: np.ndarray, basis: dict, coordinate_only: bool = False) -> np.ndarray:
    normalized = normalize(xyz, basis["coordinates"])
    if coordinate_only:
        return normalized.astype(np.float32)
    radial = wendland(cdist(normalized, np.asarray(basis["knots"])) / np.asarray(basis["radii"]))
    return np.concatenate([normalized, radial], axis=1).astype(np.float32)


def target_transform(y_train: np.ndarray) -> dict:
    standard = float(np.std(y_train))
    return {"mean": float(np.mean(y_train)), "scale": standard if standard > 0 else 1.0,
            "constant": standard == 0}


def select_neighbors(query_xyz: np.ndarray, query_holes: np.ndarray, conditioning: dict,
                     k: int, per_hole: int = 4, min_holes: int = 2,
                     max_distance: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Stable Euclidean search; query hole and all of its derivatives excluded."""
    if k < min_holes or per_hole < 1:
        raise ValueError("inconsistent neighborhood policy")
    distance = cdist(query_xyz, conditioning["xyz"])
    selected = np.full((len(query_xyz), k), -1, dtype=np.int64)
    eligible = np.zeros(len(query_xyz), dtype=bool)
    ids = conditioning["ids"]
    for row, values in enumerate(distance):
        order = np.lexsort((ids, values))
        counts, used_supports, take = {}, set(), []
        for index in order:
            hole = conditioning["holes"][index]
            support = conditioning["supportIds"][index]
            if hole == query_holes[row] or support in used_supports:
                continue
            if max_distance is not None and values[index] > max_distance:
                continue
            if counts.get(hole, 0) >= per_hole:
                continue
            take.append(index)
            counts[hole] = counts.get(hole, 0) + 1
            used_supports.add(support)
            if len(take) == k:
                break
        if len(counts) >= min_holes:
            selected[row, :len(take)] = take
            eligible[row] = True
    return selected, eligible


def graph_features(query: dict, conditioning: dict, transform: dict, target: dict,
                   length_scale: float, k: int, kernel_length: float,
                   min_holes: int = 2, max_distance: float | None = None) -> dict:
    if kernel_length <= 0 or length_scale <= 0:
        raise ValueError("graph and support scales must be positive")
    index, eligible = select_neighbors(query["xyz"], query["holes"], conditioning, k,
                                       min_holes=min_holes, max_distance=max_distance)
    n = len(index)
    valid = np.column_stack([eligible, index >= 0])
    positions = np.zeros((n, k + 1, 3), dtype=np.float64)
    features = np.zeros((n, k + 1, 8), dtype=np.float32)
    positions[:, 0] = normalize(query["xyz"], transform)
    features[:, 0, 5] = query["length"] / length_scale
    features[:, 0, 6] = query["trajectory"]
    features[:, 0, 7] = 1
    safe = np.maximum(index, 0)
    positions[:, 1:] = normalize(conditioning["xyz"][safe], transform)
    features[:, 1:, 0] = (conditioning["y"][safe] - target["mean"]) / target["scale"]
    features[:, 1:, 1] = 1
    features[:, 1:, 2:5] = positions[:, 1:] - positions[:, :1]
    features[:, 1:, 5] = conditioning["length"][safe] / length_scale
    features[:, 1:, 6] = conditioning["trajectory"][safe]
    features *= valid[:, :, None]
    delta = positions[:, :, None] - positions[:, None, :]
    adjacency = np.exp(-np.sum(delta**2, axis=-1) / (2 * kernel_length**2))
    adjacency *= valid[:, :, None] * valid[:, None, :]
    # exp(0)=1 is exactly one self-loop, not an extra loop added to an existing diagonal.
    degree = adjacency.sum(axis=-1)
    inverse = np.zeros_like(degree)
    np.divide(1, np.sqrt(degree), out=inverse, where=degree > 0)
    adjacency *= inverse[:, :, None] * inverse[:, None, :]
    return {"features": features, "adjacency": adjacency.astype(np.float32),
            "valid": valid.astype(np.float32), "neighbors": index, "eligible": eligible}


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

