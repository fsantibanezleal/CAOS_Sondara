"""The preprocess stage: exact desurvey, support positions, compositing, log overlay and modeling populations.

GeoCond does the geometry and the compositing (``geocond.geometry.Survey``, ``geocond.compositing``); this module
applies Sondara's declared policies to a canonical project and records every decision next to its result:

- **Trajectories.** One GeoCond survey per hole, built from what the source supports: the assumed vertical direction,
  the recorded collar direction, or the recorded collar direction followed by the measured stations. Every survey ends
  with a declared tangent extension to total depth; a one-station survey is a straight projection, so every position
  below its collar is flagged ``extended``. Nothing is resampled or smoothed.
- **Support positions.** Interval and envelope supports get their start, mid and end positions on the arc; point
  supports their single position. Unknown supports get none.
- **Compositing (known continuous intervals only).** Per hole, fixed-length composites anchored at the first sampled
  depth; a composite that touches a gap or a missing value is kept with its numerator and valid length but has no
  mean (minimum coverage 1); the last short composite is kept as a labelled residual. Only full composites enter a
  uniform-support population. Length and grade-length integrals are checked for conservation per hole.
- **Log overlay (logged geology against sampling envelopes).** Logs are cut into elementary pieces at every endpoint;
  a piece covered by logs with two different known codes is a conflict, not a choice. Envelope coverage and category
  proportions come from ``geocond.compositing.composite_categories``.
- **Populations.** Each modeling task names its members, its support and its rule; excluded rows are counted with a
  reason, and a family that cannot support a task says so.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import pairwise

import geocond
import numpy as np
from geocond.compositing import composite_categories, composite_intervals, fixed_boundaries
from geocond.geometry import Survey
from source_io import stable_hash

SCHEMA = "drillhole.preprocessed/v1"
COMPOSITE_LENGTHS = (1.0, 2.0, 5.0)
MIN_COVERAGE = 1.0
MEASURED_ROLES = ("recorded-collar-direction", "measured-single-shot")
UNKNOWN_CODES = {None, "", "-9999"}
TOLERANCE = 1e-9

RECIPE = {
    "trajectories": "GeoCond minimum curvature; assumed-vertical = one station (azimuth 0, dip -90) at the collar; "
                    "collar-orientation = the recorded direction at the collar; measured-stations = the recorded "
                    "collar direction and the measured stations; tangent extension to total depth in every case",
    "positions": "interval and envelope supports at start, mid and end measured depth on the arc; points at their depth",
    "compositing": "known continuous intervals only; per hole, fixed boundaries from the first sampled depth; lengths "
                   "1, 2 and 5 m; minimum coverage 1; last short composite kept as a residual; no bridging",
    "overlay": "positive-length logs cut at every endpoint; two different known codes on one piece are a conflict; "
               "codes '', '-9999' and null are unknown; coverage and proportions by GeoCond composite_categories",
}


def _vec(points):
    return [float(v) for v in points]


def build_surveys(project: dict) -> dict[str, Survey]:
    """One GeoCond survey per collar, from the trajectory kind the ingest recorded."""
    kinds = {t["holeId"]: t["kind"] for t in project["trajectories"]}
    stations = defaultdict(list)
    for s in project["surveys"]:
        if s["role"] in MEASURED_ROLES:
            stations[s["holeId"]].append(s)
    surveys = {}
    for c in project["collars"]:
        collar = [c["x"], c["y"], c["z"]]
        kind = kinds[c["id"]]
        if kind == "assumed-vertical":
            rows = [{"md": 0.0, "azimuth": 0.0, "dip": -90.0}]
        elif kind == "collar-orientation":
            rows = [s for s in stations[c["id"]] if s["role"] == "recorded-collar-direction"]
        elif kind == "measured-stations":
            rows = sorted(stations[c["id"]], key=lambda s: s["md"])
            if not rows or rows[0]["md"] != 0 or rows[0]["role"] != "recorded-collar-direction":
                raise ValueError(f"{c['id']}: measured stations need the recorded collar direction at MD 0")
        else:
            raise ValueError(f"{c['id']}: unknown trajectory kind {kind!r}")
        if not rows:
            raise ValueError(f"{c['id']}: no direction for a {kind} trajectory")
        surveys[c["id"]] = Survey(collar, [r["md"] for r in rows], [r["azimuth"] for r in rows],
                                  [r["dip"] for r in rows], end_extension="tangent")
    return surveys


def trajectory_records(project: dict, surveys: dict[str, Survey]) -> list[dict]:
    kinds = {t["holeId"]: t["kind"] for t in project["trajectories"]}
    out = []
    for c in project["collars"]:
        survey = surveys[c["id"]]
        end_md = c["totalDepth"] if c["totalDepth"] is not None else c["observedDepthMax"]
        end = survey.at([end_md])
        doglegs = np.degrees(survey.dogleg_radians)
        out.append({
            "holeId": c["id"], "kind": kinds[c["id"]], "method": "minimum-curvature",
            "stations": [{"md": float(md), "azimuth": float(az), "dip": float(dp), "position": _vec(p)}
                         for md, az, dp, p in zip(survey.measured_depth, survey.azimuth, survey.dip,
                                                  survey.station_points, strict=True)],
            "endExtension": "tangent", "endMd": float(end_md), "endPosition": _vec(end.points[0]),
            "endExtended": bool(end.extended[0]),
            "maxDoglegDegrees": float(doglegs.max()) if len(doglegs) else 0.0,
        })
    return out


def support_positions(project: dict, surveys: dict[str, Survey]) -> list[dict]:
    out = []
    for s in project["supports"]:
        survey = surveys[s["holeId"]]
        row = {"supportId": s["id"], "holeId": s["holeId"], "kind": s["kind"]}
        if s["kind"] in ("interval", "sampling-envelope"):
            a, b = s["fromMd"], s["toMd"]
            at = survey.at([a, (a + b) / 2, b])
            row.update({"fromMd": a, "toMd": b, "from": _vec(at.points[0]), "mid": _vec(at.points[1]),
                        "to": _vec(at.points[2]), "extended": bool(at.extended.any())})
        elif s["kind"] == "point":
            at = survey.at([s["atMd"]])
            row.update({"atMd": s["atMd"], "at": _vec(at.points[0]), "extended": bool(at.extended[0])})
        out.append(row)
    return out


def _values(project: dict) -> dict[str, dict[str, float]]:
    table = defaultdict(dict)
    for d in project["determinations"]:
        if d["qualifier"] == "=" and d["value"] is not None:
            table[d["supportId"]][d["analyteId"]] = d["value"]
    return table


def composite_family(project: dict, surveys: dict[str, Survey], analytes: list[str]) -> dict:
    """Fixed-length composites of every hole's known continuous intervals, with a per-hole conservation check."""
    values = _values(project)
    by_hole = defaultdict(list)
    for s in project["supports"]:
        if s["kind"] == "interval":
            by_hole[s["holeId"]].append(s)
    rows, checks = [], {}
    for length in COMPOSITE_LENGTHS:
        worst = 0.0
        for hole in sorted(by_hole):
            supports = sorted(by_hole[hole], key=lambda s: s["fromMd"])
            a = np.array([s["fromMd"] for s in supports])
            b = np.array([s["toMd"] for s in supports])
            ids = [s["id"] for s in supports]
            edges = fixed_boundaries(float(a[0]), float(b[-1]), length, residual="keep")
            per_analyte = {}
            for analyte in analytes:
                z = np.array([values[i].get(analyte, np.nan) for i in ids])
                per_analyte[analyte] = composite_intervals(a, b, z, edges, source_ids=ids, min_coverage=MIN_COVERAGE)
                source = float(np.nansum((b - a) * z))
                total = sum(c.numerator for c in per_analyte[analyte])
                worst = max(worst, abs(total - source) / max(1.0, abs(source)))
            first = per_analyte[analytes[0]]
            survey = surveys[hole]
            mids = survey.at([(c.start + c.end) / 2 for c in first])
            for k, c in enumerate(first):
                estimated = all(per_analyte[x][k].status == "estimated" for x in analytes)
                if not estimated:
                    status = "insufficient-coverage"
                elif c.end - c.start < length - TOLERANCE:
                    status = "residual"
                else:
                    status = "full"
                rows.append({
                    "id": f"{hole}:c{length:g}m:{k}", "holeId": hole, "length": length,
                    "fromMd": c.start, "toMd": c.end, "status": status, "coverage": c.coverage,
                    "validLength": c.valid_length, "missingLength": c.missing_length,
                    "mid": _vec(mids.points[k]),
                    "values": {x: (None if np.isnan(per_analyte[x][k].mean) else per_analyte[x][k].mean)
                               for x in analytes},
                    "numerators": {x: per_analyte[x][k].numerator for x in analytes},
                    "parents": [[pid, overlap] for pid, overlap in c.parents],
                })
        if worst > 1e-12:
            raise ValueError(f"compositing at {length:g} m does not conserve the grade-length integral ({worst:.3e})")
        checks[f"{length:g}m"] = worst
    return {"lengths": list(COMPOSITE_LENGTHS), "minCoverage": MIN_COVERAGE, "residual": "keep",
            "anchor": "first sampled depth of the hole", "analytes": analytes,
            "conservationMaxRelativeError": checks, "rows": rows}


def _pieces(logs: list[dict], field: str) -> dict:
    """Cut positive-length logs at every endpoint; label each piece by its single known code, or flag a conflict.

    Returns the piece starts, ends and labels, the conflicts (two different known codes on one piece) and the pieces
    covered by more than one log (the source's own overlapping log intervals, kept as recorded).
    """
    edges = sorted({g["fromMd"] for g in logs} | {g["toMd"] for g in logs})
    out = {"starts": [], "ends": [], "labels": [], "conflicts": [], "multiple": []}
    for lo, hi in pairwise(edges):
        cover = [g for g in logs if g["fromMd"] < hi - TOLERANCE and g["toMd"] > lo + TOLERANCE]
        if not cover:
            continue
        codes = {"logged"} if field == "logged" else {g[field] for g in cover} - UNKNOWN_CODES
        out["starts"].append(lo)
        out["ends"].append(hi)
        if len(cover) > 1:
            out["multiple"].append((lo, hi, [g["id"] for g in cover]))
        if len(codes) > 1:
            out["labels"].append(None)
            out["conflicts"].append({"fromMd": lo, "toMd": hi, "codes": sorted(codes),
                                     "logIds": [g["id"] for g in cover]})
        else:
            out["labels"].append(next(iter(codes), None))
    return out


def _overlap(a, b, lo, hi):
    return max(0.0, min(b, hi) - max(a, lo))


def overlay_envelopes(project: dict) -> dict:
    """Coverage of every sampling envelope by any log, by known Litho_unit and by known Rock_type.

    Coverage is the length share of the envelope under pieces with a known label; ``coveredLength`` is that length in
    metres, summed over envelopes (overlapping envelopes each count their own length). A piece in conflict counts as
    not covered by a known code.
    """
    logs = defaultdict(list)
    for g in project["geology"]:
        if g["kind"] == "interval":
            logs[g["holeId"]].append(g)
    fields = {"anyLog": "logged", "lithoUnit": "lithoUnit", "rockType": "rockType"}
    pieces = {(hole, name): _pieces(rows, field) for hole, rows in logs.items() for name, field in fields.items()}
    conflicts = [{"holeId": hole, "field": name, **c}
                 for hole in logs for name in ("lithoUnit", "rockType") for c in pieces[(hole, name)]["conflicts"]]
    rows = []
    for s in project["supports"]:
        if s["kind"] != "sampling-envelope":
            continue
        a, b = s["fromMd"], s["toMd"]
        row = {"supportId": s["id"], "holeId": s["holeId"], "fromMd": a, "toMd": b, "length": b - a}
        for name in fields:
            p = pieces.get((s["holeId"], name))
            if not p or not p["starts"]:
                row[name] = {"coverage": 0.0, "coveredLength": 0.0, "fullyCovered": False, "proportions": {},
                             "missingLength": b - a}
                continue
            result = composite_categories(p["starts"], p["ends"], p["labels"], [a, b])[0]
            coverage = float(result["coverage"])
            row[name] = {"coverage": coverage, "coveredLength": coverage * (b - a),
                         "fullyCovered": bool(coverage >= 1 - TOLERANCE),
                         "proportions": result["proportions"], "missingLength": float(result["missing_length"])}
        multiple = pieces.get((s["holeId"], "anyLog"), {"multiple": []})["multiple"]
        row["multiplyLoggedLength"] = sum(_overlap(a, b, lo, hi) for lo, hi, _ in multiple)
        rows.append(row)
    summary = {"envelopes": len(rows), "envelopeLength": round(sum(r["length"] for r in rows), 6),
               "multiplyLoggedEnvelopes": sum(r["multiplyLoggedLength"] > TOLERANCE for r in rows)}
    for name in fields:
        summary[name] = {"fullyCovered": sum(r[name]["fullyCovered"] for r in rows),
                         "coveredLength": round(sum(r[name]["coveredLength"] for r in rows), 6)}
    return {"rows": rows, "conflicts": conflicts, "summary": summary}


def sampling_gaps(project: dict) -> list[dict]:
    """Unsampled stretches between the distinct interval supports of each hole."""
    by_hole = defaultdict(set)
    for s in project["supports"]:
        if s["kind"] in ("interval", "sampling-envelope"):
            by_hole[s["holeId"]].add((s["fromMd"], s["toMd"]))
    gaps = []
    for hole, spans in sorted(by_hole.items()):
        reach = None
        for a, b in sorted(spans):
            if reach is not None and a > reach + TOLERANCE:
                gaps.append({"holeId": hole, "fromMd": reach, "toMd": a, "length": a - reach})
            reach = b if reach is None else max(reach, b)
    return gaps


def _population(identifier, task, support, members, holes, rule, excluded=None):
    return {"id": identifier, "task": task, "support": support, "count": len(members), "holes": len(set(holes)),
            "rule": rule, "excluded": excluded or {}, "members": members}


def rocklea(project, surveys):
    analytes = [a["id"] for a in project["analytes"]]
    composites = composite_family(project, surveys, analytes)
    supports = [s for s in project["supports"] if s["kind"] == "interval"]
    populations = [_population(
        "rocklea-native-1m", "grade and multivariable estimation", "original 1 m interval",
        [s["id"] for s in supports], [s["holeId"] for s in supports],
        "every eligible ingested interval: unique source collar, not zero in every analyte, 11 analytes complete")]
    for length in COMPOSITE_LENGTHS[1:]:
        full = [r for r in composites["rows"] if r["length"] == length and r["status"] == "full"]
        other = [r for r in composites["rows"] if r["length"] == length and r["status"] != "full"]
        populations.append(_population(
            f"rocklea-composite-{length:g}m", "grade and multivariable estimation", f"{length:g} m composite",
            [r["id"] for r in full], [r["holeId"] for r in full],
            f"full {length:g} m composites with coverage 1",
            {"residual": sum(r["status"] == "residual" for r in other),
             "insufficientCoverage": sum(r["status"] == "insufficient-coverage" for r in other)}))
    gaps = sampling_gaps(project)
    waterfall = []
    for length in COMPOSITE_LENGTHS:
        rows = [r for r in composites["rows"] if r["length"] == length]
        waterfall.append({"step": f"{length:g} m composites", "count": len(rows),
                          "full": sum(r["status"] == "full" for r in rows),
                          "residual": sum(r["status"] == "residual" for r in rows),
                          "insufficientCoverage": sum(r["status"] == "insufficient-coverage" for r in rows)})
    return {"composites": composites, "gaps": gaps, "populations": populations, "waterfall": waterfall}


def alberta(project, surveys):
    overlay = overlay_envelopes(project)
    envelopes = [s for s in project["supports"] if s["kind"] == "sampling-envelope"]
    points = [s for s in project["supports"] if s["kind"] == "point"]
    unknown = [s for s in project["supports"] if s["kind"] == "unknown"]
    populations = [
        _population("alberta-envelope-centre-cu-zn", "sampling-envelope-centre-approximation", "envelope centre",
                    [s["id"] for s in envelopes], [s["holeId"] for s in envelopes],
                    "positive sampling envelopes with numeric Cu and Zn, placed at their measured-depth centre; "
                    "no averaging, recompositing or support integration (component weights unknown)",
                    {"point": len(points), "unknown": len(unknown)}),
        _population("alberta-point-samples", "display and QA only", "point depth",
                    [s["id"] for s in points], [s["holeId"] for s in points],
                    "point-depth samples; kept apart from the envelope-centre task and never widened"),
    ]
    beyond = [s["id"] for s in project["supports"]
              if s["kind"] in ("sampling-envelope", "point")
              and max(v for v in (s["toMd"], s["atMd"]) if v is not None) > _total_depth(project, s["holeId"])]
    waterfall = [
        {"step": "supports", "count": len(project["supports"])},
        {"step": "positioned (envelope or point)", "count": len(envelopes) + len(points)},
        {"step": "envelope-centre population", "count": len(envelopes)},
        {"step": "envelopes fully covered by any log", "count": overlay["summary"]["anyLog"]["fullyCovered"]},
        {"step": "envelopes fully covered by a known Litho_unit",
         "count": overlay["summary"]["lithoUnit"]["fullyCovered"]},
        {"step": "envelopes fully covered by a known Rock_type", "count": overlay["summary"]["rockType"]["fullyCovered"]},
    ]
    return {"overlay": overlay, "gaps": sampling_gaps(project), "populations": populations, "waterfall": waterfall,
            "beyondTotalDepth": beyond}


def ntgs(project, surveys):
    gaps = sampling_gaps(project)
    groups = defaultdict(list)
    for s in project["supports"]:
        groups[(s["fromMd"], s["toMd"])].append(s["id"])
    repeats = [{"fromMd": a, "toMd": b, "supportIds": ids} for (a, b), ids in sorted(groups.items()) if len(ids) > 1]
    censored = defaultdict(lambda: {"numeric": 0, "censored": 0})
    for d in project["determinations"]:
        censored[d["analyteId"]]["censored" if d["qualifier"] in ("<", ">") else "numeric"] += 1
    supports = project["supports"]
    populations = [
        _population("ntgs-measured-desurvey", "desurvey, interval log, censoring and repeat QA", "original interval",
                    [s["id"] for s in supports], [s["holeId"] for s in supports],
                    "every sample of the one measured-survey hole; repeats share one split group"),
        _population("ntgs-estimation", "grouped estimation and learned-model evaluation", "none", [], [],
                    "not eligible: one hole cannot form grouped training and test sets",
                    {"singleHole": len(supports)}),
    ]
    waterfall = [
        {"step": "supports", "count": len(supports)},
        {"step": "distinct interval geometries", "count": len(groups)},
        {"step": "sampling gaps", "count": len(gaps)},
        {"step": "repeated supports", "count": len(repeats)},
    ]
    return {"gaps": gaps, "repeats": repeats, "censoring": dict(sorted(censored.items())),
            "populations": populations, "waterfall": waterfall}


def _total_depth(project, hole):
    collar = next(c for c in project["collars"] if c["id"] == hole)
    return collar["totalDepth"] if collar["totalDepth"] is not None else float("inf")


FAMILIES = {"rocklea": rocklea, "alberta": alberta, "ntgs": ntgs}


def preprocess(family: str, project: dict, project_sha256: str) -> dict:
    surveys = build_surveys(project)
    result = FAMILIES[family](project, surveys)
    return {
        "schema": SCHEMA, "family": family, "projectId": project["id"], "inputProjectSha256": project_sha256,
        "recipe": RECIPE, "recipeSha256": stable_hash(RECIPE), "engine": {"geocond": geocond.__version__},
        "frameId": project["frames"][0]["id"],
        "trajectories": trajectory_records(project, surveys),
        "positions": support_positions(project, surveys),
        **result,
    }
