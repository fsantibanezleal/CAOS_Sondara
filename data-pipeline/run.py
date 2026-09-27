#!/usr/bin/env python3
"""Sondara's offline pipeline, stage by stage. Plain scripts run by path; the product declares no package.

    python data-pipeline/run.py acquire [--cache DIR]
    python data-pipeline/run.py ingest  [--family rocklea|alberta|ntgs|all] [--cache DIR] [--out DIR]
    python data-pipeline/run.py ingest  --manifest import.json [--out DIR]
    python data-pipeline/run.py preprocess [--family rocklea|alberta|ntgs|all|<project id>] [--out DIR]
    python data-pipeline/run.py dataset    [--family ...] [--out DIR]
    python data-pipeline/run.py features   [--family ...] [--out DIR]

``acquire`` fetches the pinned sources of ``data/sources/manifest.json`` (or copies the bundled licensed subset),
checking every byte count and SHA-256, and writes an acquisition receipt. ``ingest`` builds each family's canonical
project (``drillhole.project/v2``), its QA issue table and its reconciliation waterfall, and writes them with a hash;
with ``--manifest`` it imports user files described by an import manifest instead, as a transaction that commits only
an accepted project and always writes ``<project id>.import-report.json``. ``preprocess`` reads a project, checks its
hash against the ingest summary, and writes the desurveyed positions, result selections, composites, log overlays and
modeling populations (``stages/preprocess.py``, on GeoCond); for an imported project it takes the compositing options
and method priority from the stored manifest. ``dataset`` freezes the grouped splits of each family (hole-group,
spatial-margin and a declared holdout) before any fit, and ``features`` computes training-only statistics,
declustering and experimental variograms (``stages/dataset.py``, ``stages/features.py``). Each stage checks the hash of
its input. Raw sources live outside the repository (``--cache``, default ``$SONDARA_RAW`` or ``build/sources``); derived
outputs go to ``--out`` (default ``build/derived``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from source_io import ROOT, acquire, load_json, stable_hash, write_json

FAMILIES = ("rocklea", "alberta", "ntgs")
COUNTED = ("collars", "surveys", "trajectories", "analytes", "supports", "determinations", "geology", "qc",
           "exclusions", "issues")


def _adapter(family: str):
    if family == "rocklea":
        from source_adapters.rocklea import normalize
    elif family == "alberta":
        from source_adapters.alberta import normalize
    else:
        from source_adapters.ntgs import normalize
    return normalize


def ingest(family: str, cache: Path, out: Path) -> dict:
    t0 = time.time()
    project = _adapter(family)(cache)
    target = out / family
    write_json(target / "project.json", project)
    summary = {
        "schema": "drillhole.ingest-summary/v1",
        "family": family,
        "projectSha256": stable_hash(project),
        "recipe": project["provenance"]["recipe"],
        "recipeSha256": project["provenance"]["recipeSha256"],
        "counts": {k: len(project[k]) for k in COUNTED},
        "waterfall": project.get("waterfall", []),
        "issues": [{"code": i["code"], "severity": i["severity"], "rows": len(i["rowIds"])} for i in project["issues"]],
        "seconds": round(time.time() - t0, 2),
    }
    write_json(target / "summary.json", summary, pretty=True)
    return summary


def ingest_manifest(manifest: Path, out: Path, cancel=None) -> dict:
    from source_adapters.manifest_import import run_import

    return run_import(manifest, out, cancel)


def preprocess(family: str, out: Path) -> dict:
    from stages.preprocess import preprocess as run_stage

    t0 = time.time()
    target = out / family
    project = load_json(target / "project.json")
    ingest_summary = load_json(target / "summary.json")
    project_sha = stable_hash(project)
    if ingest_summary["projectSha256"] != project_sha:
        raise ValueError(f"{family}: project.json does not match its ingest summary; run ingest again")
    options = {}
    if (target / "import.json").is_file():
        manifest = load_json(target / "import.json")
        compositing = manifest.get("compositing", {})
        options = {**({"lengths": compositing["lengths"]} if "lengths" in compositing else {}),
                   **({"minCoverage": compositing["minCoverage"]} if "minCoverage" in compositing else {}),
                   "methodPriority": manifest.get("methodPriority", {})}
    result = run_stage(family, project, project_sha, options)
    write_json(target / "preprocessed.json", result)
    summary = {
        "schema": "drillhole.preprocess-summary/v1",
        "family": family,
        "preprocessedSha256": stable_hash(result),
        "inputProjectSha256": project_sha,
        "recipeSha256": result["recipeSha256"],
        "engine": result["engine"],
        "waterfall": result["waterfall"],
        "populations": [{k: p[k] for k in ("id", "task", "support", "count", "holes", "excluded")}
                        for p in result["populations"]],
        "seconds": round(time.time() - t0, 2),
    }
    write_json(target / "preprocess-summary.json", summary, pretty=True)
    return summary


def _stored_manifest(target: Path) -> dict:
    return load_json(target / "import.json") if (target / "import.json").is_file() else {}


def _preprocessed(family: str, out: Path):
    target = out / family
    project = load_json(target / "project.json")
    pre = load_json(target / "preprocessed.json")
    project_sha, pre_sha = stable_hash(project), stable_hash(pre)
    if pre["inputProjectSha256"] != project_sha:
        raise ValueError(f"{family}: preprocessed.json was built from another project; run preprocess again")
    if load_json(target / "preprocess-summary.json")["preprocessedSha256"] != pre_sha:
        raise ValueError(f"{family}: preprocessed.json does not match its summary; run preprocess again")
    return target, project, pre, project_sha, pre_sha


def dataset(family: str, out: Path) -> dict:
    from stages.dataset import split_family

    target, project, pre, project_sha, pre_sha = _preprocessed(family, out)
    holdout = _stored_manifest(target).get("holdout")
    result = split_family(family, project, pre, project_sha, pre_sha, holdout=holdout)
    write_json(target / "dataset.json", result, pretty=True)
    return {"family": family, "eligible": result["eligible"],
            "schemes": {s["id"]: s["holeCounts"] for s in result["schemes"]}}


def features(family: str, out: Path) -> dict:
    from stages.features import family_features

    t0 = time.time()
    target, project, pre, project_sha, pre_sha = _preprocessed(family, out)
    split = load_json(target / "dataset.json")
    if (split["inputProjectSha256"], split["inputPreprocessedSha256"]) != (project_sha, pre_sha):
        raise ValueError(f"{family}: dataset.json was built from other inputs; run dataset again")
    manifest = _stored_manifest(target)
    result = family_features(family, project, pre, split, orientations=manifest.get("orientations"))
    result["inputDatasetSha256"] = stable_hash(split)
    write_json(target / "features.json", result)
    return {"family": family, "eligible": result["eligible"], "schemes": len(result["schemes"]),
            "seconds": round(time.time() - t0, 2)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["acquire", "ingest", "preprocess", "dataset", "features"])
    parser.add_argument("--family", default="all", help="rocklea, alberta, ntgs, all, or an imported project id")
    parser.add_argument("--manifest", type=Path, help="ingest user files described by this import manifest")
    parser.add_argument("--cache", type=Path, default=Path(os.environ.get("SONDARA_RAW", ROOT / "build" / "sources")))
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "derived")
    args = parser.parse_args(argv)
    if args.stage == "acquire":
        print(json.dumps(acquire(args.cache), indent=2))
        return 0
    if args.stage == "ingest" and args.manifest:
        report = ingest_manifest(args.manifest, args.out)
        print(json.dumps({"project": report["project"], "status": report["status"],
                          "findings": report["counts"]["bySeverity"]}))
        return 0 if report["status"] == "accepted" else 2
    families = FAMILIES if args.family == "all" else (args.family,)
    for family in families:
        if args.stage == "ingest":
            if family not in FAMILIES:
                parser.error(f"unknown family {family!r}; import user files with --manifest")
            summary = ingest(family, args.cache, args.out)
            print(json.dumps({k: summary[k] for k in ("family", "counts", "waterfall", "seconds")}))
        elif args.stage == "preprocess":
            summary = preprocess(family, args.out)
            print(json.dumps({k: summary[k] for k in ("family", "waterfall", "seconds")}))
        elif args.stage == "dataset":
            print(json.dumps(dataset(family, args.out)))
        else:
            print(json.dumps(features(family, args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
