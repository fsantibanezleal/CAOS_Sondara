"""The Rocklea hyperspectral export as a source table, with the files that document its lineage (unit SD-7b).

The TSG export (``RC_data_tsgexport.CSV``) carries eight spectral scalars computed by fixed scripts and eleven
assay-like columns; the product descriptions workbook, the TSG project file, the PLS model file and the exercise
answers of the same CSIRO collection say what those columns are. This adapter reads them as they are: values are
never repaired, a masked or missing scalar stays null, and every row keeps its source reference. What the columns are
is decided later (``stages/spectral.py``, with ``data/interpretations/rocklea-spectral-products-v1.json``).
Design: docs/design/features/geochemical-review/design.md, sections 1 and 2.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import openpyxl
from source_io import digest, number, read_table

COLLECTION = "https://data.csiro.au/dap/ws/v2/collections/44783/data/"
FILES = {
    "RC_data_tsgexport.CSV": ("56857422", "3db06836038139058388de9e0e6897b51a04f663c25286865e14034f868d8cff"),
    "GeoscienceProductDescriptions_ProximalHyperspectral.xlsx":
        ("56857411", "4c0fec13df07b38cf9441a7eb544fe7ebcbfd677aae766a504e0ee078aff0283"),
    "RC_data.ini": ("56857403", "ec180d15d085d474b9c83df340e9aa0112dbd2e89958ebc80d9829a514b69918"),
    "RC_data8_Fe.pls": ("56857421", "86cfeb6eea9875847408e58a2393dd6de3dc8c132394b6beed1596b9e585317d"),
    "Answers_CIDexercises.docx": ("56857431", "5f300e18975c457280d0454aea96d9d68d1a0628422fb9e6c99eae4389d610f9"),
}
SPECTRAL = ("Fe ox ai", "hem/goe", "kaolin abundance", "kaolin composition", "wmAlsmai", "wmAlsmci", "carbai3pfit",
            "carbci3pfit")
EMBEDDED = ("Fe %", "Al2O3", "SiO2 %", "K2O %", "CaO %", "MgO %", "TiO2 %", "P %", "S %", "Mn %", "LOI")
PARAMETER = re.compile(r"^Param_id_(\d+)=(\d+);([^;]*);([^;]*)$")


def _source(filename: str) -> dict:
    source_id, sha = FILES[filename]
    return {"id": source_id, "file": filename, "url": COLLECTION + source_id, "sha256": sha, "license": "CC-BY-4.0",
            "attribution": "CSIRO, Rocklea Dome 3D Mineral Mapping Test Data Set"}


def _rows(path: Path) -> list[dict]:
    out = []
    for r in read_table(path):
        hole = (r["Borehole ID"] or "").strip().upper()
        out.append({"row": r["_row"], "sample": r["Sample"], "hole": None if hole in ("", "NULL") else hole,
                    "depthFrom": number(r["Depth from"], nullable=True),
                    "spectral": {c: number(r[c], nullable=True) for c in SPECTRAL},
                    "embedded": {c: number(r[c], nullable=True) for c in EMBEDDED}})
    return out


def _descriptions(path: Path) -> dict:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    rows = []
    for index, row in enumerate(sheet.iter_rows(values_only=True), 1):
        cells = ["" if v is None else str(v).strip() for v in row]
        if any(cells):
            rows.append({"row": index, "cells": cells})
    workbook.close()
    header = next(r for r in rows if r["cells"] and r["cells"][0] == "Product name")
    names = header["cells"]
    products = []
    for r in rows:
        if r["row"] <= header["row"] or not r["cells"][0] or len([c for c in r["cells"] if c]) < 4:
            continue
        products.append({"row": r["row"], **{names[i]: r["cells"][i] for i in range(min(len(names), len(r["cells"])))
                                             if names[i]}})
    return {"sheet": sheet.title, "title": rows[0]["cells"][0], "header": [n for n in names if n],
            "products": products}


def _project(path: Path) -> dict:
    text = path.read_bytes().decode("latin-1").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    parameters = []
    for line in lines:
        match = PARAMETER.match(line.strip())
        if match:
            parameters.append({"parameter": int(match.group(1)), "index": int(match.group(2)),
                               "name": match.group(3), "guid": match.group(4)})
    header = {k: v for k, v in (line.split("=", 1) for line in lines[:12] if "=" in line)
              if k in ("layers", "samples", "channels", "params", "sets")}
    return {"version": lines[0].strip(), "header": header, "parameters": parameters,
            "sets": [line.split("=", 1)[1] for line in lines if line.startswith("Set_")]}


def _answers(path: Path) -> list[dict]:
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    paragraphs = [re.sub(r"<[^>]+>", "", p) for p in xml.split("</w:p>")]
    return [{"paragraph": i, "text": p.strip()} for i, p in enumerate(paragraphs)
            if "RMSE" in p or p.strip().startswith("Validation of")]


def normalize(cache: Path) -> dict:
    cache = Path(cache)
    for filename, (_, expected) in FILES.items():
        if digest(cache / filename) != expected:
            raise ValueError("Rocklea spectral source hash mismatch: " + filename)
    pls = cache / "RC_data8_Fe.pls"
    return {"schema": "drillhole.spectral-source/v1", "family": "rocklea",
            "sources": [_source(f) for f in FILES],
            "columns": {"spectral": list(SPECTRAL), "embedded": list(EMBEDDED)},
            "rows": _rows(cache / "RC_data_tsgexport.CSV"),
            "descriptions": _descriptions(cache / "GeoscienceProductDescriptions_ProximalHyperspectral.xlsx"),
            "project": _project(cache / "RC_data.ini"),
            "pls": {"file": pls.name, "bytes": pls.stat().st_size, "sha256": digest(pls),
                    "use": "recorded, not used: its training samples are not documented"},
            "answers": _answers(cache / "Answers_CIDexercises.docx")}
