# Changelog

All notable changes to this product. Format: `X.XX.XXX` (display) in `VERSION`, `vX.XX.XXX` as the tag,
semver in `frontend/package.json`. Keep `0.x` until the web product runs on the field families. Tag every
release.

## [0.03.000], 2026-09-26

### Added
- `acquire` and `ingest`, the first two stages of the offline lane (unit SD-1), for the three field families of the
  research dossiers. `data/sources/manifest.json` pins every source by URL or bundled path, byte count and SHA-256,
  with its license and attribution.
- Rocklea Dome (CSIRO, CC BY 4.0): 17,474 workbook intervals reconcile to 7,240 with a unique source collar, then to
  5,035 one-metre intervals in 158 assumed-vertical holes once the 2,205 all-analyte-zero rows are quarantined. Eleven
  analytes; the Fe and FeO naming difference and the four all-zero columns are issues, not conversions.
- Alberta MAR_19860002 (AGS DIG 2024-0022, OGL-Alberta): 22 collars with recorded directions, 150 logged geology
  records, 342 Cu/Zn samples kept as 176 sampling envelopes with unknown weights, 162 point depths and 4 unknown
  supports, with 9,612 determinations under their raw tokens.
- NTGS 12LE002 (CC BY 4.0), bundled as a hashed subset: one hole in a local frame anchored at the source collar, 13
  survey records of which 11 are measurements, and 1,892 determinations with the 850 below-detection results kept as
  qualifier and limit, never as negative grades.
- `scripts/check_artifacts.py` validates every ingested project against the `drillhole.project/v1` contract (identity,
  references, support geometry, censoring, finite values, issue rows, summary hash and counts); the tests prove it
  rejects each corruption.
- Case pages for the three families in `docs/cases/`, with sources, decisions and limits.

### Changed
- The template's demo stage and its authored three-hole project are gone from the pipeline; the smoke check now
  validates the ingested families. The web page still shows the 0.2 demo cases until the web unit (SD-9).
- Pinned lanes: `openpyxl`, `numpy` and `scipy` in the offline lane; `ruff` 0.16.6 in the dev lane. The frontend
  package is named `sondara-frontend`.

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
