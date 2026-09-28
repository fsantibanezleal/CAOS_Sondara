#!/usr/bin/env python3
"""The simulation contracts S10 and S11, run on this machine and recorded as a receipt the scenario matrix reads.

    python scripts/check_simulation.py [--derived build/derived]

S10: SNESIM (MPSlib) realizations of an authored binary channel image reproduce the image's 2 x 2 pattern
frequencies, counted exhaustively (total-variation distance below 0.05). S11: the product's zoned Direct Sampling
selects the same candidate for every node on the NumPy and the PyTorch (CUDA) backends, on the Alberta hole-group case
when its categorical models exist. Run it in `.venv-gpu` (PyTorch with CUDA and the pipeline requirements); a check
that cannot run is recorded as not passed, with the reason. Writes ``<derived>/simulation-checks.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data-pipeline"))

from source_io import write_json

BOUND = 0.05


def channel_ti(nx=80, ny=80):
    x, y = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
    return (np.sin(x / 5.0 + 1.3 * np.sin(y / 8.0)) > 0.5).astype(np.uint8)[..., None]


def patterns(field):
    f = field[..., 0].astype(int)
    code = f[:-1, :-1] + 2 * f[1:, :-1] + 4 * f[:-1, 1:] + 8 * f[1:, 1:]
    return np.bincount(code.ravel(), minlength=16)


def s10() -> dict:
    from stages import mps

    if not mps.available():
        return {"passed": False, "reason": "MPSlib is not built (scripts/build_mpslib.sh, SONDARA_MPSLIB)"}
    ti = channel_ti()
    with tempfile.TemporaryDirectory() as job:
        fields, receipt = mps.simulate(ti, (50, 50, 1), realizations=20, seed=5, job_dir=Path(job) / "s10",
                                       options={"template": (7, 7, 1), "multiple_grids": 2})
    p = patterns(ti) / patterns(ti).sum()
    q = sum(patterns(f) for f in fields)
    q = q / q.sum()
    distance = float(0.5 * np.abs(p - q).sum())
    return {"passed": distance < BOUND and set(np.unique(fields)) <= {0, 1}, "totalVariation": distance,
            "bound": BOUND, "realizations": 20, "grid": [50, 50, 1], "ti": [80, 80, 1],
            "tiFrequencies": p.tolist(), "realizationFrequencies": q.tolist(), "engine": receipt["engine"],
            "commit": receipt["commit"], "executableSha256": receipt["executableSha256"]}


def s11(derived: Path) -> dict:
    try:
        import torch
    except ImportError:
        return {"passed": False, "reason": "PyTorch is not installed in this environment"}
    if not torch.cuda.is_available():
        return {"passed": False, "reason": "no CUDA device"}
    from stages.categorical import _hard, ds_realization

    models_path = derived / "alberta" / "categorical-models.json"
    if not models_path.is_file():
        return {"passed": False, "reason": "no Alberta categorical models; run data-pipeline/run.py train"}
    models = json.loads(models_path.read_text(encoding="utf-8"))
    scheme = next(s for s in models["schemes"] if s["scheme"] == "hole-group")
    image = scheme["trainingImages"][0]
    ti = np.load(derived / "alberta" / image["file"])
    cells, cats = _hard(scheme)
    shape = tuple(models["grid"]["shape"])
    out = {}
    for backend in ("numpy", "torch"):
        t0 = time.time()
        field, stats = ds_realization(ti, shape, cells, cats, seed=20260926, backend=backend)
        out[backend] = (field, stats, round(time.time() - t0, 1))
    same = bool(np.array_equal(out["numpy"][0], out["torch"][0]))
    same_candidates = out["numpy"][1]["candidateSha256"] == out["torch"][1]["candidateSha256"]
    return {"passed": same and same_candidates, "case": f"alberta hole-group {image['prior']}", "grid": list(shape),
            "nodes": out["numpy"][1]["simulated"], "identicalRealization": same,
            "identicalCandidates": same_candidates, "candidateSha256": out["numpy"][1]["candidateSha256"],
            "seconds": {"numpy": out["numpy"][2], "torch": out["torch"][2]},
            "device": torch.cuda.get_device_name(0), "torch": torch.__version__}


def main(argv=None) -> int:
    import geocond

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--derived", type=Path, default=ROOT / "build" / "derived")
    args = parser.parse_args(argv)
    receipt = {"schema": "drillhole.simulation-checks/v1", "geocond": geocond.__version__,
               "s10": s10(), "s11": s11(args.derived)}
    write_json(args.derived / "simulation-checks.json", receipt, pretty=True)
    for key in ("s10", "s11"):
        r = receipt[key]
        print(f"{key.upper()}: {'passed' if r['passed'] else 'NOT passed'} "
              f"{r.get('reason') or {k: v for k, v in r.items() if k in ('totalVariation', 'nodes', 'seconds')}}")
    return 0 if all(receipt[k]["passed"] for k in ("s10", "s11")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
