# Framework card, MPSlib (SNESIM)

## What and why

[MPSlib](https://github.com/AUProbGeo/mpslib) is a C++ library of multiple-point sequential simulation from a training
image (Hansen, Vu and Bach 2016, *SoftwareX* 5, 127-133, doi:10.1016/j.softx.2016.07.001). Sondara uses its
`mps_snesim_tree` executable for SNESIM (Strebelle 2002, *Mathematical Geology* 34, 1-21, doi:10.1023/A:1014009426274):
the training image is scanned once into a search tree of pattern counts for a template, and each node is drawn from
the conditional frequencies of its informed neighbours, coarse multiple grids first.

The research of 2026-09-10 chose it as the compiled, free SNESIM: GEONE/DeeSse was excluded by its license for
industrial use, and G2S would add a native server and a CUDA build that the smaller MPSlib path does not need. Direct
Sampling, the other categorical engine, is GeoCond's (scalar and CUDA with the same candidates), so the two engines are
independent implementations of two algorithms.

## Install (exact, verified)

MPSlib is built from the pinned commit `a47718fc0e2c7c6f3411de429e51f1267b5d7f7c` with the upstream `make all`:

```powershell
$env:SONDARA_MPSLIB = "E:\_Temp\mpslib\bin"      # any folder outside the repository
.\scripts\build_mpslib.ps1                        # Windows: runs the bash script through WSL
```

```bash
export SONDARA_MPSLIB=/path/to/mpslib
./scripts/build_mpslib.sh                         # Linux or WSL: git, make and g++ (C++11)
```

The script fetches the commit, checks it, builds, copies `mps_snesim_tree`, `mps_snesim_list` and `mps_genesim` and
the LGPL license beside them, and writes `receipt.json` with the commit, compiler, make, system and the bytes and
SHA-256 of each executable. Built on 2026-09-27 in WSL Ubuntu 24.04 with g++ 13.3.0 and make 4.3: `mps_snesim_tree`
2,787,584 bytes, SHA-256 `b766ad0210949dde49b097892dc2e8498f299963d81529e2c131a67cb31f7fbd`, identical in two builds
in different folders. A build of 2026-09-10 on another toolchain differed by a few dozen bytes, so the pipeline
records its own receipt and verifies behaviour by tests, not by a published hash.

## Usage

```python
from stages import mps

fields, receipt = mps.simulate(ti, (34, 38, 24), realizations=32, seed=3483710, hard=(cells, categories),
                               soft=soft, categories=[0, 1, 2, 3, 4], job_dir=job)
```

`fields` is a `(32, nx, ny, nz)` array of category codes; `receipt` holds the commit, the executable's hash, the seed,
the parameter file and its hash, the seconds and the output hash.

## Applying it here

The `infer` stage runs one supervised SNESIM run per split scheme and prior (`stages/categorical.py`), each in its own
job directory with a timeout, the four runs in parallel. `stages/mps.py` writes the parameter file in the pinned
schema, the training image as GSLIB (dimensions on the title line, x fastest), the hard data and the soft data as EAS
points at cell centres, runs the executable (through `wsl.exe` with translated paths on Windows), parses
`ti.dat_sg_<n>.gslib`, and fails if any hard cell changed or a value is not a training-image category. Settings: three
multiple grids, a 7 x 7 x 5 template, at most 40 conditioning nodes, random path.

Facts read from the pinned source that the runner depends on: the seed is parsed with `stof`, so seeds stay below
2^24; `srand(seed)` seeds C `rand()` once per run, so the realizations of one run form one stream and one run is the
unit of reproducibility; coordinates map to cells by truncation; a missing mask or soft file switches that input off;
the hard-data search radius is replaced by the largest template size; the thread parameter is inactive.

**Soft data.** `_cpdf` in `SNESIM.cpp` combines a soft pdf with the TI's conditional pdf as their normalized product,
and lets the soft pdf win when the product is zero. Sondara supplies the training holes' vertical proportion curve
divided by the TI's proportions, so the product is $P_{TI}(k \mid \text{pattern})\,\mathrm{VPC}(k \mid z) / p_{TI}(k)$,
the conditional-independence aggregation that for two categories equals Journel's permanence of ratios (Journel 2002,
*Mathematical Geology* 34, 573-596, doi:10.1023/A:1016047012594). Without it, a stationary training image put
non-overburden categories in 16 % of the surface layer of an Alberta realization; with it, none.

## Caveats and license

LGPL-3.0 (the root `LICENSE` of the pinned commit; the documentation still states an older wording). The license is
copied beside the executables, which are built locally and not redistributed by Sondara. SNESIM is CPU-only here. On
the 31,008-cell Alberta grid it took about 20 s per realization alone in a trial, and 41 to 79 s per realization in the
full run (1,327 to 2,536 s for 32), with four runs and seven Direct Sampling workers sharing a 24-core laptop; the
gneiss-domes image is the slower one. The supervision limit is 300 s per realization. Realization quality depends on the training image, which is an interpretation; the tests check the engine's
contract (hard data, seeds, schema, small-pattern frequencies), not the geology.
