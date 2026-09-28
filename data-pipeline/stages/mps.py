"""SNESIM through MPSlib's compiled `mps_snesim_tree`, run as a supervised subprocess in a job directory.

Design: docs/design/features/categorical-simulation/design.md, section 4. MPSlib (Hansen, Vu and Bach 2016,
doi:10.1016/j.softx.2016.07.001) at the pinned commit is built by ``scripts/build_mpslib.sh``; this module writes the
parameter file in the pinned schema (``mps_snesim.txt`` of that commit), the training image, the hard data and the soft
data as GSLIB/EAS files, runs the executable with a timeout, and parses ``<ti>_sg_<n>.gslib``. Facts taken from the
pinned source: the seed is parsed with ``stof`` (so seeds stay below 2^24), C ``rand()`` is seeded once per run (one
run is the unit of reproducibility), coordinates map to cells by truncation (cell centres are written), a missing mask
or soft-data file switches that input off, and the thread parameter is inactive (the subprocess is the resource
boundary). On Windows the Linux executable runs through ``wsl.exe`` with translated paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
from source_io import ROOT

COMMIT = "a47718fc0e2c7c6f3411de429e51f1267b5d7f7c"
ENGINE = "mps_snesim_tree"
SEED_LIMIT = 2 ** 24
DEFAULTS = {"multiple_grids": 3, "min_node_count": 0, "max_conditioning": 40, "template": (7, 7, 5),
            "shuffle_path": 1, "shuffle_ti_path": 1}


class MpslibError(RuntimeError):
    pass


def location() -> Path:
    return Path(os.environ.get("SONDARA_MPSLIB", ROOT / "build" / "mpslib"))


def receipt(where: Path | None = None) -> dict | None:
    """The build receipt written by scripts/build_mpslib.sh, or None when MPSlib is not built."""
    path = (where or location()) / "receipt.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def available() -> bool:
    r = receipt()
    return r is not None and r.get("commit") == COMMIT and (location() / ENGINE).is_file()


def _windows() -> bool:
    return platform.system() == "Windows"


def _linux_path(path: Path) -> str:
    """The path the executable sees: unchanged on Linux, /mnt/<drive>/... under WSL."""
    p = Path(path).resolve()
    if not _windows():
        return p.as_posix()
    drive = p.drive.rstrip(":").lower()
    return f"/mnt/{drive}/" + "/".join(p.parts[1:])


def write_gslib(path: Path, grid: np.ndarray, name: str = "facies"):
    """GSLIB grid: the dimensions on the title line, one variable, values with x fastest, then y, then z."""
    nx, ny, nz = grid.shape
    values = np.asarray(grid).transpose(2, 1, 0).ravel()  # z slowest, x fastest
    body = "\n".join(str(int(v)) if float(v).is_integer() else repr(float(v)) for v in values)
    path.write_text(f"{nx} {ny} {nz}\n1\n{name}\n{body}\n", encoding="utf-8", newline="\n")


def read_gslib(path: Path, shape) -> np.ndarray:
    """Every whitespace token after the header (the output may put all values on one line)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    n = int(lines[1].split()[0])
    tokens = " ".join(lines[2 + n:]).split()
    values = np.array([float(t) for t in tokens])
    if values.size != int(np.prod(shape)):
        raise MpslibError(f"{path.name}: {values.size} values for a grid of {int(np.prod(shape))}")
    return values.reshape(shape[2], shape[1], shape[0]).transpose(2, 1, 0)


def write_points(path: Path, rows, names):
    """EAS points: title, column count, one name per line, then one row per point."""
    lines = ["sondara", str(len(names)), *names]
    lines += [" ".join(repr(float(v)) for v in row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def parameter_file(*, realizations, seed, shape, ti_name, out_dir, hard_name, soft_name, categories, options) -> str:
    """The pinned `mps_snesim.txt` schema, one line per entry, value after `#`."""
    o = {**DEFAULTS, **options}
    tx, ty, tz = o["template"]
    lines = [
        ("Number of realizations", realizations),
        ("Random Seed (0 `random` seed)", seed),
        ("Number of mulitple grids (start from 0)", o["multiple_grids"]),
        ("Min Node count (0 if not set any limit)", o["min_node_count"]),
        ("Maximum number condtitional data (0: all)", o["max_conditioning"]),
        ("Search template size X", f"{tx} {tx}"),
        ("Search template size Y", f"{ty} {ty}"),
        ("Search template size Z", f"{tz} {tz}"),
        ("Simulation grid size X", shape[0]), ("Simulation grid size Y", shape[1]),
        ("Simulation grid size Z", shape[2]),
        ("Simulation grid world/origin X", 0), ("Simulation grid world/origin Y", 0),
        ("Simulation grid world/origin Z", 0),
        ("Simulation grid grid cell size X", 1), ("Simulation grid grid cell size Y", 1),
        ("Simulation grid grid cell size Z", 1),
        ("Training image file (spaces not allowed)", ti_name),
        ("Output folder (spaces in name not allowed)", out_dir),
        ("Shuffle Simulation Grid path (0: sequential, 1: random, 2: preferential, EF)", o["shuffle_path"]),
        ("Shuffle Training Image path (1 : random, 0 : sequential)", o["shuffle_ti_path"]),
        ("HardData filename  (same size as the simulation grid)", hard_name),
        ("HardData seach radius (world units)", 1),
        ("Softdata categories (separated by ;)", ";".join(str(c) for c in categories)),
        ("Soft datafilenames (separated by ; only need (number_categories - 1) grids)", soft_name),
        ("Number of threads (not currently used)", 1),
        ("Debug mode(2: write to file, 1: show preview, 0: show counters, -1: no )", -1),
        ("Mask grid filename (same size as the simulation grid)", "nomask.dat"),
        ("do Entropy", 0),
        ("do Estimation", 0),
    ]
    return "".join(f"{k} # {v}\n" for k, v in lines)


def simulate(ti: np.ndarray, shape, *, realizations: int, seed: int, hard=None, soft=None, job_dir: Path,
             categories=None, options=None, timeout: float = 1800.0) -> tuple[np.ndarray, dict]:
    """``realizations`` SNESIM realizations (uint8, (n, nx, ny, nz)) from one supervised run, and its receipt.

    ``hard`` is ``(cells (m, 3) int, categories (m,))``; ``soft`` is an (nx, ny, nz, K) array of probabilities over
    ``categories`` (or None). Every hard cell is checked in every realization.
    """
    if not available():
        raise MpslibError(f"MPSlib {COMMIT[:8]} is not built at {location()}; run scripts/build_mpslib.sh")
    if not 0 < seed < SEED_LIMIT:
        raise MpslibError(f"the seed must lie in (0, 2^24): MPSlib parses it as a float (got {seed})")
    categories = sorted(int(c) for c in (categories if categories is not None else np.unique(ti)))
    job = Path(job_dir)
    if job.exists():
        shutil.rmtree(job)
    (job / "out").mkdir(parents=True)
    write_gslib(job / "ti.dat", ti)
    hard_rows = [] if hard is None else [(i + 0.5, j + 0.5, k + 0.5, c) for (i, j, k), c in zip(*hard, strict=True)]
    write_points(job / "hard.dat", hard_rows, ["X", "Y", "Z", "D"])
    if soft is not None:
        rows = []
        for i, j, k in np.ndindex(*shape):
            rows.append((i + 0.5, j + 0.5, k + 0.5, *soft[i, j, k]))
        write_points(job / "soft.dat", rows, ["X", "Y", "Z", *[f"P{c}" for c in categories]])
    text = parameter_file(realizations=realizations, seed=seed, shape=shape, ti_name=_linux_path(job / "ti.dat"),
                          out_dir=_linux_path(job / "out"), hard_name=_linux_path(job / "hard.dat"),
                          soft_name=_linux_path(job / "soft.dat") if soft is not None else _linux_path(job / "nosoft.dat"),
                          categories=categories, options=options or {})
    (job / "snesim.txt").write_text(text, encoding="utf-8", newline="\n")
    exe = location() / ENGINE
    command = [_linux_path(exe), _linux_path(job / "snesim.txt")]
    if _windows():
        distro = os.environ.get("SONDARA_WSL_DISTRO")
        command = ["wsl.exe", *(["-d", distro] if distro else []), "--exec", *command]
    t0 = time.time()
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise MpslibError(f"SNESIM exceeded its {timeout:.0f} s limit") from error
    seconds = time.time() - t0
    outputs = [job / "out" / f"ti.dat_sg_{n}.gslib" for n in range(realizations)]
    missing = [p.name for p in outputs if not p.is_file()]
    if done.returncode != 0 or missing:
        raise MpslibError(f"SNESIM failed (exit {done.returncode}; missing {missing[:3]}): {done.stdout[-400:]}"
                          f"{done.stderr[-400:]}")
    fields = np.stack([read_gslib(p, shape) for p in outputs]).astype(np.int16)
    if not np.isin(fields, categories).all():
        raise MpslibError("a realization holds a value that is not a training-image category")
    fields = fields.astype(np.uint8)
    if hard is not None:
        cells, cats = np.asarray(hard[0]), np.asarray(hard[1])
        kept = fields[:, cells[:, 0], cells[:, 1], cells[:, 2]] == cats[None, :]
        if not kept.all():
            raise MpslibError(f"{int((~kept).sum())} hard cells were changed by SNESIM")
    build = receipt()
    return fields, {"engine": ENGINE, "commit": COMMIT, "executableSha256": build["executables"][ENGINE]["sha256"],
                    "seed": seed, "realizations": realizations, "options": {**DEFAULTS, **(options or {})},
                    "seconds": round(seconds, 2), "parameterFile": text,
                    "parameterSha256": hashlib.sha256(text.encode()).hexdigest(),
                    "outputSha256": hashlib.sha256(fields.tobytes()).hexdigest(), "soft": soft is not None,
                    "hardCells": 0 if hard is None else len(hard[1])}
