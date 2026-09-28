# Frameworks

One card per research-chosen engine or library. Every engine the pipeline uses gets a card here and an exact pin in
the matching requirements file.

- [01, GeoCond](frameworks/01_geocond/geocond.md): geometry, compositing, covariance, kriging, simulation and Direct
  Sampling; pinned in `data-pipeline/requirements.txt`.
- [02, MPSlib](frameworks/02_mpslib/mpslib.md): SNESIM from a pinned commit, built by `scripts/build_mpslib.sh` with a
  receipt, run as a supervised subprocess.
- [Card template](frameworks/00_TEMPLATE.md), copied per engine to `frameworks/<NN>_<tool>/<tool>.md`.

The engines of the learned methods (PyTorch and ONNX Runtime, unit SD-7) get their cards with the unit that pins them.
