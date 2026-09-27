# Classical estimation (SD-5): tasks

| # | Task | Satisfies | Release |
|---|---|---|---|
| 1 | `stages/dataset.py`: hole-group, spatial-margin with buffer, declared holdout; derived tables and memberships | R-501 to R-505 | 0.07.000 |
| 2 | `stages/features.py`: training rows, statistics, cell declustering, GeoCond variograms, orientations | R-506 to R-509 | 0.07.000 |
| 3 | Dataset and features checks in `scripts/check_artifacts.py`; fixture F40 authored | R-504, R-510 | 0.07.000 |
| 4 | `train`: variogram and LMC fitting, indicator covariances, normal-score tables; model selection on validation | to be written with 0.08.000 | 0.08.000 |
| 5 | `infer`: NN, IDW, SK, OK, UK, LMC, MIK, SGS on identical targets; S05 to S09; F31 to F37 and F39 | to be written with 0.08.000 | 0.08.000 |
| 6 | `evaluate` and the field scenario matrix with receipts | to be written with 0.09.000 | 0.09.000 |

## Convergence

- **0.07.000:** R-501 to R-510, each gate passing (tests/test_dataset.py, tests/test_features.py).
