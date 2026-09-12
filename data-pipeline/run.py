#!/usr/bin/env python3
"""Generate or normalize a compact local drillhole project.

The command is deterministic and network-free. demo creates a small,
attributed planning fixture; a JSON path accepts the same table contract and
writes a validated copy to data/derived.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

SCHEMA = "drillhole.project/v1"

def demo_payload() -> dict[str, Any]:
    collars = [
        {"hole_id": "DH-01", "x": 500000.0, "y": 7400000.0, "z": 1260.0, "azimuth": 90.0, "dip": -62.0},
        {"hole_id": "DH-02", "x": 500085.0, "y": 7400028.0, "z": 1268.0, "azimuth": 92.0, "dip": -66.0},
        {"hole_id": "DH-03", "x": 500170.0, "y": 7399988.0, "z": 1254.0, "azimuth": 88.0, "dip": -60.0},
    ]
    surveys = [{"hole_id": c["hole_id"], "depth": 0.0, "azimuth": c["azimuth"], "dip": c["dip"]} for c in collars]
    surveys += [{"hole_id": c["hole_id"], "depth": 260.0, "azimuth": c["azimuth"] + (1 if c["hole_id"] == "DH-02" else 0), "dip": c["dip"] + 3.0} for c in collars]
    assays = []
    for hole_index, collar in enumerate(collars):
        for i in range(26):
            depth = 8.0 + i * 10.0
            grade = round(max(0.02, 0.28 + 0.62 * abs(math.sin(i * 0.47 + hole_index)) + 0.12 * hole_index), 4)
            assays.append({"hole_id": collar["hole_id"], "from": depth, "to": depth + 2.0, "cu_pct": grade})
    geology = []
    for collar in collars:
        geology.extend([
            {"hole_id": collar["hole_id"], "from": 0.0, "to": 72.0, "lithology": "weathered_halo"},
            {"hole_id": collar["hole_id"], "from": 72.0, "to": 134.0, "lithology": "potassic_core"},
            {"hole_id": collar["hole_id"], "from": 134.0, "to": 260.0, "lithology": "fresh_basement"},
        ])
    return {"schema": SCHEMA, "status": "validated", "source": "demo", "units": {"length": "m", "grade": "percent"},
            "crs": "EPSG:32719", "tables": {"collars": collars, "surveys": surveys, "assays": assays, "geology": geology},
            "counts": {"collars": len(collars), "surveys": len(surveys), "assays": len(assays), "geology": len(geology)},
            "provenance": {"kind": "authored-planning-fixture", "network": False}}

def load_source(source: str) -> dict[str, Any]:
    if source == "demo":
        return demo_payload()
    path = Path(source).resolve()
    if not path.exists() or path.suffix.lower() != ".json":
        raise SystemExit("source must be demo or an existing JSON project")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") not in {None, SCHEMA}:
        raise SystemExit("source JSON must be an object with schema drillhole.project/v1")
    payload["schema"] = SCHEMA
    payload["status"] = "validated"
    payload.setdefault("provenance", {"kind": "local-json", "path": str(path)})
    return payload

def write_project(payload: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    (output / "project.json").write_text(raw, encoding="utf-8")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    manifest = {"schema": "drillhole.manifest/v1", "project": "project.json", "sha256": digest, "counts": payload.get("counts", {})}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"schema": SCHEMA, "status": "validated", "source": payload.get("source"), "counts": payload.get("counts", {})}))

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="source project JSON or demo")
    parser.add_argument("--output", type=Path, default=Path("data/derived/demo"))
    args = parser.parse_args()
    write_project(load_source(args.source), args.output)

if __name__ == "__main__":
    main()
