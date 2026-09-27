"""The infer stage: the eight classical methods on identical test targets, conditioned on the training rows.

Design: docs/design/features/classical-estimation/design.md, section 3. For each family, split scheme and fitted
population, every method predicts every test member at its centre (the interval-centre or envelope-centre
approximation) from the same training observations and the same neighbourhood plan; a method whose model failed to fit
reports that status for every target instead of being skipped. Truth values are not read here: evaluation does that.
"""

from __future__ import annotations

import time

from stages.estimators import METHODS, Plan, estimate
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


def infer_family(family, project, pre, dataset, models) -> dict:
    out = {"schema": SCHEMA, "family": family, "methods": list(METHODS), "schemes": [],
           "conditioning": "training rows only; validation rows chose the model, test rows are predicted"}
    if not models.get("eligible"):
        return {**out, "eligible": False, "reason": models.get("reason")}
    plan = Plan(**{k: v for k, v in {
        "max_samples": models["plan"]["maxSamples"], "min_samples": models["plan"]["minSamples"],
        "max_per_hole": models["plan"]["maxPerHole"], "power": models["plan"]["power"],
        "drift": models["plan"]["drift"], "realizations": models["plan"]["realizations"],
        "seed": models["plan"]["seed"]}.items()})
    by_scheme = {s["id"]: s for s in dataset["schemes"]}
    for mscheme in models["schemes"]:
        scheme = by_scheme[mscheme["scheme"]]
        entry = {"scheme": scheme["id"], "populations": []}
        for fitted in mscheme["populations"]:
            population = next(p for p in pre["populations"] if p["id"] == fitted["population"])
            rows = _split_rows(project, pre, scheme, population)
            test = [r for r in rows["test"] if fitted["analyte"] in r["values"]]
            record = {"population": fitted["population"], "analyte": fitted["analyte"],
                      "targets": [t["id"] for t in test], "conditioning": len(rows["train"])}
            record["methods"] = run_methods(rows["train"], test, fitted["analyte"], fitted, plan) if test else {}
            entry["populations"].append(record)
        out["schemes"].append(entry)
    return {**out, "eligible": True}
