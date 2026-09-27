# Canonical contract, manifest importer and fixtures (SD-4): tasks

| # | Task | Satisfies | Depends on |
|---|---|---|---|
| 1 | Reconcile `schemas/project.schema.json` to v2 | R-401 | |
| 2 | Move the three adapters and `common.py` to v2 (states, roles, instruments, extensions, codes, sample IDs, qc, exclusions) | R-401, R-403, R-404, R-405 | 1 |
| 3 | Validate the schema and the new referential rules in `scripts/check_artifacts.py`; pin `jsonschema` | R-402 | 1 |
| 4 | Move the preprocess stage to v2 roles and extension fields | R-404 | 2 |
| 5 | Contract tests; update the ingest and preprocess tests; release 0.05.000 | R-401 to R-405 | 2, 3, 4 |
| 6 | `schemas/import.schema.json` and manifest validation | R-419 | 5 |
| 7 | Dialect reading, header and row integrity, file hashes and duplicate files | R-421, R-427, R-428 | 6 |
| 8 | Identity: namespaces, aliases, normalization collisions | R-423, R-426 | 7 |
| 9 | Frame checks, collars and conflicts with resolutions | R-422, R-430 | 8 |
| 10 | Surveys: units, dip conventions, duplicate depths, missing and truncated surveys | R-429, R-432, R-433, R-434 | 9 |
| 11 | Assays: samples, states, controls, repeats, invalid intervals, orphans, overlaps | R-425, R-435, R-436, R-437, R-440, R-443 | 9 |
| 12 | Lithology; the decision (accepted, rejected, pending); the staged atomic commit with cancellation | R-424, R-445 | 10, 11 |
| 13 | Preprocess: result selection, eligibility v1, overlay fragments, compositing parameters, extension ranges | R-431, R-434, R-438, R-439, R-440, R-441, R-442, R-444 | 12 |
| 14 | Fixtures F01 to F42 authored with expected outcomes; the fixture and scenario registries | R-420, R-460, R-461, R-462 | 13 |
| 15 | Docs: data contracts page, bring-your-own-data guide, fixture catalogue; release 0.06.000 | all | 14 |

## Convergence

- **0.05.000:** R-401 to R-405, each gate passing (tests/test_contract.py, tests/test_ingest.py).
- **0.06.000:** R-419 to R-445 and R-460 to R-462, each gate passing (tests/test_import.py,
  tests/test_fixtures.py); 52 tests in the suite; `scripts/check_sdd.py` confirms every named gate exists.
- **Not yet met:** fixtures F31 to F40 and F42 are verified by the infer, features, dataset and export stages
  (units SD-5 to SD-8); the registry test fails when one of those stages is built without them.
