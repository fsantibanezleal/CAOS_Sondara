#!/usr/bin/env python3
"""Write the evaluation figures of the docs as light and dark SVG pairs from a real metrics output.

    python scripts/figures/evaluate_figures.py [--derived build/derived]

Reads ``rocklea/metrics.json`` (run ``data-pipeline/run.py`` through ``evaluate`` first) and writes, for Fe on the 1 m
population of the hole-group split:

- ``docs/assets/evaluate-rocklea-methods-{light,dark}.svg``: every method and scenario variant against ordinary
  kriging, as the paired mean absolute-error difference with its 95 % hole-block bootstrap interval, beside each
  one's RMSE on the common targets;
- ``docs/assets/evaluate-rocklea-sgs-{light,dark}.svg``: the downhole variogram and the quantiles of the test truths,
  of ordinary kriging's estimates and of the SGS realizations (mean and 10 to 90 % band over realizations).

Standard library only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "assets"
PALETTES = {
    "light": {"bg": "#ffffff", "fg": "#1f2328", "muted": "#59636e", "grid": "#d0d7de", "band": "#0969da",
              "series": ["#0969da", "#bc4c00", "#57606a", "#1a7f37", "#8250df", "#cf222e", "#0a7ea4"]},
    "dark": {"bg": "#0d1117", "fg": "#c9d1d9", "muted": "#8b949e", "grid": "#30363d", "band": "#58a6ff",
             "series": ["#58a6ff", "#f0883e", "#c9d1d9", "#3fb950", "#bc8cff", "#f85149", "#39c5cf"]},
}
LABELS = {"nearest-neighbour": "NN", "inverse-distance": "IDW", "simple-kriging": "SK", "universal-kriging": "UK",
          "ordinary-cokriging": "LMC cokriging", "sequential-gaussian": "SGS (E-type)",
          "neighbourhood-small": "OK, 8 samples, 3 per hole", "neighbourhood-large": "OK, 64 samples, no cap",
          "isotropic": "OK, best isotropic model", "integrated-support": "OK, interval supports",
          "sparse-primary": "cokriging, secondaries at target"}


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


def population(metrics, scheme="hole-group", name="rocklea-native-1m"):
    s = next(x for x in metrics["schemes"] if x["scheme"] == scheme)
    return next(x for x in s["populations"] if x["population"] == name)


def methods_figure(record, p):
    rows = [(LABELS[m], e["versusOrdinaryKriging"], e["common"]["rmse"], 0)
            for m, e in record["methods"].items() if "versusOrdinaryKriging" in e]
    rows += [(LABELS[n], v["versusOrdinaryKriging"], v["scores"]["rmse"], 1) for n, v in record["variants"].items()]
    ok = record["methods"]["ordinary-kriging"]["common"]
    reach = max(max(abs(r[1]["interval95"][0]), abs(r[1]["interval95"][1])) for r in rows)
    span = 2 * (int(reach / 2) + 1)
    x0, w, y0, step = 250, 420, 76, 28
    X = lambda v: x0 + w * (v + span) / (2 * span)
    parts = [('  <text class="t" x="24" y="30">Rocklea Fe, 1 m samples, hole-group test holes: each method and '
              'variant against ordinary kriging</text>'),
             (f'  <text class="m" x="24" y="52">Paired mean absolute-error difference (wt% Fe) with its 95 % '
              f'hole-block bootstrap interval; left of zero beats OK. OK RMSE {ok["rmse"]:.2f} on '
              f'{ok["n"]} common targets in {ok["holes"]} holes.</text>')]
    height = y0 + step * (len(rows) + 1) + 40
    for k in range(-span, span + 1, max(1, span // 4)):
        parts.append(f'  <line x1="{X(k):.1f}" y1="{y0 - 8}" x2="{X(k):.1f}" y2="{height - 52}" '
                     f'stroke="{p["grid"]}"/>')
        parts.append(f'  <text class="m" x="{X(k):.1f}" y="{height - 36}" text-anchor="middle">{k:+d}</text>')
    parts.append(f'  <line x1="{X(0):.1f}" y1="{y0 - 8}" x2="{X(0):.1f}" y2="{height - 52}" stroke="{p["fg"]}"/>')
    parts.append(f'  <text class="m" x="{x0 + w / 2}" y="{height - 16}" text-anchor="middle">mean |error| minus '
                 f'OK mean |error| (wt% Fe)</text>')
    parts.append(f'  <text class="m" x="{x0 + w + 24}" y="{y0 - 12}">RMSE</text>')
    for i, (label, cmp, rmse, group) in enumerate(rows):
        y = y0 + step * i + (step if group else 0)
        colour = p["series"][0 if group == 0 else 1]
        low, high = cmp["interval95"]
        parts.append(f'  <text class="b" x="{x0 - 12}" y="{y + 4}" text-anchor="end">{label}</text>')
        parts.append(f'  <line x1="{X(low):.1f}" y1="{y}" x2="{X(high):.1f}" y2="{y}" stroke="{colour}" '
                     f'stroke-width="3"/>')
        parts.append(f'  <circle cx="{X(cmp["meanAbsoluteErrorDifference"]):.1f}" cy="{y}" r="5" fill="{colour}"/>')
        parts.append(f'  <text class="b" x="{x0 + w + 24}" y="{y + 4}">{rmse:.2f}</text>')
    parts.append(f'  <text class="m" x="24" y="{y0 + step * len([r for r in rows if r[3] == 0]) + 6}">'
                 f'scenario variants</text>')
    desc = "; ".join(f"{label}: {cmp['meanAbsoluteErrorDifference']:+.2f} [{cmp['interval95'][0]:+.2f}, "
                     f"{cmp['interval95'][1]:+.2f}], RMSE {rmse:.2f}" for label, cmp, rmse, _ in rows)
    return svg(780, height, "Rocklea methods and variants against ordinary kriging",
               f"Paired mean absolute-error differences with 95 % hole-block intervals. {desc}.", "\n".join(parts) + "\n", p)


def sgs_figure(record, p):
    rep = record["methods"]["sequential-gaussian"]["reproduction"]
    lags = rep["downholeVariogram"]["lags"]
    hist = rep["histogram"]
    parts = [('  <text class="t" x="24" y="30">Rocklea Fe, hole-group test holes: SGS keeps the variability '
              'ordinary kriging smooths away</text>'),
             (f'  <text class="m" x="24" y="52">{rep["targets"]} test samples, {rep["realizations"]} realizations; '
              f'band = 10 to 90 % over realizations.</text>')]

    def frame(x0, y0, w, h, xs, ymax, xlabel, ylabel, xfmt):
        X = lambda v: x0 + w * (v - xs[0]) / (xs[-1] - xs[0])
        Y = lambda v: y0 + h * (1 - v / ymax)
        for k in range(5):
            yv = ymax * k / 4
            parts.append(f'  <line x1="{x0}" y1="{Y(yv):.1f}" x2="{x0 + w}" y2="{Y(yv):.1f}" stroke="{p["grid"]}"/>')
            parts.append(f'  <text class="m" x="{x0 - 6}" y="{Y(yv) + 4:.1f}" text-anchor="end">{yv:.0f}</text>')
        for xv in xs:
            parts.append(f'  <text class="m" x="{X(xv):.1f}" y="{y0 + h + 16}" text-anchor="middle">'
                         f'{xfmt(xv)}</text>')
        parts.append(f'  <text class="m" x="{x0 + w / 2}" y="{y0 + h + 34}" text-anchor="middle">{xlabel}</text>')
        parts.append(f'  <text class="m" x="{x0}" y="{y0 - 10}">{ylabel}</text>')
        return X, Y

    def line(X, Y, xs, ys, colour, dash=None):
        path = " ".join(f"{'M' if i == 0 else 'L'}{X(x):.1f},{Y(y):.1f}" for i, (x, y) in enumerate(zip(xs, ys, strict=True)))
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        parts.append(f'  <path d="{path}" fill="none" stroke="{colour}" stroke-width="2"{extra}/>')
        parts.extend(f'  <circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="3" fill="{colour}"/>'
                     for x, y in zip(xs, ys, strict=True))

    def band(X, Y, xs, lows, highs):
        top = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xs, highs, strict=True))
        bottom = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(reversed(xs), reversed(lows), strict=True))
        parts.append(f'  <polygon points="{top} {bottom}" fill="{p["band"]}" fill-opacity="0.18" stroke="none"/>')

    xs = [g["separation"] for g in lags]
    top = max(max(g["truth"], g["realizations"]["p90"]) for g in lags)
    ymax = 25 * (int(top * 1.1 / 25) + 1)
    X, Y = frame(80, 90, 300, 220, xs, ymax, "separation along the hole (m)", "semivariance (wt% Fe squared)",
                 lambda v: f"{v:g}")
    band(X, Y, xs, [g["realizations"]["p10"] for g in lags], [g["realizations"]["p90"] for g in lags])
    line(X, Y, xs, [g["realizations"]["mean"] for g in lags], p["series"][0])
    line(X, Y, xs, [g["truth"] for g in lags], p["series"][2], "5 3")
    line(X, Y, xs, [g["ordinaryKriging"] for g in lags], p["series"][1])
    levels = [float(q) for q in hist["truth"]["quantiles"]]
    keys = list(hist["truth"]["quantiles"])
    values = [hist[k]["quantiles"][q] for k in ("truth", "ordinaryKriging", "training") for q in keys]
    values += [hist["realizations"]["quantiles"][q][b] for q in keys for b in ("p10", "p90")]
    low, high = 10 * int(min(values) / 10), 10 * (int(max(values) / 10) + 1)
    X2 = lambda v: 470 + 280 * (v - 0.1) / 0.8
    Y2 = lambda v: 90 + 220 * (1 - (v - low) / (high - low))
    for k in range(5):
        yv = low + (high - low) * k / 4
        parts.append(f'  <line x1="470" y1="{Y2(yv):.1f}" x2="750" y2="{Y2(yv):.1f}" stroke="{p["grid"]}"/>')
        parts.append(f'  <text class="m" x="464" y="{Y2(yv) + 4:.1f}" text-anchor="end">{yv:.0f}</text>')
    for q in levels:
        parts.append(f'  <text class="m" x="{X2(q):.1f}" y="326" text-anchor="middle">{q:g}</text>')
    parts.append('  <text class="m" x="610" y="344" text-anchor="middle">quantile level</text>')
    parts.append('  <text class="m" x="470" y="80">Fe (wt%)</text>')
    band(X2, Y2, levels, [hist["realizations"]["quantiles"][q]["p10"] for q in keys],
         [hist["realizations"]["quantiles"][q]["p90"] for q in keys])
    line(X2, Y2, levels, [hist["realizations"]["quantiles"][q]["mean"] for q in keys], p["series"][0])
    line(X2, Y2, levels, [hist["truth"]["quantiles"][q] for q in keys], p["series"][2], "5 3")
    line(X2, Y2, levels, [hist["ordinaryKriging"]["quantiles"][q] for q in keys], p["series"][1])
    line(X2, Y2, levels, [hist["training"]["quantiles"][q] for q in keys], p["series"][3], "2 3")
    legend = [("test truths", 2), ("SGS realizations (mean and band)", 0), ("ordinary kriging", 1),
              ("training samples (quantiles only)", 3)]
    for i, (label, colour) in enumerate(legend):
        x = 80 + 175 * i
        parts.append(f'  <line x1="{x}" y1="378" x2="{x + 22}" y2="378" stroke="{p["series"][colour]}" '
                     f'stroke-width="3"/>')
        parts.append(f'  <text class="m" x="{x + 28}" y="382">{label}</text>')
    first = lags[0]
    desc = (f"Downhole semivariance at {first['separation']:g} m: truths {first['truth']:.1f}, ordinary kriging "
            f"{first['ordinaryKriging']:.1f}, SGS mean {first['realizations']['mean']:.1f} (band "
            f"{first['realizations']['p10']:.1f} to {first['realizations']['p90']:.1f}). Variance of the truths "
            f"{hist['truth']['variance']:.1f}, of ordinary kriging {hist['ordinaryKriging']['variance']:.1f}, of the "
            f"realizations {hist['realizations']['variance']['mean']:.1f}.")
    return svg(800, 400, "Rocklea SGS reproduction against ordinary kriging", desc, "\n".join(parts) + "\n", p)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--derived", type=Path, default=ROOT / "build" / "derived")
    args = parser.parse_args(argv)
    record = population(json.loads((args.derived / "rocklea" / "metrics.json").read_text(encoding="utf-8")))
    for theme, p in PALETTES.items():
        (ASSETS / f"evaluate-rocklea-methods-{theme}.svg").write_text(methods_figure(record, p), encoding="utf-8",
                                                                      newline="\n")
        (ASSETS / f"evaluate-rocklea-sgs-{theme}.svg").write_text(sgs_figure(record, p), encoding="utf-8",
                                                                  newline="\n")
    print(f"wrote 4 figures to {ASSETS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
