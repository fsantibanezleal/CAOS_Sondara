# Guide, bring your own data

Sondara imports your own collar, survey, assay and lithology files through an import manifest. The import is a
transaction: it either produces an accepted canonical project, or a report that says exactly what stops it. Nothing
is repaired silently and no value is invented.

## 1. Describe the files

Write an import manifest (`drillhole.import/v1`, schema in [`schemas/import.schema.json`](../../schemas/import.schema.json))
next to your files. One entry per file, several files per role allowed:

```json
{
  "schema": "drillhole.import/v1",
  "project": {"id": "my-site", "name": "My site"},
  "frame": {"id": "site", "kind": "projected-metric", "horizontalCrs": "EPSG:32719"},
  "namespace": "site",
  "files": [
    {"path": "collars.csv", "role": "collar", "crs": "EPSG:32719",
     "columns": {"hole": "HoleID", "x": "East", "y": "North", "z": "RL", "totalDepth": "Depth",
                 "azimuth": "Azimuth", "dip": "Dip"},
     "angles": {"dip": "negative-down", "azimuthReference": "grid"}},
    {"path": "surveys.csv", "role": "survey",
     "columns": {"hole": "HoleID", "depth": "Depth", "azimuth": "Azimuth", "dip": "Dip"},
     "angles": {"dip": "negative-down", "azimuthReference": "grid", "instrument": "gyro"}},
    {"path": "assays.csv", "role": "assay",
     "columns": {"hole": "HoleID", "sample": "SampleID", "from": "From", "to": "To", "sampleType": "Type"},
     "analytes": {"Cu_ppm": {"analyte": "Cu", "unit": "ppm", "method": "ICP", "lab": "L1"}},
     "states": {"NS": "not-sampled", "LC": "lost-core", "-9999": "sentinel"},
     "controls": {"STD": "standard", "BLK": "blank"},
     "repeats": {"REP": "repeat", "DUP": "duplicate"}},
    {"path": "lithology.csv", "role": "lithology",
     "columns": {"hole": "HoleID", "from": "From", "to": "To", "description": "Notes"}, "codes": ["Lith"]}
  ],
  "methodPriority": {"Cu": ["OL-ICP", "ICP"]},
  "compositing": {"lengths": [1, 2, 5], "minCoverage": 1}
}
```

| Setting | Meaning |
|---|---|
| `dialect` | `delimiter`, `quote`, `decimal` (`.` or `,`) and `encoding`; nothing is guessed |
| `missing` | tokens that mean an empty value in this file |
| `lengthUnit`, `elevationUnit` | `m` or `ft`; feet convert by exactly 0.3048 |
| `crs`, `axisOrder` | every collar file must declare the same reference system; `north-east` swaps the first two coordinate columns |
| `angles.dip` | `negative-down`, `positive-down` or `inclination-from-vertical` (0 is straight down) |
| `namespace`, `aliases` | holes are keyed `namespace:ID` with the ID kept exactly; an alias is the only way to merge two keys |
| `resolutions.collars` | which file's version of a conflicting collar to keep |
| `exclude` | holes left out, with all their records, and reported |
| `assumptions` | `missingSurvey` (`collar-orientation` or `vertical`) and `surveyStart: "tangent"`, each reported with the depth range it affects |
| `states`, `controls`, `repeats` | tokens for non-results, control sample types and repeat sample types |
| `methodPriority`, `compositing` | used by the preprocess stage to select one result per sample and to composite |

Assay cells become results with a state: a number is measured (zero included), `<x` and `>x` are censored with limit
x, and the declared tokens are not-sampled, lost-core, sentinel or missing.

## 2. Import

```sh
.venv-pipeline/Scripts/python data-pipeline/run.py ingest --manifest path/to/import.json
```

The run always writes `build/derived/<project id>.import-report.json`. Its status is one of:

| Status | Meaning | What to do |
|---|---|---|
| `accepted` | the project is in `build/derived/<project id>/`, replacing the previous one atomically | preprocess it |
| `rejected` | at least one error remains; the previous project is untouched | fix the file or the manifest, or exclude the named holes |
| `pending` | no collar file yet; no geometry is created | add the collar file |

Findings are listed by file, role, hole, severity and reason. File errors (headers, ragged rows, invalid numbers,
reference systems, swapped axes) need the file or the manifest fixed; hole errors (collar conflicts, survey depth
conflicts, surveys with no assumption) can be resolved or the hole excluded. Warnings (orphans, invalid intervals,
overlapping assays, assumed or truncated surveys, identifier collisions, duplicates) do not block the import and
stay in the project's issue table.

## 3. Preprocess and check

```sh
.venv-pipeline/Scripts/python data-pipeline/run.py preprocess --family my-site
.venv-pipeline/Scripts/python scripts/check_artifacts.py
```

The stage desurveys every hole, positions every sample, selects one result per sample geometry and analyte (a
re-assay over an above-range result, or the declared method priority; repeats never), composites per analyte, cuts
samples at log boundaries and names the modeling populations. See
[the precompute pipeline](../architecture/05_precompute-pipeline.md) for the output and
[the fixtures](../cases/fixtures.md) for a worked example of every behaviour.
