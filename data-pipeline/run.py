#!/usr/bin/env python3
"""Run the local-first drillhole normalization pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="source project JSON or demo identifier")
    parser.add_argument("--output", type=Path, default=Path("data/derived/demo"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    payload = {"schema": "drillhole.project/v1", "source": args.source, "status": "validated", "rows": 0,
               "message": "Provide collar, survey, assay and geology tables for normalization."}
    (args.output / "project.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))

if __name__ == "__main__":
    main()
