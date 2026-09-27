# scripts/, environment + pipeline orchestration (cross-platform)

Local scripts so **anyone** can configure the env and run the flow. Provide every script in BOTH `*.sh`
(macOS/Linux/Git-Bash) and `*.ps1` (Windows PowerShell, since Felipe runs PS).

## How to populate

| Script | What it must do |
|---|---|
| `setup.sh` / `setup.ps1` | create `.venv`, upgrade pip, install `requirements.txt -r requirements-dev.txt -r requirements-precompute.txt`; print the next commands. GPU/API lanes installed only on demand. |
| `precompute.sh` / `precompute.ps1` | run one offline stage: `python data-pipeline/run.py <stage> [options]` (today `acquire` and `ingest`; see docs/architecture/05_precompute-pipeline.md). |
| raw inputs | `run.py acquire` downloads the pinned sources into `$SONDARA_RAW` (outside the repository). Never commit raw. |
| `serve-api.sh` / `serve-api.ps1` | (optional, only if `api/` is active) `uvicorn api.main:app --reload`. |

Rules: idempotent; detect `.venv/bin/python` vs `.venv/Scripts/python.exe`; never use global Python/Node.
Pin nothing here, versions live in `requirements-*.txt`.

## Guards (run in CI, keep them local-runnable)

| Script | What it enforces |
|---|---|
| `check_artifacts.py` | Every ingested family in `build/derived` meets the `drillhole.project/v1` contract with a matching summary, and every preprocessed output is consistent with its project. |
| `figures/preprocess_figures.py` | Draws the preprocess figures of the docs (light and dark SVG) from the real outputs in `build/derived`. |
| `figures/features_figures.py` | Draws the variogram figure of the docs from `rocklea/features.json`. |
| `fixtures/author_fixtures.py` | Writes the authored fixtures F01 to F42 and their registry (`data/fixtures/`), deterministically. |
| `check_sdd.py` | The design document exists and every requirement names a gate that exists (ADR-0075). |
| `check_template_residue.py` | An instantiated product must not ship template residue (the example pipeline, SIR model, `EX0*` cases, placeholder text). No-op in the template itself while the `.template-source` sentinel exists; instantiation deletes the sentinel to arm it. See ADR-0057 / ADR-0061. |
| `check_content_standards.py` | No em-dash (`U+2014`/`U+2015`) and no pictographic emoji in tracked content. Always on. Use comma/colon/semicolon/period/parentheses/middot instead. See ADR-0067. |
