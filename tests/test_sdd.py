"""The SDD guard's planned status: a feature designed before its code is checked for form, and counted apart."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_sdd", ROOT / "scripts" / "check_sdd.py")
check_sdd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_sdd)

LIVE_SDD = """# SDD

```
R-001  THE repository SHALL exist.
       Gate: tests/test_present.py::test_present
```
"""


def _repo(tmp_path, feature_text):
    (tmp_path / "docs" / "design" / "features" / "f").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_present.py").write_text("def test_present():\n    pass\n", encoding="utf-8")
    (tmp_path / "docs" / "design" / "SDD.md").write_text(LIVE_SDD, encoding="utf-8")
    (tmp_path / "docs" / "design" / "features" / "f" / "requirements.md").write_text(feature_text, encoding="utf-8")
    return tmp_path


def _feature(status, body):
    return f"# Feature\n\n{status}\n\n```\n{body}\n```\n"


def test_planned_requirements_are_counted_apart(tmp_path, capsys):
    body = "R-700  THE lane SHALL predict.\n       Gate: tests/test_future.py::test_not_written_yet"
    root = _repo(tmp_path, _feature("Status: planned", body))
    assert check_sdd.main(["check_sdd", str(root)]) == 0
    out = capsys.readouterr().out
    assert "planned, gates not yet checked (1)" in out and "R-700 -> tests/test_future.py" in out
    assert "1 planned" in out

    # The same requirement without the status line is a live one, and its missing gate fails.
    root = _repo(tmp_path / "live", _feature("", body))
    assert check_sdd.main(["check_sdd", str(root)]) == 1
    assert "test_future.py" in capsys.readouterr().out


def test_a_planned_requirement_still_needs_form_and_a_file_gate(tmp_path, capsys):
    cases = {
        "no-shall": "R-701  THE lane predicts.\n       Gate: tests/test_future.py::test_x",
        "no-gate": "R-702  THE lane SHALL predict.",
        "manual": "R-703  THE lane SHALL predict.\n       Gate: manual:look-at-it",
        "not-a-file": "R-704  THE lane SHALL predict.\n       Gate: somebody",
    }
    for name, body in cases.items():
        root = _repo(tmp_path / name, _feature("Status: planned", body))
        assert check_sdd.main(["check_sdd", str(root)]) == 1, name
        capsys.readouterr()


def test_the_design_document_cannot_be_planned(tmp_path, capsys):
    root = _repo(tmp_path, _feature("", "R-705  THE lane SHALL exist.\n       Gate: tests/test_present.py::test_present"))
    (root / "docs" / "design" / "SDD.md").write_text("Status: planned\n\n" + LIVE_SDD, encoding="utf-8")
    assert check_sdd.main(["check_sdd", str(root)]) == 1
    assert "cannot be planned" in capsys.readouterr().out
