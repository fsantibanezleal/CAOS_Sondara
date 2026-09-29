# Guide, the GPU lane

Sondara uses CUDA in two places, both offline: the learned lane (DeepKriging and KCN, and for Rocklea the geochemical
autoencoder review of R12, unit SD-7) trains on the device, and the Direct Sampling parity check S11 runs GeoCond's
PyTorch backend against its NumPy one. Nothing in the
published site needs a GPU: the browser receives precomputed results and, for the learned methods, ONNX models that
run on the CPU.

## Build the environment

`.venv-gpu` holds everything `.venv-pipeline` holds, plus PyTorch built for CUDA 12.6, onnx and ONNX Runtime:

```bash
python -m venv .venv-gpu
.venv-gpu/bin/python -m pip install -r requirements-gpu.txt      # .venv-gpu\Scripts\python.exe on Windows
.venv-gpu/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name())"
```

`requirements-gpu.txt` pins `torch==2.14.0` from the PyTorch CUDA 12.6 index and includes the pipeline and development
requirements. It was verified on an RTX 4070 Laptop GPU (8 GB). Without a device the same code trains on the CPU, more
slowly, and every record says which device ran.

## Run the learned lane

The learned lane needs the classical chain up to `features` (and `train` and `infer` for the continuous lane, because
`evaluate` scores every method on the same targets):

```bash
./scripts/precompute.sh train    --family rocklea --out build/derived --lane learned
./scripts/precompute.sh infer    --family rocklea --out build/derived --lane learned
./scripts/precompute.sh evaluate --family rocklea --out build/derived --lane learned
```

`scripts/precompute.sh` and `.ps1` use `.venv-gpu` when it exists. `--lane all` (the default) runs every lane and stops
with a message when PyTorch is missing.

What the three stages do, and what they write under `build/derived/<family>/`:

| Stage | Output | Notes |
|---|---|---|
| `train` | `learned-models.json`, `learned/fits/<scheme>/<population>/<method>/<configuration>/seed-<n>/` | every configuration of the frozen search with three seeds, the two controls; each fit holds `fit.json` (history, best epoch) and `weights.pt` (tensors only) |
| `infer` | `learned-predictions.json`, `learned/exports/<scheme>/<population>/<method>/seed-<n>/` | the three-seed ensemble on the test and calibration targets; one ONNX file per seed with `manifest.json`, `parity.json` and `portable-model.zip` |
| `evaluate` | `metrics.json` | the learned methods scored beside the classical ones on the same targets |
| all three, Rocklea | `geochemistry-models.json`, `geochemistry-predictions.json`, `geochemistry-metrics.json`, `learned/geochemistry/`, `learned/exports/geochemistry/` | the autoencoder review of R12: fits for latent sizes 2 and 3 with three seeds, the PCA reference, the scored records and alterations, the review export with its parity |

**Rerunning is cheap.** A finished fit whose recipe hash matches is reused, an interrupted one resumes from its last
checkpoint (every 20 epochs), and one whose recipe differs is refused: remove its folder to refit. Delete
`build/derived/<family>/learned/` to start over.

**Time.** On the RTX 4070 Laptop GPU (2026-09-28), Rocklea's six populations (414 fits, 69 per population: the two
searches and the controls, three seeds each) trained in 2,475 s, and `infer` (the ensembles and 36 exports with their
parity) took 81 s; Alberta took 40 s and 18 s. Each fit records its own `fitSeconds` in `learned-models.json`. Run
one heavy PyTorch job at a time: two jobs on one device slow each other down more than they gain. The stages are
checkpointed, so a run that stops (a closed session, a restart) continues from the finished fits when started again.

## Check the outputs

```bash
.venv-gpu/bin/python scripts/check_artifacts.py --derived build/derived
.venv-gpu/bin/python -m pytest tests/test_learned.py
```

`check_artifacts.py` re-audits every exported ONNX file (standard operators, no control flow, no external data, no
metadata, no local path, byte and node budgets), checks its parity record against the tolerance ($10^{-4}$ training
standard deviations), and checks the selection rule and every weights hash. The CUDA parity test skips without a
device.

## On Windows

The torch.export ONNX exporter prints a check-mark character that a cp1252 console cannot encode; the pipeline captures
the exporter's output, so this only matters when calling the exporter by hand (set `PYTHONUTF8=1`). The exporter also
writes each node's Python stack trace, with local paths, into the model; `learned/exporting.py` removes all metadata and
the audit refuses a model that still carries a path.
