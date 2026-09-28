# Categorical simulation (SD-6): tasks

| # | Task | Satisfies | Release |
|---|---|---|---|
| 1 | `data/interpretations/alberta-lithology-v1.json` and `stages/categories.py`: the reviewed mapping, the collar surface, depth-grid conditioning with the majority rule and conflicts | R-601 to R-603 | 0.10.000 |
| 2 | `stages/training_images.py`: the two labelled priors from the training holes' cover statistics (clipped at the basement top) and granitoid proportion | R-604, R-614 | 0.10.000 |
| 3 | GeoCond 0.8.0 `zones` for Direct Sampling (the engine release), and the zoned DS in `stages/categorical.py` | R-608, R-609 | geocond 0.08.000; 0.10.000 |
| 4 | `scripts/build_mpslib.sh`, `scripts/build_mpslib.ps1` and `stages/mps.py`: the pinned build with its receipt, the supervised SNESIM run with soft proportions | R-605 to R-607 | 0.10.000 |
| 5 | `stages/categorical.py` in `train`, `infer` and `evaluate` (`--lane`); scores, connectivity, hole connections, persistence | R-610 to R-612 | 0.10.000 |
| 6 | Categorical checks in `scripts/check_artifacts.py`, `scripts/check_simulation.py` (S10 and S11 receipt), the scenario cells A04, A07, A08, S10, S11 | R-613 | 0.10.000 |

## Convergence

- **0.10.000:** R-601 to R-614, each gate passing (tests/test_categorical.py; the MPSlib gates with the pinned build,
  the CUDA gate on the RTX 4070); Alberta passes the artifact check through the categorical evaluate;
  `simulation-checks.json` records S10 and S11 as passed; the scenario matrix has no pending SD-6 cell.
