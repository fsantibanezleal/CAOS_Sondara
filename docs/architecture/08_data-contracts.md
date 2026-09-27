# The data contracts

Data cross four enforced boundaries. Each has a written definition, a checker and tests that prove the checker
rejects what it should.

| Boundary | Contract | Definition | Enforced by |
|---|---|---|---|
| Source files to the pipeline | the sources manifest | `data/sources/manifest.json`: every file by URL or bundled path, byte count and SHA-256, license and attribution | the `acquire` stage refuses any byte or hash difference; each adapter raises on any count drift from the research audits |
| User files to the pipeline | the import manifest `drillhole.import/v1` | `schemas/import.schema.json` (release 0.06.000): roles, dialect, encoding, missing tokens, units, column map, angle convention, namespaces, resolutions | the importer validates the manifest before reading any file and reports every finding by file, role, hole, severity and reason |
| Ingest to the later stages | the canonical project `drillhole.project/v2` | [`schemas/project.schema.json`](../../schemas/project.schema.json) | `scripts/check_artifacts.py`: the schema, then the referential rules |
| Preprocess to the later stages | `drillhole.preprocessed/v1` | [the precompute pipeline](05_precompute-pipeline.md) | `scripts/check_artifacts.py`: the input hash, positions, composite statuses and conservation, populations, overlay |
| Pipeline to the web | the artifact manifest | Arrow and Parquet tables, typed geometry, tiled fields, the model registry and metrics under an immutable manifest (unit SD-8) | planned with the export and validate stages |

## What the contracts refuse

- **Silent repair.** A malformed row, a changed source, a conflicting collar or an overlapping assay series is a
  finding with its location, never a quiet fix. Excluded records stay in the project with the reason.
- **Invented values.** No imputed grade, no half detection limit, no widened point sample, no fabricated collar or
  survey station. A censored result keeps its qualifier and limit and has no value.
- **Blurred states.** A measured zero, a blank, a sample not taken, lost core and a sentinel code are different
  states, and only measured values enter an estimate.
- **Hidden geometry assumptions.** Every trajectory states how it is known and whether it is extended; every frame
  states its datum, or that it is unresolved.

## Where each is defined in the design

The requirements behind these contracts, each with the test that verifies it, are in
[the product design](../design/SDD.md) and [the import and fixtures design](../design/features/import-and-fixtures/).
