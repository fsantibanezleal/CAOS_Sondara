# Learned regression (SD-7a): tasks

| # | Task | Satisfies | Release |
|---|---|---|---|
| 1 | Audit fixes in `data-pipeline/learned/`: remove the 0.2 split and `modeling-samples` schema (L-2), move the KCN graph to metres with the paper's self weight (L-6), add the paper's knot levels (L-7), make thread count a setting (L-8) | R-701, R-702, R-706 | 0.11.000 |
| 2 | `learned/networks.py`: DeepKriging with the basis in the graph, KCN with eqs. 9 and 3 in the graph, native-unit outputs | R-704, R-706 | 0.11.000 |
| 3 | `stages/learned.py`: population loop, transforms, frozen search, fits with checkpoints, selection, ensemble, controls, residual band; `train` and `infer` with `--lane learned` | R-701 to R-703, R-705, R-707 to R-710 | 0.11.000 |
| 4 | `learned/exporting.py` on the torch.export exporter with captured output, metadata stripping, per-seed export, manifests and parity on every held-out input | R-711 to R-714 | 0.11.000 |
| 5 | `stages/evaluate.py` scores the learned predictions; `stages/scenarios.py` computes R10 and R11's learned cells; `scripts/check_artifacts.py` learned checks | R-715 to R-717 | 0.11.000 |
| 6 | The field run on Rocklea and Alberta in `.venv-gpu`, docs (architecture 05 and 06, the Rocklea case, the PyTorch and ONNX framework cards, the GPU guide), release | all | 0.11.000 |

## Convergence

- **0.11.000:** R-701 to R-717, each gate passing in `.venv-gpu` (the CUDA gate on the RTX 4070); the field run
  records every population's selection, fits, exports and parity; `metrics.json` scores the learned methods beside
  the classical ones; the scenario matrix has no pending SD-7 cell for R10 and R11. The `Status: planned` line is then
  removed from `requirements.md`.
