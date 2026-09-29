#!/usr/bin/env bash
# Create the virtual environments and install each lane's pinned requirements. Idempotent. No global installs; the
# product declares no package of its own (GeoCond is a PyPI dependency).
#   .venv-pipeline = offline lane (requirements-precompute.txt) + dev tools                 (local only)
#   .venv          = runtime lane (requirements.txt)                                         (what ships)
#   .venv-gpu      = offline lane + PyTorch CUDA, onnx, ONNX Runtime (requirements-gpu.txt), with --gpu: the learned
#                    methods and the Direct Sampling parity check (docs/guides/03_gpu-lane.md)
#   ./scripts/setup.sh [--gpu]
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"

mkvenv() { [ -d "$1" ] || "$PY" -m venv "$1"; }
venvpy() { local p="$1/bin/python"; [ -x "$p" ] || p="$1/Scripts/python.exe"; echo "$p"; }

echo "[setup] .venv-pipeline (offline lane)"
mkvenv .venv-pipeline
VP="$(venvpy .venv-pipeline)"
"$VP" -m pip install --upgrade pip -q
"$VP" -m pip install -q -r requirements-precompute.txt -r requirements-dev.txt
echo "[setup] .venv-pipeline ready."

echo "[setup] .venv (runtime lane)"
mkvenv .venv
VR="$(venvpy .venv)"
"$VR" -m pip install --upgrade pip -q
"$VR" -m pip install -q -r requirements.txt
echo "[setup] .venv ready."

if [ "${1:-}" = "--gpu" ]; then
  echo "[setup] .venv-gpu (offline lane with PyTorch CUDA 12.6)"
  mkvenv .venv-gpu
  VG="$(venvpy .venv-gpu)"
  "$VG" -m pip install --upgrade pip -q
  "$VG" -m pip install -q -r requirements-gpu.txt
  echo "[setup] .venv-gpu ready."
fi

echo "[setup] done. Next: ./scripts/precompute.sh acquire (docs/guides/01_precompute-pipeline.md)"
