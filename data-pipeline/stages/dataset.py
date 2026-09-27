"""The dataset stage: frozen grouped splits per family, built before any target-dependent transform or fit.

Design: docs/design/features/classical-estimation/design.md, section 1. Every hole of an estimation family goes to
exactly one of train, validation, calibration and test in each scheme, and every member derived from a hole (sample,
repeat, composite, fragment) follows it, so nothing from a held-out hole can train. The split is stored as the hole
assignment; ``members`` derives any population's membership from it, and the output records per-split counts and
hashes of those memberships.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from source_io import stable_hash

SCHEMA = "drillhole.dataset/v1"
SPLITS = ("train", "validation", "calibration", "test")
PROPORTIONS = (0.60, 0.15, 0.10, 0.15)
SEED = 20260926
MARGIN = 0.15
#: The buffer is this many median nearest-neighbour collar distances: on a regular grid it removes the first ring of
#: neighbours around every held-out hole, diagonals included (1.5 > sqrt(2)), and not the second.
BUFFER_FACTOR = 1.5
MIN_HOLES = len(SPLITS)


def largest_remainder(n: int, proportions) -> list[int]:
    """Counts that sum to n, each the floor of its share, the remainder to the largest fractional parts (then order)."""
    shares = [n * p / sum(proportions) for p in proportions]
    counts = [int(np.floor(s)) for s in shares]
    order = sorted(range(len(shares)), key=lambda i: (-(shares[i] - counts[i]), i))
    for i in order[: n - sum(counts)]:
        counts[i] += 1
    return counts


def seeded_order(holes, seed: int) -> list[str]:
    ordered = sorted(holes)
    permutation = np.random.Generator(np.random.PCG64(seed)).permutation(len(ordered))
    return [ordered[i] for i in permutation]


def _cut(order, proportions, names) -> dict[str, str]:
    counts = largest_remainder(len(order), proportions)
    out, start = {}, 0
    for name, n in zip(names, counts, strict=True):
        for hole in order[start:start + n]:
            out[hole] = name
        start += n
    return out


def collar_xy(project) -> dict[str, np.ndarray]:
    return {c["id"]: np.array([c["x"], c["y"]], dtype=float) for c in project["collars"]}


def collar_spacing(xy: dict[str, np.ndarray]) -> float:
    """The median distance from each collar to its nearest other collar, in the horizontal plane."""
    names = sorted(xy)
    points = np.array([xy[h] for h in names])
    distances = np.sqrt(((points[:, None, :] - points[None, :, :]) ** 2).sum(-1))
    np.fill_diagonal(distances, np.inf)
    return float(np.median(distances.min(axis=1)))


def hole_group(holes, seed: int) -> dict:
    assignment = _cut(seeded_order(holes, seed), PROPORTIONS, SPLITS)
    return {"id": "hole-group", "kind": "hole-group", "seed": seed, "proportions": list(PROPORTIONS),
            "assignment": assignment}


def spatial_margin(holes, xy, seed: int) -> dict:
    holes = sorted(holes)
    centroid = np.mean([xy[h] for h in holes], axis=0)
    distance = {h: float(np.linalg.norm(xy[h] - centroid)) for h in holes}
    n_test = max(1, largest_remainder(len(holes), (MARGIN, 1 - MARGIN))[0])
    test = sorted(sorted(holes, key=lambda h: (-distance[h], h))[:n_test])
    buffer = BUFFER_FACTOR * collar_spacing({h: xy[h] for h in holes})
    buffered = sorted(h for h in holes if h not in test
                      and min(float(np.linalg.norm(xy[h] - xy[t])) for t in test) <= buffer)
    rest = [h for h in holes if h not in test and h not in buffered]
    assignment = _cut(seeded_order(rest, seed), PROPORTIONS[:3], SPLITS[:3])
    assignment.update({h: "test" for h in test})
    return {"id": "spatial-margin", "kind": "spatial-margin", "seed": seed, "proportions": list(PROPORTIONS[:3]),
            "margin": MARGIN, "buffer": buffer, "excludedByBuffer": buffered, "assignment": assignment,
            "rule": "test = the outermost 15 % of holes by collar distance from the centroid; holes within 1.5 median "
                    "nearest-neighbour collar distances of a test hole are excluded from every other split"}


def declared(holes, holdout, seed: int) -> dict:
    unknown = sorted(set(holdout) - set(holes))
    if unknown:
        raise ValueError(f"declared holdout names holes that are not in the family: {unknown}")
    rest = [h for h in sorted(holes) if h not in set(holdout)]
    assignment = _cut(seeded_order(rest, seed), PROPORTIONS[:3], SPLITS[:3])
    assignment.update({h: "test" for h in holdout})
    return {"id": "declared", "kind": "declared", "seed": seed, "proportions": list(PROPORTIONS[:3]),
            "holdout": sorted(holdout), "assignment": assignment}


def derived_tables(project: dict, pre: dict) -> dict[str, list[tuple[str, str]]]:
    """Every table of rows derived from holes, as (row id, hole) pairs."""
    tables = {"supports": [(s["id"], s["holeId"]) for s in project["supports"]]}
    if "composites" in pre:
        tables["composites"] = [(r["id"], r["holeId"]) for r in pre["composites"]["rows"]]
    if "fragments" in pre:
        tables["fragments"] = [(f"{f['holeId']}@{f['fromMd']}-{f['toMd']}", f["holeId"]) for f in pre["fragments"]["rows"]]
    if "repeats" in pre:
        tables["repeats"] = [(f"{r['holeId']}@{r['fromMd']}-{r['toMd']}", r["holeId"]) for r in pre["repeats"]]
    holes_of = {s["id"]: s["holeId"] for s in project["supports"]}
    holes_of.update({row: hole for row, hole in tables.get("composites", [])})
    for population in pre["populations"]:
        tables[f"population:{population['id']}"] = [(m, holes_of[m]) for m in population["members"]]
    return tables


def members(table: list[tuple[str, str]], assignment: dict[str, str]) -> dict[str, list[str]]:
    """The rows of a table in each split; a row of an unassigned hole (a buffer exclusion) is in no split."""
    out = defaultdict(list)
    for row, hole in table:
        split = assignment.get(hole)
        if split is not None:
            out[split].append(row)
    return {split: sorted(out.get(split, [])) for split in SPLITS}


def split_family(family: str, project: dict, pre: dict, project_sha: str, pre_sha: str, *, seed: int = SEED,
                 holdout=None) -> dict:
    holes = sorted({s["holeId"] for s in project["supports"]})
    base = {"schema": SCHEMA, "family": family, "inputProjectSha256": project_sha, "inputPreprocessedSha256": pre_sha,
            "splits": list(SPLITS)}
    if len(holes) < MIN_HOLES:
        return {**base, "eligible": False, "schemes": [],
                "reason": f"{len(holes)} hole(s) with samples; a grouped split needs at least {MIN_HOLES}, one per split"}
    xy = collar_xy(project)
    schemes = [hole_group(holes, seed), spatial_margin(holes, xy, seed)]
    if holdout:
        schemes.append(declared(holes, holdout, seed))
    tables = derived_tables(project, pre)
    for scheme in schemes:
        scheme["holeCounts"] = {s: sum(v == s for v in scheme["assignment"].values()) for s in SPLITS}
        summary = {}
        for name, table in tables.items():
            split = members(table, scheme["assignment"])
            summary[name] = {"counts": {s: len(v) for s, v in split.items()}, "sha256": stable_hash(split)}
        scheme["membership"] = summary
    return {**base, "eligible": True, "holes": holes, "collarSpacing": collar_spacing({h: xy[h] for h in holes}),
            "schemes": schemes}
