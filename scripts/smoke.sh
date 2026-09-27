#!/usr/bin/env bash
# Smoke: validate every ingested family in build/derived against the drillhole.project/v1 contract
# (run data-pipeline/run.py ingest first).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv-pipeline/bin/python"; [ -x "$PY" ] || PY=".venv-pipeline/Scripts/python.exe"
[ -x "$PY" ] || PY="${PYTHON:-python}"
"$PY" scripts/check_artifacts.py
