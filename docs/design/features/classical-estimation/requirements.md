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
