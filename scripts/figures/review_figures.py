#!/usr/bin/env python3
"""Write the R12 figure of the docs as a light and dark SVG pair from the real Rocklea outputs.

    python scripts/figures/review_figures.py [--derived build/derived]

Reads ``rocklea/spectral-models.json``, ``rocklea/spectral-metrics.json`` and ``rocklea/geochemistry-metrics.json``
(run the pipeline through ``evaluate`` with the learned lane first) and writes
``docs/assets/review-rocklea-{light,dark}.svg``: left, the iron-oxide index against Fe for the test holes' confirmed
rows with the calibration fitted on the training holes; right, the share of each constructed alteration the
autoencoder and PCA flag at their review thresholds, beside the share of unchanged records they flag.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data-pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate_figures import PALETTES, svg

ASSETS = ROOT / "docs" / "assets"
KIND_LABELS = {"times-ten": "one property x 10", "unit-omission": "percent read as ppm",
               "cross-hole-pair": "Fe and SiO2 from another hole", "transformed-additive-0.25": "shift 0.25",
               "transformed-additive-1": "shift 1", "transformed-additive-3": "shift 3"}


def _truths(folder: Path, ids: set[str]) -> dict:
    project = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    return {d["supportId"]: d["value"] for d in project["determinations"]
            if d["supportId"] in ids and d["analyteId"] == "Fe" and d["state"] == "measured"}


def figure(models, metrics, review, truths, p):
    width, height = 820, 450
    x0, y0, w, h = 70, 92, 300, 280
    xs = [t["index"] for t in models["test"]] + models["fit"]["x"]
    xmax = max(xs) * 1.05
    ymax = 70.0
    X = lambda v: x0 + w * v / xmax
    Y = lambda v: y0 + h * (1 - v / ymax)
    parts = [('  <text class="t" x="24" y="30">Rocklea R12: what the iron-oxide index predicts, and what the '
              'autoencoder review notices</text>'),
             (f'  <text class="m" x="24" y="50">Left: test rows of confirmed holes, and the monotone fit on the '
              f'training holes; RMSE {metrics["index"]["rmse"]:.2f} wt% Fe against OK {metrics["ordinaryKriging"]["rmse"]:.2f} '
              f'on the same {metrics["rows"]} rows.</text>'),
             ('  <text class="m" x="24" y="66">Right: the share of each constructed alteration flagged at the review '
              'threshold, and of the unchanged records.</text>')]
    parts.append(f'  <rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="none" stroke="{p["grid"]}"/>')
    for t in models["test"]:
        if t["id"] in truths:
            parts.append(f'  <circle cx="{X(t["index"]):.1f}" cy="{Y(truths[t["id"]]):.1f}" r="1.6" '
                         f'fill="{p["series"][0]}" fill-opacity="0.45"/>')
    points = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(models["fit"]["x"], models["fit"]["y"], strict=True))
    parts.append(f'  <polyline points="{points}" fill="none" stroke="{p["series"][1]}" stroke-width="2"/>')
    for v in (0, 20, 40, 60):
        parts.append(f'  <text class="m" x="{x0 - 8}" y="{Y(v) + 4:.1f}" text-anchor="end">{v}</text>')
    for v in (0.0, 0.1, 0.2, 0.3):
        if v <= xmax:
            parts.append(f'  <text class="m" x="{X(v):.1f}" y="{y0 + h + 16}" text-anchor="middle">{v:.1f}</text>')
    parts.append(f'  <text class="m" x="{x0 + w / 2}" y="{y0 + h + 34}" text-anchor="middle">Fe ox ai (relative '
                 f'depth of the 900 nm absorption)</text>')
    parts.append(f'  <text class="m" x="{x0}" y="{y0 - 8}">Fe, wt%</text>')
    # right panel: recall bars
    bx, bw, top = 610, 150, y0
    kinds = [k for k in KIND_LABELS if k in review["alterations"]]
    step = h / (len(kinds) + 1)
    for i, k in enumerate(kinds):
        y = top + i * step
        parts.append(f'  <text class="m" x="{bx - 8}" y="{y + 16:.1f}" text-anchor="end">{KIND_LABELS[k]}</text>')
        for j, (m, colour) in enumerate((("ae", p["series"][0]), ("pca", p["series"][2]))):
            value = review["alterations"][k][m]["recall"] or 0.0
            parts.append(f'  <rect x="{bx}" y="{y + j * 14:.1f}" width="{bw * value:.1f}" height="11" fill="{colour}"/>')
            parts.append(f'  <text class="m" x="{bx + bw * value + 4:.1f}" y="{y + j * 14 + 10:.1f}">{value:.2f}</text>')
    flags = review["alterations"]["unchanged"]
    y = top + len(kinds) * step
    parts.append(f'  <text class="m" x="{bx - 8}" y="{y + 16:.1f}" text-anchor="end">unchanged (false flags)</text>')
    for j, (m, colour) in enumerate((("ae", p["series"][0]), ("pca", p["series"][2]))):
        value = flags[m]["falseFlags"]
        parts.append(f'  <rect x="{bx}" y="{y + j * 14:.1f}" width="{bw * value:.1f}" height="11" fill="{colour}"/>')
        parts.append(f'  <text class="m" x="{bx + bw * value + 4:.1f}" y="{y + j * 14 + 10:.1f}">{value:.2f}</text>')
    parts.append(f'  <text class="m" x="{bx}" y="{y0 + h + 34}" style="fill:{p["series"][0]}">autoencoder</text>')
    parts.append(f'  <text class="m" x="{bx + 90}" y="{y0 + h + 34}" style="fill:{p["series"][2]}">PCA</text>')
    desc = (f"Index calibration RMSE {metrics['index']['rmse']:.2f} wt% Fe against OK {metrics['ordinaryKriging']['rmse']:.2f} "
            f"on {metrics['rows']} test rows. Recall by alteration (autoencoder, PCA): "
            + "; ".join(f"{KIND_LABELS[k]} {review['alterations'][k]['ae']['recall']:.2f}, "
                        f"{review['alterations'][k]['pca']['recall']:.2f}" for k in kinds)
            + f"; false flags {flags['ae']['falseFlags']:.2f}, {flags['pca']['falseFlags']:.2f}.")
    return svg(width, height, "Rocklea R12: the iron-oxide index and the geochemical review", desc,
               "\n".join(parts) + "\n", p)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--derived", type=Path, default=ROOT / "build" / "derived")
    args = parser.parse_args(argv)
    folder = args.derived / "rocklea"
    load = lambda name: json.loads((folder / name).read_text(encoding="utf-8"))
    models, metrics, review = load("spectral-models.json"), load("spectral-metrics.json"), load("geochemistry-metrics.json")
    truths = _truths(folder, {t["id"] for t in models["test"]})
    for theme, p in PALETTES.items():
        (ASSETS / f"review-rocklea-{theme}.svg").write_text(figure(models, metrics, review, truths, p),
                                                            encoding="utf-8", newline="\n")
    print(f"wrote 2 figures to {ASSETS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
