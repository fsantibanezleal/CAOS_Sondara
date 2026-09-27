# Classical estimation (SD-5): requirements

Requirements are added with the release that builds them, each naming its test.

## Splits and features (0.07.000)

```
R-501  THE dataset stage SHALL assign every hole of an estimation family, in each scheme, to exactly one of train,
       validation, calibration and test, or to the spatial-margin buffer, and every population member SHALL follow
       its hole.
       Gate: tests/test_dataset.py::test_every_member_follows_its_hole

R-502  THE hole-group split SHALL be reproducible from its recorded seed and SHALL cut the holes 60/15/10/15 by
       largest remainder.
       Gate: tests/test_dataset.py::test_hole_group_split_is_seeded_and_proportional

R-503  THE spatial-margin split SHALL hold out the outermost 15 % of holes and SHALL exclude from training, and
       report, every hole within the buffer of a held-out hole.
       Gate: tests/test_dataset.py::test_spatial_margin_split_holds_out_the_margin_with_a_buffer

R-504  WHERE a holdout is declared, THE dataset stage SHALL use it, and every derivative of a held-out hole (samples,
       repeats, composites, fragments) SHALL be in test only (F40).
       Gate: tests/test_dataset.py::test_declared_holdout_takes_every_derivative

R-505  IF a family has fewer holes than a grouped split needs, THEN THE dataset stage SHALL record it as not eligible,
       with the reason.
       Gate: tests/test_dataset.py::test_single_hole_family_has_no_split

R-506  THE features stage SHALL read only training members, so its statistics, declustering and variograms SHALL NOT
       change when validation or test values change.
       Gate: tests/test_features.py::test_features_see_training_rows_only

R-507  THE experimental variograms SHALL equal GeoCond called directly on the same training rows, downhole and
       directional, with pair counts, separations and the sampling seed recorded.
       Gate: tests/test_features.py::test_variograms_are_geocond_on_training_rows

R-508  WHEN declared orientation normals conflict (the two largest eigenvalues of their orientation tensor within the
       declared ratio), THE features stage SHALL report the orientation as undefined, and otherwise SHALL return the
       principal orientation (F38).
       Gate: tests/test_features.py::test_conflicting_orientation_normals_are_undefined

R-509  THE declustered mean SHALL use cell declustering with a recorded cell size, and SHALL equal the plain mean on
       a regular grid.
       Gate: tests/test_features.py::test_cell_declustering
```

```
R-510  IF a dataset or features output does not match the inputs it records, or a membership record is stale,
       THEN THE artifact check SHALL fail and name it.
       Gate: tests/test_dataset.py::test_the_contract_check_rejects_a_stale_split
```

## Train and infer (0.08.000)

```
R-520  THE train stage SHALL fit every declared candidate covariance on the training variograms and SHALL select the
       candidate with the lowest validation RMSE of ordinary kriging among those covering at least 90 % of the
       validation targets, recording every candidate, and SHALL NOT read test values.
       Gate: tests/test_train.py::test_model_selection_uses_validation_only

R-521  THE train stage SHALL fit a positive semidefinite LMC for the declared variable sets, indicator covariances at
       training-weighted deciles, and a normal-score table from training values only.
       Gate: tests/test_train.py::test_lmc_indicators_and_normal_scores_are_train_only

R-522  EVERY fitted model, transform and variogram SHALL round-trip exactly through its stored record.
       Gate: tests/test_train.py::test_models_round_trip

R-523  Ordinary kriging SHALL reproduce a constant field, and universal kriging with a linear drift SHALL reproduce a
       linear field, at withheld targets within 1e-7 relative (S05).
       Gate: tests/test_infer.py::test_constant_and_polynomial_truths

R-524  Predictions SHALL be unchanged, within 1e-9, when coordinates and anisotropy are rotated and translated
       together (S06, F33).
       Gate: tests/test_infer.py::test_rotation_invariance

R-525  WITH zero cross covariance, ordinary cokriging SHALL equal ordinary kriging of the primary, and simple
       cokriging SHALL reproduce the analytic weights 3/14 and 5/7 and variance 9/28 (S07).
       Gate: tests/test_infer.py::test_cokriging_reduces_and_matches_the_analytic_case

R-526  IF a sill matrix is not positive semidefinite, THEN it SHALL be refused; IF one variable is observed twice at
       one support with different values, or the drift is rank deficient, THEN the target SHALL fail with its reason
       and keep its method label (S08, F34, F37).
       Gate: tests/test_infer.py::test_invalid_models_and_systems_fail_honestly

R-527  Block estimates SHALL converge as the quadrature order doubles, the last doubling changing the mean and the
       variance by less than 0.1 % of the sill (S09).
       Gate: tests/test_infer.py::test_block_quadrature_converges

R-528  IF fewer observations than the declared minimum lie in the neighbourhood, THEN the target SHALL be uninformed
       with its reason; no hole SHALL contribute more than the declared per-hole maximum (F31, F32).
       Gate: tests/test_infer.py::test_neighbourhood_limits_and_uninformed_targets

R-529  A hard domain boundary SHALL condition on the target's domain only, and a soft boundary SHALL add other
       domains' observations within the declared distance (F35).
       Gate: tests/test_infer.py::test_domain_boundaries

R-530  WHEN simple kriging finds no observation in the neighbourhood, THE result SHALL be the declared mean and the
       total sill with status prior-only (F36).
       Gate: tests/test_infer.py::test_simple_kriging_prior_without_conditioning

R-531  Sequential Gaussian simulation SHALL reproduce a realization from its seed, differ across seeds, and honour
       hard data at coincident nodes (F39).
       Gate: tests/test_infer.py::test_sgs_seeds_and_hard_data

R-532  THE infer stage SHALL predict every test target of every fitted population with NN, IDW, SK, OK, UK, LMC, MIK
       and SGS, recording a status and reason for each, and the artifact check SHALL fail when a method is missing.
       Gate: tests/test_infer.py::test_every_method_predicts_every_test_target
```
