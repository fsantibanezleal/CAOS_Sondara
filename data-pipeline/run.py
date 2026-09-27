#!/usr/bin/env python3
"""Sondara's offline pipeline, stage by stage. Plain scripts run by path; the product declares no package.

    python data-pipeline/run.py acquire [--cache DIR]
    python data-pipeline/run.py ingest  [--family rocklea|alberta|ntgs|all] [--cache DIR] [--out DIR]

``acquire`` fetches the pinned sources of ``data/sources/manifest.json`` (or copies the bundled licensed subset),
checking every byte count and SHA-256, and writes an acquisition receipt. ``ingest`` builds each family's canonical
project (collars, surveys, trajectories, analytes, supports, determinations, geology), its QA issue table and its
reconciliation waterfall, and writes them with a hash. Raw sources live outside the repository (``--cache``, default
``$SONDARA_RAW`` or ``build/sources``); derived projects go to ``--out`` (default ``build/derived``).
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

from source_io import ROOT, acquire, stable_hash, write_json

FAMILIES = ("rocklea", "alberta", "ntgs")


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
    counts = {k: len(project[k]) for k in ("collars", "surveys", "trajectories", "analytes", "supports",
                                            "determinations", "geology", "issues")}
    summary = {
        "schema": "drillhole.ingest-summary/v1",
        "family": family,
        "projectSha256": stable_hash(project),
        "recipe": project["provenance"]["recipe"],
        "recipeSha256": project["provenance"]["recipeSha256"],
        "counts": counts,
        "waterfall": project.get("waterfall", []),
        "issues": [{"code": i["code"], "severity": i["severity"], "rows": len(i["rowIds"])} for i in project["issues"]],
        "seconds": round(time.time() - t0, 2),
    }
    write_json(target / "summary.json", summary, pretty=True)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["acquire", "ingest"])
    parser.add_argument("--family", default="all", choices=[*FAMILIES, "all"])
    parser.add_argument("--cache", type=Path, default=Path(os.environ.get("SONDARA_RAW", ROOT / "build" / "sources")))
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "derived")
    args = parser.parse_args(argv)
    if args.stage == "acquire":
        print(json.dumps(acquire(args.cache), indent=2))
        return 0
    families = FAMILIES if args.family == "all" else (args.family,)
    for family in families:
        summary = ingest(family, args.cache, args.out)
        print(json.dumps({k: summary[k] for k in ("family", "counts", "waterfall", "seconds")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
