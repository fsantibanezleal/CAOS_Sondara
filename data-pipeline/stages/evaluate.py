"""The evaluate stage: native-unit scores of every method on the frozen test rows, and the scenario matrix.

Design: docs/design/features/classical-estimation/design.md, section 4. Truth is read here and nowhere earlier. Every
method is scored on its own predicted targets and on the common list every continuous method predicted; comparisons
with ordinary kriging are paired by target with a hole-block bootstrap; kriging variances are calibrated on the
calibration holes only; MIK is scored with Brier and log scores against the constant training proportion; SGS with the
fair CRPS of its realizations, the coverage of its 80 % interval, and the reproduction of the test truths' histogram
and downhole variogram beside ordinary kriging's smoothed estimates. A receipt records the split seeds, the plan, the
engine versions and the hashes of every input and of the result.
"""

from __future__ import annotations

import math
from collections import defaultdict
from itertools import combinations, pairwise

import numpy as np
from source_io import stable_hash
from stages.estimators import METHODS, engine
from stages.train import _split_rows

SCHEMA = "drillhole.metrics/v1"
CONTINUOUS = tuple(m for m in METHODS if m != "multiple-indicator")
KRIGING = ("simple-kriging", "ordinary-kriging", "universal-kriging", "ordinary-cokriging")
PREDICTED = ("estimated", "prior-only")
BOOTSTRAP = 1000
SEED = 20260926
LOG_FLOOR = 1e-3
Z95 = 1.959963984540054
QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)
LAGS = 5
CONVERGENCE = (8, 16, 32)


def _scores(errors, lengths, holes) -> dict:
    e = np.asarray(errors, dtype=float)
    if not len(e):
        return {"n": 0}
    w = np.asarray(lengths, dtype=float)
    w = np.where(w > 0, w, 1.0)
    per_hole = defaultdict(list)
    for err, hole in zip(e, holes, strict=True):
        per_hole[hole].append(err)
    hole_rmse = [math.sqrt(float(np.mean(np.square(v)))) for v in per_hole.values()]
    return {"n": len(e), "holes": len(per_hole), "bias": float(e.mean()), "mae": float(np.abs(e).mean()),
            "rmse": float(math.sqrt(np.mean(e * e))),
            "absoluteErrorQuantiles": {q: float(np.quantile(np.abs(e), float(q))) for q in ("0.5", "0.9")},
            "lengthWeighted": {"bias": float(w @ e / w.sum()), "mae": float(w @ np.abs(e) / w.sum()),
                               "rmse": float(math.sqrt(w @ (e * e) / w.sum()))},
            "holeMacroRmse": float(np.mean(hole_rmse))}


def paired(errors_a, errors_b, holes, *, seed=SEED, reps=BOOTSTRAP) -> dict:
    """Mean absolute-error difference a minus b over shared targets, with a 95 % hole-block bootstrap interval."""
    d = np.abs(np.asarray(errors_a)) - np.abs(np.asarray(errors_b))
    names = sorted(set(holes))
    index = {h: [i for i, x in enumerate(holes) if x == h] for h in names}
    rng = np.random.Generator(np.random.PCG64(seed))
    means = []
    for _ in range(reps):
        drawn = rng.integers(0, len(names), len(names))
        rows = [i for k in drawn for i in index[names[k]]]
        means.append(float(d[rows].mean()))
    return {"n": len(d), "holes": len(names), "meanAbsoluteErrorDifference": float(d.mean()),
            "interval95": [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))],
            "bootstrap": {"reps": reps, "seed": seed, "unit": "hole"}}


def fair_crps(realizations, truth) -> float:
    """Fair CRPS of an m-member ensemble: mean |X - y| - sum |X_i - X_j| / (2 m (m - 1))."""
    x = np.asarray(realizations, dtype=float)
    m = len(x)
    spread = np.abs(x[:, None] - x[None, :]).sum() / (2 * m * (m - 1))
    return float(np.abs(x - truth).mean() - spread)


def calibration(method_record, truth, analyte) -> dict:
    """A variance scale from the calibration holes, applied to the test rows: z-scores and 95 % coverage."""
    def zs(rows):
        out = []
        for r in rows:
            if r["status"] in PREDICTED and r.get("variance") and r["variance"] > 0 and r["id"] in truth:
                out.append((r["mean"] - truth[r["id"]]) / math.sqrt(r["variance"]))
        return np.array(out)

    cal, test = zs(method_record.get("calibrationRows", [])), zs(method_record["rows"])
    if not len(cal) or not len(test):
        return {"status": "not available", "reason": "no predicted calibration or test rows with a variance"}
    scale = float(np.mean(cal ** 2))
    calibrated = test / math.sqrt(scale)
    return {"status": "computed", "varianceScale": scale, "calibrationTargets": len(cal),
            "test": {"zMean": float(test.mean()), "zVariance": float(test.var()),
                     "coverage95": float(np.mean(np.abs(test) <= Z95)),
                     "calibratedZVariance": float(calibrated.var()),
                     "calibratedCoverage95": float(np.mean(np.abs(calibrated) <= Z95))},
            "caveat": "coverage reads the kriging variance as a Gaussian error variance; the variance is conditional "
                      "on the fitted covariance and the support approximation"}


def indicator_scores(record, truth, training_values) -> dict:
    thresholds = record["extra"].get("thresholds", [])
    rows = [r for r in record["rows"] if r["status"] == "estimated" and r["id"] in truth]
    out = []
    for k, t in enumerate(thresholds):
        y = np.array([truth[r["id"]] <= t for r in rows], dtype=float)
        p = np.array([r["cdf"][k] for r in rows], dtype=float)
        q = float(np.mean(np.asarray(training_values) <= t))
        clipped = np.clip(p, LOG_FLOOR, 1 - LOG_FLOOR)
        reference = np.clip(np.full_like(p, q), LOG_FLOOR, 1 - LOG_FLOOR)
        brier, brier_ref = float(np.mean((p - y) ** 2)), float(np.mean((q - y) ** 2))
        out.append({"threshold": t, "n": len(y), "observedProportion": float(y.mean()) if len(y) else None,
                    "trainingProportion": q, "brier": brier, "brierReference": brier_ref,
                    "brierSkill": None if brier_ref == 0 else 1 - brier / brier_ref,
                    "logScore": float(-np.mean(y * np.log(clipped) + (1 - y) * np.log(1 - clipped))),
                    "logScoreReference": float(-np.mean(y * np.log(reference) + (1 - y) * np.log(1 - reference)))})
    return {"thresholds": out, "logFloor": LOG_FLOOR}


def convergence(sims, truth) -> list[dict]:
    """E-type RMSE, fair CRPS and 80 % coverage from the first 8, 16 and 32 realizations of every target."""
    out = []
    for m in CONVERGENCE:
        usable = [r for r in sims if len(r["realizations"]) >= m]
        if not usable:
            continue
        x = [np.asarray(r["realizations"][:m], dtype=float) for r in usable]
        y = [truth[r["id"]] for r in usable]
        out.append({"realizations": m, "targets": len(usable),
                    "etypeRmse": float(math.sqrt(np.mean([(v.mean() - t) ** 2 for v, t in zip(x, y, strict=True)]))),
                    "fairCrps": float(np.mean([fair_crps(v, t) for v, t in zip(x, y, strict=True)])),
                    "coverage80": float(np.mean([np.quantile(v, 0.1) <= t <= np.quantile(v, 0.9)
                                                 for v, t in zip(x, y, strict=True)]))})
    return out


def distribution(values) -> dict:
    v = np.asarray(values, dtype=float)
    return {"n": len(v), "mean": float(v.mean()), "variance": float(v.var()),
            "quantiles": {str(q): float(np.quantile(v, q)) for q in QUANTILES}}


def downhole_pairs(holes, depths, lag) -> dict:
    """Target pairs in one hole, binned at k lags (k = 1 to LAGS) of measured-depth separation, within half a lag."""
    by_hole = defaultdict(list)
    for k, hole in enumerate(holes):
        by_hole[hole].append(k)
    bins = {k: [] for k in range(1, LAGS + 1)}
    for ks in by_hole.values():
        for a, b in combinations(ks, 2):
            k = round(abs(depths[a] - depths[b]) / lag)
            if 1 <= k <= LAGS:
                bins[k].append((a, b))
    return bins


def semivariance(values, pairs) -> float | None:
    if not pairs:
        return None
    a, b = np.array(pairs).T
    v = np.asarray(values, dtype=float)
    return float(0.5 * np.mean((v[a] - v[b]) ** 2))


def _band(values) -> dict:
    return {"mean": float(np.mean(values)), "p10": float(np.quantile(values, 0.1)),
            "p90": float(np.quantile(values, 0.9))}


def reproduction(sgs_rows, ok_rows, truth, info, training) -> dict:
    """Does SGS reproduce the variability of the test truths where OK smooths it? Histograms and downhole variograms.

    Compared on the targets both methods predicted: the training histogram, the truths, OK's estimates and every
    realization (summarized by the mean and the 10 to 90 % band over realizations). The downhole lag is the median
    support length, or, for point supports, the median spacing of consecutive targets in a hole.
    """
    ok = {r["id"]: r for r in ok_rows if r["status"] in PREDICTED}
    sims = [r for r in sgs_rows if r["status"] == "estimated" and r["id"] in truth and r["id"] in ok]
    if len(sims) < 2:
        return {"status": "not available", "reason": "fewer than two targets predicted by SGS and OK"}
    ids = [r["id"] for r in sims]
    realized = np.array([r["realizations"] for r in sims]).T  # realizations x targets
    y = np.array([truth[t] for t in ids])
    estimate = np.array([ok[t]["mean"] for t in ids])
    per = [distribution(x) for x in realized]
    realization_stats = {"mean": _band([d["mean"] for d in per]), "variance": _band([d["variance"] for d in per]),
                         "quantiles": {q: _band([d["quantiles"][q] for d in per]) for q in per[0]["quantiles"]}}
    holes = [info[t]["hole"] for t in ids]
    depths = [info[t]["md"] for t in ids]
    lengths = [info[t]["length"] for t in ids if info[t]["length"] > 0]
    if lengths:
        lag, basis = float(np.median(lengths)), "median support length"
    else:
        steps = []
        for hole in set(holes):
            d = sorted(depths[k] for k in range(len(ids)) if holes[k] == hole)
            steps += [b - a for a, b in pairwise(d) if b > a]
        lag, basis = (float(np.median(steps)), "median spacing of consecutive targets") if steps else (None, None)
    variogram = {"status": "not available", "reason": "no two targets in one hole"}
    if lag:
        bins = downhole_pairs(holes, depths, lag)
        lags = []
        for k, pairs in bins.items():
            if not pairs:
                continue
            gammas = [semivariance(x, pairs) for x in realized]
            lags.append({"lag": k, "separation": k * lag, "pairs": len(pairs), "truth": semivariance(y, pairs),
                         "ordinaryKriging": semivariance(estimate, pairs), "realizations": _band(gammas)})
        if lags:
            variogram = {"status": "computed", "lag": lag, "basis": basis, "lags": lags}
    return {"status": "computed", "targets": len(ids), "realizations": len(realized),
            "hardNodes": sum(r.get("hard", False) for r in sims),
            "histogram": {"training": distribution(training), "truth": distribution(y),
                          "ordinaryKriging": distribution(estimate), "realizations": realization_stats},
            "downholeVariogram": variogram,
            "caveat": "the realizations are conditional on the training holes, so their histogram at the test targets "
                      "is compared with the truths there; the training histogram is shown for reference"}


#: The learned residual band: this quantile of the calibration rows' absolute residuals (design section 2).
BAND_QUANTILE = 0.95


def learned_scores(method_record, targets, common, truth, info, training_range, ok_predicted) -> dict:
    """A learned method scored like the classical ones on the same targets, plus its seeds, spread, residual band
    (radius from the calibration rows, coverage on the test rows) and controls (docs/design/features/
    learned-regression/design.md, section 6)."""
    low, high = training_range
    rows = method_record["rows"]
    got = {r["id"]: r for r in rows if r["status"] in PREDICTED}
    own = [t for t in targets if t in got]
    shared_common = [t for t in common if t in got]

    def errors(ids, value=lambda r: r["mean"]):
        return [value(got[t]) - truth[t] for t in ids]

    def scores(ids, value=lambda r: r["mean"]):
        return _scores(errors(ids, value), [info[t]["length"] for t in ids], [info[t]["hole"] for t in ids])

    entry = {"coverage": len(own) / max(1, len(rows)),
             "statuses": dict(sorted({s: sum(r["status"] == s for r in rows) for s in {r["status"] for r in rows}}
                                     .items())),
             "selected": method_record.get("selected")}
    outside = [t for t in own if not low <= got[t]["mean"] <= high]
    entry["outsideTrainingRange"] = {"count": len(outside), "fraction": len(outside) / max(1, len(own)),
                                     "extremes": [min((got[t]["mean"] for t in own), default=None),
                                                  max((got[t]["mean"] for t in own), default=None)]}
    entry["own"] = scores(own)
    entry["common"] = {**scores(shared_common), "classicalCommonMissed": len(common) - len(shared_common)}
    shared = [t for t in own if t in ok_predicted]
    entry["versusOrdinaryKriging"] = paired(errors(shared), [ok_predicted[t]["mean"] - truth[t] for t in shared],
                                            [info[t]["hole"] for t in shared])
    with_seeds = [t for t in own if got[t].get("seeds")]
    if with_seeds:
        count = len(got[with_seeds[0]]["seeds"])
        entry["seeds"] = [scores(with_seeds, lambda r, s=s: r["seeds"][s]) for s in range(count)]
        spread = np.array([got[t]["spread"] for t in with_seeds])
        entry["spread"] = {"meaning": "standard deviation of the seed predictions; model-fit spread, not a variance",
                           "mean": float(spread.mean()), "median": float(np.median(spread)),
                           "max": float(spread.max())}
    calibration = [r for r in method_record.get("calibrationRows", [])
                   if r["status"] in PREDICTED and r["id"] in truth]
    if calibration and own:
        residuals = np.abs([r["mean"] - truth[r["id"]] for r in calibration])
        radius = float(np.quantile(residuals, BAND_QUANTILE, method="higher"))
        inside = np.abs(errors(own)) <= radius
        entry["residualBand"] = {"quantile": BAND_QUANTILE, "radius": radius, "calibrationRows": len(calibration),
                                 "testCoverage": float(inside.mean()), "testRows": len(own),
                                 "assumption": "calibration and test holes exchangeable; the test coverage shows "
                                               "whether that held"}
    controls = {}
    for name, control in method_record.get("controls", {}).items():
        crows = {r["id"]: r for r in control["rows"] if r["status"] in PREDICTED}
        ids = [t for t in own if t in crows]
        controls[name] = {"scores": _scores([crows[t]["mean"] - truth[t] for t in ids],
                                            [info[t]["length"] for t in ids], [info[t]["hole"] for t in ids]),
                          "versusMethod": paired([crows[t]["mean"] - truth[t] for t in ids], errors(ids),
                                                 [info[t]["hole"] for t in ids])}
    if controls:
        entry["controls"] = controls
    if method_record.get("exports"):
        entry["exports"] = {"count": len(method_record["exports"]),
                            "onnxMaxAbsolute": max(e["parity"]["onnxCpuMaxAbsolute"]
                                                   for e in method_record["exports"]),
                            "cudaMaxAbsolute": max((e["parity"]["torchCudaMaxAbsolute"] or 0.0)
                                                   for e in method_record["exports"]),
                            "tolerance": method_record["exports"][0]["parity"]["tolerance"]}
    return entry


def evaluate_family(family, project, pre, dataset, predictions, models=None, learned=None) -> dict:
    out = {"schema": SCHEMA, "family": family, "inputPredictionsSha256": stable_hash(predictions),
           "bootstrap": {"reps": BOOTSTRAP, "seed": SEED, "unit": "hole"}, "schemes": []}
    learned_by = {} if learned is None or not learned.get("eligible") else {
        (s["scheme"], p["population"]): p for s in learned["schemes"] for p in s["populations"]}
    if learned is not None:
        out["inputLearnedPredictionsSha256"] = stable_hash(learned)
    if not predictions.get("eligible"):
        return {**out, "eligible": False, "reason": predictions.get("reason")}
    by_scheme = {s["id"]: s for s in dataset["schemes"]}
    for pscheme in predictions["schemes"]:
        scheme = by_scheme[pscheme["scheme"]]
        entry = {"scheme": scheme["id"], "populations": []}
        for p in pscheme["populations"]:
            population = next(x for x in pre["populations"] if x["id"] == p["population"])
            rows = _split_rows(project, pre, scheme, population)
            analyte = p["analyte"]
            info = {r["id"]: r for split in ("test", "calibration") for r in rows[split]}
            truth = {i: r["values"][analyte] for i, r in info.items() if analyte in r["values"]}
            record = {"population": p["population"], "analyte": analyte, "targets": len(p["targets"]), "methods": {}}
            if not p["methods"]:
                entry["populations"].append({**record, "status": "no test targets"})
                continue
            predicted = {m: {r["id"]: r for r in p["methods"][m]["rows"] if r["status"] in PREDICTED}
                         for m in CONTINUOUS}
            common = [t for t in p["targets"] if all(t in predicted[m] for m in CONTINUOUS)]
            record["commonTargets"] = len(common)
            training = [r["values"][analyte] for r in rows["train"] if analyte in r["values"]]
            low, high = min(training), max(training)
            record["trainingRange"] = [low, high]
            # The constant reference: every test target predicted by the training mean, on the same targets.
            mean = float(np.mean(training))
            ids = [t for t in p["targets"] if t in truth]
            ok_rows = {r["id"]: r for r in p["methods"]["ordinary-kriging"]["rows"] if r["status"] in PREDICTED}
            shared = [t for t in ids if t in ok_rows]
            record["trainingMeanReference"] = {
                "value": mean, "scores": _scores([mean - truth[t] for t in ids], [info[t]["length"] for t in ids],
                                                 [info[t]["hole"] for t in ids]),
                "versusOrdinaryKriging": paired([mean - truth[t] for t in shared],
                                                [ok_rows[t]["mean"] - truth[t] for t in shared],
                                                [info[t]["hole"] for t in shared])}
            for m in METHODS:
                rows_m = p["methods"][m]["rows"]
                entry_m = {"coverage": sum(r["status"] in PREDICTED for r in rows_m) / max(1, len(rows_m)),
                           "statuses": dict(sorted({s: sum(r["status"] == s for r in rows_m)
                                                    for s in {r["status"] for r in rows_m}}.items()))}
                if m in CONTINUOUS:
                    own = [t for t in p["targets"] if t in predicted[m]]
                    outside = [t for t in own if not low <= predicted[m][t]["mean"] <= high]
                    entry_m["outsideTrainingRange"] = {
                        "count": len(outside), "fraction": len(outside) / max(1, len(own)),
                        "extremes": [min((predicted[m][t]["mean"] for t in own), default=None),
                                     max((predicted[m][t]["mean"] for t in own), default=None)]}
                    for label, ids in (("own", own), ("common", common)):
                        entry_m[label] = _scores([predicted[m][t]["mean"] - truth[t] for t in ids],
                                                 [info[t]["length"] for t in ids], [info[t]["hole"] for t in ids])
                    if m != "ordinary-kriging":
                        shared = [t for t in p["targets"] if t in predicted[m] and t in predicted["ordinary-kriging"]]
                        entry_m["versusOrdinaryKriging"] = paired(
                            [predicted[m][t]["mean"] - truth[t] for t in shared],
                            [predicted["ordinary-kriging"][t]["mean"] - truth[t] for t in shared],
                            [info[t]["hole"] for t in shared])
                if m in KRIGING:
                    entry_m["calibration"] = calibration(p["methods"][m], truth, analyte)
                if m == "multiple-indicator":
                    entry_m["probability"] = indicator_scores(p["methods"][m], truth, training)
                if m == "sequential-gaussian":
                    sims = [r for r in p["methods"][m]["rows"] if r["status"] == "estimated" and r["id"] in truth]
                    entry_m["ensemble"] = {
                        "fairCrps": float(np.mean([fair_crps(r["realizations"], truth[r["id"]]) for r in sims])),
                        "coverage80": float(np.mean([r["p10"] <= truth[r["id"]] <= r["p90"] for r in sims])),
                        "realizations": len(sims[0]["realizations"]) if sims else 0,
                        "convergence": convergence(sims, truth)}
                    entry_m["reproduction"] = reproduction(
                        p["methods"][m]["rows"], p["methods"]["ordinary-kriging"]["rows"],
                        {t: truth[t] for t in p["targets"] if t in truth}, info, training)
                record["methods"][m] = entry_m
            lp = learned_by.get((pscheme["scheme"], p["population"]))
            if lp is not None:
                if lp["targets"] != p["targets"] or lp["calibrationTargets"] != p["calibrationTargets"]:
                    raise ValueError(f"{family} {pscheme['scheme']} {p['population']}: the learned targets differ "
                                     "from the classical ones; run the learned lane again")
                record["learned"] = {"status": lp["status"], **({"reason": lp["reason"]} if lp.get("reason") else {})}
                for m, lm in lp["methods"].items():
                    record["methods"][m] = learned_scores(lm, p["targets"], common, truth, info, (low, high),
                                                          predicted["ordinary-kriging"])
            if "variants" in p:
                record["variants"] = {}
                base = predicted["ordinary-kriging"]
                for name, v in p["variants"].items():
                    got = {r["id"]: r for r in v["rows"] if r["status"] in PREDICTED}
                    ids = [t for t in p["targets"] if t in got]
                    shared = [t for t in ids if t in base]
                    record["variants"][name] = {
                        "method": v["method"], "description": v["description"],
                        "scores": _scores([got[t]["mean"] - truth[t] for t in ids], [info[t]["length"] for t in ids],
                                          [info[t]["hole"] for t in ids]),
                        "versusOrdinaryKriging": paired([got[t]["mean"] - truth[t] for t in shared],
                                                        [base[t]["mean"] - truth[t] for t in shared],
                                                        [info[t]["hole"] for t in shared]),
                        "meanShiftFromOrdinaryKriging": float(np.mean([got[t]["mean"] - base[t]["mean"]
                                                                       for t in shared])) if shared else None}
            entry["populations"].append(record)
        out["schemes"].append(entry)
    receipt = {"splits": [{"scheme": s["id"], "seed": s.get("seed"), "proportions": s.get("proportions")}
                          for s in dataset["schemes"]],
               "plan": (models or {}).get("plan"), "engine": {"fit": (models or {}).get("engine"),
                                                              "infer": predictions.get("engine"),
                                                              "evaluate": engine()},
               "inputs": {"datasetSha256": stable_hash(dataset), "predictionsSha256": stable_hash(predictions),
                          "modelsSha256": None if models is None else stable_hash(models),
                          "learnedPredictionsSha256": None if learned is None else stable_hash(learned)},
               "resultSha256": stable_hash(out["schemes"])}
    return {**out, "receipt": receipt, "eligible": True}
