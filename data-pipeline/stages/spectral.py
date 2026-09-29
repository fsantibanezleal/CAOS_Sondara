"""The R12 spectral-index lineage and the iron-oxide index check (unit SD-7b).

``lineage`` says what every column of the supplied hyperspectral export is, from the collection's own files and the
canonical assays: the product behind each spectral scalar, the embedded assay columns that copy the workbook, and
whether each hole's depths are registered with the assays. ``fit_index`` calibrates Fe on the iron-oxide index on the
training holes' confirmed rows (a monotone fit, GeoCond ``pava``) and predicts the test holes' confirmed rows;
``score_index`` scores it beside ordinary kriging on the same rows. Design:
docs/design/features/geochemical-review/design.md, sections 2 and 3.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

import numpy as np
from source_io import ROOT, stable_hash

LINEAGE_SCHEMA = "drillhole.spectral-lineage/v1"
MODELS_SCHEMA = "drillhole.spectral-models/v1"
METRICS_SCHEMA = "drillhole.spectral-metrics/v1"
INTERPRETATIONS = ROOT / "data" / "interpretations"
SCHEME, POPULATION = "hole-group", "rocklea-native-1m"
TOLERANCE = 1e-9


def load_mapping(family: str) -> dict | None:
    path = INTERPRETATIONS / f"{family}-spectral-products-v1.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def canonical_assays(project: dict) -> dict:
    """(hole, from depth) to the support id and its measured original values, by analyte."""
    supports = {s["id"]: s for s in project["supports"] if s.get("kind") == "interval"}
    out: dict = {}
    for d in project["determinations"]:
        s = supports.get(d["supportId"])
        if s is None or d.get("state") != "measured" or d.get("sampleRole", "original") != "original":
            continue
        entry = out.setdefault((s["holeId"], float(s["fromMd"])), {"support": s["id"], "values": {}})
        entry["values"][d["analyteId"]] = d["value"]
    return out


def _equal(export_value, canonical_value, rule):
    if rule.startswith("whole percent"):
        return export_value == float(np.round(canonical_value))
    return abs(export_value - canonical_value) <= TOLERANCE


def _summary(values):
    v = np.array([x for x in values if x is not None], dtype=float)
    if not len(v):
        return {"n": 0}
    return {"n": len(v), "min": float(v.min()), "median": float(np.median(v)), "max": float(v.max())}


def lineage(project: dict, source: dict, mapping: dict) -> dict:
    rows = source["rows"]
    canonical = canonical_assays(project)
    project_holes = {h for h, _ in canonical}
    products = {p["Product name"]: p for p in source["descriptions"]["products"]}
    parameters = {p["name"]: p for p in source["project"]["parameters"]}
    described = []
    for entry in mapping["spectral"]:
        product = products.get(entry["product"])
        values = [r["spectral"][entry["column"]] for r in rows]
        described.append({
            "column": entry["column"], "status": "described" if product else "undescribed",
            "product": entry["product"], "unit": entry["unit"], "kind": entry["kind"],
            "workbookRow": product and product["row"],
            **({k: product.get(k, "") for k in ("Base algorithm", "Filters/Masks", "Lower stretch limit",
                                                 "Upper stretch limit (based on UGD1683)", "related publication",
                                                 "Comments on general accuracy")} if product else {}),
            "tsgParameter": parameters.get(entry["column"]), "values": _summary(values),
            "null": sum(v is None for v in values)})
    listed = {e["product"] for e in mapping["spectral"]}
    not_exported = [p for p in products if p not in listed]
    undescribed = [c for c in source["columns"]["spectral"] if c not in {e["column"] for e in mapping["spectral"]}]

    embedded = []
    for column, rule in mapping["embeddedAssays"].items():
        compared = equal = 0
        for r in rows:
            v = r["embedded"].get(column)
            c = canonical.get((r["hole"], r["depthFrom"])) if r["hole"] and r["depthFrom"] is not None else None
            if v is None or c is None or rule["analyte"] not in c["values"]:
                continue
            compared += 1
            equal += _equal(v, c["values"][rule["analyte"]], rule["comparison"])
        embedded.append({"column": column, "analyte": rule["analyte"], "comparison": rule["comparison"],
                         "compared": compared, "equal": equal, "share": equal / compared if compared else None,
                         "role": "target: a copy of the workbook assay, never a feature"})

    compare = mapping["registration"]["compare"]
    analyte_of = {rule["analyte"]: column for column, rule in mapping["embeddedAssays"].items()}

    def matches(r, key):
        c = canonical.get(key)
        if c is None:
            return False
        pairs = [(r["embedded"][analyte_of[a]], c["values"].get(a)) for a in compare]
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        return bool(pairs) and all(abs(x - y) <= TOLERANCE for x, y in pairs)

    by_hole = defaultdict(Counter)
    for r in rows:
        if not r["hole"] or r["depthFrom"] is None:
            continue
        if all(r["embedded"][analyte_of[a]] is None for a in compare):
            by_hole[r["hole"]]["no embedded assay"] += 1
        elif matches(r, (r["hole"], r["depthFrom"])):
            by_hole[r["hole"]]["same depth"] += 1
        else:
            offset = next((o for o in mapping["registration"]["offsets"]
                           if matches(r, (r["hole"], r["depthFrom"] + o))), None)
            by_hole[r["hole"]][f"offset {offset:+g} m" if offset is not None else "unmatched"] += 1
    registration = {}
    for hole, counts in sorted(by_hole.items()):
        if hole not in project_holes:
            status = "not in the canonical project"
        elif set(counts) <= {"same depth", "no embedded assay"}:
            status = "confirmed" if counts["same depth"] else "no embedded assay"
        elif any(k.startswith("offset") for k in counts):
            status = "offset"
        else:
            status = "unmatched"
        registration[hole] = {"status": status, "rows": dict(counts)}
    keys = Counter((r["hole"], r["depthFrom"]) for r in rows if r["hole"] and r["depthFrom"] is not None)
    duplicates = sorted([h, d] for (h, d), n in keys.items() if n > 1)
    statuses = Counter(v["status"] for v in registration.values())
    return {"schema": LINEAGE_SCHEMA, "family": source["family"], "mappingId": mapping["id"],
            "mappingSha256": stable_hash(mapping), "sources": source["sources"],
            "exportRows": len(rows), "rowsWithoutHole": sum(r["hole"] is None for r in rows),
            "spectral": described, "undescribedColumns": undescribed, "describedNotExported": not_exported,
            "embedded": embedded,
            "registration": {"holes": registration, "counts": dict(sorted(statuses.items())),
                             "duplicateKeys": duplicates, "rule": mapping["registration"]["rule"]},
            "calibratedChannels": {"pls": source["pls"], "inExport": False,
                                   "rule": "a calibrated channel enters a held-out comparison only after a training-"
                                           "fold refit; the export holds none, and the PLS model is not used"},
            "statedAccuracy": mapping["calibration"]["statedAccuracy"],
            "answers": source["answers"]}


def _pairs(source, lineage_record, supports_of, rows_by_id, split_ids, index, target):
    """(support id, hole, index value, Fe) for the confirmed, unmasked, unambiguous rows of one split."""
    confirmed = {h for h, v in lineage_record["registration"]["holes"].items() if v["status"] == "confirmed"}
    duplicates = {(h, d) for h, d in lineage_record["registration"]["duplicateKeys"]}
    out, excluded = [], Counter()
    for r in source["rows"]:
        key = (r["hole"], r["depthFrom"])
        support = supports_of.get(key)
        if support is None or support not in split_ids:
            continue
        if r["hole"] not in confirmed:
            excluded["registration not confirmed"] += 1
        elif key in duplicates:
            excluded["duplicate hole-depth key"] += 1
        elif r["spectral"][index] is None:
            excluded["masked or missing index"] += 1
        elif target not in rows_by_id[support]["values"]:
            excluded[f"no {target}"] += 1
        else:
            out.append((support, r["hole"], r["spectral"][index], rows_by_id[support]["values"][target]))
    return out, dict(excluded)


def fit_index(project, pre, dataset, source, lineage_record, mapping, *, population_id=POPULATION) -> dict:
    """Monotone Fe on the index, fitted on the training holes' confirmed rows; predictions for the test rows."""
    from geocond import pava
    from stages.train import _split_rows

    index = mapping["calibration"]["index"]
    target = mapping["calibration"]["target"]
    scheme = next(s for s in dataset["schemes"] if s["id"] == SCHEME)
    population = next(p for p in pre["populations"] if p["id"] == population_id)
    rows = _split_rows(project, pre, scheme, population)
    rows_by_id = {r["id"]: r for split in rows.values() for r in split}
    supports_of = {(k[0], k[1]): v["support"] for k, v in canonical_assays(project).items()}
    train, excluded_train = _pairs(source, lineage_record, supports_of, rows_by_id, {r["id"] for r in rows["train"]},
                                   index, target)
    test, excluded_test = _pairs(source, lineage_record, supports_of, rows_by_id, {r["id"] for r in rows["test"]},
                                 index, target)
    x = np.array([p[2] for p in train], dtype=float)
    y = np.array([p[3] for p in train], dtype=float)
    unique, inverse, counts = np.unique(x, return_inverse=True, return_counts=True)
    means = np.bincount(inverse, weights=y) / counts
    fitted = pava(means, counts)
    predict = lambda v: np.interp(v, unique, fitted)
    return {"schema": MODELS_SCHEMA, "family": source["family"], "scheme": SCHEME, "population": population_id,
            "index": index, "target": target, "method": "isotonic (GeoCond pava on the index-sorted, tie-averaged "
                                                      "training rows), linear between knots, constant beyond them",
            "train": {"rows": len(train), "holes": len({p[1] for p in train}), "excluded": excluded_train},
            "fit": {"x": unique.tolist(), "y": fitted.tolist(), "weights": counts.tolist()},
            "test": [{"id": s, "hole": h, "index": v, "prediction": float(predict(v))} for s, h, v, _ in test],
            "testExcluded": excluded_test, "statedAccuracy": mapping["calibration"]["statedAccuracy"],
            "inputLineageSha256": stable_hash(lineage_record)}


def score_index(models: dict, project, pre, dataset, predictions: dict) -> dict:
    """The index calibration scored on the test rows, beside OK and the training mean on the same rows."""
    from stages.evaluate import _scores, paired
    from stages.train import _split_rows

    scheme = next(s for s in dataset["schemes"] if s["id"] == models["scheme"])
    population = next(p for p in pre["populations"] if p["id"] == models["population"])
    rows = _split_rows(project, pre, scheme, population)
    by_id = {r["id"]: r for split in rows.values() for r in split}
    pscheme = next(s for s in predictions["schemes"] if s["scheme"] == models["scheme"])
    precord = next(p for p in pscheme["populations"] if p["population"] == models["population"])
    ok = {r["id"]: r for r in precord["methods"]["ordinary-kriging"]["rows"] if r["status"] == "estimated"}
    target = models["target"]
    mean = float(np.mean([r["values"][target] for r in rows["train"] if target in r["values"]]))
    ids = [t["id"] for t in models["test"] if t["id"] in ok]
    pred = {t["id"]: t["prediction"] for t in models["test"]}
    truth = {i: by_id[i]["values"][target] for i in ids}
    lengths, holes = [by_id[i]["length"] for i in ids], [by_id[i]["hole"] for i in ids]
    index_errors = [pred[i] - truth[i] for i in ids]
    ok_errors = [ok[i]["mean"] - truth[i] for i in ids]
    return {"schema": METRICS_SCHEMA, "family": models["family"], "task": f"{target} from the index measured in "
            "the same interval (information the spatial methods do not have), beside OK on the same rows",
            "rows": len(ids), "holes": len(set(holes)),
            "index": _scores(index_errors, lengths, holes),
            "ordinaryKriging": _scores(ok_errors, lengths, holes),
            "trainingMean": _scores([mean - truth[i] for i in ids], lengths, holes),
            "indexVersusOrdinaryKriging": paired(index_errors, ok_errors, holes),
            "statedAccuracy": models.get("statedAccuracy"),
            "inputSpectralModelsSha256": stable_hash(models), "inputPredictionsSha256": stable_hash(predictions)}
