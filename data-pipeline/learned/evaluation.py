"""Constructed alterations for the geochemical autoencoder review (unit SD-7b).

The learned regression methods are scored by ``stages/evaluate.py`` with the classical ones (audit L-4 of the
2026-09-28 research). This module builds the labelled alterations of held-out records that test whether a
reconstruction score notices a change. The 0.2 version marked records altered without altering them (audit L-3);
here every record marked altered differs from its parent, which it names, and the unchanged kind is kept apart as the
reference. An alteration tests detection of that alteration only: it says nothing about real contamination, ore or
assay quality. Design: docs/design/features/geochemical-review/design.md, section 4.
"""

from __future__ import annotations

import numpy as np

SEVERITIES = (0.25, 1.0, 3.0)
MULTIPLY, UNIT = 10.0, 10000.0
PAIR = ("Fe", "SiO2")
DONOR_TRIES = 50


def _pick(rng, candidates):
    return int(rng.choice(candidates)) if len(candidates) else None


def alterations(values: np.ndarray, holes: np.ndarray, properties: list[str], transform: dict, seed: int) -> list[dict]:
    """Every kind as ``{"kind", "severity", "values", "altered", "property", "donor"}`` over the same records.

    ``values`` are native (records x properties, in ``properties`` order); ``transform`` holds the training median and
    interquartile range of the properties it kept (``indices``). A record that a kind cannot alter (a zero value to
    multiply, no donor from another hole with different values) keeps its parent's values and is marked unaltered.
    """
    values = np.asarray(values, dtype=np.float64)
    holes = np.asarray(holes)
    rng = np.random.Generator(np.random.PCG64(seed))
    n = len(values)
    kept = list(transform["indices"])
    median = dict(zip(kept, transform["median"], strict=True))
    scale = dict(zip(kept, transform["scale"], strict=True))
    out = [{"kind": "unchanged", "severity": 0.0, "values": values.copy(), "altered": np.zeros(n, dtype=bool),
            "property": [None] * n, "donor": [None] * n}]

    def scaled(kind, factor):
        v, altered, prop = values.copy(), np.zeros(n, dtype=bool), [None] * n
        for i in range(n):
            j = _pick(rng, [k for k in kept if values[i, k] != 0])
            if j is not None:
                v[i, j] *= factor
                altered[i], prop[i] = True, properties[j]
        return {"kind": kind, "severity": factor, "values": v, "altered": altered, "property": prop, "donor": [None] * n}

    out.append(scaled("times-ten", MULTIPLY))
    out.append(scaled("unit-omission", UNIT))

    pair = [properties.index(q) for q in PAIR if q in properties]
    v, altered, donor = values.copy(), np.zeros(n, dtype=bool), [None] * n
    if len(pair) == 2:
        for i in range(n):
            others = np.flatnonzero(holes != holes[i])
            for _ in range(DONOR_TRIES if len(others) else 0):
                d = int(rng.choice(others))
                if np.any(values[d, pair] != values[i, pair]):
                    v[i, pair] = values[d, pair]
                    altered[i], donor[i] = True, d
                    break
    out.append({"kind": "cross-hole-pair", "severity": None, "values": v, "altered": altered,
                "property": ["+".join(PAIR) if a else None for a in altered], "donor": donor})

    for delta in SEVERITIES:
        v, prop = values.copy(), [None] * n
        for i in range(n):
            j = int(rng.choice(kept))
            z = np.arcsinh((values[i, j] - median[j]) / scale[j]) + delta
            v[i, j] = median[j] + scale[j] * np.sinh(z)
            prop[i] = properties[j]
        altered = np.any(v != values, axis=1)
        out.append({"kind": f"transformed-additive-{delta:g}", "severity": delta, "values": v, "altered": altered,
                    "property": [q if a else None for q, a in zip(prop, altered, strict=True)], "donor": [None] * n})
    return out
