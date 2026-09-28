# Categorical simulation (SD-6): design

Unit SD-6 adds the categorical lane: a reviewed lithology mapping, a 3D grid in depth conditioned by the logged
intervals, two labelled training images, SNESIM (MPSlib, a supervised compiled subprocess) and Direct Sampling
(GeoCond), and their evaluation on held-out holes. It serves scenarios A04, A07 and A08 on the Alberta family and the
authored checks S10 and S11. Only Alberta has logged lithology: Rocklea has no geology and NTGS is one hole, and both
record the lane as not applicable. The research behind every choice is in the management repository
(`wip/drillhole-workbench/categorical-simulation-2026-09-27.md`), with the methods dossier of 2026-09-10.

The Alberta holes are Uranerz's Maybelle River project (report MAR_19860002, 1986), western Athabasca Basin: glacial
drift over patchy Middle Devonian dolomites and sandstones, the Athabasca Group (Manitou Falls and Fair Point
formations, 0 to 122 m and 0 to 39 m in the project's drilling), an unconformity, and a basement of granite gneisses,
metasediments and anatectic granitoids.

The lane runs inside the existing stages and writes its own outputs, so the continuous chain is untouched: `train`
writes `categorical-models.json` with the conditioning and the training images, `infer` writes
`categorical-predictions.json` and the realizations, `evaluate` adds a `categorical` section to `metrics.json`.

## 1. The reviewed mapping (A04)

`data/interpretations/<project>-lithology-v1.json` declares the modeling categories and the rules that assign a
logged interval to one of them, in order of precedence: source codes (`Litho_unit`, `Rock_type`), the unit named at
the start of the description ("Unit: Devonian"), and position rules for the few codes whose meaning depends on where
they sit (a conglomerate directly above the basement is the basal Athabasca conglomerate; a dolomitic sandstone above
logged Athabasca is Devonian; a quartzite below the logged unconformity is basement). Intervals that name two
categories, `basement` alone, intervals without codes or description, and point events stay unmapped with their
reason. The source codes are never changed; the mapping writes a derived table with the rule and evidence of every
assignment, and its SHA-256 travels with every output built on it.

Alberta's five categories follow the report's stratigraphy: 0 overburden (drift), 1 Devonian, 2 Athabasca Group,
3 basement gneiss (every gneiss, migmatite, mylonite, amphibolite and the basement quartzite), 4 basement granitoid
(granitoid, pegmatoid).

## 2. Grid and conditioning, in depth

The grid is regular in x, y and depth below a collar surface: the inverse-distance interpolation of the collar
elevations (exact at every collar; Alberta's relief is 25 m), so the ground is flat at depth 0 and a layer is a depth
band. Alberta: 250 m x 250 m x 10 m cells, 34 x 38 x 24 from x 748,750 and y 6,445,000, depth 0 to 240 m.

Each mapped interval is cut along its desurveyed trace (the preprocess trajectories), converted to depth, and the
length it logs in every cell is summed per category. A cell takes a category only when one category holds more than
half of the mapped length logged in it; otherwise it is left to the simulation and recorded as a conflict with every
candidate and its length. Cells reached only by unmapped intervals stay uninformed. Conditioning is built per split
scheme from its training holes only.

## 3. Training images (A07)

Both priors are authored by one seeded generator (`stages/training_images.py`) in the grid's cells and label
themselves as interpretations. They share the cover: overburden, Devonian and Athabasca layers in stratigraphic order
over basement, each unit's thickness a smooth random field (Gaussian-filtered white noise, correlation length a
declared 1 km) whose mean and standard deviation are the training holes' thicknesses of that unit, clipped at zero so
a unit can pinch out. They differ in the basement, where the granitoid proportion is the training holes' basement
proportion:

| Prior | Basement | Grounds |
|---|---|---|
| `nw-high-strain` | steep tabular granitoid bodies elongated along azimuth 315 | the northwest-trending Maybelle River high-strain zone (GSC Bulletin 588, doi:10.4095/223749) |
| `gneiss-domes` | rounded granitoid bodies with no preferred horizontal direction | "anatectic granitoids, which formed mantled gneiss domes" (MAR_19860002, p. 5), Taltson plutons (GSC Bulletin 588) |

Each TI (72 x 72 cells, the grid's 24 layers) records its prior, generator version, seed, parameters, category codes,
license (authored, MIT) and SHA-256.

## 4. Engines and non-stationarity

A TI is stationary, but the cover is not: overburden belongs near the surface. Each engine gets a verified mechanism:

- **SNESIM**: MPSlib `mps_snesim_tree` at `a47718fc0e2c7c6f3411de429e51f1267b5d7f7c` (LGPL-3.0), built from the pinned
  source by `scripts/build_mpslib.sh` (Linux or WSL; `scripts/build_mpslib.ps1` calls it through WSL on Windows),
  which writes the executables and a receipt (commit, compiler, bytes and SHA-256 of each executable). `stages/mps.py`
  writes the parameter file from the pinned schema, the TI, the hard data and the soft data as GSLIB/EAS files in a
  job directory, runs the executable as a subprocess with a timeout (through `wsl.exe` with translated paths on
  Windows), and parses `<ti>_sg_<n>.gslib`. One run produces all realizations of one scheme and prior from one seed
  (C `rand()` is seeded once per run); seeds stay below 2^24 because the seed is parsed as a float. Soft data: the
  training holes' vertical proportion curve per layer, shrunk toward the training proportions ((n_kz + a p_k) /
  (n_z + a), a = 20), divided by the TI's proportions, so MPSlib's normalized product gives
  P_TI(k | pattern) VPC(k | layer) / p_TI(k), the conditional-independence aggregation (Journel 2002's permanence of
  ratios for two categories). Parameters: three multiple grids, a 7 x 7 x 5 template, at most 40 conditioning nodes,
  random path.
- **Direct Sampling**: GeoCond 0.8.0 `direct_sampling`, categorical, 24 neighbours, threshold 0, scan fraction 0.25,
  one seed per realization, with `zones`: each depth layer scans only the same layer of the TI (Mariethoz, Renard and
  Straubhaar 2010, section 6). A node whose scan ends without an exact match takes the best scanned candidate,
  recorded as a fallback.
- **CPU and CUDA (S11)**: `scripts/check_ds_parity.py`, run in `.venv-gpu`, simulates the Alberta case on the NumPy
  and PyTorch backends and writes `ds-parity.json` with the counts of identical candidates and scores.

Both engines honour the conditioning exactly; `infer` fails if a realization changes a conditioning cell.

## 5. Evaluation (stage 8, categorical)

At every cell a held-out hole crosses, the realizations give a probability per category. Scores, per scheme, prior
and engine:

- the multi-category Brier score, $\mathrm{BS} = \frac{1}{n}\sum_{j}\sum_{k}(p_{jk} - o_{jk})^2$ (Brier 1950), and the
  log score with a floor of $10^{-3}$, against two references: the training proportions, and the vertical proportion
  curve of the training holes;
- accuracy of the most probable category, and how many test cells were hard data from a training hole in the same
  cell (scored separately);
- hard-data honour, proportions (realizations, TI, conditioning), fallbacks and conflicts;
- connectivity (Renard and Allard 2013): per category, the share $H$ of its largest 6-connected cluster and
  $C = n^{-2}\sum_i n_i^2$; and for every pair of training holes that both log a category, the fraction of
  realizations in which they meet in one cluster, compared across priors and engines (A07, A08). A connection that
  holds under both priors and both engines persists; one that appears under one prior only belongs to the prior.

## 6. Authored checks

- **S10**: a small authored binary TI with channels, simulated unconditionally by SNESIM; the frequencies of all
  2 x 2 patterns in the realizations, counted exhaustively, match the TI's within a declared total-variation bound,
  and the categories are the TI's.
- **S11**: the same Direct Sampling case on both backends gives identical candidates and scores for every node.

## 7. What it does not claim

The TIs are interpretations; a realization is a conditional sample of that interpretation, not a geological model of
the Maybelle River basement. Three held-out holes per scheme give weak evidence; the scores say which prior and engine
predicted those holes better, not which is true.
