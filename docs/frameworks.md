# Frameworks

One card per research-chosen engine or library. Every engine the pipeline uses gets a card here and an exact pin in
the matching requirements file.

- [01, GeoCond](frameworks/01_geocond/geocond.md): geometry, compositing, covariance, kriging, simulation and Direct
  Sampling; pinned in `data-pipeline/requirements.txt`.
- [Card template](frameworks/00_TEMPLATE.md), copied per engine to `frameworks/<NN>_<tool>/<tool>.md`.

The engines of the later units (MPSlib for SNESIM, PyTorch and ONNX Runtime for the learned methods) get their cards
with the units that pin them.
