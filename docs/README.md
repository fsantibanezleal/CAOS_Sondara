# Docs, the product wiki

SimLab-style navigable wiki (ADR-0056), authored **as the product is built**, not at the end. The pipeline +
its validation + these docs are the primary product; the web app is a projection of a validated subset.

## Map
- **[architecture/](architecture/)**, how the repo works: the frozen base, the two data contracts, determinism +
  trace, the live/precompute gate, the staged pipeline, model evaluation, deploy.
- **[frameworks/](frameworks/)**, one card per research-chosen engine/library (what/why · install · usage ·
  applying). The deep research, made binding (each is pinned in a `requirements-*.txt`).
- **[guides/](guides/)**, runnable how-tos: run the precompute pipeline, **bring your own data**, the GPU lane,
  run the API.
- **[cases/](cases/)**, the CATEGORY taxonomy + the coverage matrix + one page per documented case.

## Honesty + data policy
- Numbers come from the pipeline's outputs, never from a claim: the field families are real public data with
  their sources and licenses in `data/sources/manifest.json`, and the fixtures are authored and labelled as such.
- Public derived artifacts are committed (`data/derived/`); raw/private sources stay out of git (`data/raw/`,
  vault) per ADR-0055. The two data contracts ([architecture/08_data-contracts.md](architecture/08_data-contracts.md))
  govern raw→pipeline and pipeline→web.
