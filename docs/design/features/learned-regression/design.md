# Learned regression (SD-7a): design

Unit SD-7, first release (0.11.000): DeepKriging and the Kriging Convolutional Network (KCN) become a third lane of the
`train`, `infer` and `evaluate` stages (`--lane learned`), trained on the same splits as the classical methods,
predicting the same targets, and scored by the same `evaluate` code beside them. The research behind every choice is in
the management repository: the implementation contract of 2026-09-10
(`wip/drillhole-workbench/learned-and-probabilistic-methods-research-2026-09-10.md`) and its verification of
2026-09-28 (`wip/drillhole-workbench/learned-methods-2026-09-28.md`: the audit of the 0.2 modules, the equations
checked in the primary texts, the ONNX export probe, decisions D-1 to D-7). The geochemical autoencoder, its PCA
reference and the R12 spectral-index question follow in SD-7b (0.12.000).

The methods:

- **DeepKriging** (Chen, Li, Reich and Sun, Statistica Sinica 2024, doi:10.5705/ss.202021.0277): the position is
  embedded by Wendland basis functions on nested rectangular knot grids and passed, with the position itself, to a
  dense ReLU regressor.
- **KCN** (Appleby, Liu and Liu, AAAI 2020, doi:10.1609/aaai.v34i04.5716): a query and its K nearest observations
  form a small complete graph weighted by a Gaussian kernel of their distances; two graph-convolution layers and a
  dense readout of the query's row predict its value, with the query's own value hidden.

Both are independent implementations of the published equations; no code from the authors' repositories (which carry
no license) is copied.

## 1. Lane, environment and outputs

The lane needs PyTorch, onnx and ONNX Runtime and runs in `.venv-gpu` (`requirements-gpu.txt`, which includes the
pipeline requirements). It trains on the CUDA device when one is present and on the CPU otherwise, with the same code,
and records the device. `evaluate` reads its predictions and needs no PyTorch. `--lane all` runs every lane and stops
with a message when PyTorch is missing; `scripts/precompute.sh` and `.ps1` use `.venv-gpu` when it exists.

| Stage | Writes | Holds |
|---|---|---|
| `train --lane learned` | `learned-models.json`, `learned/fits/...` | the frozen search, every configuration's three fits (best epoch, history, validation objective, weights file hash), the selection, the controls, the fitted transforms, input hashes |
| `infer --lane learned` | `learned-predictions.json`, `learned/exports/...` | per population and method, a row per test and calibration target in the classical row schema plus the seed predictions and spread; the ONNX exports with their manifests and parity records |
| `evaluate` | `metrics.json` (learned methods beside the classical ones) | the classical scores on the same targets, the paired comparison with OK, the residual band, the seeds, the controls |

Fits are checkpoints: `learned/fits/<scheme>/<population>/<method>/<configuration>/seed-<n>/` holds `fit.json` and
`weights.pt` (tensors only, loaded with `weights_only=True`), and an interrupted fit resumes from `resume.pt` (saved
every 20 epochs) when its recipe hash matches. A rerun reuses every finished fit whose recipe hash matches and refuses
one whose recipe differs. Python pickles are never an import format.

## 2. Shared rules

- **Split, rows and targets (D-1).** The lane iterates the populations of `features.json` with the target rule of the
  classical `train` (the population's analyte, else the family's primary analyte) and loads rows with
  `stages/train._split_rows`: training rows fit, validation rows select, calibration and test rows are predicted. The
  targets are exactly the classical lane's (`predictions.json`); `evaluate` refuses learned predictions whose target
  lists or dataset hash differ. A population with fewer than three training holes is not eligible, with the reason.
- **Target scaling.** $\hat{z} = \mu_{train} + s_{train} f_\theta(\cdot)$ with the training mean and standard deviation
  (population, ddof 0). A constant training target is predicted as that constant without a fit, with the status
  `estimated` and the reason recorded.
- **Frozen search, seeds, selection.** Each method has a fixed candidate list (sections 3 and 4). Every configuration
  is fitted with seeds 20260910, 20260911 and 20260912: AdamW (learning rate 0.001, weight decay 0.0001), batch 128,
  at most 400 epochs, early stopping after 40 epochs without a better validation objective, the weights of the best
  epoch kept. The validation objective is the hole-macro RMSE in native units (the mean over validation holes of each
  hole's RMSE). A configuration is selected by the mean of its three seeds' objectives; ties go to fewer parameters,
  then to the declaration order. TF32 is disabled on the device; CPU threads are a recorded setting.
- **Ensemble.** The published prediction is the mean of the selected configuration's three seed predictions. Their
  standard deviation is published as model-fit spread; it is not a predictive variance, and the `variance` field stays
  empty.
- **Residual band.** The 95th percentile of the absolute residuals of the ensemble on the calibration rows gives a
  band radius, and `evaluate` reports the band's coverage of the test truths. The band assumes exchangeability between
  calibration and test holes, which a spatial split does not guarantee; its test coverage is what shows it.
- **Controls.** For each method the selected configuration is also fitted (three seeds) on the training targets
  permuted among the training rows (seed 20260926): a model that learned the spatial signal must beat it on the
  validation and test rows; at inference the KCN control receives the same permuted neighbour values it was trained
  on. For DeepKriging, the selected widths are also fitted on the position alone, without the basis (the
  coordinate-only ablation). Both are reported, never published as predictions.
- **What a prediction row carries.** `id`, `method`, `status` (`estimated`, or `uninformed` with the reason),
  `mean` (the ensemble), `variance` (null), `seeds` (the three predictions), `spread`, and, per method, the support
  diagnostics: DeepKriging's distance to the nearest training row and whether the position lies outside the training
  box; KCN's neighbour count, distinct holes and nearest neighbour distance.

## 3. DeepKriging

**Positions.** The origin and the per-axis scale are the training rows' minimum and extent; an axis with zero extent
keeps a scale of one metre and a constant normalized coordinate (the contract of 2026-09-10). The model's input is the
position minus the origin, in metres: the subtraction is done in float64 before the cast to float32, so projected
coordinates of millions of metres lose nothing, and the exported graph receives the same local coordinates. Positions
outside the training box are not clipped; the row records that it lies outside.

**Basis.** For a knot level with $n$ knots per axis on $[0,1]^3$, the knot spacing is $1/(n-1)$ and the radius
$\theta = 2.5/(n-1)$ (the paper: "2.5 times the associated knots spacing"). For a normalized position $\mathbf{u}$ and
knot $\mathbf{c}_j$, $r_j = \lVert \mathbf{u} - \mathbf{c}_j \rVert / \theta$ and

$$\phi(r) = \frac{(1-r)^6 (35 r^2 + 18 r + 3)}{3} \quad (0 \le r \le 1), \qquad \phi(r) = 0 \quad (r > 1).$$

Columns that are zero on every training row are removed, and the retained knots are recorded. The graph computes the
basis itself in float32, so the exported model takes positions; a float64 NumPy oracle (`learned/features.py`)
computes the same basis independently for the tests (they agree within about $10^{-6}$).

**Network.** $f_\theta([\mathbf{u}, \phi_1(\mathbf{u}), \ldots, \phi_m(\mathbf{u})])$: dense ReLU layers with dropout,
then a linear unit; the native value is $\mu_{train} + s_{train} f_\theta$.

**Candidates** (2 x 2 x 2 = 8 configurations, 24 fits per population):

| Setting | Values | Why |
|---|---|---|
| Knot levels per axis | {3, 5, 9} (27 + 125 + 729 = 881 candidate columns) or {10, 19} (1,000 + 6,859 = 7,859) | the contract's compact levels; the paper's first two levels, $K_h = (9 \cdot 2^{h-1}+1)^d$ |
| Widths | [64, 64, 32] or [128, 64, 32] | the contract |
| Dropout | 0 or 0.1 | the contract |

The paper's own network (100-unit layers, dropout 0.5, batch normalization, Adam) is not reproduced, and the paper's
accuracy is not claimed.

## 4. KCN

**Neighbours.** For a query, the conditioning rows are the training rows, searched by distance in metres (the metric
of the classical plan), in a stable order (distance, then row id). Rows from the query's own hole are excluded, at
most 4 rows are taken from one hole, and at least 2 distinct holes are required; a query that cannot meet that is
`uninformed` with the reason. During training every training row is a query and its neighbours come from the other
training holes, which is stricter than the paper's hiding of the query's own label and matches the whole-hole
prediction the split asks for.

**Scale.** $\bar{d}$ is the median, over the training queries, of the distances to their selected neighbours (per K).
Positions enter the graph relative to the query, in metres.

**Graph (the paper's eqs. 9 and 3).** Over the query and its neighbours,
$A_{jk} = \exp\left(-\lVert \mathbf{s}_j - \mathbf{s}_k \rVert^2 / (2\phi^2)\right)$ for every pair including
$j = k$, then $\bar{A} = D^{-1/2}(A+I)D^{-1/2}$ with $D = \mathrm{diag}(A\mathbf{1} + \mathbf{1})$: each node's self
weight is 2 before normalization. Padding rows (a query with fewer than K neighbours) are masked out of $A$, of the
degrees and of the messages. The 2026-09-10 contract zeroed the diagonal before adding one self-loop; the product
follows the paper.

**Node features (the paper's eq. 10, adapted).** Row 0 is the query: value 0, known flag 0, query indicator 1.
Neighbour rows: the standardized value, known flag 1, indicator 0. Every row adds its position relative to the query
over $\bar{d}$, its support length over the training rows' median length, and its trajectory kind (measured or
assumed). No row id, hole id or held-out value enters a feature.

**Network (eqs. 4 to 6, 11 and 12).** $H^\ell = \mathrm{ReLU}(\bar{A} H^{\ell-1} W^\ell + b^\ell)$ for two layers,
masked to the valid rows, and $\hat{y} = \mathbf{e}^\top H^2 \mathbf{w} + b$, the query's row read out by a linear
unit (regression, so no output nonlinearity).

**Candidates** (2 x 2 x 3 = 12 configurations, 36 fits per population):

| Setting | Values |
|---|---|
| Neighbours K | 16 or 32 |
| Hidden width | 32 or 64 |
| Kernel length $\phi$ | 0.5, 1 or 2 times $\bar{d}$ |

The graph is built inside the model from the raw inputs (relative positions in metres, native values, known flags,
lengths, trajectory kinds, validity), so the exported model applies eqs. 9 and 3 itself and a browser only has to
select the neighbours.

## 5. Export and parity

Every seed of the selected configuration of each method and population is exported as one ONNX file:

- through the torch.export exporter at opset 18 (the TorchScript exporter is marked for removal in torch 2.14), with
  the exporter's console output captured (on a Windows cp1252 console its log fails to print);
- every metadata field removed (the exporter stores each node's Python stack trace, with local paths), and the audit of
  0.2 applied: standard domain, no control flow (`Loop`, `Scan`, `If`, `SequenceMap`), no external data, at most 2,000
  nodes and 8 MiB;
- with a manifest binding it to the family, scheme, population, analyte and unit, the input and output names and
  shapes, the feature schema, the fitted transforms (origin, scales, knots, $\bar{d}$, $\phi$, mean and scale), the
  training row ids' hash, the model hash and the parity record;
- parity on the same checkpoint over every test and calibration input: ONNX Runtime on the CPU and PyTorch on CUDA
  (when present) against PyTorch on the CPU, within $10^{-4}$ times the training standard deviation in native units
  (the probe of 2026-09-28 measured about $10^{-6}$ in standardized units); the first 64 inputs and outputs are kept
  as a fixture for the browser lane (SD-9).

`learned/exporting.validate_portable` refuses an archive with other files, a hash mismatch, a non-standard or
control-flow graph, or external tensors, and `contracts.check_binding` refuses a model for another project, frame,
task or unit: a matching architecture is never a reason to reuse a fit elsewhere.

## 6. Evaluation

`evaluate` adds `deepkriging` and `kcn` to each population's `methods` in `metrics.json` with the classical fields:
coverage and statuses, the share outside the training range, the scores on their own targets and on the classical
common targets (the targets every classical continuous method predicted, unchanged, with the count a learned method
missed), and the paired comparison with ordinary kriging (95 % hole-block bootstrap). Learned-only fields: each
seed's scores, the spread summary, the residual band (radius from the calibration rows, coverage on the test rows),
the two controls, the selected configuration, the training device and time. Each population also gets a constant
reference, `trainingMeanReference`: every test target predicted by the training mean, scored on the same targets and
paired with OK, because a model that stops near its initial weights predicts close to that constant. The scenario
matrix marks R10 and R11's DeepKriging and KCN cells computed from those entries.

## 7. What it does not claim

A learned prediction is the fitted function's value at the support centre (the interval-centre or envelope-centre
approximation), not a block grade. The seed spread is not a predictive variance, and the residual band is empirical.
A model is bound to the project it was fitted on. Alberta's 13 training holes give weak evidence. Nothing here claims
that a learned method is better than kriging unless the paired comparison on the same targets says so, and then only
for those holes.
