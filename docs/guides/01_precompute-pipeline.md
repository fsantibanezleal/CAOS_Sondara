# Guide, run the precompute pipeline

The offline pipeline turns the pinned public sources into canonical projects, splits, fitted models, predictions and
scores. Each stage is run by path, reads the previous stage's outputs, checks their hashes, and writes its own. The
stages and their contracts are described in [../architecture/05_precompute-pipeline.md](../architecture/05_precompute-pipeline.md);
this guide is the order to run them in.

## 1. Environments

```bash
./scripts/setup.sh           # .venv-pipeline (offline lane) and .venv (runtime lane); scripts/setup.ps1 on Windows
./scripts/setup.sh --gpu     # also .venv-gpu: PyTorch CUDA, onnx, ONNX Runtime (the learned lane, the S11 check)
```

`scripts/precompute.sh` (and `.ps1`) runs `data-pipeline/run.py` in `.venv-gpu` when it exists, else in
`.venv-pipeline`. The learned lane needs `.venv-gpu`; in `.venv-pipeline` pass `--lane continuous` or
`--lane categorical` to `train`, `infer` and `evaluate`.

## 2. Sources and optional engines

| Setting | Default | What for |
|---|---|---|
| `SONDARA_RAW` (or `--cache`) | `build/sources` | where `acquire` puts the raw files and every later run reads them; keep it outside the repository |
| `--out` | `build/derived` | every derived output, per family |
| `SONDARA_MPSLIB` | `build/mpslib` | MPSlib's SNESIM executables, built from the pinned commit by `scripts/build_mpslib.sh` (Linux or WSL; `.ps1` on Windows calls WSL) |

The categorical lane's `infer` runs SNESIM for Alberta, so build MPSlib first (`./scripts/build_mpslib.sh`, which
writes the executables and a receipt with the commit, compiler and hashes); the tests that need it skip without it.
Without a CUDA device the learned lane trains on the CPU.

## 3. The stages, in order

```bash
./scripts/precompute.sh acquire                                  # pinned URLs, byte counts, SHA-256, license receipt
./scripts/precompute.sh ingest     --family all                  # rocklea, alberta, ntgs: canonical projects
./scripts/precompute.sh preprocess --family all                  # desurvey, supports, composites, overlay, populations
./scripts/precompute.sh dataset    --family all                  # the frozen splits
./scripts/precompute.sh features   --family all                  # training-only statistics and variograms
./scripts/precompute.sh train      --family all                  # every lane: classical, categorical, learned
./scripts/precompute.sh infer      --family all
./scripts/precompute.sh evaluate   --family all                  # scores, and the scenario matrix
```

`--family` takes `rocklea`, `alberta`, `ntgs`, `all`, or the id of a project imported with `ingest --manifest`
([guide 02](02_bring-your-own-data.md)). NTGS has one hole, so its `dataset` records it as not eligible and the later
stages carry that reason. Each stage prints a one-line JSON summary; a stage whose input changed since the previous
stage ran stops and names the stage to rerun.

| Stage | Writes under `build/derived/<family>/` |
|---|---|
| `ingest` | `project.json`, `summary.json` |
| `preprocess` | `preprocessed.json`, `preprocess-summary.json` |
| `dataset` | `dataset.json` |
| `features` | `features.json` |
| `train` | `models.json`; `categorical-models.json` (Alberta); `learned-models.json` and `learned/fits/` |
| `infer` | `predictions.json`; `categorical-predictions.json` and `categorical/`; `learned-predictions.json` and `learned/exports/` |
| `evaluate` | `metrics.json`, `categorical-metrics.json`; and `build/derived/scenarios.json` |

`--lane continuous`, `--lane categorical` or `--lane learned` runs one lane of `train`, `infer` and `evaluate`. The
learned lane scores its methods inside `metrics.json`, so it needs the continuous lane's `predictions.json` first.
Rerunning a lane reuses what is already computed when its inputs match: the SNESIM runs and Direct Sampling
realizations are saved piece by piece, and a learned fit whose recipe hash matches is reused.

## 4. The authored checks and the receipts

```bash
.venv-gpu/bin/python scripts/check_simulation.py      # S10 (SNESIM patterns) and S11 (Direct Sampling CPU and CUDA)
./scripts/smoke.sh                                     # every derived output against its contract
.venv-gpu/bin/python -m pytest                          # the test suite (.venv-pipeline skips the PyTorch tests)
```

`check_simulation.py` writes `simulation-checks.json`, which the scenario matrix reads for S10 and S11; `smoke.sh`
runs `scripts/check_artifacts.py`, which re-audits the learned ONNX exports. The runs are deterministic in their
seeds: the same inputs give the same splits, models and scores, and the learned fits give the same predictions on the
same device (training on another device can change the last digits of the weights; the parity records say by how
much the exported models may differ).
