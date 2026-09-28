"""The learned lane (SD-7a): DeepKriging and KCN on the classical splits and targets, their fits, controls, exports
and parity, and their scores beside the classical methods. Runs in .venv-gpu (PyTorch, onnx, ONNX Runtime); the lane
tests use a reduced search and epoch budget on the authored field, which the design allows the tests to declare."""

import copy
import json
import math
import sys
import zipfile
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
from learned import exporting, features, networks, training
from learned.contracts import SEEDS, check_binding

DK_TEST_SEARCH = [{"id": "compact-w16", "levels": "compact-3-5-9", "widths": [16, 16], "dropout": 0.0},
                  {"id": "compact-w32", "levels": "compact-3-5-9", "widths": [32, 16], "dropout": 0.0}]
KCN_TEST_SEARCH = [{"id": "k8-w16-phi1", "k": 8, "width": 16, "phiFactor": 1.0}]
TEST_EPOCHS, TEST_PATIENCE = 150, 40


def _load(folder, name):
    return json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def lane(tmp_path_factory):
    """The authored field through the classical chain, then the learned lane and evaluate."""
    import run
    import stages.learned

    folder, identifier = authored_field.chain(tmp_path_factory.mktemp("field"), stages=(
        "preprocess", "dataset", "features", "train", "infer"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(stages.learned, "DK_SEARCH", DK_TEST_SEARCH)
        patch.setattr(stages.learned, "KCN_SEARCH", KCN_TEST_SEARCH)
        patch.setattr(stages.learned, "EPOCHS", TEST_EPOCHS)
        patch.setattr(stages.learned, "PATIENCE", TEST_PATIENCE)
        for stage in (run.train, run.infer, run.evaluate):
            stage(identifier, folder.parent, "learned")
    names = ("project", "preprocessed", "dataset", "features", "models", "predictions", "learned-models",
             "learned-predictions", "metrics")
    return folder, identifier, {n: _load(folder, n) for n in names}


def _populations(record):
    return {(s["scheme"], p["population"]): p for s in record["schemes"] for p in s["populations"]}


# R-701 ----------------------------------------------------------------------------------------------------------


def test_the_lane_uses_the_classical_split_and_targets(lane):
    from stages.train import _split_rows

    _, _, data = lane
    classical_models = _populations(data["models"])
    classical = _populations(data["predictions"])
    learned_models = _populations(data["learned-models"])
    learned = _populations(data["learned-predictions"])
    assert set(learned) == set(classical) == set(learned_models)
    schemes = {s["id"]: s for s in data["dataset"]["schemes"]}
    for key, p in learned.items():
        assert p["targets"] == classical[key]["targets"]
        assert p["calibrationTargets"] == classical[key]["calibrationTargets"]
        m = learned_models[key]
        assert m["analyte"] == classical_models[key]["analyte"]
        assert m["rows"]["train"] == classical_models[key]["train"]
        population = next(x for x in data["preprocessed"]["populations"] if x["id"] == key[1])
        rows = _split_rows(data["project"], data["preprocessed"], schemes[key[0]], population)
        train_ids = sorted(r["id"] for r in rows["train"] if m["analyte"] in r["values"])
        assert m["binding"]["trainingRowsSha256"] == features_hash(train_ids)
        for method in ("deepkriging", "kcn"):
            assert [r["id"] for r in p["methods"][method]["rows"]] == p["targets"]


def features_hash(ids):
    from learned.contracts import canonical_hash

    return canonical_hash(sorted(ids))


# R-702 ----------------------------------------------------------------------------------------------------------


def test_transforms_see_training_rows_only(lane, tmp_path):
    import stages.learned

    _, identifier, data = lane
    scheme = next(s for s in data["dataset"]["schemes"] if s["id"] == "hole-group")
    training_holes = {h for h, split in scheme["assignment"].items() if split == "train"}
    changed = copy.deepcopy(data["preprocessed"])
    for r in changed["selections"]["rows"]:
        if r["geometry"][0] not in training_holes and isinstance(r["value"], (int, float)):
            r["value"] = r["value"] * 10 + 1
    for r in changed.get("composites", {}).get("rows", []):
        if r["holeId"] not in training_holes:
            r["values"] = {k: (v * 10 + 1 if isinstance(v, (int, float)) else v) for k, v in r["values"].items()}
    kw = {"epochs": 1, "patience": 1, "dk_search": DK_TEST_SEARCH[:1], "kcn_search": KCN_TEST_SEARCH}
    one_scheme = {**data["dataset"], "schemes": [scheme]}
    feats = {**data["features"], "schemes": [s for s in data["features"]["schemes"] if s["scheme"] == "hole-group"]}
    base = stages.learned.train_learned(identifier, data["project"], data["preprocessed"], one_scheme, feats,
                                        tmp_path / "a", **kw)
    other = stages.learned.train_learned(identifier, data["project"], changed, one_scheme, feats, tmp_path / "b", **kw)

    def transforms(record):
        out = {}
        for key, p in _populations(record).items():
            out[key] = (p["transform"], p["binding"]["trainingRowsSha256"],
                        {lv: b["sha256"] for lv, b in p["methods"]["deepkriging"]["bases"].items()},
                        p["methods"]["kcn"]["graphs"], p["methods"]["kcn"]["lengthScale"])
        return out

    assert transforms(base) == transforms(other)
    assert base["inputDatasetSha256"] == other["inputDatasetSha256"]


# R-703 ----------------------------------------------------------------------------------------------------------


def test_degenerate_axes_and_constant_targets(lane, tmp_path):
    import stages.learned

    xyz = np.array([[0.0, 0.0, 5.0], [10.0, 20.0, 5.0], [4.0, 3.0, 5.0]])
    t = features.coordinate_transform(xyz)
    assert t["degenerate"] == [False, False, True] and t["scale"][2] == 1.0
    assert np.all(features.normalize(xyz, t)[:, 2] == 0.0)
    assert features.normalize(np.array([[0.0, 0.0, 7.5]]), t)[0, 2] == 2.5  # outside the box, not clipped
    assert features.outside_box(np.array([[0.0, 0.0, 7.5]]), t)[0]
    assert features.target_transform(np.full(4, 3.0)) == {"mean": 3.0, "scale": 1.0, "constant": True}

    _, identifier, data = lane
    constant = copy.deepcopy(data["preprocessed"])
    for r in constant["selections"]["rows"]:
        if isinstance(r["value"], (int, float)):
            r["value"] = 7.0
    for r in constant.get("composites", {}).get("rows", []):
        r["values"] = {k: (7.0 if isinstance(v, (int, float)) else v) for k, v in r["values"].items()}
    record = stages.learned.train_learned(identifier, data["project"], constant, data["dataset"], data["features"],
                                          tmp_path, epochs=1, patience=1, dk_search=DK_TEST_SEARCH[:1],
                                          kcn_search=KCN_TEST_SEARCH)
    populations = list(_populations(record).values())
    assert populations and all(p["status"] == "constant" and p["reason"] for p in populations)
    predicted = stages.learned.infer_learned(record, data["project"], constant, data["dataset"], tmp_path)
    for p in _populations(predicted).values():
        for method in ("deepkriging", "kcn"):
            rows = p["methods"][method]["rows"]
            assert rows and all(r["mean"] == 7.0 and r["status"] == "estimated" and r["reason"] for r in rows)


# R-704 ----------------------------------------------------------------------------------------------------------


def test_the_basis_matches_its_oracle_inside_the_graph():
    assert features.wendland(np.array([0.0]))[0] == pytest.approx(1.0)
    assert features.wendland(np.array([1.0, 1.5, 3.0])).tolist() == [0.0, 0.0, 0.0]
    r = 0.4
    assert features.wendland(np.array([r]))[0] == pytest.approx((1 - r) ** 6 * (35 * r * r + 18 * r + 3) / 3)
    with pytest.raises(ValueError):
        features.wendland(np.array([-0.1]))

    rng = np.random.default_rng(3)
    # A cluster in one corner of the box, so knots far from every training row are dropped.
    xyz = np.vstack([rng.uniform(0, 1, (80, 3)) * [300, 200, 20], [[3000.0, 2000.0, 60.0]]]) + [500000, 7400000, 0]
    basis = features.fit_basis(xyz, features.KNOT_LEVELS["compact-3-5-9"])
    assert basis["candidateColumns"] == 27 + 125 + 729
    assert basis["removedZeroColumns"] > 0
    assert len(basis["knots"]) == basis["candidateColumns"] - basis["removedZeroColumns"]
    assert sorted(set(basis["radii"])) == sorted({2.5 / 2, 2.5 / 4, 2.5 / 8})
    oracle = features.basis_features(xyz, basis)
    assert np.all(np.any(oracle[:, 3:] > 0, axis=0))  # every retained column is active on a training row
    probe = np.vstack([xyz, xyz[:5] + [5000.0, -3000.0, 100.0]])  # outside the box as well
    model = networks.DeepKriging(basis, [8], 0.0, 0.0, 1.0)
    with torch.no_grad():
        inside = model.features(torch.as_tensor(features.local(probe, basis["coordinates"]), dtype=torch.float32))
    assert np.max(np.abs(inside.numpy() - features.basis_features(probe, basis))) < 1e-5
    exported = features.fit_basis(xyz, features.KNOT_LEVELS["paper-10-19"])
    assert exported["candidateColumns"] == 10**3 + 19**3


# R-705 ----------------------------------------------------------------------------------------------------------


def _conditioning(holes_rows):
    xyz, holes, order = [], [], []
    for hole, (x, y, depths) in holes_rows.items():
        for d in depths:
            xyz.append([x, y, -d])
            holes.append(hole)
            order.append(f"{hole}-{d:05.1f}")
    n = len(xyz)
    return {"xyz": np.array(xyz, dtype=float), "holes": np.array(holes), "order": np.array(order),
            "y": np.arange(n, dtype=float), "length": np.ones(n), "trajectory": np.zeros(n)}


def test_neighbours_exclude_the_query_hole_and_report_insufficient_support():
    cond = _conditioning({"A": (0, 0, range(10)), "B": (10, 0, range(10)), "C": (50, 0, range(10))})
    query = np.array([[0.0, 0.0, -4.0], [1000.0, 0.0, 0.0]])
    selected, supported, reasons = features.select_neighbours(query, np.array(["A", "Q"]), cond, 8, per_hole=4,
                                                              min_holes=2)
    first = selected[0][selected[0] >= 0]
    assert "A" not in set(cond["holes"][first])
    assert all((cond["holes"][first] == h).sum() <= 4 for h in ("B", "C"))
    assert supported.tolist() == [True, True] and reasons == [None, None]
    # With only one other hole within reach, the query is uninformed and says why.
    small = _conditioning({"A": (0, 0, range(5)), "B": (10, 0, range(5))})
    selected, supported, reasons = features.select_neighbours(np.array([[0.0, 0.0, -1.0]]), np.array(["A"]), small, 4,
                                                              per_hole=4, min_holes=2)
    assert not supported[0] and "1 distinct" in reasons[0]
    # Ties are broken by row id, so the selection does not depend on the input order.
    tied = _conditioning({"B": (10, 0, [0.0]), "C": (-10, 0, [0.0]), "D": (0, 10, [0.0])})
    flip = {k: v[::-1] for k, v in tied.items()}
    a = features.select_neighbours(np.zeros((1, 3)), np.array(["Q"]), tied, 2, per_hole=1, min_holes=2)[0]
    b = features.select_neighbours(np.zeros((1, 3)), np.array(["Q"]), flip, 2, per_hole=1, min_holes=2)[0]
    assert tied["order"][a[0]].tolist() == flip["order"][b[0]].tolist()
    with pytest.raises(ValueError):
        features.select_neighbours(query, np.array(["A", "Q"]), cond, 1, min_holes=2)


# R-706 ----------------------------------------------------------------------------------------------------------


def _graph_batch():
    positions = np.array([[[0, 0, 0], [10, 0, 0], [0, 20, 0], [0, 0, 0]]], dtype=float)
    values = np.array([[99.0, 30.0, 40.0, 0.0]])
    known = np.array([[0.0, 1.0, 1.0, 0.0]])
    lengths = np.array([[1.0, 1.0, 2.0, 0.0]])
    trajectory = np.zeros((1, 4))
    valid = np.array([[1.0, 1.0, 1.0, 0.0]])  # the last row is padding
    return [positions, values, known, lengths, trajectory, valid]


def test_the_kcn_graph_follows_the_paper_and_ignores_neighbour_order():
    batch = _graph_batch()
    torch.manual_seed(0)
    model = networks.KCN(8, 35.0, 5.0, 15.0, 1.0, 12.0)
    tensors = [torch.as_tensor(x, dtype=torch.float32) for x in batch]
    with torch.no_grad():
        feats, adjacency = model.graph(*tensors)
    # Eq. 9 over every pair including j = k (exp(0) = 1), then (A + I) normalized by D = diag(A1 + 1): eq. 3.
    p = batch[0][0, :3]
    a = np.exp(-np.sum((p[:, None] - p[None]) ** 2, axis=-1) / (2 * 12.0**2))
    assert np.allclose(np.diag(a), 1.0)
    degree = a.sum(axis=1) + 1
    expected = (a + np.eye(3)) / np.sqrt(degree[:, None] * degree[None, :])
    assert np.allclose(adjacency.numpy()[0, :3, :3], expected, atol=1e-6)
    assert np.all(adjacency.numpy()[0, 3] == 0) and np.all(adjacency.numpy()[0, :, 3] == 0)
    assert np.allclose(np.diag(adjacency.numpy()[0, :3, :3]) * degree, 2.0, atol=1e-5)  # self weight 2
    oracle = features.graph_oracle({k: v for k, v in zip(networks_inputs(), batch, strict=True)},
                                   35.0, 5.0, 15.0, 1.0, 12.0)
    assert np.allclose(adjacency.numpy(), oracle["adjacency"], atol=1e-6)
    assert np.allclose(feats.numpy(), oracle["features"], atol=1e-6)
    assert feats.numpy()[0, 0, 0] == 0 and feats.numpy()[0, 0, 2] == 1  # the query's value is hidden

    def run(b):
        with torch.no_grad():
            return model(*[torch.as_tensor(x, dtype=torch.float32) for x in b]).item()

    base = run(batch)
    swapped = [x.copy() for x in batch]
    for x in swapped:
        x[0, [1, 2]] = x[0, [2, 1]]
    assert run(swapped) == pytest.approx(base, abs=1e-5)
    hidden = [x.copy() for x in batch]
    hidden[1][0, 0] = -1000.0  # the query's own value never enters
    assert run(hidden) == pytest.approx(base, abs=1e-6)
    moved = [x.copy() for x in batch]
    moved[1][0, 1] = 60.0
    assert abs(run(moved) - base) > 1e-4


def networks_inputs():
    import stages.learned

    return stages.learned.KCN_INPUTS


# R-707 ----------------------------------------------------------------------------------------------------------


def test_selection_is_by_the_seed_mean_on_validation(lane):
    import stages.learned

    folder, _, data = lane
    for p in _populations(data["learned-models"]).values():
        for method in ("deepkriging", "kcn"):
            entry = p["methods"][method]
            for configuration in entry["configurations"]:
                assert [f["seed"] for f in configuration["fits"]] == list(SEEDS)
                for f in configuration["fits"]:
                    fit = json.loads((folder / f["folder"] / "fit.json").read_text(encoding="utf-8"))
                    assert fit["history"] and fit["bestEpoch"] == f["bestEpoch"]
                    assert min(h["validationObjective"] for h in fit["history"]) == f["bestValidationObjective"]
                    assert training.weights_sha256(folder / f["folder"] / "weights.pt") == f["weightsSha256"]
            means = {c["config"]["id"]: np.mean([f["bestValidationObjective"] for f in c["fits"]])
                     for c in entry["configurations"]}
            assert entry["selected"] == min(means, key=means.get)
    # The tie rule: equal objectives go to fewer parameters, then to the declaration order.
    fits = lambda obj, params: [{"bestValidationObjective": obj, "parameters": params}] * 3
    assert stages.learned._select([{"config": {"id": "a"}, "fits": fits(1.0, 50)},
                                   {"config": {"id": "b"}, "fits": fits(1.0, 20)}]) == "b"
    assert stages.learned._select([{"config": {"id": "a"}, "fits": fits(1.0, 20)},
                                   {"config": {"id": "b"}, "fits": fits(1.0, 20)}]) == "a"
    for p in _populations(data["learned-predictions"]).values():
        for method in ("deepkriging", "kcn"):
            for r in p["methods"][method]["rows"]:
                if r["status"] == "estimated":
                    assert r["variance"] is None and len(r["seeds"]) == 3
                    assert r["mean"] == pytest.approx(np.mean(r["seeds"]), abs=1e-9)
                    assert r["spread"] == pytest.approx(np.std(r["seeds"]), abs=1e-9)


# R-708 ----------------------------------------------------------------------------------------------------------


class _Interrupt(Exception):
    pass


def test_fits_resume_and_refuse_another_recipe(tmp_path):
    rng = np.random.default_rng(0)
    x = rng.normal(size=(200, 3))
    y = x @ [1.0, -2.0, 0.5] + rng.normal(0, 0.1, 200)
    holes = np.array([f"H{i % 5}" for i in range(60)])
    args = ((x[:140],), y[:140], (x[140:],), y[140:], holes)
    make = lambda: torch.nn.Sequential(torch.nn.Linear(3, 8), torch.nn.ReLU(), torch.nn.Linear(8, 1),
                                       torch.nn.Flatten(0))
    recipe = {"model": "probe"}
    straight = make()
    reference = training.fit(straight, *args, tmp_path / "straight", recipe, 1, "cpu", scale=1.0, epochs=45,
                             patience=45)
    again = make()
    reused = training.fit(again, *args, tmp_path / "straight", recipe, 1, "cpu", scale=1.0, epochs=45, patience=45)
    assert reused["reused"] and reused["weightsSha256"] == reference["weightsSha256"]
    with pytest.raises(ValueError, match="another recipe"):
        training.fit(make(), *args, tmp_path / "straight", {"model": "other"}, 1, "cpu", scale=1.0, epochs=45,
                     patience=45)
    # An interrupted fit resumes from its last checkpoint and ends where the uninterrupted one did.
    interrupted = make()
    calls = {"n": 0}
    original = interrupted.forward

    def failing(*inputs):
        if interrupted.training:
            calls["n"] += 1
            if calls["n"] > 2 * 25:  # two batches per epoch: stop inside epoch 26, after the checkpoint at 20
                raise _Interrupt
        return original(*inputs)

    interrupted.forward = failing
    with pytest.raises(_Interrupt):
        training.fit(interrupted, *args, tmp_path / "resumed", recipe, 1, "cpu", scale=1.0, epochs=45, patience=45)
    assert (tmp_path / "resumed" / "resume.pt").is_file()
    resumed = training.fit(make(), *args, tmp_path / "resumed", recipe, 1, "cpu", scale=1.0, epochs=45, patience=45)
    assert resumed["history"] == reference["history"]
    load = lambda name: torch.load(tmp_path / name / "weights.pt", weights_only=True)
    assert all(torch.equal(a, b) for a, b in zip(load("straight").values(), load("resumed").values(), strict=True))
    weights = tmp_path / "straight" / "weights.pt"
    weights.write_bytes(weights.read_bytes()[:-8] + b"tampered")
    with pytest.raises(ValueError, match="do not match"):
        training.fit(make(), *args, tmp_path / "straight", recipe, 1, "cpu", scale=1.0, epochs=45, patience=45)


# R-709 ----------------------------------------------------------------------------------------------------------


def test_controls_are_fitted_and_lose_on_the_authored_field(lane):
    _, _, data = lane
    checked = 0
    for scheme in data["metrics"]["schemes"]:
        for p in scheme["populations"]:
            for method in ("deepkriging", "kcn"):
                entry = p["methods"][method]
                expected = {"shuffled-labels"} | ({"coordinate-only"} if method == "deepkriging" else set())
                assert set(entry["controls"]) == expected
                shuffled = entry["controls"]["shuffled-labels"]["scores"]
                assert shuffled["rmse"] > entry["own"]["rmse"], (scheme["scheme"], p["population"], method)
                checked += 1
    assert checked >= 4


# R-710 ----------------------------------------------------------------------------------------------------------


def test_the_residual_band_comes_from_calibration_rows(lane):
    from stages.evaluate import learned_scores
    from stages.train import _split_rows

    _, _, data = lane
    learned = _populations(data["learned-predictions"])
    schemes = {s["id"]: s for s in data["dataset"]["schemes"]}
    for (scheme_id, pop_id), p in learned.items():
        population = next(x for x in data["preprocessed"]["populations"] if x["id"] == pop_id)
        rows = _split_rows(data["project"], data["preprocessed"], schemes[scheme_id], population)
        info = {r["id"]: r for split in ("test", "calibration") for r in rows[split]}
        truth = {i: r["values"][p["analyte"]] for i, r in info.items() if p["analyte"] in r["values"]}
        for method in ("deepkriging", "kcn"):
            record = p["methods"][method]
            residuals = [abs(r["mean"] - truth[r["id"]]) for r in record["calibrationRows"] if r["status"] == "estimated"]
            radius = float(np.quantile(residuals, 0.95, method="higher"))
            metric = next(x for s in data["metrics"]["schemes"] if s["scheme"] == scheme_id
                          for x in s["populations"] if x["population"] == pop_id)["methods"][method]
            assert metric["residualBand"]["radius"] == pytest.approx(radius)
            assert metric["residualBand"]["calibrationRows"] == len(residuals)
            moved = {k: (v + 1000.0 if k in p["targets"] else v) for k, v in truth.items()}
            again = learned_scores(record, p["targets"], [], moved, info, (0.0, 1.0),
                                   {t: {"mean": 0.0} for t in p["targets"]})
            assert again["residualBand"]["radius"] == pytest.approx(radius)  # test truths never set the radius
            assert again["residualBand"]["testCoverage"] == 0.0


# R-711 ----------------------------------------------------------------------------------------------------------


def test_the_export_is_audited_and_bound(lane, tmp_path):
    import onnx

    folder, _, data = lane
    models = _populations(data["learned-models"])
    count = 0
    for key, p in _populations(data["learned-predictions"]).items():
        for method in ("deepkriging", "kcn"):
            exports = p["methods"][method]["exports"]
            assert sorted(e["seed"] for e in exports) == sorted(SEEDS)
            for e in exports:
                path = folder / e["folder"] / "model.onnx"
                audit = exporting.audit_model(path)
                assert audit["sha256"] == e["model"]["sha256"] and audit["bytes"] <= exporting.MAX_MODEL_BYTES
                assert audit["nodes"] <= exporting.MAX_NODES and exporting.scan_paths(path) == []
                graph = onnx.load(path)
                assert not graph.metadata_props and all(not n.metadata_props for n in graph.graph.node)
                manifest = json.loads((folder / e["folder"] / "manifest.json").read_text(encoding="utf-8"))
                assert manifest["binding"] == models[key]["binding"] and manifest["unit"] == models[key]["unit"]
                assert manifest["seed"] == e["seed"] and manifest["method"] == method
                count += 1
    assert count >= 12
    # A model that carries a source path is refused.
    leaky = onnx.load(path)
    leaky.graph.node[0].metadata_props.add(key="stack", value='File "C:\\work\\model.py", line 3')
    onnx.save(leaky, tmp_path / "leaky.onnx")
    with pytest.raises(ValueError, match="paths"):
        exporting.audit_model(tmp_path / "leaky.onnx")


# R-712 ----------------------------------------------------------------------------------------------------------


def test_onnx_agrees_with_torch_on_held_out_inputs(lane):
    import onnxruntime as ort

    folder, _, data = lane
    for p in _populations(data["learned-predictions"]).values():
        for method in ("deepkriging", "kcn"):
            record = p["methods"][method]
            estimated = sum(r["status"] == "estimated" for r in record["rows"] + record["calibrationRows"])
            for e in record["exports"]:
                parity = json.loads((folder / e["folder"] / "parity.json").read_text(encoding="utf-8"))
                assert parity["rows"] == estimated and parity["passed"]
                assert parity["onnxCpuMaxAbsolute"] <= parity["tolerance"]
                session = ort.InferenceSession(str(folder / e["folder"] / "model.onnx"),
                                               providers=["CPUExecutionProvider"])
                feeds = {n: np.asarray(v["data"], dtype=np.float32).reshape(v["shape"])
                         for n, v in parity["fixture"]["inputs"].items()}
                got = session.run(None, feeds)[0]
                assert np.max(np.abs(got - np.asarray(parity["fixture"]["outputs"]["value"]))) <= parity["tolerance"]
                seeds = np.array([r["seeds"][SEEDS.index(e["seed"])] for r in record["rows"] + record["calibrationRows"]
                                  if r["status"] == "estimated"])
                assert np.allclose(seeds[:len(got)], got, atol=parity["tolerance"])


# R-713 ----------------------------------------------------------------------------------------------------------


@pytest.mark.skipif(not torch.cuda.is_available(), reason="no CUDA device")
def test_cuda_agrees_with_cpu(lane):
    _, _, data = lane
    for p in _populations(data["learned-predictions"]).values():
        for method in ("deepkriging", "kcn"):
            for e in p["methods"][method]["exports"]:
                parity = e["parity"]
                assert parity["torchCudaMaxAbsolute"] is not None
                assert parity["torchCudaMaxAbsolute"] <= parity["tolerance"]


# R-714 ----------------------------------------------------------------------------------------------------------


def test_a_foreign_or_altered_model_is_refused(lane, tmp_path):
    folder, _, data = lane
    p = next(iter(_populations(data["learned-predictions"]).values()))
    export = p["methods"]["kcn"]["exports"][0]
    archive = folder / export["folder"] / "portable-model.zip"
    manifest = exporting.validate_portable(archive)
    project = {"projectId": manifest["binding"]["projectId"], "frameId": manifest["binding"]["frameId"],
               "task": manifest["binding"]["task"], "propertyUnits": dict(manifest["binding"]["propertyUnits"])}
    check_binding(manifest, project)
    for change in ({"projectId": "another-mine"}, {"frameId": "another-frame"}, {"task": "another task"},
                   {"propertyUnits": {k: "ppm" if u != "ppm" else "wt%" for k, u in project["propertyUnits"].items()}}):
        with pytest.raises(ValueError, match="out-of-domain"):
            check_binding(manifest, {**project, **change})
    with zipfile.ZipFile(archive) as source:
        files = {n: source.read(n) for n in source.namelist()}
    altered = tmp_path / "altered.zip"
    with zipfile.ZipFile(altered, "w") as target:
        for name, raw in files.items():
            target.writestr(name, raw[:-1] + bytes([raw[-1] ^ 1]) if name == "model.onnx" else raw)
    with pytest.raises(ValueError, match="hash"):
        exporting.validate_portable(altered)
    extra = tmp_path / "extra.zip"
    with zipfile.ZipFile(extra, "w") as target:
        for name, raw in files.items():
            target.writestr(name, raw)
        target.writestr("weights.pt", b"pickle")
    with pytest.raises(ValueError, match="exactly"):
        exporting.validate_portable(extra)


# R-715 ----------------------------------------------------------------------------------------------------------


def test_evaluate_scores_the_learned_methods_beside_ordinary_kriging(lane):
    from stages.estimators import METHODS
    from stages.evaluate import evaluate_family

    folder, identifier, data = lane
    sys.path.insert(0, str(ROOT / "scripts"))
    import check_artifacts

    assert check_artifacts.check_learned(folder) == []
    assert check_artifacts.check_metrics(data["metrics"], data["predictions"]) == []
    classical_only = evaluate_family(identifier, data["project"], data["preprocessed"], data["dataset"],
                                     data["predictions"], data["models"])
    for with_learned, without in zip(data["metrics"]["schemes"], classical_only["schemes"], strict=True):
        for a, b in zip(with_learned["populations"], without["populations"], strict=True):
            assert a["commonTargets"] == b["commonTargets"]
            for m in METHODS:
                assert a["methods"][m] == b["methods"][m]
            for m in ("deepkriging", "kcn"):
                entry = a["methods"][m]
                for field in ("own", "common", "versusOrdinaryKriging", "seeds", "spread", "residualBand"):
                    assert field in entry, (m, field)
                assert entry["common"]["n"] + entry["common"]["classicalCommonMissed"] == a["commonTargets"]
                assert entry["versusOrdinaryKriging"]["bootstrap"]["unit"] == "hole"
                assert math.isfinite(entry["own"]["rmse"])
    stale = copy.deepcopy(data["learned-predictions"])
    stale["schemes"][0]["populations"][0]["targets"] = stale["schemes"][0]["populations"][0]["targets"][1:]
    with pytest.raises(ValueError, match="learned targets differ"):
        evaluate_family(identifier, data["project"], data["preprocessed"], data["dataset"], data["predictions"],
                        data["models"], learned=stale)


# R-716 ----------------------------------------------------------------------------------------------------------


def test_no_held_out_value_is_serialized(lane):
    from stages.train import _split_rows

    folder, _, data = lane
    schemes = {s["id"]: s for s in data["dataset"]["schemes"]}
    for (scheme_id, pop_id), p in _populations(data["learned-predictions"]).items():
        population = next(x for x in data["preprocessed"]["populations"] if x["id"] == pop_id)
        rows = _split_rows(data["project"], data["preprocessed"], schemes[scheme_id], population)
        held_out = {r["values"][p["analyte"]] for split in ("validation", "calibration", "test") for r in rows[split]
                    if p["analyte"] in r["values"]}
        training_values = {r["values"][p["analyte"]] for r in rows["train"] if p["analyte"] in r["values"]}
        leaked = {v for v in held_out - training_values if v != int(v)}
        assert leaked
        for method in ("deepkriging", "kcn"):
            for e in p["methods"][method]["exports"]:
                manifest = json.loads((folder / e["folder"] / "manifest.json").read_text(encoding="utf-8"))
                parity = json.loads((folder / e["folder"] / "parity.json").read_text(encoding="utf-8"))
                assert not _numbers(manifest) & leaked
                if method == "kcn":
                    values = np.asarray(parity["fixture"]["inputs"]["values"]["data"])
                    known = np.asarray(parity["fixture"]["inputs"]["known"]["data"])
                    # The inputs are float32: compare exactly in float32 (rounding a composite mean after the cast
                    # can move its third decimal).
                    assert set(values[known > 0].tolist()) <= {float(np.float32(v)) for v in training_values}
                    assert np.all(values[known == 0] == 0)
        assert not _numbers(data["learned-models"]) & leaked


def _numbers(value) -> set:
    """Every number in a parsed JSON value."""
    if isinstance(value, dict):
        return set().union(*(_numbers(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_numbers(v) for v in value)) if value else set()
    return {float(value)} if isinstance(value, (int, float)) and not isinstance(value, bool) else set()
