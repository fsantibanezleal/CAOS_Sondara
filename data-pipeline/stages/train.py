"""The train stage: fitted covariance models and transforms from training rows, selected on validation rows only.

Design: docs/design/features/classical-estimation/design.md, section 3. For each family, split scheme and estimation
population, the primary analyte's covariance is chosen among declared candidates (nested families, isotropic or
anisotropic in four horizontal frames) fitted by GeoCond on the stored training variograms; the candidate with the
lowest validation RMSE of ordinary kriging wins, and every candidate's fit objective, validation error and coverage is
recorded. Universal kriging gets a covariance fitted to the residuals of a training-only linear trend; the declared
variable sets get a jointly fitted LMC; MIK gets indicator covariances at training-weighted deciles; SGS gets a
normal-score table and a Gaussian-space covariance. Test rows are never read.
"""

from __future__ import annotations

import math

import numpy as np
from geocond import (
    NormalScoreTransform,
    ValidationError,
    experimental_variogram,
    fit_lmc,
    fit_variogram,
    principal_frame,
)
from stages.dataset import members
from stages.estimators import Plan, estimate
from stages.features import (
    MAX_PAIRS,
    SEED,
    SPATIAL_LAGS,
    cross_sets,
    declustered_mean,
    family_analytes,
    population_rows,
)
from stages.models import model_record, transform_record, variogram_from

SCHEMA = "drillhole.models/v1"
FAMILY_SETS = (("spherical",), ("exponential",), ("spherical", "spherical"))
FRAMES = (0.0, 45.0, 90.0, 135.0)
DIRECTIONAL = ("azimuth-000", "azimuth-045", "azimuth-090", "azimuth-135", "vertical")
MIN_COVERAGE = 0.9
RANGE_BOUND_FACTOR = 5.0  # GeoCond's default upper range bound, in multiples of the largest fitted separation
DECILES = tuple(k / 10 for k in range(1, 10))
PLAN = Plan()


def _split_rows(project, pre, dataset_scheme, population):
    holes_of = {s["id"]: s["holeId"] for s in project["supports"]}
    holes_of.update({r["id"]: r["holeId"] for r in pre.get("composites", {}).get("rows", [])})
    split = members([(m, holes_of[m]) for m in population["members"]], dataset_scheme["assignment"])
    return {name: population_rows(pre, ids) for name, ids in split.items()}


def _rmse(rows, predictions, analyte):
    truth = {r["id"]: r["values"][analyte] for r in rows if analyte in r["values"]}
    errors = [p["mean"] - truth[p["id"]] for p in predictions if p["status"] == "estimated" and p["id"] in truth]
    coverage = len(errors) / max(1, len(truth))
    return (math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else None), coverage


def candidates(record, analyte, train, validation):
    """Every declared candidate fitted on the training variograms and scored on the validation rows."""
    variograms = {v["name"]: variogram_from(v) for v in record["analytes"][analyte]["variograms"]}
    out = []
    specs = [("isotropic", None, fams) for fams in FAMILY_SETS[:2]]
    specs += [("anisotropic", frame, fams) for frame in FRAMES for fams in FAMILY_SETS]
    for kind, frame, families in specs:
        entry = {"kind": kind, "frameAzimuth": frame, "families": list(families)}
        try:
            used = [variograms["omni"]] if kind == "isotropic" else [variograms[n] for n in DIRECTIONAL]
            if kind == "isotropic":
                fit = fit_variogram(used, families, isotropic=True)
            else:
                fit = fit_variogram(used, families, rotation=principal_frame(frame, 0.0, 0.0))
        except (ValidationError, KeyError, np.linalg.LinAlgError) as error:
            out.append({**entry, "status": "failed", "reason": str(error)})
            continue
        # GeoCond bounds every range at 5 times the largest fitted separation; a range at that bound is not resolved
        bound = RANGE_BOUND_FACTOR * max(float(np.nanmax(v.separation[v.valid])) for v in used if v.valid.any())
        entry["rangeUpperBound"] = bound
        entry["rangesAtBound"] = [[bool(r >= 0.99 * bound) for r in c.ranges] for c in fit.model.components]
        predictions = estimate("ordinary-kriging", train, validation, analyte, PLAN, model=fit.model)["rows"]
        rmse, coverage = _rmse(validation, predictions, analyte)
        out.append({**entry, "status": "fitted", "objective": float(fit.objective), "converged": bool(fit.converged),
                    "validationRmse": rmse, "validationCoverage": coverage, "model": model_record(fit.model),
                    "_model": fit.model})
    return out


def select(candidate_list):
    admissible = [c for c in candidate_list if c["status"] == "fitted" and c["validationRmse"] is not None
                  and c["validationCoverage"] >= MIN_COVERAGE]
    if not admissible:
        return None
    return min(admissible, key=lambda c: (c["validationRmse"], c["objective"]))


def _variogram_on(rows, values, spacing, *, seed=SEED):
    xyz = np.array([r["xyz"] for r in rows], dtype=float)
    lag = max(spacing / 2, 1.0)
    return experimental_variogram(xyz, np.asarray(values, dtype=float), lag * (np.arange(SPATIAL_LAGS + 1) + 0.5),
                                  max_pairs=MAX_PAIRS, seed=seed)


def residual_model(train, analyte, spacing, families):
    """A training-only linear trend in x, y, z and the isotropic covariance of its residuals (for universal kriging)."""
    rows = [r for r in train if analyte in r["values"]]
    xyz = np.array([r["xyz"] for r in rows], dtype=float)
    z = np.array([r["values"][analyte] for r in rows], dtype=float)
    centre, scale = xyz.mean(axis=0), max(float(np.ptp(xyz, axis=0).max()), 1.0)
    design = np.c_[np.ones(len(z)), (xyz - centre) / scale]
    coefficients, *_ = np.linalg.lstsq(design, z, rcond=None)
    residuals = z - design @ coefficients
    fit = fit_variogram([_variogram_on(rows, residuals, spacing)], families, isotropic=True)
    return fit, {"coefficients": coefficients.tolist(), "centre": centre.tolist(), "scale": scale,
                 "residualVariance": float(residuals.var())}


def indicator_models(train, analyte, spacing, weights):
    """Indicator covariances at training-weighted deciles; a threshold whose fit fails is recorded, not dropped."""
    rows = [r for r in train if analyte in r["values"]]
    z = np.array([r["values"][analyte] for r in rows], dtype=float)
    order = np.argsort(z, kind="stable")
    cumulative = np.cumsum(weights[order]) / weights.sum()
    thresholds = sorted({float(z[order][np.searchsorted(cumulative, q)]) for q in DECILES})
    kept, records = [], []
    for t in thresholds:
        indicator = (z <= t).astype(float)
        if indicator.min() == indicator.max():
            records.append({"threshold": t, "status": "failed", "reason": "constant indicator"})
            continue
        try:
            fit = fit_variogram([_variogram_on(rows, indicator, spacing)], ("spherical",), isotropic=True)
        except ValidationError as error:
            records.append({"threshold": t, "status": "failed", "reason": str(error)})
            continue
        kept.append((t, fit.model))
        records.append({"threshold": t, "status": "fitted", "objective": float(fit.objective),
                        "model": model_record(fit.model)})
    return kept, records


def gaussian_model(train, analyte, spacing, weights, families):
    rows = [r for r in train if analyte in r["values"]]
    z = np.array([r["values"][analyte] for r in rows], dtype=float)
    transform = NormalScoreTransform.fit(z, weights)
    fit = fit_variogram([_variogram_on(rows, transform.forward(z), spacing)], families, isotropic=True)
    return transform, fit


def lmc_model(record, variables, families):
    """A jointly fitted isotropic LMC on the omnidirectional direct and cross training variograms."""
    index = {v: i for i, v in enumerate(variables)}
    groups = {}
    for v in variables:
        omni = next(x for x in record["analytes"][v]["variograms"] if x["name"] == "omni")
        groups[(index[v], index[v])] = [variogram_from(omni)]
    for key, records in record["cross"].items():
        a, b = key.split("|")
        if a in index and b in index:
            omni = next(x for x in records if x["name"] == "omni")
            i, j = sorted((index[a], index[b]))
            groups[(i, j)] = [variogram_from(omni, cross=True)]
    return fit_lmc(groups, families, isotropic=True)


def train_family(family, project, pre, dataset, features, *, analytes=None):
    primary = analytes or family_analytes(family, pre)
    out = {"schema": SCHEMA, "family": family, "plan": PLAN.record(), "candidates": {
        "familySets": [list(f) for f in FAMILY_SETS], "frames": list(FRAMES), "minValidationCoverage": MIN_COVERAGE},
        "schemes": []}
    if not dataset["eligible"]:
        return {**out, "eligible": False, "reason": dataset["reason"]}
    by_scheme = {s["id"]: s for s in dataset["schemes"]}
    for fscheme in features["schemes"]:
        scheme = by_scheme[fscheme["scheme"]]
        spacing = fscheme["collarSpacing"]
        entry = {"scheme": scheme["id"], "populations": []}
        for record in fscheme["populations"]:
            population = next(p for p in pre["populations"] if p["id"] == record["population"])
            target = population.get("analyte") or primary[0]
            variables = [target] + [b if a == target else a for a, b in cross_sets(family, primary) if target in (a, b)]
            rows = _split_rows(project, pre, scheme, population)
            train, validation = rows["train"], rows["validation"]
            result = {"population": population["id"], "analyte": target, "train": len(train),
                      "validation": len(validation)}
            fitted = candidates(record, target, train, validation) if len(train) >= 2 else []
            best = select(fitted)
            result["candidates"] = [{k: v for k, v in c.items() if k != "_model"} for c in fitted]
            if best is None:
                result.update(status="failed", reason="no candidate fitted with validation coverage "
                                                       f">= {MIN_COVERAGE:.0%}")
                entry["populations"].append(result)
                continue
            families = tuple(best["families"])
            use = [r for r in train if target in r["values"]]
            xyz = np.array([r["xyz"] for r in use], dtype=float)
            z = np.array([r["values"][target] for r in use], dtype=float)
            stats = record["analytes"][target]["statistics"]
            _, weights = declustered_mean(xyz, z, tuple(stats["declustered"]["cell"]))
            result.update(status="fitted", selected={k: best[k] for k in ("kind", "frameAzimuth", "families",
                                                                          "objective", "validationRmse",
                                                                          "validationCoverage", "rangeUpperBound",
                                                                          "rangesAtBound")},
                          model=best["model"], skMean=stats["declustered"]["mean"])
            try:
                fit, trend = residual_model(train, target, spacing, families[:1])
                result["universal"] = {"status": "fitted", "model": model_record(fit.model), "trend": trend,
                                       "drift": PLAN.drift}
            except ValidationError as error:
                result["universal"] = {"status": "failed", "reason": str(error)}
            if len(variables) > 1:
                try:
                    lmc = lmc_model(record, variables, families[:1])
                    result["lmc"] = {"status": "fitted", "variables": variables, "model": model_record(lmc.model),
                                     "objective": float(lmc.objective),
                                     "eigenvalues": [np.linalg.eigvalsh(c.sill).tolist() for c in lmc.model.components]}
                except ValidationError as error:
                    result["lmc"] = {"status": "failed", "variables": variables, "reason": str(error)}
            _, thresholds = indicator_models(train, target, spacing, weights)
            result["indicator"] = {"thresholds": thresholds, "rule": "training-weighted deciles (cell declustering)"}
            try:
                transform, gfit = gaussian_model(train, target, spacing, weights, families[:1])
                result["gaussian"] = {"status": "fitted", "transform": transform_record(transform),
                                      "model": model_record(gfit.model),
                                      "sill": float(gfit.model.total_sill[0, 0])}
            except ValidationError as error:
                result["gaussian"] = {"status": "failed", "reason": str(error)}
            entry["populations"].append(result)
        out["schemes"].append(entry)
    return {**out, "eligible": True}
