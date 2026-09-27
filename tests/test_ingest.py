"""The canonical ingest of the three field families against the counts of the research dossiers.

Rocklea and Alberta read the pinned downloads from ``$SONDARA_RAW`` (skipped when absent: raw sources are not in the
repository); NTGS reads the bundled licensed subset and always runs.
"""

import hashlib
import json
import os
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("SONDARA_RAW", ROOT / "build" / "sources"))


def needs(*files):
    missing = [f for f in files if not (RAW / f).is_file()]
    return pytest.mark.skipif(bool(missing), reason=f"raw sources not in {RAW}: {missing}")


def test_the_manifest_pins_every_source_with_license_and_attribution():
    manifest = json.loads((ROOT / "data/sources/manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["families"]) == {"rocklea", "alberta", "ntgs"}
    for family in manifest["families"].values():
        assert family["license"] and family["attribution"]
    for f in manifest["files"]:
        assert len(f["sha256"]) == 64 and f["bytes"] > 0
        if "bundled" in f:
            data = (ROOT / f["bundled"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == f["sha256"] and len(data) == f["bytes"]
        else:
            assert f["url"].startswith("https://")


@needs("Rocklea_Assay_MMX.xlsx", "RC_data_tsgexport.CSV", "dem_plus_collars.csv")
def test_rocklea_reconciles_to_the_dossier_population():
    from source_adapters.rocklea import FEATURES, normalize

    p = normalize(RAW)
    assert [w["count"] for w in p["waterfall"]] == [17474, 7240, 5035, 158]
    assert len(p["collars"]) == 158 and len(p["supports"]) == 5035
    assert len(p["determinations"]) == 5035 * len(FEATURES)
    assert {t["kind"] for t in p["trajectories"]} == {"assumed-vertical"}
    assert all(c["totalDepth"] is None and c["observedDepthMax"] > 0 for c in p["collars"])
    issues = {i["code"]: len(i["rowIds"]) for i in p["issues"]}
    assert issues["ALL_ANALYTE_ZERO"] == 2205 and issues["UNMATCHED_SOURCE_GEOMETRY"] == 10234
    by_support = Counter(d["supportId"] for d in p["determinations"])
    assert set(by_support.values()) == {len(FEATURES)}
    zero_rows = [s for s in p["supports"]
                 if all(d["value"] == 0 for d in p["determinations"] if d["supportId"] == s["id"])][:1]
    assert not zero_rows


@needs("DIG_2024_0022_0.zip")
def test_alberta_keeps_native_sampling_support():
    from source_adapters.alberta import normalize

    p = normalize(RAW)
    assert len(p["collars"]) == 22 and len(p["geology"]) == 150 and len(p["supports"]) == 342
    kinds = Counter(s["kind"] for s in p["supports"])
    assert kinds == {"sampling-envelope": 176, "point": 162, "unknown": 4}
    assert all(s["samplingMeasure"] == "unknown" for s in p["supports"] if s["kind"] == "sampling-envelope")
    issues = {i["code"]: len(i["rowIds"]) for i in p["issues"]}
    assert issues["OVERLAPPING_ENVELOPES"] == 85 and issues["COMPOSITE_NOTES"] == 79
    assert issues["LOI_METHODS_NOT_REPLICATES"] == 81
    assert all(abs(c["orientation"]["sourceInclination"] - (90 + c["orientation"]["dip"])) < 1e-9 for c in p["collars"])
    assert {t["kind"] for t in p["trajectories"]} == {"collar-orientation"}
    assert Counter(g["kind"] for g in p["geology"])["event"] == 12
    assert all(d["value"] is not None or d["qualifier"] != "=" for d in p["determinations"])


def test_ntgs_is_one_measured_hole_with_censoring_kept_as_qualifiers():
    from source_adapters.ntgs import normalize

    p = normalize()
    assert len(p["collars"]) == 1 and len(p["surveys"]) == 13 and len(p["supports"]) == 59
    assert Counter(s["role"] for s in p["surveys"])["measured"] == 11
    assert p["trajectories"][0]["kind"] == "measured-stations"
    censored = [d for d in p["determinations"] if d["qualifier"] in ("<", ">")]
    assert len(censored) == 850 and all(d["value"] is None and d["detectionLimit"] > 0 for d in censored)
    assert all(d["value"] is None or d["value"] >= 0 for d in p["determinations"])
    assert [w["count"] for w in p["waterfall"]] == [1892, 850, 118, 56]
    assert p["frames"][0]["origin"]["sourceHorizontalCrs"] == "EPSG:28352"


def test_ingest_writes_a_hashed_project_and_summary(tmp_path):
    import run

    summary = run.ingest("ntgs", RAW, tmp_path)
    project = json.loads((tmp_path / "ntgs" / "project.json").read_text(encoding="utf-8"))
    assert summary["counts"]["determinations"] == 1892
    assert summary["projectSha256"] == run.stable_hash(project)
    again = run.ingest("ntgs", RAW, tmp_path)
    assert again["projectSha256"] == summary["projectSha256"]  # deterministic


def _contract():
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_artifacts", ROOT / "scripts" / "check_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_contract_check_accepts_the_ingest_and_rejects_each_corruption(tmp_path):
    import copy

    import run
    from source_adapters.ntgs import normalize

    contract = _contract()
    run.ingest("ntgs", RAW, tmp_path)
    assert contract.main(["--derived", str(tmp_path)]) == 0
    base = normalize()
    assert contract.check_project(base) == []

    def broken(mutate):
        p = copy.deepcopy(base)
        mutate(p)
        return contract.check_project(p)

    censored = next(i for i, d in enumerate(base["determinations"]) if d["qualifier"] == "<")
    assert broken(lambda p: p["determinations"][censored].update(value=-0.5))  # negative limit as a grade
    assert broken(lambda p: p["determinations"][0].update(supportId="nowhere"))
    assert broken(lambda p: p["supports"][0].update(toMd=p["supports"][0]["fromMd"]))
    assert broken(lambda p: p["surveys"][1].update(azimuth=400.0))
    assert broken(lambda p: p["issues"][0].update(rowIds=[]))
    assert broken(lambda p: p["trajectories"].clear())
    (tmp_path / "ntgs" / "summary.json").write_text("{}", encoding="utf-8")
    assert contract.main(["--derived", str(tmp_path)]) == 1  # a stale summary is caught


def test_acquire_refuses_a_changed_source(tmp_path):
    from source_io import acquire, digest

    manifest = json.loads((ROOT / "data/sources/manifest.json").read_text(encoding="utf-8"))
    bundled = next(f for f in manifest["files"] if "bundled" in f)
    tampered = {**bundled, "sha256": "0" * 64}
    with pytest.raises(ValueError, match="hash mismatch"):
        acquire(tmp_path / "fresh", manifest={"files": [tampered]})
    assert not (tmp_path / "fresh" / bundled["file"]).exists()  # nothing written for the refused source
    cache = tmp_path / "cached"
    cache.mkdir()
    (cache / bundled["file"]).write_bytes(b"changed upstream")
    with pytest.raises(ValueError, match="hash mismatch"):
        acquire(cache, manifest={"files": [bundled]})
    assert digest(cache / bundled["file"]) != bundled["sha256"]
