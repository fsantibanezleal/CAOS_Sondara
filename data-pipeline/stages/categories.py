"""The reviewed lithology mapping and the conditioning of a depth grid by logged intervals.

Design: docs/design/features/categorical-simulation/design.md, sections 1 and 2. The mapping file
(``data/interpretations/<family>-lithology-v1.json``) assigns each logged interval to a modeling category by ordered
rules: source codes, the unit named at the start of the description, and position rules for the few codes whose
meaning depends on where they sit; it names the intervals it leaves unmapped and why. The source codes are never
changed. The grid is regular in x, y and depth below a collar surface, and a cell takes the category holding more
than half of the mapped length logged in it; any other logged cell is a recorded conflict, left to the simulation.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from source_io import ROOT, stable_hash

SCHEMA = "drillhole.lithology-mapping/v1"
INTERPRETATIONS = ROOT / "data" / "interpretations"
EVENT_UNCONFORMITY = "unconformity contact"
TOLERANCE = 0.1  # m: an interval "directly above" another ends within this of its top


def load_mapping(family: str) -> dict | None:
    path = INTERPRETATIONS / f"{family}-lithology-v1.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _code(row, field):
    value = (row.get("codes") or {}).get(field)
    return None if value in (None, "", "-9999") else value


def _base_rule(row, rule):
    """Whether a rule's code or description test holds, ignoring its position clause."""
    if "descriptionPrefix" in rule:
        text = (row.get("description") or "").strip()
        return any(text.startswith(p) for p in rule["descriptionPrefix"])
    return _code(row, rule["field"]) in rule["values"]


def _position_holds(r, rule, intervals, first, unconformities) -> bool:
    """A position clause against the hole's other intervals (their pass-one categories) and its unconformity events."""
    kind = rule["position"]
    if kind == "above-category":
        return any(first.get(o["id"]) == rule["positionCategory"] for o in intervals
                   if o["fromMd"] >= r["toMd"] - TOLERANCE)
    if kind == "directly-above-basement":
        below = [o for o in intervals if abs(o["fromMd"] - r["toMd"]) <= TOLERANCE and o["id"] != r["id"]]
        return (any(first.get(o["id"]) in (3, 4) for o in below)
                or any(abs(u - r["toMd"]) <= TOLERANCE for u in unconformities))
    if kind == "below-unconformity":
        return any(u <= r["fromMd"] + TOLERANCE for u in unconformities)
    raise ValueError(f"unknown position rule {kind}")


def map_lithology(project: dict, mapping: dict) -> dict:
    """Every geology row with its category and rule, or ``None`` and the reason it stays unmapped."""
    rules = mapping["rules"]
    unmapped = {(u["field"], v): u["reason"] for u in mapping.get("unmapped", []) for v in u["values"]}
    by_hole = defaultdict(list)
    for r in project["geology"]:
        by_hole[r["holeId"]].append(r)
    out = []
    for hole, rows in sorted(by_hole.items()):
        intervals = sorted((r for r in rows if r["kind"] == "interval"), key=lambda r: (r["fromMd"], r["toMd"]))
        events = [r for r in rows if r["kind"] != "interval"]
        unconformities = [e["atMd"] for e in events if _code(e, "Litho_unit") == EVENT_UNCONFORMITY]
        # Pass one: rules without a position clause.
        first = {}
        for r in intervals:
            for rule in rules:
                if "position" not in rule and _base_rule(r, rule):
                    first[r["id"]] = rule["category"]
                    break

        for r in intervals:
            row = {"geologyId": r["id"], "holeId": hole, "fromMd": r["fromMd"], "toMd": r["toMd"],
                   "codes": {k: r["codes"].get(k) for k in ("Litho_unit", "Rock_type")}, "category": None,
                   "rule": None, "reason": None}
            failed = []
            for rule in rules:
                if not _base_rule(r, rule):
                    continue
                if "position" in rule and not _position_holds(r, rule, intervals, first, unconformities):
                    failed.append(rule["id"])
                    continue
                row.update(category=rule["category"], rule=rule["id"])
                break
            if row["category"] is None:
                named = unmapped.get(("Litho_unit", _code(r, "Litho_unit")))
                row["reason"] = (named or (f"position rule {', '.join(failed)} not satisfied" if failed else None)
                                 or ("no code and no named unit" if _code(r, "Litho_unit") is None
                                     else "no rule assigns this code"))
            out.append(row)
        for e in events:
            out.append({"geologyId": e["id"], "holeId": hole, "fromMd": e.get("atMd"), "toMd": e.get("atMd"),
                        "codes": {k: e["codes"].get(k) for k in ("Litho_unit", "Rock_type")}, "category": None,
                        "rule": None, "reason": "an event, not a volume"})
    counts = defaultdict(int)
    for r in out:
        counts[str(r["category"]) if r["category"] is not None else "unmapped"] += 1
    return {"mappingId": mapping["id"], "mappingSha256": stable_hash(mapping), "categories": mapping["categories"],
            "counts": dict(sorted(counts.items())), "rows": out}


def collar_surface(collars):
    """Inverse-distance (power 2) interpolation of the collar elevations, exact at every collar."""
    xy = np.array([[c["x"], c["y"]] for c in collars], dtype=float)
    z = np.array([c["z"] for c in collars], dtype=float)

    def surface(x, y):
        d2 = (xy[:, 0][None, :] - np.asarray(x, float)[:, None]) ** 2 + (xy[:, 1][None, :] - np.asarray(y, float)[:, None]) ** 2
        exact = d2 < 1e-18
        w = np.where(exact, 0.0, 1.0 / np.where(exact, 1.0, d2))
        value = (w @ z) / w.sum(axis=1)
        hit = exact.any(axis=1)
        value[hit] = z[np.argmax(exact[hit], axis=1)]
        return value

    return surface


@dataclass(frozen=True)
class Grid:
    """A regular grid in x, y and depth below the collar surface; cells indexed (i, j, k), k downward."""

    origin: tuple
    cell: tuple
    shape: tuple

    @classmethod
    def from_mapping(cls, mapping):
        g = mapping["grid"]
        return cls(tuple(g["origin"]), tuple(g["cell"]), tuple(g["shape"]))

    def index(self, x, y, depth):
        ijk = np.floor((np.c_[x, y, depth] - np.array(self.origin)) / np.array(self.cell)).astype(int)
        inside = np.all((ijk >= 0) & (ijk < np.array(self.shape)), axis=1)
        return ijk, inside

    def record(self):
        return {"origin": list(self.origin), "cell": list(self.cell), "shape": list(self.shape)}


def cell_lengths(mapped_rows, surveys, surface, grid: Grid, holes, step: float):
    """Mapped length per cell and category, cutting each interval into pieces of at most ``step`` metres, each in the
    cell of its midpoint (a length error of at most one step per cell boundary crossed)."""
    lengths = defaultdict(lambda: defaultdict(float))
    by_cell_holes = defaultdict(set)
    outside = 0.0
    for r in mapped_rows:
        if r["category"] is None or r["holeId"] not in holes or r["toMd"] <= r["fromMd"]:
            continue
        n = max(1, math.ceil((r["toMd"] - r["fromMd"]) / step - 1e-9))
        edges = np.linspace(r["fromMd"], r["toMd"], n + 1)
        mids = (edges[:-1] + edges[1:]) / 2
        pieces = np.diff(edges)
        xyz = np.asarray(surveys[r["holeId"]].at(list(mids)).points, dtype=float)
        depth = surface(xyz[:, 0], xyz[:, 1]) - xyz[:, 2]
        ijk, inside = grid.index(xyz[:, 0], xyz[:, 1], depth)
        outside += float(pieces[~inside].sum())
        for cell, piece in zip((tuple(int(v) for v in c) for c in ijk[inside]), pieces[inside], strict=True):
            lengths[cell][r["category"]] += float(piece)
            by_cell_holes[cell].add(r["holeId"])
    return lengths, by_cell_holes, outside


def conditioning(lengths, by_cell_holes, majority: float) -> dict:
    """Hard cells where one category holds more than ``majority`` of the logged length; every other cell a conflict."""
    hard, conflicts, mixed = [], [], 0
    for cell in sorted(lengths):
        per = lengths[cell]
        total = sum(per.values())
        category, best = max(sorted(per.items()), key=lambda kv: kv[1])
        if best > majority * total:
            hard.append({"cell": list(cell), "category": category, "length": total,
                         "holes": sorted(by_cell_holes[cell])})
            mixed += len(per) > 1
        else:
            conflicts.append({"cell": list(cell), "candidates": {str(k): v for k, v in sorted(per.items())},
                              "holes": sorted(by_cell_holes[cell])})
    return {"hard": hard, "conflicts": conflicts, "mixedCells": mixed}
