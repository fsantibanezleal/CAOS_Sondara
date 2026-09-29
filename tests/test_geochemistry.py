"""The geochemical autoencoder review (SD-7b, R12): training-only transform, selection and the PCA reference,
alterations that really alter, a threshold from calibration records, and an audited, bound export. Runs in .venv-gpu;
the lane tests use the authored field's compositional analytes and a reduced epoch budget."""

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data-pipeline"))
sys.path.insert(0, str(ROOT / "tests"))

import authored_field
from learned import exporting, features
from learned.contracts import SEEDS, check_binding
from learned.evaluation import alterations
from learned.networks import GeochemicalAutoencoder

POPULATION = "authored-field-Fe-native"


@pytest.fixture(scope="module")
def review(tmp_path_factory):
    import stages.geochemistry as G

    folder, identifier = authored_field.chain(tmp_path_factory.mktemp("field"), stages=("preprocess", "dataset"),
                                              geochemistry=True)
    load = lambda name: json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
    data = {n: load(n) for n in ("project", "preprocessed", "dataset")}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(G, "POPULATION", POPULATION)
        models = G.train_geochemistry(identifier, data["project"], data["preprocessed"], data["dataset"], folder,
                                      epochs=60, patience=20)
        predictions = G.infer_geochemistry(models, data["project"], data["preprocessed"], data["dataset"], folder)
    metrics = G.evaluate_geochemistry(predictions)
    return folder, data, models, predictions, metrics


# R-723 ----------------------------------------------------------------------------------------------------------


def test_the_transform_is_fitted_on_training_records_only():
    train = np.array([[1.0, 5.0, 2.0, 7.0], [3.0, 5.0, 4.0, 8.0], [5.0, 5.0, 9.0, 1.0], [7.0, 5.0, 3.0, 2.0]])
    t = features.fit_geochemistry(train, ["a", "b", "c", "d"])
    assert t["removedZeroIqr"] == ["b"] and t["properties"] == ["a", "c", "d"] and t["indices"] == [0, 2, 3]
    assert t["median"] == [4.0, 3.5, 4.5]
    x = features.geochemical_features(train, t)
    expected = np.arcsinh((train[:, [0, 2, 3]] - np.array(t["median"])) / np.array(t["scale"]))
    assert np.allclose(x, expected, atol=1e-6)
    with pytest.raises(ValueError, match="incomplete"):
        features.geochemical_features(np.array([[1.0, 5.0, np.nan, 2.0]]), t)
    with pytest.raises(ValueError, match="three"):
        features.fit_geochemistry(train[:, [0, 1]], ["a", "b"])


def test_the_review_transform_sees_training_records_only(review):
    import stages.geochemistry as G

    _, data, models, _, _ = review
    scheme = next(s for s in data["dataset"]["schemes"] if s["id"] == "hole-group")
    training = {h for h, s in scheme["assignment"].items() if s == "train"}
    changed = copy.deepcopy(data["preprocessed"])
    for r in changed["selections"]["rows"]:
        if r["geometry"][0] not in training and isinstance(r["value"], (int, float)):
            r["value"] = r["value"] * 2 + 1
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(G, "POPULATION", POPULATION)
        split = G._split(data["project"], changed, data["dataset"], models["properties"])
    again = features.fit_geochemistry(split["train"]["values"], models["properties"])
    assert again == models["transform"]


# R-724 ----------------------------------------------------------------------------------------------------------


def test_selection_and_the_pca_reference(review):
    import stages.geochemistry as G

    _, data, models, _, _ = review
    with pytest.raises(ValueError, match="bottleneck"):
        GeochemicalAutoencoder(3, 3)
    assert models["eligible"] and [c["latent"] for c in models["configurations"]] == [2, 3]
    for c in models["configurations"]:
        assert [f["seed"] for f in c["fits"]] == list(SEEDS)
    means = {c["latent"]: np.mean([f["bestValidationObjective"] for f in c["fits"]]) for c in models["configurations"]}
    assert models["selected"] == min(means, key=means.get)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(G, "POPULATION", POPULATION)
        split = G._split(data["project"], data["preprocessed"], data["dataset"], models["properties"])
    x = features.geochemical_features(split["train"]["values"], models["transform"]).astype(np.float64)
    pca = G._pca(x, models["selected"])
    assert pca["rank"] == models["selected"] and np.allclose(pca["mean"], models["pca"]["mean"])
    assert np.allclose(np.abs(pca["components"]), np.abs(models["pca"]["components"]), atol=1e-6)


# R-725 ----------------------------------------------------------------------------------------------------------


def test_every_altered_record_is_altered():
    rng = np.random.default_rng(1)
    values = np.abs(rng.normal(20, 5, (40, 4)))
    values[3] = 0.0  # a record with nothing to multiply
    holes = np.array([f"H{i % 5}" for i in range(40)])
    props = ["Fe", "SiO2", "Al2O3", "LOI"]
    t = features.fit_geochemistry(values, props)
    kinds = alterations(values, holes, props, t, seed=7)
    assert [k["kind"] for k in kinds][:4] == ["unchanged", "times-ten", "unit-omission", "cross-hole-pair"]
    unchanged = kinds[0]
    assert not unchanged["altered"].any() and np.array_equal(unchanged["values"], values)
    for k in kinds[1:]:
        changed = np.any(k["values"] != values, axis=1)
        assert np.array_equal(changed, k["altered"]), k["kind"]  # altered exactly where the values changed
        for i in np.flatnonzero(k["altered"]):
            assert k["property"][i]
            if k["kind"] == "cross-hole-pair":
                assert holes[k["donor"][i]] != holes[i]
    times_ten = kinds[1]
    assert not times_ten["altered"][3] and times_ten["altered"].sum() == 39
    additive = [k for k in kinds if k["kind"].startswith("transformed-additive")]
    assert [k["severity"] for k in additive] == [0.25, 1.0, 3.0] and all(k["altered"].all() for k in additive)


# R-726 ----------------------------------------------------------------------------------------------------------


def test_the_threshold_comes_from_calibration_records(review):
    import stages.geochemistry as G

    _, _, _, predictions, metrics = review
    for m in ("ae", "pca"):
        scores = [r[f"{m}Score"] for r in predictions["records"]["calibration"]]
        assert metrics["thresholds"][m] == pytest.approx(float(np.quantile(scores, 0.95, method="higher")))
    moved = copy.deepcopy(predictions)
    for r in moved["records"]["test"]:
        r["aeScore"] += 100.0
    assert G.evaluate_geochemistry(moved)["thresholds"] == metrics["thresholds"]
    kinds = metrics["alterations"]
    assert set(kinds) == {k["kind"] for k in predictions["alterations"]}
    assert "falseFlags" in kinds["unchanged"]["ae"] and "falseFlags" in kinds["unchanged"]["pca"]
    for name, entry in kinds.items():
        if name != "unchanged" and entry["altered"]:
            assert 0 <= entry["ae"]["recall"] <= 1 and 0 <= entry["pca"]["recall"] <= 1
    assert kinds["unit-omission"]["ae"]["recall"] == 1.0  # a percent read as ppm is far outside the training data


# R-727 ----------------------------------------------------------------------------------------------------------


def test_the_review_export_is_audited_and_bound(review):
    import onnxruntime as ort

    folder, _, models, predictions, _ = review
    assert sorted(e["seed"] for e in predictions["exports"]) == sorted(SEEDS)
    for e in predictions["exports"]:
        path = folder / e["folder"] / "model.onnx"
        audit = exporting.audit_model(path)
        assert audit["sha256"] == e["model"]["sha256"] and exporting.scan_paths(path) == []
        manifest = json.loads((folder / e["folder"] / "manifest.json").read_text(encoding="utf-8"))
        assert list(manifest["outputs"]) == ["latent", "residual", "score"]
        assert manifest["binding"] == models["binding"]
        parity = json.loads((folder / e["folder"] / "parity.json").read_text(encoding="utf-8"))
        assert parity["passed"] and parity["onnxCpuMaxAbsolute"] <= parity["tolerance"]
        session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        inputs = parity["fixture"]["inputs"]["values"]
        latent, residual, score = session.run(None, {"values": np.asarray(inputs["data"], dtype=np.float32)
                                                     .reshape(inputs["shape"])})
        assert latent.shape[1] == models["selected"] and residual.shape[1] == len(models["transform"]["properties"])
        assert np.allclose(score, residual.mean(axis=1), atol=1e-6)
    manifest = exporting.validate_portable(folder / predictions["exports"][0]["folder"] / "portable-model.zip")
    bound = manifest["binding"]
    project = {"projectId": bound["projectId"], "frameId": bound["frameId"], "task": bound["task"],
               "propertyUnits": dict(bound["propertyUnits"])}
    check_binding(manifest, project)
    wrong = {**project, "propertyUnits": {**project["propertyUnits"], "Fe": "ppm"}}
    with pytest.raises(ValueError, match="out-of-domain"):
        check_binding(manifest, wrong)
    missing = {**project, "propertyUnits": {k: v for k, v in project["propertyUnits"].items() if k != "SiO2"}}
    with pytest.raises(ValueError, match="out-of-domain"):
        check_binding(manifest, missing)
