"""An authored field for the estimation tests: 25 vertical holes on a 50 m grid, ten 2 m samples each.

Cu is a smooth function of position plus seeded noise; Zn follows Cu with its own noise, so the pair has a real cross
correlation. It is constructed, labelled as authored, and written through the manifest importer like any user project.
"""

import csv
import json
import math

import numpy as np

#: Authored lithology codes and the categories an authored mapping gives them (the Alberta vocabulary's order).
LITHOLOGY = {"drift": 0, "dolostone": 1, "sandstone": 2, "gneiss": 3, "granite": 4}


def lithology_log(x_rel, y_rel, depth):
    """A layered cover with pinch-outs over a basement whose granite lies in a band striking north-west."""
    t0 = 3.0 + 1.0 * math.sin(x_rel / 70)
    t1 = t0 + 2.0 + 2.0 * math.cos(y_rel / 60)
    t2 = t1 + max(0.0, 4.0 * math.sin((x_rel + y_rel) / 90))
    rock = "granite" if abs((x_rel - y_rel) - 20.0) < 45.0 else "gneiss"
    cuts = [(0.0, round(t0, 1), "drift"), (round(t0, 1), round(t1, 1), "dolostone")]
    if round(t2, 1) > round(t1, 1):
        cuts.append((round(t1, 1), round(t2, 1), "sandstone"))
    cuts.append((round(max(t1, t2), 1), depth, rock))
    return [c for c in cuts if c[1] > c[0]]


def write(folder, *, seed=20260926, side=5, spacing=50.0, samples=10, lithology=False):
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
    if lithology:
        rows = []
        for hole, x, y, *_ in collars:
            log = lithology_log(x - 500000.0, y - 7400000.0, 2.0 * samples)
            if hole == "H12":  # one interval naming two basement rocks, which a mapping must leave unmapped
                a, b, _ = log[-1]
                log[-1] = (a, b, "gneiss and granite")
            rows += [(hole, f"{a:.1f}", f"{b:.1f}", code) for a, b, code in log]
        with (folder / "lithology.csv").open("w", encoding="utf-8", newline="") as stream:
            w = csv.writer(stream, lineterminator="\n")
            w.writerow(["HoleID", "From", "To", "Lith"])
            w.writerows(rows)
        manifest["files"].append({"path": "lithology.csv", "role": "lithology",
                                  "columns": {"hole": "HoleID", "from": "From", "to": "To"}, "codes": ["Lith"]})
    (folder / "import.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return folder / "import.json"


def lithology_mapping(project_id):
    """An authored mapping for the authored field: one rule per code, the mixed code unmapped, a 5 x 5 x 20 grid."""
    return {"schema": "drillhole.lithology-mapping/v1", "id": f"{project_id}-lithology-v1", "family": project_id,
            "status": "authored for the tests", "evidence": [],
            "categories": [{"code": c, "name": n, "label": n} for n, c in LITHOLOGY.items()],
            "rules": [{"id": f"code-{n}", "category": c, "field": "Lith", "values": [n], "evidence": "authored"}
                      for n, c in LITHOLOGY.items()],
            "unmapped": [{"field": "Lith", "values": ["gneiss and granite"], "reason": "names two basement rocks"}],
            "grid": {"vertical": "depth below the collar surface", "origin": [499975.0, 7399975.0, 0.0],
                     "cell": [50.0, 50.0, 1.0], "shape": [5, 5, 20], "traceStep": 0.1, "majority": 0.5}}


def chain(tmp_path, stages=("preprocess", "dataset", "features", "train", "infer"), lithology=False,
          lane="continuous"):
    """Import the authored field and run the stages (train, infer and evaluate on ``lane``); returns the output folder
    and the project id."""
    import run
    from source_adapters.manifest_import import run_import

    manifest = write(tmp_path / "source", lithology=lithology)
    out = tmp_path / "derived"
    identifier = run_import(manifest, out)["project"]
    for stage in stages:
        if stage in ("train", "infer", "evaluate"):
            getattr(run, stage)(identifier, out, lane)
        else:
            getattr(run, stage)(identifier, out)
    return out / identifier, identifier
