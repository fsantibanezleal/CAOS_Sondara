# Classical estimation (SD-5): tasks

| # | Task | Satisfies | Release |
|---|---|---|---|
| 1 | `stages/dataset.py`: hole-group, spatial-margin with buffer, declared holdout; derived tables and memberships | R-501 to R-505 | 0.07.000 |
| 2 | `stages/features.py`: training rows, statistics, cell declustering, GeoCond variograms, orientations | R-506 to R-509 | 0.07.000 |
| 3 | Dataset and features checks in `scripts/check_artifacts.py`; fixture F40 authored | R-504, R-510 | 0.07.000 |
| 4 | `train`: candidate covariances selected on validation, residual covariance, LMC, indicator covariances, normal scores | R-520 to R-522 | 0.08.000 |
| 5 | `estimators` and `infer`: the eight methods on identical targets; S05 to S09; F31 to F37 and F39 | R-523 to R-532 | 0.08.000 |
| 6 | `evaluate`: scores on own and common targets, hole-block paired comparisons, calibration, MIK and SGS scores, receipts; the scenario variants | R-540 to R-545, R-548 | 0.09.000 |
| 7 | `scenarios` and the metric and scenario checks in `scripts/check_artifacts.py` | R-546, R-547 | 0.09.000 |
| 8 | `train`: residual, LMC and indicator covariances with the selected structure; the Gaussian-space covariance selected on validation | R-533, R-534 | 0.09.000 |
| 9 | SGS on GeoCond 0.7.0's two-part search: data with the per-hole cap, 12 simulated nodes apart | R-535 | 0.09.000 |

## Convergence

- **0.07.000:** R-501 to R-510, each gate passing (tests/test_dataset.py, tests/test_features.py).
- **0.08.000:** R-520 to R-532, each gate passing (tests/test_train.py, tests/test_infer.py); fixtures F31 to F37
  and F39 verified; Rocklea and Alberta pass the artifact check through infer.
- **0.09.000:** R-533 to R-535 and R-540 to R-548, each gate passing (tests/test_train.py, tests/test_infer.py,
  tests/test_evaluate.py); Rocklea and Alberta pass the artifact check through evaluate; the scenario matrix has
  no missing cell, and its pending cells name SD-6, SD-7 or SD-8.
