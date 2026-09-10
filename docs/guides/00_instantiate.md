# Guide, instantiate a new product from this template

1. **Copy** the template tree into the new product repo (its own git repo; code-repo flow `task/* -> develop -> main`).
   Then **delete the `.template-source` sentinel file at the repo root.** This arms
   `scripts/check_template_residue.py` (a CI guard): from now on the build FAILS if any example pipeline or
   placeholder text survives, so you cannot ship SIR/EX0* residue by accident.
2. **Replace the example tooling with product-specific plain scripts** under `data-pipeline/`, invoked
   by path (`python data-pipeline/run.py`). The product declares no internal package: keep
   `pyproject.toml` for tool configuration only, with no `[project]`, `[build-system]` or setuptools
   configuration, and never use `pip install -e .`. If a reusable library is required under ADR-0061,
   create its separate published repository and consume a pinned dependency (ADR-0057 packaging rule).
3. **For a scientific product, replace the EXAMPLE engine with the complete method ladder**: classical, domain SOTA,
   foundation/learned, and frontier methods. For each method implement the ADR-0069 vertical unit:
   dependency + provenance/license + preprocessing + train/calibrate where applicable + checkpoint +
   inference + held-out evaluation + export + tests + framework/case docs + honest lane. **Keep all named
   stages and both contracts; no stage may remain an example or no-op.** Other explicitly selected
   archetypes implement their full declared stage and evidence contract; a curated spatial atlas
   follows ADR-0072 and does not introduce scientific prediction or training outside its scope.
4. **Write CONTRACT 1** (`io/contract.py`) for YOUR raw data, required columns, units, ranges, explicit outlier
   policy, plus a tiny `data/examples/` sample that passes it; document it in `data/README.md`. Update
   `tests/test_contract.py`.
5. **Define cases-by-category and variants** in `cases/` + `registry.py`: nominal regimes, operating
   extremes, acquisition degradations, boundary cases, positive/negative controls, and temporal cases
   where relevant. Define source/seed/site/time-grouped train/val/calibration/test splits before fitting;
   meaningful parametric cases carry at least six variants. Document the matrix in `docs/cases/`.
6. **Pin your engines** in the light, precompute, GPU, and API requirement files as applicable and add a card per engine in
   `docs/frameworks/<NN>_<tool>/` (the deep research, made binding, no toy substitute).
7. **Mirror the contract**: if your trace/manifest shape changed, update `frontend/src/lib/contract.types.ts`
   (a drift fails `tsc`); build the visualizations in `frontend/src/render` + `App.tsx`.
8. **Activate only the lanes you need.** Leave the rest dormant with a README marker ("this solution does not
   require it at the moment"), e.g. `app/` for a static product; `frontend/` for a pipeline-only product.
9. **Verify in separate operations**: setup → sandboxed smoke → tests → explicit canonical bake → artifact
   validation/completeness report → frontend build. CI guards green. Deployment only re-runs artifact
   validation and publishes; it never trains or recomputes canonical inference.
10. **Version** from day 1: `CHANGELOG.md` (`X.XX.XXX`, `0.x` while synthetic) + a tag per release.
11. **Ship the Architecture modal** (ADR-0058, MANDATORY): copy `frontend/src/architecture.ts.txt` to
    `architecture.ts`, specialise the product-specific SVGs (`public/svg/tech/01-the-app.svg`,
    `04-the-science.svg`) + tab copy, pass `architecture` to the `AppShell` config in `main.tsx`, and pin
    `@fasl-work/caos-app-shell` `^0.3.0`. See [guide 05](05_architecture-modal.md). Verified in screenshot-verify.

The base is frozen, you should be editing only the **core** (engine/stages, visualizations, cases/content),
never the structure, contracts, env or deploy. If you find yourself editing the base, that's the smell ADR-0057
exists to remove.
