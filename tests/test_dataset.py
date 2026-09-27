"""The dataset stage: frozen grouped splits, and every derivative of a hole on its hole's side."""

import json
import os
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("SONDARA_RAW", ROOT / "build" / "sources"))
FIXTURES = ROOT / "data" / "fixtures"


def _chain(tmp_path, manifest):
    """Import a fixture and run preprocess and dataset; return the project, preprocessed output and dataset."""
    import run
    from source_adapters.manifest_import import run_import

    report = run_import(FIXTURES / manifest, tmp_path)
    identifier = report["project"]
    run.preprocess(identifier, tmp_path)
    run.dataset(identifier, tmp_path)
    load = lambda name: json.loads((tmp_path / identifier / name).read_text(encoding="utf-8"))
    return identifier, load("project.json"), load("preprocessed.json"), load("dataset.json")


def _grid(n_side=5, spacing=100.0):
    """An authored grid of holes, one 2 m sample each, as a preprocessed project stand-in."""
    holes = [f"H{i:02d}" for i in range(n_side * n_side)]
    project = {"collars": [{"id": h, "x": spacing * (i % n_side), "y": spacing * (i // n_side)}
                           for i, h in enumerate(holes)],
               "supports": [{"id": f"{h}/s", "holeId": h} for h in holes]}
    pre = {"populations": [{"id": "all", "members": [f"{h}/s" for h in holes]}]}
    return holes, project, pre


def test_every_member_follows_its_hole(tmp_path):
    from stages.dataset import derived_tables, members

    _, project, pre, dataset = _chain(tmp_path, "F40/import.json")
    tables = derived_tables(project, pre)
    assert {"supports", "composites", "fragments", "repeats"} <= set(tables)
    assert dataset["eligible"] and [s["id"] for s in dataset["schemes"]] == ["hole-group", "spatial-margin", "declared"]
    for scheme in dataset["schemes"]:
        assignment = scheme["assignment"]
        buffered = set(scheme.get("excludedByBuffer", []))
        assert set(assignment) | buffered == {c["id"] for c in project["collars"]}  # every hole, once
        assert not set(assignment) & buffered
        assert set(assignment.values()) <= {"train", "validation", "calibration", "test"}
        for name, table in tables.items():
            split = members(table, assignment)
            for s, rows in split.items():
                assert all(assignment[hole] == s for row, hole in table if row in set(rows)), (name, s)
            assert scheme["membership"][name]["counts"] == {s: len(v) for s, v in split.items()}


def test_hole_group_split_is_seeded_and_proportional():
    from stages.dataset import hole_group, largest_remainder

    holes = [f"H{i:03d}" for i in range(158)]
    first, again, other = hole_group(holes, 7), hole_group(holes, 7), hole_group(holes, 8)
    assert first["assignment"] == again["assignment"] and first["assignment"] != other["assignment"]
    assert Counter(first["assignment"].values()) == {"train": 95, "validation": 24, "calibration": 16, "test": 23}
    assert largest_remainder(158, (0.60, 0.15, 0.10, 0.15)) == [95, 24, 16, 23]
    assert largest_remainder(10, (0.60, 0.15, 0.10, 0.15)) == [6, 2, 1, 1]
    assert hole_group(list(reversed(holes)), 7)["assignment"] == first["assignment"]  # input order is irrelevant


def test_spatial_margin_split_holds_out_the_margin_with_a_buffer():
    from stages.dataset import BUFFER_FACTOR, collar_xy, spatial_margin

    holes, project, _ = _grid()
    xy = collar_xy(project)
    scheme = spatial_margin(holes, xy, 20260926)
    test = sorted(h for h, s in scheme["assignment"].items() if s == "test")
    centre = np.mean(list(xy.values()), axis=0)
    radius = {h: np.linalg.norm(xy[h] - centre) for h in holes}
    assert len(test) == 4 and all(radius[t] >= max(radius[h] for h in holes if h not in test) for t in test)
    assert test == ["H00", "H04", "H20", "H24"]  # the four corners of the 5 x 5 grid
    assert scheme["buffer"] == pytest.approx(BUFFER_FACTOR * 100.0)
    # each corner's first ring (two edge neighbours and one diagonal) is excluded, and nothing farther
    assert sorted(scheme["excludedByBuffer"]) == ["H01", "H03", "H05", "H06", "H08", "H09", "H15", "H16", "H18",
                                                  "H19", "H21", "H23"]
    assert not set(scheme["excludedByBuffer"]) & set(scheme["assignment"])


def test_declared_holdout_takes_every_derivative(tmp_path):
    from stages.dataset import derived_tables, members

    _, project, pre, dataset = _chain(tmp_path, "F40/import.json")
    declared = next(s for s in dataset["schemes"] if s["id"] == "declared")
    assert declared["holdout"] == ["s:B"] and declared["assignment"]["s:B"] == "test"
    tables = derived_tables(project, pre)
    from_b = {name: {row for row, hole in table if hole == "s:B"} for name, table in tables.items()}
    assert len(from_b["supports"]) == 5 and from_b["repeats"] and from_b["fragments"] and from_b["composites"]
    for name, table in tables.items():
        split = members(table, declared["assignment"])
        assert from_b[name] <= set(split["test"]), name
        assert not from_b[name] & set(split["train"] + split["validation"] + split["calibration"]), name


def test_single_hole_family_has_no_split():
    from source_adapters.ntgs import normalize
    from stages.dataset import split_family

    result = split_family("ntgs", normalize(), {"populations": []}, "p", "q")
    assert result["eligible"] is False and result["schemes"] == []
    assert "1 hole(s)" in result["reason"] and "at least 4" in result["reason"]


def test_the_contract_check_rejects_a_stale_split(tmp_path):
    import copy
    import importlib.util

    import run

    identifier, project, pre, dataset = _chain(tmp_path, "F40/import.json")
    run.features(identifier, tmp_path)
    features = json.loads((tmp_path / identifier / "features.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("check_artifacts", ROOT / "scripts" / "check_artifacts.py")
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    assert contract.check_dataset(dataset, project, pre) == []
    assert contract.check_features(features, dataset) == []
    moved = copy.deepcopy(dataset)
    hole = next(h for h, s in moved["schemes"][0]["assignment"].items() if s == "train")
    moved["schemes"][0]["assignment"][hole] = "test"  # a hole changes side after the memberships were recorded
    assert any("stale" in e for e in contract.check_dataset(moved, project, pre))
    assert contract.check_features(features, moved) == ["features were computed from another dataset"]
    other = copy.deepcopy(pre)
    other["populations"] = other["populations"][:1]
    assert contract.check_dataset(dataset, project, other) == ["dataset was built from other inputs"]
