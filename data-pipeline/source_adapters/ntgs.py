"""NTGS DIP043 and DIP001, hole 12LE002 (NTGS 8440823): the measured-survey family.

The bundled subset (``data/sources/ntgs-12le002/``, CC BY 4.0, Northern Territory of Australia (Northern Territory
Geological Survey)) was normalized from the licensed compilations and corroborated against the original company
survey workbook during research. This adapter reads it and states what it is:

- One collar at a local ground-distance east/north/up origin that is exactly the declared source collar (EPSG:28352
  X=981950, Y=8277806, compiled Z=182.28 m, recorded in the frame). The compiled elevation is not a surveyed RL.
- Thirteen survey records: the recorded collar direction at MD 0, eleven Reflex EZ-Shot single-shot measurements from
  60 to 360 m, and a terminal extension at total depth that repeats the last orientation. Only the eleven are
  measurements. Azimuths are true-north bearings, already corrected for declination; they are not corrected again.
- 1,892 determinations over 44 analytes and 59 samples, with below-detection results kept as qualifier and limit and
  no numeric value, never as negative concentrations or imputed halves.
- One hole: suitable for measured desurvey, logs, gaps, repeats and censoring, not for grouped spatial evaluation.
"""

import csv
import json
from collections import Counter
from itertools import pairwise

from source_adapters.common import (
    collar,
    determination,
    frame,
    issue,
    localized,
    project,
    refs,
    source,
    support,
    survey,
    trajectory,
)
from source_io import ROOT, digest

BUNDLE = ROOT / "data" / "sources" / "ntgs-12le002"
EXPECTED = {"stations": 13, "measured": 11, "determinations": 1892, "analytes": 44, "samples": 59, "cuzn": 118}
#: The bundle's source roles, and the canonical role and instrument each becomes.
ROLES = {"recorded-collar-direction": ("recorded-collar-direction", None),
         "measured-single-shot": ("measured", "Reflex EZ-Shot electronic single-shot"),
         "compiled-terminal-extension": ("compiled-extension", None)}
STATES = {"=": "measured", "<": "censored-below", ">": "censored-above"}


def _rows(name):
    with (BUNDLE / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _float(token):
    return None if token is None or token.strip() == "" else float(token)


def normalize(cache=None):
    manifest = json.loads((ROOT / "data" / "sources" / "manifest.json").read_text(encoding="utf-8"))
    for f in manifest["files"]:
        if f.get("family") == "ntgs" and digest(ROOT / f["bundled"]) != f["sha256"]:
            raise ValueError("NTGS bundled subset hash mismatch: " + f["file"])
    mapping = json.loads((BUNDLE / "mapping.json").read_text(encoding="utf-8"))
    origin = mapping["coordinates"]["origin"]
    sources = [source(f["file"], mapping["source"]["licenseEvidenceUrl"][0 if "collars" in f["file"] or "surveys" in f["file"] else 1],
                      "CC-BY-4.0", mapping["source"]["attribution"], f["sha256"], "csv" if f["file"].endswith("csv") else "json",
                      "utf-8") for f in manifest["files"] if f.get("family") == "ntgs"]
    p = project(
        "ntgs", localized("NTGS 12LE002: one hole with measured surveys", "NTGS 12LE002: un sondaje con levantamientos medidos"),
        sources,
        "ntgs-v1: bundled DIP043/DIP001 subset for 8440823_12LE002; local ENU at the source collar; eleven measured "
        "single-shot stations; below-detection results as qualifiers",
        frame("ntgs-local-enu", "local-metric",
              origin={"sourceProjected": origin["sourceProjected"], "sourceHorizontalCrs": origin["sourceHorizontalCRS"],
                      "longitude": origin["longitude"], "latitude": origin["latitude"]},
              assumptions=[("Local ground-distance east/north/up anchored at the declared source collar; no grid-scale "
                            "distortion applied to measured depths."),
                           "Azimuths are true-north bearings already corrected for 4 degrees of declination.",
                           "Compiled elevation (SRTM-draped); the original report RL differs by 5.72 m."]),
    )
    collars = _rows("collars.csv")
    surveys = _rows("surveys.csv")
    assays = _rows("assays.csv")
    if len(collars) != 1 or len(surveys) != EXPECTED["stations"] or len(assays) != EXPECTED["determinations"]:
        raise ValueError("NTGS subset population drift")
    hole = collars[0]["holeId"]
    total = float(collars[0]["totalDepth"])
    p["collars"].append(collar(hole, "ntgs", "8440823_12LE002", "ntgs-local-enu", float(collars[0]["x"]),
                               float(collars[0]["y"]), float(collars[0]["z"]),
                               refs("ntgs-12le002-collars.csv", collars[0]["sourceRow"]), total_depth=total))
    roles = Counter(s["role"] for s in surveys)
    if roles.get("measured-single-shot") != EXPECTED["measured"]:
        raise ValueError("NTGS measured station count drift")
    for i, s in enumerate(surveys):
        role, instrument = ROLES[s["role"]]
        p["surveys"].append(survey(f"nt-srv-{i}", hole, float(s["md"]), float(s["azimuth"]), float(s["dip"]), role,
                                   refs("ntgs-12le002-surveys.csv", s["sourceRow"]), reference="true",
                                   instrument=instrument))
    p["trajectories"].append(trajectory(hole, "measured-stations", refs("ntgs-12le002-surveys.csv", "all"),
                                        valid_to=total, azimuth_assumption="true north"))
    analytes = sorted({a["analyte"] for a in assays})
    if len(analytes) != EXPECTED["analytes"]:
        raise ValueError("NTGS analyte count drift")
    units = {a["analyte"]: a["unit"] for a in assays}
    for a in analytes:
        p["analytes"].append({"id": a, "name": localized(a), "unit": units[a], "quantity": "reported concentration",
                              "sourceRefs": refs("ntgs-12le002-assays.csv", "analyte:" + a)})
    seen = {}
    for a in assays:
        sid = f"nt-{a['sampleId']}"
        if sid not in seen:
            seen[sid] = (float(a["from"]), float(a["to"]))
            p["supports"].append(support(sid, hole, float(a["from"]), float(a["to"]),
                                         refs("ntgs-12le002-assays.csv", a["sourceRow"]),
                                         f"sample {a['sampleId']}, {a['sampleMethod']}", sample=a["sampleId"]))
        p["determinations"].append(determination(
            f"{sid}:{a['analyte']}", sid, a["analyte"], _float(a["value"]), a["sourceResultText"], a["unit"],
            refs("ntgs-12le002-assays.csv", a["sourceRow"]), state=STATES[a["qualifier"]],
            limit=_float(a["detectionLimit"]), method=a["labMethod"], lab=None))
    if len(seen) != EXPECTED["samples"]:
        raise ValueError("NTGS sample count drift")
    by_support = Counter(seen.values())
    repeated = sorted(f"{lo}-{hi}" for (lo, hi), n in by_support.items() if n > 1)
    cuzn = [d for d in p["determinations"] if d["analyteId"] in ("Cu", "Zn") and d["value"] is not None
            and d["qualifier"] == "="]
    if len(cuzn) != EXPECTED["cuzn"]:
        raise ValueError(f"NTGS Cu/Zn drift: {len(cuzn)}")
    spans = sorted(set(seen.values()))
    gaps = [(a[1], b[0]) for a, b in pairwise(spans) if b[0] > a[1]]
    censored = [d["id"] for d in p["determinations"] if d["qualifier"] in ("<", ">")]
    p["waterfall"] = [
        {"step": "determinations", "count": len(assays)},
        {"step": "censored (below or above detection)", "count": len(censored)},
        {"step": "numeric unqualified Cu and Zn", "count": len(cuzn)},
        {"step": "distinct Cu/Zn supports", "count": len({seen[d['supportId']] for d in cuzn})},
    ]
    issue(p, "REPEATED_SUPPORTS", "supports", repeated,
          "Distinct sample identities share one depth interval.", "Kept as separate determinations in one split group.")
    issue(p, "SAMPLING_GAPS", "supports", [f"{lo}-{hi}" for lo, hi in gaps],
          f"{len(gaps)} unsampled gaps inside the sampled span.", "Unsampled length stays unsampled.")
    issue(p, "CENSORED_RESULTS", "determinations", censored,
          "Below-detection results encoded in the source as negative limits and '<limit' text.",
          "Qualifier and limit kept; no numeric value; no substitution.")
    issue(p, "TERMINAL_EXTENSION", "surveys", [f"md={s['md']}" for s in surveys if s["role"] not in ("measured-single-shot", "recorded-collar-direction")],
          "The compiled final record repeats the last orientation at total depth.", "Not counted as a measurement.")
    issue(p, "SINGLE_HOLE_FAMILY", "collars", [hole],
          "One hole cannot support grouped spatial evaluation.", "Used for desurvey, logs, censoring and QA scenarios.")
    return p
