# Framework card, GeoCond

## What and why

[GeoCond](https://github.com/fsantibanezleal/GeoCond) is the separate, published package that holds every reusable
spatial-conditioning method Sondara uses: minimum-curvature geometry, known sampling supports and quadrature,
conservative compositing, nested covariance and the linear model of coregionalization, experimental variograms and
their fitting, simple, ordinary and universal kriging and cokriging on support-integrated covariance, indicator
probabilities, sequential Gaussian simulation and Direct Sampling, with float64 CUDA lanes for the heavy parts.

The package boundary was set by the research of 2026-09-10. None of the audited libraries supplies the generic coupled
covariance and support boundary the product needs: OreBlocks, GeoScena, PyGeoTypes and CoreLog serve other purposes,
and GSTools and PyKrige serve as references rather than the engine. The same research put source acquisition, joins,
geologic mapping, frame interpretation, splits, learned models, SNESIM supervision and the web lifecycle on Sondara's
side, as plain scripts. Sondara never re-implements a GeoCond method; it decides what goes into one.

## Install (exact, verified)

`geocond==0.6.2` is pinned in `data-pipeline/requirements.txt` and installs from PyPI into `.venv-pipeline` with NumPy
and SciPy only. The optional `cuda` extra (`torch>=2.9,<3`) is needed only by the CUDA lanes, which the preprocess
stage does not use.

## Usage

```python
from geocond.geometry import Survey
from geocond.compositing import composite_intervals, fixed_boundaries

survey = Survey([0.0, 0.0, 500.0], [0.0], [0.0], [-90.0], end_extension="tangent")  # assumed vertical
survey.at([10.0]).points          # [[0, 0, 490]]
composite_intervals([0, 1], [1, 3], [2.0, 5.0], fixed_boundaries(0, 3, 2), min_coverage=1.0)
```

## Applying it here

| Stage | GeoCond modules | Inputs | Outputs |
|---|---|---|---|
| `preprocess` (0.04.000) | `geometry`, `compositing` | collars, survey stations, supports, determinations, logged geology | positions on the arc, composites with coverage and parents, category proportions |
| `features` (0.07.000) | `variogram` | training rows of each split | experimental direct and cross variograms |
| `train`, `infer` (0.08.000) | `variogram`, `covariance`, `kriging`, `neighborhood`, `baselines`, `probability`, `simulation` | training variograms and rows, validation rows, test targets | fitted and selected models, estimates with diagnostics, indicator probabilities, realizations |
| SD-6, SD-7 (planned) | `direct_sampling`, `cuda` | categorical rows and training images; CUDA lanes | realizations, CPU and CUDA parity |

The contracts, equations and the tests against independent references (R/gstat, PyKrige, GSTools, welleng,
scikit-learn) are in GeoCond's [methods pages](https://github.com/fsantibanezleal/GeoCond/tree/main/docs/methods).

## Caveats and license

GeoCond refuses what it cannot do honestly: overlapping source intervals, sampling envelopes with unknown weights,
antiparallel survey tangents and depths beyond the last station without a declared extension are errors, not guesses.
Sondara's stage records its policy for each case before the call. GeoCond is licensed under Apache-2.0.
