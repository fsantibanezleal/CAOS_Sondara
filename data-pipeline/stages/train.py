"""The train stage: fitted covariance models and transforms from training rows, selected on validation rows only.

Design: docs/design/features/classical-estimation/design.md, section 3. For each family, split scheme and estimation
population, the primary analyte's covariance is chosen among declared candidates (nested families, isotropic or
anisotropic in four horizontal frames) fitted by GeoCond on the stored training variograms; the candidate with the
lowest validation RMSE of ordinary kriging wins, and every candidate's fit objective, validation error and coverage is
recorded. Universal kriging gets a covariance fitted to the residuals of a training-only linear trend; the declared
variable sets get a jointly fitted LMC; MIK gets indicator covariances at training-weighted deciles. These three are
fitted with the structure selected for ordinary kriging (its families, and its frame on the four horizontal and the
vertical variograms of the transformed values when the selection is anisotropic), so the vertical continuity the
selection resolved is not lost to a nugget fitted on omnidirectional lags of half the collar spacing. SGS gets a
normal-score table and a Gaussian-space covariance selected on its own: anisotropic candidates in every frame and
family set, fitted on the normal scores' four horizontal and vertical variograms (the realizations must reproduce
continuity along the holes as well as between them), chosen by the validation RMSE of simple kriging of the normal
scores. Test rows are never read.
"""

from __future__ import annotations

import math

import numpy as np
from geocond import (
    NormalScoreTransform,
    ValidationError,
    fit_lmc,
    fit_variogram,
    principal_frame,
)
from stages.dataset import members
from stages.estimators import Plan, engine, estimate
from stages.features import (
    cross_sets,
    declustered_mean,
    directional_cross_variograms,
    family_analytes,
    population_rows,
    variograms,
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


class Structure:
    """The structure selected for ordinary kriging, which every other covariance of the population is fitted with."""

    def __init__(self, selected: dict, spacing: float, length: float):
        self.families = tuple(selected["families"])
        self.rotation = None if selected["kind"] == "isotropic" else principal_frame(selected["frameAzimuth"], 0.0, 0.0)
        self.names = ("omni",) if self.rotation is None else DIRECTIONAL
        self.spacing, self.length = spacing, length

    def record(self) -> dict:
        return {"families": list(self.families), "variograms": list(self.names),
                "frame": None if self.rotation is None else np.asarray(self.rotation).tolist()}

    def variograms_of(self, rows, values):
        """The variograms of ``values`` at ``rows``, defined exactly as the features stage defines the direct ones."""
        pseudo = [{**r, "values": {"v": float(x)}} for r, x in zip(rows, values, strict=True)]
        by_name = {v["name"]: v for v in variograms(pseudo, "v", self.spacing, self.length)}
        return [variogram_from(by_name[n]) for n in self.names]

    def fit(self, rows, values, families=None):
        used = self.variograms_of(rows, values)
        if self.rotation is None:
            return fit_variogram(used, families or self.families, isotropic=True)
        return fit_variogram(used, families or self.families, rotation=self.rotation)


def residual_model(train, analyte, structure: Structure):
    """A training-only linear trend in x, y, z and the covariance of its residuals (for universal kriging)."""
    rows = [r for r in train if analyte in r["values"]]
    xyz = np.array([r["xyz"] for r in rows], dtype=float)
    z = np.array([r["values"][analyte] for r in rows], dtype=float)
    centre, scale = xyz.mean(axis=0), max(float(np.ptp(xyz, axis=0).max()), 1.0)
    design = np.c_[np.ones(len(z)), (xyz - centre) / scale]
    coefficients, *_ = np.linalg.lstsq(design, z, rcond=None)
    residuals = z - design @ coefficients
    fit = structure.fit(rows, residuals)
    return fit, {"coefficients": coefficients.tolist(), "centre": centre.tolist(), "scale": scale,
                 "residualVariance": float(residuals.var())}


def indicator_models(train, analyte, structure: Structure, weights):
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
            fit = structure.fit(rows, indicator, families=("spherical",))
        except ValidationError as error:
            records.append({"threshold": t, "status": "failed", "reason": str(error)})
            continue
        kept.append((t, fit.model))
        records.append({"threshold": t, "status": "fitted", "objective": float(fit.objective),
                        "model": model_record(fit.model)})
    return kept, records


def gaussian_model(train, validation, analyte, structure: Structure, weights):
    """The normal-score table and the Gaussian-space covariance selected on validation, with every candidate.

    One structure for every method would not do: forcing ordinary kriging's single exponential on the normal scores
    of Rocklea's 1 m samples fitted the vertical variogram with no nugget and a 6 m east-west range, which cut the
    correlation between holes (validation RMSE 0.995 in normal-score units against 0.854 for a nested fit).
    """
    rows = [r for r in train if analyte in r["values"]]
    z = np.array([r["values"][analyte] for r in rows], dtype=float)
    transform = NormalScoreTransform.fit(z, weights)
    y = transform.forward(z)
    probe = Structure({"kind": "anisotropic", "frameAzimuth": 0.0, "families": list(FAMILY_SETS[0])},
                      structure.spacing, structure.length)
    used = probe.variograms_of(rows, y)  # the same four horizontal and vertical variograms for every frame
    bound = RANGE_BOUND_FACTOR * max(float(np.nanmax(v.separation[v.valid])) for v in used if v.valid.any())
    scored = [{**r, "values": {"y": float(v)}} for r, v in zip(rows, y, strict=True)]
    held = [r for r in validation if analyte in r["values"]]
    held_y = transform.forward(np.array([r["values"][analyte] for r in held], dtype=float)) if held else []
    check = [{**r, "values": {"y": float(v)}} for r, v in zip(held, held_y, strict=True)]
    out = []
    for frame in FRAMES:
        for families in FAMILY_SETS:
            entry = {"kind": "anisotropic", "frameAzimuth": frame, "families": list(families)}
            try:
                fit = fit_variogram(used, families, rotation=principal_frame(frame, 0.0, 0.0))
            except (ValidationError, np.linalg.LinAlgError) as error:
                out.append({**entry, "status": "failed", "reason": str(error)})
                continue
            predictions = estimate("simple-kriging", scored, check, "y", PLAN, model=fit.model, mean=0.0)["rows"]
            rmse, coverage = _rmse(check, predictions, "y")
            out.append({**entry, "status": "fitted", "objective": float(fit.objective),
                        "converged": bool(fit.converged), "rangeUpperBound": bound,
                        "rangesAtBound": [[bool(r >= 0.99 * bound) for r in c.ranges] for c in fit.model.components],
                        "sill": float(fit.model.total_sill[0, 0]), "validationRmse": rmse,
                        "validationCoverage": coverage, "model": model_record(fit.model)})
    return transform, select(out), out


def lmc_model(record, variables, structure: Structure, train):
    """A jointly fitted LMC on the direct and cross training variograms, with the selected structure."""
    index = {v: i for i, v in enumerate(variables)}
    groups = {}
    for v in variables:
        by_name = {x["name"]: x for x in record["analytes"][v]["variograms"]}
        groups[(index[v], index[v])] = [variogram_from(by_name[n]) for n in structure.names]
    for key, records in record["cross"].items():
        a, b = key.split("|")
        if a in index and b in index:
            i, j = sorted((index[a], index[b]))
            if structure.rotation is None:
                chosen = [next(x for x in records if x["name"] == "omni")]
            else:
                by_name = {x["name"]: x for x in directional_cross_variograms(train, (a, b), structure.spacing,
                                                                              structure.length)}
                chosen = [by_name[n] for n in structure.names]
            groups[(i, j)] = [variogram_from(x, cross=True) for x in chosen]
    if structure.rotation is None:
        return fit_lmc(groups, structure.families, isotropic=True)
    return fit_lmc(groups, structure.families, rotation=structure.rotation)


def train_family(family, project, pre, dataset, features, *, analytes=None):
    primary = analytes or family_analytes(family, pre)
    out = {"schema": SCHEMA, "family": family, "engine": engine(), "plan": PLAN.record(), "candidates": {
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
            structure = Structure(best, spacing, record["supportLength"])
            use = [r for r in train if target in r["values"]]
            xyz = np.array([r["xyz"] for r in use], dtype=float)
            z = np.array([r["values"][target] for r in use], dtype=float)
            stats = record["analytes"][target]["statistics"]
            _, weights = declustered_mean(xyz, z, tuple(stats["declustered"]["cell"]))
            result.update(status="fitted", selected={k: best[k] for k in ("kind", "frameAzimuth", "families",
                                                                          "objective", "validationRmse",
                                                                          "validationCoverage", "rangeUpperBound",
                                                                          "rangesAtBound")},
                          model=best["model"], skMean=stats["declustered"]["mean"], structure=structure.record())
            try:
                fit, trend = residual_model(train, target, structure)
                result["universal"] = {"status": "fitted", "model": model_record(fit.model), "trend": trend,
                                       "drift": PLAN.drift}
            except ValidationError as error:
                result["universal"] = {"status": "failed", "reason": str(error)}
            if len(variables) > 1:
                try:
                    lmc = lmc_model(record, variables, structure, train)
                    result["lmc"] = {"status": "fitted", "variables": variables, "model": model_record(lmc.model),
                                     "objective": float(lmc.objective),
                                     "eigenvalues": [np.linalg.eigvalsh(c.sill).tolist() for c in lmc.model.components]}
                except ValidationError as error:
                    result["lmc"] = {"status": "failed", "variables": variables, "reason": str(error)}
            _, thresholds = indicator_models(train, target, structure, weights)
            result["indicator"] = {"thresholds": thresholds, "rule": "training-weighted deciles (cell declustering)"}
            try:
                transform, gbest, gcandidates = gaussian_model(train, validation, target, structure, weights)
            except ValidationError as error:
                result["gaussian"] = {"status": "failed", "reason": str(error)}
            else:
                if gbest is None:
                    result["gaussian"] = {"status": "failed", "candidates": gcandidates,
                                          "reason": "no Gaussian-space candidate fitted with validation coverage "
                                                    f">= {MIN_COVERAGE:.0%}"}
                else:
                    result["gaussian"] = {
                        "status": "fitted", "transform": transform_record(transform), "model": gbest["model"],
                        "sill": gbest["sill"], "candidates": gcandidates,
                        "selected": {k: gbest[k] for k in ("kind", "frameAzimuth", "families", "objective",
                                                           "validationRmse", "validationCoverage",
                                                           "rangeUpperBound", "rangesAtBound")},
                        "rule": "anisotropic candidates in every frame and family set on the normal scores' "
                                "horizontal and vertical variograms; lowest validation RMSE of simple kriging of "
                                f"the normal scores among those covering at least {MIN_COVERAGE:.0%}"}
            entry["populations"].append(result)
        out["schemes"].append(entry)
    return {**out, "eligible": True}
