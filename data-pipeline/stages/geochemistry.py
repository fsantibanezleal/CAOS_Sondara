"""The geochemical autoencoder review with its PCA reference (unit SD-7b, R12; the learned lane).

Complete records of the declared properties on the hole-group split of the 1 m population are centred by the training
median, scaled by the training interquartile range and passed through asinh. An undercomplete autoencoder
(p-32-8-k-8-32-p) is fitted with three seeds for each latent size k in {2, 3}; k is selected by the seed mean of the
validation hole-macro reconstruction RMSE. PCA of the same rank on the same transformed training data is the linear
reference. A record's score is its mean squared reconstruction residual in transformed units (the three seeds'
mean for the autoencoder); the review threshold is the calibration records' 95th percentile. Constructed alterations
of the test records (``learned/evaluation.py``) measure what the scores notice. The score is compositional
atypicality: it directs review and says nothing about contamination, ore or assay quality. Design:
docs/design/features/geochemical-review/design.md, section 4.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import torch
from learned.contracts import AE_PROPERTIES, SEEDS, canonical_hash
from learned.evaluation import alterations
from learned.exporting import export_model
from learned.features import fit_geochemistry, geochemical_features
from learned.networks import GeochemicalAutoencoder, GeochemicalExport
from learned.training import fit, predict, tensors, weights_sha256
from source_io import stable_hash
from stages.train import _split_rows

MODELS_SCHEMA = "drillhole.geochemistry-models/v1"
PREDICTIONS_SCHEMA = "drillhole.geochemistry-predictions/v1"
METRICS_SCHEMA = "drillhole.geochemistry-metrics/v1"
SCHEME, POPULATION = "hole-group", "rocklea-native-1m"
LATENTS = (2, 3)
EPOCHS, PATIENCE = 300, 30
THRESHOLD_QUANTILE = 0.95
ALTERATION_SEED = 20260926
PARITY_TOLERANCE = 1e-4  # transformed units; the probe of 2026-09-28 measured about 1e-6
MIN_PROPERTIES = 3


def _records(rows: list[dict], properties: list[str]) -> dict:
    complete = [r for r in rows if all(p in r["values"] for p in properties)]
    return {"ids": [r["id"] for r in complete], "holes": np.array([r["hole"] for r in complete]),
            "values": np.array([[r["values"][p] for p in properties] for r in complete], dtype=np.float64
                               ).reshape(-1, len(properties)),
            "incomplete": len(rows) - len(complete)}


def _split(project, pre, dataset, properties):
    scheme = next(s for s in dataset["schemes"] if s["id"] == SCHEME)
    population = next(p for p in pre["populations"] if p["id"] == POPULATION)
    rows = _split_rows(project, pre, scheme, population)
    return {name: _records(rows[name], properties) for name in ("train", "validation", "calibration", "test")}


def _pca(x_train: np.ndarray, rank: int) -> dict:
    mean = x_train.mean(axis=0)
    _, singular, vt = np.linalg.svd(x_train - mean, full_matrices=False)
    explained = singular**2 / np.sum(singular**2)
    return {"rank": rank, "mean": mean.tolist(), "components": vt[:rank].tolist(),
            "explainedVariance": explained[:rank].tolist()}


def pca_scores(x: np.ndarray, pca: dict) -> tuple[np.ndarray, np.ndarray]:
    mean, w = np.asarray(pca["mean"]), np.asarray(pca["components"])
    residual = (x - (mean + (x - mean) @ w.T @ w)) ** 2
    return residual.mean(axis=1), residual


def train_geochemistry(family, project, pre, dataset, target: Path, *, epochs=None, patience=None,
                       latents=None) -> dict:
    epochs, patience = epochs or EPOCHS, patience or PATIENCE
    latents = latents or LATENTS
    units = {a["id"]: a["unit"] for a in project["analytes"]}
    properties = [p for p in AE_PROPERTIES if p in units]
    out = {"schema": MODELS_SCHEMA, "family": family, "scheme": SCHEME, "population": POPULATION,
           "properties": properties, "seeds": list(SEEDS), "latents": list(latents),
           "policy": {"epochs": epochs, "patience": patience, "threshold": THRESHOLD_QUANTILE,
                      "selection": "lowest mean over the three seeds of the validation hole-macro reconstruction "
                                   "RMSE (transformed units)"}}
    if not dataset.get("eligible") or len(properties) < MIN_PROPERTIES or \
            not any(p["id"] == POPULATION for p in pre["populations"]):
        return {**out, "eligible": False,
                "reason": f"needs the {POPULATION} population, a grouped split and at least {MIN_PROPERTIES} of "
                          f"{', '.join(AE_PROPERTIES)}"}
    split = _split(project, pre, dataset, properties)
    transform = fit_geochemistry(split["train"]["values"], properties)
    x = {k: geochemical_features(v["values"], transform) for k, v in split.items()}
    width = len(transform["properties"])
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    configurations = []
    for k in [k for k in latents if k < width]:
        fits = []
        for seed in SEEDS:
            model = GeochemicalAutoencoder(width, k)
            folder = target / "learned" / "geochemistry" / f"latent-{k}" / f"seed-{seed}"
            recipe = {"method": "geochemical-autoencoder", "latent": k, "transform": transform,
                      "trainingRecordsSha256": canonical_hash(sorted(split["train"]["ids"]))}
            result = fit(model, (x["train"],), x["train"], (x["validation"],), x["validation"],
                         split["validation"]["holes"], folder, recipe, seed, dev, scale=1.0, epochs=epochs,
                         patience=patience)
            fits.append({k2: result[k2] for k2 in ("seed", "recipeHash", "bestEpoch", "epochsRun",
                                                    "bestValidationObjective", "fitSeconds", "device",
                                                    "weightsSha256")}
                        | {"folder": folder.relative_to(target).as_posix()})
        configurations.append({"latent": k, "fits": fits})
    chosen = min(configurations, key=lambda c: (np.mean([f["bestValidationObjective"] for f in c["fits"]]),
                                                c["latent"]))
    return {**out, "eligible": True, "transform": transform, "records": {
                k: {"records": len(v["ids"]), "holes": len(set(v["holes"])), "incomplete": v["incomplete"]}
                for k, v in split.items()},
            "configurations": configurations, "selected": chosen["latent"],
            "pca": _pca(x["train"].astype(np.float64), chosen["latent"]),
            "binding": {"projectId": project["id"], "frameId": project["frames"][0]["id"],
                        "task": "compositional review of complete records", "population": POPULATION,
                        "propertyUnits": {p: units[p] for p in transform["properties"]},
                        "datasetSha256": stable_hash(dataset),
                        "trainingRowsSha256": canonical_hash(sorted(split["train"]["ids"]))}}


def _load(width, latent, target, fit_record):
    model = GeochemicalAutoencoder(width, latent)
    weights = target / fit_record["folder"] / "weights.pt"
    if weights_sha256(weights) != fit_record["weightsSha256"]:
        raise ValueError(f"{weights}: the weights do not match geochemistry-models.json; run train again")
    model.load_state_dict(torch.load(weights, weights_only=True, map_location="cpu"))
    return model.eval()


def _ae_scores(models, x, dev):
    per_seed = []
    for m in models:
        recon = predict(m.to(dev), tensors((x,), dev)).cpu().numpy().astype(np.float64)
        m.cpu()
        per_seed.append((x.astype(np.float64) - recon) ** 2)
    residual = np.mean(per_seed, axis=0)
    return residual.mean(axis=1), residual, [r.mean(axis=1) for r in per_seed]


def infer_geochemistry(models_record, project, pre, dataset, target: Path, *, export=True) -> dict:
    out = {"schema": PREDICTIONS_SCHEMA, "family": models_record["family"], "scheme": SCHEME,
           "population": POPULATION}
    if not models_record.get("eligible"):
        return {**out, "eligible": False, "reason": models_record.get("reason")}
    t0 = time.time()
    transform, properties = models_record["transform"], models_record["properties"]
    split = _split(project, pre, dataset, properties)
    if canonical_hash(sorted(split["train"]["ids"])) != models_record["binding"]["trainingRowsSha256"]:
        raise ValueError("the training records changed since train; run train again")
    width, latent = len(transform["properties"]), models_record["selected"]
    chosen = next(c for c in models_record["configurations"] if c["latent"] == latent)
    ae = [_load(width, latent, target, f) for f in chosen["fits"]]
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    def score(values):
        x = geochemical_features(values, transform)
        ae_score, ae_residual, seeds = _ae_scores(ae, x, dev)
        pca_score, _ = pca_scores(x.astype(np.float64), models_record["pca"])
        return ae_score, ae_residual, seeds, pca_score

    records = {}
    for name in ("calibration", "test"):
        s = split[name]
        ae_score, ae_residual, seeds, pca_score = score(s["values"])
        records[name] = [{"id": i, "hole": h, "aeScore": float(a), "aeSeeds": [float(v[j]) for v in seeds],
                          "pcaScore": float(q), "residuals": dict(zip(transform["properties"],
                                                                      map(float, r), strict=True))}
                         for j, (i, h, a, q, r) in enumerate(zip(s["ids"], s["holes"], ae_score, pca_score,
                                                                 ae_residual, strict=True))]
    test = split["test"]
    altered = []
    for kind in alterations(test["values"], test["holes"], properties, transform, ALTERATION_SEED):
        ae_score, _, _, pca_score = score(kind["values"])
        altered.append({"kind": kind["kind"], "severity": kind["severity"], "records": [
            {"parent": test["ids"][i], "altered": bool(kind["altered"][i]), "property": kind["property"][i],
             "donor": None if kind["donor"][i] is None else test["ids"][kind["donor"][i]],
             "aeScore": float(ae_score[i]), "pcaScore": float(pca_score[i])} for i in range(len(test["ids"]))]})
    exports = []
    if export and len(test["ids"]):
        kept = test["values"][:, transform["indices"]]
        for model, f in zip(ae, chosen["fits"], strict=True):
            folder = target / "learned" / "exports" / "geochemistry" / f"seed-{f['seed']}"
            manifest = export_model(
                GeochemicalExport(model, transform["median"], transform["scale"]), (kept,), ["values"], folder,
                {"method": "geochemical-autoencoder", "family": models_record["family"], "latent": latent,
                 "seed": f["seed"], "weightsSha256": f["weightsSha256"], "binding": models_record["binding"],
                 "properties": transform["properties"],
                 "features": {"input": "native values of the properties, in order", "transform": "asinh((x - median)"
                              " / iqr)", "median": transform["median"], "iqr": transform["scale"]}},
                tolerance=PARITY_TOLERANCE,
                outputs={"latent": "latent units", "residual": "squared transformed units",
                         "score": "squared transformed units"})
            exports.append({"seed": f["seed"], "folder": folder.relative_to(target).as_posix(),
                            "model": manifest["model"], "parity": manifest["parity"]})
    return {**out, "eligible": True, "latent": latent, "properties": transform["properties"], "records": records,
            "alterations": altered, "exports": exports, "seconds": round(time.time() - t0, 2)}


def evaluate_geochemistry(predictions: dict) -> dict:
    out = {"schema": METRICS_SCHEMA, "family": predictions["family"], "inputPredictionsSha256":
           stable_hash(predictions)}
    if not predictions.get("eligible"):
        return {**out, "eligible": False, "reason": predictions.get("reason")}
    calibration, test = predictions["records"]["calibration"], predictions["records"]["test"]
    thresholds = {m: float(np.quantile([r[f"{m}Score"] for r in calibration], THRESHOLD_QUANTILE, method="higher"))
                  for m in ("ae", "pca")}
    kinds = {}
    for kind in predictions["alterations"]:
        altered = [r for r in kind["records"] if r["altered"]]
        reference = [r for r in kind["records"] if not r["altered"]]
        entry = {"severity": kind["severity"], "altered": len(altered)}
        for m in ("ae", "pca"):
            if kind["kind"] == "unchanged":
                entry[m] = {"falseFlags": float(np.mean([r[f"{m}Score"] > thresholds[m] for r in reference]))}
            else:
                entry[m] = {"recall": float(np.mean([r[f"{m}Score"] > thresholds[m] for r in altered]))
                            if altered else None}
        kinds[kind["kind"]] = entry
    ae, pca = np.array([r["aeScore"] for r in test]), np.array([r["pcaScore"] for r in test])
    properties = predictions["properties"]
    top = sorted(test, key=lambda r: -r["aeScore"])[:10]
    return {**out, "eligible": True, "latent": predictions["latent"], "thresholds": thresholds,
            "quantile": THRESHOLD_QUANTILE, "calibrationRecords": len(calibration), "testRecords": len(test),
            "testScores": {"ae": {"mean": float(ae.mean()), "median": float(np.median(ae))},
                           "pca": {"mean": float(pca.mean()), "median": float(np.median(pca))}},
            "residualByProperty": {p: float(np.mean([r["residuals"][p] for r in test])) for p in properties},
            "alterations": kinds,
            "highestTestRecords": [{k: r[k] for k in ("id", "hole", "aeScore", "pcaScore")} for r in top],
            "note": "compositional atypicality: a high score directs review; it is not contamination, ore or an "
                    "invalid assay, and the alterations test detection of those alterations only"}
