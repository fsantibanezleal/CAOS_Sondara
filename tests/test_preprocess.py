"""The preprocess stage: authored cases with exact answers, then the three field families against the dossier gates."""

import copy
import importlib.util
import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("SONDARA_RAW", ROOT / "build" / "sources"))


def needs(*files):
    missing = [f for f in files if not (RAW / f).is_file()]
    return pytest.mark.skipif(bool(missing), reason=f"raw sources not in {RAW}: {missing}")


def _contract():
    spec = importlib.util.spec_from_file_location("check_artifacts", ROOT / "scripts" / "check_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _authored():
    """Three holes, one of each trajectory kind, with a gap, a residual and a conflicting log overlap."""
    from source_adapters.common import (
        collar,
        determination,
        frame,
        localized,
        project,
        support,
        survey,
        trajectory,
    )

    p = project("authored", localized("authored"), [], "authored test project", frame("local", "local-metric"),
                kind="authored-validation")
    p["collars"] = [collar("V", "t", "V", "local", 10.0, 20.0, 500.0, [], total_depth=6.0, observed_depth=6.0),
                    collar("C", "t", "C", "local", 0.0, 0.0, 0.0, [], total_depth=50.0),
                    collar("M", "t", "M", "local", 0.0, 0.0, 0.0, [], total_depth=120.0)]
    p["trajectories"] = [trajectory("V", "assumed-vertical", []), trajectory("C", "collar-orientation", []),
                         trajectory("M", "measured-stations", [])]
    p["surveys"] = [survey("s1", "C", 0.0, 90.0, -45.0, "recorded-collar-direction", []),
                    survey("s2", "M", 0.0, 0.0, 0.0, "recorded-collar-direction", []),
                    survey("s3", "M", 100.0, 0.0, -90.0, "measured", []),
                    survey("s4", "M", 110.0, 45.0, -10.0, "compiled-extension", [])]  # never a station
    p["analytes"] = [{"id": "Cu", "name": localized("Cu"), "unit": "ppm", "quantity": "authored", "sourceRefs": []}]
    for sid, a, b, z in (("v1", 0, 1, 2.0), ("v2", 1, 3, 5.0), ("v3", 4, 6, 3.0)):
        p["supports"].append(support(sid, "V", float(a), float(b), [], "authored", sample=sid))
        p["determinations"].append(determination(f"{sid}:Cu", sid, "Cu", z, z, "ppm", []))
    p["supports"].append(support("e1", "C", 10.0, 20.0, [], "authored envelope", unknown_weights=True))
    p["supports"].append(support("p1", "C", 30.0, 30.0, [], "authored point"))
    p["supports"].append(support("m1", "M", 50.0, 60.0, [], "authored"))

    def log(identifier, a, b, rock, litho):
        return {"id": identifier, "holeId": "C", "kind": "interval", "fromMd": a, "toMd": b, "atMd": None,
                "codes": {"Rock_type": rock, "Litho_unit": litho}, "description": None, "mappedCode": None,
                "mappingVersion": None, "sourceRefs": []}

    p["geology"] = [log("g1", 8.0, 15.0, "A", "a"), log("g2", 14.0, 18.0, "B", "-9999")]
    return p


def _stage():
    from stages import preprocess

    return preprocess


def test_authored_compositing_positions_and_statuses():
    stage = _stage()
    p = _authored()
    surveys = stage.build_surveys(p)
    comps = stage.composite_family(p, surveys, ["Cu"], stage.select_results(p))
    table = {(r["length"], r["fromMd"]): r for r in comps["rows"] if r["holeId"] == "V"}
    assert table[(2.0, 0.0)]["values"]["Cu"] == 3.5 and table[(2.0, 0.0)]["status"] == "full"
    assert table[(2.0, 2.0)]["status"] == "insufficient-coverage" and table[(2.0, 2.0)]["values"]["Cu"] is None
    assert table[(2.0, 2.0)]["validLength"] == 1.0 and table[(2.0, 2.0)]["numerators"]["Cu"] == 5.0
    assert table[(2.0, 4.0)]["values"]["Cu"] == 3.0
    assert table[(5.0, 0.0)]["status"] == "insufficient-coverage" and table[(5.0, 5.0)]["status"] == "residual"
    for length in (1.0, 2.0, 5.0):
        rows = [r for r in comps["rows"] if r["holeId"] == "V" and r["length"] == length]
        assert sum(r["numerators"]["Cu"] for r in rows) == 2 + 10 + 6
    positions = {r["supportId"]: r for r in stage.support_positions(p, surveys)}
    assert positions["v3"]["to"] == pytest.approx([10.0, 20.0, 494.0], abs=1e-12)  # vertical: collar z minus depth
    s = math.sqrt(0.5)
    assert np.allclose(positions["e1"]["mid"], [15 * s, 0.0, -15 * s], atol=1e-12)  # recorded direction 90 / -45
    assert np.allclose(positions["p1"]["at"], [30 * s, 0.0, -30 * s], atol=1e-12)
    end = next(t for t in stage.trajectory_records(p, surveys) if t["holeId"] == "M")
    assert abs(end["maxDoglegDegrees"] - 90.0) < 1e-9
    at_100 = surveys["M"].at([100.0]).points[0]
    assert np.allclose(at_100, [0.0, 200 / math.pi, -200 / math.pi], atol=1e-9)  # quarter circle: 2L/pi each way
    assert end["endExtended"] and np.allclose(end["endPosition"], at_100 + [0, 0, -20.0], atol=1e-9)


def test_authored_overlay_flags_conflicts_and_unknown_codes():
    stage = _stage()
    overlay = stage.overlay_envelopes(_authored())
    row = overlay["rows"][0]
    assert row["anyLog"]["coverage"] == pytest.approx(0.8) and not row["anyLog"]["fullyCovered"]
    assert row["rockType"]["coverage"] == pytest.approx(0.7)  # 14-15 m is A and B at once: a conflict, not covered
    assert row["rockType"]["proportions"] == pytest.approx({"A": 4 / 7, "B": 3 / 7})
    assert row["lithoUnit"]["coverage"] == pytest.approx(0.5)  # '-9999' is unknown, and 14-15 m keeps its known 'a'
    assert row["multiplyLoggedLength"] == pytest.approx(1.0)
    assert [(c["field"], c["codes"]) for c in overlay["conflicts"]] == [("rockType", ["A", "B"])]


def test_stations_below_the_collar_need_a_declared_start_extension():
    stage = _stage()
    p = _authored()
    p["surveys"] = [s for s in p["surveys"] if not (s["holeId"] == "M" and s["md"] == 0.0)]
    with pytest.raises(ValueError, match="no start extension is declared"):
        stage.build_surveys(p)
    next(t for t in p["trajectories"] if t["holeId"] == "M")["startExtension"] = "tangent"
    survey = stage.build_surveys(p)["M"]
    assert np.allclose(survey.at([40.0]).points[0], [0.0, 0.0, -40.0], atol=1e-12)  # first tangent, straight down


def _pre(family, tmp_path):
    import run

    run.ingest(family, RAW, tmp_path)
    run.preprocess(family, tmp_path)
    project = json.loads((tmp_path / family / "project.json").read_text(encoding="utf-8"))
    pre = json.loads((tmp_path / family / "preprocessed.json").read_text(encoding="utf-8"))
    return project, pre


@needs("Rocklea_Assay_MMX.xlsx", "RC_data_tsgexport.CSV", "dem_plus_collars.csv")
def test_rocklea_composites_reproduce_and_conserve(tmp_path):
    project, pre = _pre("rocklea", tmp_path)
    rows = pre["composites"]["rows"]
    by_status = {(r["length"], r["status"]) for r in rows}
    assert by_status <= {(L, s) for L in (1.0, 2.0, 5.0) for s in ("full", "residual", "insufficient-coverage")}
    counts = {w["step"]: (w["full"], w["residual"], w["insufficientCoverage"]) for w in pre["waterfall"]}
    assert counts["1 m composites"] == (5035, 0, 12)  # one composite per native interval, one per 1 m gap
    assert counts["2 m composites"][2] == 12 and counts["5 m composites"][2] == 12
    values = {}
    for d in project["determinations"]:
        values[(d["supportId"], d["analyteId"])] = d["value"]
    ones = [r for r in rows if r["length"] == 1.0 and r["status"] == "full"]
    for r in ones:
        (parent, overlap), = r["parents"]
        assert overlap == 1.0 and all(r["values"][a] == values[(parent, a)] for a in r["values"])
    gaps = {(g["holeId"], g["fromMd"]) for g in pre["gaps"]}
    assert len(gaps) == 12 and all((r["holeId"], r["fromMd"]) in gaps for r in rows
                                   if r["length"] == 1.0 and r["status"] == "insufficient-coverage")
    assert max(pre["composites"]["conservationMaxRelativeError"].values()) < 1e-12
    collars = {c["id"]: c for c in project["collars"]}
    for p in pre["positions"][:500]:
        c = collars[p["holeId"]]
        assert p["mid"] == pytest.approx([c["x"], c["y"], c["z"] - (p["fromMd"] + p["toMd"]) / 2], abs=1e-9)
    native = next(q for q in pre["populations"] if q["id"] == "rocklea-native-1m")
    assert (native["count"], native["holes"]) == (5035, 158)
    assert _contract().check_preprocessed(pre, project) == []


@needs("DIG_2024_0022_0.zip")
def test_alberta_overlay_and_populations_match_the_dossier(tmp_path):
    project, pre = _pre("alberta", tmp_path)
    summary = pre["overlay"]["summary"]
    assert (summary["envelopes"], summary["envelopeLength"], summary["multiplyLoggedEnvelopes"]) == (176, 1960.4, 2)
    assert [summary[k]["fullyCovered"] for k in ("anyLog", "lithoUnit", "rockType")] == [173, 51, 36]
    assert [summary[k]["coveredLength"] for k in ("anyLog", "lithoUnit", "rockType")] == [1960.1, 285.6, 207.4]
    assert pre["overlay"]["conflicts"] == [] and pre["beyondTotalDepth"] == []
    doubly = {r["supportId"] for r in pre["overlay"]["rows"] if r["multiplyLoggedLength"] > 0}
    assert {s["holeId"] for s in project["supports"] if s["id"] in doubly} == {"MR-14"}
    centre = next(q for q in pre["populations"] if q["id"] == "alberta-envelope-centre-cu-zn")
    assert (centre["count"], centre["holes"], centre["excluded"]) == (176, 22, {"point": 162, "unknown": 4})
    collars = {c["id"]: c for c in project["collars"]}
    for p in pre["positions"]:
        if p["kind"] != "sampling-envelope":
            continue
        o = collars[p["holeId"]]["orientation"]
        a, d = np.radians(o["azimuth"]), np.radians(o["dip"])
        t = np.array([np.cos(d) * np.sin(a), np.cos(d) * np.cos(a), np.sin(d)])
        c = collars[p["holeId"]]
        assert np.allclose(p["mid"], np.array([c["x"], c["y"], c["z"]]) + (p["fromMd"] + p["toMd"]) / 2 * t, atol=1e-9)
    assert _contract().check_preprocessed(pre, project) == []


def test_ntgs_trajectory_gaps_and_repeats_match_the_dossier(tmp_path):
    project, pre = _pre("ntgs", tmp_path)
    t = pre["trajectories"][0]
    assert abs(t["maxDoglegDegrees"] - 1.5014466345301114) < 1e-9
    assert [s["md"] for s in t["stations"]][:2] == [0.0, 60.0] and len(t["stations"]) == 12
    from stages.preprocess import build_surveys

    survey = build_surveys(project)["8440823"]
    collar = project["surveys"][0]
    a, d = np.radians(collar["azimuth"]), np.radians(collar["dip"])
    straight = 364.600006 * np.array([np.cos(d) * np.sin(a), np.cos(d) * np.cos(a), np.sin(d)])
    displacement = np.linalg.norm(survey.at([364.600006]).points[0] - straight)
    assert abs(displacement - 9.565414584568332) < 1e-6  # dossier value; this implementation differs by about 8e-11 m
    assert t["endExtended"]  # total depth lies beyond the last measured station at 360 m
    assert len(pre["gaps"]) == 50 and round(sum(g["length"] for g in pre["gaps"]), 6) == 169.51
    assert [(r["fromMd"], r["toMd"]) for r in pre["repeats"]] == [(153.0, 154.0), (232.5, 232.6), (327.5, 327.6)]
    estimation = next(q for q in pre["populations"] if q["id"] == "ntgs-estimation")
    assert estimation["count"] == 0 and "one hole" in estimation["rule"]
    assert sum(v["censored"] for v in pre["censoring"].values()) == 850
    assert _contract().check_preprocessed(pre, project) == []


def test_the_contract_check_rejects_each_preprocess_corruption(tmp_path):
    project, pre = _pre("ntgs", tmp_path)
    contract = _contract()

    def broken(mutate, target="pre"):
        p, q = copy.deepcopy(project), copy.deepcopy(pre)
        mutate(q if target == "pre" else p)
        return contract.check_preprocessed(q, p)

    assert broken(lambda q: q["positions"].pop())
    assert broken(lambda q: q["positions"][0].update({"mid": [0.0, float("nan"), 0.0]}))
    assert broken(lambda q: q["populations"][0]["members"].append("nowhere"))
    assert broken(lambda q: q["trajectories"].clear())
    assert broken(lambda p: p["collars"][0].update({"z": 1.0}), target="project")  # built from another project
    stage = _stage()
    authored = _authored()
    surveys = stage.build_surveys(authored)
    selection = stage.select_results(authored)
    rocklike = {"schema": "drillhole.preprocessed/v1", "inputProjectSha256": contract.stable_hash(authored),
                "trajectories": stage.trajectory_records(authored, surveys),
                "positions": stage.support_positions(authored, surveys), "selections": selection,
                "composites": stage.composite_family(authored, surveys, ["Cu"], selection), "populations": []}
    assert contract.check_preprocessed(rocklike, authored) == []
    rocklike["composites"]["rows"][0]["numerators"]["Cu"] += 1.0
    assert any("conserve" in e for e in contract.check_preprocessed(rocklike, authored))


def test_preprocess_refuses_a_changed_project(tmp_path):
    import run

    run.ingest("ntgs", RAW, tmp_path)
    path = tmp_path / "ntgs" / "project.json"
    project = json.loads(path.read_text(encoding="utf-8"))
    project["collars"][0]["z"] = 1.0
    path.write_text(json.dumps(project), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match its ingest summary"):
        run.preprocess("ntgs", tmp_path)
    assert not (tmp_path / "ntgs" / "preprocessed.json").exists()
