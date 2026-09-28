"""Two labelled training images for the Alberta categorical lane, authored from the training holes of a split.

Design: docs/design/features/categorical-simulation/design.md, section 3. A training image (TI) is an interpretation,
not observed truth. Both priors share a layered cover (overburden, Devonian and Athabasca over basement) whose unit
thicknesses are smooth random fields with the training holes' mean and spread, clipped at zero so a unit can pinch
out. They differ in the basement: steep granitoid bodies elongated along the northwest trend of the Maybelle River
high-strain zone, or rounded granitoid bodies with no preferred direction (the mantled gneiss domes of the report).
The granitoid proportion is the training holes' basement proportion. Every parameter is declared and recorded.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict

import numpy as np

GENERATOR = "sondara-ti-v1"
PLAN = (72, 72)  # cells, at the grid's cell size; the depth is the grid's number of layers
CORRELATION_M = 1000.0  # lateral correlation length of the cover thickness fields
PRIORS = {
    "nw-high-strain": {"label": "Steep granitoid bodies elongated along azimuth 315 (Maybelle River high-strain zone)",
                       "azimuth": 315.0, "along_m": 3000.0, "across_m": 375.0, "vertical_m": 300.0},
    "gneiss-domes": {"label": "Rounded granitoid bodies with no preferred horizontal direction (mantled gneiss domes)",
                     "azimuth": 0.0, "along_m": 1000.0, "across_m": 1000.0, "vertical_m": 60.0},
}
COVER = (0, 1, 2)  # overburden, Devonian, Athabasca, top to bottom
BASEMENT = (3, 4)  # gneiss, granitoid


def _field(rng, shape, sigma_cells, azimuth_deg=0.0):
    """A standardized Gaussian random field: white noise convolved with an (anisotropic) Gaussian kernel, computed on a
    padded domain by FFT and cropped, so no periodic wrap reaches the image. The padding is three kernel widths, capped
    at four image extents per axis: a kernel wider than that is nearly flat across the image, and an uncapped one on
    fine cells asked for gigabytes. The kernel is built by broadcasting the three axes, never as full meshgrids."""
    pad = [min(int(3 * s) + 1, 4 * n)
           for s, n in zip((max(sigma_cells[0], sigma_cells[1]),) * 2 + (sigma_cells[2],), shape, strict=True)]
    big = tuple(n + 2 * p for n, p in zip(shape, pad, strict=True))
    noise = rng.standard_normal(big)
    x, y, z = (np.fft.fftfreq(n) * n for n in big)
    x, y, z = x[:, None, None], y[None, :, None], z[None, None, :]
    a = math.radians(azimuth_deg)
    along = x * math.sin(a) + y * math.cos(a)  # azimuth measured from north (y) toward east (x)
    across = x * math.cos(a) - y * math.sin(a)
    kernel = np.exp(-0.5 * ((along / sigma_cells[0]) ** 2 + (across / sigma_cells[1]) ** 2 + (z / sigma_cells[2]) ** 2))
    field = np.real(np.fft.ifftn(np.fft.fftn(noise) * np.fft.fftn(kernel)))
    field = field[pad[0]:pad[0] + shape[0], pad[1]:pad[1] + shape[1], pad[2]:pad[2] + shape[2]]
    return (field - field.mean()) / field.std()


def cover_statistics(mapped_rows, surveys, surface, holes) -> dict:
    """Per cover unit, the vertical thickness of each training hole that reaches the basement with its cover mapped
    without a gap; mean and standard deviation per unit, with the holes used and excluded."""
    by_hole = defaultdict(list)
    for r in mapped_rows:
        if r["holeId"] in holes and r["toMd"] is not None and r["toMd"] > r["fromMd"]:
            by_hole[r["holeId"]].append(r)
    thickness = {u: [] for u in COVER}
    used, excluded = [], {}
    for hole, rows in sorted(by_hole.items()):
        rows.sort(key=lambda r: r["fromMd"])
        top_basement = next((r["fromMd"] for r in rows if r["category"] in BASEMENT
                             or (r["category"] is None and "basement" in (r["reason"] or ""))), None)
        if top_basement is None:
            excluded[hole] = "does not reach the basement"
            continue
        # Cover is every interval that starts above the basement top, clipped at that top: a source overlap (MR-14's
        # Athabasca ends 5 cm below its basement top) must not drop a unit from the statistics.
        cover = [r for r in rows if r["fromMd"] < top_basement - 1e-6]
        gap = sum(min(r["toMd"], top_basement) - r["fromMd"] for r in cover if r["category"] is None)
        if gap > 1.0 or not cover or cover[0]["fromMd"] > 1.0:
            excluded[hole] = f"{gap:.1f} m of unmapped cover above the basement"
            continue
        survey = surveys[hole]
        for u in COVER:
            t = 0.0
            for r in cover:
                if r["category"] == u:
                    ends = np.asarray(survey.at([r["fromMd"], min(r["toMd"], top_basement)]).points, dtype=float)
                    depth = surface(ends[:, 0], ends[:, 1]) - ends[:, 2]
                    t += float(depth[1] - depth[0])
            thickness[u].append(t)
        used.append(hole)
    stats = {str(u): {"mean": float(np.mean(v)), "sd": float(np.std(v)), "n": len(v), "zeros": int(sum(x == 0 for x in v))}
             for u, v in thickness.items() if v}
    return {"units": stats, "holes": used, "excluded": excluded}


def granitoid_proportion(hard_cells) -> float:
    basement = [h for h in hard_cells if h["category"] in BASEMENT]
    return float(np.mean([h["category"] == 4 for h in basement])) if basement else 0.0


def author(prior: str, cell, layers: int, cover: dict, granitoid: float, seed: int) -> tuple[np.ndarray, dict]:
    """One training image (uint8 category codes, indexed x, y, depth), as deep as the grid, and its record."""
    spec = PRIORS[prior]
    rng = np.random.Generator(np.random.PCG64(seed))
    nx, ny, nz = (*PLAN, layers)
    shape = (nx, ny, nz)
    sigma = CORRELATION_M / cell[0]
    base = np.zeros((nx, ny))
    bases = []
    for u in COVER:
        s = cover["units"][str(u)]
        t = np.clip(s["mean"] + s["sd"] * _field(rng, (nx, ny, 1), (sigma, sigma, 1.0))[..., 0], 0.0, None)
        base = base + t
        bases.append(base.copy())
    depth = (np.arange(nz) + 0.5) * cell[2]
    ti = np.full(shape, 3, np.uint8)
    for u in reversed(COVER):  # deepest cover unit first, so shallower units overwrite
        ti[depth[None, None, :] < bases[u][..., None]] = u
    body = _field(rng, shape, (spec["along_m"] / cell[0], spec["across_m"] / cell[1], spec["vertical_m"] / cell[2]),
                  spec["azimuth"])
    basement = ti == 3
    if granitoid > 0:
        cut = np.quantile(body[basement], 1.0 - granitoid)
        ti[basement & (body > cut)] = 4
    proportions = {str(k): float(np.mean(ti == k)) for k in range(5)}
    record = {"prior": prior, "label": spec["label"], "generator": GENERATOR, "seed": seed, "shape": list(shape),
              "cell": list(cell), "parameters": {**spec, "coverCorrelationM": CORRELATION_M,
                                                 "granitoidProportion": granitoid, "cover": cover["units"]},
              "proportions": proportions, "categories": sorted(int(v) for v in np.unique(ti)),
              "license": "authored for Sondara, MIT", "interpretation": True,
              "sha256": hashlib.sha256(np.ascontiguousarray(ti).tobytes()).hexdigest()}
    return ti, record
