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


def test_other_covariances_follow_the_selected_structure(trained):
    from geocond import fit_variogram, principal_frame
    from stages import train
    from stages.features import variograms
    from stages.models import model_from, variogram_from

    _, data = trained
    checked = 0
    for scheme, fscheme in zip(data["models"]["schemes"], data["features"]["schemes"], strict=True):
        split = next(s for s in data["dataset"]["schemes"] if s["id"] == scheme["scheme"])
        for p, fp in zip(scheme["populations"], fscheme["populations"], strict=True):
            selected = p["selected"]
            frame = None if selected["kind"] == "isotropic" else principal_frame(selected["frameAzimuth"], 0.0, 0.0)
            names = ["omni"] if frame is None else list(train.DIRECTIONAL)
            assert p["structure"]["families"] == selected["families"] and p["structure"]["variograms"] == names
            models = [(p["universal"]["model"], selected["families"]), (p["lmc"]["model"], selected["families"])]
            models += [(t["model"], ["spherical"]) for t in p["indicator"]["thresholds"] if t["status"] == "fitted"]
            for record, families in models:
                model = model_from(record)
                assert [c.family for c in model.components] == families
                for c in model.components:
                    if frame is None:
                        assert len(set(np.round(c.ranges, 9))) == 1  # isotropic
                    else:
                        assert np.allclose(c.rotation, frame)
            # An indicator model is the fit of the indicators' own variograms, defined as the features stage defines
            # the direct ones, in the selected frame.
            population = next(x for x in data["preprocessed"]["populations"] if x["id"] == p["population"])
            split_rows = train._split_rows(data["project"], data["preprocessed"], split, population)["train"]
            rows = [r for r in split_rows if p["analyte"] in r["values"]]
            first = next(t for t in p["indicator"]["thresholds"] if t["status"] == "fitted")
            indicator = [float(r["values"][p["analyte"]] <= first["threshold"]) for r in rows]
            pseudo = [{**r, "values": {"v": v}} for r, v in zip(rows, indicator, strict=True)]
            by_name = {v["name"]: v for v in variograms(pseudo, "v", fscheme["collarSpacing"], fp["supportLength"])}
            used = [variogram_from(by_name[n]) for n in names]
            fit = (fit_variogram(used, ("spherical",), isotropic=True) if frame is None
                   else fit_variogram(used, ("spherical",), rotation=frame))
            assert np.allclose(first["model"]["nugget"], fit.model.nugget, rtol=1e-12, atol=0)
            assert model_from(first["model"]).components[0].ranges == pytest.approx(fit.model.components[0].ranges,
                                                                                    rel=1e-12)
            checked += 1
    assert checked
    # An anisotropic selection fits on the four horizontal and the vertical variograms, in its own frame.
    structure = train.Structure({"kind": "anisotropic", "frameAzimuth": 45.0, "families": ["spherical"]}, 50.0, 2.0)
    assert structure.names == train.DIRECTIONAL and np.allclose(structure.rotation, principal_frame(45.0, 0.0, 0.0))


def test_the_gaussian_covariance_is_selected_on_validation(trained):
    from geocond import fit_variogram, principal_frame
    from stages import train
    from stages.estimators import estimate
    from stages.models import model_from, transform_from

    _, data = trained
    checked = 0
    for scheme, fscheme in zip(data["models"]["schemes"], data["features"]["schemes"], strict=True):
        split = next(s for s in data["dataset"]["schemes"] if s["id"] == scheme["scheme"])
        for p, fp in zip(scheme["populations"], fscheme["populations"], strict=True):
            g = p["gaussian"]
            candidates = g["candidates"]
            assert [(c["frameAzimuth"], c["families"]) for c in candidates] == [
                (f, list(fams)) for f in train.FRAMES for fams in train.FAMILY_SETS]  # every declared candidate
            assert all(c["kind"] == "anisotropic" for c in candidates)
            admissible = [c for c in candidates if c["status"] == "fitted" and c["validationCoverage"] >= 0.9]
            best = min(admissible, key=lambda c: (c["validationRmse"], c["objective"]))
            assert g["model"] == best["model"] and g["selected"]["validationRmse"] == best["validationRmse"]
            # Recompute the chosen candidate: its fit on the normal scores' variograms and its validation RMSE.
            population = next(x for x in data["preprocessed"]["populations"] if x["id"] == p["population"])
            rows = train._split_rows(data["project"], data["preprocessed"], split, population)
            transform = transform_from(g["transform"])
            train_rows = [r for r in rows["train"] if p["analyte"] in r["values"]]
            held = [r for r in rows["validation"] if p["analyte"] in r["values"]]
            y = transform.forward(np.array([r["values"][p["analyte"]] for r in train_rows]))
            structure = train.Structure({"kind": "anisotropic", "frameAzimuth": best["frameAzimuth"],
                                         "families": best["families"]}, fscheme["collarSpacing"], fp["supportLength"])
            used = structure.variograms_of(train_rows, y)
            fit = fit_variogram(used, best["families"], rotation=principal_frame(best["frameAzimuth"], 0.0, 0.0))
            assert model_from(g["model"]).components[0].ranges == pytest.approx(fit.model.components[0].ranges,
                                                                                rel=1e-12)
            scored = [{**r, "values": {"y": float(v)}} for r, v in zip(train_rows, y, strict=True)]
            truth = transform.forward(np.array([r["values"][p["analyte"]] for r in held]))
            check = [{**r, "values": {"y": float(v)}} for r, v in zip(held, truth, strict=True)]
            out = estimate("simple-kriging", scored, check, "y", train.PLAN, model=fit.model, mean=0.0)["rows"]
            errors = [r["mean"] - v for r, v in zip(out, truth, strict=True) if r["status"] == "estimated"]
            assert best["validationRmse"] == pytest.approx(float(np.sqrt(np.mean(np.square(errors)))), rel=1e-12)
            checked += 1
    assert checked
