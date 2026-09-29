"""The scenario matrix: every registered scenario, cell by cell, computed, verified or pending with its owner.

A cell is a method or variant scored in a family's metrics, a categorical run scored in its categorical metrics, a
stage output the scenario reads, a test that verifies an authored truth, a check recorded as passed in
``simulation-checks.json`` (S10 and S11, whose tests skip without MPSlib or CUDA), or a pending cell with the unit that
will compute it. Computed cells cite the metrics they come from by
hash, so a stale matrix is detectable. Nothing is marked computed without a metric behind it.
"""

from __future__ import annotations

import json
from pathlib import Path

from source_io import ROOT, stable_hash
from stages.estimators import METHODS

SCHEMA = "drillhole.scenarios/v1"
R1, R2, R5 = "rocklea-native-1m", "rocklea-composite-2m", "rocklea-composite-5m"
AB = "alberta-envelope-centre-cu-zn"
T = "tests/test_infer.py::"


def _m(family, scheme, population, method):
    return {"kind": "metric", "family": family, "scheme": scheme, "population": population, "method": method}


def _v(family, scheme, population, variant):
    return {"kind": "variant", "family": family, "scheme": scheme, "population": population, "variant": variant}


def _pending(owner, what):
    return {"kind": "pending", "owner": owner, "what": what}


def _artifact(family, stage, what):
    return {"kind": "artifact", "family": family, "stage": stage, "what": what}


def _test(gate):
    return {"kind": "test", "gate": gate}


def _categorical(family, scheme, prior, engine):
    return {"kind": "categorical", "family": family, "scheme": scheme, "prior": prior, "engine": engine}


def _receipt(check):
    return {"kind": "receipt", "check": check}


def _output(family, file, what):
    return {"kind": "output", "family": family, "file": file, "what": what}


def _output_summary(file: str, record: dict) -> dict:
    """The few numbers a matrix cell shows for a stage output of R12."""
    if file == "spectral-lineage.json":
        return {"registration": record["registration"]["counts"],
                "embeddedEqualShare": {e["column"]: e["share"] for e in record["embedded"]}}
    if file == "spectral-metrics.json":
        return {"rows": record["rows"], "indexRmse": record["index"]["rmse"],
                "ordinaryKrigingRmse": record["ordinaryKriging"]["rmse"]}
    return {"thresholds": record["thresholds"],
            "falseFlags": {m: record["alterations"]["unchanged"][m]["falseFlags"] for m in ("ae", "pca")}}


PRIORS = ("nw-high-strain", "gneiss-domes")
C = "tests/test_categorical.py::"


#: The learned methods of unit SD-7a, scored by evaluate beside the classical ones (stages/learned.py).
LEARNED = ("deepkriging", "kcn")
CELLS = {
    "R01": [_m("rocklea", "hole-group", R1, m) for m in ("nearest-neighbour", "inverse-distance", "ordinary-kriging")],
    "R02": [_artifact("rocklea", "preprocess", "one hole's samples, positions and composites"),
            _pending("SD-8", "the exported one-hole log view")],
    "R03": [_pending("SD-8", "the exported fence section")],
    "R04": [_m("rocklea", "hole-group", pop, "ordinary-kriging") for pop in (R1, R2, R5)],
    "R05": [_m("rocklea", "hole-group", R1, "ordinary-kriging"), _v("rocklea", "hole-group", R1, "isotropic")],
    "R06": [_v("rocklea", "hole-group", R1, "neighbourhood-small"), _m("rocklea", "hole-group", R1, "ordinary-kriging"),
            _v("rocklea", "hole-group", R1, "neighbourhood-large")],
    "R07": [_m("rocklea", "hole-group", R1, "ordinary-kriging"), _v("rocklea", "hole-group", R1, "integrated-support")],
    "R08": [_m("rocklea", "hole-group", R1, "ordinary-kriging"), _m("rocklea", "hole-group", R1, "ordinary-cokriging")],
    "R09": [_m("rocklea", "hole-group", R1, "ordinary-kriging"), _v("rocklea", "hole-group", R1, "sparse-primary")],
    "R10": [_m("rocklea", "hole-group", R1, m) for m in METHODS + LEARNED],
    "R11": [_m("rocklea", "spatial-margin", R1, m) for m in METHODS + LEARNED],
    "R12": [_output("rocklea", "spectral-lineage.json", "the spectral export's lineage: products, embedded assays, "
                                                        "registration"),
            _output("rocklea", "spectral-metrics.json", "the iron-oxide index calibrated on training holes, beside OK"),
            _output("rocklea", "geochemistry-metrics.json", "the autoencoder review and its PCA reference")],
    "A01": [_artifact("alberta", "ingest", "support QA: waterfall and issues")],
    "A02": [_artifact("alberta", "preprocess", "176 envelope positions on 22 collar projections"),
            _pending("SD-8", "the exported envelope view")],
    "A03": [_m("alberta", "hole-group", AB, "ordinary-kriging"), _m("alberta", "hole-group", AB, "ordinary-cokriging")],
    "A04": [{"kind": "categorical-mapping", "family": "alberta"}, _test(C + "test_the_mapping_applies_declared_rules_only")],
    "A05": [_artifact("alberta", "preprocess", "envelope and log overlay")],
    "A06": [_m("alberta", "hole-group", AB, m) for m in METHODS],
    "A07": [_categorical("alberta", "hole-group", prior, "snesim") for prior in PRIORS],
    "A08": [_categorical("alberta", "hole-group", prior, "direct-sampling") for prior in PRIORS],
    "S01": [_test("tests/test_import.py::test_analytic_trajectories"),
            _test("tests/test_import.py::test_dip_conventions_give_the_same_trace")],
    "S02": [_test("tests/test_import.py::test_analytic_trajectories"),
            _test("tests/test_import.py::test_conflicting_survey_depths_block_the_hole")],
    "S03": [_test("tests/test_import.py::test_overlay_fragments_conserve_parent_lengths"),
            _test("tests/test_import.py::test_composite_fixtures")],
    "S04": [_test("tests/test_import.py::test_invalid_intervals_are_excluded_by_record"),
            _test("tests/test_import.py::test_states_are_distinct_and_eligibility_is_versioned"),
            _test("tests/test_import.py::test_overlimit_reassay_is_selected"),
            _test("tests/test_import.py::test_result_selection_is_explicit")],
    "S05": [_test(T + "test_constant_and_polynomial_truths")],
    "S06": [_test(T + "test_rotation_invariance")],
    "S07": [_test(T + "test_cokriging_reduces_and_matches_the_analytic_case")],
    "S08": [_test(T + "test_invalid_models_and_systems_fail_honestly")],
    "S09": [_test(T + "test_block_quadrature_converges")],
    "S10": [_test(C + "test_snesim_reproduces_small_pattern_frequencies"), _receipt("s10")],
    "S11": [_test(C + "test_direct_sampling_cpu_and_cuda_agree_in_the_product"), _receipt("s11")],
    "S12": [_test("tests/test_import.py::test_split_and_reordered_files_equal_the_consolidated_import"),
            _test("tests/test_import.py::test_an_interrupted_import_leaves_the_previous_project"),
            _pending("SD-8", "export and re-import round trip")],
}


def _gate_exists(gate: str) -> bool:
    path, _, name = gate.partition("::")
    file = ROOT / path
    return file.is_file() and f"def {name}" in file.read_text(encoding="utf-8")


def _summary(scores: dict) -> dict:
    return {k: scores.get(k) for k in ("n", "rmse", "mae", "bias")}


def _read(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def resolve(cell, metrics, out_dir) -> dict:
    kind = cell["kind"]
    if kind == "pending":
        return {**cell, "status": "pending"}
    if kind == "categorical-mapping":
        models = _read(Path(out_dir) / cell["family"] / "categorical-models.json")
        if not models or not models.get("eligible"):
            return {**cell, "status": "missing", "reason": "no eligible categorical models"}
        return {**cell, "status": "computed", "summary": {"mappingId": models["mapping"]["mappingId"],
                                                          "counts": models["mapping"]["counts"]}}
    if kind == "categorical":
        record = _read(Path(out_dir) / cell["family"] / "categorical-metrics.json")
        if not record or not record.get("eligible"):
            return {**cell, "status": "missing", "reason": "no categorical metrics for the family"}
        try:
            scheme = next(s for s in record["schemes"] if s["scheme"] == cell["scheme"])
            run = next(r for r in scheme["runs"] if (r["prior"], r["engine"]) == (cell["prior"], cell["engine"]))
        except StopIteration:
            return {**cell, "status": "missing", "reason": "not in the categorical metrics"}
        return {**cell, "status": "computed", "metricsSha256": stable_hash(record),
                "summary": {**{k: run["all"].get(k) for k in ("n", "brier", "logScore", "accuracy")},
                            "brierSkill": run["brierSkill"]}}
    if kind == "output":
        record = _read(Path(out_dir) / cell["family"] / cell["file"])
        if not record or record.get("eligible") is False:
            return {**cell, "status": "missing", "reason": f"no {cell['file']} for the family"}
        return {**cell, "status": "computed", "outputSha256": stable_hash(record),
                "summary": _output_summary(cell["file"], record)}
    if kind == "receipt":
        receipt = _read(Path(out_dir) / "simulation-checks.json")
        check = (receipt or {}).get(cell["check"])
        if not check or not check.get("passed"):
            return {**cell, "status": "missing", "reason": (check or {}).get("reason", "no passing receipt")}
        return {**cell, "status": "computed", "receiptSha256": stable_hash(receipt)}
    if kind == "test":
        return {**cell, "status": "verified" if _gate_exists(cell["gate"]) else "missing"}
    if kind == "artifact":
        name = {"ingest": "project.json", "preprocess": "preprocessed.json"}[cell["stage"]]
        path = Path(out_dir) / cell["family"] / name
        return {**cell, "status": "computed" if path.is_file() else "missing"}
    family = metrics.get(cell["family"])
    if family is None:
        return {**cell, "status": "missing", "reason": "no metrics for the family"}
    try:
        scheme = next(s for s in family["schemes"] if s["scheme"] == cell["scheme"])
        population = next(p for p in scheme["populations"] if p["population"] == cell["population"])
        if kind == "metric":
            entry = population["methods"][cell["method"]]
            summary = _summary(entry["common"]) if "common" in entry else {"coverage": entry["coverage"]}
        else:
            summary = _summary(population["variants"][cell["variant"]]["scores"])
    except (StopIteration, KeyError):
        return {**cell, "status": "missing", "reason": "not in the metrics"}
    return {**cell, "status": "computed", "metricsSha256": stable_hash(family), "summary": summary}


def scenario_matrix(out_dir) -> dict:
    registry = json.loads((ROOT / "data" / "scenarios" / "registry.json").read_text(encoding="utf-8"))
    metrics = {}
    for family in ("rocklea", "alberta"):
        path = Path(out_dir) / family / "metrics.json"
        if path.is_file():
            metrics[family] = json.loads(path.read_text(encoding="utf-8"))
    scenarios, counts = [], {"computed": 0, "verified": 0, "pending": 0, "missing": 0}
    pending_by_owner: dict = {}
    for s in registry["scenarios"]:
        cells = [resolve(c, metrics, out_dir) for c in CELLS[s["id"]]]
        for c in cells:
            counts[c["status"]] += 1
            if c["status"] == "pending":
                pending_by_owner[c["owner"]] = pending_by_owner.get(c["owner"], 0) + 1
        statuses = {c["status"] for c in cells}
        state = ("missing" if "missing" in statuses else "complete" if statuses <= {"computed", "verified"}
                 else "partial" if statuses & {"computed", "verified"} else "pending")
        scenarios.append({"id": s["id"], "family": s["family"], "title": s["title"], "question": s["question"],
                          "state": state, "cells": cells})
    return {"schema": SCHEMA, "counts": counts, "pendingByOwner": dict(sorted(pending_by_owner.items())),
            "scenarios": scenarios}
