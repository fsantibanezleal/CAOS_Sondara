#!/usr/bin/env python3
"""Validate every ingested canonical project against the drillhole.project/v2 contract.

    python scripts/check_artifacts.py [--derived build/derived]

For each ``<family>/project.json`` with its ``summary.json`` the check verifies: the JSON Schema in
``schemas/project.schema.json``; the summary hash and counts against the project; unique identifiers per table; every
survey, trajectory, support and geology record on a known collar; every determination on a known support and analyte;
support geometry consistent with its kind; determination states (a measured value with '=', censoring as a qualifier
with a positive limit and no value, other states with neither); controls without supports; geology intervals and
events; and exclusions that name existing records. When a family has been preprocessed, it also checks that output against its project: the input hash, one
trajectory per collar, a finite position for every positioned support and none for an unknown one, composite
statuses, means only where covered, per-hole conservation of every grade-length integral, population members, and
overlay coverage and proportions. It exits nonzero and lists every violation, so a changed stage cannot write an
output the later stages would misread.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data-pipeline"))

from source_io import stable_hash

SCHEMA = "drillhole.project/v2"
SCHEMA_FILE = ROOT / "schemas" / "project.schema.json"
TABLES = ("collars", "surveys", "trajectories", "analytes", "supports", "determinations", "geology", "qc",
          "exclusions", "issues")
CENSORED = {"censored-below": "<", "censored-above": ">"}


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _schema_errors(project: dict, limit: int = 50) -> list[str]:
    import jsonschema

    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))
    errors = []
    for error in validator.iter_errors(project):
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"schema: {where}: {error.message[:160]}")
        if len(errors) >= limit:
            errors.append("schema: stopped after the first violations")
            break
    return errors


def _determination_errors(d: dict, label: str) -> list[str]:
    state, value, qualifier = d.get("state"), d.get("value"), d.get("qualifier")
    if state == "measured":
        if not _finite(value) or qualifier != "=":
            return [f"{label}: a measured result has a finite value and qualifier '='"]
    elif state in CENSORED:
        if value is not None or qualifier != CENSORED[state] or not (_finite(d.get("detectionLimit"))
                                                                     and d["detectionLimit"] > 0):
            return [f"{label}: a censored result keeps no value, its qualifier and a positive limit"]
    elif value is not None or qualifier is not None:
        return [f"{label}: a {state} result carries no value and no qualifier"]
    return []


def check_project(project: dict) -> list[str]:
    """Return every violation of one canonical project: the schema first, then the referential rules."""
    errors = _schema_errors(project)
    if errors:
        return errors
    frames = {f["id"] for f in project["frames"]}

    def unique(table: str) -> set:
        ids = [row["id"] for row in project[table]]
        if len(set(ids)) != len(ids):
            errors.append(f"{table}: duplicate ids")
        return set(ids)

    collars = unique("collars")
    analytes = unique("analytes")
    supports = unique("supports")
    determinations = unique("determinations")
    surveys = unique("surveys")
    geology = unique("geology")
    unique("qc")
    if not collars:
        errors.append("no collars")
    for c in project["collars"]:
        if c["frameId"] not in frames:
            errors.append(f"collar {c['id']}: unknown frame {c['frameId']!r}")
        if c["totalDepth"] is not None and c["totalDepth"] <= 0:
            errors.append(f"collar {c['id']}: total depth must be positive or null")
    for table in ("surveys", "trajectories", "supports", "geology"):
        orphans = {r["holeId"] for r in project[table]} - collars
        if orphans:
            errors.append(f"{table}: records on unknown collars {sorted(orphans)[:5]}")
    if sorted(t["holeId"] for t in project["trajectories"]) != sorted(collars):
        errors.append("every collar needs exactly one trajectory")
    for s in project["supports"]:
        kind, a, b, at = s["kind"], s["fromMd"], s["toMd"], s["atMd"]
        if kind in ("interval", "sampling-envelope"):
            if not (_finite(a) and _finite(b) and 0 <= a < b and at is None):
                errors.append(f"support {s['id']}: {kind} needs 0 <= from < to")
            if kind == "sampling-envelope" and s["samplingMeasure"] != "unknown":
                errors.append(f"support {s['id']}: an envelope's sampling measure is unknown")
        elif kind == "point":
            if not (_finite(at) and at >= 0 and a is None and b is None):
                errors.append(f"support {s['id']}: a point needs atMd only")
        elif not (a is None and b is None and at is None):
            errors.append(f"support {s['id']}: unknown support must carry no depths")
    for d in project["determinations"]:
        if d["supportId"] not in supports:
            errors.append(f"determination {d['id']}: unknown support")
        if d["analyteId"] not in analytes:
            errors.append(f"determination {d['id']}: unknown analyte")
        errors += _determination_errors(d, f"determination {d['id']}")
        if len(errors) > 200:
            errors.append("stopped after 200 violations")
            return errors
    for q in project["qc"]:
        for d in q["determinations"]:
            if d["supportId"] is not None:
                errors.append(f"qc {q['id']}: a control has no support")
            errors += _determination_errors(d, f"qc {q['id']}")
    for g in project["geology"]:
        if g["kind"] == "interval" and not (_finite(g["fromMd"]) and _finite(g["toMd"]) and g["fromMd"] < g["toMd"]
                                            and g["atMd"] is None):
            errors.append(f"geology {g['id']}: an interval needs from < to")
        if g["kind"] == "event" and not (_finite(g["atMd"]) and g["fromMd"] is None and g["toMd"] is None):
            errors.append(f"geology {g['id']}: an event has one depth")
    known = {"supports": supports, "determinations": determinations, "surveys": surveys, "geology": geology,
             "collars": collars}
    for x in project["exclusions"]:
        if x["rowId"] not in known.get(x["table"], set()):
            errors.append(f"exclusion of {x['table']}/{x['rowId']}: no such record")
    return errors


STATUSES = {"full", "residual", "insufficient-coverage"}


def _finite_xyz(value) -> bool:
    return isinstance(value, list) and len(value) == 3 and all(_finite(v) for v in value)


def check_preprocessed(pre: dict, project: dict) -> list[str]:
    """Return every violation of a preprocess output against the project it was built from."""
    errors: list[str] = []
    if pre.get("schema") != "drillhole.preprocessed/v1":
        errors.append(f"preprocessed schema is {pre.get('schema')!r}")
    if pre.get("inputProjectSha256") != stable_hash(project):
        errors.append("preprocessed output was built from another project (input hash differs)")
    collars = {c["id"] for c in project["collars"]}
    if {t.get("holeId") for t in pre.get("trajectories", [])} != collars:
        errors.append("every collar needs exactly one desurveyed trajectory")
    for t in pre.get("trajectories", []):
        if not t.get("stations") or not all(_finite_xyz(s.get("position")) for s in t["stations"]):
            errors.append(f"trajectory {t.get('holeId')}: stations without finite positions")
        if not _finite_xyz(t.get("endPosition")):
            errors.append(f"trajectory {t.get('holeId')}: no finite end position")
    supports = {s["id"]: s for s in project["supports"]}
    positioned = {p["supportId"]: p for p in pre.get("positions", [])}
    for sid, s in supports.items():
        p = positioned.get(sid)
        if s["kind"] == "unknown":
            if p and any(k in p for k in ("from", "mid", "to", "at")):
                errors.append(f"support {sid}: an unknown support was given a position")
        elif p is None:
            errors.append(f"support {sid}: no position")
        elif s["kind"] == "point":
            if not _finite_xyz(p.get("at")):
                errors.append(f"support {sid}: point without a finite position")
        elif not all(_finite_xyz(p.get(k)) for k in ("from", "mid", "to")):
            errors.append(f"support {sid}: interval without finite start, mid and end positions")
    determinations = {d["id"]: d for d in project["determinations"]}
    excluded = {x["rowId"] for x in project["exclusions"] if x["table"] == "determinations"}
    source: dict = {}
    for r in pre.get("selections", {}).get("rows", []):
        d = determinations.get(r["determinationId"])
        if d is None or d["state"] != "measured" or d["sampleRole"] != "original" or d["id"] in excluded:
            errors.append(f"selection of {r['determinationId']}: not a measured, original, non-excluded result")
            continue
        if r["representative"] not in supports:
            errors.append(f"selection of {r['determinationId']}: representative is not a project support")
        hole, a, b = r["geometry"]
        if r["kind"] == "interval":
            source[(hole, r["analyteId"])] = source.get((hole, r["analyteId"]), 0.0) + r["value"] * (b - a)
    composite_ids = set()
    if "composites" in pre:
        minimum = pre["composites"]["minCoverage"]
        numerators: dict = {}
        for row in pre["composites"]["rows"]:
            composite_ids.add(row["id"])
            if row["status"] not in STATUSES:
                errors.append(f"composite {row['id']}: status {row['status']!r}")
                continue
            length = row["toMd"] - row["fromMd"]
            if row["status"] == "full" and (abs(length - row["length"]) > 1e-9 or row["coverage"] < minimum - 1e-12):
                errors.append(f"composite {row['id']}: a full composite has the declared length and enough coverage")
            if row["status"] == "residual" and not (length < row["length"] and row["coverage"] >= minimum - 1e-12):
                errors.append(f"composite {row['id']}: a residual is shorter with enough coverage")
            for analyte, value in row["values"].items():
                share = row["coverageByAnalyte"][analyte]
                covered = share > 0 and share >= minimum - 1e-12  # GeoCond: some valid length and enough coverage
                if (value is not None and _finite(value)) != covered:
                    errors.append(f"composite {row['id']}: {analyte} carries a mean only where it is covered")
            if any(pid not in supports for pid, _ in row["parents"]):
                errors.append(f"composite {row['id']}: parent is not a project support")
            for analyte, value in row["numerators"].items():
                key = (row["holeId"], row["length"], analyte)
                numerators[key] = numerators.get(key, 0.0) + value
        for (hole, _length, analyte), total in numerators.items():
            expected = source.get((hole, analyte), 0.0)
            if abs(total - expected) > 1e-9 * max(1.0, abs(expected)):
                errors.append(f"composites of {hole} do not conserve the {analyte} grade-length integral")
    fragments = pre.get("fragments")
    if fragments is not None and fragments["parentLengthMaxError"] > 1e-9:
        errors.append("overlay fragments do not add up to their parent intervals")
    known = set(supports) | composite_ids
    for population in pre.get("populations", []):
        if population.get("count") != len(population.get("members", [])):
            errors.append(f"population {population.get('id')}: count differs from its members")
        if any(m not in known for m in population.get("members", [])):
            errors.append(f"population {population.get('id')}: a member is neither a support nor a composite")
        if not population.get("rule"):
            errors.append(f"population {population.get('id')}: no rule")
    for row in pre.get("overlay", {}).get("rows", []):
        for name in ("anyLog", "lithoUnit", "rockType"):
            cell = row[name]
            if not 0 <= cell["coverage"] <= 1 + 1e-12:
                errors.append(f"overlay {row['supportId']}: {name} coverage outside [0, 1]")
            if cell["proportions"] and abs(sum(cell["proportions"].values()) - 1) > 1e-9:
                errors.append(f"overlay {row['supportId']}: {name} proportions do not sum to one")
    return errors


def check_dataset(dataset: dict, project: dict, pre: dict) -> list[str]:
    """Return every violation of a dataset output against the project and preprocessed output it splits."""
    from stages.dataset import SPLITS, derived_tables, members

    errors = []
    if (dataset.get("inputProjectSha256"), dataset.get("inputPreprocessedSha256")) != (stable_hash(project),
                                                                                      stable_hash(pre)):
        return ["dataset was built from other inputs"]
    if not dataset["eligible"]:
        return [] if dataset.get("reason") else ["an ineligible family states no reason"]
    holes = {s["holeId"] for s in project["supports"]}
    tables = derived_tables(project, pre)
    for scheme in dataset["schemes"]:
        assignment = scheme["assignment"]
        buffered = set(scheme.get("excludedByBuffer", []))
        if set(assignment) | buffered != holes or set(assignment) & buffered:
            errors.append(f"scheme {scheme['id']}: every hole needs exactly one split or the buffer")
        if set(assignment.values()) - set(SPLITS):
            errors.append(f"scheme {scheme['id']}: unknown split names")
        for name, table in tables.items():
            split = members(table, assignment)
            if scheme["membership"].get(name, {}).get("sha256") != stable_hash(split):
                errors.append(f"scheme {scheme['id']}: the {name} membership record is stale")
    return errors


def check_features(features: dict, dataset: dict) -> list[str]:
    """Return every violation of a features output against the dataset it was computed from."""
    if features.get("inputDatasetSha256") != stable_hash(dataset):
        return ["features were computed from another dataset"]
    errors = []
    for scheme in features.get("schemes", []):
        for population in scheme["populations"]:
            variograms = [v for a in population["analytes"].values() for v in a["variograms"]]
            variograms += [v for vs in population["cross"].values() for v in vs]
            for v in variograms:
                if len(v["edges"]) != len(v["counts"]) + 1 or any(c < 0 for c in v["counts"]):
                    errors.append(f"{scheme['scheme']}/{population['population']}/{v['name']}: malformed bins")
                if any((c == 0) != (value is None) for c, value in zip(v["counts"], v["values"], strict=True)):
                    errors.append(f"{scheme['scheme']}/{population['population']}/{v['name']}: a value needs pairs")
    return errors


PREDICTION_STATUSES = {"estimated", "uninformed", "failed", "prior-only"}


def check_models(models: dict, features: dict) -> list[str]:
    """Return every violation of a models output: its input, rebuildable models, and a selection by validation."""
    from stages.models import model_from, transform_from

    if models.get("inputFeaturesSha256") != stable_hash(features):
        return ["models were fitted on other features"]
    errors = []
    for scheme in models.get("schemes", []):
        for p in scheme["populations"]:
            label = f"{scheme['scheme']}/{p['population']}"
            if p["status"] != "fitted":
                if not p.get("reason"):
                    errors.append(f"{label}: a population without a model states no reason")
                continue
            admissible = [c for c in p["candidates"] if c["status"] == "fitted" and c["validationRmse"] is not None
                          and c["validationCoverage"] >= models["candidates"]["minValidationCoverage"]]
            best = min(admissible, key=lambda c: (c["validationRmse"], c["objective"]), default=None)
            if best is None or best["validationRmse"] != p["selected"]["validationRmse"] or best["model"] != p["model"]:
                errors.append(f"{label}: the selected model is not the lowest validation error")
            try:
                model_from(p["model"])
                for part in ("universal", "lmc", "gaussian"):
                    if p.get(part, {}).get("status") == "fitted":
                        model_from(p[part]["model"])
                if p.get("gaussian", {}).get("status") == "fitted":
                    transform_from(p["gaussian"]["transform"])
                for t in p["indicator"]["thresholds"]:
                    if t["status"] == "fitted":
                        model_from(t["model"])
            except Exception as error:  # noqa: BLE001 - any rebuild failure is a contract violation
                errors.append(f"{label}: a stored model does not rebuild ({error})")
            thresholds = [t["threshold"] for t in p["indicator"]["thresholds"]]
            if thresholds != sorted(set(thresholds)):
                errors.append(f"{label}: indicator thresholds are not strictly increasing")
    return errors


def check_predictions(predictions: dict, models: dict) -> list[str]:
    """Return every violation of a predictions output: its input, and every method on every target with a status."""
    from stages.estimators import METHODS

    if predictions.get("inputModelsSha256") != stable_hash(models):
        return ["predictions come from other models"]
    errors = []
    for scheme in predictions.get("schemes", []):
        for p in scheme["populations"]:
            label = f"{scheme['scheme']}/{p['population']}"
            if not p["targets"]:
                continue
            if set(p["methods"]) != set(METHODS):
                errors.append(f"{label}: methods {sorted(set(METHODS) - set(p['methods']))} are missing")
            for method, result in p["methods"].items():
                if [r["id"] for r in result["rows"]] != p["targets"]:
                    errors.append(f"{label}/{method}: rows do not match the targets")
                for r in result["rows"]:
                    if r["status"] not in PREDICTION_STATUSES:
                        errors.append(f"{label}/{method}: status {r['status']!r}")
                    elif r["status"] == "estimated" and method != "multiple-indicator" and not _finite(r["mean"]):
                        errors.append(f"{label}/{method}: an estimated target has no finite mean")
                    elif r["status"] != "estimated" and r["status"] != "prior-only" and not r.get("reason"):
                        errors.append(f"{label}/{method}: a target without an estimate states no reason")
    return errors


def check_metrics(metrics: dict, predictions: dict) -> list[str]:
    """Return every violation of a metrics output: its input, and every method scored for every population."""
    from stages.estimators import METHODS

    if metrics.get("inputPredictionsSha256") != stable_hash(predictions):
        return ["metrics were computed from other predictions"]
    errors = []
    predicted = {(s["scheme"], p["population"]): p for s in predictions.get("schemes", []) for p in s["populations"]}
    for scheme in metrics.get("schemes", []):
        for p in scheme["populations"]:
            label = f"{scheme['scheme']}/{p['population']}"
            source = predicted.get((scheme["scheme"], p["population"]))
            if source is None:
                errors.append(f"{label}: no such predictions")
                continue
            if not source["methods"]:
                continue
            expected = set(METHODS)
            if p.get("learned", {}).get("status") in ("fitted", "constant"):
                expected |= set(LEARNED_METHODS)
            if expected - set(p["methods"]):
                errors.append(f"{label}: methods {sorted(expected - set(p['methods']))} are not scored")
            if set(p["methods"]) - expected:
                errors.append(f"{label}: methods {sorted(set(p['methods']) - expected)} are scored without their "
                              "predictions")
            for method, entry in p["methods"].items():
                common = entry.get("common")
                covered = None if common is None else common.get("n", 0) + common.get("classicalCommonMissed", 0)
                if common is not None and covered != p["commonTargets"]:
                    errors.append(f"{label}/{method}: common scores cover {covered} of {p['commonTargets']}")
    return errors


LEARNED_METHODS = ("deepkriging", "kcn")


def check_learned_models(models: dict, folder: Path, dataset: dict, features: dict) -> list[str]:
    """The learned fits: inputs, every configuration of the frozen search with its three seeds and weights, the
    selection rule, the controls."""
    from learned.contracts import SEEDS

    if models.get("inputDatasetSha256") != stable_hash(dataset):
        return ["learned-models.json was fitted on another dataset"]
    if models.get("inputFeaturesSha256") != stable_hash(features):
        return ["learned-models.json was fitted on other features"]
    errors = []

    def fits_ok(label, fits):
        if sorted(f["seed"] for f in fits) != sorted(SEEDS):
            errors.append(f"{label}: seeds {[f['seed'] for f in fits]}, expected {list(SEEDS)}")
        for f in fits:
            weights = folder / f["folder"] / "weights.pt"
            if not weights.is_file() or hashlib.sha256(weights.read_bytes()).hexdigest() != f["weightsSha256"]:
                errors.append(f"{label}/seed-{f['seed']}: weights missing or not matching their record")

    for scheme in models.get("schemes", []):
        for p in scheme["populations"]:
            if p.get("status") != "fitted":
                continue
            for method in LEARNED_METHODS:
                label = f"{scheme['scheme']}/{p['population']}/{method}"
                entry = p["methods"][method]
                search = [c["id"] for c in models["search"][method]]
                if [e["config"]["id"] for e in entry["configurations"]] != search:
                    errors.append(f"{label}: the configurations differ from the frozen search")
                for e in entry["configurations"]:
                    fits_ok(f"{label}/{e['config']['id']}", e["fits"])
                best = min(entry["configurations"], key=lambda e: (
                    sum(f["bestValidationObjective"] for f in e["fits"]) / len(e["fits"]), e["fits"][0]["parameters"],
                    search.index(e["config"]["id"])))
                if best["config"]["id"] != entry["selected"]:
                    errors.append(f"{label}: selected {entry['selected']}, the rule gives {best['config']['id']}")
                controls = {"shuffled-labels"} | ({"coordinate-only"} if method == "deepkriging" else set())
                if set(entry["controls"]) != controls:
                    errors.append(f"{label}: controls {sorted(entry['controls'])}, expected {sorted(controls)}")
                for name, fits in entry["controls"].items():
                    fits_ok(f"{label}/{name}", fits)
    return errors


def check_learned_predictions(learned: dict, models: dict, predictions: dict, folder: Path) -> list[str]:
    """The learned predictions: inputs, the classical targets, every row predicted or given a reason, the ensemble
    mean, and every export on disk, audited, with its parity inside the tolerance."""
    if learned.get("inputLearnedModelsSha256") != stable_hash(models):
        return ["learned-predictions.json came from other learned models"]
    errors = []
    classical = {(s["scheme"], p["population"]): p for s in predictions.get("schemes", []) for p in s["populations"]}
    for scheme in learned.get("schemes", []):
        for p in scheme["populations"]:
            label = f"{scheme['scheme']}/{p['population']}"
            source = classical.get((scheme["scheme"], p["population"]))
            if source is None or source["targets"] != p["targets"] or \
                    source["calibrationTargets"] != p["calibrationTargets"]:
                errors.append(f"{label}: learned targets differ from the classical targets")
                continue
            if p["status"] not in ("fitted", "constant"):
                continue
            for method in LEARNED_METHODS:
                record = p["methods"].get(method)
                if record is None:
                    errors.append(f"{label}/{method}: no predictions")
                    continue
                rows = record["rows"] + record["calibrationRows"]
                if [r["id"] for r in rows] != p["targets"] + p["calibrationTargets"]:
                    errors.append(f"{label}/{method}: rows do not follow the targets")
                for r in rows:
                    if r["status"] == "estimated":
                        if not _finite(r["mean"]) or r["variance"] is not None:
                            errors.append(f"{label}/{method}/{r['id']}: an estimate needs a finite mean, no variance")
                        elif r.get("seeds") and abs(sum(r["seeds"]) / len(r["seeds"]) - r["mean"]) > 1e-9 * max(
                                1.0, abs(r["mean"])):
                            errors.append(f"{label}/{method}/{r['id']}: the mean is not the seed mean")
                    elif r["status"] != "uninformed" or not r.get("reason"):
                        errors.append(f"{label}/{method}/{r['id']}: status {r['status']} without a reason")
                if p["status"] == "fitted":
                    errors += _check_exports(label, method, record.get("exports", []), folder)
    return errors


def _check_exports(label, method, exports, folder) -> list[str]:
    from learned.contracts import SEEDS
    from learned.exporting import audit_model

    errors = []
    if sorted(e["seed"] for e in exports) != sorted(SEEDS):
        return [f"{label}/{method}: exports for seeds {[e['seed'] for e in exports]}, expected {list(SEEDS)}"]
    for e in exports:
        path = folder / e["folder"] / "model.onnx"
        try:
            audit = audit_model(path)
        except (OSError, ValueError) as error:
            errors.append(f"{label}/{method}/seed-{e['seed']}: {error}")
            continue
        if audit["sha256"] != e["model"]["sha256"]:
            errors.append(f"{label}/{method}/seed-{e['seed']}: the model file does not match its record")
        parity = e["parity"]
        worst = max(parity["onnxCpuMaxAbsolute"], parity["torchCudaMaxAbsolute"] or 0.0)
        if worst > parity["tolerance"]:
            errors.append(f"{label}/{method}/seed-{e['seed']}: parity {worst:.3g} over {parity['tolerance']:.3g}")
    return errors


def check_learned(folder: Path) -> list[str]:
    """The learned chain of a family folder, as far as its outputs go (needs the .venv-gpu packages)."""
    path = folder / "learned-models.json"
    if not path.is_file():
        return []
    models = json.loads(path.read_text(encoding="utf-8"))
    if not models.get("eligible"):
        return []
    try:
        import learned.exporting  # noqa: F401
    except ImportError as error:
        return [f"learned outputs exist but cannot be checked without PyTorch and onnx ({error}); use .venv-gpu"]
    load = lambda name: json.loads((folder / name).read_text(encoding="utf-8"))
    errors = check_learned_models(models, folder, load("dataset.json"), load("features.json"))
    if (folder / "learned-predictions.json").is_file():
        errors += check_learned_predictions(load("learned-predictions.json"), models, load("predictions.json"), folder)
    return errors


def check_scenarios(matrix: dict, out_dir: Path) -> list[str]:
    """Return every violation of the scenario matrix: coverage of the registry, owners, and fresh metric hashes."""
    registry = json.loads((ROOT / "data" / "scenarios" / "registry.json").read_text(encoding="utf-8"))
    errors = []
    if [s["id"] for s in matrix["scenarios"]] != [s["id"] for s in registry["scenarios"]]:
        errors.append("the matrix does not list the registered scenarios in order")
    current = {}
    for family in ("rocklea", "alberta"):
        path = Path(out_dir) / family / "metrics.json"
        if path.is_file():
            current[family] = stable_hash(json.loads(path.read_text(encoding="utf-8")))
    for s in matrix["scenarios"]:
        for c in s["cells"]:
            if c["status"] == "missing":
                errors.append(f"{s['id']}: a cell is missing ({c.get('reason', c['kind'])})")
            if c["status"] == "pending" and not c.get("owner"):
                errors.append(f"{s['id']}: a pending cell names no owner")
            if c["status"] == "computed" and c["kind"] in ("metric", "variant") \
                    and c.get("metricsSha256") != current.get(c["family"]):
                errors.append(f"{s['id']}: a computed cell cites stale metrics")
            if c["status"] == "computed" and c["kind"] == "categorical":
                path = Path(out_dir) / c["family"] / "categorical-metrics.json"
                now = stable_hash(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else None
                if c.get("metricsSha256") != now:
                    errors.append(f"{s['id']}: a computed cell cites stale categorical metrics")
    return errors


def _array_sha(array) -> str:
    import numpy as np

    a = np.ascontiguousarray(array)
    return hashlib.sha256(f"{a.dtype}{a.shape}".encode() + a.tobytes()).hexdigest()


def check_categorical_models(models: dict, folder: Path, project: dict | None = None,
                             dataset: dict | None = None) -> list[str]:
    """Return every violation of a categorical models output: inputs, a mapping gap, the conditioning, the TIs."""
    import numpy as np

    errors = []
    if project is not None and models.get("inputProjectSha256") != stable_hash(project):
        errors.append("categorical models were built from another project")
    if dataset is not None and models.get("inputDatasetSha256") != stable_hash(dataset):
        errors.append("categorical models were built from another dataset")
    if not models.get("eligible"):
        return errors if models.get("reason") else [*errors, "an ineligible categorical lane states no reason"]
    codes = {c["code"] for c in models["categories"]}
    rows = models["mapping"]["rows"]
    if project is not None and sorted(r["geologyId"] for r in rows) != sorted(g["id"] for g in project["geology"]):
        errors.append("the mapping does not cover every geology row exactly once")
    for r in rows:
        if r["category"] is None and not r["reason"]:
            errors.append(f"{r['geologyId']}: unmapped without a reason")
        if r["reason"] == "no rule assigns this code":
            errors.append(f"{r['geologyId']}: no rule assigns the code {r['codes']}")
        if r["category"] is not None and r["category"] not in codes:
            errors.append(f"{r['geologyId']}: category {r['category']} is not declared")
    shape = tuple(models["grid"]["shape"])
    for s in models["schemes"]:
        hard = s["conditioning"]["hard"]
        cells = [tuple(h["cell"]) for h in hard]
        if len(set(cells)) != len(cells):
            errors.append(f"{s['scheme']}: a cell is conditioned twice")
        if any(not all(0 <= c[i] < shape[i] for i in range(3)) for c in cells):
            errors.append(f"{s['scheme']}: a conditioning cell lies outside the grid")
        if any(h["category"] not in codes for h in hard):
            errors.append(f"{s['scheme']}: a conditioning category is not declared")
        if any(len(c["candidates"]) < 2 for c in s["conditioning"]["conflicts"]):
            errors.append(f"{s['scheme']}: a conflict has fewer than two candidates")
        for image in s["trainingImages"]:
            file = folder / image["file"]
            if not file.is_file():
                errors.append(f"{image['file']} is missing")
                continue
            ti = np.load(file)
            if hashlib.sha256(np.ascontiguousarray(ti).tobytes()).hexdigest() != image["sha256"]:
                errors.append(f"{image['file']} does not match its record")
            if ti.shape[2] != shape[2]:
                errors.append(f"{image['file']} is not as deep as the grid")
    return errors


def check_categorical_predictions(predictions: dict, models: dict, folder: Path) -> list[str]:
    """Return every violation of a categorical predictions output: its input, every run present, files, hard data."""
    import numpy as np

    if predictions.get("inputCategoricalModelsSha256") != stable_hash(models):
        return ["categorical predictions come from other models"]
    if not predictions.get("eligible"):
        return [] if predictions.get("reason") else ["ineligible categorical predictions state no reason"]
    errors = []
    expected = {(s["scheme"], i["prior"], e) for s in models["schemes"] for i in s["trainingImages"]
                for e in predictions["engines"]}
    got = {(r["scheme"], r["prior"], r["engine"]) for r in predictions["runs"]}
    if got != expected:
        errors.append(f"runs missing: {sorted(expected - got)[:3]}")
    counts = {r["realizations"] for r in predictions["runs"]}
    if len(counts) > 1:
        errors.append(f"the engines ran different numbers of realizations {sorted(counts)}")
    for r in predictions["runs"]:
        label = f"{r['scheme']}/{r['prior']}/{r['engine']}"
        if not r["hardHonoured"]:
            errors.append(f"{label}: a realization changed a conditioning cell")
        file = folder / r["file"]
        if not file.is_file():
            errors.append(f"{label}: {r['file']} is missing")
        elif _array_sha(np.load(file)) != r["sha256"]:
            errors.append(f"{label}: {r['file']} does not match its record")
    return errors


def check_categorical_metrics(metrics: dict, predictions: dict) -> list[str]:
    if metrics.get("inputCategoricalPredictionsSha256") != stable_hash(predictions):
        return ["categorical metrics were computed from other predictions"]
    if not metrics.get("eligible"):
        return []
    scored = {(s["scheme"], r["prior"], r["engine"]) for s in metrics["schemes"] for r in s["runs"]}
    expected = {(r["scheme"], r["prior"], r["engine"]) for r in predictions["runs"]}
    return [] if scored == expected else [f"categorical runs not scored: {sorted(expected - scored)[:3]}"]


def check_categorical(folder: Path) -> list[str]:
    """The categorical chain of a family folder, as far as its outputs go."""
    path = folder / "categorical-models.json"
    if not path.is_file():
        return []
    project = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    dataset_path = folder / "dataset.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8")) if dataset_path.is_file() else None
    models = json.loads(path.read_text(encoding="utf-8"))
    errors = check_categorical_models(models, folder, project, dataset)
    predictions_path = folder / "categorical-predictions.json"
    if predictions_path.is_file():
        predictions = json.loads(predictions_path.read_text(encoding="utf-8"))
        errors += check_categorical_predictions(predictions, models, folder)
        metrics_path = folder / "categorical-metrics.json"
        if metrics_path.is_file():
            errors += check_categorical_metrics(json.loads(metrics_path.read_text(encoding="utf-8")), predictions)
    return errors


def check_family(folder: Path) -> list[str]:
    project_path, summary_path = folder / "project.json", folder / "summary.json"
    if not summary_path.is_file():
        return [f"{folder.name}: summary.json missing"]
    project = json.loads(project_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    errors = check_project(project)
    if summary.get("projectSha256") != stable_hash(project):
        errors.append("summary hash does not match the project")
    counts = {t: len(project.get(t, [])) for t in TABLES}
    if summary.get("counts") != counts:
        errors.append("summary counts do not match the project")
    pre_path, pre_summary_path = folder / "preprocessed.json", folder / "preprocess-summary.json"
    if pre_path.is_file():
        pre = json.loads(pre_path.read_text(encoding="utf-8"))
        errors += check_preprocessed(pre, project)
        pre_summary = json.loads(pre_summary_path.read_text(encoding="utf-8")) if pre_summary_path.is_file() else {}
        if pre_summary.get("preprocessedSha256") != stable_hash(pre):
            errors.append("preprocess summary hash does not match the preprocessed output")
        dataset_path, features_path = folder / "dataset.json", folder / "features.json"
        if dataset_path.is_file():
            dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
            errors += check_dataset(dataset, project, pre)
            if features_path.is_file():
                features = json.loads(features_path.read_text(encoding="utf-8"))
                errors += check_features(features, dataset)
                models_path, predictions_path = folder / "models.json", folder / "predictions.json"
                if models_path.is_file():
                    models = json.loads(models_path.read_text(encoding="utf-8"))
                    errors += check_models(models, features)
                    if predictions_path.is_file():
                        predictions = json.loads(predictions_path.read_text(encoding="utf-8"))
                        errors += check_predictions(predictions, models)
                        metrics_path = folder / "metrics.json"
                        if metrics_path.is_file():
                            errors += check_metrics(json.loads(metrics_path.read_text(encoding="utf-8")), predictions)
        errors += check_categorical(folder)
        errors += check_learned(folder)
    return [f"{folder.name}: {e}" for e in errors]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--derived", type=Path, default=ROOT / "build" / "derived")
    args = parser.parse_args(argv)
    folders = sorted(p.parent for p in args.derived.glob("*/project.json"))
    if not folders:
        print(f"FAIL: no ingested project under {args.derived} (run data-pipeline/run.py ingest first)")
        return 1
    errors = [e for folder in folders for e in check_family(folder)]
    if (args.derived / "scenarios.json").is_file():
        matrix = json.loads((args.derived / "scenarios.json").read_text(encoding="utf-8"))
        errors += [f"scenarios: {e}" for e in check_scenarios(matrix, args.derived)]
    if errors:
        print("PROJECT CONTRACT VIOLATIONS:")
        for error in errors:
            print(f"  - {error}")
        return 1
    names = ("preprocessed.json", "dataset.json", "features.json", "models.json", "predictions.json", "metrics.json")
    stages = {f.name: " + ".join(["ingest"] + [n.split(".")[0].replace("preprocessed", "preprocess").replace("models", "train")
                                                .replace("predictions", "infer").replace("metrics", "evaluate")
                                                for n in names
                                               if (f / n).is_file()]) for f in folders}
    print("PROJECT CONTRACT OK: " + ", ".join(f"{k} ({v})" for k, v in stages.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
