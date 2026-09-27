"""The method layer on authored truths (S05 to S09) and fixtures F31 to F37 and F39, through GeoCond."""

import json
import math
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from geocond import CovarianceComponent, CovarianceModel, ValidationError, block_support, principal_frame

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = {f["id"]: f for f in json.loads((ROOT / "data" / "fixtures" / "registry.json").read_text())["fixtures"]}


def _rows(points, hole=None):
    return [{"id": f"o{i}", "hole": hole or f"h{i}", "xyz": list(map(float, p[:3])), "values": {"z": float(p[3])}}
            for i, p in enumerate(points)]


def _targets(points):
    return [{"id": f"t{i}", "hole": "target", "xyz": list(map(float, p[:3])), "values": {}} for i, p in enumerate(points)]


def _model(family="spherical", ranges=100.0, sill=1.0, nugget=0.0, rotation=None):
    return CovarianceModel((CovarianceComponent(family, ranges, [[sill]], rotation),), [[nugget]])


def _plan(**kw):
    from stages.estimators import Plan

    return Plan(**{"max_samples": 32, "min_samples": 1, "max_per_hole": None, **kw})


def test_constant_and_polynomial_truths():
    from stages.estimators import estimate

    rng = np.random.default_rng(1)
    points = rng.uniform(0, 100, (30, 3))
    withheld = rng.uniform(10, 90, (8, 3))
    constant = _rows(np.c_[points, np.full(30, 5.0)])
    out = estimate("ordinary-kriging", constant, _targets(withheld), "z", _plan(), model=_model())
    assert all(r["status"] == "estimated" for r in out["rows"])
    assert [r["mean"] for r in out["rows"]] == pytest.approx([5.0] * 8, rel=1e-7)
    field = lambda p: 2.0 + 0.1 * p[0] - 0.05 * p[1] + 0.02 * p[2]
    linear = _rows(np.c_[points, [field(p) for p in points]])
    out = estimate("universal-kriging", linear, _targets(withheld), "z", _plan(drift="linear"), model=_model())
    assert [r["mean"] for r in out["rows"]] == pytest.approx([field(p) for p in withheld], rel=1e-7)


def test_rotation_invariance():
    from stages.estimators import estimate

    p = REGISTRY["F33"]["parameters"]
    frame = principal_frame(*p["anisotropy"]["rotation"])
    turn = principal_frame(*p["rigidRotation"])
    rng = np.random.default_rng(2)
    points = rng.uniform(-80, 80, (40, 3))
    values = rng.normal(size=40)
    withheld = rng.uniform(-50, 50, (10, 3))
    shift = np.array([500.0, -200.0, 30.0])
    model = _model("exponential", p["anisotropy"]["ranges"], rotation=frame)
    rotated_model = _model("exponential", p["anisotropy"]["ranges"], rotation=turn @ frame)
    before = estimate("ordinary-kriging", _rows(np.c_[points, values]), _targets(withheld), "z", _plan(), model=model)
    after = estimate("ordinary-kriging", _rows(np.c_[points @ turn.T + shift, values]),
                     _targets(withheld @ turn.T + shift), "z", _plan(), model=rotated_model)
    difference = max(abs(a["mean"] - b["mean"]) for a, b in zip(before["rows"], after["rows"], strict=True))
    assert difference <= p["expect"]["maxAbsoluteDifference"]


def test_cokriging_reduces_and_matches_the_analytic_case():
    from stages.estimators import estimate

    rng = np.random.default_rng(3)
    points = rng.uniform(0, 100, (20, 3))
    rows = [{"id": f"o{i}", "hole": f"h{i}", "xyz": list(x), "values": {"a": float(rng.normal()), "b": float(rng.normal())}}
            for i, x in enumerate(points)]
    targets = _targets(rng.uniform(10, 90, (5, 3)))
    independent = CovarianceModel((CovarianceComponent("spherical", 60.0, [[1.0, 0.0], [0.0, 2.0]]),),
                                  [[0.0, 0.0], [0.0, 0.0]])
    joint = estimate("ordinary-cokriging", rows, targets, "a", _plan(), model=independent, secondary=["b"])
    alone = estimate("ordinary-kriging", rows, targets, "a", _plan(), model=_model("spherical", 60.0))
    assert [r["mean"] for r in joint["rows"]] == pytest.approx([r["mean"] for r in alone["rows"]], abs=1e-9)
    # C = [[1, 0.4], [0.4, 1]], c = [0.5, 0.8]: weights 3/14 and 5/7, variance 9/28
    a = 1.0
    d = a * math.log(2) / 3  # exponential correlation exp(-3 r / a) = 0.5
    lmc = CovarianceModel((CovarianceComponent("exponential", a, [[1.0, 0.8], [0.8, 1.0]]),), [[0.0, 0.0], [0.0, 0.0]])
    target = [{"id": "t", "hole": "t", "xyz": [0.0, 0.0, 0.0], "values": {}}]
    for primary, secondary, expected in ((1.0, 0.0, 3 / 14), (0.0, 1.0, 5 / 7)):
        obs = [{"id": "p", "hole": "p", "xyz": [d, 0.0, 0.0], "values": {"a": primary}},
               {"id": "s", "hole": "s", "xyz": [0.0, 0.0, 0.0], "values": {"b": secondary}}]
        (row,) = estimate("ordinary-cokriging", obs, target, "a", _plan(), model=lmc, secondary=["b"])["rows"]
        from geocond import predict
        from stages.estimators import observations, targets

        batch = predict(observations(obs, ["a", "b"]), targets(target), lmc, method="simple", mean=[0.0, 0.0])
        assert batch.mean[0] == pytest.approx(expected, abs=1e-12)
        assert batch.variance[0] == pytest.approx(9 / 28, abs=1e-12)
        assert row["status"] == "estimated"


def test_invalid_models_and_systems_fail_honestly():
    from stages.estimators import estimate

    with pytest.raises(ValidationError):  # pairwise-valid correlations, but not positive semidefinite
        CovarianceComponent("spherical", 50.0, [[1, 0.9, 0.9], [0.9, 1, -0.9], [0.9, -0.9, 1]])
    p34 = REGISTRY["F34"]["parameters"]
    conflicting = _rows(p34["observations"])
    out = estimate("ordinary-kriging", conflicting, _targets([[1, 0, 0]]), "z", _plan(),
                   model=_model(nugget=p34["nugget"]))
    (row,) = out["rows"]
    assert row["status"] == p34["expect"]["status"] and row["mean"] is None and "same support" in row["reason"]
    p37 = REGISTRY["F37"]["parameters"]
    out = estimate("universal-kriging", _rows(p37["observations"]), _targets([p37["target"]]), "z",
                   _plan(drift=p37["drift"]), model=_model(ranges=10.0))
    (row,) = out["rows"]
    assert (row["status"], row["method"]) == ("failed", "universal-kriging")
    assert "rank deficient" in row["reason"] and row["mean"] is None


def test_block_quadrature_converges():
    from stages.estimators import estimate

    rng = np.random.default_rng(4)
    points = rng.uniform(0, 100, (25, 3))
    rows = _rows(np.c_[points, rng.normal(size=25)])
    model = _model("spherical", 80.0)
    target = _targets([[50, 50, 50]])
    means, variances = [], []
    for order in (1, 2, 4, 8, 16):
        support = [block_support([50.0, 50.0, 50.0], [20.0, 20.0, 10.0], order=order)]
        (row,) = estimate("ordinary-kriging", rows, target, "z", _plan(), model=model, target_supports=support)["rows"]
        means.append(row["mean"])
        variances.append(row["variance"])
    for series in (means, variances):
        steps = [abs(b - a) for a, b in pairwise(series)]
        assert all(later < earlier for earlier, later in pairwise(steps))  # each doubling helps
        assert steps[-1] < 1e-3 * float(model.total_sill[0, 0])  # order 8 to 16 changes less than 0.1 % of the sill


def test_neighbourhood_limits_and_uninformed_targets():
    from stages.estimators import estimate

    p31 = REGISTRY["F31"]["parameters"]
    out = estimate("ordinary-kriging", _rows(p31["observations"]), _targets([p31["target"]]), "z",
                   _plan(radius=p31["neighbourhood"]["radius"], min_samples=p31["neighbourhood"]["minObservations"]),
                   model=_model())
    (row,) = out["rows"]
    assert row["status"] == "uninformed" and "fewer than min_samples = 3" in row["reason"] and row["mean"] is None
    p32 = REGISTRY["F32"]["parameters"]
    dense = [{"id": f"a{k}", "hole": "A", "xyz": [0.0, 0.0, -float(k)], "values": {"z": float(k)}}
             for k in range(p32["denseHole"]["count"])]
    others = [{"id": h, "hole": h, "xyz": [30.0 * (i + 1), 0.0, -5.0], "values": {"z": 1.0}}
              for i, h in enumerate(p32["otherHoles"])]
    plan = _plan(max_samples=p32["neighbourhood"]["maxObservations"], max_per_hole=p32["neighbourhood"]["maxPerHole"])
    (row,) = estimate("ordinary-kriging", dense + others, _targets([[1.0, 0.0, -5.0]]), "z", plan,
                      model=_model())["rows"]
    assert row["maxFromOneHole"] == p32["expect"]["maxFromOneHole"] and row["holes"] == 4
    (unlimited,) = estimate("ordinary-kriging", dense + others, _targets([[1.0, 0.0, -5.0]]), "z",
                            _plan(max_samples=12), model=_model())["rows"]
    assert unlimited["maxFromOneHole"] > 4  # without the cap the dense hole dominates


def test_domain_boundaries():
    from stages.estimators import estimate

    p = REGISTRY["F35"]["parameters"]
    rows = []
    for domain, points in p["domains"].items():
        for k, (x, y, z, v) in enumerate(points):
            rows.append({"id": f"{domain}{k}", "hole": f"{domain}{k}", "xyz": [x, y, z], "values": {"z": v},
                         "domain": domain})
    target = [{"id": "t", "hole": "t", "xyz": p["target"]["at"], "values": {}, "domain": p["target"]["domain"]}]
    (hard,) = estimate("inverse-distance", rows, target, "z", _plan(domain={"policy": "hard"}))["rows"]
    assert hard["mean"] == pytest.approx(1.0) and hard["samples"] == 1
    soft_plan = _plan(domain={"policy": "soft", "distance": p["expect"]["soft"]["distance"]})
    (soft,) = estimate("inverse-distance", rows, target, "z", soft_plan)["rows"]
    assert 1.0 < soft["mean"] < 9.0 and soft["samples"] == 2


def test_simple_kriging_prior_without_conditioning():
    from stages.estimators import estimate

    p = REGISTRY["F36"]["parameters"]
    (row,) = estimate("simple-kriging", _rows(p["observations"]), _targets([p["target"]]), "z",
                      _plan(radius=p["range"]), model=_model(ranges=p["range"]), mean=p["mean"])["rows"]
    assert (row["status"], row["mean"]) == ("prior-only", p["expect"]["estimate"]) and row["samples"] == 0
    assert row["variance"] == pytest.approx(1.0) and "no conditioning observation" in row["reason"]


def test_sgs_seeds_and_hard_data():
    from geocond import NormalScoreTransform
    from stages.estimators import estimate

    p = REGISTRY["F39"]["parameters"]
    rng = np.random.default_rng(5)
    points = rng.uniform(0, 50, (15, 3))
    values = rng.lognormal(1.0, 0.5, 15)
    rows = _rows(np.c_[points, values])
    targets = _targets(np.vstack([points[:2], rng.uniform(0, 50, (6, 3))]))  # two nodes on observations
    transform = NormalScoreTransform.fit(values)
    run = lambda seed: estimate("sequential-gaussian", rows, targets, "z",
                                _plan(realizations=p["realizations"], seed=seed), model=_model(ranges=30.0),
                                transform=transform)
    first, again, other = run(p["seed"]), run(p["seed"]), run(p["seed"] + 1)
    assert first["extra"]["nativeSha256"] == again["extra"]["nativeSha256"]
    assert first["extra"]["nativeSha256"] != other["extra"]["nativeSha256"]
    for k in range(2):
        row = first["rows"][k]
        assert row["hard"] and row["p10"] == pytest.approx(values[k]) and row["p90"] == pytest.approx(values[k])


def test_every_method_predicts_every_test_target(tmp_path):
    import importlib.util

    import authored_field
    from stages.estimators import METHODS

    folder, _ = authored_field.chain(tmp_path)
    predictions = json.loads((folder / "predictions.json").read_text(encoding="utf-8"))
    populations = [p for s in predictions["schemes"] for p in s["populations"]]
    assert populations and all(p["targets"] for p in populations)
    for p in populations:
        assert list(p["methods"]) == list(METHODS)
        for method, result in p["methods"].items():
            assert [r["id"] for r in result["rows"]] == p["targets"], method
            assert all(r["status"] == "estimated" for r in result["rows"]), method  # a well-posed authored field
    spec = importlib.util.spec_from_file_location("check_artifacts", ROOT / "scripts" / "check_artifacts.py")
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    assert contract.check_family(folder) == []
    broken = json.loads((folder / "predictions.json").read_text(encoding="utf-8"))
    del broken["schemes"][0]["populations"][0]["methods"]["sequential-gaussian"]
    models = json.loads((folder / "models.json").read_text(encoding="utf-8"))
    assert any("missing" in e for e in contract.check_predictions(broken, models))


def test_sgs_searches_data_and_simulated_nodes_apart():
    from geocond import Neighborhood, NormalScoreTransform, sequential_gaussian
    from stages.estimators import estimate, observations, targets

    rng = np.random.default_rng(12)
    rows = [{"id": f"o{h}-{k}", "hole": f"h{h}", "xyz": [40.0 * (h % 3), 40.0 * (h // 3), -float(k)],
             "values": {"z": float(rng.normal())}} for h in range(6) for k in range(10)]
    line = _targets(np.c_[np.full(20, 20.0), np.full(20, 20.0), -np.arange(20.0), np.zeros(20)])
    transform = NormalScoreTransform.fit([r["values"]["z"] for r in rows])
    plan = _plan(max_samples=8, min_samples=2, max_per_hole=2, simulated_nodes=5, realizations=6, seed=9)
    assert plan.record()["simulatedNodes"] == 5
    out = estimate("sequential-gaussian", rows, line, "z", plan, model=_model(ranges=30.0), transform=transform)
    assert out["extra"]["search"] == "two-part" and out["extra"]["perHoleCap"] == 2
    assert out["extra"]["simulatedNodes"] == 5
    direct = sequential_gaussian(observations(rows, ["z"]), targets(line), _model(ranges=30.0), transform,
                                 realizations=6, seed=9,
                                 neighborhood=Neighborhood(max_samples=8, min_samples=2, max_per_group=2),
                                 node_neighborhood=Neighborhood(max_samples=5))
    assert np.allclose([r["realizations"] for r in out["rows"]], direct.native.T, rtol=0, atol=1e-9)
