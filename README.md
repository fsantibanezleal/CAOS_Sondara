# Sondara

Sondara is a drillhole scientific workbench. It combines local multi-source collar, survey, assay and geology import
with linked spatial analysis, reproducible estimation and geological simulation, on real public drillhole data.

The product uses the shared CAOS application shell and the separately published numerical library
[GeoCond](https://pypi.org/project/geocond/). It declares no internal Python distribution; the pipeline runs as scripts
by path.

## Current release

Version 0.09.000. The build follows ten units (SD-1 to SD-10); the first eight stages of the offline pipeline are
complete for the classical methods, with every method evaluated on held-out holes and a scenario matrix that accounts
for every cell, your own files import through a manifest ([guide](docs/guides/02_bring-your-own-data.md)), and every stage writes the canonical contract `drillhole.project/v2` defined by
[`schemas/project.schema.json`](schemas/project.schema.json):

| Stage | What it does | Families |
|---|---|---|
| `acquire` | fetches the pinned sources by URL, byte count and SHA-256, with license and attribution | all three |
| `ingest` | builds the canonical project, its QA issues and its reconciliation waterfall | all three |
| `preprocess` | desurveys every hole, positions every support, selects results, composites, overlays logs and names the modeling populations | all three |
| `dataset` | freezes hole-group, spatial-margin and declared splits; every derivative follows its hole | Rocklea, Alberta (NTGS has one hole) |
| `features` | training-only statistics, declustering and experimental variograms | Rocklea, Alberta |
| `train` | covariance candidates selected on validation; LMC, indicator, residual and Gaussian-space covariances with the selected structure | Rocklea, Alberta |
| `infer` | NN, IDW, SK, OK, UK, LMC cokriging, MIK and SGS on every test target, and the scenario variants | Rocklea, Alberta |
| `evaluate` | scores against the test truths, paired hole-block comparisons with OK, variance calibration, MIK and SGS scores, and the scenario matrix | Rocklea, Alberta |

The three field families are [Rocklea Dome](docs/cases/rocklea.md) (CSIRO, 5,035 one-metre multielement intervals in
158 holes), [Alberta MAR_19860002](docs/cases/alberta.md) (22 inclined holes with logged geology and 176 sampling
envelopes) and [NTGS 12LE002](docs/cases/ntgs.md) (one hole with eleven measured survey stations). The stages, outputs
and checks are described in [the precompute pipeline](docs/architecture/05_precompute-pipeline.md), and the
evaluation, with its results and their limits, in [model evaluation](docs/architecture/06_model-evaluation.md).

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
.venv-pipeline/Scripts/python data-pipeline/run.py dataset
.venv-pipeline/Scripts/python data-pipeline/run.py features
.venv-pipeline/Scripts/python data-pipeline/run.py train
.venv-pipeline/Scripts/python data-pipeline/run.py infer
.venv-pipeline/Scripts/python data-pipeline/run.py evaluate
.venv-pipeline/Scripts/python scripts/check_artifacts.py
```

## Design

The design, with every requirement and the test that verifies it, is [docs/design/SDD.md](docs/design/SDD.md).

## License

MIT, see [LICENSE](LICENSE). The source data keep their own licenses and attribution, listed in
`data/sources/manifest.json` and on each case page.
