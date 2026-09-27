# Canonical contract, manifest importer and fixtures (SD-4): design

## 1. The canonical contract, `drillhole.project/v2`

`schemas/project.schema.json` is the normative definition; `scripts/check_artifacts.py` validates it with
`jsonschema` (Draft 2020-12) and then applies the referential rules a schema cannot express. The three source
adapters and the manifest importer write the same contract. What changes from the adapters' first form:

| Part | v2 rule | Why |
|---|---|---|
| Root | adds `qc`, `exclusions` and `waterfall` as required tables (empty when unused) | controls, excluded records and reconciliation are part of the project, not side files |
| `provenance.kind` | `field`, `user-import` or `authored-validation` | user imports and authored fixtures are labelled as such everywhere |
| `frames` | `kind` is `projected-metric` or `local-metric`; `horizontalDefinition` holds a definition that has no EPSG code (Alberta's 10TM); `origin` is the declared anchor of a local frame | one shape for all three families |
| `collars` | add `namespace`; `orientation.sourceInclination` keeps a source inclination next to the derived dip | identity across sources; no lost source value |
| `surveys` | add `id`, `azimuthReference` and `instrument`; `role` is `recorded-collar-direction`, `measured`, `compiled-extension` or `authored-validation` | the instrument is data (NTGS Reflex EZ-Shot), not part of the role name |
| `trajectories` | `startExtension` and `endExtension` are `none` or `tangent`, replacing free text | the preprocess stage reads the policy instead of assuming it |
| `supports` | add `sampleId` | one support per physical sample; repeats are separate samples on one geometry |
| `determinations` | `qualifier` is `=`, `<`, `>` or null; add `state` (measured, censored-below, censored-above, missing, not-sampled, lost-core, sentinel) and `sampleRole` (original, repeat, duplicate) | distinct states for F26; explicit repeats for F28 |
| `geology` | `kind` is `interval` or `event` (an event has `atMd`); source codes live in `codes` under their source column names; `description` is verbatim | one shape for any lithology file; codes never renamed |

Referential rules added by the check: a measured determination has a finite value and qualifier `=`; a censored one
has no value, qualifier `<` or `>` and a positive limit; any other state has no value and no qualifier; every
exclusion names an existing row; a qc determination has no support.

## 2. The manifest importer

`data-pipeline/source_adapters/manifest_import.py`, run as
`python data-pipeline/run.py ingest --manifest <import.json> [--out DIR]`. It turns an import manifest into either an
accepted canonical project or a report that says why not.

### 2.1 The manifest, `drillhole.import/v1` (`schemas/import.schema.json`)

```json
{
  "schema": "drillhole.import/v1",
  "project": {"id": "demo", "name": "Demo"},
  "frame": {"id": "site", "kind": "projected-metric", "horizontalCrs": "EPSG:32719"},
  "files": [
    {"path": "collars.csv", "role": "collar", "namespace": "a",
     "dialect": {"delimiter": ",", "quote": "\"", "decimal": ".", "encoding": "utf-8"},
     "missing": [""], "lengthUnit": "m", "elevationUnit": "m", "crs": "EPSG:32719", "axisOrder": "east-north",
     "columns": {"hole": "HoleID", "x": "East", "y": "North", "z": "RL", "totalDepth": "Depth",
                 "azimuth": "Azi", "dip": "Dip"},
     "angles": {"dip": "negative-down", "azimuthReference": "grid"}},
    {"path": "assays.csv", "role": "assay", "namespace": "a",
     "columns": {"hole": "HoleID", "from": "From", "to": "To", "sample": "SampleID", "sampleType": "Type"},
     "analytes": {"Cu_ppm": {"analyte": "Cu", "unit": "ppm", "method": "ICP", "lab": "L1"}},
     "states": {"NS": "not-sampled", "LC": "lost-core", "-9999": "sentinel"},
     "controls": {"STD": "standard", "BLK": "blank"},
     "repeats": {"REP": "repeat", "DUP": "duplicate"}}
  ],
  "aliases": {"b:DH-12": "a:DH12"},
  "resolutions": {"collars": {"a:DH1": "collars_b.csv"}},
  "exclude": ["a:DH9"],
  "assumptions": {"missingSurvey": "collar-orientation", "surveyStart": "tangent"},
  "methodPriority": {"Cu": ["OL-ICP", "ICP"]}
}
```

Roles: `collar`, `survey`, `assay`, `lithology`. Lengths (depths, total depth, from, to) convert from `ft` by exactly
0.3048; elevations by the same factor when `elevationUnit` is `ft`; planar coordinates stay in the CRS unit. Dip
conventions: `negative-down` (kept), `positive-down` (negated), `inclination-from-vertical` (0 is straight down:
dip = inclination - 90).

### 2.2 Flow

1. **Validate the manifest** against its schema before opening any file (R-419).
2. **Read every file** with its declared dialect: strict CSV (`csv.DictReader(strict=True)`), header checks
   (duplicate or blank names fail with the file and columns), ragged rows fail with the file and row, a decimal comma
   is converted only in mapped numeric columns, missing tokens are declared. The SHA-256 of each file is recorded; a
   file whose hash equals an earlier one is skipped and reported (R-421).
3. **Identity.** A hole key is `namespace:sourceId`, the source identifier kept as an exact string. Aliases map keys
   explicitly. Keys that collide after normalization (upper case, punctuation removed, leading zeros of digit runs
   removed) within the project are reported, not merged (R-426).
4. **Frame checks before joins.** Collar files must declare the same CRS; for files that do, an extent that overlaps
   another file's only after swapping axes fails as suspected swapped axes (R-430).
5. **Collars.** Records of one key from different files are compared; identical copies collapse; different versions
   are a `COLLAR_CONFLICT` error listing both and the dependent survey, assay and lithology rows, unless
   `resolutions.collars` names the file to keep (R-422).
6. **Surveys.** Angles are mapped to the internal convention (R-432); duplicate depths with equal angles collapse, with
   different angles block the hole (R-433). A hole without stations uses its recorded collar direction, or the
   declared `missingSurvey` assumption, and the report gives the affected range; with neither it is blocked (R-434).
   A first station below the collar needs `surveyStart: "tangent"`.
7. **Assays.** Each row is one sample and one support; each mapped analyte column is one determination with its state:
   a number is measured (a zero is a measured zero), `<x` and `>x` are censored with limit x, and declared tokens map
   to not-sampled, lost-core, sentinel or missing (R-440). Control rows go to `qc` with no support (R-443). Invalid
   intervals are excluded by record (R-435). Samples on unknown holes are orphans, isolated with a warning (R-425).
   Overlapping intervals of one analyte and method in one hole are a conflict: both are listed in `exclusions` (R-436);
   different analytes or methods overlap freely (R-437).
8. **Lithology.** Intervals and events with their mapped code columns kept verbatim in `codes`.
9. **Decide.** Any error finding not resolved or excluded makes the status `rejected`; a missing collar role makes it
   `pending` (R-424); otherwise `accepted`. Only an accepted import writes a project.
10. **Commit.** Outputs are written to a staging directory and swapped in with an atomic rename; a cancellation
    callback is checked between files and records. A cancelled or failed import removes its staging directory and
    leaves the previous project untouched (R-445).

### 2.3 The report, `drillhole.import-report/v1`

Status, files (path, role, SHA-256, rows, duplicate-of), findings (code, severity, file, role, hole, rows, message),
counts by file, role, hole, severity and code, and the accepted, excluded, blocked and pending holes.

| Code | Severity | Scope | Resolution |
|---|---|---|---|
| `MANIFEST_INVALID`, `HEADER_DUPLICATE`, `HEADER_BLANK`, `ROW_RAGGED`, `COLUMN_MISSING`, `NUMBER_INVALID`, `UNIT_UNKNOWN` | error | file | fix the file or the manifest |
| `CRS_MISMATCH`, `AXES_SWAPPED_SUSPECTED` | error | file | declare the CRS or the axis order |
| `COLLAR_CONFLICT`, `SURVEY_DEPTH_CONFLICT`, `SURVEY_MISSING_UNASSUMED` | error | hole | resolve in the manifest or exclude the hole |
| `ASSAY_OVERLAP` | warning | records | excluded from modeling until a policy selects one |
| `ORPHAN_ASSAY`, `ORPHAN_SURVEY`, `ORPHAN_LITHOLOGY`, `INTERVAL_INVALID` | warning | records | excluded, listed |
| `ID_NORMALIZATION_COLLISION`, `FILE_DUPLICATE`, `RECORD_DUPLICATE`, `SURVEY_ASSUMED`, `SURVEY_START_EXTENDED` | warning | hole or file | informational, listed |
| `UNIT_CONVERTED`, `ANGLES_MAPPED`, `ALIAS_APPLIED`, `COLLAR_CONFLICT_RESOLVED`, `HOLE_EXCLUDED` | info | file or hole | none |

## 3. Preprocess additions

- **Result selection** per distinct support geometry and analyte, across repeat samples (R-441, R-442): measured
  results only; an above-range result with a measured re-assay on the same sample or geometry selects the re-assay;
  several measured results from different methods or labs select by `methodPriority`, else stay unresolved; a repeat
  or duplicate never replaces an original and never adds support. Units convert among ppb, ppm, g/t, % and wt%.
  The `selections` table records the chosen determination and the rule; `unresolved` lists the rest.
- **Eligibility v1** (R-440): only selected measured values enter compositing and populations; every other state is
  counted per analyte.
- **Overlay fragments** (R-438, R-444): interval supports cut at log boundaries per distinct geometry, each fragment
  with its parent support geometry, its logs and their codes; parent lengths are conserved.
- **Compositing parameters** come from the project recipe or the run: lengths and minimum coverage (1 for the field
  families); an insufficient composite also reports its observed mean (numerator over valid length) (R-439).
- **Trajectories** follow `startExtension` and `endExtension` from the project, and report extended ranges (R-434).

## 4. Registries

- `data/fixtures/<ID>/` holds each fixture's files, `import.json` and `expected.json`; `data/fixtures/registry.json`
  lists F01 to F42 with construction, expected outcome, owning stage and the test that verifies it. Stages not yet
  built are listed in the registry; the registry test fails when a built stage owns an unverified fixture (R-461).
- `data/scenarios/registry.json` lists the 32 scenarios with family, question, methods and computing stages (R-462).
