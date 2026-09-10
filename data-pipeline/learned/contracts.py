"""Strict, source-bound contracts for Sondara's standalone learned recipes.

This is product orchestration, not an installed Python distribution. Values in
the input have already passed the canonical importer; this boundary validates
that learned fitting cannot silently reinterpret their frame, units or support.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

SPLITS = ("train", "validation", "calibration", "test")
TASKS = ("interval-centre-approximation", "sampling-envelope-centre-approximation")
SEEDS = (20260910, 20260911, 20260912)
AE_PROPERTIES = ("Fe", "P", "SiO2", "Al2O3", "CaO", "K2O", "MgO", "TiO2", "LOI")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def validate_input(data: dict) -> dict:
    if data.get("schema") != "sondara.learned-input.v1":
        raise ValueError("unsupported learned input schema")
    for key in ("projectId", "projectRevision", "frameId", "family", "splitHash"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValueError(f"missing scientific identity: {key}")
    if data.get("task") not in TASKS:
        raise ValueError("learned models require a declared centre-approximation task")
    units = data.get("propertyUnits", {})
    if not units or any(not isinstance(k, str) or not isinstance(v, str) or not v for k, v in units.items()):
        raise ValueError("property units must be explicitly declared")
    rows = data.get("rows", [])
    if not rows:
        raise ValueError("no eligible rows")
    ids, groups, split_counts = set(), {}, dict.fromkeys(SPLITS, 0)
    for row in rows:
        for key in ("id", "holeId", "supportId", "supportKind", "trajectory"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError(f"row requires string {key}")
        if row["id"] in ids:
            raise ValueError("duplicate row identity")
        ids.add(row["id"])
        split = row.get("split")
        if split not in SPLITS:
            raise ValueError("unknown split")
        split_counts[split] += 1
        if groups.setdefault(row["holeId"], split) != split:
            raise ValueError("whole-hole split leakage")
        xyz = np.asarray(row.get("xyz"), dtype=np.float64)
        if xyz.shape != (3,) or not np.isfinite(xyz).all():
            raise ValueError("xyz must be three finite metric coordinates")
        length = row.get("length")
        if not isinstance(length, (int, float)) or not np.isfinite(length) or length <= 0:
            raise ValueError("non-positive support/envelope length")
        if row["supportKind"] == "sampling-envelope" and data["task"] != TASKS[1]:
            raise ValueError("unknown sampling weights cannot become uniform interval support")
        for key, value in row.get("values", {}).items():
            if key not in units or (value is not None and not np.isfinite(float(value))):
                raise ValueError("non-finite or undeclared property")
    if any(count == 0 for count in split_counts.values()):
        raise ValueError("all four sealed splits require observations")
    if len({r["holeId"] for r in rows if r["split"] == "train"}) < 3:
        raise ValueError("at least three training holes are required")
    return data


def read_input(path: Path) -> dict:
    return validate_input(json.loads(path.read_text(encoding="utf-8")))


def split_manifest(canonical: dict, seed: int = SEEDS[0], spatial_margin: bool = False) -> dict:
    """Freeze labels by whole hole before extracting any target-dependent feature."""
    rows = [r for r in canonical["rows"] if r.get("eligible", True)]
    holes = sorted({r["holeId"] for r in rows})
    if len(holes) < 7:
        raise ValueError("four grouped splits require at least seven eligible holes")
    rank = lambda hole: hashlib.sha256(f"{seed}:{hole}".encode()).hexdigest()
    holes.sort(key=rank)
    n = len(holes)
    nv, nc, nt = max(1, round(.15 * n)), max(1, round(.10 * n)), max(1, round(.15 * n))
    if spatial_margin:
        # A declared geometry-only challenge: largest mean easting holes are sealed.
        eastings = {h: np.mean([r["x"] for r in rows if r["holeId"] == h]) for h in holes}
        test = sorted(holes, key=lambda h: (eastings[h], rank(h)))[-nt:]
        rest = [h for h in holes if h not in test]
        ordered = rest + test
    else:
        ordered = holes
    labels = ["train"] * (n - nv - nc - nt) + ["validation"] * nv + ["calibration"] * nc + ["test"] * nt
    assignment = dict(zip(ordered, labels, strict=True))
    result = {"schema": "sondara.grouped-split.v1", "seed": seed,
              "recipe": "easting-margin-holdout" if spatial_margin else "sha256-whole-hole-60-15-10-15",
              "projectId": canonical["projectId"], "sourceTableHash": canonical_hash(canonical),
              "secondaryAvailability": "all properties removed from held-out holes",
              "assignment": assignment,
              "rows": {split: [r["id"] for r in rows if assignment[r["holeId"]] == split] for split in SPLITS},
              "holeCounts": {split: labels.count(split) for split in SPLITS}}
    return result | {"hash": canonical_hash(result)}


def from_canonical(canonical: dict, split: dict, family: str) -> dict:
    if canonical.get("schema") != "drillhole.modeling-samples/v1":
        raise ValueError("unsupported canonical modeling table")
    if split["sourceTableHash"] != canonical_hash(canonical):
        raise ValueError("split was sealed against a different table")
    data = {"schema": "sondara.learned-input.v1", "family": family,
            "projectId": canonical["projectId"], "projectRevision": canonical_hash(canonical),
            "frameId": canonical["frameId"], "task": canonical["task"], "splitHash": split["hash"],
            "sourceHashes": canonical.get("sourceHashes", []),
            "propertyUnits": {p["id"]: p["unit"] for p in canonical["analytes"]},
            "rows": [{"id": r["id"], "holeId": r["holeId"], "supportId": r["supportId"],
                      "xyz": [r["x"], r["y"], r["z"]], "length": r["supportLength"],
                      "supportKind": r["supportKind"], "samplingMeasure": r["samplingMeasure"],
                      "trajectory": r["trajectoryKind"], "values": r["values"],
                      "split": split["assignment"][r["holeId"]],
                      "fromMd": r["fromMd"], "toMd": r["toMd"],
                      "determinationIds": r["determinationIds"]}
                     for r in canonical["rows"] if r.get("eligible", True)]}
    return validate_input(data)


def arrays(data: dict, target: str) -> dict:
    if target not in data["propertyUnits"]:
        raise ValueError("target is absent from the unit schema")
    rows = [r for r in data["rows"] if r["values"].get(target) is not None]
    if not rows:
        raise ValueError("no target observations")
    return {
        "rows": rows,
        "ids": np.asarray([r["id"] for r in rows]),
        "holes": np.asarray([r["holeId"] for r in rows]),
        "xyz": np.asarray([r["xyz"] for r in rows], dtype=np.float64),
        "length": np.asarray([r["length"] for r in rows], dtype=np.float64),
        "trajectory": np.asarray([r["trajectory"] == "measured-stations" for r in rows], dtype=np.float32),
        "y": np.asarray([r["values"][target] for r in rows], dtype=np.float64),
        "split": np.asarray([r["split"] for r in rows]),
    }


def binding(data: dict, properties: list[str]) -> dict:
    return {key: data[key] for key in ("projectId", "projectRevision", "frameId", "family", "task", "splitHash")} | {
        "propertyUnits": {key: data["propertyUnits"][key] for key in properties},
        "sourceHashes": data.get("sourceHashes", []),
        "inputHash": canonical_hash(data),
    }


def check_binding(model: dict, project: dict) -> None:
    """A compatible architecture is never permission to reuse a foreign fit."""
    bound = model["binding"]
    for key in ("projectId", "frameId", "task"):
        if project.get(key) != bound[key]:
            raise ValueError(f"out-of-domain: incompatible {key}")
    for key, unit in bound["propertyUnits"].items():
        if project.get("propertyUnits", {}).get(key) != unit:
            raise ValueError(f"out-of-domain: incompatible property/unit {key}")
