"""Import user drillhole files, described by an import manifest, into the canonical project (drillhole.project/v2).

The import is a reviewable transaction (docs/design/features/import-and-fixtures/design.md, section 2). It reads every
file with its declared dialect, keys holes by namespace and exact source identifier, checks frames before any join,
compares collar versions, maps survey angles, turns assay cells into determinations with explicit states, isolates
orphans and invalid records, and reports every finding by file, role, hole, severity and reason. Only an accepted
import writes a project, through a staging directory swapped in at the end; a rejected, pending, cancelled or failed
import leaves the previous project untouched.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import shutil
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from source_adapters.common import (
    collar,
    determination,
    frame,
    localized,
    orientation,
    project,
    refs,
    source,
    support,
    survey,
    trajectory,
)
from source_io import ROOT, stable_hash, write_json

REPORT_SCHEMA = "drillhole.import-report/v1"
FOOT = 0.3048
REQUIRED = {"collar": ("hole", "x", "y", "z"), "survey": ("hole", "depth", "azimuth", "dip"),
            "assay": ("hole", "from", "to"), "lithology": ("hole", "from", "to")}
DEFAULT_DIALECT = {"delimiter": ",", "quote": '"', "decimal": ".", "encoding": "utf-8"}
CHECK_EVERY = 1000


class ImportCancelled(RuntimeError):
    """The caller's cancellation callback returned true; nothing was committed."""


class ManifestInvalid(ValueError):
    """The manifest does not validate against schemas/import.schema.json; no file was read."""


def validate_manifest(manifest: dict) -> list[str]:
    import jsonschema

    schema = json.loads((ROOT / "schemas" / "import.schema.json").read_text(encoding="utf-8"))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message[:200]}"
            for e in jsonschema.Draft202012Validator(schema).iter_errors(manifest)]


def normalized(identifier: str) -> str:
    """Upper case, punctuation removed, leading zeros of digit runs removed: the form in which IDs are compared."""
    text = re.sub(r"[^0-9A-Za-z]", "", identifier).upper()
    return re.sub(r"(?<![0-9])0+(?=[0-9])", "", text)


class Report:
    def __init__(self):
        self.findings: list[dict] = []

    def add(self, code, severity, message, *, file=None, role=None, hole=None, rows=()):
        self.findings.append({"code": code, "severity": severity, "file": file, "role": role, "hole": hole,
                              "rows": [str(r) for r in rows], "message": message})

    def errors(self, scope=None):
        return [f for f in self.findings if f["severity"] == "error"
                and (scope is None or (scope == "hole") == (f["hole"] is not None))]


class Importer:
    def __init__(self, manifest: dict, base: Path, cancel=None):
        self.m = manifest
        self.base = Path(base)
        self.cancel = cancel or (lambda: False)
        self.report = Report()
        self.files: list[dict] = []
        self.rows: dict[str, list] = defaultdict(list)  # role -> [(spec, row)]
        self.checked = 0

    # ---- reading --------------------------------------------------------------------------------------------------
    def _tick(self):
        self.checked += 1
        if self.checked % CHECK_EVERY == 0 and self.cancel():
            raise ImportCancelled("import cancelled")

    def read(self):
        seen = {}
        for spec in self.m["files"]:
            if self.cancel():
                raise ImportCancelled("import cancelled")
            path = self.base / spec["path"]
            role = spec["role"]
            data = path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            # The same bytes read the same way are a duplicate; read under another namespace or mapping they are
            # another source.
            reading = (sha, stable_hash({k: v for k, v in spec.items() if k != "path"}))
            entry = {"path": spec["path"], "role": role, "sha256": sha, "bytes": len(data), "rows": 0,
                     "duplicateOf": seen.get(reading)}
            self.files.append(entry)
            if "sha256" in spec and spec["sha256"] != sha:
                self.report.add("FILE_HASH_MISMATCH", "error", "The file differs from the hash the manifest pins.",
                                file=spec["path"], role=role)
                continue
            if reading in seen:
                self.report.add("FILE_DUPLICATE", "warning", f"Identical to {seen[reading]} and read the same way; "
                                "skipped, no record added.", file=spec["path"], role=role)
                continue
            seen[reading] = spec["path"]
            dialect = {**DEFAULT_DIALECT, **spec.get("dialect", {})}
            try:
                text = data.decode(dialect["encoding"])
            except UnicodeDecodeError as error:
                self.report.add("ENCODING_INVALID", "error", f"Not valid {dialect['encoding']}: byte {error.start}.",
                                file=spec["path"], role=role)
                continue
            rows = self._table(spec, text, dialect)
            if rows is not None:
                entry["rows"] = len(rows)
                self.rows[role].extend((spec, r) for r in rows)

    def _table(self, spec, text, dialect):
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=dialect["delimiter"],
                            quotechar=dialect["quote"], strict=True)
        try:
            header = next(reader)
        except StopIteration:
            self.report.add("HEADER_BLANK", "error", "The file is empty.", file=spec["path"], role=spec["role"])
            return None
        blank = [i + 1 for i, h in enumerate(header) if not h.strip()]
        duplicated = sorted(h for h, n in Counter(header).items() if n > 1 and h.strip())
        if blank:
            self.report.add("HEADER_BLANK", "error", f"Blank column names at positions {blank}.",
                            file=spec["path"], role=spec["role"], rows=["1"])
        if duplicated:
            self.report.add("HEADER_DUPLICATE", "error", f"Duplicate column names: {', '.join(duplicated)}.",
                            file=spec["path"], role=spec["role"], rows=["1"])
        if blank or duplicated:
            return None
        wanted = set(spec["columns"].values()) | set(spec.get("analytes", {})) | set(spec.get("codes", []))
        missing = sorted(wanted - set(header))
        if missing:
            self.report.add("COLUMN_MISSING", "error", f"Mapped columns not in the header: {', '.join(missing)}.",
                            file=spec["path"], role=spec["role"], rows=["1"])
            return None
        rows = []
        try:
            for line, fields in enumerate(reader, start=2):
                if not fields:
                    continue
                if len(fields) != len(header):
                    self.report.add("ROW_RAGGED", "error",
                                    f"Row {reader.line_num} has {len(fields)} fields; the header has {len(header)}. "
                                    "No value is shifted: the file is refused.",
                                    file=spec["path"], role=spec["role"], rows=[str(reader.line_num)])
                    return None
                rows.append({"_row": str(reader.line_num), **dict(zip(header, fields, strict=True))})
        except csv.Error as error:
            self.report.add("ROW_RAGGED", "error", f"Malformed quoting near line {reader.line_num}: {error}.",
                            file=spec["path"], role=spec["role"], rows=[str(reader.line_num)])
            return None
        return rows

    # ---- values ---------------------------------------------------------------------------------------------------
    def number(self, spec, row, field, *, required=True):
        column = spec["columns"].get(field)
        token = "" if column is None else row[column].strip()
        missing = {t.strip() for t in spec.get("missing", [""])}
        if token in missing or token == "":
            if required:
                self.report.add("NUMBER_INVALID", "error", f"Required value {column!r} is missing.",
                                file=spec["path"], role=spec["role"], rows=[row["_row"]],
                                hole=self._hole(spec, row))
            return None
        return self._parse(spec, row, column, token)

    def _parse(self, spec, row, column, token):
        decimal = spec.get("dialect", {}).get("decimal", ".")
        text = token
        if decimal == ",":
            if "." in text:
                self._bad(spec, row, column, token)
                return None
            text = text.replace(",", ".")
        try:
            value = float(text)
        except ValueError:
            self._bad(spec, row, column, token)
            return None
        if not math.isfinite(value):
            self._bad(spec, row, column, token)
            return None
        return value

    def _bad(self, spec, row, column, token):
        self.report.add("NUMBER_INVALID", "error", f"Column {column!r} holds {token!r}, which is not a number in "
                        "the declared dialect and not a declared state token.",
                        file=spec["path"], role=spec["role"], rows=[row["_row"]], hole=self._hole(spec, row))

    def _hole(self, spec, row):
        """The hole a row belongs to, so a value error can be resolved by excluding that hole."""
        column = spec["columns"].get("hole")
        return self.key(spec, row)[0] if column and row.get(column, "").strip() else None

    def length(self, spec, value):
        return None if value is None else (value * FOOT if spec.get("lengthUnit", "m") == "ft" else value)

    def elevation(self, spec, value):
        return None if value is None else (value * FOOT if spec.get("elevationUnit", "m") == "ft" else value)

    @staticmethod
    def dip(spec, value):
        convention = spec.get("angles", {}).get("dip", "negative-down")
        if value is None:
            return None
        if convention == "positive-down":
            return -value
        if convention == "inclination-from-vertical":
            return value - 90.0
        return value

    def key(self, spec, row):
        raw = row[spec["columns"]["hole"]].strip()
        namespace = spec.get("namespace", self.m.get("namespace", "src"))
        key = f"{namespace}:{raw}"
        return self.m.get("aliases", {}).get(key, key), raw, namespace

    # ---- building -------------------------------------------------------------------------------------------------
    def build(self):
        self.read()
        if self.report.errors("file"):
            return self._decide(None)
        self._units_and_angles_notes()
        collars = self._collars()
        if self.report.errors("file"):
            return self._decide(None)
        if not self.rows["collar"] and not any(f["role"] == "collar" for f in self.m["files"]):
            self.report.add("COLLARS_PENDING", "warning", "No collar file yet: records wait for their companions; "
                            "no geometry is created.")
            return self._decide(None, pending=True)
        p = self._project()
        excluded = set(self.m.get("exclude", []))
        for key in sorted(excluded):
            self.report.add("HOLE_EXCLUDED", "info", "Excluded by the manifest with all its records.", hole=key)
        holes = {k: v for k, v in collars.items() if k not in excluded}
        stations = self._surveys(holes, excluded)
        blocked = {f["hole"] for f in self.report.errors("hole")}
        for key in sorted(holes):
            if key in blocked:
                continue
            c = holes[key]
            p["collars"].append(c["record"])
        self._trajectories(p, holes, stations, blocked)
        accepted = {c["id"] for c in p["collars"]}
        self._assays(p, accepted, excluded | blocked)
        self._lithology(p, accepted, excluded | blocked)
        self._unique_geology_ids(p)
        self._collisions()
        return self._decide(p)

    def _units_and_angles_notes(self):
        for spec in self.m["files"]:
            if spec.get("lengthUnit") == "ft" or spec.get("elevationUnit") == "ft":
                self.report.add("UNIT_CONVERTED", "info", "Feet converted to metres by exactly 0.3048.",
                                file=spec["path"], role=spec["role"])
            if spec.get("angles", {}).get("dip", "negative-down") != "negative-down":
                self.report.add("ANGLES_MAPPED", "info",
                                f"Dip convention {spec['angles']['dip']} mapped to dip from horizontal, negative down.",
                                file=spec["path"], role=spec["role"])
        for alias, target in self.m.get("aliases", {}).items():
            self.report.add("ALIAS_APPLIED", "info", f"{alias} is recorded as {target}.", hole=target)

    def _collars(self):
        crs = {}
        versions = defaultdict(list)
        extents = defaultdict(list)
        for spec, row in self.rows["collar"]:
            self._tick()
            key, raw, namespace = self.key(spec, row)
            x, y = self.number(spec, row, "x"), self.number(spec, row, "y")
            z = self.elevation(spec, self.number(spec, row, "z"))
            if spec.get("axisOrder") == "north-east":
                x, y = y, x
            total = self.length(spec, self.number(spec, row, "totalDepth", required=False))
            az = self.number(spec, row, "azimuth", required=False)
            dip = self.dip(spec, self.number(spec, row, "dip", required=False))
            if None in (x, y, z):
                continue
            if dip is not None and not -90 <= dip <= 90:
                self._bad(spec, row, spec["columns"]["dip"], row[spec["columns"]["dip"]])
                continue
            crs[spec["path"]] = spec.get("crs", self.m["frame"].get("horizontalCrs"))
            extents[spec["path"]].append((x, y))
            versions[key].append({"spec": spec, "row": row, "raw": raw, "namespace": namespace,
                                  "values": (x, y, z, total, None if az is None else az % 360.0, dip)})
        if len({c for c in crs.values()}) > 1:
            listing = ", ".join(f"{f} ({c})" for f, c in sorted(crs.items()))
            self.report.add("CRS_MISMATCH", "error", f"Collar files declare different reference systems: {listing}.",
                            role="collar")
            return {}
        self._axes(extents)
        out = {}
        resolutions = self.m.get("resolutions", {}).get("collars", {})
        for key, group in versions.items():
            distinct = {v["values"] for v in group}
            if len(group) > 1 and len(distinct) == 1:
                self.report.add("RECORD_DUPLICATE", "warning", "Identical collar records collapsed to one.",
                                hole=key, rows=[f"{v['spec']['path']}:{v['row']['_row']}" for v in group])
            chosen = group[0]
            if len(distinct) > 1:
                listing = "; ".join(f"{v['spec']['path']} row {v['row']['_row']}: {v['values']}" for v in group)
                if key in resolutions and any(v["spec"]["path"] == resolutions[key] for v in group):
                    chosen = next(v for v in group if v["spec"]["path"] == resolutions[key])
                    self.report.add("COLLAR_CONFLICT_RESOLVED", "info",
                                    f"Versions {listing}; the manifest keeps {resolutions[key]}.", hole=key)
                else:
                    self.report.add("COLLAR_CONFLICT", "error",
                                    f"Different versions of one collar: {listing}. Dependent records: "
                                    f"{self._dependents(key)}. Resolve in the manifest or exclude the hole.",
                                    hole=key, rows=[f"{v['spec']['path']}:{v['row']['_row']}" for v in group])
            x, y, z, total, az, dip = chosen["values"]
            spec = chosen["spec"]
            reference = spec.get("angles", {}).get("azimuthReference", "unknown")
            out[key] = {"record": collar(key, chosen["namespace"], chosen["raw"], self.m["frame"]["id"], x, y, z,
                                         refs(spec["path"], chosen["row"]["_row"]), total_depth=total,
                                         orientation=None if az is None or dip is None
                                         else orientation(az, dip, reference)),
                        "spec": spec}
        return out

    def _axes(self, extents):
        boxes = {f: (min(p[0] for p in pts), max(p[0] for p in pts), min(p[1] for p in pts), max(p[1] for p in pts))
                 for f, pts in extents.items() if pts}

        def meets(a, b):
            pad = max(1000.0, 0.5 * max(a[1] - a[0], a[3] - a[2], b[1] - b[0], b[3] - b[2]))
            return a[0] - pad <= b[1] and b[0] - pad <= a[1] and a[2] - pad <= b[3] and b[2] - pad <= a[3]

        names = sorted(boxes)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                A, B = boxes[a], boxes[b]
                swapped = (B[2], B[3], B[0], B[1])
                if not meets(A, B) and meets(A, swapped):
                    self.report.add("AXES_SWAPPED_SUSPECTED", "error",
                                    f"{b} overlaps {a} only with its easting and northing swapped; declare axisOrder.",
                                    file=b, role="collar")

    def _dependents(self, key):
        counts = Counter()
        for role in ("survey", "assay", "lithology"):
            for spec, row in self.rows[role]:
                if self.key(spec, row)[0] == key:
                    counts[role] += 1
        return ", ".join(f"{n} {role}" for role, n in sorted(counts.items())) or "none"

    def _surveys(self, holes, excluded):
        by_hole = defaultdict(list)
        for spec, row in self.rows["survey"]:
            self._tick()
            key = self.key(spec, row)[0]
            if key in excluded:
                continue
            if key not in holes:
                self.report.add("ORPHAN_SURVEY", "warning", "Survey record on a hole with no collar; isolated.",
                                file=spec["path"], role="survey", rows=[row["_row"]], hole=key)
                continue
            md = self.length(spec, self.number(spec, row, "depth"))
            az = self.number(spec, row, "azimuth")
            dip = self.dip(spec, self.number(spec, row, "dip"))
            if None in (md, az, dip):
                continue
            if md < 0 or not -90 <= dip <= 90:
                self._bad(spec, row, spec["columns"]["depth"], f"{md} / {dip}")
                continue
            by_hole[key].append({"md": md, "azimuth": az % 360.0, "dip": dip, "spec": spec, "row": row})
        stations = {}
        for key, rows in by_hole.items():
            groups = defaultdict(list)
            for r in rows:
                groups[r["md"]].append(r)
            kept = []
            for md in sorted(groups):
                group = groups[md]
                angles = {(r["azimuth"], r["dip"]) for r in group}
                where = [f"{r['spec']['path']}:{r['row']['_row']}" for r in group]
                if len(angles) > 1:
                    self.report.add("SURVEY_DEPTH_CONFLICT", "error",
                                    f"Two survey records at {md} m with different angles {sorted(angles)}; the hole "
                                    "cannot be desurveyed until one is chosen or the hole is excluded.",
                                    hole=key, rows=where)
                elif len(group) > 1:
                    self.report.add("RECORD_DUPLICATE", "warning", f"Identical survey records at {md} m collapsed.",
                                    hole=key, rows=where)
                kept.append(group[0])
            stations[key] = kept
        return stations

    def _trajectories(self, p, holes, stations, blocked):
        assumption = self.m.get("assumptions", {})
        deepest = self._deepest(holes)
        for c in p["collars"]:
            key = c["id"]
            spec = holes[key]["spec"]
            reference = spec.get("angles", {}).get("azimuthReference", "unknown")
            rows = stations.get(key, [])
            o = c["orientation"]
            end = c["totalDepth"] if c["totalDepth"] is not None else deepest.get(key)
            if rows:
                start = "none"
                if o is not None and rows[0]["md"] > 0:
                    p["surveys"].append(survey(f"{key}#collar", key, 0.0, o["azimuth"], o["dip"],
                                               "recorded-collar-direction", c["sourceRefs"], reference=reference))
                elif rows[0]["md"] > 0:
                    if assumption.get("surveyStart") != "tangent":
                        self.report.add("SURVEY_START_UNDECLARED", "error",
                                        f"The first station is at {rows[0]['md']} m and no start extension is "
                                        "declared (assumptions.surveyStart).", hole=key)
                        blocked.add(key)
                        continue
                    start = "tangent"
                    self.report.add("SURVEY_START_EXTENDED", "warning",
                                    f"0 to {rows[0]['md']} m follow the first station's direction (declared).",
                                    hole=key)
                for i, r in enumerate(rows):
                    instrument = r["spec"].get("angles", {}).get("instrument")
                    ref = r["spec"].get("angles", {}).get("azimuthReference", "unknown")
                    p["surveys"].append(survey(f"{key}#s{i}", key, r["md"], r["azimuth"], r["dip"], "measured",
                                               refs(r["spec"]["path"], r["row"]["_row"]), reference=ref,
                                               instrument=instrument))
                if end is not None and end > rows[-1]["md"]:
                    self.report.add("SURVEY_TRUNCATED", "warning",
                                    f"Stations end at {rows[-1]['md']} m; {rows[-1]['md']} to {end} m follow the last "
                                    "station's direction.", hole=key)
                p["trajectories"].append(trajectory(key, "measured-stations", c["sourceRefs"], valid_to=end,
                                                    azimuth_assumption=reference, start=start))
            elif o is not None:
                p["surveys"].append(survey(f"{key}#collar", key, 0.0, o["azimuth"], o["dip"],
                                           "recorded-collar-direction", c["sourceRefs"], reference=reference))
                p["trajectories"].append(trajectory(key, "collar-orientation", c["sourceRefs"], valid_to=end,
                                                    azimuth_assumption=reference))
                self.report.add("SURVEY_ASSUMED", "warning",
                                f"No stations: the recorded collar direction is extended from 0 to {end} m.", hole=key)
            elif assumption.get("missingSurvey") == "vertical":
                p["trajectories"].append(trajectory(key, "assumed-vertical", c["sourceRefs"], valid_to=end))
                self.report.add("SURVEY_ASSUMED", "warning",
                                f"No stations and no collar direction: assumed vertical from 0 to {end} m "
                                "(declared).", hole=key)
            else:
                self.report.add("SURVEY_MISSING_UNASSUMED", "error",
                                "No stations, no recorded collar direction and no declared assumption "
                                "(assumptions.missingSurvey).", hole=key)
                blocked.add(key)
        p["collars"] = [c for c in p["collars"] if c["id"] not in blocked]
        p["surveys"] = [s for s in p["surveys"] if s["holeId"] not in blocked]
        p["trajectories"] = [t for t in p["trajectories"] if t["holeId"] not in blocked]

    def _deepest(self, holes):
        deepest = defaultdict(float)
        for role in ("assay", "lithology"):
            for spec, row in self.rows[role]:
                key = self.key(spec, row)[0]
                if key in holes:
                    to = self.length(spec, self.number(spec, row, "to", required=False))
                    if to is not None:
                        deepest[key] = max(deepest[key], to)
        return deepest

    def _state(self, spec, token):
        """(state, value, limit) for one assay cell, or None when the token is not declared and not a number."""
        text = token.strip()
        states = {k.strip(): v for k, v in spec.get("states", {}).items()}
        if text in states:
            return states[text], None, None
        if text == "" or text in {t.strip() for t in spec.get("missing", [])}:
            return "missing", None, None
        if text[:1] in "<>":
            limit = self._number_text(spec, text[1:])
            if limit is None or limit <= 0:
                return None
            return ("censored-below" if text[0] == "<" else "censored-above"), None, limit
        value = self._number_text(spec, text)
        return None if value is None else ("measured", value, None)

    @staticmethod
    def _number_text(spec, text):
        if spec.get("dialect", {}).get("decimal", ".") == ",":
            if "." in text:
                return None
            text = text.replace(",", ".")
        try:
            value = float(text)
        except ValueError:
            return None
        return value if math.isfinite(value) else None

    def _assays(self, p, accepted, dropped):
        analytes = {}
        supports = {}
        results = set()
        dids = set()
        series = defaultdict(list)
        controls = 0
        for spec, row in self.rows["assay"]:
            self._tick()
            mapping = spec.get("analytes", {})
            sample_column = spec["columns"].get("sample")
            sample = row[sample_column].strip() if sample_column else f"{Path(spec['path']).stem}-{row['_row']}"
            type_column = spec["columns"].get("sampleType")
            kind = row[type_column].strip() if type_column else ""
            lineage = refs(spec["path"], row["_row"])
            if kind in spec.get("controls", {}):
                controls += 1
                qid = f"qc-{sample}"
                while qid in dids:
                    qid += "+"
                dids.add(qid)
                dets = []
                for column, m in mapping.items():
                    parsed = self._state(spec, row[column])
                    if parsed is None:
                        self._bad(spec, row, column, row[column])
                        continue
                    state, value, limit = parsed
                    dets.append(determination(f"{qid}:{column}", None, m["analyte"], value, row[column],
                                              m["unit"], lineage, state=state, limit=limit, method=m.get("method"),
                                              lab=m.get("lab")))
                p["qc"].append({"id": qid, "sampleId": sample,
                                "controlType": spec["controls"][kind], "determinations": dets, "sourceRefs": lineage})
                continue
            key = self.key(spec, row)[0]
            if key in dropped:
                continue
            if key not in accepted:
                self.report.add("ORPHAN_ASSAY", "warning", "Assay record on a hole with no collar; isolated.",
                                file=spec["path"], role="assay", rows=[row["_row"]], hole=key)
                continue
            a = self.length(spec, self.number(spec, row, "from"))
            b = self.length(spec, self.number(spec, row, "to"))
            if a is None or b is None:
                continue
            if a < 0 or b <= a:
                self.report.add("INTERVAL_INVALID", "warning",
                                f"Interval {a} to {b} m is reversed, zero-length or negative; this record is excluded.",
                                file=spec["path"], role="assay", rows=[row["_row"]], hole=key)
                continue
            sid = f"{key}/{sample}"
            where = f"{spec['path']}:{row['_row']}"
            if sid in supports and supports[sid][1] != (a, b):
                self.report.add("SAMPLE_CONFLICT", "error",
                                f"Sample {sample} is {supports[sid][1][0]} to {supports[sid][1][1]} m in "
                                f"{supports[sid][2]} and {a} to {b} m here.", hole=key, rows=[where, supports[sid][2]])
                continue
            if sid not in supports:
                supports[sid] = (key, (a, b), where)
                p["supports"].append(support(sid, key, a, b, lineage, None, sample=sample))
            role = spec.get("repeats", {}).get(kind, "original")
            for column, m in mapping.items():
                parsed = self._state(spec, row[column])
                if parsed is None:
                    self._bad(spec, row, column, row[column])
                    continue
                state, value, limit = parsed
                signature = (sid, m["analyte"], m.get("method"), m.get("lab"), row[column].strip(), role)
                if signature in results:
                    self.report.add("RECORD_DUPLICATE", "warning", f"Identical {m['analyte']} result for sample "
                                    f"{sample} collapsed; no doubled measurement.", hole=key, rows=[where])
                    continue
                results.add(signature)
                did = f"{sid}:{column}"
                n = 2
                while did in dids:
                    did, n = f"{sid}:{column}#{n}", n + 1
                dids.add(did)
                p["determinations"].append(determination(did, sid, m["analyte"], value, row[column], m["unit"],
                                                         lineage, state=state, limit=limit, method=m.get("method"),
                                                         lab=m.get("lab"), sample_role=role))
                analytes.setdefault(m["analyte"], (m["unit"], spec["path"], column))
                series[(key, m["analyte"], m.get("method"))].append((a, b, did, sid))
        for analyte, (unit, path, column) in analytes.items():
            p["analytes"].append({"id": analyte, "name": localized(analyte), "unit": unit,
                                  "quantity": "reported mass fraction", "sourceRefs": refs(path, "header:" + column)})
        for (key, analyte, method), items in series.items():
            items.sort()
            for i, (a, b, did, sid) in enumerate(items):
                for a2, b2, did2, sid2 in items[i + 1:]:
                    if a2 >= b:
                        break
                    if (a2, b2) == (a, b):
                        continue  # the same interval sampled twice is a repeat, not an overlap
                    self.report.add("ASSAY_OVERLAP", "warning",
                                    f"{analyte} ({method}) intervals {a}-{b} and {a2}-{b2} m overlap in one series; "
                                    "both are excluded from modeling, never summed or averaged.",
                                    hole=key, rows=[sid, sid2])
                    for d in (did, did2):
                        if not any(x["rowId"] == d for x in p["exclusions"]):
                            p["exclusions"].append({"table": "determinations", "rowId": d, "reason": "ASSAY_OVERLAP"})

    def _lithology(self, p, accepted, dropped):
        for spec, row in self.rows["lithology"]:
            self._tick()
            key = self.key(spec, row)[0]
            if key in dropped:
                continue
            if key not in accepted:
                self.report.add("ORPHAN_LITHOLOGY", "warning", "Lithology record on a hole with no collar; isolated.",
                                file=spec["path"], role="lithology", rows=[row["_row"]], hole=key)
                continue
            a = self.length(spec, self.number(spec, row, "from"))
            b = self.length(spec, self.number(spec, row, "to"))
            if a is None or b is None:
                continue
            if a < 0 or b < a:
                self.report.add("INTERVAL_INVALID", "warning", f"Lithology {a} to {b} m is reversed or negative; "
                                "this record is excluded.", file=spec["path"], role="lithology",
                                rows=[row["_row"]], hole=key)
                continue
            description = spec["columns"].get("description")
            event = a == b
            p["geology"].append({"id": f"{key}/L{a:g}-{b:g}", "holeId": key,
                                 "kind": "event" if event else "interval",
                                 "fromMd": None if event else a, "toMd": None if event else b,
                                 "atMd": a if event else None,
                                 "codes": {c: (row[c] if row[c].strip() else None) for c in spec.get("codes", [])},
                                 "description": (row[description] if description and row[description].strip()
                                                 else None),
                                 "mappedCode": None, "mappingVersion": None,
                                 "sourceRefs": refs(spec["path"], row["_row"])})

    @staticmethod
    def _unique_geology_ids(p):
        """Identifiers from the hole and depths, so file and row order never change them; repeats get a suffix."""
        seen = Counter()
        p["geology"].sort(key=lambda g: (g["id"], json.dumps(g["codes"], sort_keys=True), g["description"] or ""))
        for g in p["geology"]:
            seen[g["id"]] += 1
            if seen[g["id"]] > 1:
                g["id"] = f"{g['id']}#{seen[g['id']]}"

    def _collisions(self):
        keys = set()
        for role in ("collar", "survey", "assay", "lithology"):
            for spec, row in self.rows[role]:
                key, raw, namespace = self.key(spec, row)
                if not (role == "assay" and row.get(spec["columns"].get("sampleType", ""), "").strip()
                        in spec.get("controls", {})):
                    keys.add(key)
        groups = defaultdict(set)
        for key in keys:
            namespace, raw = key.split(":", 1)
            groups[(namespace, normalized(raw))].add(key)
        for (namespace, form), members in sorted(groups.items()):
            if len(members) > 1:
                self.report.add("ID_NORMALIZATION_COLLISION", "warning",
                                f"{', '.join(sorted(members))} differ only in case, punctuation or leading zeros; "
                                "they stay distinct unless an alias merges them.", hole=min(members))

    # ---- project and decision -------------------------------------------------------------------------------------
    def _project(self):
        f = self.m["frame"]
        sources = [source(e["path"], None, None, None, e["sha256"], "csv",
                          next(s for s in self.m["files"] if s["path"] == e["path"]).get("dialect", {})
                          .get("encoding", "utf-8"))
                   for e in self.files if e["duplicateOf"] is None]
        recipe = f"import-v1: manifest sha256 {stable_hash(self.m)}"
        return project(self.m["project"]["id"], localized(self.m["project"]["name"]), sources, recipe,
                       frame(f["id"], f["kind"], horizontal_crs=f.get("horizontalCrs"),
                             vertical_datum=f.get("verticalDatum"),
                             assumptions=["Frame and units as declared in the import manifest."]),
                       kind="user-import")

    def _decide(self, p, pending=False):
        blocked = sorted({f["hole"] for f in self.report.errors("hole")})
        if self.report.errors("file") or blocked:
            status = "rejected"
        elif pending:
            status = "pending"
        else:
            status = "accepted"
        if status == "accepted":
            self._finish(p)
        counts = {"bySeverity": Counter(f["severity"] for f in self.report.findings),
                  "byCode": Counter(f["code"] for f in self.report.findings),
                  "byFile": Counter(f["file"] for f in self.report.findings if f["file"]),
                  "byRole": Counter(f["role"] for f in self.report.findings if f["role"]),
                  "byHole": Counter(f["hole"] for f in self.report.findings if f["hole"])}
        report = {"schema": REPORT_SCHEMA, "project": self.m["project"]["id"], "status": status,
                  "manifestSha256": stable_hash(self.m), "files": self.files, "findings": self.report.findings,
                  "counts": {k: dict(sorted(v.items())) for k, v in counts.items()},
                  "holes": {"accepted": sorted(c["id"] for c in p["collars"]) if p and status == "accepted" else [],
                            "blocked": blocked, "excluded": sorted(self.m.get("exclude", []))}}
        return status, (p if status == "accepted" else None), report

    def _finish(self, p):
        for f in self.report.findings:
            if f["severity"] in ("warning", "info"):
                p["issues"].append({"id": f"qa-{len(p['issues']) + 1}", "severity": f["severity"], "code": f["code"],
                                    "table": f["role"] or "import", "rowIds": f["rows"] or [f["hole"] or f["file"]
                                                                                          or "import"],
                                    "holeId": f["hole"], "message": f["message"], "action": "reported by the import"})
        p["waterfall"] = [
            {"step": "files", "count": len(self.files)},
            {"step": "rows read", "count": sum(len(v) for v in self.rows.values())},
            {"step": "holes accepted", "count": len(p["collars"])},
            {"step": "samples", "count": len(p["supports"])},
            {"step": "determinations", "count": len(p["determinations"])},
            {"step": "controls", "count": len(p["qc"])},
            {"step": "excluded from modeling", "count": len(p["exclusions"])},
        ]
        order = {"collars": "id", "surveys": "id", "supports": "id", "determinations": "id", "geology": "id"}
        for table, field in order.items():
            p[table].sort(key=lambda r, f=field: r[f])
        p["trajectories"].sort(key=lambda t: t["holeId"])
        p["analytes"].sort(key=lambda a: a["id"])


def run_import(manifest_path: Path, out: Path, cancel=None) -> dict:
    """Validate, import and, when accepted, commit atomically to ``out/<project id>/``. Returns the report."""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = validate_manifest(manifest)
    if problems:
        raise ManifestInvalid("; ".join(problems[:10]))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    identifier = manifest["project"]["id"]
    staging = out / f".staging-{identifier}-{uuid.uuid4().hex[:8]}"
    try:
        status, p, report = Importer(manifest, manifest_path.parent, cancel).build()
        write_json(out / f"{identifier}.import-report.json", report, pretty=True)
        if status != "accepted":
            return report
        staging.mkdir()
        write_json(staging / "project.json", p)
        write_json(staging / "import.json", manifest, pretty=True)
        counts = {k: len(p[k]) for k in ("collars", "surveys", "trajectories", "analytes", "supports",
                                         "determinations", "geology", "qc", "exclusions", "issues")}
        write_json(staging / "summary.json", {
            "schema": "drillhole.ingest-summary/v1", "family": identifier, "projectSha256": stable_hash(p),
            "recipe": p["provenance"]["recipe"], "recipeSha256": p["provenance"]["recipeSha256"], "counts": counts,
            "waterfall": p["waterfall"], "issues": [{"code": i["code"], "severity": i["severity"],
                                                     "rows": len(i["rowIds"])} for i in p["issues"]],
            "seconds": 0.0}, pretty=True)
        if cancel and cancel():
            raise ImportCancelled("import cancelled before commit")
        target = out / identifier
        previous = out / f".previous-{identifier}-{uuid.uuid4().hex[:8]}"
        if target.exists():
            target.rename(previous)
        staging.rename(target)
        if previous.exists():
            shutil.rmtree(previous)
        return report
    finally:
        if staging.exists():
            shutil.rmtree(staging)
