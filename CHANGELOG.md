# Changelog

All notable changes to this product. Format: `X.XX.XXX` (display), see `pipeline.__version__`. Keep `0.x`
while on mock/synthetic data. Tag every release.

## [0.02.001], 2026-09-26

### Fixed
- Every version source names the same release: `VERSION` had stayed at `0.01.000` while the
  releases of 2026-09-12 were tagged in the semver form (`v0.1.1`, `v0.1.2`, `v0.2.0`) and
  `frontend/package.json` moved to `0.2.0`. From here the display form is `X.XX.XXX`, the tag
  `vX.XX.XXX`, and the manifest carries the PEP 440 form.
- No em-dash in the files the content guard does not scan.

### Housekeeping
- `task/drillhole-workbench` (2026-09-10) deleted: `main` carries its workbench and more; its only
  extra lines were an older CI. The SIR example lane of the product template, which sat untracked in
  the working tree, is removed; the template-residue guard forbids it.

## [0.02.000], 2026-09-12 (tagged `v0.2.0`)

- Merge of develop (#11) after the connected local estimation workbench (`v0.1.1`, #8) and the
  deterministic source fixtures (`v0.1.2`, #9). Reconstructed from the release pull requests; no
  entry was written at the time.

## [0.01.000], 2026-06-20

### Added
- Initial instantiation from the CAOS product-repo template (ADR-0057).
- Offline `data-pipeline/` (`pipeline`): the two data contracts (ingestion + artifact), the named staged
  pipeline (preprocess → feature_extraction → train → infer → evaluate → export), the seeded RNG, the compact
  trace, the manifest, and the measured live-vs-precompute gate.
- EXAMPLE engine: a deterministic SIR epidemic (numpy-only, Pyodide-safe), **replace with the product's
  research-chosen SOTA engine**.
- Cases-by-category registry (4 regimes + 1 degenerate control); a live-lane entrypoint (`live.py`); tests for
  both contracts + pipeline determinism.
