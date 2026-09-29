"""Seeds, hashing and the binding that ties a fitted model to the project it was fitted on.

The learned lane takes its rows, splits and targets from the pipeline stages (``stages/learned.py``); the 0.2
split code and its ``modeling-samples`` schema, which no stage wrote, are gone (audit L-2 of the 2026-09-28 research).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SEEDS = (20260910, 20260911, 20260912)
AE_PROPERTIES = ("Fe", "P", "SiO2", "Al2O3", "CaO", "K2O", "MgO", "TiO2", "LOI")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def binding(project: dict, population: dict, analyte: str, unit: str, dataset_sha: str, train_ids: list[str]) -> dict:
    """What a fitted model is bound to: a compatible architecture is never permission to reuse a fit elsewhere."""
    return {"projectId": project["id"], "frameId": project["frames"][0]["id"], "task": population["task"],
            "population": population["id"], "support": population.get("support"),
            "propertyUnits": {analyte: unit}, "datasetSha256": dataset_sha,
            "trainingRowsSha256": canonical_hash(sorted(train_ids))}


def check_binding(model: dict, project: dict) -> None:
    """Refuse a model for another project, frame, task or property unit (``project`` holds the same keys)."""
    bound = model["binding"]
    for key in ("projectId", "frameId", "task"):
        if project.get(key) != bound[key]:
            raise ValueError(f"out-of-domain: incompatible {key}")
    for key, unit in bound["propertyUnits"].items():
        if project.get("propertyUnits", {}).get(key) != unit:
            raise ValueError(f"out-of-domain: incompatible property or unit {key}")
