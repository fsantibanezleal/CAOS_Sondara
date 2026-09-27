#!/usr/bin/env python3
"""Write the features figure of the docs as a light and dark SVG pair from a real features output.

    python scripts/figures/features_figures.py [--derived build/derived]

Reads ``rocklea/features.json`` (run ``data-pipeline/run.py`` through ``features`` first) and writes
``docs/assets/features-rocklea-variograms-{light,dark}.svg``: the training variograms of Fe on the 1 m population of
the hole-group split, downhole and spatial, with the training variance as reference. Standard library only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "assets"
PALETTES = {
    "light": {"bg": "#ffffff", "fg": "#1f2328", "muted": "#59636e", "grid": "#d0d7de",
              "series": ["#0969da", "#bc4c00", "#57606a", "#1a7f37", "#8250df", "#cf222e", "#0a7ea4"]},
    "dark": {"bg": "#0d1117", "fg": "#c9d1d9", "muted": "#8b949e", "grid": "#30363d",
             "series": ["#58a6ff", "#f0883e", "#c9d1d9", "#3fb950", "#bc8cff", "#f85149", "#39c5cf"]},
}


def svg(width, height, title, desc, body, p):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-labelledby="t d">\n  <title id="t">{title}</title>\n  <desc id="d">{desc}</desc>\n'
        f"  <style>\n"
        f"    .t {{ font: 600 15px 'Segoe UI', Helvetica, Arial, sans-serif; fill: {p['fg']}; }}\n"
        f"    .b {{ font: 13px 'Segoe UI', Helvetica, Arial, sans-serif; fill: {p['fg']}; }}\n"
        f"    .m {{ font: 12px 'Segoe UI', Helvetica, Arial, sans-serif; fill: {p['muted']}; }}\n"
        f"  </style>\n  <rect width=\"{width}\" height=\"{height}\" fill=\"{p['bg']}\"/>\n{body}</svg>\n"
    )


def panel(parts, p, x0, y0, w, h, series, xmax, ymax, xlabel, variance):
    X = lambda v: x0 + w * v / xmax
    Y = lambda v: y0 + h * (1 - v / ymax)
    for k in range(5):
        yv = ymax * k / 4
        parts.append(f'  <line x1="{x0}" y1="{Y(yv):.1f}" x2="{x0 + w}" y2="{Y(yv):.1f}" stroke="{p["grid"]}"/>')
        parts.append(f'  <text class="m" x="{x0 - 6}" y="{Y(yv) + 4:.1f}" text-anchor="end">{yv:.0f}</text>')
        xv = xmax * k / 4
        parts.append(f'  <text class="m" x="{X(xv):.1f}" y="{y0 + h + 16}" text-anchor="middle">{xv:.0f}</text>')
    parts.append(f'  <text class="m" x="{x0 + w / 2}" y="{y0 + h + 34}" text-anchor="middle">{xlabel}</text>')
    parts.append(f'  <line x1="{x0}" y1="{Y(variance):.1f}" x2="{x0 + w}" y2="{Y(variance):.1f}" stroke="{p["muted"]}" '
                 'stroke-dasharray="6 4"/>')
    parts.append(f'  <text class="m" x="{x0 + w - 4}" y="{Y(variance) - 6:.1f}" text-anchor="end">training variance '
                 f'{variance:.0f}</text>')
    for label, v, index in series:
        colour = p["series"][index]
        points = [(s, g, c) for s, g, c in zip(v["separation"], v["values"], v["counts"], strict=True)
                  if g is not None and s is not None and s <= xmax]
        path = " ".join(f"{'M' if i == 0 else 'L'}{X(s):.1f},{Y(min(g, ymax)):.1f}" for i, (s, g, _) in enumerate(points))
        parts.append(f'  <path d="{path}" fill="none" stroke="{colour}" stroke-width="1.8"/>')
        for s, g, c in points:
            radius = 2 + min(4.0, (c / 2000) ** 0.5)
            parts.append(f'  <circle cx="{X(s):.1f}" cy="{Y(min(g, ymax)):.1f}" r="{radius:.1f}" fill="{colour}"/>')
    return X, Y


def variograms(features, p):
    scheme = next(s for s in features["schemes"] if s["scheme"] == "hole-group")
    population = next(x for x in scheme["populations"] if x["population"] == "rocklea-native-1m")
    fe = population["analytes"]["Fe"]
    stats = fe["statistics"]
    by_name = {v["name"]: v for v in fe["variograms"]}
    variance = stats["variance"]
    top = max(variance, max(g for v in fe["variograms"] for g in v["values"] if g is not None))
    ymax = 100 * (int(top * 1.05 / 100) + 1)
    parts = [('  <text class="t" x="24" y="30">Rocklea Fe, 1 m training samples of the hole-group split: '
              'experimental variograms</text>')]
    panel(parts, p, 70, 70, 300, 240, [("downhole", by_name["downhole"], 0), ("vertical", by_name["vertical"], 1)],
          20, ymax, "separation along the hole (m)", variance)
    names = ("omni", "azimuth-000", "azimuth-045", "azimuth-090", "azimuth-135")
    spatial = [(n, by_name[n], 2 + i) for i, n in enumerate(names)]
    xmax = 100 * (int(max(s for _, v, _ in spatial for s in v["separation"] if s is not None) / 100) + 1)
    panel(parts, p, 460, 70, 300, 240, spatial, xmax, ymax, "separation in space (m)", variance)
    parts.append('  <text class="m" x="70" y="58">semivariance ((wt%)^2)</text>')
    labels = [("downhole", 0), ("vertical", 1)] + [(n, i) for n, _, i in spatial]
    x = 70
    for k, (label, index) in enumerate(labels):
        colour = p["series"][index]
        y = 372 if k < 2 else 392
        if k == 2:
            x = 70
        parts.append(f'  <rect x="{x}" y="{y - 9}" width="12" height="3" fill="{colour}"/>')
        parts.append(f'  <text class="m" x="{x + 18}" y="{y - 4}">{label}</text>')
        x += 120
    parts.append(f'  <text class="m" x="24" y="420">{stats["count"]:,} samples in {stats["holes"]} training holes; '
                 f'declustered mean {stats["declustered"]["mean"]:.2f} against {stats["mean"]:.2f}. Dot size grows with '
                 'the pair count;</text>')
    parts.append('  <text class="m" x="24" y="438">empty bins are gaps, not zeros. Directional bins follow the '
                 'roughly 100 m drilling grid, so several lags hold no pairs.</text>')
    return svg(820, 458, "Rocklea Fe experimental variograms",
               "Downhole and vertical variograms of Fe rising over the first metres toward the training variance, and "
               "omnidirectional and four horizontal directional variograms near that variance from the first spatial "
               "lag.", "\n".join(parts) + "\n", p)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--derived", type=Path, default=ROOT / "build" / "derived")
    args = parser.parse_args(argv)
    features = json.loads((args.derived / "rocklea" / "features.json").read_text(encoding="utf-8"))
    ASSETS.mkdir(parents=True, exist_ok=True)
    for mode, palette in PALETTES.items():
        (ASSETS / f"features-rocklea-variograms-{mode}.svg").write_text(variograms(features, palette),
                                                                         encoding="utf-8", newline="\n")
    print("written to", ASSETS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
