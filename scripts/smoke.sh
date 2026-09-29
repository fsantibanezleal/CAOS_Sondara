#!/usr/bin/env bash
# Smoke: check every derived output in build/derived against its contract (scripts/check_artifacts.py: the
# drillhole.project/v2 projects, the stage outputs, the categorical and learned lanes, the scenario matrix).
#   ./scripts/smoke.sh [--derived DIR]
# Uses .venv-gpu when it exists, because the learned outputs are audited with onnx.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=""
for venv in .venv-gpu .venv-pipeline; do
  for exe in bin/python Scripts/python.exe; do
    if [ -z "$PY" ] && [ -x "$venv/$exe" ]; then PY="$venv/$exe"; fi
  done
done
PY="${PY:-${PYTHON:-python}}"
"$PY" scripts/check_artifacts.py "$@"
