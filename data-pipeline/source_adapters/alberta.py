"""AGS DIG 2024-0022, report MAR_19860002: recorded collar orientations, native sampling envelopes, logged geology.

What the source supports, and what it does not (``docs/cases/alberta.md``):

- 22 collars with Easting, Northing and ground elevation in NAD83 / 10TM (central meridian -115 degrees), total depth,
  azimuth and dip. ``Inclnation = 90 + Survey_dip`` holds for every row, so ``Survey_dip`` is a negative-downward dip
  from horizontal. These are recorded collar directions: there is no station-survey table, and the azimuth's north
  reference and the vertical datum are not given. Trajectories are straight lines along the recorded direction and
  are labelled ``collar-orientation``.
- Samples are sampling envelopes, not intervals: many notes describe composites or spaced sampling, and positive
  envelopes overlap. A positive envelope keeps ``unknown`` component weights; a zero-length sample stays a point; a
  sample without endpoints has unknown support. None is widened, averaged or recomposited.
- Every populated analyte cell becomes a determination with its raw token; ``-9999`` and empty are missing, a ``<`` or
  ``>`` prefix is a qualifier with its threshold, and nothing is imputed. LOI at three temperatures are three methods,
  not replicates.
- Geology keeps the source's ``Rock_type``, ``Litho_unit`` and ``Material`` codes verbatim under their column names,
  and the description verbatim; point rows (top equal to bottom) are events.
"""

from collections import Counter

from source_adapters.common import (
    collar,
    determination,
    frame,
    issue,
    localized,
    orientation,
    project,
    refs,
    source,
    support,
    survey,
    trajectory,
)
from source_io import digest, zip_table

ARCHIVE = "DIG_2024_0022_0.zip"
SHA256 = "ba7989acb3a433eb0514bba31305e64538ba99266e9be03b4c8d0039641af7f5"
REPORT = "MAR_19860002"
MEMBERS = {
    "collars": "DIG_2024_0022_Drillhole_Details.txt",
    "intervals": "DIG_2024_0022_Drillhole_Interval_Data.txt",
    "assays": "DIG_2024_0022_Drillhole_Assay_Data.txt",
}
FIRST_ANALYTE = "AcdIns_pct"
MISSING = {"", "-9999"}
EXPECTED = {"collars": 22, "geology": 150, "assay_rows": 3717, "cuzn_samples": 342, "positive_envelopes": 176,
            "envelope_holes": 22, "overlap_pairs": 85}


def _unit(column: str) -> str:
    suffix = column.rsplit("_", 1)[-1]
    return {"pct": "wt%", "ppm": "ppm", "ppb": "ppb", "ozt": "oz/t", "g": "g", "mg": "mg", "ug": "ug",
            "oz": "oz", "KeV": "keV"}.get(suffix, suffix)


def _parse(token: str):
    """(value, state, limit): '<x' -> censored-below at x; '>x' -> censored-above at x; a number -> measured."""
    raw = token.strip()
    if raw[0] in "<>":
        return None, "censored-below" if raw[0] == "<" else "censored-above", float(raw[1:])
    return float(raw), "measured", None


def _code(token: str):
    """A source code kept verbatim; an empty field is no code."""
    return token if token.strip() else None


def _number(token: str):
    raw = token.strip()
    return None if raw in MISSING else float(raw)


def normalize(cache):
    path = cache / ARCHIVE
    if digest(path) != SHA256:
        raise ValueError("Alberta archive hash mismatch")
    sources = [source("DIG_2024_0022_0", "https://static.ags.aer.ca/files/document/DIG/DIG_2024_0022_0.zip",
                      "OGL-Alberta", "Alberta Energy Regulator / Alberta Geological Survey, DIG 2024-0022", SHA256,
                      "zip:tsv", "cp1252")]
    p = project(
        "alberta", localized("Alberta MAR_19860002: historical collars and sampling envelopes",
                             "Alberta MAR_19860002: collares históricos y envolventes de muestreo"),
        sources,
        "alberta-v1: report MAR_19860002; (Data_src, DH_name) keys; recorded collar directions as straight "
        "trajectories; positive samples as sampling envelopes with unknown weights; raw analytical tokens retained",
        frame("alberta-10tm", "projected-metric",
              horizontal_definition="NAD83 / 10TM, central meridian -115 degrees (source metadata)",
              assumptions=["Horizontal definition from the archive metadata; not mapped to an EPSG code.",
                           "Ground elevation in metres; vertical datum deferred to the original reports.",
                           "Azimuth north reference (true, grid or magnetic) not given by the source."]),
    )
    def archive(member):
        return zip_table(path, member, encoding="cp1252", delimiter="\t")

    collars = [r for r in archive(MEMBERS["collars"]) if r["Data_src"] == REPORT]
    keys = [(r["Data_src"], r["DH_name"]) for r in collars]
    if len(keys) != EXPECTED["collars"] or len(set(keys)) != len(keys):
        raise ValueError("Alberta collar population drift")
    holes = {}
    for r in collars:
        hole = r["DH_name"]
        dip, inclination = float(r["Survey_dip"]), float(r["Inclnation"])
        if abs(inclination - (90.0 + dip)) > 1e-9:
            raise ValueError(f"Alberta {hole}: Inclnation is not 90 + Survey_dip")
        total = float(r["Total_dpth"])
        holes[hole] = total
        lineage = refs("DIG_2024_0022_0", f"collars:{r['_row']}")
        azimuth = float(r["Azimuth"])
        p["collars"].append(collar(hole, "alberta", hole, "alberta-10tm", float(r["E_10TM83"]), float(r["N_10TM83"]),
                                   float(r["Elvtn_grnd"]), lineage, total_depth=total,
                                   orientation=orientation(azimuth, dip, "unknown", inclination)))
        p["surveys"].append(survey(f"ab-srv-{hole}", hole, 0.0, azimuth, dip, "recorded-collar-direction", lineage))
        p["trajectories"].append(trajectory(hole, "collar-orientation", lineage, valid_to=total,
                                            azimuth_assumption="source azimuth, north reference unknown"))

    geology = [r for r in archive(MEMBERS["intervals"]) if r["Data_src"] == REPORT]
    if len(geology) != EXPECTED["geology"] or any(r["DH_name"] not in holes for r in geology):
        raise ValueError("Alberta geology population drift or orphan")
    for r in geology:
        top, bottom = _number(r["Intrvl_top"]), _number(r["Intrvl_btm"])
        event = top is not None and top == bottom
        p["geology"].append({"id": f"ab-geo-{r['AGS_ID']}", "holeId": r["DH_name"],
                             "kind": "event" if event else "interval",
                             "fromMd": None if event else top, "toMd": None if event else bottom,
                             "atMd": top if event else None,
                             "codes": {"Rock_type": _code(r["Rock_type"]), "Litho_unit": _code(r["Litho_unit"]),
                                       "Material": _code(r["Material"])},
                             "description": _code(r["Intrvl_dsc"]), "mappedCode": None, "mappingVersion": None,
                             "sourceRefs": refs("DIG_2024_0022_0", f"intervals:{r['_row']}")})

    rows = [r for r in archive(MEMBERS["assays"]) if r["Data_src"] == REPORT]
    if len(rows) != EXPECTED["assay_rows"] or any(r["DH_name"] not in holes for r in rows):
        raise ValueError("Alberta assay population drift or orphan")
    columns = list(rows[0].keys())
    analytes = [c for c in columns[columns.index(FIRST_ANALYTE):] if c not in ("Compiler", "Publisher")]
    populated = [c for c in analytes if any(r[c].strip() not in MISSING for r in rows)]
    for c in populated:
        p["analytes"].append({"id": c, "name": localized(c), "unit": _unit(c),
                             "quantity": "reported value; unit from the source column name",
                             "sourceRefs": refs("DIG_2024_0022_0", "header:" + c)})
    samples = {}
    for r in rows:
        key = (r["DH_name"], r["Sample_nme"])
        sid = f"ab-{r['DH_name']}-{r['Sample_nme']}"
        lineage = refs("DIG_2024_0022_0", f"assays:{r['_row']}")
        if key not in samples:
            top, bottom = _number(r["Smpl_int_t"]), _number(r["Smpl_int_b"])
            samples[key] = sid
            envelope = support(sid, r["DH_name"], top, bottom, lineage, r["Sample_nte"].strip() or None,
                               sample=r["Sample_nme"], unknown_weights=True)
            p["supports"].append(envelope)
        for c in populated:
            token = r[c]
            if token.strip() in MISSING:
                continue
            value, state, threshold = _parse(token)
            p["determinations"].append(determination(
                f"{sid}:{c}:{r['AGS_ID']}", sid, c, value, token, _unit(c), lineage, state=state,
                limit=threshold, method=r["Methd_code"].strip() or None, lab=r["Lab_name"].strip() or None))

    cuzn = {}
    for d in p["determinations"]:
        if d["analyteId"] in ("Cu_ppm", "Zn_ppm") and d["value"] is not None:
            cuzn.setdefault(d["supportId"], set()).add(d["analyteId"])
    both = [s for s, a in cuzn.items() if a == {"Cu_ppm", "Zn_ppm"}]
    by_id = {s["id"]: s for s in p["supports"]}
    positive = [by_id[s] for s in both if by_id[s]["kind"] == "sampling-envelope"]
    point = [by_id[s] for s in both if by_id[s]["kind"] == "point"]
    unknown = [by_id[s] for s in both if by_id[s]["kind"] == "unknown"]
    if (len(both), len(positive), len({s["holeId"] for s in positive})) != (
            EXPECTED["cuzn_samples"], EXPECTED["positive_envelopes"], EXPECTED["envelope_holes"]):
        raise ValueError(f"Alberta Cu/Zn population drift: {len(both)}, {len(positive)}")
    overlaps = []
    per_hole = {}
    for s in positive:
        per_hole.setdefault(s["holeId"], []).append(s)
    for group in per_hole.values():
        group.sort(key=lambda s: (s["fromMd"], s["toMd"], s["id"]))
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if b["fromMd"] < a["toMd"] and a["fromMd"] < b["toMd"]:
                    overlaps.append(f"{a['id']}|{b['id']}")
    if len(overlaps) != EXPECTED["overlap_pairs"]:
        raise ValueError(f"Alberta overlap drift: {len(overlaps)}")
    composite_notes = [s["id"] for s in positive if s["sourceDescription"] and "composite" in s["sourceDescription"].lower()]
    loi = Counter(d["supportId"] for d in p["determinations"] if d["analyteId"].startswith("LOI"))

    p["waterfall"] = [
        {"step": "report assay rows", "count": len(rows)},
        {"step": "samples with numeric Cu and Zn", "count": len(both)},
        {"step": "positive sampling envelopes", "count": len(positive), "excluded": {"point": len(point), "unknown": len(unknown)}},
        {"step": "holes with positive envelopes", "count": len({s["holeId"] for s in positive})},
    ]
    issue(p, "SAMPLING_ENVELOPE_UNKNOWN_WEIGHTS", "supports", [s["id"] for s in positive],
          "Positive sample endpoints bound an envelope; the sampled components and their weights are unknown.",
          "Kept as sampling envelopes: no uniform-interval averaging, recompositing or integrated covariance.")
    issue(p, "COMPOSITE_NOTES", "supports", composite_notes,
          "These sample notes describe composites or spaced sampling.", "Retained with the source note for review.")
    issue(p, "OVERLAPPING_ENVELOPES", "supports", overlaps,
          "Positive envelopes of one hole overlap (including nested basal samples).",
          "Not averaged or split; overlapping samples stay separate observations with their groups.")
    issue(p, "POINT_OR_UNKNOWN_SUPPORT", "supports", [s["id"] for s in point + unknown],
          "Zero-length or endpoint-free samples.", "Kept as point or unknown support; never widened.")
    issue(p, "LOI_METHODS_NOT_REPLICATES", "determinations", [s for s, n in loi.items() if n > 1],
          "LOI at different temperatures are method-dependent quantities.", "Kept as distinct methods; not averaged.")
    issue(p, "UNKNOWN_AZIMUTH_REFERENCE", "collars", sorted(holes),
          "The source gives no true, grid or magnetic reference for collar azimuths.",
          "Trajectories use the source azimuth and state the unknown reference.")
    issue(p, "COLLAR_ORIENTATION_ONLY", "trajectories", sorted(holes),
          "No station surveys: the recorded collar direction is extended to total depth.", "Labelled collar-orientation.")
    return p
