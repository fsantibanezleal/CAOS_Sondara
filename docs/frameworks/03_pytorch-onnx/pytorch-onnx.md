# Framework card, PyTorch and ONNX (the learned methods)

## What and why

The learned methods (unit SD-7) are trained with [PyTorch](https://pytorch.org) and shipped as
[ONNX](https://onnx.ai) models checked with [ONNX Runtime](https://onnxruntime.ai):

- **PyTorch** trains DeepKriging and KCN on the CUDA device (or the CPU) from the same code, with dense tensors only:
  KCN's graphs have a fixed size (the query and at most K neighbours), so they are batched as dense adjacency
  matrices and no graph library (PyTorch Geometric) is needed.
- **ONNX** is the exchange format: each fitted seed is exported with its features computed inside the graph (the
  Wendland basis for DeepKriging, eqs. 9 and 3 of the KCN paper), so a browser (ONNX Runtime Web, unit SD-9) runs the
  same computation from raw positions and values.
- **ONNX Runtime** on the CPU checks every exported model against PyTorch on the held-out inputs.

The methods are independent implementations of the published equations (Chen, Li, Reich and Sun, Statistica Sinica
2024, doi:10.5705/ss.202021.0277; Appleby, Liu and Liu, AAAI 2020, doi:10.1609/aaai.v34i04.5716). The authors'
repositories carry no license and nothing is copied from them.

## Install (exact, verified)

`requirements-gpu.txt`, installed in `.venv-gpu` (`./scripts/setup.sh --gpu`):

| Package | Pin | Role |
|---|---|---|
| torch | 2.14.0 (`+cu126`, from the PyTorch CUDA 12.6 index) | training, the reference predictions, CUDA parity |
| onnx | 1.22.0 | the exported graph, the audit and `onnx.checker` (full check) |
| onnxscript | 0.7.2 | required by the torch.export exporter |
| onnxruntime | 1.29.0 | the CPU parity check |

Verified on 2026-09-28 on an RTX 4070 Laptop GPU (8 GB), Windows 11, Python 3.12: `torch.cuda.is_available()` true,
the export probe of the research (in the management repository, `wip/drillhole-workbench/learned-methods-2026-09-28.md`,
section 4) and the tests of `tests/test_learned.py`.

## Usage

```python
from learned.networks import DeepKriging, KCN
from learned.exporting import export_model, validate_portable

model = DeepKriging(basis, widths=[128, 64, 32], dropout=0.1, mean=32.5, scale=18.0)
native = model(torch.as_tensor(xyz_minus_origin, dtype=torch.float32))      # (batch,) in the target's unit
manifest = export_model(model, (xyz_minus_origin,), ["local"], folder, metadata, tolerance=1e-4 * 18.0)
```

`export_model` writes `model.onnx`, `parity.json` (the maximum ONNX Runtime and CUDA differences on every input and a
fixture of the first 64), `manifest.json` (the binding, the transforms, the audit) and `portable-model.zip`.
`validate_portable` checks an archive before anything reads it.

## Applying it here

**The exporter.** `torch.onnx.export(..., dynamo=True)` (torch.export, the default since PyTorch 2.9) at opset 18 with
a dynamic batch dimension shared by every input. The TorchScript exporter still works in 2.14 and warns that it will be
removed, so it is not used. Two facts found in the probe: the exporter prints a check-mark character that a Windows
cp1252 console cannot encode (the pipeline captures its output), and it writes each node's Python stack trace, with
local file paths, into the node metadata (the pipeline removes every metadata field and doc string, and the audit
refuses a model whose strings still look like a path).

**The audit** (`learned/exporting.audit_model`, applied at export and again by `scripts/check_artifacts.py`): standard
domain only, no control flow (`Loop`, `Scan`, `If`, `SequenceMap`), no local functions, no external data, at most
2,000 nodes and 8 MiB, `onnx.checker` full check, no path in any string. The exported operators are ordinary
arithmetic (`Add`, `Sub`, `Mul`, `Div`, `Pow`, `Sqrt`, `Exp`, `Max`, `ReduceSum`, `Gemm`, `MatMul`, `Relu`,
`Concat`, `Gather`, `Where`, shape operators), all in ONNX Runtime Web's CPU (WASM) operator set.

**Float32.** The graphs compute in float32. Positions enter as the position minus the frozen training origin,
subtracted in float64 before the cast, so projected coordinates of millions of metres lose nothing. The in-graph basis
matches the float64 NumPy oracle within about $10^{-6}$; ONNX Runtime and CUDA match PyTorch on the CPU within about
$10^{-5}$ in native units; the tolerance is $10^{-4}$ training standard deviations.

**Training.** AdamW, batch 128, at most 400 epochs with early stopping (patience 40) on the validation hole-macro RMSE,
TF32 disabled on the device, a checkpoint every 20 epochs (`resume.pt`, with the CPU and CUDA random states) and the
best epoch's weights saved as tensors (`weights.pt`, loaded with `weights_only=True`). A fit is identified by the hash
of its recipe (configuration, seed, transforms, training rows, epochs, optimizer).

## Caveats and license

PyTorch is BSD-3-Clause; onnx, onnxscript and ONNX Runtime are MIT. They are development and pipeline dependencies:
Sondara ships the exported `.onnx` files, not the libraries. Weights trained on another device or library version can
differ in their last digits, so exported models are compared through their parity records, not by hash. An exported
model is bound to the project, frame, task and unit it was fitted on (`learned.contracts.check_binding`); the same
architecture fitted elsewhere is a different model.
