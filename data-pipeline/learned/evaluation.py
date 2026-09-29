"""Constructed alterations for the geochemical autoencoder review (unit SD-7b).

The learned regression methods are scored by ``stages/evaluate.py`` with the classical ones (audit L-4 of the
2026-09-28 research); this module keeps the perturbation experiment, which SD-7b corrects (audit L-3: the
transformed-additive perturbations are marked altered without being applied) and runs.
"""

from __future__ import annotations

import numpy as np


def perturbations(values: np.ndarray, holes: np.ndarray, properties: list[str], seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    outputs = []
    for severity in (0., .25, 1., 3.):
        outputs.append({"id": f"transformed-additive-{severity:g}", "kind": "transformed-additive",
                        "severity": severity, "values": values.copy(), "altered": severity > 0})
    multiplied = values.copy()
    multiplied[:, 0] *= 10
    outputs.append({"id": f"{properties[0]}-times-ten", "kind": "native-multiply", "severity": 10,
                    "values": multiplied, "altered": True})
    omitted_unit = values.copy()
    omitted_unit[:, 0] *= 10000
    outputs.append({"id": f"{properties[0]}-percent-ppm-unit-omission", "kind": "unit-omission",
                    "severity": 10000, "values": omitted_unit, "altered": True})
    permutation = values.copy()
    parents = []
    for i, hole in enumerate(holes):
        eligible = np.flatnonzero(holes != hole)
        if not len(eligible):
            raise ValueError("pair perturbation requires distinct test holes")
        parent = int(rng.choice(eligible))
        permutation[i, :2] = values[parent, :2]
        parents.append(parent)
    outputs.append({"id": "cross-hole-pair-permutation", "kind": "cross-hole-pair-permutation",
                    "values": permutation, "donorIndices": parents, "altered": True})
    return outputs
