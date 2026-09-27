"""The eight classical methods on one set of observations and targets, through GeoCond, with Sondara's policies.

NN, IDW, SK, OK, UK, ordinary cokriging (LMC), MIK and SGS share the observation rows, the target rows and the
neighbourhood plan. Rows are ``{"id", "hole", "xyz", "values": {analyte: value}}`` and optional ``"domain"``; targets
are predicted at their centres (the interval-centre approximation) unless the caller passes supports. Every target
gets a status (estimated, uninformed, failed, prior-only) and a reason; nothing falls back silently to another method.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np
from geocond import (
    Neighborhood,
    Observations,
    ValidationError,
    indicator_kriging,
    inverse_distance,
    nearest_neighbour,
    point_support,
    predict,
    sequential_gaussian,
)

METHODS = ("nearest-neighbour", "inverse-distance", "simple-kriging", "ordinary-kriging", "universal-kriging",
           "ordinary-cokriging", "multiple-indicator", "sequential-gaussian")


@dataclass
class Plan:
    """The neighbourhood and method settings shared by every method of one comparison."""

    max_samples: int = 24
    min_samples: int = 4
    radius: float = float("inf")
    max_per_hole: int | None = 6
    metric: tuple | None = None  # (rotation, ranges): distances in range units
    power: float = 2.0
    drift: str = "linear"
    realizations: int = 32
    simulated_nodes: int = 12  # SGS: previously simulated nodes, searched apart from the data (GSLIB ncnode)
    seed: int = 20260926
    domain: dict | None = None  # {"policy": "hard" | "soft", "distance": metres}
    extra: dict = field(default_factory=dict)

    def neighbourhood(self) -> Neighborhood:
        return Neighborhood(max_samples=self.max_samples, min_samples=self.min_samples, radius=self.radius,
                            max_per_group=self.max_per_hole, metric=self.metric)

    def record(self) -> dict:
        return {"maxSamples": self.max_samples, "minSamples": self.min_samples,
                "radius": None if self.radius == float("inf") else self.radius, "maxPerHole": self.max_per_hole,
                "metric": None if self.metric is None else {"rotation": np.asarray(self.metric[0]).tolist(),
                                                           "ranges": list(self.metric[1])},
                "power": self.power, "drift": self.drift, "realizations": self.realizations,
                "simulatedNodes": self.simulated_nodes, "seed": self.seed, "domain": self.domain}


def engine() -> dict:
    """The engine versions a stage ran with, recorded in its output."""
    import geocond
    import scipy

    return {"geocond": geocond.__version__, "numpy": np.__version__, "scipy": scipy.__version__}


def observations(rows, analytes, supports_by_id=None) -> Observations:
    """Stacked observations of one or several analytes; only rows that carry the analyte enter its variable.

    ``supports_by_id`` replaces the centre point of a row by an explicit support (for example the sample interval).
    """
    supports, values, variables, groups, ids = [], [], [], [], []
    for v, analyte in enumerate(analytes):
        for r in rows:
            if analyte in r["values"]:
                supports.append(supports_by_id[r["id"]] if supports_by_id else point_support(r["xyz"], id=r["id"]))
                values.append(r["values"][analyte])
                variables.append(v)
                groups.append(r["hole"])
                ids.append(f"{r['id']}|{analyte}")
    return Observations(supports, values, variables=np.array(variables, np.int64), groups=np.array(groups),
                        ids=ids)


def targets(rows) -> list:
    return [point_support(r["xyz"], id=r["id"]) for r in rows]


def _records(batch, rows, observed, method) -> list[dict]:
    out = []
    for i, r in enumerate(rows):
        diagnostics = batch.diagnostics[i] or {}
        ids = diagnostics.get("ids", [])
        per_hole = {}
        for x in ids:
            per_hole[observed.get(x, x)] = per_hole.get(observed.get(x, x), 0) + 1
        out.append({"id": r["id"], "method": method, "status": batch.status[i], "reason": batch.reasons[i],
                    "mean": None if not np.isfinite(batch.means[i, 0]) else float(batch.means[i, 0]),
                    "variance": None if not np.isfinite(batch.variances[i, 0]) else float(batch.variances[i, 0]),
                    "samples": len(ids), "holes": len(per_hole), "maxFromOneHole": max(per_hole.values(), default=0),
                    "negativeWeightMass": diagnostics.get("negative_weight_mass")})
    return out


def _domain_filter(obs_rows, target, plan):
    policy = plan.domain
    if policy is None:
        return obs_rows
    same = [r for r in obs_rows if r.get("domain") == target.get("domain")]
    if policy["policy"] == "hard":
        return same
    reach = policy["distance"]
    near = [r for r in obs_rows if r.get("domain") != target.get("domain")
            and np.linalg.norm(np.subtract(r["xyz"], target["xyz"])) <= reach]
    return same + near


def estimate(method, obs_rows, target_rows, analyte, plan: Plan, *, model=None, mean=None, secondary=(),
             thresholds=None, indicator_models=None, transform=None, target_supports=None,
             supports_by_id=None) -> dict:
    """Run one method; returns ``{"method", "rows": [per-target record], "extra": {...}}``."""
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}")
    if plan.domain is not None:
        inner = Plan(**{**plan.__dict__, "domain": None})
        rows_out, extras = [], []
        for t in target_rows:
            one = estimate(method, _domain_filter(obs_rows, t, plan), [t], analyte, inner, model=model, mean=mean,
                           secondary=secondary, thresholds=thresholds, indicator_models=indicator_models,
                           transform=transform)
            rows_out += one["rows"]
            extras.append(one["extra"])
        return {"method": method, "rows": rows_out, "extra": {"perTarget": extras, "domain": plan.domain}}
    analytes = [analyte, *secondary] if method == "ordinary-cokriging" else [analyte]
    usable = [r for r in obs_rows if analyte in r["values"]]
    if not usable:
        return {"method": method, "extra": {},
                "rows": [{"id": t["id"], "method": method, "status": "uninformed", "reason": "no observation",
                          "mean": None, "variance": None, "samples": 0, "holes": 0} for t in target_rows]}
    try:
        obs = observations(obs_rows, analytes, supports_by_id)
    except ValidationError as error:  # e.g. one variable twice at one support with different values
        return {"method": method, "extra": {"error": str(error)},
                "rows": [{"id": t["id"], "method": method, "status": "failed", "reason": str(error), "mean": None,
                          "variance": None, "samples": 0, "holes": 0} for t in target_rows]}
    observed = {f"{r['id']}|{a}": r["hole"] for r in obs_rows for a in analytes}
    if target_supports is None and supports_by_id is not None:
        target_supports = [supports_by_id[t["id"]] for t in target_rows]
    tgt = target_supports if target_supports is not None else targets(target_rows)
    hood = plan.neighbourhood()
    extra = {}
    if method == "nearest-neighbour":
        batch = nearest_neighbour(obs, tgt, neighborhood=hood)
    elif method == "inverse-distance":
        batch = inverse_distance(obs, tgt, power=plan.power, neighborhood=hood)
    elif method in ("simple-kriging", "ordinary-kriging", "universal-kriging", "ordinary-cokriging"):
        kind = {"simple-kriging": "simple", "ordinary-kriging": "ordinary", "universal-kriging": "universal",
                "ordinary-cokriging": "ordinary"}[method]
        try:
            batch = predict(obs, tgt, model, method=kind, target_variable=0,
                            mean=mean if kind == "simple" else None,
                            drift=plan.drift if kind == "universal" else None, neighborhood=hood)
        except ValidationError as error:
            return {"method": method, "extra": {"error": str(error)},
                    "rows": [{"id": t["id"], "method": method, "status": "failed", "reason": str(error),
                              "mean": None, "variance": None, "samples": 0, "holes": 0} for t in target_rows]}
        records = _records(batch, target_rows, observed, method)
        if kind == "simple":
            prior = float(np.atleast_1d(mean)[0])
            sill = float(model.total_sill[0, 0])
            for rec in records:
                if rec["status"] == "uninformed" and rec["samples"] == 0:  # nothing to condition on at all
                    rec.update(status="prior-only", mean=prior, variance=sill,
                               reason=f"no conditioning observation in the neighbourhood ({rec['reason']}); the "
                                      "declared mean and the total sill")
        if method == "ordinary-cokriging":
            extra["weightSums"] = [(d or {}).get("weight_sums") for d in batch.diagnostics]
        return {"method": method, "rows": records, "extra": extra}
    elif method == "multiple-indicator":
        result = indicator_kriging(obs, tgt, thresholds, indicator_models, neighborhood=hood)
        rows = []
        for i, t in enumerate(target_rows):
            rows.append({"id": t["id"], "method": method, "status": result.status[i], "reason": result.reasons[i],
                         "mean": None, "variance": None, "samples": 0, "holes": 0,
                         "raw": [None if not np.isfinite(x) else float(x) for x in result.raw[i]],
                         "cdf": [None if not np.isfinite(x) else float(x) for x in result.cdf[i]],
                         "correctionMax": float(result.correction_max[i])
                         if np.isfinite(result.correction_max[i]) else None})
        return {"method": method, "rows": rows, "extra": {"thresholds": [float(x) for x in thresholds]}}
    else:  # sequential-gaussian
        # A two-part search (GSLIB sstrat 0): the data by the shared plan, with its per-hole cap, and the nodes
        # already simulated apart, so dense nodes along one hole cannot crowd the other holes out of the system.
        nodes = Neighborhood(max_samples=plan.simulated_nodes, radius=plan.radius, metric=plan.metric)
        result = sequential_gaussian(obs, tgt, model, transform, realizations=plan.realizations, seed=plan.seed,
                                     neighborhood=plan.neighbourhood(), node_neighborhood=nodes)
        etype = result.etype()
        p10, p50, p90 = result.quantile(0.1), result.quantile(0.5), result.quantile(0.9)
        rows = [{"id": t["id"], "method": method, "status": "estimated", "reason": None,
                 "mean": float(etype[i]), "variance": float(result.native[:, i].var()),
                 "p10": float(p10[i]), "p50": float(p50[i]), "p90": float(p90[i]),
                 "hard": bool(result.hard[i]), "samples": 0, "holes": 0,
                 "realizations": [round(float(x), 9) for x in result.native[:, i]]} for i, t in enumerate(target_rows)]
        return {"method": method, "rows": rows,
                "extra": {"realizations": plan.realizations, "seed": plan.seed, "search": "two-part",
                          "perHoleCap": plan.max_per_hole, "simulatedNodes": plan.simulated_nodes,
                          "nativeSha256": hashlib.sha256(result.native.tobytes()).hexdigest()}}
    return {"method": method, "rows": _records(batch, target_rows, observed, method), "extra": extra}
