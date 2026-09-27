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
- **Methods:** NN and IDW (`baselines`), SK with the train-only declustered mean, OK, UK with a declared drift, LMC
  cokriging, MIK with the bounded isotonic correction, SGS (32 seeds, convergence at 8, 16, 32), all through GeoCond
  on identical targets and neighbourhoods; failures are statuses, never silent fallbacks.
- **Authored truths:** constant OK, polynomial UK, rigid rotation, zero-cross LMC, invalid PSD and rank, quadrature
  convergence (S05 to S09) and fixtures F31 to F37 and F39.

## 4. Evaluate (0.09.000)

Native-unit bias, MAE, RMSE and error quantiles per method on the common target list, hole-macro and
length-weighted; coverage masks; MIK Brier and log scores against constant train proportions; SGS hard-data honor,
histogram and variogram reproduction; the matched OK comparison for LMC; every method beside the baselines,
including when it does not improve. Receipts carry split IDs, recipes, seeds, engine versions and result hashes.
