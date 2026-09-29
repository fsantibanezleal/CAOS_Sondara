# Alberta MAR_19860002: inclined holes, logged geology, sampling envelopes

**Source.** Alberta Geological Survey, DIG 2024-0022, a compilation of drillhole data from mineral assessment reports
(`DIG_2024_0022_0.zip`, 8,623,762 bytes, SHA-256 pinned), under the Open Government Licence - Alberta with
acknowledgement of the Alberta Energy Regulator / Alberta Geological Survey. Sondara uses report `MAR_19860002`. The
archive's three tables are tab-separated Windows-1252 with multiline quoted descriptions; they are read member by member
without extraction, decoded with the declared encoding, and joined on `(Data_src, DH_name)`.

**The project.** MAR_19860002 is Uranerz Exploration and Mining's assessment report for the Maybelle River project
(project 71-42, permits 6884100001, 6884100002 and 6884120001; work of October 1984 to July 1986, compiled by R. G.
Orr), in the western Athabasca Basin of northeastern Alberta. Its stratigraphy table lists glacial drift over patchy
Middle Devonian dolomites and sandstones, the Athabasca Group (Manitou Falls Formation, 0 to 122.3 m, and Fair Point
Formation, 0 to 39.3 m, in the project's drilling), an unconformity, and a basement of Aphebian granitoids and
metasediments and Archean granite gneisses. The basement is known only from drilling: "there is no known outcrop within
the project area".

## What the ingest keeps

| Quantity | Count |
|---|---|
| Collars, with Easting, Northing, ground elevation, total depth, azimuth and dip | 22 |
| Geology records (138 intervals with positive length, 12 point events) | 150 |
| Assay rows (wide, 32 populated analyte columns) | 3,717 |
| Samples with numeric Cu and Zn | 342 |
| of which positive sampling envelopes, on all 22 holes | 176 |
| point-depth samples | 162 |
| samples without endpoints | 4 |

## Decisions carried into every result

- **Collar directions are recorded, not surveyed.** Every row has `Inclnation = 90 + Survey_dip`, so the dip is
  negative downward from horizontal. There is no station table, so each trajectory is the recorded direction extended
  to total depth, labelled `collar-orientation`. The azimuth's north reference is not given and the frame is NAD83 /
  10TM (central meridian -115 degrees) with the vertical datum deferred to the original reports; neither is guessed.
- **Samples are envelopes.** 79 notes describe composites or spaced sampling (MR-01-1 spans 34-55 m and was sampled
  every 1.5 m), and 85 pairs of positive envelopes overlap. An envelope's sampled components and weights are unknown,
  so it is never treated as a uniform interval: no averaging, no recompositing, no support-integrated covariance.
  Estimation on Alberta is a separately named envelope-centre approximation.
- **Raw analytical tokens stay.** `-9999` and empty are missing, a `<` or `>` prefix is a qualifier with its threshold,
  nothing is imputed. Every Cu and Zn value in the report is numeric and unqualified; a value of 1 ppm equal to the
  detection limit is not evidence of censoring. The three LOI results of 81 samples (600, 900 and 1100 C) are three
  methods, not replicates.
- **Geology stays as logged.** `Rock_type`, `Litho_unit`, material and description are kept verbatim; point rows stay
  events. A many-to-one lithology mapping for categorical simulation is a separate, versioned interpretation. MR-14's
  0.05 m logging overlap and MR-16's 0.1 m gap stay as recorded.

## Preprocessing

Each hole is a straight projection of its recorded collar direction to total depth, so all 338 positioned supports
(176 envelopes and 162 points) lie on that projection; the 4 samples without endpoints get no position. No envelope,
point or log endpoint lies beyond its hole's total depth. Each envelope is then overlaid on the logged geology:

| Coverage by | Covered metres (of 1,960.4) | Envelopes fully covered (of 176) |
|---|---:|---:|
| any positive log, including unknown units | 1,960.1 | 173 |
| a known `Litho_unit` | 285.6 | 51 |
| a known `Rock_type` | 207.4 | 36 |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../assets/preprocess-alberta-overlay-dark.svg">
  <img alt="Bars showing the share of the 176 Alberta sampling envelopes covered by any log, by a known Litho_unit and by a known Rock_type, with the counts of fully covered envelopes." src="../assets/preprocess-alberta-overlay-light.svg" width="760">
</picture>

- **The three envelopes not fully logged** are MR-16's, which cross the unlogged 63.30 to 63.40 m.
- **Two envelopes cross MR-14's 0.05 m logged twice.** The two logs do not disagree on a known code there, so the
  report has no conflict; a piece with two different known codes would count as uncovered and be listed.
- **Proportions stay proportions.** Partly typed envelopes carry the length share of each known code; none is promoted
  to a single dominant category.
- **Populations.** The envelope-centre Cu/Zn population holds the 176 envelopes on all 22 holes, placed at their
  measured-depth centre, with 162 point samples and 4 unknown supports counted as excluded. The point samples form a
  separate display and QA population and are never widened.

These numbers reproduce the research audit exactly.

## Splits and features

| Scheme | Train | Validation | Calibration | Test |
|---|---:|---:|---:|---:|
| hole-group | 13 | 4 | 2 | 3 |
| spatial-margin | 14 | 3 | 2 | 3 |

Each hole's nearest neighbour is a median of about 710 m away, so the 1,062 m buffer excludes no hole. On the
envelope-centre population of the hole-group split, Cu has 102 training envelopes in 13 holes, a mean of 8.7 ppm and a
cell-declustered mean of 7.6 ppm. Its omnidirectional variogram's first bin, centred near 600 m, holds 49 pairs, and
its downhole variogram (10 m lag, the median envelope length) holds 90 pairs at the first lag: weak evidence, recorded
with its pair counts.

## Models

The covariance selected on the validation holes, for Cu at the envelope centres:

| Scheme | Model | Validation RMSE (ppm) |
|---|---|---:|
| hole-group | spherical 336, ranges 10,204 m (azimuth 135), 75 m, 2,611 m vertical | 11.21 |
| spatial-margin | exponential 274, ranges 23,519 m (azimuth 135, at the fitting bound), 47 m, 4,380 m | 7.21 |

With 13 or 14 training holes about 700 m apart, the fits rest on few pairs and should be read as weak evidence; the
two schemes disagree on the family and the ranges. Every method predicts every test envelope.

## Evaluation

With three test holes per scheme (28 and 26 envelope centres), no method separates from OK (RMSE 5.47 ppm Cu inside
the drilled area, 11.15 at the margin) beyond wide hole-block intervals, and Zn does not improve Cu. The kriging
variances are about five times too large (variance scale 0.19, from two calibration holes), MIK has no skill, and
the Gaussian-space model's sill (1.87) makes the SGS realizations twice as variable as the truths. DeepKriging and
KCN (0.11.000) score below OK inside the drilled area (RMSE 4.81 and 4.80), but their shuffled-label controls score
the same and the training mean alone scores 4.66: with 13 training holes, early stopping keeps models close to the
mean, and no method shows spatial skill over a constant on these test values. These are weak evidence, as the fits
are. Tables and caveats: [model evaluation](../architecture/06_model-evaluation.md).

## The reviewed lithology mapping (A04)

The logs keep three fields: `Rock_type` (6 values, 72 of 150 rows missing), `Litho_unit` (42 values and `-9999`), and a
free description, which names the unit where the codes are missing ("Unit: Devonian", "Unit: Athabasca").
`data/interpretations/alberta-lithology-v1.json` maps them to five categories that follow the report's stratigraphy,
by ordered rules, and leaves the source codes unchanged:

| Category | Rows | Logged length | Rules |
|---|---:|---:|---|
| 0 overburden | 22 | 827.0 m | the code `overburden` |
| 1 Devonian | 21 | 494.4 m | a description beginning "Unit: Devonian" (20); a dolomitic sandstone above logged Athabasca (MR-03) |
| 2 Athabasca Group | 19 | 1,008.3 m | a description beginning "Unit: Athabasca" (17); a conglomerate directly above the basement or the logged unconformity (MR-01, MR-03) |
| 3 basement gneiss | 48 | 1,094.1 m | 26 gneiss, migmatite, mylonite and amphibolite codes (47); a quartzite below the logged unconformity (MR-04) |
| 4 basement granitoid | 20 | 551.4 m | `granitoid`, `basement granitoid`, `pegmatoid`, `granitoid / pegmatoid` |

Twenty rows stay unmapped with their reason: the 12 point events (unconformity contacts and ends of hole) are events,
not volumes; six intervals name both basement categories (`granitoid and pelitic gneiss` and five like it); MR-11's
`basement` is neither gneiss nor granitoid; and MR-08 logs 69.0 to 124.9 m with no code and no description. The mapping
is an interpretation with a version and a hash; every categorical output records it, so an edit invalidates them.

## Categorical simulation (A07, A08)

The mapped intervals condition a grid of 250 m x 250 m x 10 m cells in depth below the collar surface (34 x 38 x 24
cells): a cell takes the category holding more than half of its logged length, and the few cells where no category
does are recorded conflicts (one on the hole-group split, in MR-22, and one more on the margin, in MR-15). Two training
images are authored from the training holes: both share the layered cover, with thickness fields whose means and
spreads are the training holes' (Athabasca 39.5 m on average, absent in 3 of 12), and differ in the basement, where
granitoid forms steep bands along the northwest trend of the Maybelle River high-strain zone (GSC Bulletin 588) or
rounded bodies (the report's "mantled gneiss domes"). SNESIM (MPSlib) and zoned Direct Sampling (GeoCond) each draw 32
realizations per image and split.

On the three held-out holes of each split, every run beats both references on the Brier score: on the hole-group split
SNESIM with the gneiss domes scores 0.359 against 0.464 for the vertical proportion curve, and on the margin zoned
Direct Sampling with the gneiss domes scores 0.387 against 0.623. The ranking of engines and priors reverses between the
splits, and three holes cannot separate them. The cover is one connected body in every run; granitoid bodies between
holes stay uncertain (one persistent pair per split); MR-22's basement gneiss joins its neighbours' under one prior and
not the other. Every run under-reproduces granitoid (0.06 to 0.12 of the grid against 0.15 to 0.21 in the images).
Tables, figures and limits: [model evaluation](../architecture/06_model-evaluation.md).

## What it can and cannot answer

Alberta supplies the inclined-hole, logged-geology and native-support scenarios (A01 to A08): support QA, the
envelope-centre Cu/Zn comparison, lithology-assay overlap, whole-hole holdouts and categorical simulation under
authored training images. It cannot supply known-weight interval supports, a measured trajectory or observed 3D
categorical truth.
