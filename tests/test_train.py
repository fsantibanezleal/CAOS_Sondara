"""The train stage on the authored field: selection by validation, train-only transforms, exact model records."""

import copy
import json

import authored_field
import numpy as np
import pytest


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    folder, identifier = authored_field.chain(tmp_path_factory.mktemp("field"), stages=(
        "preprocess", "dataset", "features", "train"))
    load = lambda name: json.loads((folder / name).read_text(encoding="utf-8"))
    return identifier, {name: load(f"{name}.json") for name in ("project", "preprocessed", "dataset", "features",
                                                                 "models")}


def test_model_selection_uses_validation_only(trained):
    from stages.train import FAMILY_SETS, FRAMES, train_family

    identifier, data = trained
    models = data["models"]
    fitted = [p for s in models["schemes"] for p in s["populations"]]
    assert fitted and all(p["status"] == "fitted" for p in fitted)
    for p in fitted:
        assert len(p["candidates"]) == 2 + len(FRAMES) * len(FAMILY_SETS)  # every declared candidate recorded
        admissible = [c for c in p["candidates"] if c["status"] == "fitted" and c["validationCoverage"] >= 0.9]
        best = min(admissible, key=lambda c: (c["validationRmse"], c["objective"]))
        assert p["selected"]["validationRmse"] == best["validationRmse"] and p["model"] == best["model"]
    # changing every test value changes nothing the train stage produces
    scheme = data["dataset"]["schemes"][0]
    test_holes = {h for h, s in scheme["assignment"].items() if s == "test"}
    changed = copy.deepcopy(data["preprocessed"])
    for r in changed["selections"]["rows"]:
        if r["geometry"][0] in test_holes:
            r["value"] = r["value"] * 3 + 1000
    for r in changed.get("composites", {}).get("rows", []):
        if r["holeId"] in test_holes:
            r["values"] = {k: (None if v is None else v * 3 + 1000) for k, v in r["values"].items()}
    again = train_family(identifier, data["project"], changed, data["dataset"], data["features"])
    assert again["schemes"][0] == {k: v for k, v in models["schemes"][0].items()}


def test_lmc_indicators_and_normal_scores_are_train_only(trained):
    from stages.dataset import members
    from stages.features import declustered_mean, population_rows

    _, data = trained
    scheme = data["dataset"]["schemes"][0]
    p = data["models"]["schemes"][0]["populations"][0]
    assert p["lmc"]["status"] == "fitted" and p["lmc"]["variables"] == ["Cu", "Zn"]
    assert all(min(values) >= -1e-10 for values in p["lmc"]["eigenvalues"])  # every sill matrix PSD
    population = next(x for x in data["preprocessed"]["populations"] if x["id"] == p["population"])
    holes = {s["id"]: s["holeId"] for s in data["project"]["supports"]}
    train_ids = members([(m, holes[m]) for m in population["members"]], scheme["assignment"])["train"]
    rows = [r for r in population_rows(data["preprocessed"], train_ids) if "Cu" in r["values"]]
    z = np.array([r["values"]["Cu"] for r in rows])
    assert p["gaussian"]["transform"]["values"] == sorted(set(z.tolist()))  # the table is the training values
    thresholds = [t["threshold"] for t in p["indicator"]["thresholds"]]
    assert thresholds == sorted(set(thresholds)) and set(thresholds) <= set(z.tolist())
    cell = next(pp for s in data["features"]["schemes"] if s["scheme"] == scheme["id"]
                for pp in s["populations"] if pp["population"] == p["population"])
    _, weights = declustered_mean(np.array([r["xyz"] for r in rows]), z,
                                  tuple(cell["analytes"]["Cu"]["statistics"]["declustered"]["cell"]))
    order = np.argsort(z, kind="stable")
    cumulative = np.cumsum(weights[order]) / weights.sum()
    expected = sorted({float(z[order][np.searchsorted(cumulative, q)]) for q in [k / 10 for k in range(1, 10)]})
    assert thresholds == expected  # training-weighted deciles


def test_models_round_trip(trained):
    from geocond import NormalScoreTransform
    from stages.models import model_from, model_record, transform_from, transform_record, variogram_from

    _, data = trained
    p = data["models"]["schemes"][0]["populations"][0]
    for record in (p["model"], p["universal"]["model"], p["lmc"]["model"], p["gaussian"]["model"]):
        model = model_from(record)
        assert model_record(model) == record
        h = np.array([[10.0, 5.0, -2.0], [0.0, 0.0, 0.0], [80.0, 0.0, 0.0]])
        again = model_from(model_record(model))
        assert np.array_equal(model.covariance(h), again.covariance(h))
    transform = transform_from(p["gaussian"]["transform"])
    assert isinstance(transform, NormalScoreTransform) and transform_record(transform) == p["gaussian"]["transform"]
    values = np.linspace(min(transform.values), max(transform.values), 7)
    assert np.allclose(transform.backward(transform.forward(values)), values)
    record = data["features"]["schemes"][0]["populations"][0]["analytes"]["Cu"]["variograms"][1]
    rebuilt = variogram_from(record)
    assert rebuilt.counts.tolist() == record["counts"] and list(rebuilt.edges) == record["edges"]
