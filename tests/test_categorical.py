"""The categorical lane: the reviewed mapping, depth conditioning, training images, SNESIM (MPSlib) and Direct Sampling
in the product, their scores and connectivity, and the lane end to end on an authored layered field."""

import copy
import importlib.util
import json
import math
from pathlib import Path

import authored_field
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
def _mpslib_built() -> bool:
    from stages import mps

    return mps.available()


needs_mpslib = pytest.mark.skipif(not _mpslib_built(), reason="MPSlib is not built (scripts/build_mpslib.sh, SONDARA_MPSLIB)")


def _contract():
    spec = importlib.util.spec_from_file_location("check_artifacts", ROOT / "scripts" / "check_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(hole, a, b, litho=None, rock=None, description=None, kind="interval"):
    return {"id": f"{hole}/{a}-{b}", "holeId": hole, "kind": kind, "fromMd": a if kind == "interval" else None,
            "toMd": b if kind == "interval" else None, "atMd": a if kind != "interval" else None,
            "codes": {"Litho_unit": litho or "-9999", "Rock_type": rock or "-9999"}, "description": description}


def test_the_mapping_applies_declared_rules_only():
    from stages.categories import load_mapping, map_lithology

    mapping = load_mapping("alberta")
    geology = [
        _row("A", 0, 30, "overburden"),
        _row("A", 30, 40, description="Unit: Devonian; dolomitic sandstone"),
        _row("A", 40, 44, "dolomitic sandstone"),  # above Athabasca: Devonian by position
        _row("A", 44, 60, description="Unit: Athabasca Group Sandstone"),
        _row("A", 60, 62, "conglomerate"),  # directly above the unconformity: basal Athabasca
        _row("A", 62, 62, "unconformity contact", kind="event"),
        _row("A", 62, 90, "pelitic gneiss", "Gneiss"),
        _row("A", 90, 95, "quartzite", "Quartzite"),  # below the unconformity: basement
        _row("A", 95, 99, "granitoid and pelitic gneiss"),
        _row("B", 0, 20, "overburden"),
        _row("B", 20, 30, "quartzite"),  # no unconformity above it: the position rule fails
        _row("B", 30, 40, "conglomerate"),  # nothing below it: fails
        _row("B", 40, 50, description="-9999"),
        _row("B", 50, 60, "basement"),
        _row("B", 60, 70, "pegmatoid"),
        _row("B", 70, 72, "an unlisted code"),
    ]
    project = {"geology": copy.deepcopy(geology)}
    rows = {r["geologyId"]: r for r in map_lithology(project, mapping)["rows"]}
    expected = {"A/0-30": (0, "code-overburden"), "A/30-40": (1, "description-devonian"),
                "A/40-44": (1, "position-devonian-sandstone"), "A/44-60": (2, "description-athabasca"),
                "A/60-62": (2, "position-basal-conglomerate"), "A/62-90": (3, "code-gneiss"),
                "A/90-95": (3, "position-basement-quartzite"), "B/60-70": (4, "code-granitoid"),
                "B/0-20": (0, "code-overburden")}
    for gid, (category, rule) in expected.items():
        assert (rows[gid]["category"], rows[gid]["rule"]) == (category, rule), gid
    assert rows["A/95-99"]["reason"] == "the description names both basement categories"
    assert rows["B/20-30"]["reason"] == "position rule position-basement-quartzite not satisfied"
    assert rows["B/30-40"]["reason"] == "position rule position-basal-conglomerate not satisfied"
    assert rows["B/40-50"]["reason"] == "no code and no named unit"
    assert rows["B/50-60"]["reason"] == "basement, but neither gneiss nor granitoid"
    assert rows["B/70-72"]["reason"] == "no rule assigns this code"
    assert rows["A/62-62"]["reason"] == "an event, not a volume"
    assert project["geology"] == geology  # the source codes are never changed


def test_the_alberta_mapping_file_is_consistent():
    from stages.categories import load_mapping

    mapping = load_mapping("alberta")
    assert [c["code"] for c in mapping["categories"]] == list(range(5))
    seen = []
    for rule in mapping["rules"]:
        assert rule["category"] in range(5) and rule["evidence"]
        if "values" in rule and "position" not in rule:
            seen += [(rule["field"], v) for v in rule["values"]]
    for u in mapping["unmapped"]:
        seen += [(u["field"], v) for v in u["values"]]
    assert len(seen) == len(set(seen))  # a code sits in one rule or one unmapped list
    grid = mapping["grid"]
    assert len(grid["shape"]) == 3 and 0 < grid["majority"] < 1 and grid["traceStep"] > 0


def test_conditioning_conserves_length_and_records_conflicts():
    from geocond.geometry import Survey
    from stages.categories import Grid, cell_lengths, collar_surface, conditioning

    collars = [{"x": 25.0, "y": 25.0, "z": 100.0}, {"x": 175.0, "y": 25.0, "z": 110.0}]
    surface = collar_surface(collars)
    assert surface(np.array([25.0, 175.0]), np.array([25.0, 25.0])).tolist() == [100.0, 110.0]
    grid = Grid((0.0, 0.0, 0.0), (50.0, 50.0, 10.0), (4, 1, 3))
    surveys = {"V": Survey([25.0, 25.0, 100.0], [0.0], [0.0], [-90.0], end_extension="tangent"),
               "W": Survey([175.0, 25.0, 110.0], [0.0], [0.0], [-90.0], end_extension="tangent")}
    rows = [{"holeId": "V", "fromMd": 0.0, "toMd": 7.0, "category": 0}, {"holeId": "V", "fromMd": 7.0, "toMd": 16.0,
             "category": 1}, {"holeId": "V", "fromMd": 16.0, "toMd": 20.0, "category": 2},
            {"holeId": "W", "fromMd": 0.0, "toMd": 5.0, "category": 0}, {"holeId": "W", "fromMd": 5.0, "toMd": 10.0,
             "category": 3}, {"holeId": "W", "fromMd": 10.0, "toMd": 30.0, "category": None}]
    lengths, holes, outside = cell_lengths(rows, surveys, surface, grid, {"V", "W"}, 0.1)
    assert outside == 0.0
    total = {h: sum(v for c, per in lengths.items() for v in per.values() if h in holes[c]) for h in ("V", "W")}
    assert total == pytest.approx({"V": 20.0, "W": 10.0}, abs=1e-9)  # every mapped metre in one cell
    assert dict(lengths[(0, 0, 0)]) == pytest.approx({0: 7.0, 1: 3.0})
    result = conditioning(lengths, holes, 0.5)
    hard = {tuple(h["cell"]): h["category"] for h in result["hard"]}
    assert hard[(0, 0, 0)] == 0 and hard[(0, 0, 1)] == 1  # 7 of 10 m and 6 of 10 m
    conflict = next(c for c in result["conflicts"] if c["cell"] == [3, 0, 0])
    assert conflict["candidates"] == pytest.approx({"0": 5.0, "3": 5.0})  # half and half: neither wins
    assert (3, 0, 1) not in hard and (3, 0, 0) not in hard  # the unmapped interval informs nothing


def test_training_images_are_seeded_labelled_and_different_where_declared():
    from stages.training_images import PRIORS, author

    cover = {"units": {"0": {"mean": 30.0, "sd": 5.0}, "1": {"mean": 20.0, "sd": 5.0},
                       "2": {"mean": 30.0, "sd": 10.0}}}
    a, ra = author("nw-high-strain", (250.0, 250.0, 10.0), 24, cover, 0.35, 7)
    again, _ = author("nw-high-strain", (250.0, 250.0, 10.0), 24, cover, 0.35, 7)
    b, rb = author("gneiss-domes", (250.0, 250.0, 10.0), 24, cover, 0.35, 7)
    assert np.array_equal(a, again) and ra["sha256"] != rb["sha256"]
    assert ra["interpretation"] and ra["label"] == PRIORS["nw-high-strain"]["label"] and ra["categories"] == [0, 1, 2, 3, 4]
    cover_a, cover_b = np.isin(a, (0, 1, 2)), np.isin(b, (0, 1, 2))
    assert np.array_equal(cover_a, cover_b) and np.array_equal(a[cover_a], b[cover_b])  # the same cover
    basement = ~cover_a
    assert np.mean(a[basement] == 4) == pytest.approx(0.35, abs=0.01)
    assert np.mean(b[basement] == 4) == pytest.approx(0.35, abs=0.01)
    assert np.all(np.diff(np.where(cover_a, 0, 1), axis=2) >= 0)  # cover above basement in every column
    # The high-strain prior's granitoid runs along azimuth 315 (x - 1, y + 1), not across it (x + 1, y + 1).
    deep = np.flatnonzero(~cover_a.any(axis=(0, 1)))  # layers below the thickest cover: basement only
    assert len(deep) >= 3
    g = a[:, :, deep] == 4
    along = np.mean(g[1:, :-1] == g[:-1, 1:])
    across = np.mean(g[:-1, :-1] == g[1:, 1:])
    assert along > across + 0.1
    d = b[:, :, deep] == 4
    assert abs(np.mean(d[1:, :-1] == d[:-1, 1:]) - np.mean(d[:-1, :-1] == d[1:, 1:])) < 0.05


def test_vertical_proportions_and_soft_probabilities():
    from stages.categorical import VPC_PSEUDOCOUNT, soft_grid, vertical_proportions

    hard = [{"cell": [0, 0, 0], "category": 0}] * 6 + [{"cell": [0, 0, 1], "category": 1}] * 5 + \
        [{"cell": [0, 0, 2], "category": 2}] * 2
    vpc, counts, glob = vertical_proportions(hard, 4, 3)
    assert counts.sum() == len(hard)
    assert glob == pytest.approx([6 / 13, 5 / 13, 2 / 13])
    assert vpc[0] == pytest.approx((np.array([6, 0, 0]) + VPC_PSEUDOCOUNT * glob) / (6 + VPC_PSEUDOCOUNT))
    assert vpc[2] == pytest.approx(vpc[1]) and vpc[3] == pytest.approx(vpc[1])  # too few cells: carried from layer 1
    soft = soft_grid(vpc, [0.5, 0.25, 0.25], (2, 1, 4))
    ratio = vpc[0] / np.array([0.5, 0.25, 0.25])
    assert soft[1, 0, 0] == pytest.approx(ratio / ratio.sum()) and soft.shape == (2, 1, 4, 3)


def channel_ti(nx=80, ny=80):
    x, y = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
    return (np.sin(x / 5.0 + 1.3 * np.sin(y / 8.0)) > 0.5).astype(np.uint8)[..., None]


@needs_mpslib
def test_snesim_runner_is_supervised_seeded_and_exact(tmp_path):
    from stages import mps

    ti = channel_ti()
    hard = (np.array([[0, 0, 0], [10, 12, 0], [29, 5, 0]]), np.array([1, 0, 1]))
    run = lambda seed, name: mps.simulate(ti, (30, 20, 1), realizations=3, seed=seed, hard=hard,
                                          job_dir=tmp_path / name, options={"template": (5, 5, 1)})
    a, ra = run(11, "a")
    b, _ = run(11, "b")
    c, _ = run(12, "c")
    assert np.array_equal(a, b) and not np.array_equal(a, c) and a.shape == (3, 30, 20, 1)
    assert np.all(a[:, hard[0][:, 0], hard[0][:, 1], 0] == hard[1][None, :]) and ra["hardCells"] == 3
    lines = ra["parameterFile"].splitlines()
    assert len(lines) == 30 and lines[1].endswith("# 11") and lines[5].endswith("# 5 5")  # the pinned schema
    assert ra["commit"] == mps.COMMIT and ra["executableSha256"] == mps.receipt()["executables"][mps.ENGINE]["sha256"]
    with pytest.raises(mps.MpslibError, match="2\\^24"):
        mps.simulate(ti, (30, 20, 1), realizations=1, seed=2 ** 24, job_dir=tmp_path / "d")


def patterns(field):
    """Exhaustive 2 x 2 pattern counts of a binary 2D field (16 patterns)."""
    f = field[..., 0].astype(int)
    code = f[:-1, :-1] + 2 * f[1:, :-1] + 4 * f[:-1, 1:] + 8 * f[1:, 1:]
    return np.bincount(code.ravel(), minlength=16)


@needs_mpslib
def test_snesim_reproduces_small_pattern_frequencies(tmp_path):
    """S10: unconditional SNESIM realizations of an authored binary channel image reproduce the image's 2 x 2 pattern
    frequencies, counted exhaustively."""
    from stages import mps

    ti = channel_ti()
    fields, _ = mps.simulate(ti, (50, 50, 1), realizations=20, seed=5, job_dir=tmp_path / "s10",
                             options={"template": (7, 7, 1), "multiple_grids": 2})
    assert set(np.unique(fields)) == {0, 1}
    p = patterns(ti) / patterns(ti).sum()
    q = sum(patterns(f) for f in fields)
    q = q / q.sum()
    assert 0.5 * np.abs(p - q).sum() < 0.05
    assert np.all(q[p == 0] < 0.01)  # patterns the image never holds stay rare


def test_zoned_direct_sampling_in_the_product():
    from stages.categorical import ds_realization

    rng = np.random.default_rng(3)
    ti = np.repeat(np.array([0, 0, 1, 1, 2, 2, 3, 3], dtype=np.uint8)[None, None, :], 30, 0).repeat(30, 1)
    ti = np.where(rng.random(ti.shape) < 0.05, 3 - ti, ti).astype(np.uint8)
    cells = np.array([[1, 1, 0], [5, 5, 7]])
    cats = np.array([0, 3])
    a, stats = ds_realization(ti, (8, 8, 8), cells, cats, seed=4)
    b, _ = ds_realization(ti, (8, 8, 8), cells, cats, seed=4)
    assert np.array_equal(a, b) and a[1, 1, 0] == 0 and a[5, 5, 7] == 3
    layer_mode = [np.bincount(a[:, :, k].ravel(), minlength=4).argmax() for k in range(8)]
    assert layer_mode == [0, 0, 1, 1, 2, 2, 3, 3]
    assert stats["simulated"] == 8 * 8 * 8 - 2


@pytest.mark.cuda
def test_direct_sampling_cpu_and_cuda_agree_in_the_product():
    """S11: the product's zoned Direct Sampling selects the same candidate for every node on both backends."""
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("no CUDA device")
    from stages.categorical import ds_realization

    ti = channel_ti(40, 40).repeat(4, axis=2)
    cells, cats = np.array([[0, 0, 0], [7, 3, 2]]), np.array([1, 0])
    a, sa = ds_realization(ti, (12, 10, 4), cells, cats, seed=2, backend="numpy")
    b, sb = ds_realization(ti, (12, 10, 4), cells, cats, seed=2, backend="torch")
    assert np.array_equal(a, b) and sa["candidateSha256"] == sb["candidateSha256"]


def test_categorical_scores_equal_a_direct_computation():
    from stages.categorical import LOG_FLOOR, category_probabilities, scores

    fields = np.zeros((4, 2, 1, 1), np.uint8)
    fields[:, 1, 0, 0] = [0, 1, 1, 2]
    cells = np.array([[0, 0, 0], [1, 0, 0]])
    prob = category_probabilities(fields, cells, [0, 1, 2])
    assert prob.tolist() == [[1.0, 0.0, 0.0], [0.25, 0.5, 0.25]]
    got = scores(prob, np.array([0, 2]), [0, 1, 2])
    brier = ((0.0) + (0.25 ** 2 + 0.5 ** 2 + 0.75 ** 2)) / 2
    assert got["brier"] == pytest.approx(brier) and got["accuracy"] == 0.5
    assert got["logScore"] == pytest.approx(-(math.log(1.0) + math.log(0.25)) / 2)
    floored = scores(np.array([[0.0, 1.0, 0.0]]), np.array([0]), [0, 1, 2])
    assert floored["logScore"] == pytest.approx(-math.log(LOG_FLOOR)) and floored["brier"] == pytest.approx(2.0)


def test_connectivity_and_hole_connections():
    from stages.categorical import connectivity, hole_connections

    field = np.zeros((6, 1, 1), np.uint8)
    field[[0, 1, 2, 4], 0, 0] = 1  # clusters of 3 and 1 cells
    got = connectivity(field, 1)
    assert got["clusters"] == 2 and got["H"] == pytest.approx(3 / 4) and got["C"] == pytest.approx((9 + 1) / 16)
    assert connectivity(field * 0, 1)["H"] is None
    fields = np.stack([field, field])
    joined = hole_connections(fields, {"a": np.array([[0, 0, 0]]), "b": np.array([[2, 0, 0]]),
                                       "c": np.array([[4, 0, 0]])}, 1)
    assert joined == {"a|b": 1.0, "a|c": 0.0, "b|c": 0.0}


@pytest.fixture(scope="module")
def lane(tmp_path_factory):
    """The categorical lane end to end on the authored layered field, with an authored mapping."""
    import run
    import stages.categorical
    import stages.categories

    base = tmp_path_factory.mktemp("lane")
    folder, identifier = authored_field.chain(base, stages=("preprocess", "dataset"), lithology=True)
    interpretations = base / "interpretations"
    interpretations.mkdir()
    (interpretations / f"{identifier}-lithology-v1.json").write_text(
        json.dumps(authored_field.lithology_mapping(identifier)), encoding="utf-8")
    import stages.training_images

    # The Alberta priors' lengths (kilometres) scaled to the authored field's 50 m x 1 m cells.
    priors = {"nw-high-strain": {**stages.training_images.PRIORS["nw-high-strain"], "along_m": 600.0, "across_m": 100.0,
                                 "vertical_m": 20.0},
              "gneiss-domes": {**stages.training_images.PRIORS["gneiss-domes"], "along_m": 200.0, "across_m": 200.0,
                               "vertical_m": 5.0}}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(stages.categories, "INTERPRETATIONS", interpretations)
        patch.setattr(stages.categorical, "REALIZATIONS", 6)
        patch.setattr(stages.training_images, "PRIORS", priors)
        patch.setattr(stages.training_images, "CORRELATION_M", 200.0)
        for stage in (run.train, run.infer, run.evaluate):
            stage(identifier, folder.parent, "categorical")
    load = lambda name: json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
    return folder, {n: load(n) for n in ("categorical-models", "categorical-predictions", "categorical-metrics")}


@needs_mpslib
def test_the_lane_runs_end_to_end_on_an_authored_field(lane):
    folder, data = lane
    models, predictions, metrics = data["categorical-models"], data["categorical-predictions"], data["categorical-metrics"]
    assert models["eligible"] and models["mapping"]["counts"]["unmapped"] == 1
    assert {(r["scheme"], r["prior"], r["engine"]) for r in predictions["runs"]} == {
        (s, p, e) for s in ("hole-group", "spatial-margin") for p in ("nw-high-strain", "gneiss-domes")
        for e in ("snesim", "direct-sampling")}
    assert all(r["hardHonoured"] and r["realizations"] == 6 for r in predictions["runs"])
    for s in metrics["schemes"]:
        assert s["testCells"] > 0 and len(s["runs"]) == 4
        for run in s["runs"]:
            assert run["all"]["n"] == s["testCells"] and 0 <= run["all"]["brier"] <= 2
            assert set(run["connectivity"]) == {"0", "1", "2", "3", "4"}
    assert _contract().check_family(folder) == []


@needs_mpslib
def test_the_contract_check_rejects_stale_categorical_outputs(lane):
    folder, data = lane
    contract = _contract()
    models, predictions = data["categorical-models"], data["categorical-predictions"]
    assert contract.check_categorical(folder) == []
    stale = copy.deepcopy(predictions)
    stale["inputCategoricalModelsSha256"] = "0" * 64
    assert any("other models" in e for e in contract.check_categorical_predictions(stale, models, folder))
    tampered = copy.deepcopy(predictions)
    tampered["runs"][0]["sha256"] = "0" * 64
    assert any("does not match" in e for e in contract.check_categorical_predictions(tampered, models, folder))
    unhonoured = copy.deepcopy(predictions)
    unhonoured["runs"][1]["hardHonoured"] = False
    assert any("conditioning" in e for e in contract.check_categorical_predictions(unhonoured, models, folder))
    gap = copy.deepcopy(models)
    gap["mapping"]["rows"][0].update(category=None, rule=None, reason="no rule assigns this code")
    assert any("no rule" in e for e in contract.check_categorical_models(gap, folder))


def test_cover_statistics_clip_overlaps_and_exclude_gaps():
    """A cover interval that overlaps the basement top (MR-14's Athabasca ends 5 cm below it) counts up to that top;
    a hole with an unmapped gap in its cover is excluded, with the reason."""
    from geocond.geometry import Survey
    from stages.categories import collar_surface
    from stages.training_images import cover_statistics

    collars = [{"x": 0.0, "y": 0.0, "z": 300.0}, {"x": 500.0, "y": 0.0, "z": 300.0}]
    surveys = {h: Survey([c["x"], c["y"], c["z"]], [0.0], [0.0], [-90.0], end_extension="tangent")
               for h, c in zip("AB", collars, strict=True)}
    row = lambda h, a, b, c, reason=None: {"holeId": h, "fromMd": a, "toMd": b, "category": c, "reason": reason}
    rows = [row("A", 0.0, 30.0, 0), row("A", 30.0, 40.0, 1), row("A", 40.0, 60.05, 2), row("A", 60.0, 80.0, 3),
            row("B", 0.0, 30.0, 0), row("B", 30.0, 45.0, None, "no code and no named unit"), row("B", 45.0, 60.0, 4)]
    stats = cover_statistics(rows, surveys, collar_surface(collars), {"A", "B"})
    assert stats["holes"] == ["A"] and "unmapped cover" in stats["excluded"]["B"]
    assert stats["units"]["2"]["mean"] == pytest.approx(20.0) and stats["units"]["2"]["zeros"] == 0
    assert stats["units"]["0"]["mean"] == pytest.approx(30.0) and stats["units"]["1"]["mean"] == pytest.approx(10.0)
