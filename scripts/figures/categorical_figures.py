#!/usr/bin/env python3
"""Write the categorical figures of the docs as light and dark SVG pairs from the real Alberta outputs.

    python scripts/figures/categorical_figures.py [--derived build/derived]

Reads ``alberta/categorical-models.json``, ``categorical-predictions.json`` and the training images and realizations
they name (run ``data-pipeline/run.py`` through ``evaluate`` first), and writes:

- ``docs/assets/categorical-alberta-priors-{light,dark}.svg``: the two training images of the hole-group split, a plan
  at 185 m depth and a west-east section, category by category;
- ``docs/assets/categorical-alberta-sections-{light,dark}.svg``: one west-east section of the grid through the most
  conditioned row, the most probable category of each engine and prior over 32 realizations, with the conditioning
  cells outlined.

Standard library and NumPy only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "assets"
PALETTES = {
    "light": {"bg": "#ffffff", "fg": "#1f2328", "muted": "#59636e", "edge": "#1f2328",
              "cat": ["#c9b37e", "#7fb3d5", "#e59866", "#85929e", "#c0392b"]},
    "dark": {"bg": "#0d1117", "fg": "#c9d1d9", "muted": "#8b949e", "edge": "#f0f6fc",
             "cat": ["#b59a5a", "#5dade2", "#dc7633", "#5d6d7e", "#e74c3c"]},
}
NAMES = ["overburden", "Devonian", "Athabasca Group", "basement gneiss", "basement granitoid"]
PRIOR_LABEL = {"nw-high-strain": "northwest high-strain fabric", "gneiss-domes": "gneiss domes"}
ENGINE_LABEL = {"snesim": "SNESIM (MPSlib)", "direct-sampling": "Direct Sampling (GeoCond, zoned)"}


FONT = "Segoe UI, Helvetica, Arial, sans-serif"


def svg(width, height, title, desc, body, p):
    # Text colours as presentation attributes too: a renderer that ignores the style block still draws them right.
    body = (body.replace('class="t"', f'class="t" font-family="{FONT}" font-size="15" font-weight="600" fill="{p["fg"]}"')
            .replace('class="b"', f'class="b" font-family="{FONT}" font-size="13" fill="{p["fg"]}"')
            .replace('class="m"', f'class="m" font-family="{FONT}" font-size="12" fill="{p["muted"]}"'))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-labelledby="t d">\n  <title id="t">{title}</title>\n  <desc id="d">{desc}</desc>\n'
        f"  <style>\n"
        f"    .t {{ font: 600 15px 'Segoe UI', Helvetica, Arial, sans-serif; fill: {p['fg']}; }}\n"
        f"    .b {{ font: 13px 'Segoe UI', Helvetica, Arial, sans-serif; fill: {p['fg']}; }}\n"
        f"    .m {{ font: 12px 'Segoe UI', Helvetica, Arial, sans-serif; fill: {p['muted']}; }}\n"
        f"  </style>\n  <rect width=\"{width}\" height=\"{height}\" fill=\"{p['bg']}\"/>\n{body}</svg>\n"
    )


def raster(parts, p, grid, x0, y0, cw, ch):
    """A 2D category array (columns x, rows y downward) as run-length rectangles; each row overlaps the next by a
    fraction of a pixel, which the next row covers, so no renderer shows a seam between rows."""
    for row in range(grid.shape[1]):
        start = 0
        for col in range(1, grid.shape[0] + 1):
            if col == grid.shape[0] or grid[col, row] != grid[start, row]:
                parts.append(f'  <rect x="{x0 + start * cw:.1f}" y="{y0 + row * ch:.1f}" '
                             f'width="{(col - start) * cw:.1f}" height="{ch + (0.6 if row < grid.shape[1] - 1 else 0):.1f}" '
                             f'fill="{p["cat"][int(grid[start, row])]}" shape-rendering="crispEdges"/>')
                start = col


def legend(parts, p, x, y):
    for i, name in enumerate(NAMES):
        parts.append(f'  <rect x="{x + i * 150}" y="{y - 10}" width="12" height="12" fill="{p["cat"][i]}"/>')
        parts.append(f'  <text class="m" x="{x + i * 150 + 18}" y="{y}">{name}</text>')


def priors_figure(scheme, derived, p):
    parts = [('  <text class="t" x="24" y="30">Alberta training images, hole-group split: two labelled priors that '
              'share the cover</text>'),
             ('  <text class="m" x="24" y="50">Authored from the training holes (cover thicknesses, granitoid '
              'share); interpretations, not observed geology. 250 m cells, 10 m layers.</text>')]
    for n, image in enumerate(scheme["trainingImages"]):
        ti = np.load(derived / "alberta" / image["file"])
        x = 24 + n * 470
        parts.append(f'  <text class="b" x="{x}" y="82">{PRIOR_LABEL[image["prior"]]}</text>')
        plan = ti[:, ::-1, 18]  # plan at 185 m depth, north up
        raster(parts, p, plan, x, 92, 3.0, 3.0)
        parts.append(f'  <text class="m" x="{x}" y="{92 + 72 * 3 + 16}">plan at 185 m depth, north up '
                     f'(18 x 18 km)</text>')
        section = ti[:, 36, :]  # west-east, depth down
        raster(parts, p, section, x + 232, 92, 3.0, 9.0)
        parts.append(f'  <text class="m" x="{x + 232}" y="{92 + 24 * 9 + 16}">west-east section, 0 to 240 m</text>')
    legend(parts, p, 24, 350)
    desc = ("Two training images of five categories. Both have the same layered cover of overburden, Devonian and "
            "Athabasca Group over basement gneiss; the first puts granitoid in steep bands along azimuth 315, the "
            "second in rounded bodies.")
    return svg(960, 370, "Alberta training images", desc, "\n".join(parts) + "\n", p)


def sections_figure(models, predictions, derived, p):
    scheme = next(s for s in models["schemes"] if s["scheme"] == "hole-group")
    hard = scheme["conditioning"]["hard"]
    rows = np.bincount([h["cell"][1] for h in hard])
    j = int(np.argmax(rows))
    runs = [r for r in predictions["runs"] if r["scheme"] == "hole-group"]
    cw, ch = 12.0, 9.0
    parts = [('  <text class="t" x="24" y="30">Alberta, hole-group split: the most probable category over 32 '
              f'realizations, west-east row {j}</text>'),
             ('  <text class="m" x="24" y="50">Outlined cells are conditioned by training holes; 250 m cells, '
              '10 m layers, depth down.</text>')]
    for n, run in enumerate(sorted(runs, key=lambda r: (r["engine"], r["prior"]))):
        fields = np.load(derived / "alberta" / run["file"])[:, :, j, :]
        counts = np.stack([(fields == c).sum(axis=0) for c in range(5)])
        mode = counts.argmax(axis=0)
        x = 24 + (n % 2) * 470
        y = 80 + (n // 2) * 270
        parts.append(f'  <text class="b" x="{x}" y="{y}">{ENGINE_LABEL[run["engine"]]}, '
                     f'{PRIOR_LABEL[run["prior"]]}</text>')
        raster(parts, p, mode, x, y + 10, cw, ch)
        for h in hard:
            if h["cell"][1] == j:
                i, _, k = h["cell"]
                parts.append(f'  <rect x="{x + i * cw:.1f}" y="{y + 10 + k * ch:.1f}" width="{cw:.1f}" '
                             f'height="{ch:.1f}" fill="none" stroke="{p["edge"]}" stroke-width="1.2"/>')
    legend(parts, p, 24, 80 + 2 * 270 - 18)
    desc = (f"Four sections of the Alberta grid at row {j}, one per engine and prior, coloured by the category most "
            f"often simulated in 32 realizations, with the {int(rows[j])} conditioning cells of the "
            "training holes outlined. The cover is layered in all four; the basement granitoid differs between priors.")
    return svg(960, 80 + 2 * 270, "Alberta categorical sections", desc, "\n".join(parts) + "\n", p)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--derived", type=Path, default=ROOT / "build" / "derived")
    args = parser.parse_args(argv)
    models = json.loads((args.derived / "alberta" / "categorical-models.json").read_text(encoding="utf-8"))
    predictions = json.loads((args.derived / "alberta" / "categorical-predictions.json").read_text(encoding="utf-8"))
    scheme = next(s for s in models["schemes"] if s["scheme"] == "hole-group")
    for theme, p in PALETTES.items():
        (ASSETS / f"categorical-alberta-priors-{theme}.svg").write_text(
            priors_figure(scheme, args.derived, p), encoding="utf-8", newline="\n")
        (ASSETS / f"categorical-alberta-sections-{theme}.svg").write_text(
            sections_figure(models, predictions, args.derived, p), encoding="utf-8", newline="\n")
    print(f"wrote 4 figures to {ASSETS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
