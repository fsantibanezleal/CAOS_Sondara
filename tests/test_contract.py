"""The canonical project contract, drillhole.project/v2: one schema, written by every adapter, with consistent states."""

import importlib.util
import json
import os
import zipfile
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("SONDARA_RAW", ROOT / "build" / "sources"))


def _contract():
    spec = importlib.util.spec_from_file_location("check_artifacts", ROOT / "scripts" / "check_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _families():
    """The families whose sources are present: NTGS always (bundled), Rocklea and Alberta with the raw cache."""
    from source_adapters import alberta, ntgs, rocklea

    out = {"ntgs": ntgs.normalize()}
    if all((RAW / f).is_file() for f in rocklea.FILES):
        out["rocklea"] = rocklea.normalize(RAW)
    if (RAW / alberta.ARCHIVE).is_file():
        out["alberta"] = alberta.normalize(RAW)
    return out


def test_every_family_validates_against_the_schema():
    import jsonschema

    schema = json.loads((ROOT / "schemas" / "project.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    families = _families()
    for name, project in families.items():
        assert project["schema"] == "drillhole.project/v2"
        assert not list(validator.iter_errors(project)), name
        assert _contract().check_project(project) == [], name
    broken = dict(families["ntgs"], waterfall=None)
    assert list(validator.iter_errors(broken))  # the schema is strict, not decorative


def test_states_and_qualifiers_are_consistent():
    from source_adapters.common import STATES, determination

    project = _families()["ntgs"]
    pairs = Counter((d["state"], d["qualifier"], d["value"] is None) for d in project["determinations"])
    assert pairs == {("measured", "=", False): 1042, ("censored-below", "<", True): 850}
    for state in STATES:
        d = determination("d", "s", "Cu", 1.5, "raw", "ppm", [], state=state, limit=0.5)
        assert (d["value"] is not None) == (state == "measured")
        assert d["qualifier"] == {"measured": "=", "censored-below": "<", "censored-above": ">"}.get(state)
    with pytest.raises(ValueError):
        determination("d", "s", "Cu", 1.0, "raw", "ppm", [], state="guessed")
    contract = _contract()
    measured = next(i for i, d in enumerate(project["determinations"]) if d["state"] == "measured")
    for change in ({"value": None}, {"qualifier": None}, {"state": "not-sampled"}):
        broken = json.loads(json.dumps(project))
        broken["determinations"][measured].update(change)
        assert contract.check_project(broken), change


def test_only_measured_rows_and_collar_directions_are_stations():
    from stages.preprocess import build_surveys

    project = _families()["ntgs"]
    roles = Counter((s["role"], s["instrument"]) for s in project["surveys"])
    assert roles == {("recorded-collar-direction", None): 1,
                     ("measured", "Reflex EZ-Shot electronic single-shot"): 11,
                     ("compiled-extension", None): 1}
    assert {s["azimuthReference"] for s in project["surveys"]} == {"true"}
    survey = build_surveys(project)["8440823"]
    assert list(survey.measured_depth) == sorted(s["md"] for s in project["surveys"]
                                                 if s["role"] != "compiled-extension")
    assert survey.measured_depth[-1] == 360.0  # the compiled record at total depth is not a station


def test_geology_keeps_source_codes_verbatim():
    from source_adapters import alberta

    if not (RAW / alberta.ARCHIVE).is_file():
        pytest.skip(f"raw sources not in {RAW}")
    project = alberta.normalize(RAW)
    with zipfile.ZipFile(RAW / alberta.ARCHIVE) as archive:
        text = archive.read(alberta.MEMBERS["intervals"]).decode("cp1252")
    import csv
    import io

    raw = {f"ab-geo-{r['AGS_ID']}": r for r in csv.DictReader(io.StringIO(text, newline=""), delimiter="\t")
           if r["Data_src"] == alberta.REPORT}
    assert len(raw) == len(project["geology"]) == 150
    for g in project["geology"]:
        source = raw[g["id"]]
        for column in ("Rock_type", "Litho_unit", "Material"):
            expected = source[column] if source[column].strip() else None
            assert g["codes"][column] == expected, (g["id"], column)
        assert g["description"] == (source["Intrvl_dsc"] if source["Intrvl_dsc"].strip() else None)
    rock_types = Counter(g["codes"]["Rock_type"] for g in project["geology"]
                         if g["kind"] == "interval" and g["codes"]["Rock_type"] not in (None, "-9999"))
    assert sum(rock_types.values()) == 78 and len(rock_types) == 6  # the dossier's six source values on 78 intervals
