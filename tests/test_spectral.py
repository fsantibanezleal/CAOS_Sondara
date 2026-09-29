"""R12's spectral lineage and the index check (SD-7b): pinned sources, products, embedded assays, registration, and a
monotone calibration fitted on training holes only."""

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data-pipeline"))
sys.path.insert(0, str(ROOT / "tests"))

import authored_field
from source_adapters import rocklea_spectral
from stages import spectral

MAPPING = spectral.load_mapping("rocklea")


def _project(holes):
    """A canonical project with one-metre supports: ``holes`` maps a hole to {from depth: {analyte: value}}."""
    supports, determinations = [], []
    for hole, depths in holes.items():
        for depth, values in depths.items():
            sid = f"{hole}-{depth:g}"
            supports.append({"id": sid, "holeId": hole, "kind": "interval", "fromMd": depth, "toMd": depth + 1})
            determinations += [{"supportId": sid, "analyteId": a, "value": v, "state": "measured",
                                "sampleRole": "original"} for a, v in values.items()]
    return {"supports": supports, "determinations": determinations}


def _row(hole, depth, embedded=None, spectral_values=None, row=2):
    embedded = embedded or {}
    return {"row": row, "sample": f"{hole}-{depth}", "hole": hole, "depthFrom": depth,
            "spectral": {c: (spectral_values or {}).get(c) for c in rocklea_spectral.SPECTRAL},
            "embedded": {c: embedded.get(c) for c in rocklea_spectral.EMBEDDED}}


def _source(rows, products=None):
    products = products if products is not None else [
        {"row": 12 + i, "Product name": e["product"], "Base algorithm": "a", "Filters/Masks": "m",
         "Lower stretch limit": "l", "Upper stretch limit (based on UGD1683)": "u", "related publication": "p",
         "Comments on general accuracy": "c"} for i, e in enumerate(MAPPING["spectral"])]
    return {"family": "rocklea", "sources": [], "columns": {"spectral": list(rocklea_spectral.SPECTRAL),
                                                             "embedded": list(rocklea_spectral.EMBEDDED)},
            "rows": rows, "descriptions": {"products": products},
            "project": {"parameters": [{"name": c, "index": i, "guid": "g"} for i, c in
                                       enumerate(rocklea_spectral.SPECTRAL)]},
            "pls": {"file": "RC_data8_Fe.pls", "bytes": 1, "sha256": "x"}, "answers": []}


ASSAYS = {"Al2O3": 3.0, "SiO2": 20.0, "CaO": 0.5, "MgO": 0.3, "TiO2": 0.2, "LOI": 9.0, "Fe": 44.6}


def _embedded(values):
    return {"Al2O3": values["Al2O3"], "SiO2 %": values["SiO2"], "CaO %": values["CaO"], "MgO %": values["MgO"],
            "TiO2 %": values["TiO2"], "LOI": values["LOI"], "Fe %": float(np.round(values["Fe"]))}


# R-718 ----------------------------------------------------------------------------------------------------------


def test_the_lineage_sources_are_pinned():
    manifest = json.loads((ROOT / "data" / "sources" / "manifest.json").read_text(encoding="utf-8"))
    pinned = {f["file"]: f for f in manifest["files"]}
    assert manifest["families"]["rocklea"]["license"] == "CC-BY-4.0"
    for name, (source_id, sha) in rocklea_spectral.FILES.items():
        entry = pinned[name]
        assert entry["family"] == "rocklea" and entry["sha256"] == sha and entry["bytes"] > 0
        assert entry["url"] == rocklea_spectral.COLLECTION + source_id


# R-719 ----------------------------------------------------------------------------------------------------------


def test_every_spectral_column_has_its_product_or_is_marked():
    assert {e["column"] for e in MAPPING["spectral"]} == set(rocklea_spectral.SPECTRAL)
    project = _project({"H1": {0.0: ASSAYS}})
    rows = [_row("H1", 0.0, _embedded(ASSAYS), {"Fe ox ai": 0.2, "hem/goe": 905.0})]
    lineage = spectral.lineage(project, _source(rows), MAPPING)
    assert all(e["status"] == "described" and e["Base algorithm"] for e in lineage["spectral"])
    hem = next(e for e in lineage["spectral"] if e["column"] == "hem/goe")
    assert hem["unit"].startswith("nm") and hem["values"]["n"] == 1 and hem["null"] == 0
    # A product the workbook lacks is undescribed; a column the mapping lacks is listed; unexported products listed.
    missing = _source(rows, products=[{"row": 12, "Product name": "Another product"}])
    lineage = spectral.lineage(project, missing, MAPPING)
    assert all(e["status"] == "undescribed" for e in lineage["spectral"])
    assert lineage["describedNotExported"] == ["Another product"]
    partial = copy.deepcopy(MAPPING)
    partial["spectral"] = partial["spectral"][1:]
    assert spectral.lineage(project, _source(rows), partial)["undescribedColumns"] == [MAPPING["spectral"][0]["column"]]


# R-720 ----------------------------------------------------------------------------------------------------------


def test_embedded_assays_are_identified_as_targets():
    project = _project({"H1": {0.0: ASSAYS, 1.0: {**ASSAYS, "Fe": 50.4}}})
    rows = [_row("H1", 0.0, _embedded(ASSAYS)),
            _row("H1", 1.0, {**_embedded(ASSAYS), "Fe %": 51.0, "SiO2 %": 21.0})]  # Fe off by one, SiO2 differs
    lineage = spectral.lineage(project, _source(rows), MAPPING)
    by = {e["column"]: e for e in lineage["embedded"]}
    assert by["Fe %"]["compared"] == 2 and by["Fe %"]["equal"] == 1  # 44.6 rounds to 45; 50.4 to 50, not 51
    assert by["SiO2 %"]["equal"] == 1 and by["Al2O3"]["equal"] == 2
    assert all(e["role"].startswith("target") for e in lineage["embedded"])


# R-721 ----------------------------------------------------------------------------------------------------------


def test_registration_is_classified_and_gates_the_pairing():
    depths = {d: {**ASSAYS, "SiO2": 20.0 + d} for d in (0.0, 1.0, 2.0, 3.0)}
    project = _project({"A": depths, "B": depths, "C": depths, "D": depths})
    shifted = {d: _embedded(depths[d + 1]) for d in (0.0, 1.0, 2.0)}
    rows = ([_row("A", d, _embedded(depths[d])) for d in (0.0, 1.0, 2.0)]
            + [_row("B", d, shifted[d]) for d in (0.0, 1.0, 2.0)]                      # one metre deeper
            + [_row("C", 0.0, {**_embedded(ASSAYS), "SiO2 %": 99.0})]                  # nothing matches
            + [_row("D", 0.0, {}), _row("E", 0.0, _embedded(ASSAYS))]                  # no assays; not in project
            + [_row("A", 2.0, _embedded(depths[2.0]))])                               # a duplicate key
    lineage = spectral.lineage(project, _source(rows), MAPPING)
    holes = lineage["registration"]["holes"]
    assert holes["A"]["status"] == "confirmed" and holes["B"]["status"] == "offset"
    assert holes["B"]["rows"] == {"offset +1 m": 3}
    assert holes["C"]["status"] == "unmatched" and holes["D"]["status"] == "no embedded assay"
    assert holes["E"]["status"] == "not in the canonical project"
    assert lineage["registration"]["duplicateKeys"] == [["A", 2.0]]
    # Pairing: only the confirmed hole's rows, never a duplicate key.
    supports_of = {(k[0], k[1]): v["support"] for k, v in spectral.canonical_assays(project).items()}
    rows_by_id = {sid: {"values": {"Fe": 40.0}} for sid in supports_of.values()}
    source = _source(rows)
    for r in source["rows"]:
        r["spectral"]["Fe ox ai"] = 0.2
    pairs, excluded = spectral._pairs(source, lineage, supports_of, rows_by_id, set(supports_of.values()),
                                      "Fe ox ai", "Fe")
    assert {p[1] for p in pairs} == {"A"} and len(pairs) == 2  # A at 0 and 1 m; A at 2 m is a duplicate key
    assert excluded["registration not confirmed"] == 5 and excluded["duplicate hole-depth key"] == 2


# R-722 ----------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def field(tmp_path_factory):
    folder, _ = authored_field.chain(tmp_path_factory.mktemp("field"), stages=(
        "preprocess", "dataset", "features", "train", "infer"), geochemistry=True)
    load = lambda name: json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
    return folder, {n: load(n) for n in ("project", "preprocessed", "dataset", "predictions")}


def _authored_source(data, rng):
    """An index that tracks Fe with noise, one row per one-metre support of the field, every hole confirmed."""
    rows = []
    for key, entry in spectral.canonical_assays(data["project"]).items():
        fe = entry["values"].get("Fe")
        index = None if fe is None else fe / 100 + rng.normal(0, 0.02)
        rows.append(_row(key[0], key[1], None, {"Fe ox ai": index}))
    return _source(rows)


def test_the_index_calibration_is_fitted_on_training_rows_only(field):
    _, data = field
    rng = np.random.default_rng(0)
    source = _authored_source(data, rng)
    holes = {r["hole"] for r in source["rows"]}
    lineage = {"registration": {"holes": {h: {"status": "confirmed"} for h in holes}, "duplicateKeys": []}}
    population = "authored-field-Fe-native"
    model = spectral.fit_index(data["project"], data["preprocessed"], data["dataset"], source, lineage, MAPPING,
                               population_id=population)
    assert model["train"]["rows"] > 0 and model["test"]
    assert np.all(np.diff(model["fit"]["y"]) >= -1e-12)  # monotone
    low, high = model["fit"]["x"][0], model["fit"]["x"][-1]
    beyond = [t for t in model["test"] if not low <= t["index"] <= high]
    assert all(t["prediction"] in (model["fit"]["y"][0], model["fit"]["y"][-1]) for t in beyond)
    # Changing every non-training truth leaves the fit unchanged.
    scheme = next(s for s in data["dataset"]["schemes"] if s["id"] == "hole-group")
    training = {h for h, s in scheme["assignment"].items() if s == "train"}
    changed = copy.deepcopy(data["preprocessed"])
    for r in changed["selections"]["rows"]:
        if r["geometry"][0] not in training and isinstance(r["value"], (int, float)):
            r["value"] = r["value"] * 3 + 7
    again = spectral.fit_index(data["project"], changed, data["dataset"], source, lineage, MAPPING,
                               population_id=population)
    assert again["fit"] == model["fit"] and again["test"] == model["test"]
    scores = spectral.score_index(model, data["project"], data["preprocessed"], data["dataset"], data["predictions"])
    assert scores["rows"] == len({t["id"] for t in model["test"]})
    assert scores["index"]["n"] == scores["ordinaryKriging"]["n"] == scores["trainingMean"]["n"] == scores["rows"]
    assert scores["index"]["rmse"] < scores["trainingMean"]["rmse"]  # the authored index tracks Fe
