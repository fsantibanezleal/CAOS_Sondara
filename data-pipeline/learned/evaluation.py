"""Observed field errors and separately labelled constructed-alteration scores."""

from __future__ import annotations

import numpy as np


def regression_metrics(observed: np.ndarray, predicted: np.ndarray, holes: np.ndarray,
                       lengths: np.ndarray, eligible: np.ndarray | None = None) -> dict:
    if eligible is None:
        eligible = np.isfinite(predicted)
    good = eligible & np.isfinite(predicted) & np.isfinite(observed)
    count = int(good.sum())
    base = {"expected": len(observed), "estimated": count, "unestimated": int((~good).sum()),
            "coverage": float(good.mean()) if len(good) else 0}
    if not count:
        return base | {"mae": None, "rmse": None, "bias": None, "holeMacroRmse": None,
                       "lengthWeightedRmse": None}
    error = predicted[good] - observed[good]
    groups = holes[good]
    return base | {"mae": float(np.mean(np.abs(error))), "rmse": float(np.sqrt(np.mean(error**2))),
                   "bias": float(np.mean(error)),
                   "holeMacroRmse": float(np.mean([np.sqrt(np.mean(error[groups == h] ** 2))
                                                   for h in np.unique(groups)])),
                   "lengthWeightedRmse": float(np.sqrt(np.average(error**2, weights=lengths[good])))}


def residual_calibration(observed: np.ndarray, predicted: np.ndarray) -> dict:
    residuals = np.abs(observed - predicted)
    residuals = residuals[np.isfinite(residuals)]
    if len(residuals) == 0:
        raise ValueError("calibration has no valid observations")
    return {"kind": "empirical-absolute-residual-band", "nominal": .95,
            "radius": float(np.quantile(residuals, .95, method="higher")), "count": len(residuals),
            "claim": "empirical calibration; spatial exchangeability is not assumed"}


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
