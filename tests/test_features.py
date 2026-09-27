"""The features stage: training rows only, GeoCond variograms, declustering and declared orientations."""

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures"


def _chain(tmp_path, manifest="F40/import.json"):
    import run
    from source_adapters.manifest_import import run_import

    identifier = run_import(FIXTURES / manifest, tmp_path)["project"]
    run.preprocess(identifier, tmp_path)
    run.dataset(identifier, tmp_path)
    load = lambda name: json.loads((tmp_path / identifier / name).read_text(encoding="utf-8"))
    return identifier, load("project.json"), load("preprocessed.json"), load("dataset.json")


def _strip_run_facts(features):
    return {k: v for k, v in features.items() if k != "inputDatasetSha256"}


def test_features_see_training_rows_only(tmp_path):
    from stages.dataset import derived_tables, members
    from stages.features import family_features

    identifier, project, pre, dataset = _chain(tmp_path)
    before = family_features(identifier, project, pre, dataset)
    assert dataset["eligible"] and before["eligible"]
    scheme = dataset["schemes"][0]
    held = {s for s, h in scheme["assignment"].items() if h != "train"}
    changed = copy.deepcopy(pre)
    for r in changed["selections"]["rows"]:
        if r["geometry"][0] in held:
            r["value"] = r["value"] * 1000 + 7  # every validation, calibration and test value changes
    for r in changed.get("composites", {}).get("rows", []):
        if r["holeId"] in held:
            r["values"] = {k: (None if v is None else v * 1000 + 7) for k, v in r["values"].items()}
    after = family_features(identifier, project, changed, dataset)
    assert _strip_run_facts(after)["schemes"][0] == _strip_run_facts(before)["schemes"][0]
    tables = derived_tables(project, pre)
    train = set(members(tables["supports"], scheme["assignment"])["train"])
    record = before["schemes"][0]["populations"][0]
    assert record["trainMembers"] <= len(train)


def test_variograms_are_geocond_on_training_rows(tmp_path):
    from geocond import experimental_variogram
    from stages.dataset import members
    from stages.features import MAX_PAIRS, SEED, population_rows, variograms

    _, project, pre, dataset = _chain(tmp_path)
    scheme = dataset["schemes"][0]
    population = pre["populations"][0]
    holes_of = {s["id"]: s["holeId"] for s in project["supports"]}
    holes_of.update({r["id"]: r["holeId"] for r in pre.get("composites", {}).get("rows", [])})
    train = members([(m, holes_of[m]) for m in population["members"]], scheme["assignment"])["train"]
    rows = [r for r in population_rows(pre, train) if "Cu" in r["values"]]
    records = {v["name"]: v for v in variograms(rows, "Cu", 50.0, 2.0)}
    xyz = np.array([r["xyz"] for r in rows])
    z = np.array([r["values"]["Cu"] for r in rows])
    holes = sorted({r["hole"] for r in rows})
    direct = experimental_variogram(xyz, z, 2.0 * (np.arange(21) + 0.5), groups=[holes.index(r["hole"]) for r in rows],
                                    downhole=True, depths=[r["md"] for r in rows], max_pairs=MAX_PAIRS, seed=SEED)
    assert records["downhole"]["counts"] == [int(c) for c in direct.counts]
    assert records["downhole"]["values"] == [None if math.isnan(v) else float(v) for v in direct.values]
    assert sum(records["downhole"]["counts"]) > 0
    omni = experimental_variogram(xyz, z, 25.0 * (np.arange(13) + 0.5), max_pairs=MAX_PAIRS, seed=SEED)
    assert records["omni"]["counts"] == [int(c) for c in omni.counts]
    for name in ("azimuth-000", "azimuth-045", "azimuth-090", "azimuth-135", "vertical"):
        assert records[name]["angleTolerance"] == 22.5 and records[name]["bandwidth"] == 100.0
        assert "populationPairs" in records[name] and "seed" in records[name]


def test_conflicting_orientation_normals_are_undefined():
    from stages.features import orientation_from_normals

    registry = json.loads((FIXTURES / "registry.json").read_text(encoding="utf-8"))
    f38 = next(f for f in registry["fixtures"] if f["id"] == "F38")["parameters"]
    conflicting = orientation_from_normals(f38["orientations"])
    assert conflicting["status"] == f38["expect"]["status"] == "undefined" and conflicting["principal"] is None
    agreeing = orientation_from_normals([{"dip": 40, "dipDirection": 88}, {"dip": 45, "dipDirection": 92},
                                         {"dip": 50, "dipDirection": 90}])
    assert agreeing["status"] == "defined"
    assert agreeing["principal"]["dip"] == pytest.approx(45.0, abs=0.5)
    assert agreeing["principal"]["dipDirection"] == pytest.approx(90.0, abs=0.5)
    opposite_normals = orientation_from_normals([{"dip": 30, "dipDirection": 10}, {"dip": 30, "dipDirection": 10}])
    assert opposite_normals["status"] == "defined"  # one plane measured twice is not a conflict


def test_cell_declustering():
    from stages.features import declustered_mean

    grid = np.array([[x, y, 0.0] for x in range(0, 500, 100) for y in range(0, 500, 100)], dtype=float)
    z = np.arange(len(grid), dtype=float)
    mean, weights = declustered_mean(grid, z, (100.0, 100.0, 1.0))
    assert mean == pytest.approx(z.mean(), abs=1e-12) and np.allclose(weights, weights[0])
    clustered = np.vstack([grid, [[1.0, 1.0, 0.0], [2.0, 2.0, 0.0], [3.0, 3.0, 0.0]]])
    values = np.r_[np.full(len(grid), 1.0), [10.0, 10.0, 10.0]]
    mean, _ = declustered_mean(clustered, values, (100.0, 100.0, 1.0))
    assert values.mean() > mean > 1.0  # the cluster of high values is down-weighted, not removed
