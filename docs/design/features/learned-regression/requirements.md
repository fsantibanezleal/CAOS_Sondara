# Learned regression (SD-7a): requirements

Status: planned

Each requirement names the test that verifies it (`tests/test_learned.py`, run in `.venv-gpu`; the CUDA gate skips
without a device). The tests train on the authored field of `tests/authored_field.py` with a reduced epoch budget; the
field run is recorded in `learned-models.json` and checked by `scripts/check_artifacts.py`.

## Rows, splits and transforms (0.11.000)

```
R-701  THE learned lane SHALL take its populations from features.json with the classical target rule, SHALL fit on
       training rows only, select on validation rows only, and predict exactly the classical lane's test and
       calibration targets.
       Gate: tests/test_learned.py::test_the_lane_uses_the_classical_split_and_targets

R-702  THE fitted transforms (origin, axis scales, retained knots, target mean and scale, neighbour scale) SHALL depend
       on training rows only: changing any validation, calibration or test value SHALL leave them unchanged.
       Gate: tests/test_learned.py::test_transforms_see_training_rows_only

R-703  WHEN a training axis has zero extent, THE lane SHALL keep a one-metre scale and a constant normalized
       coordinate, and WHEN the training target is constant, THE lane SHALL predict that constant without a fit and
       record the reason.
       Gate: tests/test_learned.py::test_degenerate_axes_and_constant_targets
```

## DeepKriging (0.11.000)

```
R-704  THE DeepKriging basis SHALL be the Wendland function (1-r)^6(35r^2+18r+3)/3 on [0,1] and zero beyond, with a
       radius of 2.5 knot spacings on rectangular levels over the training box, SHALL drop the columns that are zero
       on every training row, and SHALL be computed inside the exported graph within 1e-5 of the float64 NumPy
       oracle (float32 arithmetic; measured 1.5e-6).
       Gate: tests/test_learned.py::test_the_basis_matches_its_oracle_inside_the_graph
```

## KCN (0.11.000)

```
R-705  THE KCN neighbour search SHALL exclude the query's own hole, SHALL take at most the declared rows per hole,
       SHALL require the declared distinct holes, and SHALL leave a query without that support uninformed with its
       reason.
       Gate: tests/test_learned.py::test_neighbours_exclude_the_query_hole_and_report_insufficient_support

R-706  THE KCN graph SHALL follow Appleby, Liu and Liu (2020) eqs. 9 and 3 (a self weight of 2 before normalization,
       D = diag(A1 + 1)) with padding excluded from degrees and messages and the query's value hidden; its prediction
       SHALL NOT depend on the order of the neighbours and SHALL change when a neighbour's value changes.
       Gate: tests/test_learned.py::test_the_kcn_graph_follows_the_paper_and_ignores_neighbour_order
```

## Training and selection (0.11.000)

```
R-707  THE lane SHALL fit every configuration of the frozen search with the three declared seeds, SHALL select by the
       mean over seeds of the validation hole-macro RMSE with the declared tie rule, SHALL publish the three-seed mean
       with its spread and no variance, and SHALL record every fit's best epoch, history and weights hash.
       Gate: tests/test_learned.py::test_selection_is_by_the_seed_mean_on_validation

R-708  WHEN a saved fit's recipe hash matches, THE lane SHALL reuse its weights, loaded as tensors only; WHEN it
       differs, THE lane SHALL refuse it.
       Gate: tests/test_learned.py::test_fits_resume_and_refuse_another_recipe

R-709  THE lane SHALL fit the shuffled-label control for both methods and the coordinate-only ablation for
       DeepKriging, and on the authored field the fitted models SHALL beat the shuffled-label control on the test
       rows.
       Gate: tests/test_learned.py::test_controls_are_fitted_and_lose_on_the_authored_field

R-710  THE residual band SHALL take its radius from the calibration rows only (the 95th percentile of the ensemble's
       absolute residuals), and evaluate SHALL report its coverage of the test truths.
       Gate: tests/test_learned.py::test_the_residual_band_comes_from_calibration_rows
```

## Export and parity (0.11.000)

```
R-711  THE export SHALL write one ONNX file per seed in the standard domain, with no control flow, no external data,
       no metadata and no local path, within 2,000 nodes and 8 MiB, with a manifest binding it to its project,
       population, analyte, unit, feature schema, transforms and training rows.
       Gate: tests/test_learned.py::test_the_export_is_audited_and_bound

R-712  ONNX Runtime on the CPU SHALL agree with PyTorch on the CPU on every held-out input of the same checkpoint within
       1e-4 training standard deviations, and the parity SHALL be recorded per seed.
       Gate: tests/test_learned.py::test_onnx_agrees_with_torch_on_held_out_inputs

R-713  WHEN a CUDA device is present, PyTorch on CUDA SHALL agree with PyTorch on the CPU within the same tolerance.
       Gate: tests/test_learned.py::test_cuda_agrees_with_cpu

R-714  A portable model SHALL be refused when its archive, hashes or graph fail the audit, or when its project, frame,
       task or property unit differs from the one it is applied to.
       Gate: tests/test_learned.py::test_a_foreign_or_altered_model_is_refused
```

## Evaluation (0.11.000)

```
R-715  THE evaluate stage SHALL score DeepKriging and KCN with the classical scores on the same targets, including the
       paired comparison with ordinary kriging, SHALL leave the classical common targets unchanged, and SHALL refuse
       learned predictions built on another dataset or target list.
       Gate: tests/test_learned.py::test_evaluate_scores_the_learned_methods_beside_ordinary_kriging

R-716  THE learned outputs SHALL carry no held-out value: the fits, exports and manifests SHALL hold training row ids
       and training values only.
       Gate: tests/test_learned.py::test_no_held_out_value_is_serialized

R-717  THE learned models, predictions and exports of a family SHALL pass the artifact checks: every selected
       configuration present with three fits, every target predicted or given a reason, every export audited with its
       parity inside the tolerance.
       Gate: scripts/check_artifacts.py
```
