"""An authored field for the estimation tests: 25 vertical holes on a 50 m grid, ten 2 m samples each.

Cu is a smooth function of position plus seeded noise; Zn follows Cu with its own noise, so the pair has a real cross
correlation. It is constructed, labelled as authored, and written through the manifest importer like any user project.
"""

import csv
import json
import math

import numpy as np


def write(folder, *, seed=20260926, side=5, spacing=50.0, samples=10):
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    collars, assays = [], []
    for i in range(side * side):
        hole = f"H{i:02d}"
        x, y = 500000.0 + spacing * (i % side), 7400000.0 + spacing * (i // side)
        collars.append((hole, x, y, 1000.0, 2.0 * samples, 0.0, -90.0))
        for k in range(samples):
            depth = 2.0 * k + 1.0
            smooth = 100 + 40 * math.sin((x - 500000) / 90) + 30 * math.cos((y - 7400000) / 110) - 1.5 * depth
            cu = smooth + rng.normal(0, 8)
            zn = 0.6 * cu + rng.normal(0, 10) + 20
            assays.append((hole, f"{hole}-{k}", 2.0 * k, 2.0 * k + 2.0, f"{cu:.3f}", f"{zn:.3f}"))
    with (folder / "collars.csv").open("w", encoding="utf-8", newline="") as stream:
        w = csv.writer(stream, lineterminator="\n")
        w.writerow(["HoleID", "East", "North", "RL", "Depth", "Azimuth", "Dip"])
        w.writerows(collars)
    with (folder / "assays.csv").open("w", encoding="utf-8", newline="") as stream:
        w = csv.writer(stream, lineterminator="\n")
        w.writerow(["HoleID", "SampleID", "From", "To", "Cu_ppm", "Zn_ppm"])
        w.writerows(assays)
    manifest = {
        "schema": "drillhole.import/v1", "project": {"id": "authored-field", "name": "Authored field"},
        "frame": {"id": "site", "kind": "projected-metric", "horizontalCrs": "EPSG:32719"}, "namespace": "a",
        "files": [
            {"path": "collars.csv", "role": "collar", "crs": "EPSG:32719",
             "columns": {"hole": "HoleID", "x": "East", "y": "North", "z": "RL", "totalDepth": "Depth",
                         "azimuth": "Azimuth", "dip": "Dip"}},
            {"path": "assays.csv", "role": "assay",
             "columns": {"hole": "HoleID", "sample": "SampleID", "from": "From", "to": "To"},
             "analytes": {"Cu_ppm": {"analyte": "Cu", "unit": "ppm", "method": "ICP"},
                          "Zn_ppm": {"analyte": "Zn", "unit": "ppm", "method": "ICP"}}}],
        "compositing": {"lengths": [4.0], "minCoverage": 1.0},
    }
    (folder / "import.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return folder / "import.json"


def chain(tmp_path, stages=("preprocess", "dataset", "features", "train", "infer")):
    """Import the authored field and run the stages; returns the output folder and the project id."""
    import run
    from source_adapters.manifest_import import run_import

    manifest = write(tmp_path / "source")
    out = tmp_path / "derived"
    identifier = run_import(manifest, out)["project"]
    for stage in stages:
        getattr(run, stage)(identifier, out)
    return out / identifier, identifier
