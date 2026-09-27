# Changelog

All notable changes to this product. Format: `X.XX.XXX` (display) in `VERSION`, `vX.XX.XXX` as the tag,
semver in `frontend/package.json`. Keep `0.x` until the web product runs on the field families. Tag every
release.

## [0.05.000], 2026-09-26

### Added
- The design document the product lacked (ADR-0075): `docs/design/SDD.md` with the problem, non-goals, contracts,
  lanes, method acceptance criteria, cases, oracle, deploy driver, risks and 18 requirements in force, each naming the
  test or guard that verifies it; the feature design of unit SD-4 in `docs/design/features/import-and-fixtures/`, with
  the 5 contract requirements of this release;
  `scripts/check_sdd.py` in the CI guards.
- Tests for two requirements that had none: `acquire` refuses a changed source, and `preprocess` refuses a project
  that does not match its ingest summary.

### Changed
- The canonical contract is `drillhole.project/v2`, and `schemas/project.schema.json`, which had drifted from what the
  adapters wrote, is now its one normative definition. The artifact check validates it with `jsonschema` before the
  referential rules. Changes: determination `state` (measured, censored-below, censored-above, missing, not-sampled,
  lost-core, sentinel) and `sampleRole`; survey `id`, `azimuthReference`, `instrument` and the roles
  `recorded-collar-direction`, `measured`, `compiled-extension`; trajectory `startExtension` and `endExtension`;
  collar `namespace` and `orientation.sourceInclination`; support `sampleId`; geology `codes` verbatim under their
  source column names and events at `atMd`; new `qc` and `exclusions` tables.
- The three adapters and the preprocess stage write and read v2; the desurvey takes its extension policies from the
  project, uses only recorded collar directions and measurements as stations, and accepts a first station below the
  collar only under a declared start extension. All audit figures are unchanged.
- `docs/architecture/08_data-contracts.md` describes Sondara's contracts instead of the template's example.

## [0.04.000], 2026-09-26

### Added
- The `preprocess` stage (units SD-2 and SD-3 of the plan, delivered together because the stage is shared), on
  GeoCond 0.6.1:
  - Every hole desurveyed by minimum curvature from what its source supports (assumed vertical, recorded collar
    direction, or the recorded collar direction and the measured stations), with a declared tangent extension to total
    depth; every support positioned on the arc.
  - Rocklea composites at 1, 2 and 5 m per hole, anchored at the first sampled depth, with minimum coverage 1 and
    labelled residuals: 5,035, 2,469 and 937 full composites; the 1 m composites reproduce the native intervals
    exactly and every grade-length integral is conserved per hole.
  - The Alberta log overlay, reproducing the research audit: 173, 51 and 36 of 176 envelopes fully covered by any log,
    a known `Litho_unit` and a known `Rock_type` (1,960.1, 285.6 and 207.4 m covered).
  - NTGS 12LE002: largest dogleg 1.5014 degrees and a 9.57 m departure from the collar direction, as in the audit; 50
    sampling gaps, 3 repeated supports and the censoring table.
  - Modeling populations with members, support, rule and excluded counts, including the empty NTGS estimation
    population and its reason.
- `scripts/check_artifacts.py` validates the preprocessed output against its project; tests cover authored cases with
  exact answers, the three families against the dossier gates and each rejected corruption.
- `scripts/figures/preprocess_figures.py` and three figures in `docs/assets/`; a preprocessing section on each case
  page; the GeoCond framework card.
- The MIT `LICENSE` the product lacked.

### Changed
- The README describes the current release and how to run the pipeline.

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
