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

## Manifest importer and registries (0.06.000)

Their requirements are added here with the release that builds them, each naming its test; the design is in
[design.md](design.md), sections 2 to 4.
