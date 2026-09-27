"""The fixture and scenario registries: every entry enumerated, and every fixture of a built stage verified."""

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / "data" / "fixtures" / "registry.json").read_text(encoding="utf-8"))
SCENARIOS = json.loads((ROOT / "data" / "scenarios" / "registry.json").read_text(encoding="utf-8"))
PIPELINE_STAGES = ("acquire", "ingest", "import", "preprocess", "dataset", "features", "train", "infer", "evaluate",
                   "export", "validate")


def _built_stages():
    """The stages the runner actually offers: its stage choices, plus import when ingest takes a manifest."""
    source = (ROOT / "data-pipeline" / "run.py").read_text(encoding="utf-8")
    choices = re.search(r'add_argument\("stage", choices=\[([^\]]*)\]', source).group(1)
    stages = {s.strip().strip('"') for s in choices.split(",")}
    if '"--manifest"' in source:
        stages.add("import")
    return stages


def _gate_exists(gate):
    spec = importlib.util.spec_from_file_location("check_sdd", ROOT / "scripts" / "check_sdd.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.gate_exists(ROOT, gate)


def test_every_fixture_is_enumerated():
    ids = [f["id"] for f in FIXTURES["fixtures"]]
    assert ids == [f"F{n:02d}" for n in range(1, 43)]
    for f in FIXTURES["fixtures"]:
        assert f["construction"] and f["expected"] and f["stage"] in PIPELINE_STAGES, f["id"]
        assert (f["files"] is None) != (f["parameters"] is None), f["id"]  # authored files or parameters
        if f["files"]:
            folder = ROOT / f["files"]
            assert folder.is_dir() and any(folder.rglob("*.json")), f["id"]


def test_fixtures_of_built_stages_are_verified():
    built = _built_stages()
    assert set(FIXTURES["builtStages"]) == built
    for f in FIXTURES["fixtures"]:
        if f["stage"] in built:
            assert f["verification"], f"{f['id']}: its stage {f['stage']} is built, so it must be verified"
            ok, why = _gate_exists(f["verification"])
            assert ok, f"{f['id']}: {why}"
        else:
            assert f["verification"] is None, f"{f['id']}: names a verification for a stage not built yet"


def test_every_scenario_is_enumerated():
    ids = [s["id"] for s in SCENARIOS["scenarios"]]
    expected = ([f"R{n:02d}" for n in range(1, 13)] + [f"A{n:02d}" for n in range(1, 9)]
                + [f"S{n:02d}" for n in range(1, 13)])
    assert ids == expected
    fixture_ids = {f["id"] for f in FIXTURES["fixtures"]}
    for s in SCENARIOS["scenarios"]:
        assert s["family"] in ("rocklea", "alberta", "authored") and s["title"] and s["question"], s["id"]
        assert s["stages"] and set(s["stages"]) <= set(PIPELINE_STAGES), s["id"]
        assert set(s.get("fixtures", [])) <= fixture_ids, s["id"]
        if s["family"] == "authored":
            assert "fixtures" in s, s["id"]
