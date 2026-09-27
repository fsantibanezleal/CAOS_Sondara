"""Fitted GeoCond objects as JSON records and back, exactly: covariance models, normal-score tables, variograms."""

from __future__ import annotations

import numpy as np
from geocond import CovarianceComponent, CovarianceModel, ExperimentalVariogram, NormalScoreTransform


def model_record(model: CovarianceModel) -> dict:
    return {"nugget": model.nugget.tolist(),
            "components": [{"family": c.family, "ranges": c.ranges.tolist(), "sill": c.sill.tolist(),
                            "rotation": c.rotation.tolist()} for c in model.components]}


def model_from(record: dict) -> CovarianceModel:
    return CovarianceModel(tuple(CovarianceComponent(c["family"], c["ranges"], c["sill"], c["rotation"])
                                 for c in record["components"]), record["nugget"])


def transform_record(t: NormalScoreTransform) -> dict:
    return {"values": t.values.tolist(), "scores": t.scores.tolist(), "probabilities": t.probabilities.tolist(),
            "tail": t.tail, "lowerTail": None if t.lower_tail is None else list(t.lower_tail),
            "upperTail": None if t.upper_tail is None else list(t.upper_tail), "meta": t.meta}


def transform_from(record: dict) -> NormalScoreTransform:
    return NormalScoreTransform(np.array(record["values"]), np.array(record["scores"]),
                                np.array(record["probabilities"]), record["tail"],
                                None if record["lowerTail"] is None else tuple(record["lowerTail"]),
                                None if record["upperTail"] is None else tuple(record["upperTail"]), record["meta"])


def variogram_from(record: dict, *, cross: bool = False) -> ExperimentalVariogram:
    """An experimental variogram rebuilt from its stored record (bins, counts, values; the pairs are not stored)."""
    nan = float("nan")
    empty = np.zeros(0, np.int64)
    return ExperimentalVariogram(
        np.array(record["edges"], dtype=float),
        np.array([nan if x is None else x for x in record["separation"]], dtype=float),
        np.array(record["counts"], dtype=np.int64),
        np.array([nan if x is None else x for x in record["values"]], dtype=float),
        empty, empty, empty, record["estimator"],
        None if record["direction"] is None else np.array(record["direction"], dtype=float),
        record["angleTolerance"], record["bandwidth"], record["downhole"], cross, record["populationPairs"],
        record["sampled"], record["seed"], 0)
