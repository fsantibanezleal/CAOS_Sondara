#!/usr/bin/env python3
"""Fail an INSTANTIATED product repo that still ships template residue (ADR-0057 / ADR-0061).

The archetype template ships an intentional example PIPELINE (not a package, not a lab) (`data-pipeline/pipeline/`, an SIR model,
`EX0*` baked cases) so a fresh clone runs end to end. Instantiation is supposed to REPLACE all of
it with the real product; five shipped products proved that replacement is easy to forget, leaving
SIR/Pyodide/EX0* text presented as product docs. This guard makes that structurally impossible.

It is a no-op in the template itself: the template root carries a `.template-source` sentinel, and
instantiation deletes it (see the README "Instantiate" steps). With the sentinel present the guard
prints a note and exits 0; once it is gone (a real product) the guard enforces a clean repo.

Scanned set = git-tracked files only (never venvs / node_modules / data caches). Exit 1 on any hit.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SENTINEL = ROOT / ".template-source"

# This script and its allowlist name the markers by definition; never scan them for content.
SELF = {"scripts/check_template_residue.py", "scripts/.template_residue_allow"}

# Tracked PATHS that must not exist in an instantiated product (the example pipeline + its cases +
# known scaffold residue). Matched as substring on the path or a suffix for extensions.
FORBIDDEN_PATH_SUBSTR = (
    "data-pipeline/pipeline/",
    "data/derived/EX01_subcritical",
    "data/derived/EX02_epidemic",
    "data/derived/EX03_fast_burn",
    "data/derived/EX04_slow_spread",
    "data/derived/manifests/EX0",
    "data/derived/manifests/CTRL_degenerate",
)
FORBIDDEN_PATH_SUFFIX = (
    ".ts.txt",  # architecture.ts.txt scaffold residue
)
FORBIDDEN_PATH_NAME = (
    "INSTANTIATE.md",
    "instantiate.md",
)

# Tracked TEXT content that must not survive instantiation (unambiguous template tokens only;
# generic capability words like "Pyodide" are intentionally NOT listed, a product may truly use it).
FORBIDDEN_CONTENT = (
    "SIRChart",
    "CAOS product template",
    "PENDING-training",
    "EX01_subcritical",
    "EX02_epidemic",
)

TEXT_SUFFIXES = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".md", ".json",
    ".css", ".html", ".yml", ".yaml", ".toml", ".txt", ".cfg", ".ini",
}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def load_allowlist() -> list[str]:
    f = ROOT / "scripts" / ".template_residue_allow"
    if not f.exists():
        return []
    return [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]


def allowed(path: str, patterns: list[str]) -> bool:
    return any(pat in path for pat in patterns)


def main() -> int:
    if SENTINEL.exists():
        print("check_template_residue: .template-source present: this is the template repo, "
              "residue check skipped (the example pipeline is intentional here).")
        return 0

    allow = load_allowlist()
    files = tracked_files()
    path_hits: list[str] = []
    content_hits: list[tuple[str, str]] = []

    for rel in files:
        if rel in SELF or allowed(rel, allow):
            continue
        low = rel.lower()
        if (any(s in rel for s in FORBIDDEN_PATH_SUBSTR)
                or any(low.endswith(sfx) for sfx in FORBIDDEN_PATH_SUFFIX)
                or Path(rel).name in FORBIDDEN_PATH_NAME):
            path_hits.append(rel)
            continue  # a forbidden path need not also be content-scanned

        if Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for token in FORBIDDEN_CONTENT:
            if token in text:
                content_hits.append((rel, token))

    if not path_hits and not content_hits:
        print(f"check_template_residue: OK: no template residue in {len(files)} tracked files.")
        return 0

    print("::error::template residue found: instantiation left the example pipeline / placeholder text in place.")
    for p in sorted(path_hits):
        print(f"  forbidden file: {p}")
    for rel, token in sorted(content_hits):
        print(f"  forbidden text: {rel}  (contains '{token}')")
    print("\nReplace the example pipeline (data-pipeline/pipeline -> your product's lab), rebake the real")
    print("cases, and purge the placeholder text. If a hit is a false positive, add a path fragment to")
    print("scripts/.template_residue_allow. This guard is skipped only in the template (.template-source).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
