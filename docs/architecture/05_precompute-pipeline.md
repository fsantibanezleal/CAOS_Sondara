# The staged precompute pipeline

Sondara's offline lane is a chain of ten named stages, run by path with
`python data-pipeline/run.py <stage> [options]` in the local `.venv-pipeline`. Every stage reads the previous stage's
outputs, writes its own with a hash, and never reaches back to a source it did not declare. Raw sources stay outside
the repository (`--cache`, default `$SONDARA_RAW`, else `build/sources`); derived outputs go to `build/derived/`
(gitignored) until the export stage produces the compact artifacts the web page reads.

| # | Stage | Does | Status |
|---|---|---|---|
| 1 | `acquire` | Fetches the allowlisted sources of `data/sources/manifest.json` over HTTPS with byte bounds and SHA-256 checks, or copies a bundled licensed subset; writes an acquisition receipt | 0.03.000 |
| 2 | `ingest` | Builds each family's canonical project: source namespaces, collars, surveys, trajectories, analytes, supports, determinations, geology, the QA issue table and the reconciliation waterfall, every row carrying its raw source row identity | 0.03.000 (Rocklea, Alberta, NTGS) |
| 3 | `preprocess` | Units and coordinate conventions, deterministic joins, quarantine, exact desurvey, support overlay, compositing and eligibility, through GeoCond | next unit |
| 4 | `dataset` | Frozen hole-group and spatial-block train, validation, calibration and test assignments; every derivative stays with its parent | planned |
| 5 | `features` | Support-aware coordinates, train-only transforms, declared covariates, variogram pair plans and training-image conditioning maps | planned |
| 6 | `train` | Covariance, LMC and indicator fitting, normal-score preparation, DeepKriging, KCN and autoencoder training, model selection and train-only calibration | planned |
| 7 | `infer` | Every continuous estimator on the identical targets; SNESIM and Direct Sampling realizations; CPU and GPU method identity kept | planned |
| 8 | `evaluate` | Native-unit bias, MAE and RMSE, support coverage, class probability scores, hard-data honor and structural metrics | planned |
| 9 | `export` | Arrow and Parquet tables, typed geometry, tiled fields, the model registry, metrics and an immutable manifest | planned |
| 10 | `validate` | Source identity, every expected method, case and variant cell, masks, seeds, license attribution and offline and live parity | planned |

## The canonical project (stage 2 output)

`build/derived/<family>/project.json` follows `drillhole.project/v1`; `summary.json` beside it holds the project hash,
the recipe and its hash, the table counts, the waterfall and the issue counts.

| Table | One row is |
|---|---|
| `frames` | a coordinate frame with its kind, unit, source CRS or definition, origin and stated assumptions |
| `collars` | a hole: frame, x, y, z, total depth (null when the source gives none), observed depth, recorded orientation |
| `surveys` | a survey record with its role; only rows with a measured role are measurements |
| `trajectories` | how a hole's path is known: `measured-stations`, `collar-orientation` or `assumed-vertical` |
| `analytes` | an analyte with its unit, the quantity it reports and its source column |
| `supports` | a sample support: `interval` (known uniform length), `sampling-envelope` (unknown weights), `point` or `unknown` |
| `determinations` | one analytical result: value, the raw source token, qualifier (`=`, `<` or `>`), detection limit, method, lab |
| `geology` | a logged interval or point event, kept verbatim, with an empty slot for a versioned mapping |
| `issues` | a QA finding: code, severity, the affected rows, what it means and the action taken |

`scripts/check_artifacts.py` enforces the contract on every ingested family: unique identifiers, every record on a known
collar, support geometry consistent with its kind, censored results with a limit and no value, finite numbers, named
issue rows, and a summary whose hash and counts match the project. The ingest tests also prove the check rejects each
of those corruptions.

## Determinism

The adapters raise on any drift from the pinned counts, and ingesting the same sources twice produces the same project
hash. The recipe text and its hash travel with every project, so a later result names the exact rules that built its
inputs.
