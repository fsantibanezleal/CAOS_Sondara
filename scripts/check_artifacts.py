#!/usr/bin/env python3
"""Validate every ingested canonical project against the drillhole.project/v1 contract.

    python scripts/check_artifacts.py [--derived build/derived]

For each ``<family>/project.json`` with its ``summary.json`` the check verifies: the schema; the summary hash and
counts against the project; unique identifiers per table; every survey, trajectory, support and geology record on a
known collar; every determination on a known support and analyte; support geometry consistent with its kind;
censoring kept as a qualifier with a positive limit and no value; finite values; and a QA issue table whose rows are
named. It exits nonzero and lists every violation, so a changed adapter cannot write a project the later stages would
misread.
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
    print(f"PROJECT CONTRACT OK: {', '.join(f.name for f in folders)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
