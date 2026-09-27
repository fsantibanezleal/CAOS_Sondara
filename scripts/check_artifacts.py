#!/usr/bin/env python3
"""Validate every ingested canonical project against the drillhole.project/v2 contract.

    python scripts/check_artifacts.py [--derived build/derived]

For each ``<family>/project.json`` with its ``summary.json`` the check verifies: the JSON Schema in
``schemas/project.schema.json``; the summary hash and counts against the project; unique identifiers per table; every
survey, trajectory, support and geology record on a known collar; every determination on a known support and analyte;
support geometry consistent with its kind; determination states (a measured value with '=', censoring as a qualifier
with a positive limit and no value, other states with neither); controls without supports; geology intervals and
events; and exclusions that name existing records. When a family has been preprocessed, it also checks that output against its project: the input hash, one
trajectory per collar, a finite position for every positioned support and none for an unknown one, composite
statuses, means only where covered, per-hole conservation of every grade-length integral, population members, and
overlay coverage and proportions. It exits nonzero and lists every violation, so a changed stage cannot write an
output the later stages would misread.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data-pipeline"))

from source_io import stable_hash

SCHEMA = "drillhole.project/v2"
SCHEMA_FILE = ROOT / "schemas" / "project.schema.json"
TABLES = ("collars", "surveys", "trajectories", "analytes", "supports", "determinations", "geology", "qc",
          "exclusions", "issues")
CENSORED = {"censored-below": "<", "censored-above": ">"}


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _schema_errors(project: dict, limit: int = 50) -> list[str]:
    import jsonschema

    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))
    errors = []
    for error in validator.iter_errors(project):
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"schema: {where}: {error.message[:160]}")
        if len(errors) >= limit:
            errors.append("schema: stopped after the first violations")
            break
    return errors


def _determination_errors(d: dict, label: str) -> list[str]:
    state, value, qualifier = d.get("state"), d.get("value"), d.get("qualifier")
    if state == "measured":
        if not _finite(value) or qualifier != "=":
            return [f"{label}: a measured result has a finite value and qualifier '='"]
    elif state in CENSORED:
        if value is not None or qualifier != CENSORED[state] or not (_finite(d.get("detectionLimit"))
                                                                     and d["detectionLimit"] > 0):
            return [f"{label}: a censored result keeps no value, its qualifier and a positive limit"]
    elif value is not None or qualifier is not None:
        return [f"{label}: a {state} result carries no value and no qualifier"]
    return []


def check_project(project: dict) -> list[str]:
    """Return every violation of one canonical project: the schema first, then the referential rules."""
    errors = _schema_errors(project)
    if errors:
        return errors
    frames = {f["id"] for f in project["frames"]}

    def unique(table: str) -> set:
        ids = [row["id"] for row in project[table]]
        if len(set(ids)) != len(ids):
            errors.append(f"{table}: duplicate ids")
        return set(ids)

    collars = unique("collars")
    analytes = unique("analytes")
    supports = unique("supports")
    determinations = unique("determinations")
    surveys = unique("surveys")
    geology = unique("geology")
    unique("qc")
    if not collars:
        errors.append("no collars")
    for c in project["collars"]:
        if c["frameId"] not in frames:
            errors.append(f"collar {c['id']}: unknown frame {c['frameId']!r}")
        if c["totalDepth"] is not None and c["totalDepth"] <= 0:
            errors.append(f"collar {c['id']}: total depth must be positive or null")
    for table in ("surveys", "trajectories", "supports", "geology"):
        orphans = {r["holeId"] for r in project[table]} - collars
        if orphans:
            errors.append(f"{table}: records on unknown collars {sorted(orphans)[:5]}")
    if sorted(t["holeId"] for t in project["trajectories"]) != sorted(collars):
        errors.append("every collar needs exactly one trajectory")
    for s in project["supports"]:
        kind, a, b, at = s["kind"], s["fromMd"], s["toMd"], s["atMd"]
        if kind in ("interval", "sampling-envelope"):
            if not (_finite(a) and _finite(b) and 0 <= a < b and at is None):
                errors.append(f"support {s['id']}: {kind} needs 0 <= from < to")
            if kind == "sampling-envelope" and s["samplingMeasure"] != "unknown":
                errors.append(f"support {s['id']}: an envelope's sampling measure is unknown")
        elif kind == "point":
            if not (_finite(at) and at >= 0 and a is None and b is None):
                errors.append(f"support {s['id']}: a point needs atMd only")
        elif not (a is None and b is None and at is None):
            errors.append(f"support {s['id']}: unknown support must carry no depths")
    for d in project["determinations"]:
        if d["supportId"] not in supports:
            errors.append(f"determination {d['id']}: unknown support")
        if d["analyteId"] not in analytes:
            errors.append(f"determination {d['id']}: unknown analyte")
        errors += _determination_errors(d, f"determination {d['id']}")
        if len(errors) > 200:
            errors.append("stopped after 200 violations")
            return errors
    for q in project["qc"]:
        for d in q["determinations"]:
            if d["supportId"] is not None:
                errors.append(f"qc {q['id']}: a control has no support")
            errors += _determination_errors(d, f"qc {q['id']}")
    for g in project["geology"]:
        if g["kind"] == "interval" and not (_finite(g["fromMd"]) and _finite(g["toMd"]) and g["fromMd"] < g["toMd"]
                                            and g["atMd"] is None):
            errors.append(f"geology {g['id']}: an interval needs from < to")
        if g["kind"] == "event" and not (_finite(g["atMd"]) and g["fromMd"] is None and g["toMd"] is None):
            errors.append(f"geology {g['id']}: an event has one depth")
    known = {"supports": supports, "determinations": determinations, "surveys": surveys, "geology": geology,
             "collars": collars}
    for x in project["exclusions"]:
        if x["rowId"] not in known.get(x["table"], set()):
            errors.append(f"exclusion of {x['table']}/{x['rowId']}: no such record")
    return errors


STATUSES = {"full", "residual", "insufficient-coverage"}


def _finite_xyz(value) -> bool:
    return isinstance(value, list) and len(value) == 3 and all(_finite(v) for v in value)


def check_preprocessed(pre: dict, project: dict) -> list[str]:
    """Return every violation of a preprocess output against the project it was built from."""
    errors: list[str] = []
    if pre.get("schema") != "drillhole.preprocessed/v1":
        errors.append(f"preprocessed schema is {pre.get('schema')!r}")
    if pre.get("inputProjectSha256") != stable_hash(project):
        errors.append("preprocessed output was built from another project (input hash differs)")
    collars = {c["id"] for c in project["collars"]}
    if {t.get("holeId") for t in pre.get("trajectories", [])} != collars:
        errors.append("every collar needs exactly one desurveyed trajectory")
    for t in pre.get("trajectories", []):
        if not t.get("stations") or not all(_finite_xyz(s.get("position")) for s in t["stations"]):
            errors.append(f"trajectory {t.get('holeId')}: stations without finite positions")
        if not _finite_xyz(t.get("endPosition")):
            errors.append(f"trajectory {t.get('holeId')}: no finite end position")
    supports = {s["id"]: s for s in project["supports"]}
    positioned = {p["supportId"]: p for p in pre.get("positions", [])}
    for sid, s in supports.items():
        p = positioned.get(sid)
        if s["kind"] == "unknown":
            if p and any(k in p for k in ("from", "mid", "to", "at")):
                errors.append(f"support {sid}: an unknown support was given a position")
        elif p is None:
            errors.append(f"support {sid}: no position")
        elif s["kind"] == "point":
            if not _finite_xyz(p.get("at")):
                errors.append(f"support {sid}: point without a finite position")
        elif not all(_finite_xyz(p.get(k)) for k in ("from", "mid", "to")):
            errors.append(f"support {sid}: interval without finite start, mid and end positions")
    determinations = {d["id"]: d for d in project["determinations"]}
    excluded = {x["rowId"] for x in project["exclusions"] if x["table"] == "determinations"}
    source: dict = {}
    for r in pre.get("selections", {}).get("rows", []):
        d = determinations.get(r["determinationId"])
        if d is None or d["state"] != "measured" or d["sampleRole"] != "original" or d["id"] in excluded:
            errors.append(f"selection of {r['determinationId']}: not a measured, original, non-excluded result")
            continue
        if r["representative"] not in supports:
            errors.append(f"selection of {r['determinationId']}: representative is not a project support")
        hole, a, b = r["geometry"]
        source[(hole, r["analyteId"])] = source.get((hole, r["analyteId"]), 0.0) + r["value"] * (b - a)
    composite_ids = set()
    if "composites" in pre:
        minimum = pre["composites"]["minCoverage"]
        numerators: dict = {}
        for row in pre["composites"]["rows"]:
            composite_ids.add(row["id"])
            if row["status"] not in STATUSES:
                errors.append(f"composite {row['id']}: status {row['status']!r}")
                continue
            length = row["toMd"] - row["fromMd"]
            if row["status"] == "full" and (abs(length - row["length"]) > 1e-9 or row["coverage"] < minimum - 1e-12):
                errors.append(f"composite {row['id']}: a full composite has the declared length and enough coverage")
            if row["status"] == "residual" and not (length < row["length"] and row["coverage"] >= minimum - 1e-12):
                errors.append(f"composite {row['id']}: a residual is shorter with enough coverage")
            for analyte, value in row["values"].items():
                share = row["coverageByAnalyte"][analyte]
                covered = share > 0 and share >= minimum - 1e-12  # GeoCond: some valid length and enough coverage
                if (value is not None and _finite(value)) != covered:
                    errors.append(f"composite {row['id']}: {analyte} carries a mean only where it is covered")
            if any(pid not in supports for pid, _ in row["parents"]):
                errors.append(f"composite {row['id']}: parent is not a project support")
            for analyte, value in row["numerators"].items():
                key = (row["holeId"], row["length"], analyte)
                numerators[key] = numerators.get(key, 0.0) + value
        for (hole, _length, analyte), total in numerators.items():
            expected = source.get((hole, analyte), 0.0)
            if abs(total - expected) > 1e-9 * max(1.0, abs(expected)):
                errors.append(f"composites of {hole} do not conserve the {analyte} grade-length integral")
    fragments = pre.get("fragments")
    if fragments is not None and fragments["parentLengthMaxError"] > 1e-9:
        errors.append("overlay fragments do not add up to their parent intervals")
    known = set(supports) | composite_ids
    for population in pre.get("populations", []):
        if population.get("count") != len(population.get("members", [])):
            errors.append(f"population {population.get('id')}: count differs from its members")
        if any(m not in known for m in population.get("members", [])):
            errors.append(f"population {population.get('id')}: a member is neither a support nor a composite")
        if not population.get("rule"):
            errors.append(f"population {population.get('id')}: no rule")
    for row in pre.get("overlay", {}).get("rows", []):
        for name in ("anyLog", "lithoUnit", "rockType"):
            cell = row[name]
            if not 0 <= cell["coverage"] <= 1 + 1e-12:
                errors.append(f"overlay {row['supportId']}: {name} coverage outside [0, 1]")
            if cell["proportions"] and abs(sum(cell["proportions"].values()) - 1) > 1e-9:
                errors.append(f"overlay {row['supportId']}: {name} proportions do not sum to one")
    return errors


def check_family(folder: Path) -> list[str]:
    project_path, summary_path = folder / "project.json", folder / "summary.json"
    if not summary_path.is_file():
        return [f"{folder.name}: summary.json missing"]
    project = json.loads(project_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    errors = check_project(project)
    if summary.get("projectSha256") != stable_hash(project):
        errors.append("summary hash does not match the project")
    counts = {t: len(project.get(t, [])) for t in TABLES}
    if summary.get("counts") != counts:
        errors.append("summary counts do not match the project")
    pre_path, pre_summary_path = folder / "preprocessed.json", folder / "preprocess-summary.json"
    if pre_path.is_file():
        pre = json.loads(pre_path.read_text(encoding="utf-8"))
        errors += check_preprocessed(pre, project)
        pre_summary = json.loads(pre_summary_path.read_text(encoding="utf-8")) if pre_summary_path.is_file() else {}
        if pre_summary.get("preprocessedSha256") != stable_hash(pre):
            errors.append("preprocess summary hash does not match the preprocessed output")
    return [f"{folder.name}: {e}" for e in errors]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--derived", type=Path, default=ROOT / "build" / "derived")
    args = parser.parse_args(argv)
    folders = sorted(p.parent for p in args.derived.glob("*/project.json"))
    if not folders:
        print(f"FAIL: no ingested project under {args.derived} (run data-pipeline/run.py ingest first)")
        return 1
    errors = [e for folder in folders for e in check_family(folder)]
    if errors:
        print("PROJECT CONTRACT VIOLATIONS:")
        for error in errors:
            print(f"  - {error}")
        return 1
    stages = {f.name: "ingest + preprocess" if (f / "preprocessed.json").is_file() else "ingest" for f in folders}
    print("PROJECT CONTRACT OK: " + ", ".join(f"{k} ({v})" for k, v in stages.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
