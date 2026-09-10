"""Validate the compact derived drillhole project contract."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    path = ROOT / "data" / "derived" / "demo" / "project.json"
    if not path.exists():
        print(f"FAIL: missing {path} (run data-pipeline/run.py demo first)")
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = []
    if payload.get("schema") != "drillhole.project/v1": errors.append("wrong project schema")
    if payload.get("status") != "validated": errors.append("project is not validated")
    if errors:
        print("PROJECT CONTRACT DRIFT:")
        for error in errors: print(f"  - {error}")
        return 1
    print("PROJECT CONTRACT OK: validated drillhole project present.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
