# Categorical simulation (SD-6): requirements

Each requirement names the test that verifies it. The tests marked MPSlib skip, with the reason, where the pinned
executables are not built (`scripts/build_mpslib.sh`, `SONDARA_MPSLIB`); the CUDA test skips without PyTorch or a
device and runs in `.venv-gpu` (`requirements-gpu.txt`). Their evidence on a machine that has both is the receipt
`simulation-checks.json` written by `scripts/check_simulation.py`, which the scenario matrix reads for S10 and S11.

## Mapping and conditioning (0.10.000)

```
R-601  THE reviewed mapping SHALL assign a logged interval to a category only by a declared rule (a source code, a
       unit named in the description, or a position clause that holds), SHALL leave every other interval unmapped
       with its reason, and SHALL NOT change a source code.
       Gate: tests/test_categorical.py::test_the_mapping_applies_declared_rules_only

R-602  THE Alberta mapping file SHALL declare categories 0 to 4, an evidence line for every rule, and every code in at
       most one rule or unmapped list.
       Gate: tests/test_categorical.py::test_the_alberta_mapping_file_is_consistent

R-603  WHEN mapped intervals are cut into a grid in depth below the collar surface, THE cell lengths SHALL conserve
       every interval's length, THE surface SHALL be exact at every collar, a cell SHALL take a category only when it
       holds more than half of the mapped length logged in it, any other logged cell SHALL be a recorded conflict with
       every candidate, and an unmapped interval SHALL inform no cell.
       Gate: tests/test_categorical.py::test_conditioning_conserves_length_and_records_conflicts
```

## Training images and engines (0.10.000)

```
R-604  THE training images SHALL be reproducible from their seed, label themselves as interpretations, share the cover
       and differ only in the basement, hold the requested granitoid proportion in the basement, keep the cover above
       the basement in every column, and the northwest prior SHALL be more continuous along azimuth 315 than across it.
       Gate: tests/test_categorical.py::test_training_images_are_seeded_labelled_and_different_where_declared

R-614  THE cover statistics of the training images SHALL count every cover interval that starts above a hole's
       basement top, clipped at that top, and SHALL exclude, with the reason, a hole whose cover has an unmapped gap.
       Gate: tests/test_categorical.py::test_cover_statistics_clip_overlaps_and_exclude_gaps

R-605  THE SNESIM soft probabilities SHALL be the training holes' vertical proportion curve, shrunk toward the
       training proportions and carried from the nearest layer with enough cells, divided by the TI's proportions and
       normalized per layer.
       Gate: tests/test_categorical.py::test_vertical_proportions_and_soft_probabilities

R-606  THE MPSlib run SHALL write the pinned parameter schema, reproduce its realizations from the seed, differ across
       seeds, refuse a seed at or above 2^24, record the executable's hash from the build receipt, and fail unless
       every hard cell is honoured. (MPSlib)
       Gate: tests/test_categorical.py::test_snesim_runner_is_supervised_seeded_and_exact

R-607  SNESIM realizations of an authored binary channel image SHALL reproduce the image's 2 x 2 pattern frequencies,
       counted exhaustively, within a total-variation distance of 0.05, and patterns the image never holds SHALL
       stay below 1 % (S10). (MPSlib)
       Gate: tests/test_categorical.py::test_snesim_reproduces_small_pattern_frequencies

R-608  THE product's Direct Sampling SHALL scan each depth layer's own TI layer, reproduce a realization from its seed
       and honour every hard cell.
       Gate: tests/test_categorical.py::test_zoned_direct_sampling_in_the_product

R-609  THE product's Direct Sampling SHALL select the same candidate and value for every node on the NumPy and the
       PyTorch backends (S11). (CUDA)
       Gate: tests/test_categorical.py::test_direct_sampling_cpu_and_cuda_agree_in_the_product
```

## Scores, the lane and its checks (0.10.000)

```
R-610  THE categorical scores SHALL equal a direct computation: the multi-category Brier score, the log score with its
       floor, and the accuracy of the most probable category, from the realizations' category frequencies.
       Gate: tests/test_categorical.py::test_categorical_scores_equal_a_direct_computation

R-611  H and C SHALL equal their definitions (Renard and Allard 2013) on an array with known clusters, and a hole
       connection SHALL be 1 for holes joined in every realization and 0 for holes never joined.
       Gate: tests/test_categorical.py::test_connectivity_and_hole_connections

R-612  THE categorical lane SHALL run through train, infer and evaluate on an authored layered field, with every
       scheme, prior and engine, every hard cell honoured, and every test cell scored. (MPSlib)
       Gate: tests/test_categorical.py::test_the_lane_runs_end_to_end_on_an_authored_field

R-613  IF a categorical output does not match its input, a training image or realization file does not match its
       hash, a run changed a conditioning cell, or the mapping leaves a code without a rule, THEN THE artifact check
       SHALL fail and name it. (MPSlib)
       Gate: tests/test_categorical.py::test_the_contract_check_rejects_stale_categorical_outputs
```
