"""The features stage: training-only statistics, declustering and experimental variograms per split and population.

Design: docs/design/features/classical-estimation/design.md, section 2. The stage is handed the training members of a
split and nothing else: validation and test values never enter a statistic, a declustering weight or a variogram. The
variograms are GeoCond's (``geocond.experimental_variogram`` and ``experimental_cross_variogram``); this module decides
which rows, lags and directions go in, and records them.
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
from geocond import experimental_cross_variogram, experimental_variogram
from stages.dataset import collar_spacing, collar_xy

SCHEMA = "drillhole.features/v1"
MAX_PAIRS = 2_000_000
SEED = 20260926
DOWNHOLE_LAGS = 20
SPATIAL_LAGS = 12
DIRECTIONS = {"azimuth-000": 0.0, "azimuth-045": 45.0, "azimuth-090": 90.0, "azimuth-135": 135.0}
ANGLE_TOLERANCE = 22.5
ORIENTATION_RATIO = 1.2
DECLUSTER_OFFSETS = 4
#: The analytes each field family's scenarios model, and the declared multivariate sets for cross variograms.
FAMILY_ANALYTES = {"rocklea": ["Fe", "SiO2", "Al2O3"], "alberta": ["Cu_ppm", "Zn_ppm"]}
CROSS_SETS = {"rocklea": [("Fe", "SiO2"), ("Fe", "Al2O3"), ("SiO2", "Al2O3")], "alberta": [("Cu_ppm", "Zn_ppm")]}


def population_rows(pre: dict, member_ids) -> list[dict]:
    """One row per member: id, hole, centre, centre depth, support length and its selected values by analyte.

    A composite member carries its composite means; a sample member carries the values selected for its geometry.
    """
    composites = {r["id"]: r for r in pre.get("composites", {}).get("rows", [])}
    positions = {p["supportId"]: p for p in pre["positions"]}
    values = defaultdict(dict)
    for r in pre["selections"]["rows"]:
        values[tuple(r["geometry"])][r["analyteId"]] = r["value"]
    out = []
    for m in member_ids:
        if m in composites:
            r = composites[m]
            out.append({"id": m, "hole": r["holeId"], "xyz": r["mid"], "md": (r["fromMd"] + r["toMd"]) / 2,
                        "length": r["toMd"] - r["fromMd"],
                        "values": {k: v for k, v in r["values"].items() if v is not None}})
            continue
        p = positions[m]
        if "mid" in p:
            geometry = (p["holeId"], p["fromMd"], p["toMd"])
            xyz, md, length = p["mid"], (p["fromMd"] + p["toMd"]) / 2, p["toMd"] - p["fromMd"]
        else:
            geometry = (p["holeId"], p["atMd"], p["atMd"])
            xyz, md, length = p["at"], p["atMd"], 0.0
        out.append({"id": m, "hole": p["holeId"], "xyz": xyz, "md": md, "length": length,
                    "values": dict(values[geometry])})
    return out


def declustered_mean(xyz: np.ndarray, z: np.ndarray, cell: tuple[float, float, float],
                     offsets: int = DECLUSTER_OFFSETS) -> tuple[float, np.ndarray]:
    """Cell declustering: weight 1 / (samples in the cell), averaged over ``offsets`` diagonal origin shifts."""
    size = np.asarray(cell, dtype=float)
    size = np.where(size > 0, size, 1.0)
    weights = np.zeros(len(z))
    origin = xyz.min(axis=0)
    for k in range(offsets):
        shifted = np.floor((xyz - origin + size * k / offsets) / size).astype(np.int64)
        _, inverse, counts = np.unique(shifted, axis=0, return_inverse=True, return_counts=True)
        w = 1.0 / counts[inverse.ravel()]
        weights += w / w.sum()
    weights /= offsets
    return float(weights @ z / weights.sum()), weights


def _variogram_record(v, name) -> dict:
    return {"name": name, "estimator": v.estimator, "downhole": bool(v.downhole),
            "direction": None if v.direction is None else [float(x) for x in v.direction],
            "angleTolerance": v.angle_tolerance, "bandwidth": v.bandwidth,
            "edges": [float(x) for x in v.edges],
            "separation": [None if math.isnan(x) else float(x) for x in v.separation],
            "counts": [int(x) for x in v.counts],
            "values": [None if math.isnan(x) else float(x) for x in v.values],
            "populationPairs": int(v.population_pairs), "sampled": bool(v.sampled), "seed": v.seed}


def variograms(rows, analyte, spacing, length, *, seed=SEED):
    """Downhole, omnidirectional, four horizontal and one vertical direct variogram of one analyte."""
    use = [r for r in rows if analyte in r["values"]]
    if len(use) < 2:
        return []
    xyz = np.array([r["xyz"] for r in use], dtype=float)
    z = np.array([r["values"][analyte] for r in use], dtype=float)
    holes = sorted({r["hole"] for r in use})
    groups = np.array([holes.index(r["hole"]) for r in use])
    depths = np.array([r["md"] for r in use], dtype=float)
    out = []
    lag = max(length, 1e-6)
    edges = lag * (np.arange(DOWNHOLE_LAGS + 1) + 0.5)
    out.append(_variogram_record(experimental_variogram(xyz, z, edges, groups=groups, downhole=True, depths=depths,
                                                        max_pairs=MAX_PAIRS, seed=seed), "downhole"))
    spatial = max(spacing / 2, lag)
    edges = spatial * (np.arange(SPATIAL_LAGS + 1) + 0.5)
    out.append(_variogram_record(experimental_variogram(xyz, z, edges, max_pairs=MAX_PAIRS, seed=seed), "omni"))
    for name, azimuth in DIRECTIONS.items():
        a = math.radians(azimuth)
        out.append(_variogram_record(experimental_variogram(
            xyz, z, edges, direction=[math.sin(a), math.cos(a), 0.0], angle_tolerance=ANGLE_TOLERANCE,
            bandwidth=2 * spacing, max_pairs=MAX_PAIRS, seed=seed), name))
    out.append(_variogram_record(experimental_variogram(
        xyz, z, lag * (np.arange(DOWNHOLE_LAGS + 1) + 0.5), direction=[0.0, 0.0, 1.0],
        angle_tolerance=ANGLE_TOLERANCE, bandwidth=2 * spacing, max_pairs=MAX_PAIRS, seed=seed), "vertical"))
    return out


def cross_variograms(rows, pair, spacing, length, *, seed=SEED):
    """Omnidirectional and downhole cross variograms on co-located values only (common support)."""
    first, second = pair
    use = [r for r in rows if first in r["values"] and second in r["values"]]
    if len(use) < 2:
        return []
    xyz = np.array([r["xyz"] for r in use], dtype=float)
    a = np.array([r["values"][first] for r in use], dtype=float)
    b = np.array([r["values"][second] for r in use], dtype=float)
    holes = sorted({r["hole"] for r in use})
    groups = np.array([holes.index(r["hole"]) for r in use])
    depths = np.array([r["md"] for r in use], dtype=float)
    lag = max(length, 1e-6)
    return [
        _variogram_record(experimental_cross_variogram(xyz, a, b, lag * (np.arange(DOWNHOLE_LAGS + 1) + 0.5),
                                                       groups=groups, downhole=True, depths=depths,
                                                       max_pairs=MAX_PAIRS, seed=seed), "downhole"),
        _variogram_record(experimental_cross_variogram(xyz, a, b, max(spacing / 2, lag)
                                                       * (np.arange(SPATIAL_LAGS + 1) + 0.5),
                                                       max_pairs=MAX_PAIRS, seed=seed), "omni"),
    ]


def statistics(rows, analyte, spacing, length) -> dict:
    use = [r for r in rows if analyte in r["values"]]
    if not use:
        return {"count": 0}
    xyz = np.array([r["xyz"] for r in use], dtype=float)
    z = np.array([r["values"][analyte] for r in use], dtype=float)
    cell = (spacing, spacing, max(length, 1.0))
    mean, _ = declustered_mean(xyz, z, cell)
    return {"count": len(use), "holes": len({r["hole"] for r in use}), "mean": float(z.mean()),
            "variance": float(z.var(ddof=0)), "min": float(z.min()), "max": float(z.max()),
            "declustered": {"mean": mean, "cell": list(cell), "offsets": DECLUSTER_OFFSETS}}


def orientation_from_normals(measurements, ratio: float = ORIENTATION_RATIO) -> dict:
    """The principal plane of declared orientations, or ``undefined`` when the measurements do not agree.

    Each measurement is a plane (dip, dip direction in degrees); its upward unit normal enters the orientation tensor
    T = mean(n n^T). The largest eigenvector is the mean normal; when the two largest eigenvalues are within ``ratio``
    of each other the normals spread over a girdle and no single plane is supported.
    """
    normals = []
    for m in measurements:
        dip, direction = math.radians(m["dip"]), math.radians(m["dipDirection"])
        normals.append([math.sin(dip) * math.sin(direction), math.sin(dip) * math.cos(direction), math.cos(dip)])
    n = np.array(normals)
    tensor = n.T @ n / len(n)
    values, vectors = np.linalg.eigh(tensor)
    order = np.argsort(values)[::-1]
    values, vectors = values[order], vectors[:, order]
    record = {"eigenvalues": [float(v) for v in values], "ratio": ratio, "count": len(n)}
    if values[1] <= 0 or values[0] / values[1] >= ratio:
        normal = vectors[:, 0] * (1 if vectors[2, 0] >= 0 else -1)
        dip = math.degrees(math.acos(max(-1.0, min(1.0, normal[2]))))
        direction = math.degrees(math.atan2(normal[0], normal[1])) % 360.0
        return {**record, "status": "defined", "principal": {"dip": dip, "dipDirection": direction}}
    return {**record, "status": "undefined", "principal": None,
            "reason": f"the two largest eigenvalues are within a ratio of {ratio}: the normals do not share a plane"}


def family_features(family, project, pre, dataset, *, analytes=None, cross=None, orientations=None, seed=SEED):
    from stages.dataset import members

    analytes = analytes if analytes is not None else FAMILY_ANALYTES.get(
        family, sorted({r["analyteId"] for r in pre["selections"]["rows"]}))
    cross = cross if cross is not None else CROSS_SETS.get(family, [])
    xy = collar_xy(project)
    out = {"schema": SCHEMA, "family": family, "inputDatasetSha256": dataset.get("sha256"),
           "maxPairs": MAX_PAIRS, "seed": seed, "schemes": []}
    if orientations:
        out["orientation"] = orientation_from_normals(orientations)
    if not dataset["eligible"]:
        return {**out, "eligible": False, "reason": dataset["reason"]}
    estimation = [p for p in pre["populations"] if p["count"] > 0 and "QA" not in p["task"]]
    holes_of = {s["id"]: s["holeId"] for s in project["supports"]}
    holes_of.update({r["id"]: r["holeId"] for r in pre.get("composites", {}).get("rows", [])})
    for scheme in dataset["schemes"]:
        train_holes = sorted(h for h, s in scheme["assignment"].items() if s == "train")
        spacing = collar_spacing({h: xy[h] for h in train_holes}) if len(train_holes) > 1 else 0.0
        entry = {"scheme": scheme["id"], "trainHoles": len(train_holes), "collarSpacing": spacing, "populations": []}
        for population in estimation:
            split = members([(m, holes_of[m]) for m in population["members"]], scheme["assignment"])
            train = set(split["train"])
            rows = population_rows(pre, sorted(train))
            length = float(np.median([r["length"] for r in rows])) if rows else 0.0
            record = {"population": population["id"], "trainMembers": len(rows), "supportLength": length,
                      "analytes": {}}
            for analyte in analytes:
                record["analytes"][analyte] = {"statistics": statistics(rows, analyte, spacing, length),
                                               "variograms": variograms(rows, analyte, spacing, length, seed=seed)}
            record["cross"] = {f"{a}|{b}": cross_variograms(rows, (a, b), spacing, length, seed=seed)
                               for a, b in cross if a in analytes and b in analytes}
            entry["populations"].append(record)
        out["schemes"].append(entry)
    return {**out, "eligible": True}
