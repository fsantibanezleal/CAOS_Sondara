"""The manifest importer and the preprocess behaviours it feeds, one test per requirement, on fixtures F01 to F30 and F41.

Every fixture is authored (``scripts/fixtures/author_fixtures.py``) and listed in ``data/fixtures/registry.json``.
"""

import copy
import json
import math
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures"


def _import(manifest, out, cancel=None):
    from source_adapters.manifest_import import run_import

    report = run_import(FIXTURES / manifest, out, cancel)
    identifier = report["project"]
    path = out / identifier / "project.json"
    project = json.loads(path.read_text(encoding="utf-8")) if report["status"] == "accepted" else None
    return report, project


def _preprocess(out, identifier):
    import run

    run.preprocess(identifier, out)
    return json.loads((out / identifier / "preprocessed.json").read_text(encoding="utf-8"))


def _codes(report, code):
    return [f for f in report["findings"] if f["code"] == code]


def _canonical(project):
    """The scientific content, without provenance, file references, issues or the file-count waterfall."""
    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k != "sourceRefs"}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value
    return strip({k: v for k, v in project.items() if k not in ("provenance", "issues", "waterfall")})


def test_the_manifest_is_validated_before_reading(tmp_path):
    from source_adapters.manifest_import import ManifestInvalid, run_import

    bad = {"schema": "drillhole.import/v1", "project": {"id": "x", "name": "x"},
           "frame": {"id": "f", "kind": "projected-metric"},
           "files": [{"path": "does-not-exist.csv", "role": "core-photos", "columns": {"hole": "H"}}]}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ManifestInvalid, match="role"):
        run_import(path, tmp_path / "out")  # a FileNotFoundError here would mean the file was opened first
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_split_and_reordered_files_equal_the_consolidated_import(tmp_path):
    _, consolidated = _import("F01/consolidated.json", tmp_path / "a")
    _, split = _import("F01/split.json", tmp_path / "b")
    _, reordered = _import("F02/reordered.json", tmp_path / "c")
    assert len(consolidated["supports"]) == 45 and len(consolidated["geology"]) == 6
    assert _canonical(split) == _canonical(consolidated)
    assert _canonical(reordered) == _canonical(consolidated)


def test_a_repeated_file_adds_no_measurement(tmp_path):
    report, project = _import("F03/import.json", tmp_path)
    assert [f["file"] for f in _codes(report, "FILE_DUPLICATE")] == ["assays_copy.csv"]
    assert len(project["supports"]) == 45 and len(project["determinations"]) == 90


def test_conflicting_collars_block_until_resolved(tmp_path):
    report, project = _import("F04/import.json", tmp_path)
    assert report["status"] == "rejected" and project is None and not (tmp_path / "f04").exists()
    (conflict,) = _codes(report, "COLLAR_CONFLICT")
    assert conflict["hole"] == "s:DH2" and conflict["rows"] == ["collars_a.csv:3", "collars_b.csv:2"]
    assert "500050.0" in conflict["message"] and "500055.0" in conflict["message"]
    assert "15 assay, 3 survey" in conflict["message"]
    report, project = _import("F04/resolved.json", tmp_path)
    assert report["status"] == "accepted" and _codes(report, "COLLAR_CONFLICT_RESOLVED")
    assert next(c for c in project["collars"] if c["id"] == "s:DH2")["x"] == 500055.0


def test_namespaces_keep_reused_hole_ids_apart(tmp_path):
    _, project = _import("F05/import.json", tmp_path / "a")
    assert sorted((c["id"], c["namespace"], c["sourceHoleId"]) for c in project["collars"]) == [
        ("a:DH001", "a", "DH001"), ("b:DH001", "b", "DH001")]
    report, merged = _import("F05/aliased.json", tmp_path / "b")
    assert [c["id"] for c in merged["collars"]] == ["a:DH001"] and _codes(report, "ALIAS_APPLIED")
    assert sorted(s["id"] for s in merged["supports"]) == ["a:DH001/A-1", "a:DH001/B-1"]


def test_assays_without_collars_stay_pending(tmp_path):
    report, project = _import("F06/import.json", tmp_path)
    assert report["status"] == "pending" and project is None and _codes(report, "COLLARS_PENDING")
    assert not (tmp_path / "f06").exists()


def test_an_orphan_assay_is_isolated(tmp_path):
    report, project = _import("F07/import.json", tmp_path)
    assert report["status"] == "accepted"
    (orphan,) = _codes(report, "ORPHAN_ASSAY")
    assert (orphan["hole"], orphan["file"], orphan["rows"]) == ("s:DH9", "orphan.csv", ["2"])
    assert {c["id"] for c in project["collars"]} == {"s:DH1", "s:DH2", "s:DH3"}
    assert not any(s["holeId"] == "s:DH9" for s in project["supports"])
    assert any(i["code"] == "ORPHAN_ASSAY" for i in project["issues"])


def test_hole_ids_keep_case_and_zeros_and_collisions_are_reported(tmp_path):
    report, project = _import("F08/import.json", tmp_path)
    assert sorted(c["sourceHoleId"] for c in project["collars"]) == ["00012", "12", "DH-12", "dh-12"]
    groups = sorted(f["message"].split(" differ")[0] for f in _codes(report, "ID_NORMALIZATION_COLLISION"))
    assert groups == ["s:00012, s:12", "s:DH-12, s:dh-12"]


def test_declared_dialects_preserve_values(tmp_path):
    _, project = _import("F09/import.json", tmp_path)
    (c,) = project["collars"]
    assert (c["x"], c["y"], c["z"]) == (500000.5, 7400000.25, 1000.75)
    first = min(project["geology"], key=lambda g: g["fromMd"])
    assert (first["fromMd"], first["toMd"], first["description"]) == (0.0, 12.5, 'clay; sandy, "soft"')


def test_malformed_files_fail_with_file_row_and_column(tmp_path):
    report, project = _import("F10/duplicate_header.json", tmp_path)
    (finding,) = _codes(report, "HEADER_DUPLICATE")
    assert report["status"] == "rejected" and project is None
    assert finding["file"] == "duplicate_header.csv" and "From" in finding["message"]
    report, project = _import("F10/ragged.json", tmp_path)
    (finding,) = _codes(report, "ROW_RAGGED")
    assert report["status"] == "rejected" and (finding["file"], finding["rows"]) == ("ragged.csv", ["3"])
    assert not (tmp_path / "f10").exists()


def test_feet_convert_exactly(tmp_path):
    report, project = _import("F11/import.json", tmp_path)
    (s,) = project["supports"]
    assert (s["fromMd"], s["toMd"]) == (0.0, 3.048)
    assert [v["md"] for v in project["surveys"]] == [0.0, 3.048, 30.48]
    assert project["collars"][0]["totalDepth"] == 30.48 and _codes(report, "UNIT_CONVERTED")


def test_crs_mismatch_and_swapped_axes_fail_before_join(tmp_path):
    report, _ = _import("F12/crs.json", tmp_path)
    assert report["status"] == "rejected" and _codes(report, "CRS_MISMATCH")
    report, _ = _import("F12/axes.json", tmp_path)
    (swap,) = _codes(report, "AXES_SWAPPED_SUSPECTED")
    assert report["status"] == "rejected" and swap["file"] == "collars_swapped.csv"
    report, project = _import("F12/declared.json", tmp_path)
    dh3 = next(c for c in project["collars"] if c["id"] == "s:DH3")
    assert report["status"] == "accepted" and (dh3["x"], dh3["y"]) == (500100.0, 7400050.0)


def test_analytic_trajectories(tmp_path):
    for fixture, identifier in (("F13", "f13"), ("F14", "f14"), ("F15", "f15")):
        _import(f"{fixture}/import.json", tmp_path)
    vertical = _preprocess(tmp_path, "f13")["trajectories"][0]
    assert vertical["endPosition"] == pytest.approx([1000.0, 2000.0, 400.0], abs=1e-9)
    arc = _preprocess(tmp_path, "f14")["trajectories"][0]
    radius = 200 / math.pi
    assert arc["endPosition"] == pytest.approx([1000.0 + radius, 2000.0 + radius, 500.0], abs=1e-9)
    wrap = _preprocess(tmp_path, "f15")["trajectories"][0]
    assert wrap["maxDoglegDegrees"] == pytest.approx(2.0, abs=1e-9)


def test_dip_conventions_give_the_same_trace(tmp_path):
    ends, dips = [], []
    for name in ("negative", "positive", "vertical"):
        out = tmp_path / name
        _, project = _import(f"F16/{name}.json", out)
        dips.append([s["dip"] for s in project["surveys"]])
        ends.append(_preprocess(out, "f16")["trajectories"][0]["endPosition"])
    assert dips[0] == dips[1] == dips[2] == [-60.0, -58.0, -55.0]
    assert ends[0] == pytest.approx(ends[1], abs=1e-12) and ends[0] == pytest.approx(ends[2], abs=1e-12)


def test_conflicting_survey_depths_block_the_hole(tmp_path):
    report, project = _import("F17/import.json", tmp_path)
    (conflict,) = _codes(report, "SURVEY_DEPTH_CONFLICT")
    assert report["status"] == "rejected" and conflict["hole"] == "s:DH1" and project is None
    assert [f["hole"] for f in _codes(report, "RECORD_DUPLICATE")] == ["s:DH2"]
    report, project = _import("F17/excluded.json", tmp_path)
    assert report["status"] == "accepted" and {c["id"] for c in project["collars"]} == {"s:DH2", "s:DH3"}
    assert _codes(report, "HOLE_EXCLUDED")[0]["hole"] == "s:DH1"


def test_missing_and_truncated_surveys_are_declared(tmp_path):
    report, project = _import("F18/import.json", tmp_path)
    assert report["status"] == "rejected" and _codes(report, "SURVEY_MISSING_UNASSUMED")[0]["hole"] == "s:DH2"
    assert "0 to 30.0 m" in _codes(report, "SURVEY_ASSUMED")[0]["message"]
    assert "20.0 to 30.0 m" in _codes(report, "SURVEY_TRUNCATED")[0]["message"]
    report, project = _import("F18/assumed.json", tmp_path)
    kinds = {t["holeId"]: t["kind"] for t in project["trajectories"]}
    assert kinds == {"s:DH1": "collar-orientation", "s:DH2": "assumed-vertical", "s:DH3": "measured-stations"}
    extended = {t["holeId"]: t["extendedRanges"] for t in _preprocess(tmp_path, "f18")["trajectories"]}
    assert extended["s:DH3"] == [[20.0, 30.0]] and extended["s:DH2"] == [[0.0, 30.0]]


def test_invalid_intervals_are_excluded_by_record(tmp_path):
    report, project = _import("F19/import.json", tmp_path)
    assert sorted(r for f in _codes(report, "INTERVAL_INVALID") for r in f["rows"]) == ["3", "4", "5"]
    assert sorted(s["sampleId"] for s in project["supports"]) == ["A", "B"]


def test_overlapping_assays_are_conflicts_not_sums(tmp_path):
    report, project = _import("F20/import.json", tmp_path)
    (overlap,) = _codes(report, "ASSAY_OVERLAP")
    assert overlap["rows"] == ["s:DH1/A", "s:DH1/B"]
    assert sorted(x["rowId"] for x in project["exclusions"]) == ["s:DH1/A:Cu_ppm", "s:DH1/B:Cu_ppm"]
    pre = _preprocess(tmp_path, "f20")
    assert [r["determinationId"] for r in pre["selections"]["rows"]] == ["s:DH1/C:Cu_ppm"]
    values = [r["values"]["Cu"] for r in pre["composites"]["rows"] if r["values"]["Cu"] is not None]
    assert values == [300.0]  # never 100, 200 or their average


def test_parallel_series_are_separate_observations(tmp_path):
    report, project = _import("F21/import.json", tmp_path)
    assert not _codes(report, "ASSAY_OVERLAP") and project["exclusions"] == []
    by = Counter(d["analyteId"] for d in project["determinations"])
    assert by == {"Cu": 2, "Au": 1}
    pre = _preprocess(tmp_path, "f21")
    assert Counter(r["analyteId"] for r in pre["selections"]["rows"]) == {"Cu": 2, "Au": 1}


def test_overlay_fragments_conserve_parent_lengths(tmp_path):
    _, project = _import("F22/import.json", tmp_path)
    fragments = _preprocess(tmp_path, "f22")["fragments"]
    assert [(f["fromMd"], f["toMd"]) for f in fragments["rows"]] == [(0.0, 2.0), (2.0, 3.0), (3.0, 5.0)]
    assert fragments["parentLengthMaxError"] == 0.0
    by_log = Counter()
    for f in fragments["rows"]:
        for log in f["logIds"]:
            by_log[log] += f["toMd"] - f["fromMd"]
    assert {g["id"]: g["toMd"] - g["fromMd"] for g in project["geology"]} == dict(by_log)


def test_composite_fixtures(tmp_path):
    for fixture in ("F23", "F24", "F25"):
        _import(f"{fixture}/import.json", tmp_path)
    (five,) = _preprocess(tmp_path, "f23")["composites"]["rows"]
    assert (five["fromMd"], five["toMd"], five["status"]) == (0.0, 5.0, "full")
    assert five["values"]["Cu"] == pytest.approx(2.2, abs=1e-12)
    (three,) = _preprocess(tmp_path, "f24")["composites"]["rows"]
    assert three["coverage"] == pytest.approx(2 / 3) and three["observedMeans"]["Cu"] == pytest.approx(3.0)
    assert three["values"]["Cu"] is None and three["status"] == "insufficient-coverage"
    rows = _preprocess(tmp_path, "f25")["composites"]["rows"]
    assert [(r["fromMd"], r["toMd"], r["status"]) for r in rows] == [
        (0.0, 2.0, "full"), (2.0, 4.0, "full"), (4.0, 5.5, "residual")]


def test_states_are_distinct_and_eligibility_is_versioned(tmp_path):
    _, project = _import("F26/import.json", tmp_path)
    states = {d["supportId"].split("/")[1]: (d["state"], d["value"], d["qualifier"], d["detectionLimit"])
              for d in project["determinations"]}
    assert states == {"CENS": ("censored-below", None, "<", 0.5), "ZERO": ("measured", 0.0, "=", None),
                      "BLANK": ("missing", None, None, None), "NS": ("not-sampled", None, None, None),
                      "LOST": ("lost-core", None, None, None), "SENT": ("sentinel", None, None, None),
                      "MEAS": ("measured", 12.5, "=", None)}
    eligibility = _preprocess(tmp_path, "f26")["eligibility"]
    assert eligibility["version"] == "eligibility-v1"
    assert eligibility["selected"] == {"Cu": 2} and eligibility["unresolved"] == {"Cu": 5}


def test_overlimit_reassay_is_selected(tmp_path):
    _, project = _import("F27/import.json", tmp_path)
    kept = sorted((d["state"], d["unit"], d["value"], d["detectionLimit"]) for d in project["determinations"])
    assert kept == [("censored-above", "ppm", None, 10000.0), ("measured", "%", 1.2, None)]
    (selected,) = _preprocess(tmp_path, "f27")["selections"]["rows"]
    assert (selected["value"], selected["unit"], selected["rule"]) == (pytest.approx(12000.0), "ppm", "reassay")


def test_result_selection_is_explicit(tmp_path):
    _, project = _import("F28/import.json", tmp_path / "a")
    pre = _preprocess(tmp_path / "a", "f28")
    (unresolved,) = pre["selections"]["unresolved"]
    assert "no declared method priority" in unresolved["reason"] and pre["selections"]["rows"] == []
    _, project = _import("F28/priority.json", tmp_path / "b")
    pre = _preprocess(tmp_path / "b", "f28")
    (selected,) = pre["selections"]["rows"]
    chosen = next(d for d in project["determinations"] if d["id"] == selected["determinationId"])
    assert (chosen["method"], chosen["lab"], selected["value"], selected["rule"]) == ("AAS", "L2", 98.0, "priority")
    assert chosen["sampleRole"] == "original"
    assert len(project["supports"]) == 2 and len(pre["repeats"]) == 1  # the repeat is a sample, not new support
    assert all(len(r["parents"]) == 1 for r in pre["composites"]["rows"] if r["parents"])


def test_controls_get_no_coordinates(tmp_path):
    report, project = _import("F29/import.json", tmp_path)
    assert sorted((q["sampleId"], q["controlType"]) for q in project["qc"]) == [
        ("BLK-1", "blank"), ("STD-OREAS-45", "standard")]
    assert all(d["supportId"] is None for q in project["qc"] for d in q["determinations"])
    assert sorted(s["sampleId"] for s in project["supports"]) == ["S1", "S2"]
    assert not [f for f in report["findings"] if f["code"].startswith("ORPHAN")]
    positions = _preprocess(tmp_path, "f29")["positions"]
    assert sorted(p["supportId"] for p in positions) == ["s:DH1/S1", "s:DH1/S2"]


def test_repeats_do_not_multiply_fragments(tmp_path):
    _import("F30/import.json", tmp_path)
    pre = _preprocess(tmp_path, "f30")
    rows = pre["fragments"]["rows"]
    assert [(f["fromMd"], f["toMd"], f["supportIds"]) for f in rows] == [
        (0.0, 1.0, ["s:DH1/S3", "s:DH1/S3R"]), (1.0, 2.0, ["s:DH1/S3", "s:DH1/S3R"])]
    (selected,) = pre["selections"]["rows"]
    assert (selected["value"], selected["rule"]) == (5.0, "single")


def test_an_interrupted_import_leaves_the_previous_project(tmp_path):
    from source_adapters.manifest_import import ImportCancelled

    report, project = _import("F41/import.json", tmp_path)
    assert report["status"] == "accepted"
    path = tmp_path / "f41" / "project.json"
    before = path.read_bytes()
    with pytest.raises(ImportCancelled):
        _import("F41/replacement.json", tmp_path, cancel=lambda: True)  # at the first file
    calls = Counter()

    def at_commit():
        calls["n"] += 1
        return calls["n"] > len(json.loads((FIXTURES / "F41/replacement.json").read_text())["files"])

    with pytest.raises(ImportCancelled):
        _import("F41/replacement.json", tmp_path, cancel=at_commit)  # after the build, before the swap
    assert path.read_bytes() == before
    assert not [p for p in tmp_path.iterdir() if p.name.startswith((".staging", ".previous"))]
    report, replaced = _import("F41/replacement.json", tmp_path)
    assert report["status"] == "accepted" and replaced != copy.deepcopy(project)
    assert {d["value"] for d in replaced["determinations"] if d["analyteId"] == "Cu"} == {999.0}
