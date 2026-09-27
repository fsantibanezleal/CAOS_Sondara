# Canonical contract, manifest importer and fixtures (SD-4): requirements

The unit ships in two releases: the canonical contract `drillhole.project/v2` (0.05.000), then the manifest importer
and the fixture and scenario registries (0.06.000). Fixtures F01 to F42 come from the data dossier's importer and QA
catalogue; the stage that owns each one verifies it.

## Canonical contract (0.05.000)

```
R-401  THE file schemas/project.schema.json SHALL be the one normative definition of the canonical project, and
       every ingested family SHALL validate against it.
       Gate: tests/test_contract.py::test_every_family_validates_against_the_schema

R-402  IF a project violates the schema or a referential rule, THEN THE artifact check SHALL fail and name the
       violation.
       Gate: tests/test_ingest.py::test_the_contract_check_accepts_the_ingest_and_rejects_each_corruption

R-403  THE determination state SHALL distinguish measured, censored-below, censored-above, missing, not-sampled,
       lost-core and sentinel results; only measured results SHALL carry a value, and censored results SHALL carry
       their qualifier and a positive limit.
       Gate: tests/test_contract.py::test_states_and_qualifiers_are_consistent

R-404  THE survey roles SHALL separate recorded collar directions, measurements and compiled extensions, and the
       desurvey SHALL use only recorded collar directions and measurements as stations.
       Gate: tests/test_contract.py::test_only_measured_rows_and_collar_directions_are_stations

R-405  THE geology table SHALL keep every source code verbatim under its source column name.
       Gate: tests/test_contract.py::test_geology_keeps_source_codes_verbatim
```

## Manifest importer (0.06.000)

```
R-419  WHEN an import manifest does not validate against schemas/import.schema.json, THE importer SHALL reject it
       before reading any file.
       Gate: tests/test_import.py::test_the_manifest_is_validated_before_reading

R-420  WHEN the same records arrive split across several files per role, in any file or row order, THE importer
       SHALL produce the same canonical content as the consolidated files (F01, F02).
       Gate: tests/test_import.py::test_split_and_reordered_files_equal_the_consolidated_import

R-421  WHEN an identical file is supplied twice, THE importer SHALL add no measurement and SHALL report the duplicate
       (F03).
       Gate: tests/test_import.py::test_a_repeated_file_adds_no_measurement

R-422  IF two collar files give different versions of one hole, THEN THE importer SHALL report both versions and the
       affected records and SHALL NOT accept the import until the manifest records a resolution (F04).
       Gate: tests/test_import.py::test_conflicting_collars_block_until_resolved

R-423  THE importer SHALL key holes by namespace and source identifier, and SHALL merge two identifiers only through
       an explicit alias (F05).
       Gate: tests/test_import.py::test_namespaces_keep_reused_hole_ids_apart

R-424  WHILE no collar file has been supplied, THE importer SHALL report the import as pending and SHALL NOT create any
       geometry (F06).
       Gate: tests/test_import.py::test_assays_without_collars_stay_pending

R-425  IF an assay names a hole with no collar, THEN THE importer SHALL isolate that record and accept the valid holes
       (F07).
       Gate: tests/test_import.py::test_an_orphan_assay_is_isolated

R-426  THE importer SHALL keep hole identifiers as exact strings and SHALL report identifiers that collide after case,
       punctuation and leading-zero normalization (F08).
       Gate: tests/test_import.py::test_hole_ids_keep_case_and_zeros_and_collisions_are_reported

R-427  THE importer SHALL parse each file with its declared delimiter, quote, decimal separator and encoding, so that
       semicolons, decimal commas and quoted delimiters keep their values (F09).
       Gate: tests/test_import.py::test_declared_dialects_preserve_values

R-428  IF a file has duplicate or blank headers or a row with the wrong number of fields, THEN THE importer SHALL fail
       naming the file, the row and the columns, and SHALL NOT shift any value (F10).
       Gate: tests/test_import.py::test_malformed_files_fail_with_file_row_and_column

R-429  THE importer SHALL convert declared foot lengths to metres exactly (10 ft = 3.048 m) and record the conversion
       (F11).
       Gate: tests/test_import.py::test_feet_convert_exactly

R-430  IF collar files declare different coordinate reference systems, or their extents agree only with the axes
       swapped, THEN THE importer SHALL fail before any join (F12).
       Gate: tests/test_import.py::test_crs_mismatch_and_swapped_axes_fail_before_join

R-431  THE imported and preprocessed trajectories SHALL match the analytic cases: a vertical 100 m hole drops 100 m
       with unchanged easting and northing; a horizontal arc from azimuth 0 to 90 degrees over 100 m ends 200/pi m
       east and north; a turn from 359 to 1 degrees is a 2 degree dogleg (F13, F14, F15).
       Gate: tests/test_import.py::test_analytic_trajectories

R-432  THE importer SHALL map every declared dip convention to dip from the horizontal, negative downward, so that one
       survey in any convention gives the same trace (F16).
       Gate: tests/test_import.py::test_dip_conventions_give_the_same_trace

R-433  IF a hole has two survey records at one depth with different angles, THEN THE importer SHALL block that hole
       before desurvey; identical duplicates SHALL collapse with a note (F17).
       Gate: tests/test_import.py::test_conflicting_survey_depths_block_the_hole

R-434  WHERE a hole has no survey, THE importer SHALL use the recorded collar direction or a declared assumption and
       report the affected depth range, and IF neither exists, THEN the hole SHALL be blocked; WHERE stations end
       above the deepest record, THE preprocess stage SHALL report the extended range (F18).
       Gate: tests/test_import.py::test_missing_and_truncated_surveys_are_declared

R-435  IF an interval is reversed, zero-length or negative, THEN THE importer SHALL exclude exactly that record and
       report it (F19).
       Gate: tests/test_import.py::test_invalid_intervals_are_excluded_by_record

R-436  IF two intervals of one analyte and method overlap in one hole, THEN THE importer SHALL report a conflict and
       exclude both from modeling, and SHALL NOT sum or average them (F20).
       Gate: tests/test_import.py::test_overlapping_assays_are_conflicts_not_sums

R-437  THE importer SHALL keep overlapping intervals of different analytes or methods as separate observations (F21).
       Gate: tests/test_import.py::test_parallel_series_are_separate_observations

R-438  THE preprocess overlay SHALL cut supports at log boundaries so that lithology at 0/3/5 m and assays at 0/2/5 m
       give fragments at 0/2/3/5 m, with every parent's length conserved (F22).
       Gate: tests/test_import.py::test_overlay_fragments_conserve_parent_lengths

R-439  THE compositing SHALL give 2.2 for grade 1 over 2 m and grade 3 over 3 m at 5 m; coverage 2/3 and an observed
       mean of 3 that fails a 0.75 coverage gate for grades 2 at 0-1 m and 4 at 2-3 m; and a declared 1.5 m residual
       for a 5.5 m interval at 2 m (F23, F24, F25).
       Gate: tests/test_import.py::test_composite_fixtures

R-440  THE importer SHALL give censored, zero, blank, not-sampled, lost-core and sentinel results distinct states, and
       THE preprocess stage SHALL admit only measured values under a named, versioned eligibility rule (F26).
       Gate: tests/test_import.py::test_states_are_distinct_and_eligibility_is_versioned

R-441  WHEN an above-range result has an overlimit re-assay on the same sample, THE preprocess stage SHALL keep both
       and select the re-assay converted to the analyte unit (>10000 ppm and 1.2 % select 12000 ppm) (F27).
       Gate: tests/test_import.py::test_overlimit_reassay_is_selected

R-442  WHEN one sample has results from several methods or laboratories, THE preprocess stage SHALL select one only
       under a declared method priority, and otherwise SHALL leave it unresolved; a repeat SHALL add no support (F28).
       Gate: tests/test_import.py::test_result_selection_is_explicit

R-443  THE importer SHALL place standards and blanks in the quality-control table with no hole and no coordinates
       (F29).
       Gate: tests/test_import.py::test_controls_get_no_coordinates

R-444  THE overlay SHALL cut each distinct support geometry once, so repeats on one interval do not multiply fragments
       (F30).
       Gate: tests/test_import.py::test_repeats_do_not_multiply_fragments

R-445  IF an import is cancelled or fails, THEN THE previous project SHALL stay intact and no partial output SHALL
       remain (F41).
       Gate: tests/test_import.py::test_an_interrupted_import_leaves_the_previous_project
```

## Registries (0.06.000)

```
R-460  THE fixture registry SHALL enumerate F01 to F42, each with its construction, its expected outcome and the stage
       that verifies it.
       Gate: tests/test_fixtures.py::test_every_fixture_is_enumerated

R-461  WHEN a stage is built, every fixture it owns SHALL name a verification that exists; only fixtures owned by
       stages not yet built MAY be unverified.
       Gate: tests/test_fixtures.py::test_fixtures_of_built_stages_are_verified

R-462  THE scenario registry SHALL enumerate R01 to R12, A01 to A08 and S01 to S12, each with its family, question,
       methods and the stages that compute it.
       Gate: tests/test_fixtures.py::test_every_scenario_is_enumerated
```
