# Template blueprint, the authoritative structure (align here BEFORE mass-generating)

This is the agreed shape of a REAL product repo. Every requirement Felipe raised is captured here. Nothing is
built against it until the shape is approved, so we don't build-then-redo.

> **Blueprint names → shipped tree (read this first).** This blueprint predates the built template and uses
> generic names. In the tree actually shipped: **`productlab/` = `data-pipeline/pipeline/`** (the Python
> package lives INSIDE `data-pipeline/`; on instantiation rename `pipeline` → `pipeline`), **`web/` =
> `frontend/`**, and **`api/` = `app/`** (the dormant FastAPI module). The stage/contract/lane semantics below
> are unchanged, only the paths differ. When in doubt, the shipped tree + `docs/guides/00_instantiate.md` win.

## Three execution lanes + a replay fallback, SEPARATE dependencies AND implementation

A product can run in up to three lanes. They do **not** share one engine by default: the offline engine is the
heavy SOTA one; the live engine is often a **reduced / surrogate / small-Pyodide** model; the web always has a
**replay fallback** (the baked artifact). The clean separation of *dependencies* and *implementation* per lane is
mandatory, never let a heavy native dep leak into the live lane, never let the live toy masquerade as the SOTA.

| Lane | Dependencies | Implementation | Notes |
|---|---|---|---|
| **Offline (precompute)** | `requirements-precompute.txt` (+ `-gpu`) | `productlab/stages/` (heavy SOTA engine) | bakes the committed artifacts; native libs OK (Yade/OR-Tools/…) |
| **Live (client-side)** | `requirements.txt` (Pyodide-safe wheels) **or** web npm deps | `productlab/live/` (Pyodide-safe Python) **or** `web/src/engine/` (TS) | small sims / surrogate / analytic core, runs in the browser, like SimLab's Pyodide live lane. **May be a DIFFERENT, lighter model than offline.** |
| **API / backend** *(optional)* | `requirements-api.txt` | `api/` (FastAPI) over `productlab/model/` | only on an ADR-0002 trigger; thin layer over the shared core, never a re-implementation |
| **Replay fallback** |, (none) | `web/src/engine/replay` loads `data/artifacts` + manifest | always present; first paint + when live unavailable |

- **`productlab/model/`**, the pure-Python analytic/physics core that is **shared and Pyodide-safe**, usable by the
  offline stages, the live lane, and the api. The *only* code that may run in more than one lane.
- **`productlab/stages/`**, the OFFLINE pipeline (heavy engines), never imported by the live lane.
- **`productlab/live/`**, the LIVE-lane engine (reduced/surrogate/small), importing only `model/` + Pyodide-safe deps.
- **`web/`**, the app; runs the live lane (Pyodide importing `productlab.live`, or a TS engine in `src/engine/`) and
  always falls back to **replaying** committed artifacts.
- **`api/`** *(optional, dormant)*, a thin FastAPI layer over `productlab/model/`; imports it, never re-implements.

The lane each case actually uses is decided by `productlab/core/gate.py` (pure-python ∧ runtime ∧ trace-size gate,
ADR-0054), exactly SimLab's `classify_lane`.

## The pipeline is SEPARATED BY NAMED STAGES

`productlab/stages/`, each stage is a pure, deterministic, **seeded**, typed, independently-tested function with an
explicit **input→output contract** to the next stage. Not a monolith.

| Order | Stage module | Input | Output | Notes |
|---|---|---|---|---|
| 1 | `ingest.py` | raw dataset (via `io/contract.py`) | validated source records | applies the ingestion contract, provenance, and outlier policy |
| 2 | `preprocess.py` | validated source records | calibrated/cleaned records | domain normalization with fitted-state persistence |
| 3 | `dataset.py` | records + source/seed/site/time groups | versioned train/val/calibration/test splits | blocks leakage before fitting |
| 4 | `features.py` | split records | feature tensors/tables | deterministic; fitted transforms use train only |
| 5 | `train.py` | train/val features + labels | checkpoint(s) + training manifest | one real implementation per learned method; resumable |
| 6 | `infer.py` | method + checkpoint + held-out cases | predictions + timings | executes every promised method, including offline-only engines |
| 7 | `evaluate.py` | predictions vs held-out truth | complete method × case metric matrix | missing cells fail; includes parity and robustness |
| 8 | `export.py` | predictions + metrics | compact web artifacts + manifests | processing→web contract; canonical results are immutable |
| 9 | `validate.py` | registry + checkpoints + manifests + artifacts | signed/checksummed release report | final completeness, schema, provenance, and drift gate |

`pipeline.py` orchestrates these (an ordered `STAGES` list); `python -m productlab.pipeline <case>` runs them and
persists artifact + manifest. Add domain stages as needed (e.g. `calibrate.py`, `decimate.py`), same rules.

## The TWO data contracts (were missing everywhere)

1. **Ingestion `raw → processing`**, `productlab/io/contract.py`: required schema (columns, units, ranges) + an
   explicit outlier policy (reject/clip/flag). The *bring-your-own-data* gate. Doc: `docs/data-contract.md`.
2. **Artifact `processing → web`**, `manifests/<case>.json` + the compact artifact schema; the web has a TS type
   mirroring it (`web/src/contract.ts`) so a drift fails the build; `web/copy-data.mjs` copies canonical artifacts.

## Standard formats end-to-end

`productlab/io/formats.py`: domain-standard readers/writers, CSV (sieve-series / tabular), parquet (heavy full
dataset, gitignored/LFS), npz/JSON (compact committed artifact), and per-product `.vtk/.vtu`, `.h5`, `.mat`,
GeoTIFF. The compact committed artifacts in `data/artifacts/` ARE the standardized synthetic datasets.

## Full tree

```
<producto>/
├─ README.md · CHANGELOG.md (X.XX.XXX + tags) · LICENSE · LICENSES.md · ATTRIBUTION.md
├─ pyproject.toml · .env.example · .gitignore · .gitattributes
├─ requirements.txt (live) · -dev · -precompute (SOTA engines) · -gpu · -api
├─ scripts/  setup.{sh,ps1} · precompute.{sh,ps1} · fetch-data.{sh,ps1} · serve-api.{sh,ps1}
├─ productlab/                      # the engine + staged pipeline
│  ├─ __init__.py (version) · pipeline.py (orchestrator+CLI) · registry.py (cases, grouped by CATEGORY)
│  ├─ io/     contract.py (ingestion contract+outliers) · formats.py (std readers/writers) · schema.py (types)
│  ├─ core/   rng.py (seed→determinism) · trace.py (artifact) · manifest.py · gate.py (lane gate)
│  ├─ model/  shared pure-Python analytic core, Pyodide-safe; used by stages + live + api (the ONLY shared code)
│  ├─ stages/ OFFLINE pipeline (heavy SOTA engine): preprocess · features · train · infer · evaluate · export
│  ├─ live/   LIVE-lane engine (reduced/surrogate/small), imports model/ + Pyodide-safe deps only; ≠ offline
│  └─ cases/  one module per case; each carries id, CATEGORY, params, expected band, real/synthetic, anchor
├─ models/                          # trained model artifacts (small→committed e.g. .onnx; heavy→gitignored)
├─ data/
│  ├─ raw/ (gitignored)  · examples/ (tiny committed sample input, std format) · artifacts/<case>/ (committed compact)
│  └─ README.md                     # the data contract: formats, schema, units, provenance, license, outliers
├─ manifests/<case>.json            # ADR-0054 contract per case (+ a top-level index)
├─ tests/  test_contract · test_determinism · test_stages · test_gate · test_parity
├─ docs/                            # the wiki (ADR-0056), authored AS you build
│  ├─ README.md (landing)
│  ├─ architecture/  overview · determinism+trace · the-gate · data-contracts · staged-pipeline · api-backend · deploy
│  ├─ frameworks/<tool>/            # 1 per research-chosen engine: what/why · install · configure · runnable example
│  ├─ cases/                        # ← CASES + CATEGORIES: README (category taxonomy + coverage matrix) + 1 md/case
│  ├─ guides/  00_instantiate · 01_precompute-pipeline · 02_bring-your-own-data · 03_gpu-lane · 04_run-the-api
│  └─ data-contract.md
├─ api/                             # OPTIONAL backend (dormant): main.py · routes/ · deps over productlab
├─ web/  src/ (App/Intro/Methodology/Implementation/Experiments/Benchmark) · contract.ts · copy-data.mjs · vite/pkg
└─ .github/workflows/  ci.yml (install reqs · ruff · pytest · pipeline smoke · guards) · deploy-pages.yml
```

## Cases & categories (explicit)

- Each case in `productlab/cases/` declares a **`category`** (the domain taxonomy of problem types) + params +
  expected output band + real/synthetic flag + validation anchor.
- `registry.py` groups cases by category; the App tab shows **one selected case**, while Experiments/Benchmark
  show **cross-case summaries grouped by category** (never mixed into App).
- `docs/cases/README.md` is the category taxonomy + the coverage matrix; `docs/cases/<id>.md` documents each case.

## What CI enforces (so we can't regress to demos)

`ruff` · `pytest` · **sandboxed pipeline smoke** (regenerate one case under a temporary output root) ·
**guards** (no real `.env`, no raw/heavy data tracked, no incomplete method/case matrix, no "live"-tagged
stage that breaches the gate, manifest⇄artifact contract holds). The release bake is an explicit command;
the web build and deployment only verify/copy committed artifacts and never run canonical science.
