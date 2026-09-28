"""The categorical lane (SD-6): conditioning and training images (train), SNESIM and Direct Sampling realizations
(infer), and their scores on held-out holes (evaluate).

Design: docs/design/features/categorical-simulation/design.md. A family takes part when it has a reviewed lithology
mapping (``data/interpretations/<family>-lithology-v1.json``) and a grouped split; otherwise its outputs say why not.
Conditioning uses the training holes of each split only. Both engines produce the same number of realizations, so
their ensemble scores are comparable; every realization is reproducible from its recorded seed. Truth values of the
held-out holes are read in ``evaluate_categorical`` and nowhere earlier.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from scipy import ndimage
from source_io import stable_hash
from stages import mps
from stages.categories import Grid, cell_lengths, collar_surface, conditioning, load_mapping, map_lithology
from stages.preprocess import build_surveys
from stages.training_images import PRIORS, author, cover_statistics, granitoid_proportion

MODELS_SCHEMA = "drillhole.categorical-models/v1"
PREDICTIONS_SCHEMA = "drillhole.categorical-predictions/v1"
METRICS_SCHEMA = "drillhole.categorical-metrics/v1"
ENGINES = ("snesim", "direct-sampling")
REALIZATIONS = 32
TI_SEED = 20260926
MPS_SEED = 20260926 % mps.SEED_LIMIT  # MPSlib parses the seed as a float; below 2^24 it is exact
DS_SEED = 20260926
DS_SETTINGS = {"max_neighbors": 24, "threshold": 0.05, "scan_fraction": 0.25}  # 0.05: "a low threshold" (Mariethoz 2010)
SNESIM_SECONDS_PER_REALIZATION = 300  # the supervision limit of one SNESIM run is this times its count
VPC_PSEUDOCOUNT = 2.0
VPC_MIN_CELLS = 5
LOG_FLOOR = 1e-3
PERSISTENT, ABSENT, PRIOR_GAP = 0.9, 0.1, 0.5
CONNECTED = ndimage.generate_binary_structure(3, 1)  # 6-connectivity: cells sharing a face


def _sha(array: np.ndarray) -> str:
    a = np.ascontiguousarray(array)
    return hashlib.sha256(f"{a.dtype}{a.shape}".encode() + a.tobytes()).hexdigest()


def _workers() -> int:
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def vertical_proportions(hard, layers: int, categories: int):
    """The training cells' proportion of each category per layer, shrunk toward the global proportions with a small
    pseudo-count, and carried from the nearest layer with enough cells where a layer has too few."""
    counts = np.zeros((layers, categories))
    for h in hard:
        counts[h["cell"][2], h["category"]] += 1
    total = counts.sum()
    glob = counts.sum(axis=0) / total if total else np.full(categories, 1.0 / categories)
    vpc = (counts + VPC_PSEUDOCOUNT * glob) / (counts.sum(axis=1, keepdims=True) + VPC_PSEUDOCOUNT)
    enough = np.flatnonzero(counts.sum(axis=1) >= VPC_MIN_CELLS)
    if len(enough):
        source = np.array([enough[np.argmin(np.abs(enough - k))] for k in range(layers)])
        vpc = vpc[source]
    return vpc, counts, glob


def soft_grid(vpc: np.ndarray, ti_proportions, shape) -> np.ndarray:
    """MPSlib soft probabilities whose normalized product with the TI's conditional pdf is the conditional-independence
    aggregation: soft(k | layer) proportional to VPC(k | layer) / p_TI(k)."""
    p = np.asarray(ti_proportions, dtype=float)
    ratio = np.where(p > 0, vpc / np.where(p > 0, p, 1.0), 0.0)
    ratio /= ratio.sum(axis=1, keepdims=True)
    return np.broadcast_to(ratio[None, None, :, :], (*shape[:2], *ratio.shape)).copy()


def train_categorical(family: str, project: dict, dataset: dict, out_dir: Path) -> dict:
    base = {"schema": MODELS_SCHEMA, "family": family}
    mapping = load_mapping(family)
    if mapping is None:
        return {**base, "eligible": False, "reason": "no reviewed lithology mapping for this family"}
    if not dataset.get("eligible"):
        return {**base, "eligible": False, "reason": dataset.get("reason", "no grouped split")}
    lith = map_lithology(project, mapping)
    surveys, surface = build_surveys(project), collar_surface(project["collars"])
    grid = Grid.from_mapping(mapping)
    k = len(mapping["categories"])
    folder = Path(out_dir) / "categorical"
    folder.mkdir(parents=True, exist_ok=True)
    schemes = []
    for scheme in dataset["schemes"]:
        train = sorted(h for h, s in scheme["assignment"].items() if s == "train")
        lengths, holes, outside = cell_lengths(lith["rows"], surveys, surface, grid, set(train),
                                               mapping["grid"]["traceStep"])
        cond = conditioning(lengths, holes, mapping["grid"]["majority"])
        cover = cover_statistics(lith["rows"], surveys, surface, set(train))
        granitoid = granitoid_proportion(cond["hard"])
        vpc, counts, glob = vertical_proportions(cond["hard"], grid.shape[2], k)
        images = []
        for index, prior in enumerate(PRIORS):
            ti, record = author(prior, grid.cell, grid.shape[2], cover, granitoid, TI_SEED + index)
            name = f"ti-{scheme['id']}-{prior}.npy"
            np.save(folder / name, ti)
            images.append({**record, "file": f"categorical/{name}"})
        schemes.append({
            "scheme": scheme["id"], "trainHoles": train,
            "conditioning": {**cond, "outsideLength": outside, "cells": len(cond["hard"])},
            "cover": cover, "granitoidProportion": granitoid,
            "verticalProportions": {"pseudoCount": VPC_PSEUDOCOUNT, "minCells": VPC_MIN_CELLS,
                                    "global": glob.tolist(), "counts": counts.tolist(), "layers": vpc.tolist()},
            "trainingImages": images})
    return {**base, "eligible": True, "mapping": lith, "categories": mapping["categories"],
            "grid": {**grid.record(), "vertical": mapping["grid"]["vertical"], "traceStep": mapping["grid"]["traceStep"],
                     "majority": mapping["grid"]["majority"]},
            "surface": {"method": "inverse distance, power 2, exact at every collar", "collars": len(project["collars"])},
            "schemes": schemes}


def _hard(scheme_record):
    hard = scheme_record["conditioning"]["hard"]
    return np.array([h["cell"] for h in hard], dtype=np.int64).reshape(-1, 3), np.array([h["category"] for h in hard])


def ds_realization(ti: np.ndarray, shape, cells, categories, seed: int, backend: str = "numpy"):
    """One zoned Direct Sampling realization (uint8) and its statistics; each depth layer scans its own TI layer."""
    from geocond import direct_sampling

    layers = shape[2]
    ti_zones = np.broadcast_to(np.arange(layers)[None, None, :], ti.shape).astype(np.int64)
    grid_zones = np.broadcast_to(np.arange(layers)[None, None, :], tuple(shape)).astype(np.int64)
    t0 = time.time()
    result = direct_sampling(ti.astype(float), tuple(shape), variable_kinds=["categorical"],
                             hard_data=(cells, categories.astype(float)), seed=seed, backend=backend,
                             zones=(ti_zones, grid_zones), **DS_SETTINGS)
    field = result.realization[..., 0]
    if not result.complete:
        raise RuntimeError(f"Direct Sampling left {int(result.failed.sum())} cells unsimulated (seed {seed})")
    simulated = result.candidate >= 0
    return field.astype(np.uint8), {"seed": seed, "seconds": round(time.time() - t0, 2),
                                    "fallbacks": int(result.fallback.sum()), "simulated": int(simulated.sum()),
                                    "meanScanned": float(result.scanned[simulated].mean()),
                                    "candidateSha256": _sha(result.candidate)}


def _ds_task(args):
    ti_path, shape, cells, categories, seed = args
    return ds_realization(np.load(ti_path), shape, cells, categories, seed)


def _saved(folder: Path, name: str, inputs: str):
    """A finished piece of work (an array and its record) when its recorded inputs and hash still match, else None."""
    array_path, record_path = folder / f"{name}.npy", folder / f"{name}.json"
    if not (array_path.is_file() and record_path.is_file()):
        return None
    record = json.loads(record_path.read_text(encoding="utf-8"))
    array = np.load(array_path)
    if record.get("inputs") != inputs or record.get("sha256") != _sha(array):
        return None
    return array, record


def _save(folder: Path, name: str, inputs: str, array: np.ndarray, record: dict):
    """Write a finished piece at once, so an interrupted run loses only what was still running."""
    folder.mkdir(parents=True, exist_ok=True)
    np.save(folder / f"{name}.npy", array)
    (folder / f"{name}.json").write_text(json.dumps({**record, "inputs": inputs, "sha256": _sha(array)}),
                                         encoding="utf-8")


def infer_categorical(models: dict, out_dir: Path) -> dict:
    """SNESIM and Direct Sampling realizations for every scheme and prior. Each SNESIM run and each Direct Sampling
    realization is saved as it finishes, with a hash of its inputs; a rerun reuses the pieces whose inputs match."""
    base = {"schema": PREDICTIONS_SCHEMA, "family": models["family"], "realizations": REALIZATIONS}
    if not models.get("eligible"):
        return {**base, "eligible": False, "reason": models.get("reason")}
    out_dir = Path(out_dir)
    shape = tuple(models["grid"]["shape"])
    categories = [c["code"] for c in models["categories"]]
    folder = out_dir / "categorical"
    pieces = folder / "pieces"
    runs, snesim_jobs, ds_jobs, done = [], [], [], {}
    for s in models["schemes"]:
        cells, cats = _hard(s)
        for image in s["trainingImages"]:
            ti_path = out_dir / image["file"]
            ti = np.load(ti_path)
            if image["sha256"] != hashlib.sha256(np.ascontiguousarray(ti).tobytes()).hexdigest():
                raise ValueError(f"{image['file']} does not match its record")
            proportions = [image["proportions"][str(c)] for c in categories]
            soft = soft_grid(np.array(s["verticalProportions"]["layers"]), proportions, shape)
            key = (s["scheme"], image["prior"])
            common = {"ti": image["sha256"], "hard": _sha(cells), "categories": _sha(cats), "shape": list(shape)}
            name = f"snesim-{key[0]}-{key[1]}"
            inputs = stable_hash({**common, "soft": _sha(soft), "seed": MPS_SEED, "realizations": REALIZATIONS,
                                  "engine": mps.COMMIT, "options": mps.DEFAULTS})
            done[name] = _saved(pieces, name, inputs)
            if done[name] is None:
                snesim_jobs.append((name, inputs, ti, soft, cells, cats))
            for r in range(REALIZATIONS):
                name = f"ds-{key[0]}-{key[1]}-{r:02d}"
                inputs = stable_hash({**common, "seed": DS_SEED + r, "settings": DS_SETTINGS, "zones": "depth layer"})
                done[name] = _saved(pieces, name, inputs)
                if done[name] is None:
                    ds_jobs.append((name, inputs, (str(ti_path), shape, cells, cats, DS_SEED + r)))
    t0 = time.time()
    if snesim_jobs or ds_jobs:
        with ThreadPoolExecutor(max_workers=max(1, len(snesim_jobs))) as threads, \
                ProcessPoolExecutor(_workers()) as processes:
            futures = {}
            for name, inputs, ti, soft, cells, cats in snesim_jobs:
                futures[threads.submit(mps.simulate, ti, shape, realizations=REALIZATIONS, seed=MPS_SEED,
                                       hard=(cells, cats), soft=soft, categories=categories,
                                       job_dir=folder / "jobs" / name,
                                       timeout=SNESIM_SECONDS_PER_REALIZATION * REALIZATIONS)] = (name, inputs, "snesim")
            for name, inputs, args in ds_jobs:
                futures[processes.submit(_ds_task, args)] = (name, inputs, "ds")
            failures = []
            for future in as_completed(futures):
                name, inputs, kind = futures[future]
                try:
                    array, record = future.result()
                except Exception as error:  # noqa: BLE001 - recorded, and the stage fails after the others finish
                    failures.append(f"{name}: {error}")
                    continue
                if kind == "snesim":
                    record = {"receipt": {k: v for k, v in record.items() if k != "parameterFile"},
                              "parameterFile": record["parameterFile"]}
                _save(pieces, name, inputs, array, record)
                done[name] = (array, {**record, "inputs": inputs})
            if failures:
                raise RuntimeError("categorical realizations failed (finished pieces are saved): " + "; ".join(failures))
    for s in models["schemes"]:
        cells, cats = _hard(s)
        for image in s["trainingImages"]:
            key = (s["scheme"], image["prior"])
            fields, snesim_record = done[f"snesim-{key[0]}-{key[1]}"]
            outputs = {"snesim": (fields, {k: v for k, v in snesim_record.items() if k not in ("inputs", "sha256")})}
            stats = [done[f"ds-{key[0]}-{key[1]}-{r:02d}"] for r in range(REALIZATIONS)]
            ds_fields = np.stack([x[0] for x in stats])
            stats = [{k: v for k, v in x[1].items() if k not in ("inputs", "sha256")} for x in stats]
            outputs["direct-sampling"] = (ds_fields, {
                "settings": {**DS_SETTINGS, "zones": "one per depth layer"}, "seeds": [x["seed"] for x in stats],
                "fallbackFraction": float(np.mean([x["fallbacks"] / x["simulated"] for x in stats])),
                "meanScanned": float(np.mean([x["meanScanned"] for x in stats])),
                "seconds": float(sum(x["seconds"] for x in stats)), "realizationStats": stats})
            for engine, (field_stack, extra) in outputs.items():
                honoured = bool((field_stack[:, cells[:, 0], cells[:, 1], cells[:, 2]] == cats[None, :]).all())
                if not honoured:
                    raise RuntimeError(f"{engine} changed a conditioning cell in {key}")
                name = f"real-{key[0]}-{key[1]}-{engine}.npy"
                np.save(folder / name, field_stack)
                runs.append({"scheme": key[0], "prior": key[1], "engine": engine, "file": f"categorical/{name}",
                             "sha256": _sha(field_stack), "realizations": int(field_stack.shape[0]),
                             "hardHonoured": honoured, "hardCells": len(cats), **extra})
    return {**base, "eligible": True, "engines": list(ENGINES), "priors": list(PRIORS),
            "computedSeconds": round(time.time() - t0, 1), "runs": runs}


def category_probabilities(fields: np.ndarray, cells: np.ndarray, categories) -> np.ndarray:
    """Per target cell, the fraction of realizations holding each category."""
    values = fields[:, cells[:, 0], cells[:, 1], cells[:, 2]]
    return np.stack([np.mean(values == c, axis=0) for c in categories], axis=1)


def scores(prob: np.ndarray, truth: np.ndarray, categories) -> dict:
    """Multi-category Brier score (0 to 2), log score with a floor, and accuracy of the most probable category."""
    if not len(truth):
        return {"n": 0}
    outcome = np.stack([truth == c for c in categories], axis=1).astype(float)
    brier = float(np.mean(np.sum((prob - outcome) ** 2, axis=1)))
    p_true = np.clip(np.sum(prob * outcome, axis=1), LOG_FLOOR, 1.0)
    best = np.asarray(categories)[np.argmax(prob, axis=1)]
    return {"n": len(truth), "brier": brier, "logScore": float(-np.mean(np.log(p_true))),
            "accuracy": float(np.mean(best == truth))}


def connectivity(field: np.ndarray, category: int) -> dict:
    """Renard and Allard (2013): H, the share of the category in its largest 6-connected cluster, and
    C = (1/n^2) sum n_i^2, the probability that two of its cells are connected."""
    labels, count = ndimage.label(field == category, structure=CONNECTED)
    sizes = np.bincount(labels.ravel())[1:]
    n = sizes.sum()
    if n == 0:
        return {"cells": 0, "clusters": 0, "H": None, "C": None}
    return {"cells": int(n), "clusters": int(count), "H": float(sizes.max() / n), "C": float((sizes ** 2).sum() / n ** 2)}


def hole_connections(fields: np.ndarray, hole_cells: dict, category: int) -> dict:
    """For every pair of holes that both hold ``category`` in conditioning cells, the fraction of realizations in which
    those cells meet in one 6-connected cluster of the category."""
    holes = sorted(h for h, cells in hole_cells.items() if len(cells))
    hits = {pair: 0 for pair in itertools.combinations(holes, 2)}
    for field in fields:
        labels, _ = ndimage.label(field == category, structure=CONNECTED)
        own = {h: set(labels[c[:, 0], c[:, 1], c[:, 2]].tolist()) - {0} for h, c in hole_cells.items() if len(c)}
        for a, b in hits:
            hits[(a, b)] += bool(own[a] & own[b])
    return {f"{a}|{b}": v / len(fields) for (a, b), v in hits.items()}


def _summary(values):
    v = np.array([x for x in values if x is not None], dtype=float)
    if not len(v):
        return None
    return {"mean": float(v.mean()), "p10": float(np.quantile(v, 0.1)), "p90": float(np.quantile(v, 0.9))}


def evaluate_categorical(project: dict, dataset: dict, models: dict, predictions: dict, out_dir: Path) -> dict:
    base = {"schema": METRICS_SCHEMA, "family": models["family"]}
    if not predictions.get("eligible"):
        return {**base, "eligible": False, "reason": predictions.get("reason")}
    out_dir = Path(out_dir)
    categories = [c["code"] for c in models["categories"]]
    grid = Grid(tuple(models["grid"]["origin"]), tuple(models["grid"]["cell"]), tuple(models["grid"]["shape"]))
    surveys, surface = build_surveys(project), collar_surface(project["collars"])
    rows = models["mapping"]["rows"]
    by_scheme = {s["id"]: s for s in dataset["schemes"]}
    out = []
    for s in models["schemes"]:
        scheme = by_scheme[s["scheme"]]
        test = sorted(h for h, v in scheme["assignment"].items() if v == "test")
        lengths, holes, _ = cell_lengths(rows, surveys, surface, grid, set(test), models["grid"]["traceStep"])
        truth_cond = conditioning(lengths, holes, models["grid"]["majority"])
        cells = np.array([h["cell"] for h in truth_cond["hard"]], dtype=np.int64).reshape(-1, 3)
        truth = np.array([h["category"] for h in truth_cond["hard"]])
        train_cells = {tuple(h["cell"]) for h in s["conditioning"]["hard"]}
        informed = np.array([tuple(c) in train_cells for c in cells.tolist()], dtype=bool)
        vpc = np.array(s["verticalProportions"]["layers"])
        glob = np.array(s["verticalProportions"]["global"])
        references = {"trainingProportions": np.broadcast_to(glob, (len(truth), len(categories))),
                      "verticalProportions": vpc[cells[:, 2]] if len(cells) else np.zeros((0, len(categories)))}
        hole_cells = {}
        for h in s["conditioning"]["hard"]:
            for hole in h["holes"]:
                hole_cells.setdefault(hole, {}).setdefault(h["category"], []).append(h["cell"])
        record = {"scheme": s["scheme"], "testHoles": test, "testCells": len(truth),
                  "testCellsInformedByTraining": int(informed.sum()), "testConflicts": len(truth_cond["conflicts"]),
                  "truthProportions": {str(c): float(np.mean(truth == c)) if len(truth) else None for c in categories},
                  "references": {name: {"all": scores(p, truth, categories),
                                        "uninformed": scores(p[~informed], truth[~informed], categories)}
                                 for name, p in references.items()},
                  "runs": []}
        for run in (r for r in predictions["runs"] if r["scheme"] == s["scheme"]):
            fields = np.load(out_dir / run["file"])
            if _sha(fields) != run["sha256"]:
                raise ValueError(f"{run['file']} does not match its record")
            prob = category_probabilities(fields, cells, categories) if len(cells) else np.zeros((0, len(categories)))
            entry = {"prior": run["prior"], "engine": run["engine"], "realizations": len(fields),
                     "all": scores(prob, truth, categories),
                     "uninformed": scores(prob[~informed], truth[~informed], categories),
                     "proportions": {str(c): float(np.mean(fields == c)) for c in categories},
                     "hardHonoured": run["hardHonoured"]}
            for name in references:
                ref = record["references"][name]["all"]
                entry.setdefault("brierSkill", {})[name] = (None if not ref.get("brier") else
                                                           1.0 - entry["all"]["brier"] / ref["brier"])
            entry["connectivity"] = {}
            for c in categories:
                per = [connectivity(f, c) for f in fields]
                entry["connectivity"][str(c)] = {"H": _summary(x["H"] for x in per), "C": _summary(x["C"] for x in per),
                                                 "clusters": _summary(x["clusters"] for x in per)}
            entry["holeConnections"] = {str(c): hole_connections(
                fields, {h: np.array(v.get(c, []), dtype=np.int64).reshape(-1, 3) for h, v in hole_cells.items()}, c)
                for c in categories}
            record["runs"].append(entry)
        record["persistence"] = _persistence(record["runs"], categories)
        out.append(record)
    return {**base, "eligible": True, "logFloor": LOG_FLOOR, "categories": models["categories"], "schemes": out}


def _persistence(runs, categories) -> dict:
    """Per category and hole pair: persistent (connected in at least 90 % of realizations in every prior and engine),
    absent (at most 10 % in all), or prior-dependent (the two priors' means, over engines, differ by 0.5 or more)."""
    out = {}
    priors = sorted({r["prior"] for r in runs})
    for c in categories:
        pairs = sorted({p for r in runs for p in r["holeConnections"][str(c)]})
        counts = {"pairs": len(pairs), "persistent": [], "absent": 0, "priorDependent": [], "other": 0}
        for pair in pairs:
            values = [r["holeConnections"][str(c)].get(pair, 0.0) for r in runs]
            by_prior = {p: np.mean([r["holeConnections"][str(c)].get(pair, 0.0) for r in runs if r["prior"] == p])
                        for p in priors}
            if min(values) >= PERSISTENT:
                counts["persistent"].append(pair)
            elif max(values) <= ABSENT:
                counts["absent"] += 1
            elif len(priors) == 2 and abs(by_prior[priors[0]] - by_prior[priors[1]]) >= PRIOR_GAP:
                counts["priorDependent"].append({"pair": pair, **{p: float(v) for p, v in by_prior.items()}})
            else:
                counts["other"] += 1
        out[str(c)] = counts
    return out

