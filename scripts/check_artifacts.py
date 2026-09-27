#!/usr/bin/env python3
"""Validate every ingested canonical project against the drillhole.project/v1 contract.

    python scripts/check_artifacts.py [--derived build/derived]

For each ``<family>/project.json`` with its ``summary.json`` the check verifies: the schema; the summary hash and
counts against the project; unique identifiers per table; every survey, trajectory, support and geology record on a
known collar; every determination on a known support and analyte; support geometry consistent with its kind;
censoring kept as a qualifier with a positive limit and no value; finite values; and a QA issue table whose rows are
named. When a family has been preprocessed, it also checks that output against its project: the input hash, one
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

SCHEMA = "drillhole.project/v1"
TABLES = ("collars", "surveys", "trajectories", "analytes", "supports", "determinations", "geology", "issues")
SUPPORT_KINDS = {"interval", "sampling-envelope", "point", "unknown"}
TRAJECTORY_KINDS = {"assumed-vertical", "collar-orientation", "measured-stations"}
QUALIFIERS = {"=", "<", ">"}
SEVERITIES = {"info", "warning", "error"}


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_project(project: dict) -> list[str]:
    """Return every contract violation of one canonical project (empty when valid)."""
    errors: list[str] = []
    if project.get("schema") != SCHEMA:
        errors.append(f"schema is {project.get('schema')!r}, expected {SCHEMA}")
    for table in TABLES:
        if not isinstance(project.get(table), list):
            errors.append(f"table {table} is missing")
            return errors
    frames = {f["id"] for f in project.get("frames", [])}
    if not frames:
        errors.append("no coordinate frame")

    def unique(table: str) -> set:
        ids = [row.get("id") for row in project[table]]
        if any(i is None for i in ids) or len(set(ids)) != len(ids):
            errors.append(f"{table}: missing or duplicate ids")
        return set(ids)

    collars = unique("collars")
    analytes = unique("analytes")
    supports = unique("supports")
    unique("determinations")
    if project["geology"]:
        unique("geology")
    if not collars:
        errors.append("no collars")

    for c in project["collars"]:
        if c.get("frameId") not in frames:
            errors.append(f"collar {c['id']}: unknown frame {c.get('frameId')!r}")
        if not all(_finite(c.get(k)) for k in ("x", "y", "z")):
            errors.append(f"collar {c['id']}: non-finite coordinates")
        if c.get("totalDepth") is not None and not (_finite(c["totalDepth"]) and c["totalDepth"] > 0):
            errors.append(f"collar {c['id']}: total depth must be positive or null")

    for table in ("surveys", "trajectories", "supports", "geology"):
        orphans = {r.get("holeId") for r in project[table]} - collars
        if orphans:
            errors.append(f"{table}: records on unknown collars {sorted(map(str, orphans))[:5]}")

    for s in project["surveys"]:
        if not (_finite(s.get("md")) and s["md"] >= 0 and _finite(s.get("azimuth")) and _finite(s.get("dip"))):
            errors.append(f"survey on {s.get('holeId')} at {s.get('md')}: non-finite or negative")
        elif not (0 <= s["azimuth"] < 360 and -90 <= s["dip"] <= 90):
            errors.append(f"survey on {s.get('holeId')} at {s['md']}: azimuth or dip out of range")
        if not s.get("role"):
            errors.append(f"survey on {s.get('holeId')} at {s.get('md')}: no role")

    for t in project["trajectories"]:
        if t.get("kind") not in TRAJECTORY_KINDS:
            errors.append(f"trajectory of {t.get('holeId')}: kind {t.get('kind')!r}")
    if {t.get("holeId") for t in project["trajectories"]} != collars:
        errors.append("every collar needs exactly one trajectory")

    for s in project["supports"]:
        kind, a, b, at = s.get("kind"), s.get("fromMd"), s.get("toMd"), s.get("atMd")
        if kind not in SUPPORT_KINDS:
            errors.append(f"support {s['id']}: kind {kind!r}")
        elif kind in ("interval", "sampling-envelope"):
            if not (_finite(a) and _finite(b) and 0 <= a < b and at is None):
                errors.append(f"support {s['id']}: {kind} needs 0 <= from < to")
            if kind == "sampling-envelope" and s.get("samplingMeasure") != "unknown":
                errors.append(f"support {s['id']}: an envelope's sampling measure is unknown")
        elif kind == "point":
            if not (_finite(at) and at >= 0 and a is None and b is None):
                errors.append(f"support {s['id']}: a point needs atMd only")
        elif not (a is None and b is None and at is None):
            errors.append(f"support {s['id']}: unknown support must carry no depths")

    for d in project["determinations"]:
        if d.get("supportId") not in supports:
            errors.append(f"determination {d['id']}: unknown support")
        if d.get("analyteId") not in analytes:
            errors.append(f"determination {d['id']}: unknown analyte")
        q, v = d.get("qualifier"), d.get("value")
        if q not in QUALIFIERS:
            errors.append(f"determination {d['id']}: qualifier {q!r}")
        elif q == "=":
            if not _finite(v):
                errors.append(f"determination {d['id']}: an unqualified result needs a finite value")
        elif v is not None or not (_finite(d.get("detectionLimit")) and d["detectionLimit"] > 0):
            errors.append(f"determination {d['id']}: a censored result keeps no value and a positive limit")
        if d.get("rawValue") in (None, ""):
            errors.append(f"determination {d['id']}: raw source token lost")
        if len(errors) > 200:
            errors.append("stopped after 200 violations")
            return errors

    for g in project["geology"]:
        kind = g.get("kind")
        if kind == "interval" and not (_finite(g.get("fromMd")) and _finite(g.get("toMd")) and g["fromMd"] < g["toMd"]):
            errors.append(f"geology {g['id']}: interval needs from < to")
        if kind == "event" and not (_finite(g.get("fromMd")) and g.get("fromMd") == g.get("toMd")):
            errors.append(f"geology {g['id']}: an event has one depth")
        if kind not in ("interval", "event"):
            errors.append(f"geology {g['id']}: kind {kind!r}")

    for i in project["issues"]:
        if i.get("severity") not in SEVERITIES or not i.get("code") or not i.get("rowIds"):
            errors.append(f"issue {i.get('id')}: needs a severity, a code and the affected rows")

    for step in project.get("waterfall", []):
        if not (isinstance(step.get("count"), int) and step["count"] >= 0 and step.get("step")):
            errors.append(f"waterfall step {step!r}: needs a name and a nonnegative count")
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
    composite_ids = set()
    if "composites" in pre:
        numerators: dict = {}
        for row in pre["composites"]["rows"]:
            composite_ids.add(row["id"])
            if row["status"] not in STATUSES:
                errors.append(f"composite {row['id']}: status {row['status']!r}")
                continue
            length = row["toMd"] - row["fromMd"]
            if row["status"] == "full" and (abs(length - row["length"]) > 1e-9 or abs(row["coverage"] - 1) > 1e-12):
                errors.append(f"composite {row['id']}: a full composite has the declared length and coverage 1")
            if row["status"] == "residual" and not (length < row["length"] and abs(row["coverage"] - 1) <= 1e-12):
                errors.append(f"composite {row['id']}: a residual is shorter with coverage 1")
            has_values = all(v is not None and _finite(v) for v in row["values"].values())
            if (row["status"] == "insufficient-coverage") == has_values:
                errors.append(f"composite {row['id']}: only covered composites carry means")
            if any(pid not in supports for pid, _ in row["parents"]):
                errors.append(f"composite {row['id']}: parent is not a project support")
            for analyte, value in row["numerators"].items():
                key = (row["holeId"], row["length"], analyte)
                numerators[key] = numerators.get(key, 0.0) + value
        source: dict = {}
        for d in project["determinations"]:
            s = supports[d["supportId"]]
            if s["kind"] == "interval" and d["qualifier"] == "=":
                key = (s["holeId"], d["analyteId"])
                source[key] = source.get(key, 0.0) + d["value"] * (s["toMd"] - s["fromMd"])
        for (hole, _length, analyte), total in numerators.items():
            expected = source.get((hole, analyte), 0.0)
            if abs(total - expected) > 1e-9 * max(1.0, abs(expected)):
                errors.append(f"composites of {hole} do not conserve the {analyte} grade-length integral")
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
