#!/usr/bin/env python3
"""Author the importer and QA fixtures (F01 to F42) and the fixture registry, deterministically.

    python scripts/fixtures/author_fixtures.py

Every fixture is a constructed acceptance case, never a field observation (the catalogue is in the data dossier of
the management repository, "Authored validation fixture catalogue"). Fixtures owned by built stages get their files
under ``data/fixtures/<ID>/`` (CSV files and import manifests); the registry ``data/fixtures/registry.json`` lists all
42 with construction, expected outcome, owning stage and the test that verifies each. Fixtures of stages not yet built
carry their construction as parameters in the registry and no verification until their stage exists.
"""

from __future__ import annotations

import csv
import json
import random
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "fixtures"
CRS = "EPSG:32719"
T = "tests/test_import.py::"

COLLARS = [("DH1", 500000.0, 7400000.0, 1000.0, 30.0, 0.0, -90.0),
           ("DH2", 500050.0, 7400000.0, 1002.0, 30.0, 90.0, -60.0),
           ("DH3", 500100.0, 7400050.0, 1001.0, 30.0, 180.0, -75.0)]
SURVEYS = [("DH1", 0.0, 0.0, -90.0), ("DH1", 30.0, 0.0, -90.0),
           ("DH2", 0.0, 90.0, -60.0), ("DH2", 15.0, 92.0, -61.0), ("DH2", 30.0, 94.0, -62.0),
           ("DH3", 0.0, 180.0, -75.0), ("DH3", 30.0, 182.0, -74.0)]
ASSAYS = [(h, f"{h}-S{k:02d}", 2.0 * k, 2.0 * k + 2.0, f"{100 + 10 * n + k}", f"{0.1 * k:.1f}")
          for n, h in enumerate(("DH1", "DH2", "DH3"), 1) for k in range(15)]
LITHOLOGY = [(h, 0.0, 10.0, "OX", "oxidised") for h in ("DH1", "DH2", "DH3")] + \
            [(h, 10.0, 30.0, "FR", "fresh") for h in ("DH1", "DH2", "DH3")]

COLLAR_COLUMNS = {"hole": "HoleID", "x": "East", "y": "North", "z": "RL", "totalDepth": "Depth",
                  "azimuth": "Azimuth", "dip": "Dip"}
SURVEY_COLUMNS = {"hole": "HoleID", "depth": "Depth", "azimuth": "Azimuth", "dip": "Dip"}
ASSAY_COLUMNS = {"hole": "HoleID", "sample": "SampleID", "from": "From", "to": "To"}
ANALYTES = {"Cu_ppm": {"analyte": "Cu", "unit": "ppm", "method": "ICP", "lab": "L1"},
            "Au_gpt": {"analyte": "Au", "unit": "g/t", "method": "FA", "lab": "L1"}}
LITH_COLUMNS = {"hole": "HoleID", "from": "From", "to": "To", "description": "Description"}


def write_csv(path: Path, header, rows, *, delimiter=","):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def collars_csv(path, rows):
    write_csv(path, ["HoleID", "East", "North", "RL", "Depth", "Azimuth", "Dip"], rows)


def surveys_csv(path, rows):
    write_csv(path, ["HoleID", "Depth", "Azimuth", "Dip"], rows)


def assays_csv(path, rows, header=("HoleID", "SampleID", "From", "To", "Cu_ppm", "Au_gpt")):
    write_csv(path, list(header), rows)


def lith_csv(path, rows):
    write_csv(path, ["HoleID", "From", "To", "Lith", "Description"], rows)


def manifest(identifier, files, **extra):
    return {"schema": "drillhole.import/v1", "project": {"id": identifier, "name": f"Fixture {identifier}"},
            "frame": {"id": "site", "kind": "projected-metric", "horizontalCrs": CRS}, "namespace": "s",
            "files": files, **extra}


def collar_file(path, **extra):
    return {"path": path, "role": "collar", "crs": CRS, "columns": COLLAR_COLUMNS,
            "angles": {"azimuthReference": "grid"}, **extra}


def survey_file(path, **extra):
    return {"path": path, "role": "survey", "columns": SURVEY_COLUMNS,
            "angles": {"azimuthReference": "grid", "instrument": "authored"}, **extra}


def assay_file(path, analytes=None, **extra):
    return {"path": path, "role": "assay", "columns": ASSAY_COLUMNS, "analytes": analytes or ANALYTES, **extra}


def lith_file(path, **extra):
    return {"path": path, "role": "lithology", "columns": LITH_COLUMNS, "codes": ["Lith"], **extra}


def base(folder: Path, prefix=""):
    collars_csv(folder / f"{prefix}collars.csv", COLLARS)
    surveys_csv(folder / f"{prefix}surveys.csv", SURVEYS)
    assays_csv(folder / f"{prefix}assays.csv", ASSAYS)
    lith_csv(folder / f"{prefix}lithology.csv", LITHOLOGY)
    return [collar_file(f"{prefix}collars.csv"), survey_file(f"{prefix}surveys.csv"),
            assay_file(f"{prefix}assays.csv"), lith_file(f"{prefix}lithology.csv")]


# ---- fixtures owned by the import and preprocess stages ------------------------------------------------------------

def f01(d):
    files = base(d / "consolidated")
    write_json(d / "consolidated.json", manifest("f01", [dict(f, path="consolidated/" + f["path"]) for f in files]))
    collars_csv(d / "split" / "collars_a.csv", COLLARS[:2])
    collars_csv(d / "split" / "collars_b.csv", COLLARS[2:])
    surveys_csv(d / "split" / "surveys_a.csv", [s for s in SURVEYS if s[0] == "DH1"])
    surveys_csv(d / "split" / "surveys_b.csv", [s for s in SURVEYS if s[0] != "DH1"])
    for n, hole in enumerate(("DH1", "DH2", "DH3"), 1):
        assays_csv(d / "split" / f"assays_{n}.csv", [a for a in ASSAYS if a[0] == hole])
    lith_csv(d / "split" / "lithology.csv", LITHOLOGY)
    write_json(d / "split.json", manifest("f01", [
        collar_file("split/collars_a.csv"), collar_file("split/collars_b.csv"),
        survey_file("split/surveys_a.csv"), survey_file("split/surveys_b.csv"),
        assay_file("split/assays_1.csv"), assay_file("split/assays_2.csv"), assay_file("split/assays_3.csv"),
        lith_file("split/lithology.csv")]))


def f02(d):
    rng = random.Random(20260926)
    shuffled = {name: rng.sample(rows, len(rows)) for name, rows in
                (("collars", COLLARS), ("surveys", SURVEYS), ("assays", ASSAYS), ("lithology", LITHOLOGY))}
    collars_csv(d / "reordered" / "collars_b.csv", [c for c in shuffled["collars"] if c[0] == "DH3"])
    collars_csv(d / "reordered" / "collars_a.csv", [c for c in shuffled["collars"] if c[0] != "DH3"])
    surveys_csv(d / "reordered" / "surveys.csv", shuffled["surveys"])
    assays_csv(d / "reordered" / "assays_2.csv", [a for a in shuffled["assays"] if a[0] != "DH1"])
    assays_csv(d / "reordered" / "assays_1.csv", [a for a in shuffled["assays"] if a[0] == "DH1"])
    lith_csv(d / "reordered" / "lithology.csv", shuffled["lithology"])
    write_json(d / "reordered.json", manifest("f01", [
        lith_file("reordered/lithology.csv"), assay_file("reordered/assays_2.csv"),
        assay_file("reordered/assays_1.csv"), survey_file("reordered/surveys.csv"),
        collar_file("reordered/collars_b.csv"), collar_file("reordered/collars_a.csv")]))


def f03(d):
    files = base(d)
    shutil.copyfile(d / "assays.csv", d / "assays_copy.csv")
    write_json(d / "import.json", manifest("f03", files + [assay_file("assays_copy.csv")]))


def f04(d):
    collars_csv(d / "collars_a.csv", COLLARS)
    changed = [(h, x + 5.0 if h == "DH2" else x, y, z, td, az, dip) for h, x, y, z, td, az, dip in COLLARS[1:2]]
    collars_csv(d / "collars_b.csv", changed)
    surveys_csv(d / "surveys.csv", SURVEYS)
    assays_csv(d / "assays.csv", ASSAYS)
    files = [collar_file("collars_a.csv"), collar_file("collars_b.csv"), survey_file("surveys.csv"),
             assay_file("assays.csv")]
    write_json(d / "import.json", manifest("f04", files))
    write_json(d / "resolved.json", manifest("f04", files, resolutions={"collars": {"s:DH2": "collars_b.csv"}}))


def f05(d):
    collars_csv(d / "a_collars.csv", [("DH001", 500000.0, 7400000.0, 1000.0, 30.0, 0.0, -90.0)])
    collars_csv(d / "b_collars.csv", [("DH001", 500000.0, 7400000.0, 1000.0, 30.0, 0.0, -90.0)])
    assays_csv(d / "a_assays.csv", [("DH001", "A-1", 0.0, 2.0, "150", "0.2")])
    assays_csv(d / "b_assays.csv", [("DH001", "B-1", 2.0, 4.0, "160", "0.3")])
    files = [collar_file("a_collars.csv", namespace="a"), collar_file("b_collars.csv", namespace="b"),
             assay_file("a_assays.csv", namespace="a"), assay_file("b_assays.csv", namespace="b")]
    write_json(d / "import.json", manifest("f05", files))
    write_json(d / "aliased.json", manifest("f05", files, aliases={"b:DH001": "a:DH001"}))


def f06(d):
    assays_csv(d / "assays.csv", ASSAYS)
    write_json(d / "import.json", manifest("f06", [assay_file("assays.csv")]))


def f07(d):
    files = base(d)
    assays_csv(d / "orphan.csv", [("DH9", "DH9-S00", 0.0, 2.0, "120", "0.1")])
    write_json(d / "import.json", manifest("f07", files + [assay_file("orphan.csv")]))


def f08(d):
    ids = ["00012", "12", "DH-12", "dh-12"]
    collars_csv(d / "collars.csv", [(h, 500000.0 + 10 * i, 7400000.0, 1000.0, 20.0, 0.0, -90.0)
                                    for i, h in enumerate(ids)])
    write_json(d / "import.json", manifest("f08", [collar_file("collars.csv")],
                                           assumptions={"missingSurvey": "vertical"}))


def f09(d):
    write_csv(d / "collars.csv", ["HoleID", "East", "North", "RL", "Depth", "Azimuth", "Dip"],
              [("DH1", "500000,5", "7400000,25", "1000,75", "30", "0", "-90")], delimiter=";")
    write_csv(d / "lithology.csv", ["HoleID", "From", "To", "Lith", "Description"],
              [("DH1", "0", "12,5", "OX", "clay; sandy, \"soft\""), ("DH1", "12,5", "30", "FR", "fresh")],
              delimiter=";")
    dialect = {"delimiter": ";", "decimal": ",", "quote": "\"", "encoding": "utf-8"}
    write_json(d / "import.json", manifest("f09", [collar_file("collars.csv", dialect=dialect),
                                                   lith_file("lithology.csv", dialect=dialect)]))


def f10(d):
    (d / "duplicate_header.csv").parent.mkdir(parents=True, exist_ok=True)
    (d / "duplicate_header.csv").write_text("HoleID,SampleID,From,From,To,Cu_ppm,Au_gpt\n"
                                            "DH1,DH1-S00,0,0,2,110,0.0\n", encoding="utf-8", newline="\n")
    (d / "ragged.csv").write_text("HoleID,SampleID,From,To,Cu_ppm,Au_gpt\n"
                                  "DH1,DH1-S00,0,2,110,0.0\n"
                                  "DH1,DH1-S01,2,4,111,0.1,EXTRA\n", encoding="utf-8", newline="\n")
    collars_csv(d / "collars.csv", COLLARS)
    write_json(d / "duplicate_header.json", manifest("f10", [collar_file("collars.csv"),
                                                             assay_file("duplicate_header.csv")]))
    write_json(d / "ragged.json", manifest("f10", [collar_file("collars.csv"), assay_file("ragged.csv")]))


def f11(d):
    collars_csv(d / "collars.csv", [("DH1", 500000.0, 7400000.0, 1000.0, 100.0, 0.0, -90.0)])
    surveys_csv(d / "surveys_ft.csv", [("DH1", 0.0, 0.0, -90.0), ("DH1", 10.0, 0.0, -90.0),
                                       ("DH1", 100.0, 0.0, -90.0)])
    assays_csv(d / "assays_ft.csv", [("DH1", "DH1-S00", 0.0, 10.0, "150", "0.2")])
    write_json(d / "import.json", manifest("f11", [
        collar_file("collars.csv", lengthUnit="ft"), survey_file("surveys_ft.csv", lengthUnit="ft"),
        assay_file("assays_ft.csv", lengthUnit="ft")]))


def f12(d):
    collars_csv(d / "collars_a.csv", COLLARS[:2])
    collars_csv(d / "collars_b.csv", COLLARS[2:])
    swapped = [(h, y, x, z, td, az, dip) for h, x, y, z, td, az, dip in COLLARS[2:]]
    collars_csv(d / "collars_swapped.csv", swapped)
    write_json(d / "crs.json", manifest("f12", [collar_file("collars_a.csv"),
                                                collar_file("collars_b.csv", crs="EPSG:32718")]))
    write_json(d / "axes.json", manifest("f12", [collar_file("collars_a.csv"), collar_file("collars_swapped.csv")]))
    write_json(d / "declared.json", manifest("f12", [collar_file("collars_a.csv"),
                                                     collar_file("collars_swapped.csv", axisOrder="north-east")],
                                             assumptions={"missingSurvey": "collar-orientation"}))


def trajectory_fixture(d, identifier, collar_row, stations):
    collars_csv(d / "collars.csv", [collar_row])
    surveys_csv(d / "surveys.csv", stations)
    write_json(d / "import.json", manifest(identifier, [collar_file("collars.csv"), survey_file("surveys.csv")]))


def f13(d):
    trajectory_fixture(d, "f13", ("V", 1000.0, 2000.0, 500.0, 100.0, 0.0, -90.0),
                       [("V", 0.0, 0.0, -90.0), ("V", 100.0, 0.0, -90.0)])


def f14(d):
    trajectory_fixture(d, "f14", ("H", 1000.0, 2000.0, 500.0, 100.0, 0.0, 0.0),
                       [("H", 0.0, 0.0, 0.0), ("H", 100.0, 90.0, 0.0)])


def f15(d):
    trajectory_fixture(d, "f15", ("W", 1000.0, 2000.0, 500.0, 100.0, 359.0, 0.0),
                       [("W", 0.0, 359.0, 0.0), ("W", 100.0, 1.0, 0.0)])


def f16(d):
    collars_csv(d / "collars.csv", [("DH1", 500000.0, 7400000.0, 1000.0, 60.0, 45.0, -60.0)])
    for name, convention, dips in (("negative", "negative-down", (-60.0, -58.0, -55.0)),
                                   ("positive", "positive-down", (60.0, 58.0, 55.0)),
                                   ("vertical", "inclination-from-vertical", (30.0, 32.0, 35.0))):
        surveys_csv(d / f"surveys_{name}.csv", [("DH1", 0.0, 45.0, dips[0]), ("DH1", 30.0, 47.0, dips[1]),
                                                ("DH1", 60.0, 50.0, dips[2])])
        spec = survey_file(f"surveys_{name}.csv")
        spec["angles"] = {**spec["angles"], "dip": convention}
        write_json(d / f"{name}.json", manifest("f16", [collar_file("collars.csv"), spec]))


def f17(d):
    collars_csv(d / "collars.csv", COLLARS)
    rows = SURVEYS + [("DH1", 30.0, 10.0, -85.0), ("DH2", 15.0, 92.0, -61.0)]
    surveys_csv(d / "surveys.csv", rows)
    files = [collar_file("collars.csv"), survey_file("surveys.csv")]
    write_json(d / "import.json", manifest("f17", files))
    write_json(d / "excluded.json", manifest("f17", files, exclude=["s:DH1"]))


def f18(d):
    collars_csv(d / "collars.csv", [("DH1", 500000.0, 7400000.0, 1000.0, 30.0, 45.0, -60.0),
                                    ("DH2", 500050.0, 7400000.0, 1000.0, 30.0, "", ""),
                                    ("DH3", 500100.0, 7400000.0, 1000.0, 30.0, 0.0, -90.0)])
    surveys_csv(d / "surveys.csv", [("DH3", 0.0, 0.0, -90.0), ("DH3", 20.0, 0.0, -88.0)])
    files = [collar_file("collars.csv"), survey_file("surveys.csv")]
    write_json(d / "import.json", manifest("f18", files))
    write_json(d / "assumed.json", manifest("f18", files, assumptions={"missingSurvey": "vertical"}))


def f19(d):
    collars_csv(d / "collars.csv", COLLARS[:1])
    assays_csv(d / "assays.csv", [("DH1", "A", 0.0, 2.0, "100", "0.1"), ("DH1", "REV", 5.0, 4.0, "100", "0.1"),
                                  ("DH1", "ZERO", 6.0, 6.0, "100", "0.1"), ("DH1", "NEG", -1.0, 2.0, "100", "0.1"),
                                  ("DH1", "B", 8.0, 10.0, "100", "0.1")])
    write_json(d / "import.json", manifest("f19", [collar_file("collars.csv"), assay_file("assays.csv")],
                                           assumptions={"missingSurvey": "collar-orientation"}))


def f20(d):
    collars_csv(d / "collars.csv", COLLARS[:1])
    assays_csv(d / "assays.csv", [("DH1", "A", 0.0, 2.0, "100"), ("DH1", "B", 1.0, 3.0, "200"),
                                  ("DH1", "C", 4.0, 6.0, "300")], header=("HoleID", "SampleID", "From", "To", "Cu_ppm"))
    write_json(d / "import.json", manifest("f20", [collar_file("collars.csv"),
                                                   assay_file("assays.csv", {"Cu_ppm": ANALYTES["Cu_ppm"]})],
                                           compositing={"lengths": [2.0], "minCoverage": 1.0}))


def f21(d):
    collars_csv(d / "collars.csv", COLLARS[:1])
    assays_csv(d / "multielement.csv", [("DH1", "M1", 0.0, 2.0, "100"), ("DH1", "M2", 2.0, 4.0, "120")],
               header=("HoleID", "SampleID", "From", "To", "Cu_ppm"))
    assays_csv(d / "gold.csv", [("DH1", "G1", 1.0, 3.0, "0.8")], header=("HoleID", "SampleID", "From", "To", "Au_gpt"))
    write_json(d / "import.json", manifest("f21", [
        collar_file("collars.csv"), assay_file("multielement.csv", {"Cu_ppm": ANALYTES["Cu_ppm"]}),
        assay_file("gold.csv", {"Au_gpt": ANALYTES["Au_gpt"]})]))


def f22(d):
    collars_csv(d / "collars.csv", COLLARS[:1])
    assays_csv(d / "assays.csv", [("DH1", "A", 0.0, 2.0, "100"), ("DH1", "B", 2.0, 5.0, "200")],
               header=("HoleID", "SampleID", "From", "To", "Cu_ppm"))
    lith_csv(d / "lithology.csv", [("DH1", 0.0, 3.0, "OX", "oxidised"), ("DH1", 3.0, 5.0, "FR", "fresh")])
    write_json(d / "import.json", manifest("f22", [collar_file("collars.csv"),
                                                   assay_file("assays.csv", {"Cu_ppm": ANALYTES["Cu_ppm"]}),
                                                   lith_file("lithology.csv")]))


def composite_fixture(d, identifier, rows, lengths, coverage):
    collars_csv(d / "collars.csv", COLLARS[:1])
    assays_csv(d / "assays.csv", rows, header=("HoleID", "SampleID", "From", "To", "Cu_ppm"))
    write_json(d / "import.json", manifest(identifier, [collar_file("collars.csv"),
                                                        assay_file("assays.csv", {"Cu_ppm": ANALYTES["Cu_ppm"]})],
                                           compositing={"lengths": lengths, "minCoverage": coverage}))


def f23(d):
    composite_fixture(d, "f23", [("DH1", "A", 0.0, 2.0, "1"), ("DH1", "B", 2.0, 5.0, "3")], [5.0], 1.0)


def f24(d):
    composite_fixture(d, "f24", [("DH1", "A", 0.0, 1.0, "2"), ("DH1", "B", 2.0, 3.0, "4")], [3.0], 0.75)


def f25(d):
    composite_fixture(d, "f25", [("DH1", "A", 0.0, 5.5, "7")], [2.0], 1.0)


def f26(d):
    collars_csv(d / "collars.csv", COLLARS[:1])
    tokens = [("CENS", "<0.5"), ("ZERO", "0"), ("BLANK", ""), ("NS", "NS"), ("LOST", "LC"), ("SENT", "-9999"),
              ("MEAS", "12.5")]
    assays_csv(d / "assays.csv", [("DH1", sample, 2.0 * i, 2.0 * i + 2.0, token) for i, (sample, token)
                                  in enumerate(tokens)], header=("HoleID", "SampleID", "From", "To", "Cu_ppm"))
    write_json(d / "import.json", manifest("f26", [collar_file("collars.csv"), assay_file(
        "assays.csv", {"Cu_ppm": ANALYTES["Cu_ppm"]}, states={"NS": "not-sampled", "LC": "lost-core",
                                                             "-9999": "sentinel"})]))


def f27(d):
    collars_csv(d / "collars.csv", COLLARS[:1])
    assays_csv(d / "assays.csv", [("DH1", "S1", 0.0, 2.0, ">10000")], header=("HoleID", "SampleID", "From", "To", "Cu_ppm"))
    assays_csv(d / "overlimit.csv", [("DH1", "S1", 0.0, 2.0, "1.2")], header=("HoleID", "SampleID", "From", "To", "Cu_pct"))
    write_json(d / "import.json", manifest("f27", [
        collar_file("collars.csv"), assay_file("assays.csv", {"Cu_ppm": ANALYTES["Cu_ppm"]}),
        assay_file("overlimit.csv", {"Cu_pct": {"analyte": "Cu", "unit": "%", "method": "OL-ICP", "lab": "L1"}})]))


def f28(d):
    collars_csv(d / "collars.csv", COLLARS[:1])
    header = ("HoleID", "SampleID", "From", "To", "Type", "Cu_ppm")
    assays_csv(d / "lab1.csv", [("DH1", "S2", 2.0, 4.0, "", "105"), ("DH1", "S2R", 2.0, 4.0, "REP", "102")], header)
    assays_csv(d / "lab2.csv", [("DH1", "S2", 2.0, 4.0, "", "98")], header)
    columns = {**ASSAY_COLUMNS, "sampleType": "Type"}
    files = [collar_file("collars.csv"),
             assay_file("lab1.csv", {"Cu_ppm": ANALYTES["Cu_ppm"]}, columns=columns, repeats={"REP": "repeat"}),
             assay_file("lab2.csv", {"Cu_ppm": {"analyte": "Cu", "unit": "ppm", "method": "AAS", "lab": "L2"}},
                        columns=columns, repeats={"REP": "repeat"})]
    write_json(d / "import.json", manifest("f28", files))
    write_json(d / "priority.json", manifest("f28", files, methodPriority={"Cu": ["AAS", "ICP"]}))


def f29(d):
    collars_csv(d / "collars.csv", COLLARS[:1])
    header = ("HoleID", "SampleID", "From", "To", "Type", "Cu_ppm")
    assays_csv(d / "assays.csv", [("DH1", "S1", 0.0, 2.0, "", "110"), ("", "STD-OREAS-45", "", "", "STD", "780"),
                                  ("", "BLK-1", "", "", "BLK", "<2"), ("DH1", "S2", 2.0, 4.0, "", "120")], header)
    columns = {**ASSAY_COLUMNS, "sampleType": "Type"}
    write_json(d / "import.json", manifest("f29", [collar_file("collars.csv"), assay_file(
        "assays.csv", {"Cu_ppm": ANALYTES["Cu_ppm"]}, columns=columns,
        controls={"STD": "standard", "BLK": "blank"})]))


def f30(d):
    collars_csv(d / "collars.csv", COLLARS[:1])
    header = ("HoleID", "SampleID", "From", "To", "Type", "Cu_ppm")
    assays_csv(d / "assays.csv", [("DH1", "S3", 0.0, 2.0, "", "5"), ("DH1", "S3R", 0.0, 2.0, "REP", "5.2")], header)
    lith_csv(d / "lithology.csv", [("DH1", 0.0, 1.0, "OX", "oxidised"), ("DH1", 1.0, 2.0, "FR", "fresh")])
    columns = {**ASSAY_COLUMNS, "sampleType": "Type"}
    write_json(d / "import.json", manifest("f30", [
        collar_file("collars.csv"), assay_file("assays.csv", {"Cu_ppm": ANALYTES["Cu_ppm"]}, columns=columns,
                                               repeats={"REP": "repeat"}), lith_file("lithology.csv")]))


def f41(d):
    files = base(d)
    write_json(d / "import.json", manifest("f41", files))
    assays_csv(d / "assays_new.csv", [a[:4] + ("999", "9.9") for a in ASSAYS])
    write_json(d / "replacement.json", manifest("f41", files[:2] + [assay_file("assays_new.csv"), files[3]]))


AUTHORED = {f"F{int(name[1:]):02d}": fn for name, fn in globals().items()
            if name.startswith("f") and name[1:].isdigit() and callable(fn)}

# ---- the catalogue ------------------------------------------------------------------------------------------------

REGISTRY = [
    ("F01", "Two collar, two survey and three disjoint assay files", "import",
     "Same canonical data as the consolidated files", T + "test_split_and_reordered_files_equal_the_consolidated_import"),
    ("F02", "Reordered files and rows", "import",
     "Invariant under explicit precedence and sorting", T + "test_split_and_reordered_files_equal_the_consolidated_import"),
    ("F03", "Identical file twice", "import", "No doubled measurements", T + "test_a_repeated_file_adds_no_measurement"),
    ("F04", "Conflicting collar versions", "import",
     "Both versions and the affected records reported; accepted only with a recorded resolution",
     T + "test_conflicting_collars_block_until_resolved"),
    ("F05", "Two sources reuse DH001", "import", "Namespaced identity remains distinct; an explicit alias merges",
     T + "test_namespaces_keep_reused_hole_ids_apart"),
    ("F06", "Assays arrive first", "import", "Pending companions, no invented geometry",
     T + "test_assays_without_collars_stay_pending"),
    ("F07", "One orphan assay", "import", "Isolated while the valid holes are accepted", T + "test_an_orphan_assay_is_isolated"),
    ("F08", "00012, 12, DH-12 and dh-12", "import", "Exact strings kept; normalization collisions reported",
     T + "test_hole_ids_keep_case_and_zeros_and_collisions_are_reported"),
    ("F09", "Semicolon, decimal comma and quoted delimiters", "import", "Declared parsing conventions preserve values",
     T + "test_declared_dialects_preserve_values"),
    ("F10", "Duplicate headers or malformed rows", "import", "Precise file, row and column error; no shifted values",
     T + "test_malformed_files_fail_with_file_row_and_column"),
    ("F11", "Feet and metres", "import", "Declared conversion: 10 ft = 3.048 m", T + "test_feet_convert_exactly"),
    ("F12", "CRS mismatch or swapped axes", "import", "Spatial incompatibility surfaced before any join",
     T + "test_crs_mismatch_and_swapped_axes_fail_before_join"),
    ("F13", "Vertical 100 m hole", "preprocess", "Easting and northing unchanged, elevation 100 m lower",
     T + "test_analytic_trajectories"),
    ("F14", "Horizontal 100 m arc, azimuth 0 to 90 degrees", "preprocess", "East = North = 200/pi m",
     T + "test_analytic_trajectories"),
    ("F15", "Azimuth 359 to 1 degrees", "preprocess", "A 2 degree turn, never 358", T + "test_analytic_trajectories"),
    ("F16", "Opposite declared dip conventions", "import", "Same trace after explicit convention mapping",
     T + "test_dip_conventions_give_the_same_trace"),
    ("F17", "Conflicting duplicate survey depth", "import", "Ambiguity reported before desurvey; the hole is blocked",
     T + "test_conflicting_survey_depths_block_the_hole"),
    ("F18", "Missing or truncated survey", "import", "Explicit assumption and the affected depth range",
     T + "test_missing_and_truncated_surveys_are_declared"),
    ("F19", "Reversed, zero and negative intervals", "import", "Exactly those records excluded and reported",
     T + "test_invalid_intervals_are_excluded_by_record"),
    ("F20", "Within-series assay overlap", "import", "A conflict; no implicit summing or averaging",
     T + "test_overlapping_assays_are_conflicts_not_sums"),
    ("F21", "Parallel analyte and method supports", "import", "Overlap retained as separate observations",
     T + "test_parallel_series_are_separate_observations"),
    ("F22", "Lithology 0/3/5 m; assays 0/2/5 m", "preprocess", "Fragments 0/2/3/5 m, parent lengths conserved",
     T + "test_overlay_fragments_conserve_parent_lengths"),
    ("F23", "Grade 1 over 2 m, grade 3 over 3 m", "preprocess", "Five-metre composite 2.2", T + "test_composite_fixtures"),
    ("F24", "Grade 2 at 0-1 m, grade 4 at 2-3 m", "preprocess",
     "Coverage 2/3, observed mean 3; fails a 0.75 coverage gate", T + "test_composite_fixtures"),
    ("F25", "5.5 m support, 2 m composites", "preprocess", "A declared 1.5 m residual", T + "test_composite_fixtures"),
    ("F26", "Censored, zero, blank, not sampled, lost core and sentinel", "import",
     "Distinct states and a versioned eligibility rule", T + "test_states_are_distinct_and_eligibility_is_versioned"),
    ("F27", "Above 10000 ppm, then 1.2 % by an overlimit method", "preprocess",
     "Both preserved; the selected overlimit value is 12000 ppm", T + "test_overlimit_reassay_is_selected"),
    ("F28", "Several methods and labs, and a repeat", "preprocess",
     "Explicit result selection; the repeat adds no spatial support", T + "test_result_selection_is_explicit"),
    ("F29", "Standards and blanks mixed with samples", "import", "Controls receive no fabricated coordinates",
     T + "test_controls_get_no_coordinates"),
    ("F30", "Repeats joined to interval fragments", "preprocess", "No many-to-many fragment expansion",
     T + "test_repeats_do_not_multiply_fragments"),
    ("F31", "Insufficient eligible neighbours", "infer", "A reasoned unestimated target; no zero-grade fallback", None),
    ("F32", "Dense single hole versus several holes", "infer", "Per-hole and sector limits and the selected support shown", None),
    ("F33", "Authored anisotropic field and a rigid rotation", "infer",
     "Estimates invariant under a joint rotation of coordinates and anisotropy", None),
    ("F34", "Conflicting colocated or ill-conditioned data", "infer", "Conditioning failure reported; never a successful NaN", None),
    ("F35", "Hard versus soft domain boundary", "infer", "The declared support and range rules enforced", None),
    ("F36", "Prior without nearby observations", "infer", "An explicit prior-driven result with absent conditioning", None),
    ("F37", "Missing external drift or deficient rank", "infer", "Unsupported model or target; no silent method switch", None),
    ("F38", "Conflicting orientation normals", "features", "Undefined or unstable orientation diagnosed", None),
    ("F39", "Seeded conditional realizations", "infer", "Seed reproducibility and model-specific conditioning checks", None),
    ("F40", "Holdout with fragments and repeats", "dataset", "Every held-out derivative and result excluded from training", None),
    ("F41", "Cancellation, failure and an interrupted import", "import",
     "The previous project intact; no partial final result", T + "test_an_interrupted_import_leaves_the_previous_project"),
    ("F42", "Export, re-import and CPU and accelerated parity", "export",
     "Metadata, eligibility and declared tolerances preserved", None),
]

LATER = {
    "F31": {"observations": [[0, 0, 0, 1.0], [500, 0, 0, 2.0]], "target": [1000, 0, 0],
            "neighbourhood": {"radius": 100, "minObservations": 3}, "expect": {"status": "unestimated",
                                                                               "reason": "insufficient-neighbours"}},
    "F32": {"denseHole": {"hole": "A", "count": 20, "spacing": 1}, "otherHoles": ["B", "C", "D"],
            "neighbourhood": {"maxPerHole": 4, "maxObservations": 12}, "expect": {"maxFromOneHole": 4}},
    "F33": {"anisotropy": {"ranges": [100, 50, 10], "rotation": [30, 0, 0]}, "rigidRotation": [45, 10, 5],
            "expect": {"maxAbsoluteDifference": 1e-9}},
    "F34": {"observations": [[0, 0, 0, 1.0], [0, 0, 0, 3.0]], "nugget": 0.0,
            "expect": {"status": "failed", "reason": "singular-or-ill-conditioned"}},
    "F35": {"domains": {"A": [[0, 0, 0, 1.0]], "B": [[5, 0, 0, 9.0]]}, "target": {"domain": "A", "at": [2, 0, 0]},
            "expect": {"hard": {"usesDomain": ["A"]}, "soft": {"distance": 10, "usesDomain": ["A", "B"]}}},
    "F36": {"mean": 2.0, "observations": [[0, 0, 0, 5.0]], "target": [10000, 0, 0], "range": 100,
            "expect": {"estimate": 2.0, "conditioning": "absent"}},
    "F37": {"drift": "linear", "observations": [[0, 0, 0, 1.0], [1, 0, 0, 2.0], [2, 0, 0, 3.0]], "target": [0, 1, 0],
            "expect": {"status": "failed", "reason": "rank-deficient-drift", "methodLabel": "universal kriging"}},
    "F38": {"orientations": [{"dip": 45, "dipDirection": 90}, {"dip": 45, "dipDirection": 270}],
            "expect": {"status": "undefined"}},
    "F39": {"seed": 20260926, "realizations": 2, "expect": {"sameSeedIdentical": True, "hardDataHonoured": True}},
    "F40": {"heldOutHole": "B", "derivatives": ["composites", "fragments", "repeats"],
            "expect": {"trainingContainsHeldOut": False}},
    "F42": {"roundTrip": ["project", "preprocessed", "estimates"], "tolerances": {"cpuCuda": 1e-12, "onnx": 1e-5},
            "expect": {"metadataPreserved": True}},
}


def main() -> int:
    for identifier, fn in sorted(AUTHORED.items()):
        folder = OUT / identifier
        if folder.exists():
            shutil.rmtree(folder)
        fn(folder)
    fixtures = []
    for identifier, construction, stage, expected, verification in REGISTRY:
        entry = {"id": identifier, "construction": construction, "stage": stage, "expected": expected,
                 "files": f"data/fixtures/{identifier}/" if identifier in AUTHORED else None,
                 "parameters": LATER.get(identifier), "verification": verification}
        fixtures.append(entry)
    write_json(OUT / "registry.json", {
        "schema": "drillhole.fixtures/v1",
        "source": "Authored validation fixture catalogue, data dossier of 2026-09-10 (management repository)",
        "builtStages": ["acquire", "ingest", "import", "preprocess"],
        "fixtures": fixtures})
    print(f"wrote {len(AUTHORED)} fixture folders and a registry of {len(fixtures)} fixtures to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
