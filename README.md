# Sondara

Sondara is a drillhole scientific workbench. It combines local multi-source collar, survey, assay and geology import
with linked spatial analysis, reproducible estimation and geological simulation, on real public drillhole data.

The product uses the shared CAOS application shell and the separately published numerical library
[GeoCond](https://pypi.org/project/geocond/). It declares no internal Python distribution; the pipeline runs as scripts
by path.

## Current release

Version 0.06.000. The build follows ten units (SD-1 to SD-10); the first three stages of the offline pipeline are
complete, your own files import through a manifest ([guide](docs/guides/02_bring-your-own-data.md)), and every stage writes the canonical contract `drillhole.project/v2` defined by
[`schemas/project.schema.json`](schemas/project.schema.json):

| Stage | What it does | Families |
|---|---|---|
| `acquire` | fetches the pinned sources by URL, byte count and SHA-256, with license and attribution | all three |
| `ingest` | builds the canonical project, its QA issues and its reconciliation waterfall | all three |
| `preprocess` | desurveys every hole, positions every support, composites, overlays logs on sampling envelopes and names the modeling populations | all three |

The three field families are [Rocklea Dome](docs/cases/rocklea.md) (CSIRO, 5,035 one-metre multielement intervals in
158 holes), [Alberta MAR_19860002](docs/cases/alberta.md) (22 inclined holes with logged geology and 176 sampling
envelopes) and [NTGS 12LE002](docs/cases/ntgs.md) (one hole with eleven measured survey stations). The stages, outputs
and checks are described in [the precompute pipeline](docs/architecture/05_precompute-pipeline.md).

The public page at https://sondara.ml.fasl-work.com/ still shows the local-first workbench of the 0.2 releases, with
its authored demo cases, until the web unit (SD-9) rebuilds it on these families. It does not claim a production
resource estimate or replace QA/QC, variogram fitting or competent-person review.

## Run the pipeline

```sh
python -m venv .venv-pipeline
.venv-pipeline/Scripts/python -m pip install -r requirements-precompute.txt -r requirements-dev.txt
export SONDARA_RAW=/path/outside/the/repo
.venv-pipeline/Scripts/python data-pipeline/run.py acquire
.venv-pipeline/Scripts/python data-pipeline/run.py ingest
.venv-pipeline/Scripts/python data-pipeline/run.py preprocess
.venv-pipeline/Scripts/python scripts/check_artifacts.py
```

## Design

The design, with every requirement and the test that verifies it, is [docs/design/SDD.md](docs/design/SDD.md).

## License

MIT, see [LICENSE](LICENSE). The source data keep their own licenses and attribution, listed in
`data/sources/manifest.json` and on each case page.
