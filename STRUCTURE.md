# Repository structure

Sondara is a product repository of the CAOS archetype (ADR-0057): an offline pipeline that does the science, a
static web page that will replay its exported artifacts, and one engine package, GeoCond, which lives in its own
repository and is installed from PyPI. This page maps the tree as it is; the build units that change it are listed in
[the design](docs/design/SDD.md).

```
data-pipeline/            the offline pipeline, run by path: python data-pipeline/run.py <stage>
  run.py                  the ten stages: acquire, ingest, preprocess, dataset, features, train, infer, evaluate
                          (export and validate come with unit SD-8)
  source_io.py            downloads, byte and hash checks, JSON and table readers, stable hashes
  source_adapters/        Rocklea, Alberta and NTGS into the canonical project; the manifest importer for user files
  stages/                 preprocess, dataset, features, models, estimators, train, infer, evaluate, scenarios;
                          categories, training_images, mps, categorical (the categorical lane); learned (the learned lane)
  learned/                the learned methods' binding, transforms, networks, fits and audited ONNX export
  requirements.txt        the pipeline's pins, GeoCond among them
data/                     source declarations, the bundled NTGS subset, fixtures, the scenario registry (data/README.md)
schemas/                  project.schema.json (drillhole.project/v2) and import.schema.json (drillhole.import/v1)
scripts/                  artifact, SDD, content, residue and CI-budget checks; figures; the fixture author
tests/                    one file per stage and contract, and the authored field the estimation tests share
docs/                     the product wiki: architecture, design (SDD and feature designs), cases, frameworks, guides
frontend/                 the web page (Vite, React); still the 0.2 workbench until the web unit (SD-9)
app/                      a dormant FastAPI module; no request-time backend is needed
deploy/                   the nginx site and the Pages notes for sondara.ml.fasl-work.com
```

Derived outputs are never committed: the pipeline writes them to `build/derived/` (or `--out`), and raw downloads go
to `$SONDARA_RAW` outside the repository. Two virtual environments keep the lanes apart: `.venv-pipeline`
(`requirements-precompute.txt`, Python 3.12, the pipeline and its tests) and `.venv-gpu` (`requirements-gpu.txt`: the
pipeline plus PyTorch CUDA, onnx and ONNX Runtime, for the learned lane and the S11 check).
