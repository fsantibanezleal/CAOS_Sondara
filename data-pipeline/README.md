# data-pipeline/, the offline lane

Plain scripts run by path in the local `.venv-pipeline`; the product declares no package of its own. The numerical
engine is the separate [GeoCond](https://pypi.org/project/geocond/) package, consumed as a dependency.

| Path | Role |
|---|---|
| `run.py` | Stage runner: `python data-pipeline/run.py acquire|ingest [--family rocklea|alberta|ntgs|all] [--cache DIR] [--out DIR]` |
| `source_io.py` | Bounded acquisition (HTTPS, byte limits, SHA-256), strict CSV/TSV reading that keeps logical row IDs, zip members read without extraction, atomic JSON writes, stable hashing |
| `source_adapters/common.py` | Constructors for the canonical project tables and the QA issue records |
| `source_adapters/rocklea.py` | CSIRO Rocklea Dome: assay workbook, TSG coordinates and terrain elevations into assumed-vertical holes |
| `source_adapters/alberta.py` | AGS DIG 2024-0022, report MAR_19860002: collars, logged geology and Cu/Zn sampling envelopes |
| `source_adapters/ntgs.py` | NTGS 12LE002: the bundled measured-survey subset with censored results as qualifiers |
| `learned/` | Contracts, features, networks, training, evaluation and ONNX export for the learned methods (unit SD-7) |

## Setup and run

```sh
python -m venv .venv-pipeline
.venv-pipeline/Scripts/python -m pip install -r requirements-precompute.txt -r requirements-dev.txt
export SONDARA_RAW=/path/outside/the/repo        # raw downloads; never committed
.venv-pipeline/Scripts/python data-pipeline/run.py acquire
.venv-pipeline/Scripts/python data-pipeline/run.py ingest
.venv-pipeline/Scripts/python scripts/check_artifacts.py
```

`acquire` downloads about 14.7 MB (the Rocklea workbook, TSG export and terrain points, and the Alberta archive) and
copies the bundled NTGS subset. `ingest` writes `build/derived/<family>/project.json` and `summary.json`.

The stage chain, the canonical tables and what each stage will add are described in
[../docs/architecture/05_precompute-pipeline.md](../docs/architecture/05_precompute-pipeline.md); the three families in
[../docs/cases/](../docs/cases/).
