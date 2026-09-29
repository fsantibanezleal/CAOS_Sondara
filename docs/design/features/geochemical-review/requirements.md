# Geochemical review and the spectral-index lineage (SD-7b): requirements

Each requirement names the test that verifies it (`tests/test_spectral.py` for the lineage and the calibration check,
`tests/test_geochemistry.py` for the autoencoder review, run in `.venv-gpu`).

## Sources and lineage (0.12.000)

```
R-718  THE sources manifest SHALL pin the product-descriptions workbook, the TSG project file, the PLS model file and
       the exercise answers of CSIRO collection 44783 by URL, byte count and SHA-256, with their license.
       Gate: tests/test_spectral.py::test_the_lineage_sources_are_pinned

R-719  THE lineage SHALL give every spectral column of the export its product, algorithm, unit, mask and stated
       accuracy from the descriptions workbook, and SHALL list a column the workbook does not describe as undescribed.
       Gate: tests/test_spectral.py::test_every_spectral_column_has_its_product_or_is_marked

R-720  THE lineage SHALL count, for every assay-like column of the export, the rows equal to the workbook assay at the
       same hole and depth, and SHALL classify those columns as targets that no feature may use.
       Gate: tests/test_spectral.py::test_embedded_assays_are_identified_as_targets

R-721  THE lineage SHALL classify every hole's depth registration as confirmed, offset by one metre either way,
       unmatched or without embedded assays, SHALL list duplicate hole-depth keys, and SHALL pair a spectral row with
       an assay interval only in a confirmed hole.
       Gate: tests/test_spectral.py::test_registration_is_classified_and_gates_the_pairing
```

## The iron-oxide index (0.12.000)

```
R-722  THE calibration of Fe on the iron-oxide index SHALL be monotone, fitted on the training holes' confirmed and
       unmasked rows only, bounded by their range, and scored on the test holes' confirmed rows beside OK's error on
       the same rows, as its own task.
       Gate: tests/test_spectral.py::test_the_index_calibration_is_fitted_on_training_rows_only
```

## The autoencoder review (0.12.000)

```
R-723  THE geochemical transform SHALL centre each property by its training median, scale it by its training
       interquartile range and apply asinh, SHALL remove a zero-IQR property with a record, and SHALL refuse an
       incomplete record rather than impute it.
       Gate: tests/test_geochemistry.py::test_the_transform_is_fitted_on_training_records_only

R-724  THE autoencoder SHALL have a bottleneck smaller than its inputs, SHALL be fitted with the three seeds and select
       its latent size by the seed mean of the validation reconstruction error, and THE PCA reference SHALL use the
       same transformed training data and rank.
       Gate: tests/test_geochemistry.py::test_selection_and_the_pca_reference

R-725  EVERY constructed alteration SHALL change the record it marks as altered, SHALL keep its parent id, and SHALL
       leave the unchanged records equal to their parents.
       Gate: tests/test_geochemistry.py::test_every_altered_record_is_altered

R-726  THE review threshold SHALL come from the calibration records only, and THE evaluation SHALL report the recall
       of every alteration kind and the false flags of unchanged records for the autoencoder and PCA.
       Gate: tests/test_geochemistry.py::test_the_threshold_comes_from_calibration_records

R-727  THE exported review model SHALL compute the scaling, latent, residuals and score in one audited graph within
       the parity tolerance, and SHALL be refused for records whose properties or units differ.
       Gate: tests/test_geochemistry.py::test_the_review_export_is_audited_and_bound
```
