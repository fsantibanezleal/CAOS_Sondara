# Geochemical review and the spectral-index lineage (SD-7b): design

Unit SD-7, second release (0.12.000): scenario R12, "What does the supplied spectral index actually represent?", on
the Rocklea family. It has three parts: the lineage of the supplied hyperspectral export, a training-fold check of what
its iron-oxide index predicts, and the geochemical autoencoder review of the assays with its PCA reference. The research
is in the management repository (`wip/drillhole-workbench/learned-methods-2026-09-28.md`, section 3, with its evidence
file), on top of the contract of 2026-09-10 (geochemical autoencoder vertical).

## 1. Sources

Four more files of CSIRO collection 44783 (CC BY 4.0) are pinned in `data/sources/manifest.json` with their byte counts
and SHA-256 and fetched by `acquire`:

| File | Bytes | Why |
|---|---:|---|
| `GeoscienceProductDescriptions_ProximalHyperspectral.xlsx` | 15,560 | the definition, mask, stretch and stated accuracy of every spectral scalar in the export |
| `RC_data.ini` | 79,884 | the TSG project of the export: its parameters, which scalars are scripts and which are imported columns |
| `RC_data8_Fe.pls` | 41,640 | a TSG PLS model for Fe: its existence is part of the lineage; it is not used |
| `Answers_CIDexercises.docx` | 1,639,454 | the stated validation of the Fe-oxide script (RMSE 11.3 wt% Fe) |

Where each part runs, so no stage reaches back to a source it did not declare:

| Stage | Writes | Holds |
|---|---|---|
| `ingest` (Rocklea) | `spectral-source.json` | the TSG export's rows (hole, depth, the spectral scalars with their masks as null, the embedded assay columns, the source row), the descriptions workbook's rows, the TSG project's parameter list, the PLS file's hash and size, the exercise answers' validation statements, all with source references |
| `features` | `spectral-lineage.json` | the products, the embedded-assay identity against the canonical assays, the registration per hole |
| `train` | `spectral-models.json`; `geochemistry-models.json` and `learned/geochemistry/` (learned lane) | the index calibration with its test predictions; the autoencoder fits and the PCA reference |
| `infer` | `geochemistry-predictions.json` and the review export (learned lane) | reconstruction scores of the calibration and test records and of the constructed alterations |
| `evaluate` | `review-metrics.json` | the index check's scores beside OK, and the review's threshold, recalls and false flags |

R12 uses the hole-group split and the 1 m population.

## 2. The lineage (features, Rocklea)

`stages/spectral.py` writes `spectral-lineage.json` beside the features:

- **Products.** Each export column with its product name, base algorithm, unit (relative depth, ratio or nm), mask and
  stated accuracy, parsed from the descriptions workbook; a column the workbook does not describe is listed as such.
- **Embedded assays.** For each assay-like column of the export (`Fe %`, `Al2O3`, `SiO2 %` and eight more), the count of
  rows equal to the workbook assay at the same hole and depth (for `Fe %`, equal after rounding to a whole percent):
  these columns are the targets, never features.
- **Registration.** Per hole, whether the embedded assays confirm the export's depths: `confirmed`, `offset +1 m`,
  `offset -1 m`, `unmatched` (no workbook interval within 2 m holds the same values), or `no embedded assay`; and the
  duplicate hole-depth keys. A spectral row is paired with an assay interval only where its hole's registration is
  confirmed (12 holes are not, on the 2026-09-28 probe).
- **Calibrated channels.** The PLS model's file hash and the statement that no calibrated channel is in the export;
  any calibrated channel would need a training-fold refit before it could enter a held-out comparison.

## 3. What the iron-oxide index predicts (train and evaluate)

`Fe ox ai` is a relative band depth, not wt% Fe. A monotone calibration (isotonic, as MIK's correction, bounded by the
training range) of Fe on `Fe ox ai` is fitted on the training holes' confirmed rows where the mask admits a value, and
scored on the test holes' confirmed rows: RMSE, MAE and bias in wt% Fe, beside the published figures (9.7 % in the
descriptions sheet, 11.3 wt% Fe in the exercise answers, both without their method). This task has information the
spatial methods do not: a measurement in the target interval. It is reported as its own task, with OK's error on the
same rows for scale, never as an improvement of OK.

## 4. The geochemical autoencoder review (train, infer, evaluate)

The contract's properties: Fe, P, SiO2, Al2O3, CaO, K2O, MgO, TiO2, LOI, on complete records of the 1 m population.
Each is centred by its training median and scaled by its training interquartile range, then `asinh`; a zero-IQR
property is removed with a record.

- **Autoencoder:** p-32-8-k-8-32-p with ReLU hidden layers and a linear output, k in {2, 3}, AdamW (0.001, 0.0001), at
  most 300 epochs, patience 30, three seeds; k selected by the seed mean of the validation reconstruction MSE.
- **PCA reference:** the same transformed training data and the selected rank.
- **Scores:** the per-record reconstruction error and the per-property residuals on the test records; a review
  threshold at the calibration records' 95th percentile of the error. The title is compositional atypicality, not
  contamination, ore or assay invalidity.
- **Constructed alterations** (the 0.2 module's defect L-3 fixed: every altered record is altered): unchanged records;
  one property multiplied by 10; the first two properties swapped in from a record of another hole; a percent-to-ppm
  omission (x 10,000); additive shifts of 0.25, 1 and 3 in transformed units on one property per record, chosen by a
  seeded generator and recorded. Each keeps its parent id. Scores: per-perturbation recall at the threshold, false
  flags on unchanged records, for the autoencoder and PCA.
- **Export:** encoder, decoder, scaling and score as one ONNX graph (`values` to latent, residuals and score), with the
  audit and parity of SD-7a, bound to the property names and units: a model refuses records whose properties or units
  differ.

## 5. R12's cells

`spectral-lineage.json` (the lineage), the calibration check's metrics, and the autoencoder review's metrics. With
them the scenario matrix has no pending SD-7 cell.

## 6. What it does not claim

The lineage says what each column is and where its depths can be trusted; it does not validate the spectral scripts.
The calibration check measures one index against one assay on these holes. A high reconstruction error directs review;
it is not a finding about the rock or the laboratory, and the constructed alterations test detection of those
alterations only.
