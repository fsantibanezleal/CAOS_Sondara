# Classical estimation (SD-5): design

Unit SD-5 builds the stages between the preprocessed families and the evaluated classical methods: `dataset`,
`features`, `train`, `infer` and `evaluate`, for NN, IDW, SK, OK, UK, LMC cokriging, MIK and SGS, on GeoCond. It
ships in three releases: splits and features (0.07.000); fitting and inference with the authored truths and fixtures
F31 to F37 and F39 (0.08.000); the evaluated field scenario matrix (0.09.000). The rules come from the methods
dossier (independent validation and comparison program), the learned and probabilistic methods dossier (shared
prediction task, SK, MIK, SGS) and the content contract (domain limitations as operational rules).

## 1. Dataset (`stages/dataset.py`)

The split is built before any target-dependent transform or fit, once per family, and frozen.

| Scheme | Assignment | Why |
|---|---|---|
| `hole-group` | holes sorted by ID, permuted by `numpy.random.Generator(PCG64(seed))`, cut 60/15/10/15 into train, validation, calibration and test by largest remainder | the default undrilled-hole task; random intervals from one hole would answer an easier interpolation question |
| `spatial-margin` | test = the 15 % of holes whose collars lie farthest from the collar centroid (ties by ID); training excludes holes within the buffer (1.5 median nearest-neighbour collar distances, which on a regular grid is the first ring of neighbours, diagonals included) of any test hole, and reports them; the rest cut 60/15/10 as above | prediction into less-drilled margins, with a buffer so neighbouring holes do not leak the answer |
| `declared` | the holes a user or fixture names are test; the rest as `hole-group` | a reproducible, reviewable holdout |

Every population member (sample, repeat, composite, fragment) inherits its hole's split, so no derivative of a
held-out hole can train. A family with one hole (NTGS) has no split and is recorded as not eligible, with the reason.
Output `dataset.json` (`drillhole.dataset/v1`): input hashes, schemes with seeds, proportions, hole assignments,
buffer exclusions and the membership of every population.

## 2. Features (`stages/features.py`)

The stage receives only the training members of each split and never opens validation or test values; a test
changes those values and requires identical features.

- **Coordinates:** support centres (interval and composite mid positions, envelope centres), in the family frame.
- **Statistics:** count, mean, variance, extremes, and the cell-declustered mean with its cell size (the median
  nearest-neighbour collar distance horizontally, the support length vertically). On a regular grid the declustered
  and plain means coincide.
- **Variograms (GeoCond):** downhole (pairs within one hole, measured-depth separation, lag = support length) and
  spatial (omnidirectional, horizontal azimuths 0, 45, 90 and 135 degrees with 22.5 degree tolerance and a bandwidth
  of twice the collar spacing, and vertical), lag = half the median collar spacing, each with its pair counts, mean
  separations, sampling flag and seed; cross variograms for declared variable sets (Rocklea Fe with SiO2 and Al2O3,
  Alberta Cu with Zn).
- **Orientation (F38):** declared orientation measurements become plane normals; the principal direction is the
  largest eigenvector of their orientation tensor, and when the two largest eigenvalues are within the declared ratio
  (1.2) the orientation is `undefined`, never averaged into a spurious direction.

Output `features.json` (`drillhole.features/v1`) per family, scheme, population and analyte.

## 3. Train and infer (0.08.000)

- **Fitting:** variogram models by GeoCond `fit_variogram` on the training variograms (nested families, bounded,
  deterministic starts); LMC by `fit_lmc` (B = L L^T); indicator covariances per threshold (train-only weighted
  deciles); normal-score tables with recorded tails. Model selection sees validation only.
- **One structure for the estimators, its own for SGS (0.09.000):** the residual, LMC and indicator covariances are
  fitted with the families and frame selected for ordinary kriging, on the four horizontal and the vertical
  variograms of their own values (R-533). The Gaussian-space covariance is chosen among the twelve anisotropic
  candidates (four frames, three family sets) fitted on the normal scores' horizontal and vertical variograms, by the
  validation RMSE of simple kriging of the normal scores (R-534): the realizations must reproduce continuity along the
  holes, which an omnidirectional fit on lags of half the collar spacing cannot see, and ordinary kriging's single
  structure, forced on the normal scores, cut the correlation between holes.
- **Methods:** NN and IDW (`baselines`), SK with the train-only declustered mean, OK, UK with a declared drift, LMC
  cokriging, MIK with the bounded isotonic correction, SGS (32 seeds, convergence at 8, 16, 32), all through GeoCond
  on identical targets and neighbourhoods; failures are statuses, never silent fallbacks. SGS searches the data (the
  shared plan, at most 6 per hole) and 12 previously simulated nodes apart, GeoCond 0.7.0's two-part search after
  GSLIB (R-535), so dense nodes along a held-out hole cannot crowd the other holes out of the system.
- **Authored truths:** constant OK, polynomial UK, rigid rotation, zero-cross LMC, invalid PSD and rank, quadrature
  convergence (S05 to S09) and fixtures F31 to F37 and F39.

## 4. Evaluate (0.09.000)

Truth values are read here and nowhere earlier (`stages/evaluate.py`, output `metrics.json`,
`drillhole.metrics/v1`). For each family, scheme and population:

| Measure | Definition | Why |
|---|---|---|
| Scores on own and common targets | bias, MAE, RMSE, the 50 % and 90 % absolute-error quantiles, length-weighted bias, MAE and RMSE, and the hole-macro RMSE (the mean of per-hole RMSEs), in native units, on the targets each method predicted and on the common list every continuous method predicted | a method that declines hard targets must not look better by declining them; one long hole must not dominate |
| Paired comparison with OK | the mean absolute-error difference on the targets both methods predicted, with a 95 % interval from 1000 bootstrap draws of holes (seed 20260926) | errors within a hole are correlated; resampling rows would overstate the evidence |
| Variance calibration | a variance scale `s = mean(z^2)` from the calibration holes' z-scores, applied to the test rows: z mean and variance, 95 % coverage before and after | the kriging variance is conditional on the fitted covariance; it is checked, not believed |
| MIK probability scores | per threshold, Brier and log scores (log floor 1e-3) against the constant training proportion, and the Brier skill | a probability forecast is judged against the climatology it must beat |
| SGS ensemble | fair CRPS of the 32 realizations, the coverage of the 10 to 90 % interval, and the reproduction of the truths' histogram and downhole variogram beside OK | simulation is for variability; OK is expected to smooth it |
| Training range | the count and fraction of estimates outside the training range, and the extremes | extrapolation (UK's local drift at the margins) is reported, not hidden |

The fair CRPS of an m-member ensemble is `mean|X_i - y| - sum_{i,j}|X_i - X_j| / (2 m (m - 1))`, unbiased for the
CRPS of the distribution the members sample; the plain ensemble CRPS overstates it by `E|X - X'| / (2 m)`, which
would penalize a small ensemble for its size. The downhole variogram is computed on pairs of test targets in one
hole, binned at one to five lags of the median support length (or the median spacing of consecutive targets for
point supports).

A receipt records the split seeds and proportions, the neighbourhood plan, the engine versions of fit, infer and
evaluate, the hashes of the dataset, models and predictions, and the hash of the scored result.

**Variants.** On Rocklea's hole-group 1 m population, `infer` also predicts the test targets with ordinary kriging
under a small (8 samples, 3 per hole) and a large (64 samples, no cap) neighbourhood (R06), the best isotropic
candidate (R05), observations and targets integrated over their sample intervals with 4-point Gauss-Legendre
quadrature (R07), and ordinary cokriging with the secondaries measured on the test samples available (R09).

## 5. The scenario matrix (0.09.000)

`stages/scenarios.py` resolves each registered scenario (R01 to R12, A01 to A08, S01 to S12) to cells: a method or
variant scored in a family's metrics (computed, citing the metrics by hash), a stage output the scenario reads
(computed when present), a test that verifies an authored truth (verified when the test exists), or a pending cell
naming the unit that will compute it (SD-6 categorical simulation, SD-7 learned methods, SD-8 export). A scenario is
complete, partial or pending from its cells. `evaluate` rebuilds `scenarios.json` after every family, and the
artifact check fails on a missing cell, a pending cell without an owner, or a computed cell whose metrics changed.
