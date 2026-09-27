# Architecture, overview

This product is an instance of the **CAOS product-repo archetype** ([ADR-0057]): offline-pipeline-heavy,
backend-optional, deploying as a static deterministic-replay viewer. The base is **frozen** (instantiated, never
re-litigated); per-product rework lives only in the **core**, models/algorithms, visualization, content.

## The lanes (and what runs where)
| Lane | Where | Deps | Notes |
|---|---|---|---|
| **Offline (precompute)** | `data-pipeline/` (`pipeline`), `.venv-pipeline` | `data-pipeline/requirements.txt` (SOTA engines) | bakes the committed artifacts |
| **Live (client-side)** | `frontend/src/pyodide` + `pipeline/live.py` | Pyodide-safe wheels (`requirements.txt`) | optional small recompute in the browser; may be a reduced model |
| **Replay** | `frontend/` | n/a | always present; the fallback (ADR-0054) |
| **API (backend)** | `app/` (FastAPI) | `requirements-api.txt` | DORMANT; activate only on an ADR-0002 trigger |

A measured **[gate](03_the-gate.md)** decides live vs replay per case.

## The flow
Pinned sources or user files enter through the sources manifest or an import manifest
([the data contracts](08_data-contracts.md)); the ten stages of `data-pipeline/run.py` (acquire, ingest, preprocess,
dataset, features, train, infer, evaluate, export, validate) turn them into the canonical project and then into
models, predictions and metrics, each output naming the hash of its input
([the precompute pipeline](05_precompute-pipeline.md)); the export stage (unit SD-8) writes the compact artifacts
under an immutable manifest, and the web page (unit SD-9) replays them.

## Frozen base vs rework
- **Frozen:** the folder layout, the two contracts, the staged pipeline names, the gate, the manifest/trace,
  the two-venv split, the cases-by-category mechanism, CI guards. Any area may be **dormant** (with a README).
- **Rework (the only per-product surface):** the engine in `model/` + the stage bodies (the science), the
  `frontend/` visualizations, and the cases + content + calibration.

[ADR-0057]: ../../../conventions/architecture/0-archetype/ADR-0057-product-repo-archetype.md
