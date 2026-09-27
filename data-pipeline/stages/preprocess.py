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

from collections import Counter, defaultdict
from itertools import pairwise

import geocond
import numpy as np
from geocond.compositing import composite_categories, composite_intervals, fixed_boundaries
from geocond.geometry import Survey
from source_io import stable_hash

SCHEMA = "drillhole.preprocessed/v1"
COMPOSITE_LENGTHS = (1.0, 2.0, 5.0)
MIN_COVERAGE = 1.0
MEASURED_ROLES = ("recorded-collar-direction", "measured")
#: Mass-fraction units and their factor to ppm.
UNIT_TO_PPM = {"ppb": 1e-3, "ppm": 1.0, "g/t": 1.0, "%": 1e4, "wt%": 1e4}
SELECTION_RULES = {"single": "the only measured original result on the geometry",
                   "reassay": "a measured re-assay that replaces an above-range result",
                   "priority": "the first method in the declared priority"}
EXTENSION = {"none": "error", "tangent": "tangent"}
#: Source code columns the overlay reads for each named coverage.
OVERLAY_FIELDS = {"anyLog": None, "lithoUnit": "Litho_unit", "rockType": "Rock_type"}
UNKNOWN_CODES = {None, "", "-9999"}
TOLERANCE = 1e-9

RECIPE = {
    "trajectories": "GeoCond minimum curvature; assumed-vertical = one station (azimuth 0, dip -90) at the collar; "
                    "collar-orientation = the recorded direction at the collar; measured-stations = the recorded "
                    "collar direction and the measured stations (never compiled extensions); start and end "
                    "extensions as the project declares them",
    "positions": "interval and envelope supports at start, mid and end measured depth on the arc; points at their depth",
    "compositing": "known continuous intervals only; per hole, fixed boundaries from the first sampled depth; lengths "
                   "1, 2 and 5 m; minimum coverage 1; last short composite kept as a residual; no bridging",
    "overlay": "positive-length logs cut at every endpoint; codes read verbatim from the Litho_unit and Rock_type "
               "source columns; two different known codes on one piece are a conflict; codes '', '-9999' and null "
               "are unknown; coverage and proportions by GeoCond composite_categories",
}


def _vec(points):
    return [float(v) for v in points]


def build_surveys(project: dict) -> dict[str, Survey]:
    """One GeoCond survey per collar, from the trajectory kind and the extension policies the ingest recorded.

    Stations are the recorded collar direction and the measured rows only; compiled extensions are never stations.
    A first station below the collar is accepted only under a declared start extension.
    """
    kinds = {t["holeId"]: t["kind"] for t in project["trajectories"]}
    policies = {t["holeId"]: (t["startExtension"], t["endExtension"]) for t in project["trajectories"]}
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
            if rows and rows[0]["md"] > 0 and policies[c["id"]][0] != "tangent":
                raise ValueError(f"{c['id']}: the first station is below the collar and no start extension is declared")
        else:
            raise ValueError(f"{c['id']}: unknown trajectory kind {kind!r}")
        if not rows:
            raise ValueError(f"{c['id']}: no direction for a {kind} trajectory")
        start, end = policies[c["id"]]
        surveys[c["id"]] = Survey(collar, [r["md"] for r in rows], [r["azimuth"] for r in rows],
                                  [r["dip"] for r in rows], start_extension=EXTENSION[start],
                                  end_extension=EXTENSION[end])
    return surveys


def trajectory_records(project: dict, surveys: dict[str, Survey]) -> list[dict]:
    """Stations with positions, the end position, the largest dogleg and every extended depth range."""
    policies = {t["holeId"]: t for t in project["trajectories"]}
    out = []
    for c in project["collars"]:
        survey = surveys[c["id"]]
        end_md = c["totalDepth"] if c["totalDepth"] is not None else c["observedDepthMax"]
        end = survey.at([end_md])
        doglegs = np.degrees(survey.dogleg_radians)
        first, last = float(survey.measured_depth[0]), float(survey.measured_depth[-1])
        extended = ([[0.0, first]] if first > 0 else []) + ([[last, float(end_md)]] if end_md > last else [])
        out.append({
            "holeId": c["id"], "kind": policies[c["id"]]["kind"], "method": "minimum-curvature",
            "stations": [{"md": float(md), "azimuth": float(az), "dip": float(dp), "position": _vec(p)}
                         for md, az, dp, p in zip(survey.measured_depth, survey.azimuth, survey.dip,
                                                  survey.station_points, strict=True)],
            "startExtension": policies[c["id"]]["startExtension"],
            "endExtension": policies[c["id"]]["endExtension"],
            "extendedRanges": extended,
            "endMd": float(end_md), "endPosition": _vec(end.points[0]),
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


def convert(value: float, unit: str, target: str) -> float:
    """Convert a mass fraction between ppb, ppm, g/t, % and wt%; any other pair must already agree."""
    if unit == target:
        return value
    if unit in UNIT_TO_PPM and target in UNIT_TO_PPM:
        return value * UNIT_TO_PPM[unit] / UNIT_TO_PPM[target]
    raise ValueError(f"no conversion from {unit} to {target}")


def select_results(project: dict, method_priority: dict | None = None) -> dict:
    """One value per distinct sample geometry and analyte, chosen by a declared rule, or unresolved with a reason.

    Candidates are the results of every original sample on one geometry, minus excluded results. A single measured
    result is selected (named a re-assay when an above-range result shares the geometry); several measured results
    are separated only by the declared method priority; repeats and duplicates are never selected and never add
    support. Values convert to the analyte's unit.
    """
    priority = method_priority or {}
    excluded = {x["rowId"] for x in project["exclusions"] if x["table"] == "determinations"}
    located = {s["id"]: s for s in project["supports"] if s["kind"] != "unknown"}
    units = {a["id"]: a["unit"] for a in project["analytes"]}

    def geometry(s):
        if s["kind"] == "point":
            return s["holeId"], s["atMd"], s["atMd"]
        return s["holeId"], s["fromMd"], s["toMd"]

    representatives, kinds = {}, {}
    for s in located.values():
        g = geometry(s)
        representatives[g] = min(representatives.get(g, s["id"]), s["id"])
        kinds[g] = s["kind"]
    groups = defaultdict(list)
    for d in project["determinations"]:
        s = located.get(d["supportId"])
        if s is not None and d["id"] not in excluded:
            groups[(geometry(s), d["analyteId"])].append(d)
    rows, unresolved = [], []
    for (g, analyte), ds in sorted(groups.items()):
        originals = [d for d in ds if d["sampleRole"] == "original"]
        measured = sorted((d for d in originals if d["state"] == "measured"), key=lambda d: d["id"])
        above = any(d["state"] == "censored-above" for d in originals)
        chosen, rule, reason = None, None, None
        if len(measured) == 1:
            chosen, rule = measured[0], "reassay" if above else "single"
        elif len(measured) > 1:
            order = priority.get(analyte, [])
            ranked = sorted((d for d in measured if d["method"] in order),
                            key=lambda d: (order.index(d["method"]), d["id"]))
            if ranked and (len(ranked) == 1 or order.index(ranked[0]["method"]) < order.index(ranked[1]["method"])):
                chosen, rule = ranked[0], "priority"
            else:
                reason = "several measured results and no declared method priority that separates them"
        else:
            states = sorted({d["state"] for d in originals})
            reason = f"no measured original result ({', '.join(states) or 'repeats only'})"
        if chosen is None:
            unresolved.append({"geometry": list(g), "kind": kinds[g], "analyteId": analyte, "reason": reason,
                               "determinationIds": sorted(d["id"] for d in ds)})
        else:
            rows.append({"geometry": list(g), "kind": kinds[g], "representative": representatives[g],
                         "analyteId": analyte,
                         "determinationId": chosen["id"], "value": convert(chosen["value"], chosen["unit"],
                                                                           units[analyte]),
                         "unit": units[analyte], "rule": rule})
    return {"rules": SELECTION_RULES, "rows": rows, "unresolved": unresolved}


def eligibility(project: dict, selection: dict) -> dict:
    """Eligibility v1: only selected measured original values are modeled; every other result is counted."""
    states = defaultdict(Counter)
    for d in project["determinations"]:
        states[d["analyteId"]][d["state"]] += 1
    return {"version": "eligibility-v1",
            "rule": "only a selected measured original value enters compositing and populations; censored, missing, "
                    "not-sampled, lost-core and sentinel results, repeats and duplicates are counted, never valued",
            "states": {a: dict(sorted(c.items())) for a, c in sorted(states.items())},
            "selected": dict(sorted(Counter(r["analyteId"] for r in selection["rows"]).items())),
            "unresolved": dict(sorted(Counter(r["analyteId"] for r in selection["unresolved"]).items())),
            "excludedResults": sum(x["table"] == "determinations" for x in project["exclusions"])}


def composite_family(project: dict, surveys: dict[str, Survey], analytes: list[str], selection: dict, *,
                     lengths=COMPOSITE_LENGTHS, min_coverage=MIN_COVERAGE) -> dict:
    """Fixed-length composites of the selected values on each hole's interval geometries.

    Each analyte composites over the geometries that carry a selected value for it (a series never overlaps itself
    once overlaps are excluded); all analytes share the hole's boundaries, anchored at its first selected depth. A
    row is full only when every analyte covers it at the minimum coverage and it has the declared length.
    """
    values = defaultdict(dict)
    representative = {}
    for r in selection["rows"]:
        if r["kind"] != "interval":
            continue  # only known continuous intervals composite
        g = tuple(r["geometry"])
        values[g][r["analyteId"]] = r["value"]
        representative[g] = r["representative"]
    by_hole = defaultdict(list)
    for g in values:
        by_hole[g[0]].append(g)
    rows, checks = [], {}
    for length in lengths:
        worst = 0.0
        for hole in sorted(by_hole):
            geoms = sorted(by_hole[hole], key=lambda g: (g[1], g[2]))
            anchor, end = geoms[0][1], max(g[2] for g in geoms)
            edges = fixed_boundaries(float(anchor), float(end), length, residual="keep")
            per = {}
            for analyte in analytes:
                subset = [g for g in geoms if analyte in values[g]]
                if not subset:
                    per[analyte] = None
                    continue
                a = np.array([g[1] for g in subset])
                b = np.array([g[2] for g in subset])
                z = np.array([values[g][analyte] for g in subset])
                per[analyte] = composite_intervals(a, b, z, edges, source_ids=[representative[g] for g in subset],
                                                   min_coverage=min_coverage)
                total = sum(c.numerator for c in per[analyte])
                source = float(np.sum((b - a) * z))
                worst = max(worst, abs(total - source) / max(1.0, abs(source)))
            spans = list(pairwise(edges))
            mids = surveys[hole].at([(lo + hi) / 2 for lo, hi in spans])
            for k, (lo, hi) in enumerate(spans):
                cells = {x: (per[x][k] if per[x] is not None else None) for x in analytes}
                coverage = {x: (c.coverage if c else 0.0) for x, c in cells.items()}
                valid = {x: (c.valid_length if c else 0.0) for x, c in cells.items()}
                estimated = all(c is not None and c.status == "estimated" for c in cells.values())
                status = ("insufficient-coverage" if not estimated
                          else "residual" if hi - lo < length - TOLERANCE else "full")
                parents = {}
                for c in cells.values():
                    for pid, overlap in (c.parents if c else ()):
                        parents.setdefault(pid, overlap)
                rows.append({
                    "id": f"{hole}:c{length:g}m:{k}", "holeId": hole, "length": length,
                    "fromMd": float(lo), "toMd": float(hi), "status": status,
                    "coverage": min(coverage.values()), "validLength": min(valid.values()),
                    "missingLength": float(hi - lo) - min(valid.values()),
                    "mid": _vec(mids.points[k]),
                    "values": {x: (None if c is None or np.isnan(c.mean) else c.mean) for x, c in cells.items()},
                    "numerators": {x: (c.numerator if c else 0.0) for x, c in cells.items()},
                    "observedMeans": {x: (c.numerator / c.valid_length if c and c.valid_length > 0 else None)
                                      for x, c in cells.items()},
                    "coverageByAnalyte": coverage,
                    "parents": [[pid, overlap] for pid, overlap in parents.items()],
                })
        if worst > 1e-12:
            raise ValueError(f"compositing at {length:g} m does not conserve the grade-length integral ({worst:.3e})")
        checks[f"{length:g}m"] = worst
    return {"lengths": list(lengths), "minCoverage": min_coverage, "residual": "keep",
            "anchor": "first selected depth of the hole", "analytes": analytes,
            "conservationMaxRelativeError": checks, "rows": rows}


def overlay_fragments(project: dict) -> dict:
    """Cut every distinct interval geometry at the boundaries of its hole's logs; each geometry is cut once."""
    logs = defaultdict(list)
    for g in project["geology"]:
        if g["kind"] == "interval":
            logs[g["holeId"]].append(g)
    geoms = defaultdict(lambda: defaultdict(list))
    for s in project["supports"]:
        if s["kind"] == "interval" and s["holeId"] in logs:
            geoms[s["holeId"]][(s["fromMd"], s["toMd"])].append(s["id"])
    rows, worst = [], 0.0
    for hole in sorted(geoms):
        columns = sorted({c for g in logs[hole] for c in g["codes"]})
        for (a, b), ids in sorted(geoms[hole].items()):
            cuts = sorted({a, b} | {x for g in logs[hole] for x in (g["fromMd"], g["toMd"]) if a < x < b})
            total = 0.0
            for lo, hi in pairwise(cuts):
                cover = [g for g in logs[hole] if g["fromMd"] < hi - TOLERANCE and g["toMd"] > lo + TOLERANCE]
                rows.append({"holeId": hole, "parent": [a, b], "supportIds": sorted(ids), "fromMd": lo, "toMd": hi,
                             "logIds": [g["id"] for g in cover],
                             "codes": {c: sorted({g["codes"].get(c) for g in cover} - UNKNOWN_CODES) for c in columns}})
                total += hi - lo
            worst = max(worst, abs(total - (b - a)))
    return {"rows": rows, "parentLengthMaxError": worst}


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
        codes = {"logged"} if field is None else {g["codes"].get(field) for g in cover} - UNKNOWN_CODES
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
    fields = OVERLAY_FIELDS
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


def rocklea(project, surveys, selection, options):
    analytes = [a["id"] for a in project["analytes"]]
    composites = composite_family(project, surveys, analytes, selection, lengths=options["lengths"],
                                  min_coverage=options["minCoverage"])
    supports = [s for s in project["supports"] if s["kind"] == "interval"]
    populations = [_population(
        "rocklea-native-1m", "grade and multivariable estimation", "original 1 m interval",
        [s["id"] for s in supports], [s["holeId"] for s in supports],
        "every eligible ingested interval: unique source collar, not zero in every analyte, 11 analytes complete")]
    for length in options["lengths"][1:]:
        full = [r for r in composites["rows"] if r["length"] == length and r["status"] == "full"]
        other = [r for r in composites["rows"] if r["length"] == length and r["status"] != "full"]
        populations.append(_population(
            f"rocklea-composite-{length:g}m", "grade and multivariable estimation", f"{length:g} m composite",
            [r["id"] for r in full], [r["holeId"] for r in full],
            f"full {length:g} m composites with coverage 1",
            {"residual": sum(r["status"] == "residual" for r in other),
             "insufficientCoverage": sum(r["status"] == "insufficient-coverage" for r in other)}))
    return {"composites": composites, "gaps": sampling_gaps(project), "populations": populations,
            "waterfall": _composite_waterfall(composites)}


def _composite_waterfall(composites):
    out = []
    for length in composites["lengths"]:
        rows = [r for r in composites["rows"] if r["length"] == length]
        out.append({"step": f"{length:g} m composites", "count": len(rows),
                    "full": sum(r["status"] == "full" for r in rows),
                    "residual": sum(r["status"] == "residual" for r in rows),
                    "insufficientCoverage": sum(r["status"] == "insufficient-coverage" for r in rows)})
    return out


def alberta(project, surveys, selection, options):
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


def _repeats(project):
    groups = defaultdict(list)
    for s in project["supports"]:
        if s["kind"] == "interval":
            groups[(s["holeId"], s["fromMd"], s["toMd"])].append(s["id"])
    return [{"holeId": h, "fromMd": a, "toMd": b, "supportIds": sorted(ids)}
            for (h, a, b), ids in sorted(groups.items()) if len(ids) > 1], len(groups)


def ntgs(project, surveys, selection, options):
    gaps = sampling_gaps(project)
    repeats, geometries = _repeats(project)
    censored = defaultdict(lambda: {"numeric": 0, "censored": 0})
    for d in project["determinations"]:
        censored[d["analyteId"]]["censored" if d["state"].startswith("censored") else "numeric"] += 1
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
        {"step": "distinct interval geometries", "count": geometries},
        {"step": "sampling gaps", "count": len(gaps)},
        {"step": "repeated supports", "count": len(repeats)},
    ]
    return {"gaps": gaps, "repeats": repeats, "censoring": dict(sorted(censored.items())),
            "populations": populations, "waterfall": waterfall}


def imported(project, surveys, selection, options):
    """A user import: composites per analyte, overlay fragments, gaps, repeats and per-analyte populations."""
    analytes = sorted({r["analyteId"] for r in selection["rows"] if r["kind"] == "interval"})
    composites = (composite_family(project, surveys, analytes, selection, lengths=options["lengths"],
                                   min_coverage=options["minCoverage"]) if analytes else None)
    repeats, geometries = _repeats(project)
    populations = []
    for analyte in analytes:
        native = [r for r in selection["rows"] if r["analyteId"] == analyte]
        populations.append({**_population(
            f"{project['id']}-{analyte}-native", "estimation", "original interval",
            sorted({r["representative"] for r in native}), [r["geometry"][0] for r in native],
            f"every interval geometry with a selected measured {analyte} value"), "analyte": analyte})
        for length in options["lengths"]:
            rows = [r for r in composites["rows"] if r["length"] == length]
            full = [r for r in rows if r["values"][analyte] is not None and r["toMd"] - r["fromMd"] >= length - TOLERANCE]
            populations.append({"analyte": analyte, **_population(
                f"{project['id']}-{analyte}-{length:g}m", "estimation", f"{length:g} m composite",
                [r["id"] for r in full], [r["holeId"] for r in full],
                f"{length:g} m composites whose {analyte} coverage meets {options['minCoverage']:g}",
                {"notCovered": sum(r["values"][analyte] is None for r in rows),
                 "residual": sum(r["values"][analyte] is not None and r["toMd"] - r["fromMd"] < length - TOLERANCE
                                 for r in rows)})})
    waterfall = [{"step": "samples", "count": len(project["supports"])},
                 {"step": "distinct interval geometries", "count": geometries},
                 {"step": "selected values", "count": len(selection["rows"])},
                 {"step": "unresolved selections", "count": len(selection["unresolved"])}]
    out = {"gaps": sampling_gaps(project), "repeats": repeats, "fragments": overlay_fragments(project),
           "populations": populations, "waterfall": waterfall + (_composite_waterfall(composites) if composites else [])}
    if composites:
        out["composites"] = composites
    return out


def _total_depth(project, hole):
    collar = next(c for c in project["collars"] if c["id"] == hole)
    return collar["totalDepth"] if collar["totalDepth"] is not None else float("inf")


FAMILIES = {"rocklea": rocklea, "alberta": alberta, "ntgs": ntgs}


def preprocess(family: str, project: dict, project_sha256: str, options: dict | None = None) -> dict:
    """Run the stage. ``options``: compositing ``lengths`` and ``minCoverage``, and ``methodPriority`` per analyte."""
    options = {"lengths": list(COMPOSITE_LENGTHS), "minCoverage": MIN_COVERAGE, "methodPriority": {},
               **(options or {})}
    surveys = build_surveys(project)
    selection = select_results(project, options["methodPriority"])
    result = FAMILIES.get(family, imported)(project, surveys, selection, options)
    recipe = {**RECIPE, "options": {k: options[k] for k in ("lengths", "minCoverage", "methodPriority")}}
    return {
        "schema": SCHEMA, "family": family, "projectId": project["id"], "inputProjectSha256": project_sha256,
        "recipe": recipe, "recipeSha256": stable_hash(recipe), "engine": {"geocond": geocond.__version__},
        "frameId": project["frames"][0]["id"],
        "trajectories": trajectory_records(project, surveys),
        "positions": support_positions(project, surveys),
        "selections": selection,
        "eligibility": eligibility(project, selection),
        **result,
    }
