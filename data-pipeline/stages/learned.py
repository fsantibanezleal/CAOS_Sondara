"""The learned lane: DeepKriging and KCN on the classical lane's splits and targets (unit SD-7a).

Design: docs/design/features/learned-regression/design.md. ``train_learned`` fits the frozen candidate search of both
methods on every population the classical lane estimates (three seeds per configuration, validation selection by the
seed mean of the hole-macro RMSE), the two controls and the transforms; ``infer_learned`` predicts the test and
calibration targets with the three-seed ensemble, exports each seed to ONNX and checks its parity on those inputs.
Needs PyTorch, onnx and ONNX Runtime (``requirements-gpu.txt``).
"""

from __future__ import annotations

import time
from functools import partial
from pathlib import Path

import numpy as np
import torch
from learned.contracts import SEEDS, binding, canonical_hash
from learned.exporting import export_model
from learned.features import (
    KNOT_LEVELS,
    fit_basis,
    graph_inputs,
    local,
    neighbour_scale,
    outside_box,
    select_neighbours,
    target_transform,
)
from learned.networks import KCN, DeepKriging
from learned.training import EPOCHS, PATIENCE, fit, predict, tensors, weights_sha256
from scipy.spatial import cKDTree
from source_io import stable_hash
from stages.features import family_analytes
from stages.train import _split_rows

MODELS_SCHEMA = "drillhole.learned-models/v1"
PREDICTIONS_SCHEMA = "drillhole.learned-predictions/v1"
METHODS = ("deepkriging", "kcn")
DK_SEARCH = [{"id": f"{levels}-w{'-'.join(map(str, widths))}-d{dropout:g}", "levels": levels, "widths": widths,
              "dropout": dropout}
             for levels in KNOT_LEVELS for widths in ([64, 64, 32], [128, 64, 32]) for dropout in (0.0, 0.1)]
KCN_SEARCH = [{"id": f"k{k}-w{width}-phi{factor:g}", "k": k, "width": width, "phiFactor": factor}
              for k in (16, 32) for width in (32, 64) for factor in (0.5, 1.0, 2.0)]
PER_HOLE, MIN_HOLES = 4, 2
MIN_TRAINING_HOLES = 3
CONTROL_SEED = 20260926
BAND_QUANTILE = 0.95
#: Parity tolerance in training standard deviations (native units); the 2026-09-28 probe measured about 1e-6.
PARITY_FACTOR = 1e-4
KCN_INPUTS = ("positions", "values", "known", "lengths", "trajectory", "valid")


def device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def engine() -> dict:
    import onnx
    import onnxruntime

    return {"torch": torch.__version__, "cuda": torch.version.cuda, "onnx": onnx.__version__,
            "onnxruntime": onnxruntime.__version__, "numpy": np.__version__}


def populations(family: str, pre: dict, features: dict):
    """The populations the classical lane estimates, with the classical target rule (``stages/train.py``)."""
    primary = family_analytes(family, pre)
    for fscheme in features["schemes"]:
        for record in fscheme["populations"]:
            population = next(p for p in pre["populations"] if p["id"] == record["population"])
            yield fscheme["scheme"], population, population.get("analyte") or primary[0]


def _arrays(rows: list[dict], analyte: str, measured: set[str]) -> dict:
    use = [r for r in rows if analyte in r["values"]]
    return {"ids": [r["id"] for r in use], "order": np.array([r["id"] for r in use]),
            "holes": np.array([r["hole"] for r in use]),
            "xyz": np.array([r["xyz"] for r in use], dtype=np.float64).reshape(-1, 3),
            "y": np.array([r["values"][analyte] for r in use], dtype=np.float64),
            "length": np.array([r["length"] for r in use], dtype=np.float64),
            "trajectory": np.array([r["hole"] in measured for r in use], dtype=np.float64)}


def _split(project, pre, scheme, population, analyte) -> dict:
    measured = {t["holeId"] for t in pre["trajectories"] if t["kind"] == "measured-stations"}
    rows = _split_rows(project, pre, scheme, population)
    return {name: _arrays(rows[name], analyte, measured) for name in ("train", "validation", "calibration", "test")}


def _unit(project, analyte) -> str:
    return next(a["unit"] for a in project["analytes"] if a["id"] == analyte)


def _fits_dir(target: Path, scheme, population, method, config) -> Path:
    return target / "learned" / "fits" / scheme / population / method / config


def _dk_model(basis, config, transform, coordinate_only=False):
    return DeepKriging(basis, config["widths"], config["dropout"], transform["mean"], transform["scale"],
                       coordinate_only=coordinate_only)


def _make(method, cfg, transform, *, basis=None, dbar=None, length_scale=None, coordinate_only=False):
    if method == "deepkriging":
        return _dk_model(basis, cfg, transform, coordinate_only)
    return KCN(cfg["width"], transform["mean"], transform["scale"], dbar, length_scale, cfg["phiFactor"] * dbar)


def _kcn_inputs(query: dict, conditioning: dict, k: int):
    selected, supported, reasons = select_neighbours(query["xyz"], query["holes"], conditioning, k,
                                                     per_hole=PER_HOLE, min_holes=MIN_HOLES)
    inputs = graph_inputs(query, conditioning, selected)
    return tuple(inputs[name] for name in KCN_INPUTS), selected, supported, reasons


def _take(inputs, mask):
    return tuple(x[mask] for x in inputs)


def _length_scale(train) -> float:
    median = float(np.median(train["length"])) if len(train["length"]) else 0.0
    return median if median > 0 else 1.0


def _fit_config(method, config, split, transform, context, out_dir, dev, *, epochs, patience, labels=None,
                coordinate_only=False, tag=""):
    """Fit one configuration with the three seeds; returns the fit records."""
    train, validation = split["train"], split["validation"]
    label_kind = "shuffled" if labels is not None else "observed"
    y = train["y"] if labels is None else labels
    if method == "deepkriging":
        basis = context["bases"][config["levels"]]
        x_train = (local(train["xyz"], basis["coordinates"]),)
        x_val = (local(validation["xyz"], basis["coordinates"]),)
        val_mask = np.ones(len(validation["y"]), dtype=bool)
        recipe = {"method": method, "config": config, "coordinateOnly": coordinate_only,
                  "basisSha256": context["basisHash"][config["levels"]], "transform": transform}
    else:
        graph = context["graphs"][config["k"]]
        key = (config["k"], label_kind)
        if key not in context["kcnInputs"]:  # the search depends on K and the labels only, not on the seed
            conditioning = graph["conditioning"] if labels is None else {**graph["conditioning"], "y": labels}
            x_all = _kcn_inputs(train, conditioning, config["k"])[0]
            x_val_all, _, supported, _ = _kcn_inputs(validation, conditioning, config["k"])
            context["kcnInputs"][key] = (_take(x_all, graph["trainSupported"]), _take(x_val_all, supported), supported)
        x_train, x_val, val_mask = context["kcnInputs"][key]
        y = y[graph["trainSupported"]]
        recipe = {"method": method, "config": config, "dbar": graph["dbar"], "lengthScale": context["lengthScale"],
                  "transform": transform}
    recipe |= {"trainingRowsSha256": context["trainHash"], "labels": label_kind}
    records = []
    for seed in SEEDS:
        if method == "deepkriging":
            model = _dk_model(basis, config, transform, coordinate_only)
        else:
            model = KCN(config["width"], transform["mean"], transform["scale"], graph["dbar"], context["lengthScale"],
                        config["phiFactor"] * graph["dbar"])
        folder = out_dir / (f"{tag}{config['id']}") / f"seed-{seed}"
        result = fit(model, x_train, y, x_val, validation["y"][val_mask], validation["holes"][val_mask], folder,
                     recipe, seed, dev, scale=transform["scale"], epochs=epochs, patience=patience)
        records.append({k: result[k] for k in ("seed", "recipeHash", "bestEpoch", "epochsRun",
                                               "bestValidationObjective", "fitSeconds", "device", "weightsSha256")}
                       | {"folder": folder.relative_to(context["target"]).as_posix(),
                          "validationCoverage": float(val_mask.mean()) if len(val_mask) else 0.0,
                          "parameters": sum(p.numel() for p in model.parameters())})
    return records


def _shuffled(y):
    """The shuffled-label control's targets: the training values permuted among the training rows."""
    return np.random.Generator(np.random.PCG64(CONTROL_SEED)).permutation(y)


def _select(entries):
    """The configuration with the lowest mean validation objective over its seeds; ties to fewer parameters, then to
    the declaration order."""
    ranked = sorted(enumerate(entries), key=lambda ie: (float(np.mean([f["bestValidationObjective"]
                                                                        for f in ie[1]["fits"]])),
                                                         ie[1]["fits"][0]["parameters"], ie[0]))
    return ranked[0][1]["config"]["id"]


def train_learned(family, project, pre, dataset, features, target: Path, *, epochs=None, patience=None,
                  dk_search=None, kcn_search=None) -> dict:
    """Fit both methods' frozen searches and controls; the module settings apply unless the caller passes others."""
    epochs = EPOCHS if epochs is None else epochs
    patience = PATIENCE if patience is None else patience
    dk_search = DK_SEARCH if dk_search is None else dk_search
    kcn_search = KCN_SEARCH if kcn_search is None else kcn_search
    dev = device()
    out = {"schema": MODELS_SCHEMA, "family": family, "engine": engine(), "device": dev,
           "deviceName": torch.cuda.get_device_name() if dev == "cuda" else "CPU", "cpuThreads": torch.get_num_threads(),
           "seeds": list(SEEDS), "search": {"deepkriging": dk_search, "kcn": kcn_search},
           "policy": {"perHole": PER_HOLE, "minHoles": MIN_HOLES, "minTrainingHoles": MIN_TRAINING_HOLES,
                      "epochs": epochs, "patience": patience, "controlSeed": CONTROL_SEED,
                      "selection": "lowest mean over the three seeds of the validation hole-macro RMSE (native); "
                                   "ties to fewer parameters, then declaration order"},
           "schemes": []}
    if not dataset["eligible"]:
        return {**out, "eligible": False, "reason": dataset["reason"]}
    dataset_sha = stable_hash(dataset)
    by_scheme = {s["id"]: s for s in dataset["schemes"]}
    grouped: dict[str, list] = {}
    for scheme_id, population, analyte in populations(family, pre, features):
        t0 = time.time()
        split = _split(project, pre, by_scheme[scheme_id], population, analyte)
        train = split["train"]
        record = {"population": population["id"], "analyte": analyte, "unit": _unit(project, analyte),
                  "rows": {k: len(v["y"]) for k, v in split.items()},
                  "holes": {k: len(set(v["holes"])) for k, v in split.items()},
                  "binding": binding(project, population, analyte, _unit(project, analyte), dataset_sha,
                                     train["ids"])}
        grouped.setdefault(scheme_id, []).append(record)
        if record["holes"]["train"] < MIN_TRAINING_HOLES or not record["rows"]["validation"]:
            record.update(status="not eligible", reason=f"{record['holes']['train']} training holes and "
                                                        f"{record['rows']['validation']} validation rows; at least "
                                                        f"{MIN_TRAINING_HOLES} and 1 are required")
            continue
        transform = target_transform(train["y"])
        record["transform"] = transform
        if transform["constant"]:
            record.update(status="constant", reason="the training target is constant; it is predicted as that value")
            continue
        conditioning = {k: train[k] for k in ("xyz", "holes", "order", "y", "length", "trajectory")}
        context = {"target": target, "trainHash": canonical_hash(sorted(train["ids"])), "bases": {}, "basisHash": {},
                   "kcnInputs": {},
                   "graphs": {}, "lengthScale": _length_scale(train)}
        for levels in {c["levels"] for c in dk_search}:
            basis = fit_basis(train["xyz"], KNOT_LEVELS[levels])
            context["bases"][levels], context["basisHash"][levels] = basis, canonical_hash(basis)
        for k in sorted({c["k"] for c in kcn_search}):
            selected, supported, _ = select_neighbours(train["xyz"], train["holes"], conditioning, k,
                                                       per_hole=PER_HOLE, min_holes=MIN_HOLES)
            context["graphs"][k] = {"conditioning": conditioning, "trainSupported": supported,
                                    "dbar": neighbour_scale(train["xyz"][supported], selected[supported],
                                                            train["xyz"])}
        shuffled = _shuffled(train["y"])
        record["methods"] = {}
        for method, search in (("deepkriging", dk_search), ("kcn", kcn_search)):
            folder = _fits_dir(target, scheme_id, population["id"], method, "")
            entries = [{"config": c, "fits": _fit_config(method, c, split, transform, context, folder, dev,
                                                         epochs=epochs, patience=patience)} for c in search]
            chosen = _select(entries)
            config = next(e["config"] for e in entries if e["config"]["id"] == chosen)
            controls = {"shuffled-labels": _fit_config(method, config, split, transform, context, folder, dev,
                                                       epochs=epochs, patience=patience, labels=shuffled,
                                                       tag="control-shuffled-")}
            if method == "deepkriging":
                controls["coordinate-only"] = _fit_config(method, config, split, transform, context, folder, dev,
                                                          epochs=epochs, patience=patience, coordinate_only=True,
                                                          tag="control-coordinates-")
            entry = {"selected": chosen, "configurations": entries, "controls": controls}
            if method == "deepkriging":
                entry["bases"] = {lv: {k: context["bases"][lv][k] for k in ("levels", "candidateColumns",
                                                                            "removedZeroColumns", "coordinates")}
                                  | {"columns": len(context["bases"][lv]["knots"]), "sha256": context["basisHash"][lv]}
                                  for lv in context["bases"]}
            else:
                entry["graphs"] = {str(k): {"dbar": g["dbar"], "trainQueriesSupported": int(g["trainSupported"].sum())}
                                   for k, g in context["graphs"].items()}
                entry["lengthScale"] = context["lengthScale"]
            record["methods"][method] = entry
        record.update(status="fitted", seconds=round(time.time() - t0, 1))
    out["schemes"] = [{"scheme": s, "populations": p} for s, p in grouped.items()]
    return {**out, "eligible": True, "inputDatasetSha256": dataset_sha}


def _load(model, target: Path, fit_record: dict):
    weights = target / fit_record["folder"] / "weights.pt"
    if weights_sha256(weights) != fit_record["weightsSha256"]:
        raise ValueError(f"{weights}: the weights do not match learned-models.json; run train again")
    model.load_state_dict(torch.load(weights, weights_only=True, map_location="cpu"))
    return model.eval()


def _ensemble(models, inputs, dev):
    seeds = np.stack([predict(m.to(dev), tensors(inputs, dev)).cpu().numpy().astype(np.float64) for m in models])
    for m in models:
        m.cpu()
    return seeds


def _rows(method, ids, seeds, supported, reasons, extra):
    rows = []
    for i, row_id in enumerate(ids):
        if supported is not None and not supported[i]:
            rows.append({"id": row_id, "method": method, "status": "uninformed", "reason": reasons[i], "mean": None,
                         "variance": None, "seeds": None, "spread": None, **{k: v[i] for k, v in extra.items()}})
            continue
        j = i if supported is None else int(supported[:i].sum())
        values = seeds[:, j]
        rows.append({"id": row_id, "method": method, "status": "estimated", "reason": None,
                     "mean": float(values.mean()), "variance": None, "seeds": [float(v) for v in values],
                     "spread": float(values.std()), **{k: v[i] for k, v in extra.items()}})
    return rows


def infer_learned(models_record, project, pre, dataset, target: Path, *, export=True) -> dict:
    dev = device()
    out = {"schema": PREDICTIONS_SCHEMA, "family": models_record["family"], "engine": engine(), "device": dev,
           "methods": list(METHODS), "schemes": [],
           "conditioning": "training rows only; validation rows chose the configuration; calibration rows set the "
                           "residual band; test rows are scored by evaluate"}
    if not models_record.get("eligible"):
        return {**out, "eligible": False, "reason": models_record.get("reason")}
    by_scheme = {s["id"]: s for s in dataset["schemes"]}
    for mscheme in models_record["schemes"]:
        entry = {"scheme": mscheme["scheme"], "populations": []}
        for record in mscheme["populations"]:
            population = next(p for p in pre["populations"] if p["id"] == record["population"])
            analyte = record["analyte"]
            split = _split(project, pre, by_scheme[mscheme["scheme"]], population, analyte)
            if canonical_hash(sorted(split["train"]["ids"])) != record["binding"]["trainingRowsSha256"]:
                raise ValueError(f"{record['population']}: the training rows changed since train; run train again")
            query = {k: np.concatenate([split["test"][k], split["calibration"][k]])
                     for k in ("xyz", "holes", "length", "trajectory", "y")}
            ids = split["test"]["ids"] + split["calibration"]["ids"]
            n_test = len(split["test"]["ids"])
            result = {"population": record["population"], "analyte": analyte, "targets": split["test"]["ids"],
                      "calibrationTargets": split["calibration"]["ids"], "status": record["status"], "methods": {}}
            entry["populations"].append(result)
            if record["status"] == "constant":
                for method in METHODS:
                    rows = [{"id": i, "method": method, "status": "estimated", "reason": record["reason"],
                             "mean": record["transform"]["mean"], "variance": None, "seeds": None, "spread": 0.0}
                            for i in ids]
                    result["methods"][method] = {"rows": rows[:n_test], "calibrationRows": rows[n_test:]}
                continue
            if record["status"] != "fitted":
                result["reason"] = record.get("reason")
                continue
            train = split["train"]
            conditioning = {k: train[k] for k in ("xyz", "holes", "order", "y", "length", "trajectory")}
            transform = record["transform"]
            tree = cKDTree(train["xyz"])
            nearest = tree.query(query["xyz"])[0] if len(query["xyz"]) else np.zeros(0)
            for method in METHODS:
                t0 = time.time()
                m = record["methods"][method]
                config = next(e for e in m["configurations"] if e["config"]["id"] == m["selected"])
                cfg = config["config"]
                if method == "deepkriging":
                    basis = fit_basis(train["xyz"], KNOT_LEVELS[cfg["levels"]])
                    if canonical_hash(basis) != m["bases"][cfg["levels"]]["sha256"]:
                        raise ValueError(f"{record['population']}: the basis differs from train; run train again")

                    build = partial(_make, method, cfg, transform, basis=basis)
                    inputs = (local(query["xyz"], basis["coordinates"]),)
                    supported, reasons = None, None
                    extra = {"distanceToTraining": [float(d) for d in nearest],
                             "outsideTrainingBox": [bool(b) for b in outside_box(query["xyz"], basis["coordinates"])]}
                    names = ["local"]
                    features_record = {"input": "position minus the training origin, metres (float64 subtraction "
                                                "before the float32 cast)", "origin": basis["coordinates"]["origin"],
                                       "axisScale": basis["coordinates"]["scale"], "levels": basis["levels"],
                                       "columns": len(basis["knots"]), "basisSha256": m["bases"][cfg["levels"]]["sha256"]}
                else:
                    dbar = m["graphs"][str(cfg["k"])]["dbar"]

                    build = partial(_make, method, cfg, transform, dbar=dbar, length_scale=m["lengthScale"])
                    all_inputs, selected, supported, reasons = _kcn_inputs(query, conditioning, cfg["k"])
                    inputs = _take(all_inputs, supported)
                    real = selected >= 0
                    extra = {"neighbours": [int(r.sum()) for r in real],
                             "neighbourHoles": [len({train["holes"][j] for j in s[s >= 0]}) for s in selected],
                             "nearestNeighbour": [float(np.min(np.linalg.norm(train["xyz"][s[s >= 0]] - q, axis=1)))
                                                  if (s >= 0).any() else None for s, q in zip(selected, query["xyz"],
                                                                                               strict=True)]}
                    names = list(KCN_INPUTS)
                    features_record = {"inputs": "row 0 the query: positions relative to it (metres), native values "
                                                 "(0 for the query), known flags, support lengths (metres), "
                                                 "trajectory kinds (1 measured), validity",
                                       "k": cfg["k"], "perHole": PER_HOLE, "minHoles": MIN_HOLES, "dbar": dbar,
                                       "phi": cfg["phiFactor"] * dbar, "lengthScale": m["lengthScale"]}
                seeds_models = [_load(build(), target, f) for f in config["fits"]]
                seeds = _ensemble(seeds_models, inputs, dev) if len(inputs[0]) else np.zeros((len(SEEDS), 0))
                rows = _rows(method, ids, seeds, supported, reasons, extra)
                controls = {}
                for name, fits in m["controls"].items():
                    cmodels = [_load(build(coordinate_only=name == "coordinate-only"), target, f) for f in fits]
                    cinputs = inputs
                    if method == "kcn" and name == "shuffled-labels":  # the permuted values it was trained on
                        permuted = {**conditioning, "y": _shuffled(train["y"])}
                        cinputs = _take(_kcn_inputs(query, permuted, cfg["k"])[0], supported)
                    cseeds = _ensemble(cmodels, cinputs, dev) if len(inputs[0]) else np.zeros((len(SEEDS), 0))
                    controls[name] = {"rows": [{k: r[k] for k in ("id", "status", "mean")}
                                               for r in _rows(method, ids, cseeds, supported, reasons, {})][:n_test]}
                exports = []
                if export and len(inputs[0]):
                    for model, fit_record in zip(seeds_models, config["fits"], strict=True):
                        folder = target / "learned" / "exports" / mscheme["scheme"] / record["population"] / method / \
                            f"seed-{fit_record['seed']}"
                        manifest = export_model(model, inputs, names, folder, {
                            "method": method, "family": models_record["family"], "scheme": mscheme["scheme"],
                            "population": record["population"], "analyte": analyte, "unit": record["unit"],
                            "configuration": cfg, "seed": fit_record["seed"], "weightsSha256": fit_record["weightsSha256"],
                            "binding": record["binding"], "features": features_record,
                            "transform": {"mean": transform["mean"], "scale": transform["scale"]}},
                            tolerance=PARITY_FACTOR * transform["scale"])
                        exports.append({"seed": fit_record["seed"], "folder": folder.relative_to(target).as_posix(),
                                        "model": manifest["model"], "parity": manifest["parity"]})
                result["methods"][method] = {"selected": cfg, "rows": rows[:n_test], "calibrationRows": rows[n_test:],
                                             "controls": controls, "exports": exports,
                                             "seconds": round(time.time() - t0, 2)}
        out["schemes"].append(entry)
    return {**out, "eligible": True}
