# Fixtures and authored scenarios

The importer and QA catalogue of the data research has 42 authored fixtures. Each is a constructed case with an exact
expected outcome, never a field observation, and each is verified by the stage that owns it.
`scripts/fixtures/author_fixtures.py` writes them deterministically: the files and import manifests of the fixtures
whose stages exist are in `data/fixtures/<ID>/`, and every fixture is listed in `data/fixtures/registry.json` with its
construction, expected outcome, owning stage and verifying test. Fixtures of stages still to be built carry their
construction as parameters in the registry; the registry test fails the moment their stage exists without a
verification.

| ID | Construction | Expected outcome | Stage | Verified by |
|---|---|---|---|---|
| F01 | Two collar, two survey and three disjoint assay files | Same canonical data as the consolidated files | import | test_split_and_reordered_files_equal_the_consolidated_import |
| F02 | Reordered files and rows | Invariant under explicit precedence and sorting | import | test_split_and_reordered_files_equal_the_consolidated_import |
| F03 | Identical file twice | No doubled measurements | import | test_a_repeated_file_adds_no_measurement |
| F04 | Conflicting collar versions | Both versions and the affected records reported; accepted only with a recorded resolution | import | test_conflicting_collars_block_until_resolved |
| F05 | Two sources reuse DH001 | Namespaced identity remains distinct; an explicit alias merges | import | test_namespaces_keep_reused_hole_ids_apart |
| F06 | Assays arrive first | Pending companions, no invented geometry | import | test_assays_without_collars_stay_pending |
| F07 | One orphan assay | Isolated while the valid holes are accepted | import | test_an_orphan_assay_is_isolated |
| F08 | 00012, 12, DH-12 and dh-12 | Exact strings kept; normalization collisions reported | import | test_hole_ids_keep_case_and_zeros_and_collisions_are_reported |
| F09 | Semicolon, decimal comma and quoted delimiters | Declared parsing conventions preserve values | import | test_declared_dialects_preserve_values |
| F10 | Duplicate headers or malformed rows | Precise file, row and column error; no shifted values | import | test_malformed_files_fail_with_file_row_and_column |
| F11 | Feet and metres | Declared conversion: 10 ft = 3.048 m | import | test_feet_convert_exactly |
| F12 | CRS mismatch or swapped axes | Spatial incompatibility surfaced before any join | import | test_crs_mismatch_and_swapped_axes_fail_before_join |
| F13 | Vertical 100 m hole | Easting and northing unchanged, elevation 100 m lower | preprocess | test_analytic_trajectories |
| F14 | Horizontal 100 m arc, azimuth 0 to 90 degrees | East = North = 200/pi m | preprocess | test_analytic_trajectories |
| F15 | Azimuth 359 to 1 degrees | A 2 degree turn, never 358 | preprocess | test_analytic_trajectories |
| F16 | Opposite declared dip conventions | Same trace after explicit convention mapping | import | test_dip_conventions_give_the_same_trace |
| F17 | Conflicting duplicate survey depth | Ambiguity reported before desurvey; the hole is blocked | import | test_conflicting_survey_depths_block_the_hole |
| F18 | Missing or truncated survey | Explicit assumption and the affected depth range | import | test_missing_and_truncated_surveys_are_declared |
| F19 | Reversed, zero and negative intervals | Exactly those records excluded and reported | import | test_invalid_intervals_are_excluded_by_record |
| F20 | Within-series assay overlap | A conflict; no implicit summing or averaging | import | test_overlapping_assays_are_conflicts_not_sums |
| F21 | Parallel analyte and method supports | Overlap retained as separate observations | import | test_parallel_series_are_separate_observations |
| F22 | Lithology 0/3/5 m; assays 0/2/5 m | Fragments 0/2/3/5 m, parent lengths conserved | preprocess | test_overlay_fragments_conserve_parent_lengths |
| F23 | Grade 1 over 2 m, grade 3 over 3 m | Five-metre composite 2.2 | preprocess | test_composite_fixtures |
| F24 | Grade 2 at 0-1 m, grade 4 at 2-3 m | Coverage 2/3, observed mean 3; fails a 0.75 coverage gate | preprocess | test_composite_fixtures |
| F25 | 5.5 m support, 2 m composites | A declared 1.5 m residual | preprocess | test_composite_fixtures |
| F26 | Censored, zero, blank, not sampled, lost core and sentinel | Distinct states and a versioned eligibility rule | import | test_states_are_distinct_and_eligibility_is_versioned |
| F27 | Above 10000 ppm, then 1.2 % by an overlimit method | Both preserved; the selected overlimit value is 12000 ppm | preprocess | test_overlimit_reassay_is_selected |
| F28 | Several methods and labs, and a repeat | Explicit result selection; the repeat adds no spatial support | preprocess | test_result_selection_is_explicit |
| F29 | Standards and blanks mixed with samples | Controls receive no fabricated coordinates | import | test_controls_get_no_coordinates |
| F30 | Repeats joined to interval fragments | No many-to-many fragment expansion | preprocess | test_repeats_do_not_multiply_fragments |
| F31 | Insufficient eligible neighbours | A reasoned unestimated target; no zero-grade fallback | infer | with the infer stage |
| F32 | Dense single hole versus several holes | Per-hole and sector limits and the selected support shown | infer | with the infer stage |
| F33 | Authored anisotropic field and a rigid rotation | Estimates invariant under a joint rotation of coordinates and anisotropy | infer | with the infer stage |
| F34 | Conflicting colocated or ill-conditioned data | Conditioning failure reported; never a successful NaN | infer | with the infer stage |
| F35 | Hard versus soft domain boundary | The declared support and range rules enforced | infer | with the infer stage |
| F36 | Prior without nearby observations | An explicit prior-driven result with absent conditioning | infer | with the infer stage |
| F37 | Missing external drift or deficient rank | Unsupported model or target; no silent method switch | infer | with the infer stage |
| F38 | Conflicting orientation normals | Undefined or unstable orientation diagnosed | features | with the features stage |
| F39 | Seeded conditional realizations | Seed reproducibility and model-specific conditioning checks | infer | with the infer stage |
| F40 | Holdout with fragments and repeats | Every held-out derivative and result excluded from training | dataset | with the dataset stage |
| F41 | Cancellation, failure and an interrupted import | The previous project intact; no partial final result | import | test_an_interrupted_import_leaves_the_previous_project |
| F42 | Export, re-import and CPU and accelerated parity | Metadata, eligibility and declared tolerances preserved | export | with the export stage |

The verifying tests are in `tests/test_import.py`. Every accepted fixture project also passes the artifact check.

## Authored scenarios S01 to S12

The scenario registry `data/scenarios/registry.json` lists the 32 scenarios: Rocklea R01 to R12, Alberta A01 to A08
and the authored S01 to S12, each with its question, methods, computing stages and, for the authored ones, the
fixtures they are built from. S01 to S04 (geometry, angle boundaries, conservation and result states) run on the
stages that exist today; S05 to S12 run with the estimation, simulation and export stages.
