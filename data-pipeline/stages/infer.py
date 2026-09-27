"""The infer stage: the eight classical methods on identical test targets, conditioned on the training rows.

Design: docs/design/features/classical-estimation/design.md, section 3. For each family, split scheme and fitted
population, every method predicts every test member at its centre (the interval-centre or envelope-centre
approximation) from the same training observations and the same neighbourhood plan; a method whose model failed to fit
reports that status for every target instead of being skipped. Truth values are not read here: evaluation does that.
"""

from __future__ import annotations

import time

from stages.estimators import METHODS, Plan, engine, estimate
from stages.models import model_from, transform_from
from stages.train import _split_rows

SCHEMA = "drillhole.predictions/v1"


def _failed(method, targets, reason):
    return {"method": method, "extra": {}, "rows": [{"id": t["id"], "method": method, "status": "failed",
                                                     "reason": reason, "mean": None, "variance": None,
                                                     "samples": 0, "holes": 0} for t in targets]}


#: The declared deterministic fallback for universal kriging: a target whose neighbourhood makes the drift rank
#: deficient is retried once with this many times the samples (same per-hole cap); it stays universal kriging.
ENLARGE = 2


def _universal(train, test, analyte, plan, model):
    first = estimate("universal-kriging", train, test, analyte, plan, model=model)
    retry = [i for i, r in enumerate(first["rows"]) if r["status"] == "failed" and "rank deficient" in (r["reason"] or "")]
    if retry:
        wider = Plan(**{**plan.__dict__, "max_samples": plan.max_samples * ENLARGE})
        second = estimate("universal-kriging", train, [test[i] for i in retry], analyte, wider, model=model)
        for i, row in zip(retry, second["rows"], strict=True):
            row["neighbourhood"] = f"enlarged to {wider.max_samples} samples after a rank-deficient drift"
            first["rows"][i] = row
        first["extra"]["enlarged"] = len(retry)
    return first


def run_methods(train, test, analyte, fitted: dict, plan: Plan) -> dict:
    """All eight methods for one population; returns ``{method: {"rows", "extra", "seconds"}}``."""
    out = {}
    model = model_from(fitted["model"]) if fitted.get("model") else None
    for method in METHODS:
        t0 = time.time()
        if method in ("nearest-neighbour", "inverse-distance"):
            result = estimate(method, train, test, analyte, plan)
        elif model is None:
            result = _failed(method, test, fitted.get("reason", "no fitted covariance model"))
        elif method == "simple-kriging":
            result = estimate(method, train, test, analyte, plan, model=model, mean=fitted["skMean"])
        elif method == "ordinary-kriging":
            result = estimate(method, train, test, analyte, plan, model=model)
        elif method == "universal-kriging":
            universal = fitted.get("universal", {})
            if universal.get("status") == "fitted":
                result = _universal(train, test, analyte, plan, model_from(universal["model"]))
            else:
                result = _failed(method, test, universal.get("reason", "no residual covariance"))
        elif method == "ordinary-cokriging":
            lmc = fitted.get("lmc", {})
            result = (estimate(method, train, test, analyte, plan, model=model_from(lmc["model"]),
                               secondary=lmc["variables"][1:])
                      if lmc.get("status") == "fitted"
                      else _failed(method, test, lmc.get("reason", "no declared secondary variables")))
        elif method == "multiple-indicator":
            kept = [t for t in fitted.get("indicator", {}).get("thresholds", []) if t["status"] == "fitted"]
            result = (estimate(method, train, test, analyte, plan, thresholds=[t["threshold"] for t in kept],
                               indicator_models=[model_from(t["model"]) for t in kept])
                      if kept else _failed(method, test, "no fitted indicator threshold"))
        else:
            gaussian = fitted.get("gaussian", {})
            result = (estimate(method, train, test, analyte, plan, model=model_from(gaussian["model"]),
                               transform=transform_from(gaussian["transform"]))
                      if gaussian.get("status") == "fitted"
                      else _failed(method, test, gaussian.get("reason", "no Gaussian-space model")))
        out[method] = {"rows": result["rows"], "extra": result["extra"], "seconds": round(time.time() - t0, 3)}
    return out


#: The scenario variants, computed on one declared population per family (R05, R06, R07, R09).
VARIANT_POPULATIONS = {"rocklea": ("hole-group", "rocklea-native-1m")}
NEIGHBOURHOODS = {"neighbourhood-small": {"max_samples": 8, "max_per_hole": 3},
                  "neighbourhood-large": {"max_samples": 64, "max_per_hole": None}}
LINE_ORDER = 4


def _line_supports(pre, rows):
    from geocond import line_support, point_support

    positions = {p["supportId"]: p for p in pre["positions"]}
    out = {}
    for r in rows:
        p = positions.get(r["id"])
        if p is not None and "from" in p:
            out[r["id"]] = line_support(p["from"], p["to"], order=LINE_ORDER, id=r["id"])
        else:
            out[r["id"]] = point_support(r["xyz"], id=r["id"])
    return out


def variants(pre, train, test, analyte, fitted, plan) -> dict:
    """R06 neighbourhood sizes, R05 the best isotropic model, R07 sample-interval supports, R09 sparse primary."""
    out = {}
    model = model_from(fitted["model"])

    def run(name, description, method, *args, **kw):
        t0 = time.time()
        result = estimate(method, *args, **kw)
        out[name] = {"method": method, "description": description, "rows": result["rows"], "extra": result["extra"],
                     "seconds": round(time.time() - t0, 3)}

    for name, change in NEIGHBOURHOODS.items():
        run(name, f"ordinary kriging with {change['max_samples']} samples, per-hole cap {change['max_per_hole']}",
            "ordinary-kriging", train, test, analyte, Plan(**{**plan.__dict__, **change}), model=model)
    isotropic = [c for c in fitted["candidates"] if c["kind"] == "isotropic" and c["status"] == "fitted"
                 and c["validationRmse"] is not None]
    if isotropic:
        best = min(isotropic, key=lambda c: (c["validationRmse"], c["objective"]))
        run("isotropic", f"ordinary kriging with the best isotropic candidate ({'+'.join(best['families'])})",
            "ordinary-kriging", train, test, analyte, plan, model=model_from(best["model"]))
    supports = _line_supports(pre, train + test)
    run("integrated-support", f"ordinary kriging with observations and targets integrated over their sample "
                              f"intervals ({LINE_ORDER}-point Gauss-Legendre)",
        "ordinary-kriging", train, test, analyte, plan, model=model, supports_by_id=supports)
    lmc = fitted.get("lmc", {})
    if lmc.get("status") == "fitted":
        secondary = lmc["variables"][1:]
        available = [{**r, "id": f"{r['id']}#secondary", "values": {k: v for k, v in r["values"].items()
                                                                     if k in secondary}} for r in test]
        run("sparse-primary", "ordinary cokriging with the secondaries measured on the test samples available",
            "ordinary-cokriging", train + [a for a in available if a["values"]], test, analyte, plan,
            model=model_from(lmc["model"]), secondary=secondary)
    return out


def infer_family(family, project, pre, dataset, models) -> dict:
    out = {"schema": SCHEMA, "family": family, "engine": engine(), "methods": list(METHODS), "schemes": [],
           "conditioning": "training rows only; validation rows chose the model; calibration and test rows are "
                           "predicted, calibration for the variance calibration of evaluate"}
    if not models.get("eligible"):
        return {**out, "eligible": False, "reason": models.get("reason")}
    plan = Plan(**{k: v for k, v in {
        "max_samples": models["plan"]["maxSamples"], "min_samples": models["plan"]["minSamples"],
        "max_per_hole": models["plan"]["maxPerHole"], "power": models["plan"]["power"],
        "drift": models["plan"]["drift"], "realizations": models["plan"]["realizations"],
        "simulated_nodes": models["plan"]["simulatedNodes"], "seed": models["plan"]["seed"]}.items()})
    by_scheme = {s["id"]: s for s in dataset["schemes"]}
    declared = VARIANT_POPULATIONS.get(family)
    for mscheme in models["schemes"]:
        scheme = by_scheme[mscheme["scheme"]]
        entry = {"scheme": scheme["id"], "populations": []}
        for fitted in mscheme["populations"]:
            population = next(p for p in pre["populations"] if p["id"] == fitted["population"])
            rows = _split_rows(project, pre, scheme, population)
            analyte = fitted["analyte"]
            test = [r for r in rows["test"] if analyte in r["values"]]
            calibration = [r for r in rows["calibration"] if analyte in r["values"]]
            record = {"population": fitted["population"], "analyte": analyte, "targets": [t["id"] for t in test],
                      "calibrationTargets": [t["id"] for t in calibration], "conditioning": len(rows["train"]),
                      "methods": {}}
            if test:
                joint = run_methods(rows["train"], test + calibration, analyte, fitted, plan)
                n = len(test)
                for method, result in joint.items():
                    record["methods"][method] = {"rows": result["rows"][:n], "calibrationRows": result["rows"][n:],
                                                 "extra": result["extra"], "seconds": result["seconds"]}
                if declared == (scheme["id"], fitted["population"]) and fitted.get("model"):
                    record["variants"] = variants(pre, rows["train"], test, analyte, fitted, plan)
            entry["populations"].append(record)
        out["schemes"].append(entry)
    return {**out, "eligible": True}
