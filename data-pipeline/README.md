# data-pipeline/, the offline lane

Plain scripts run by path in the local `.venv-pipeline`; the product declares no package of its own. The numerical
engine is the separate [GeoCond](https://pypi.org/project/geocond/) package, consumed as a dependency.

| Path | Role |
|---|---|
| `run.py` | Stage runner: `python data-pipeline/run.py acquire|ingest|preprocess [--family rocklea|alberta|ntgs|all] [--cache DIR] [--out DIR]` |
| `source_io.py` | Bounded acquisition (HTTPS, byte limits, SHA-256), strict CSV/TSV reading that keeps logical row IDs, zip members read without extraction, atomic JSON writes, stable hashing |
| `source_adapters/common.py` | Constructors for the canonical project tables and the QA issue records |
| `source_adapters/rocklea.py` | CSIRO Rocklea Dome: assay workbook, TSG coordinates and terrain elevations into assumed-vertical holes |
| `source_adapters/alberta.py` | AGS DIG 2024-0022, report MAR_19860002: collars, logged geology and Cu/Zn sampling envelopes |
| `source_adapters/ntgs.py` | NTGS 12LE002: the bundled measured-survey subset with censored results as qualifiers |
| `source_adapters/manifest_import.py` | User files through an import manifest: declared dialects, identity, frame checks, conflicts, states, controls, repeats, orphans and overlaps, committed as a transaction |
| `stages/preprocess.py` | The preprocess stage on GeoCond: desurvey, support positions, result selection, eligibility, compositing, log overlays and fragments, gaps, repeats and the modeling populations |
| `stages/dataset.py` | Frozen grouped splits: hole-group, spatial-margin with a buffer, and a declared holdout; memberships of every derived table |
| `stages/features.py` | Training-only statistics, cell declustering, GeoCond experimental variograms (downhole, directional, cross) and declared orientations |
| `stages/models.py` | Fitted GeoCond models, normal-score tables and variograms as JSON records and back, exactly |
| `stages/estimators.py` | The eight classical methods on shared observations, targets and neighbourhood, with domain policies and honest statuses |
| `stages/train.py` | Candidate covariances selected on validation; residual, LMC, indicator and Gaussian-space covariances fitted with the selected structure |
| `stages/infer.py` | Every method on every test target of each scheme and population, and the scenario variants |
| `stages/evaluate.py` | Scores against the test truths, paired hole-block comparisons with OK, variance calibration, MIK Brier and log scores, SGS fair CRPS and reproduction, receipts |
| `stages/categories.py` | The reviewed lithology mapping, the collar surface, and the conditioning of a depth grid by logged intervals (majority rule, recorded conflicts) |
| `stages/training_images.py` | The two labelled training images of the Alberta lane, authored from the training holes |
| `stages/mps.py` | SNESIM through MPSlib's compiled `mps_snesim_tree` as a supervised subprocess, in the pinned parameter schema |
| `stages/categorical.py` | The categorical lane in train, infer and evaluate: conditioning and images, SNESIM and zoned Direct Sampling realizations, scores, connectivity and hole connections |
| `stages/scenarios.py` | The scenario matrix: every registered scenario resolved cell by cell to computed, verified or pending with its owner |
| `stages/learned.py` | The learned lane in train, infer and evaluate: DeepKriging and KCN over their frozen searches with three seeds, validation selection, controls, the ensemble predictions and the ONNX exports with their parity |
| `learned/` | The learned methods' parts: the model binding and seeds (`contracts.py`), training-only transforms and the NumPy oracles (`features.py`), the networks with their features in the graph (`networks.py`), resumable fits (`training.py`), the audited ONNX export and parity (`exporting.py`); `evaluation.py` holds the autoencoder's perturbations (unit SD-7b) |

## Setup and run

```sh
python -m venv .venv-pipeline
.venv-pipeline/Scripts/python -m pip install -r requirements-precompute.txt -r requirements-dev.txt
export SONDARA_RAW=/path/outside/the/repo        # raw downloads; never committed
.venv-pipeline/Scripts/python data-pipeline/run.py acquire
.venv-pipeline/Scripts/python data-pipeline/run.py ingest
.venv-pipeline/Scripts/python data-pipeline/run.py preprocess
.venv-pipeline/Scripts/python data-pipeline/run.py dataset
.venv-pipeline/Scripts/python data-pipeline/run.py features
.venv-pipeline/Scripts/python data-pipeline/run.py train
.venv-pipeline/Scripts/python data-pipeline/run.py infer
.venv-pipeline/Scripts/python data-pipeline/run.py evaluate
.venv-pipeline/Scripts/python scripts/check_artifacts.py
```

`acquire` downloads about 14.7 MB (the Rocklea workbook, TSG export and terrain points, and the Alberta archive) and
copies the bundled NTGS subset. `ingest` writes `build/derived/<family>/project.json` and `summary.json`;
`preprocess` writes `preprocessed.json` and `preprocess-summary.json` beside them.

The stage chain, the canonical tables and what each stage will add are described in
[../docs/architecture/05_precompute-pipeline.md](../docs/architecture/05_precompute-pipeline.md); the three families in
[../docs/cases/](../docs/cases/).
