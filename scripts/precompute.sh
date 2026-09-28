#!/usr/bin/env bash
# Run one offline stage (pass-through args). E.g.:  ./scripts/precompute.sh ingest --family rocklea
# Uses .venv-gpu when it exists (it holds the pipeline packages and PyTorch, which the learned lane needs), else
# .venv-pipeline, where the learned lane stops with a message (pass --lane continuous or --lane categorical).
set -euo pipefail
cd "$(dirname "$0")/.."
VP=""
for venv in .venv-gpu .venv-pipeline; do
  for exe in bin/python Scripts/python.exe; do
    if [ -z "$VP" ] && [ -x "$venv/$exe" ]; then VP="$venv/$exe"; fi
  done
done
[ -n "$VP" ] || { echo "no .venv-gpu or .venv-pipeline; run scripts/setup.sh first" >&2; exit 1; }
"$VP" data-pipeline/run.py "$@"
