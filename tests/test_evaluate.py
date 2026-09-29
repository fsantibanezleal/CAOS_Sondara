"""The evaluate stage and the scenario matrix: direct recomputation, hole blocks, calibration, probability scores."""

import copy
import importlib.util
import json
import math
from pathlib import Path

import authored_field
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _contract():
    spec = importlib.util.spec_from_file_location("check_artifacts", ROOT / "scripts" / "check_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def evaluated(tmp_path_factory):
    """The authored field through evaluate, with the scenario variants declared on its first hole-group population."""
    import run
    import stages.infer

    folder, identifier = authored_field.chain(tmp_path_factory.mktemp("field"), stages=(
        "preprocess", "dataset", "features", "train"))
    models = json.loads((folder / "models.json").read_text(encoding="utf-8"))
    scheme = next(s for s in models["schemes"] if s["scheme"] == "hole-group")
    population = next(p["population"] for p in scheme["populations"] if p.get("model"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(stages.infer.VARIANT_POPULATIONS, identifier, ("hole-group", population))
        run.infer(identifier, folder.parent, "continuous")
    run.evaluate(identifier, folder.parent, "continuous")
    load = lambda name: json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
    return folder, identifier, population, {n: load(n) for n in ("project", "preprocessed", "dataset", "models",
                                                                 "predictions", "metrics")}


def _truth(data, scheme_id, population_id, analyte):
    from stages.train import _split_rows

    scheme = next(s for s in data["dataset"]["schemes"] if s["id"] == scheme_id)
    population = next(p for p in data["preprocessed"]["populations"] if p["id"] == population_id)
    rows = _split_rows(data["project"], data["preprocessed"], scheme, population)
    return {r["id"]: r for split in ("test", "calibration") for r in rows[split]}, rows


def test_scores_equal_a_direct_computation(evaluated):
    from stages.estimators import METHODS
    from stages.evaluate import CONTINUOUS, PREDICTED

    folder, _, _, data = evaluated
    checked = 0
    for pscheme, mscheme in zip(data["predictions"]["schemes"], data["metrics"]["schemes"], strict=True):
        for p, m in zip(pscheme["populations"], mscheme["populations"], strict=True):
            if not p["methods"]:
                continue
            assert list(m["methods"]) == list(METHODS)
            info, _ = _truth(data, pscheme["scheme"], p["population"], p["analyte"])
            predicted = {k: {r["id"]: r["mean"] for r in p["methods"][k]["rows"] if r["status"] in PREDICTED}
                         for k in CONTINUOUS}
            common = [t for t in p["targets"] if all(t in predicted[k] for k in CONTINUOUS)]
            assert m["commonTargets"] == len(common) > 0
            for method in CONTINUOUS:
                e = np.array([predicted[method][t] - info[t]["values"][p["analyte"]] for t in common])
                w = np.array([info[t]["length"] for t in common])
                holes = sorted({info[t]["hole"] for t in common})
                macro = np.mean([math.sqrt(np.mean([x ** 2 for x, t in zip(e, common, strict=True)
                                                    if info[t]["hole"] == h])) for h in holes])
                got = m["methods"][method]["common"]
                assert got["n"] == len(common) and got["holes"] == len(holes)
                assert got["bias"] == pytest.approx(e.mean(), abs=1e-12)
                assert got["mae"] == pytest.approx(np.abs(e).mean(), abs=1e-12)
                assert got["rmse"] == pytest.approx(math.sqrt(np.mean(e ** 2)), abs=1e-12)
                assert got["lengthWeighted"]["rmse"] == pytest.approx(math.sqrt(w @ e ** 2 / w.sum()), abs=1e-12)
                assert got["holeMacroRmse"] == pytest.approx(macro, abs=1e-12)
                checked += 1
    assert checked >= len(CONTINUOUS)
    assert _contract().check_family(folder) == []


def test_paired_hole_block_bootstrap():
    from stages.evaluate import paired

    rng = np.random.default_rng(3)
    a = rng.normal(size=60)
    holes = [f"h{k % 6}" for k in range(60)]
    same = paired(a, a, holes)
    assert same["meanAbsoluteErrorDifference"] == 0 and same["interval95"] == [0.0, 0.0]
    once, again, other = paired(a, a * 0.5, holes), paired(a, a * 0.5, holes), paired(a, a * 0.5, holes, seed=1)
    assert once == again and once["interval95"] != other["interval95"]
    low, high = once["interval95"]
    assert low <= once["meanAbsoluteErrorDifference"] <= high
    # One hole carries every difference: resampling holes, not rows, must show that the evidence is one hole wide.
    errors_a = np.r_[np.ones(1), np.zeros(99)]
    blocks = ["lone"] + ["crowd"] * 99
    by_hole = paired(errors_a, np.zeros(100), blocks)
    assert by_hole["holes"] == 2 and by_hole["interval95"][1] >= 0.5 - 1e-12  # the lone hole drawn twice: mean 1
    assert by_hole["interval95"][0] == 0.0  # the crowd drawn twice: mean 0


def test_calibration_uses_calibration_holes_only():
    from stages.evaluate import Z95, calibration

    rng = np.random.default_rng(4)
    rows = lambda prefix, n: [{"id": f"{prefix}{k}", "status": "estimated", "mean": float(rng.normal()),
                               "variance": 4.0} for k in range(n)]
    record = {"rows": rows("t", 40), "calibrationRows": rows("c", 30)}
    truth = {r["id"]: float(r["mean"] + rng.normal(0, 1.0)) for r in record["rows"] + record["calibrationRows"]}
    base = calibration(record, truth, "z")
    moved_test = dict(truth, **{f"t{k}": truth[f"t{k}"] + 50 for k in range(40)})
    moved_calibration = dict(truth, **{f"c{k}": truth[f"c{k}"] + 3 for k in range(30)})
    assert calibration(record, moved_test, "z")["varianceScale"] == base["varianceScale"]
    assert calibration(record, moved_calibration, "z")["varianceScale"] != base["varianceScale"]
    z = np.array([(r["mean"] - truth[r["id"]]) / 2.0 for r in record["calibrationRows"]])
    assert base["varianceScale"] == pytest.approx(np.mean(z ** 2), rel=1e-12)
    zt = np.array([(r["mean"] - truth[r["id"]]) / 2.0 for r in record["rows"]])
    assert base["test"]["coverage95"] == pytest.approx(np.mean(np.abs(zt) <= Z95))
    calibrated = zt / math.sqrt(base["varianceScale"])
    assert base["test"]["calibratedCoverage95"] == pytest.approx(np.mean(np.abs(calibrated) <= Z95))
    assert calibration({"rows": record["rows"], "calibrationRows": []}, truth, "z")["status"] == "not available"


def test_indicator_scores_against_the_training_proportion():
    from stages.evaluate import LOG_FLOOR, indicator_scores

    truth = {f"t{k}": float(k) for k in range(10)}
    training = [float(k) for k in range(20)]  # proportion below 4.5 is 5/20
    q = 5 / 20
    climatology = {"extra": {"thresholds": [4.5]},
                   "rows": [{"id": t, "status": "estimated", "cdf": [q]} for t in truth]}
    perfect = {"extra": {"thresholds": [4.5]},
               "rows": [{"id": t, "status": "estimated", "cdf": [1.0 if v <= 4.5 else 0.0]} for t, v in truth.items()]}
    flat = indicator_scores(climatology, truth, training)["thresholds"][0]
    assert flat["trainingProportion"] == q and flat["observedProportion"] == 0.5
    assert flat["brierSkill"] == pytest.approx(0.0, abs=1e-12)
    assert flat["logScore"] == pytest.approx(flat["logScoreReference"], abs=1e-12)
    sharp = indicator_scores(perfect, truth, training)
    assert sharp["thresholds"][0]["brier"] == 0 and sharp["thresholds"][0]["brierSkill"] == 1
    assert sharp["thresholds"][0]["logScore"] == pytest.approx(-math.log(1 - LOG_FLOOR))  # floored, finite
    assert sharp["logFloor"] == LOG_FLOOR


def test_sgs_fair_crps_and_reproduction():
    from stages.evaluate import convergence, downhole_pairs, fair_crps, reproduction, semivariance

    # CRPS of N(0, 1) at 0 is 2 phi(0) - 1 / sqrt(pi); the fair estimator is unbiased for four-member ensembles,
    # while the plain ensemble CRPS overstates it by E|X - X'| / (2 m).
    exact = 2 / math.sqrt(2 * math.pi) - 1 / math.sqrt(math.pi)
    rng = np.random.default_rng(5)
    draws = rng.normal(size=(20000, 4))
    fair = np.mean([fair_crps(x, 0.0) for x in draws])
    plain = np.mean([np.abs(x).mean() - np.abs(x[:, None] - x[None, :]).sum() / (2 * 16) for x in draws])
    assert fair == pytest.approx(exact, abs=0.006)
    assert plain - exact > 0.05
    assert fair_crps([0.0, 1.0], 0.0) == pytest.approx(0.0)
    # Pairs are binned by measured-depth separation within one hole.
    bins = downhole_pairs(["a", "a", "a", "b"], [1.0, 3.0, 5.0, 1.0], 2.0)
    assert bins[1] == [(0, 1), (1, 2)] and bins[2] == [(0, 2)] and not bins[3]
    assert semivariance([0.0, 2.0, 4.0], bins[1]) == pytest.approx(2.0)
    # A smoothed estimate loses the variability the realizations keep.
    ids = [f"t{k}" for k in range(30)]
    truth = {t: float(np.sin(k / 2)) for k, t in enumerate(ids)}
    info = {t: {"hole": f"h{k // 10}", "md": 1.0 + 2 * (k % 10), "length": 2.0} for k, t in enumerate(ids)}
    sgs = [{"id": t, "status": "estimated", "realizations": list(truth[t] + rng.normal(0, 0.1, 16))} for t in ids]
    ok = [{"id": t, "status": "estimated", "mean": 0.0} for t in ids]
    out = reproduction(sgs, ok, truth, info, list(truth.values()))
    assert out["status"] == "computed" and out["targets"] == 30 and out["realizations"] == 16
    assert out["histogram"]["ordinaryKriging"]["variance"] == 0.0
    assert out["histogram"]["realizations"]["variance"]["mean"] == pytest.approx(
        out["histogram"]["truth"]["variance"], rel=0.1)
    first = out["downholeVariogram"]["lags"][0]
    assert out["downholeVariogram"]["lag"] == 2.0 and first["pairs"] == 27 and first["ordinaryKriging"] == 0.0
    assert first["realizations"]["p10"] <= first["truth"] * 1.5 and first["realizations"]["mean"] > 0
    # Convergence reads the first 8, 16 and 32 realizations; the last entry is the full ensemble.
    wide = [{"id": t, "status": "estimated", "realizations": list(truth[t] + rng.normal(0, 0.3, 32))} for t in ids]
    steps = convergence(wide, truth)
    assert [s["realizations"] for s in steps] == [8, 16, 32] and all(s["targets"] == 30 for s in steps)
    full = np.array([r["realizations"] for r in wide])
    y = np.array([truth[t] for t in ids])
    assert steps[-1]["etypeRmse"] == pytest.approx(math.sqrt(np.mean((full.mean(axis=1) - y) ** 2)), rel=1e-12)
    assert steps[0]["fairCrps"] == pytest.approx(np.mean([fair_crps(x[:8], v) for x, v in zip(full, y, strict=True)]),
                                                 rel=1e-12)


def test_variants_are_computed_and_scored(evaluated):
    from stages.infer import NEIGHBOURHOODS

    _, _, population, data = evaluated
    record = next(p for s in data["metrics"]["schemes"] if s["scheme"] == "hole-group"
                  for p in s["populations"] if p["population"] == population)
    expected = {*NEIGHBOURHOODS, "isotropic", "integrated-support", "sparse-primary"}
    assert set(record["variants"]) == expected
    predicted = next(p for s in data["predictions"]["schemes"] if s["scheme"] == "hole-group"
                     for p in s["populations"] if p["population"] == population)
    for name, v in record["variants"].items():
        assert [r["id"] for r in predicted["variants"][name]["rows"]] == predicted["targets"], name
        assert v["scores"]["n"] == len(predicted["targets"]), name
        assert v["versusOrdinaryKriging"]["n"] == len(predicted["targets"]), name
    # The integrated support integrates over the 2 m (or 4 m) interval, so it is not the centre estimate.
    assert record["variants"]["integrated-support"]["meanShiftFromOrdinaryKriging"] != 0


def test_scenario_matrix_accounts_for_every_cell(tmp_path):
    from stages.estimators import METHODS
    from stages.scenarios import CELLS, LEARNED, scenario_matrix

    registry = json.loads((ROOT / "data" / "scenarios" / "registry.json").read_text(encoding="utf-8"))
    assert list(CELLS) == [s["id"] for s in registry["scenarios"]]
    contract = _contract()
    empty = scenario_matrix(tmp_path)  # no metrics yet: metric cells are missing, never computed
    for s in empty["scenarios"]:
        for c in s["cells"]:
            assert c["status"] == {"test": "verified", "pending": "pending"}.get(c["kind"], "missing"), (s["id"], c)
            assert c["kind"] != "pending" or c["owner"] in ("SD-7", "SD-8")
    assert any("missing" in e for e in contract.check_scenarios(empty, tmp_path))

    # Metrics shaped like the families' outputs: every cited method and variant resolves and cites its hash.
    def metrics(family):
        cells = [c for cs in CELLS.values() for c in cs if c.get("family") == family and c["kind"] in ("metric", "variant")]
        schemes = {}
        for c in cells:
            population = schemes.setdefault(c["scheme"], {}).setdefault(
                c["population"], {"population": c["population"], "methods": {}, "variants": {}})
            score = {"n": 3, "rmse": 1.5, "mae": 1.0, "bias": 0.1}
            population["methods"].update({m: {"common": score} for m in METHODS + LEARNED})
            if c["kind"] == "variant":
                population["variants"][c["variant"]] = {"scores": score}
        return {"family": family, "schemes": [{"scheme": s, "populations": list(p.values())}
                                              for s, p in schemes.items()]}

    for family in ("rocklea", "alberta"):
        (tmp_path / family).mkdir()
        for name in ("project.json", "preprocessed.json"):
            (tmp_path / family / name).write_text("{}", encoding="utf-8")
        (tmp_path / family / "metrics.json").write_text(json.dumps(metrics(family)), encoding="utf-8")
    # The categorical lane's outputs and the S10/S11 receipt, shaped like the stages write them.
    runs = [{"prior": c["prior"], "engine": c["engine"], "brierSkill": {"trainingProportions": 0.3},
             "all": {"n": 5, "brier": 0.4, "logScore": 0.9, "accuracy": 0.7}}
            for cs in CELLS.values() for c in cs if c["kind"] == "categorical"]
    categorical = {"eligible": True, "schemes": [{"scheme": "hole-group", "runs": runs}]}
    (tmp_path / "alberta" / "categorical-metrics.json").write_text(json.dumps(categorical), encoding="utf-8")
    (tmp_path / "alberta" / "categorical-models.json").write_text(
        json.dumps({"eligible": True, "mapping": {"mappingId": "m", "counts": {"0": 1}}}), encoding="utf-8")
    (tmp_path / "simulation-checks.json").write_text(json.dumps({"s10": {"passed": True}, "s11": {"passed": True}}),
                                                     encoding="utf-8")
    matrix = scenario_matrix(tmp_path)
    assert matrix["counts"]["missing"] == 0 and contract.check_scenarios(matrix, tmp_path) == []
    assert sum(matrix["counts"].values()) == sum(len(c) for c in CELLS.values())
    states = {s["id"]: s["state"] for s in matrix["scenarios"]}
    assert states["R01"] == "complete" and states["R10"] == "complete" and states["R12"] == "pending"
    assert states["A07"] == "complete" and states["S11"] == "complete"
    assert matrix["pendingByOwner"] == {o: sum(c.get("owner") == o for cs in CELLS.values() for c in cs)
                                        for o in ("SD-7", "SD-8")}
    failed = scenario_matrix  # a failed receipt is missing, never computed
    (tmp_path / "simulation-checks.json").write_text(
        json.dumps({"s10": {"passed": True}, "s11": {"passed": False, "reason": "no CUDA device"}}), encoding="utf-8")
    s11 = next(s for s in failed(tmp_path)["scenarios"] if s["id"] == "S11")
    assert s11["state"] == "missing" and any(c.get("reason") == "no CUDA device" for c in s11["cells"])
    categorical["schemes"][0]["runs"][0]["all"]["brier"] = 0.5
    (tmp_path / "alberta" / "categorical-metrics.json").write_text(json.dumps(categorical), encoding="utf-8")
    assert any("stale categorical" in e for e in contract.check_scenarios(matrix, tmp_path))
    stale = metrics("rocklea")
    stale["schemes"][0]["populations"][0]["methods"]["ordinary-kriging"]["common"]["rmse"] = 9.9
    (tmp_path / "rocklea" / "metrics.json").write_text(json.dumps(stale), encoding="utf-8")
    assert any("stale" in e for e in contract.check_scenarios(matrix, tmp_path))
    orphan = copy.deepcopy(matrix)
    next(c for s in orphan["scenarios"] for c in s["cells"] if c["status"] == "pending").pop("owner")
    assert any("no owner" in e for e in contract.check_scenarios(orphan, tmp_path))


def test_the_contract_check_rejects_stale_metrics(evaluated):
    _, _, _, data = evaluated
    contract = _contract()
    assert contract.check_metrics(data["metrics"], data["predictions"]) == []
    other = copy.deepcopy(data["predictions"])
    other["schemes"][0]["populations"][0]["methods"]["ordinary-kriging"]["rows"][0]["mean"] += 1.0
    assert contract.check_metrics(data["metrics"], other) == ["metrics were computed from other predictions"]
    unscored = copy.deepcopy(data["metrics"])
    population = next(p for s in unscored["schemes"] for p in s["populations"] if p.get("methods"))
    del population["methods"]["multiple-indicator"]
    unscored["inputPredictionsSha256"] = data["metrics"]["inputPredictionsSha256"]
    assert any("not scored" in e for e in contract.check_metrics(unscored, data["predictions"]))


def test_receipt_records_seeds_plan_engines_and_hashes(evaluated):
    import geocond
    from source_io import stable_hash

    _, _, _, data = evaluated
    receipt = data["metrics"]["receipt"]
    assert [s["seed"] for s in receipt["splits"]] == [s["seed"] for s in data["dataset"]["schemes"]]
    assert receipt["plan"] == data["models"]["plan"]
    for stage in ("fit", "infer", "evaluate"):
        assert receipt["engine"][stage]["geocond"] == geocond.__version__
    assert receipt["inputs"] == {"datasetSha256": stable_hash(data["dataset"]),
                                 "predictionsSha256": stable_hash(data["predictions"]),
                                 "modelsSha256": stable_hash(data["models"]),
                                 "learnedPredictionsSha256": None}  # the continuous lane alone
    assert receipt["resultSha256"] == stable_hash(data["metrics"]["schemes"])
