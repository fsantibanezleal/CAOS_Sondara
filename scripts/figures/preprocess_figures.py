#!/usr/bin/env python3
"""Write the preprocess figures of docs/ as light and dark SVG pairs from real preprocess outputs.

    python scripts/figures/preprocess_figures.py [--derived build/derived]

Reads ``<family>/preprocessed.json`` for Rocklea, Alberta and NTGS (run ``data-pipeline/run.py ingest`` and
``preprocess`` first) and writes ``docs/assets/preprocess-*-{light,dark}.svg``. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "assets"

PALETTES = {
    "light": {"bg": "#ffffff", "fg": "#1f2328", "muted": "#59636e", "grid": "#d0d7de", "a": "#0969da",
              "good": "#1a7f37", "warn": "#9a6700", "bad": "#d1242f"},
    "dark": {"bg": "#0d1117", "fg": "#c9d1d9", "muted": "#8b949e", "grid": "#30363d", "a": "#58a6ff",
             "good": "#3fb950", "warn": "#d29922", "bad": "#f85149"},
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


def composites(pre, p):
    """Rocklea: composite statuses at 1, 2 and 5 m as stacked horizontal bars."""
    rows = {w["step"]: w for w in pre["waterfall"]}
    x0, width, top = 110, 400, 70
    most = max(w["count"] for w in rows.values())
    parts = ['  <text class="t" x="24" y="30">Rocklea composites: full, residual and gap-touching intervals per length</text>']
    for i, length in enumerate((1, 2, 5)):
        w = rows[f"{length} m composites"]
        y = top + i * 56
        parts.append(f'  <text class="b" x="24" y="{y + 20}">{length} m</text>')
        x = x0
        for key, colour in (("full", p["good"]), ("residual", p["warn"]), ("insufficientCoverage", p["bad"])):
            span = width * w[key] / most
            parts.append(f'  <rect x="{x:.1f}" y="{y}" width="{max(span, 1.5):.1f}" height="28" fill="{colour}" fill-opacity="0.85"/>')
            x += span
        parts.append(f'  <text class="m" x="{x + 8:.1f}" y="{y + 19}">{w["full"]:,} full, {w["residual"]} residual, '
                     f'{w["insufficientCoverage"]} touch a gap</text>')
    y = top + 3 * 56 + 6
    for k, (label, colour) in enumerate((("full: declared length, coverage 1", p["good"]),
                                         ("residual: last short composite of a hole", p["warn"]),
                                         ("touches one of the 12 one-metre gaps: no mean", p["bad"]))):
        parts.append(f'  <rect x="{24 + k * 250}" y="{y}" width="12" height="12" fill="{colour}"/>')
        parts.append(f'  <text class="m" x="{42 + k * 250}" y="{y + 11}">{label}</text>')
    parts.append(f'  <text class="m" x="24" y="{y + 40}">Only full composites enter a uniform-support population. The grade-length integral of every '
                 f'analyte is conserved per hole</text>')
    parts.append(f'  <text class="m" x="24" y="{y + 58}">(largest relative error '
                 f'{max(pre["composites"]["conservationMaxRelativeError"].values()):.1e}).</text>')
    return svg(820, y + 78, "Rocklea composites by length",
               "Stacked bars of full, residual and gap-touching composites at 1, 2 and 5 m for the 158 Rocklea holes.",
               "\n".join(parts) + "\n", p)


def overlay(pre, p):
    """Alberta: how much of the 176 sampling envelopes each kind of log covers."""
    s = pre["overlay"]["summary"]
    x0, width, top = 250, 440, 70
    parts = ['  <text class="t" x="24" y="30">Alberta: logged geology over the 176 Cu/Zn sampling envelopes</text>']
    labels = (("anyLog", "any positive log"), ("lithoUnit", "known Litho_unit"), ("rockType", "known Rock_type"))
    for i, (key, label) in enumerate(labels):
        y = top + i * 60
        share = s[key]["coveredLength"] / s["envelopeLength"]
        parts.append(f'  <text class="b" x="24" y="{y + 19}">{label}</text>')
        parts.append(f'  <rect x="{x0}" y="{y}" width="{width}" height="26" fill="none" stroke="{p["grid"]}"/>')
        parts.append(f'  <rect x="{x0}" y="{y}" width="{width * share:.1f}" height="26" fill="{p["a"]}" fill-opacity="0.8"/>')
        parts.append(f'  <text class="m" x="{x0}" y="{y + 44}">{s[key]["coveredLength"]:.1f} of {s["envelopeLength"]:.1f} m covered; '
                     f'{s[key]["fullyCovered"]} of {s["envelopes"]} envelopes fully covered</text>')
    y = top + 3 * 60 + 10
    parts.append(f'  <text class="m" x="24" y="{y}">A piece logged with two different known codes would be a conflict, not a choice; this report has none.</text>')
    parts.append(f'  <text class="m" x="24" y="{y + 18}">{s["multiplyLoggedEnvelopes"]} envelopes cross the 0.05 m where MR-14 is logged twice. Codes -9999 and blank are unknown.</text>')
    return svg(760, y + 38, "Alberta log coverage of sampling envelopes",
               "Bars showing the share of the 176 Alberta sampling envelopes covered by any log, by a known Litho_unit "
               "and by a known Rock_type, with the counts of fully covered envelopes.",
               "\n".join(parts) + "\n", p)


def trajectory(pre, p):
    """NTGS 12LE002: a true-scale side view, and the departure from the collar direction against measured depth."""
    t = pre["trajectories"][0]
    first = t["stations"][0]
    a, d = math.radians(first["azimuth"]), math.radians(first["dip"])
    tangent = (math.cos(d) * math.sin(a), math.cos(d) * math.cos(a), math.sin(d))
    stations = [(s["md"], s["position"]) for s in t["stations"]] + [(t["endMd"], t["endPosition"])]
    departure = [(md, math.dist(q, [md * c for c in tangent])) for md, q in stations]
    parts = ['  <text class="t" x="24" y="30">NTGS 12LE002: eleven measured stations bend the hole away from its collar direction</text>']
    # left: side view at true scale, west distance against elevation
    x0, y0, scale = 60, 70, 0.8
    X = lambda q: x0 + scale * (-q[0])
    Y = lambda q: y0 - scale * q[2]
    end_md = t["endMd"]
    straight = [end_md * c for c in tangent]
    parts.append(f'  <line x1="{X([0, 0, 0]):.1f}" y1="{Y([0, 0, 0]):.1f}" x2="{X(straight):.1f}" y2="{Y(straight):.1f}" '
                 f'stroke="{p["muted"]}" stroke-width="1.5" stroke-dasharray="6 4"/>')
    path_d = " ".join(f"{'M' if i == 0 else 'L'}{X(q):.1f},{Y(q):.1f}" for i, (_, q) in enumerate(stations))
    parts.append(f'  <path d="{path_d}" fill="none" stroke="{p["a"]}" stroke-width="2.5"/>')
    for _, q in stations[1:-1]:
        parts.append(f'  <circle cx="{X(q):.1f}" cy="{Y(q):.1f}" r="3" fill="{p["a"]}"/>')
    parts.append(f'  <text class="m" x="{x0 + 40}" y="{y0 + 24}">side view, true scale:</text>')
    parts.append(f'  <text class="m" x="{x0 + 40}" y="{y0 + 40}">west 0 to {-stations[-1][1][0]:.0f} m,</text>')
    parts.append(f'  <text class="m" x="{x0 + 40}" y="{y0 + 56}">elevation 0 to {stations[-1][1][2]:.0f} m</text>')
    # right: departure from the straight projection against measured depth
    px, py, pw, ph = 330, 80, 380, 250
    top = 10.0
    U = lambda md: px + pw * md / 370
    V = lambda dev: py + ph * (1 - dev / top)
    for dev in (0, 2.5, 5, 7.5, 10):
        parts.append(f'  <line x1="{px}" y1="{V(dev):.1f}" x2="{px + pw}" y2="{V(dev):.1f}" stroke="{p["grid"]}"/>')
        parts.append(f'  <text class="m" x="{px - 8}" y="{V(dev) + 4:.1f}" text-anchor="end">{dev:g}</text>')
    for md in (0, 100, 200, 300):
        parts.append(f'  <text class="m" x="{U(md):.1f}" y="{py + ph + 16}" text-anchor="middle">{md}</text>')
    parts.append(f'  <text class="m" x="{px + pw / 2}" y="{py + ph + 34}" text-anchor="middle">measured depth (m)</text>')
    parts.append(f'  <text class="m" x="{px}" y="{py - 12}">departure from the collar direction (m)</text>')
    line = " ".join(f"{'M' if i == 0 else 'L'}{U(md):.1f},{V(dev):.1f}" for i, (md, dev) in enumerate(departure))
    parts.append(f'  <path d="{line}" fill="none" stroke="{p["a"]}" stroke-width="2.5"/>')
    for md, dev in departure[1:-1]:
        parts.append(f'  <circle cx="{U(md):.1f}" cy="{V(dev):.1f}" r="3" fill="{p["a"]}"/>')
    md, dev = departure[-1]
    parts.append(f'  <circle cx="{U(md):.1f}" cy="{V(dev):.1f}" r="4" fill="none" stroke="{p["warn"]}" stroke-width="2"/>')
    parts.append(f'  <text class="b" x="{U(md) - 8:.1f}" y="{V(dev) - 10:.1f}" text-anchor="end">{dev:.2f} m at total depth {md:.1f} m</text>')
    y = py + ph + 64
    parts.append(f'  <text class="m" x="24" y="{y}">Dots: the Reflex EZ-Shot stations from 60 to 360 m; dashed: the recorded collar direction '
                 f'({first["azimuth"]:.0f} / {first["dip"]:.0f}) projected</text>')
    parts.append(f'  <text class="m" x="24" y="{y + 18}">to total depth. Largest dogleg between stations {t["maxDoglegDegrees"]:.2f} degrees; '
                 f'the last 4.6 m follow the last measured tangent.</text>')
    return svg(760, y + 38, "NTGS 12LE002 measured trajectory",
               "Left, the minimum-curvature path of hole 12LE002 in true-scale side view against the straight projection "
               "of its recorded collar direction; right, the distance between the two against measured depth, reaching "
               "about 9.6 m at total depth.",
               "\n".join(parts) + "\n", p)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--derived", type=Path, default=ROOT / "build" / "derived")
    args = parser.parse_args(argv)
    load = lambda family: json.loads((args.derived / family / "preprocessed.json").read_text(encoding="utf-8"))
    figures = {"preprocess-rocklea-composites": (composites, load("rocklea")),
               "preprocess-alberta-overlay": (overlay, load("alberta")),
               "preprocess-ntgs-trajectory": (trajectory, load("ntgs"))}
    ASSETS.mkdir(parents=True, exist_ok=True)
    for name, (draw, pre) in figures.items():
        for mode, palette in PALETTES.items():
            (ASSETS / f"{name}-{mode}.svg").write_text(draw(pre, palette), encoding="utf-8", newline="\n")
    print("written to", ASSETS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
