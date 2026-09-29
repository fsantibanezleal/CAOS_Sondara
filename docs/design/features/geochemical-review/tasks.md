# Geochemical review and the spectral-index lineage (SD-7b): tasks

| # | Task | Satisfies | Release |
|---|---|---|---|
| 1 | Pin the four lineage files in `data/sources/manifest.json`; `acquire` fetches them with their hashes | R-718 | 0.12.000 |
| 2 | `stages/spectral.py`: the product table from the descriptions workbook, the embedded-assay identity, the per-hole registration, the calibrated-channel record; `spectral-lineage.json` from `features` (Rocklea) | R-719 to R-721 | 0.12.000 |
| 3 | The iron-oxide index check: isotonic calibration on confirmed training rows, scored on confirmed test rows beside OK | R-722 | 0.12.000 |
| 4 | `learned/features.py` and `learned/evaluation.py`: the geochemical transform and the corrected alterations (audit L-3) | R-723, R-725 | 0.12.000 |
| 5 | `stages/geochemistry.py`: the autoencoder search with three seeds, the PCA reference, the review threshold, the alteration scores, the ONNX export with parity; in `train`, `infer` and `evaluate` (the learned lane) | R-724, R-726, R-727 | 0.12.000 |
| 6 | R12's cells in the scenario matrix, artifact checks, docs (architecture 06, the Rocklea case, the spectral lineage page), release | all | 0.12.000 |

## Convergence

- **0.12.000:** R-718 to R-727, each gate passing in `.venv-gpu`; the Rocklea run records the lineage, the index
  check and the review; the scenario matrix has no pending SD-7 cell. The `Status: planned` line is then removed.
