#!/usr/bin/env python3
"""Sondara's offline pipeline, stage by stage. Plain scripts run by path; the product declares no package.

    python data-pipeline/run.py acquire [--cache DIR]
    python data-pipeline/run.py ingest  [--family rocklea|alberta|ntgs|all] [--cache DIR] [--out DIR]
    python data-pipeline/run.py ingest  --manifest import.json [--out DIR]
    python data-pipeline/run.py preprocess [--family rocklea|alberta|ntgs|all|<project id>] [--out DIR]
    python data-pipeline/run.py dataset    [--family ...] [--out DIR]
    python data-pipeline/run.py features   [--family ...] [--out DIR]
    python data-pipeline/run.py train      [--family ...] [--out DIR]
    python data-pipeline/run.py infer      [--family ...] [--out DIR]
    python data-pipeline/run.py evaluate   [--family ...] [--out DIR]

``acquire`` fetches the pinned sources of ``data/sources/manifest.json`` (or copies the bundled licensed subset),
checking every byte count and SHA-256, and writes an acquisition receipt. ``ingest`` builds each family's canonical
project (``drillhole.project/v2``), its QA issue table and its reconciliation waterfall, and writes them with a hash;
with ``--manifest`` it imports user files described by an import manifest instead, as a transaction that commits only
an accepted project and always writes ``<project id>.import-report.json``. ``preprocess`` reads a project, checks its
hash against the ingest summary, and writes the desurveyed positions, result selections, composites, log overlays and
modeling populations (``stages/preprocess.py``, on GeoCond); for an imported project it takes the compositing options
and method priority from the stored manifest. ``dataset`` freezes the grouped splits of each family (hole-group,
spatial-margin and a declared holdout) before any fit, and ``features`` computes training-only statistics,
declustering and experimental variograms (``stages/dataset.py``, ``stages/features.py``). ``train`` fits and selects
the covariance models on training and validation rows (``stages/train.py``), and ``infer`` predicts the test rows with
the eight classical methods (``stages/infer.py``). ``evaluate`` scores them against the test truths and rebuilds the
scenario matrix ``<out>/scenarios.json`` (``stages/evaluate.py``, ``stages/scenarios.py``). For a family with a reviewed
lithology mapping, the same three stages run the categorical lane (``stages/categorical.py``): conditioning and training
images, SNESIM (MPSlib, ``scripts/build_mpslib.sh``) and Direct Sampling realizations, and their scores. The learned
lane (``stages/learned.py``, PyTorch and ONNX, run in ``.venv-gpu``) trains DeepKriging and KCN on the same splits,
predicts the same targets, exports each fit to ONNX with its parity, and ``evaluate`` scores them beside the
classical methods. ``--lane`` runs one lane alone. Each stage checks the hash of
its input. Raw sources live outside the repository (``--cache``, default ``$SONDARA_RAW`` or ``build/sources``); derived
outputs go to ``--out`` (default ``build/derived``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from source_io import ROOT, acquire, load_json, stable_hash, write_json

FAMILIES = ("rocklea", "alberta", "ntgs")
COUNTED = ("collars", "surveys", "trajectories", "analytes", "supports", "determinations", "geology", "qc",
           "exclusions", "issues")


def _adapter(family: str):
    if family == "rocklea":
        from source_adapters.rocklea import normalize
    elif family == "alberta":
        from source_adapters.alberta import normalize
    else:
        from source_adapters.ntgs import normalize
    return normalize


def ingest(family: str, cache: Path, out: Path) -> dict:
    t0 = time.time()
    project = _adapter(family)(cache)
    target = out / family
    write_json(target / "project.json", project)
    summary = {
        "schema": "drillhole.ingest-summary/v1",
        "family": family,
        "projectSha256": stable_hash(project),
        "recipe": project["provenance"]["recipe"],
        "recipeSha256": project["provenance"]["recipeSha256"],
        "counts": {k: len(project[k]) for k in COUNTED},
        "waterfall": project.get("waterfall", []),
        "issues": [{"code": i["code"], "severity": i["severity"], "rows": len(i["rowIds"])} for i in project["issues"]],
        "seconds": round(time.time() - t0, 2),
    }
    if family == "rocklea":  # the hyperspectral export and the files of its lineage (unit SD-7b)
        from source_adapters.rocklea_spectral import normalize as spectral

        source = spectral(cache)
        write_json(target / "spectral-source.json", source)
        summary["spectralSourceSha256"] = stable_hash(source)
        summary["spectralRows"] = len(source["rows"])
    write_json(target / "summary.json", summary, pretty=True)
    return summary


def ingest_manifest(manifest: Path, out: Path, cancel=None) -> dict:
    from source_adapters.manifest_import import run_import

    return run_import(manifest, out, cancel)


def preprocess(family: str, out: Path) -> dict:
    from stages.preprocess import preprocess as run_stage

    t0 = time.time()
    target = out / family
    project = load_json(target / "project.json")
    ingest_summary = load_json(target / "summary.json")
    project_sha = stable_hash(project)
    if ingest_summary["projectSha256"] != project_sha:
        raise ValueError(f"{family}: project.json does not match its ingest summary; run ingest again")
    options = {}
    if (target / "import.json").is_file():
        manifest = load_json(target / "import.json")
        compositing = manifest.get("compositing", {})
        options = {**({"lengths": compositing["lengths"]} if "lengths" in compositing else {}),
                   **({"minCoverage": compositing["minCoverage"]} if "minCoverage" in compositing else {}),
                   "methodPriority": manifest.get("methodPriority", {})}
    result = run_stage(family, project, project_sha, options)
    write_json(target / "preprocessed.json", result)
    summary = {
        "schema": "drillhole.preprocess-summary/v1",
        "family": family,
        "preprocessedSha256": stable_hash(result),
        "inputProjectSha256": project_sha,
        "recipeSha256": result["recipeSha256"],
        "engine": result["engine"],
        "waterfall": result["waterfall"],
        "populations": [{k: p[k] for k in ("id", "task", "support", "count", "holes", "excluded")}
                        for p in result["populations"]],
        "seconds": round(time.time() - t0, 2),
    }
    write_json(target / "preprocess-summary.json", summary, pretty=True)
    return summary


def _stored_manifest(target: Path) -> dict:
    return load_json(target / "import.json") if (target / "import.json").is_file() else {}


def _preprocessed(family: str, out: Path):
    target = out / family
    project = load_json(target / "project.json")
    pre = load_json(target / "preprocessed.json")
    project_sha, pre_sha = stable_hash(project), stable_hash(pre)
    if pre["inputProjectSha256"] != project_sha:
        raise ValueError(f"{family}: preprocessed.json was built from another project; run preprocess again")
    if load_json(target / "preprocess-summary.json")["preprocessedSha256"] != pre_sha:
        raise ValueError(f"{family}: preprocessed.json does not match its summary; run preprocess again")
    return target, project, pre, project_sha, pre_sha


def dataset(family: str, out: Path) -> dict:
    from stages.dataset import split_family

    target, project, pre, project_sha, pre_sha = _preprocessed(family, out)
    holdout = _stored_manifest(target).get("holdout")
    result = split_family(family, project, pre, project_sha, pre_sha, holdout=holdout)
    write_json(target / "dataset.json", result, pretty=True)
    return {"family": family, "eligible": result["eligible"],
            "schemes": {s["id"]: s["holeCounts"] for s in result["schemes"]}}


def features(family: str, out: Path) -> dict:
    from stages.features import family_features

    t0 = time.time()
    target, project, pre, project_sha, pre_sha = _preprocessed(family, out)
    split = load_json(target / "dataset.json")
    if (split["inputProjectSha256"], split["inputPreprocessedSha256"]) != (project_sha, pre_sha):
        raise ValueError(f"{family}: dataset.json was built from other inputs; run dataset again")
    manifest = _stored_manifest(target)
    result = family_features(family, project, pre, split, orientations=manifest.get("orientations"))
    result["inputDatasetSha256"] = stable_hash(split)
    write_json(target / "features.json", result)
    summary = {"family": family, "eligible": result["eligible"], "schemes": len(result["schemes"])}
    lineage = _spectral_lineage(family, target, project)
    if lineage is not None:
        summary["spectralRegistration"] = lineage["registration"]["counts"]
    return {**summary, "seconds": round(time.time() - t0, 2)}


def _spectral_lineage(family: str, target: Path, project: dict):
    """R12: the lineage of the supplied hyperspectral export, where the family has one and a reviewed mapping."""
    from stages.spectral import lineage, load_mapping

    mapping = load_mapping(family)
    if mapping is None or not (target / "spectral-source.json").is_file():
        return None
    source = load_json(target / "spectral-source.json")
    if load_json(target / "summary.json").get("spectralSourceSha256") != stable_hash(source):
        raise ValueError(f"{family}: spectral-source.json does not match its ingest summary; run ingest again")
    result = lineage(project, source, mapping)
    result.update(inputProjectSha256=stable_hash(project), inputSpectralSourceSha256=stable_hash(source))
    write_json(target / "spectral-lineage.json", result, pretty=True)
    return result


def _chain(family: str, out: Path):
    target, project, pre, project_sha, pre_sha = _preprocessed(family, out)
    split = load_json(target / "dataset.json")
    if (split["inputProjectSha256"], split["inputPreprocessedSha256"]) != (project_sha, pre_sha):
        raise ValueError(f"{family}: dataset.json was built from other inputs; run dataset again")
    return target, project, pre, split


LANES = ("all", "continuous", "categorical", "learned")


def _learned_stages():
    """The learned lane's stage module; it needs PyTorch, onnx and ONNX Runtime (requirements-gpu.txt)."""
    try:
        from stages import learned
    except ImportError as error:
        raise SystemExit(f"the learned lane needs PyTorch, onnx and ONNX Runtime ({error}); run it in .venv-gpu "
                         "(requirements-gpu.txt), or pass --lane continuous or --lane categorical") from error
    return learned


def train(family: str, out: Path, lane: str = "all") -> dict:
    from stages.categorical import train_categorical
    from stages.train import train_family

    t0 = time.time()
    target, project, pre, split = _chain(family, out)
    summary = {"family": family}
    if lane in ("all", "learned"):
        learned = _learned_stages()
        features_record = load_json(target / "features.json")
        if features_record["inputDatasetSha256"] != stable_hash(split):
            raise ValueError(f"{family}: features.json was computed from another dataset; run features again")
        result = learned.train_learned(family, project, pre, split, features_record, target)
        result["inputFeaturesSha256"] = stable_hash(features_record)
        write_json(target / "learned-models.json", result)
        fitted = [p for s in result["schemes"] for p in s["populations"]]
        summary["learned"] = {"eligible": result["eligible"], "populations": len(fitted),
                              "fitted": sum(p.get("status") == "fitted" for p in fitted)}
        from stages.geochemistry import train_geochemistry  # R12: the geochemical review

        review = train_geochemistry(family, project, pre, split, target)
        review["inputDatasetSha256"] = stable_hash(split)
        write_json(target / "geochemistry-models.json", review, pretty=True)
        summary["geochemistry"] = review["eligible"]
    if lane in ("all", "continuous"):
        features_record = load_json(target / "features.json")
        if features_record["inputDatasetSha256"] != stable_hash(split):
            raise ValueError(f"{family}: features.json was computed from another dataset; run features again")
        result = train_family(family, project, pre, split, features_record)
        result["inputFeaturesSha256"] = stable_hash(features_record)
        write_json(target / "models.json", result)
        if (target / "spectral-lineage.json").is_file():  # R12: the iron-oxide index, fitted on training holes
            from stages.spectral import fit_index, load_mapping

            lineage = load_json(target / "spectral-lineage.json")
            if lineage["inputProjectSha256"] != stable_hash(project):
                raise ValueError(f"{family}: spectral-lineage.json was built from another project; run features again")
            spectral = fit_index(project, pre, split, load_json(target / "spectral-source.json"), lineage,
                                 load_mapping(family))
            spectral["inputDatasetSha256"] = stable_hash(split)
            write_json(target / "spectral-models.json", spectral, pretty=True)
            summary["spectral"] = {"train": spectral["train"]["rows"], "test": len(spectral["test"])}
        fitted = [p for s in result["schemes"] for p in s["populations"]]
        summary.update(eligible=result["eligible"], populations=len(fitted),
                       fitted=sum(p["status"] == "fitted" for p in fitted))
    if lane in ("all", "categorical"):
        categorical = train_categorical(family, project, split, target)
        categorical.update(inputProjectSha256=stable_hash(project), inputDatasetSha256=stable_hash(split))
        write_json(target / "categorical-models.json", categorical)
        summary["categorical"] = categorical["eligible"]
    return {**summary, "seconds": round(time.time() - t0, 1)}


def infer(family: str, out: Path, lane: str = "all") -> dict:
    from stages.categorical import infer_categorical
    from stages.infer import infer_family

    t0 = time.time()
    target, project, pre, split = _chain(family, out)
    summary = {"family": family}
    if lane in ("all", "continuous"):
        models = load_json(target / "models.json")
        if models["inputFeaturesSha256"] != stable_hash(load_json(target / "features.json")):
            raise ValueError(f"{family}: models.json was fitted on other features; run train again")
        result = infer_family(family, project, pre, split, models)
        result["inputModelsSha256"] = stable_hash(models)
        write_json(target / "predictions.json", result)
        summary["eligible"] = result["eligible"]
    if lane in ("all", "categorical"):
        models = load_json(target / "categorical-models.json")
        if (models["inputProjectSha256"], models["inputDatasetSha256"]) != (stable_hash(project), stable_hash(split)):
            raise ValueError(f"{family}: categorical-models.json was built from other inputs; run train again")
        result = infer_categorical(models, target)
        result["inputCategoricalModelsSha256"] = stable_hash(models)
        write_json(target / "categorical-predictions.json", result)
        summary["categorical"] = result["eligible"]
    if lane in ("all", "learned"):
        learned = _learned_stages()
        models = load_json(target / "learned-models.json")
        if models.get("inputDatasetSha256", stable_hash(split)) != stable_hash(split):
            raise ValueError(f"{family}: learned-models.json was fitted on another dataset; run train again")
        result = learned.infer_learned(models, project, pre, split, target)
        result["inputLearnedModelsSha256"] = stable_hash(models)
        result["inputDatasetSha256"] = stable_hash(split)
        write_json(target / "learned-predictions.json", result)
        summary["learned"] = result["eligible"]
        from stages.geochemistry import infer_geochemistry

        review_models = load_json(target / "geochemistry-models.json")
        if review_models["inputDatasetSha256"] != stable_hash(split):
            raise ValueError(f"{family}: geochemistry-models.json was fitted on another dataset; run train again")
        review = infer_geochemistry(review_models, project, pre, split, target)
        review["inputGeochemistryModelsSha256"] = stable_hash(review_models)
        write_json(target / "geochemistry-predictions.json", review)
        summary["geochemistry"] = review["eligible"]
    return {**summary, "seconds": round(time.time() - t0, 1)}


def evaluate(family: str, out: Path, lane: str = "all") -> dict:
    from stages.categorical import evaluate_categorical
    from stages.evaluate import evaluate_family
    from stages.scenarios import scenario_matrix

    t0 = time.time()
    target, project, pre, split = _chain(family, out)
    summary = {"family": family}
    if lane in ("all", "continuous", "learned"):
        predictions, models = load_json(target / "predictions.json"), load_json(target / "models.json")
        if predictions["inputModelsSha256"] != stable_hash(models):
            raise ValueError(f"{family}: predictions.json came from other models; run infer again")
        learned = None
        if (target / "learned-predictions.json").is_file():
            learned = load_json(target / "learned-predictions.json")
            if learned["inputDatasetSha256"] != stable_hash(split):
                raise ValueError(f"{family}: learned-predictions.json was built on another dataset; run the learned "
                                 "lane again")
        elif lane in ("all", "learned"):
            raise ValueError(f"{family}: learned-predictions.json is missing; run train and infer --lane learned")
        result = evaluate_family(family, project, pre, split, predictions, models, learned=learned)
        if (target / "spectral-models.json").is_file():  # R12: the index check beside OK on the same rows
            from stages.spectral import score_index

            spectral = load_json(target / "spectral-models.json")
            if spectral["inputDatasetSha256"] != stable_hash(split):
                raise ValueError(f"{family}: spectral-models.json was fitted on another dataset; run train again")
            write_json(target / "spectral-metrics.json", score_index(spectral, project, pre, split, predictions),
                       pretty=True)
        write_json(target / "metrics.json", result)
        summary["eligible"] = result["eligible"]
    if lane in ("all", "learned") and (target / "geochemistry-predictions.json").is_file():
        from stages.geochemistry import evaluate_geochemistry

        review = load_json(target / "geochemistry-predictions.json")
        write_json(target / "geochemistry-metrics.json", evaluate_geochemistry(review), pretty=True)
    if lane in ("all", "categorical"):
        models = load_json(target / "categorical-models.json")
        predictions = load_json(target / "categorical-predictions.json")
        if predictions["inputCategoricalModelsSha256"] != stable_hash(models):
            raise ValueError(f"{family}: categorical-predictions.json came from other models; run infer again")
        result = evaluate_categorical(project, split, models, predictions, target)
        result["inputCategoricalPredictionsSha256"] = stable_hash(predictions)
        write_json(target / "categorical-metrics.json", result)
        summary["categorical"] = result["eligible"]
    matrix = scenario_matrix(out)
    write_json(out / "scenarios.json", matrix, pretty=True)
    return {**summary, "scenarioCells": matrix["counts"], "seconds": round(time.time() - t0, 1)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["acquire", "ingest", "preprocess", "dataset", "features", "train", "infer",
                                          "evaluate"])
    parser.add_argument("--family", default="all", help="rocklea, alberta, ntgs, all, or an imported project id")
    parser.add_argument("--manifest", type=Path, help="ingest user files described by this import manifest")
    parser.add_argument("--cache", type=Path, default=Path(os.environ.get("SONDARA_RAW", ROOT / "build" / "sources")))
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "derived")
    parser.add_argument("--lane", choices=LANES, default="all",
                        help="train, infer and evaluate: the continuous, categorical or learned lane, or all three "
                             "(the learned lane needs .venv-gpu)")
    args = parser.parse_args(argv)
    if args.stage == "acquire":
        print(json.dumps(acquire(args.cache), indent=2))
        return 0
    if args.stage == "ingest" and args.manifest:
        report = ingest_manifest(args.manifest, args.out)
        print(json.dumps({"project": report["project"], "status": report["status"],
                          "findings": report["counts"]["bySeverity"]}))
        return 0 if report["status"] == "accepted" else 2
    families = FAMILIES if args.family == "all" else (args.family,)
    for family in families:
        if args.stage == "ingest":
            if family not in FAMILIES:
                parser.error(f"unknown family {family!r}; import user files with --manifest")
            summary = ingest(family, args.cache, args.out)
            print(json.dumps({k: summary[k] for k in ("family", "counts", "waterfall", "seconds")}))
        elif args.stage == "preprocess":
            summary = preprocess(family, args.out)
            print(json.dumps({k: summary[k] for k in ("family", "waterfall", "seconds")}))
        elif args.stage == "dataset":
            print(json.dumps(dataset(family, args.out)))
        elif args.stage == "features":
            print(json.dumps(features(family, args.out)))
        elif args.stage == "train":
            print(json.dumps(train(family, args.out, args.lane)))
        elif args.stage == "infer":
            print(json.dumps(infer(family, args.out, args.lane)))
        else:
            print(json.dumps(evaluate(family, args.out, args.lane)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
