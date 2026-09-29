# Frameworks

One card per research-chosen engine or library. Every engine the pipeline uses gets a card here and an exact pin in
the matching requirements file.

- [01, GeoCond](frameworks/01_geocond/geocond.md): geometry, compositing, covariance, kriging, simulation and Direct
  Sampling; pinned in `data-pipeline/requirements.txt`.
- [02, MPSlib](frameworks/02_mpslib/mpslib.md): SNESIM from a pinned commit, built by `scripts/build_mpslib.sh` with a
  receipt, run as a supervised subprocess.
- [03, PyTorch and ONNX](frameworks/03_pytorch-onnx/pytorch-onnx.md): the learned methods' training, the ONNX export
  with its audit, and the CPU, CUDA and ONNX parity; pinned in `requirements-gpu.txt`.
- [Card template](frameworks/00_TEMPLATE.md), copied per engine to `frameworks/<NN>_<tool>/<tool>.md`.
