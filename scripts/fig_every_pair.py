"""Fig. 1: every FEE clock pair on the two builders that publish a clock, drawn raw against that clock.

One mark per pair (above the plot B landed first, below it A did), the share in the bins of the REPORT with its Wilson
95% interval, and the dashed line 1 - s/T that a metronome of the published period T would give at random phase.
No model is fitted here. The last bin, 75 to 300 ms, gets its own compressed strip, so that every pair is on the page.

Usage:
    python scripts/fig_every_pair.py [--derived data/derived] [--out figures]
"""
import argparse
import os
import sys

import pandas as pd
from matplotlib.transforms import ScaledTranslation

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from analysis import figures, fit, pairs  # noqa: E402
from analysis.figures import plt  # noqa: E402

BINS = [(0, 5), (5, 10), (10, 15), (15, 20), (20, 25), (25, 30), (30, 35), (35, 40), (40, 50), (50, 75), (75, 300)]
HARMONIC, BAM = ["HarmonicAgave", "HarmonicFiredancer"], ["AgaveBam", "FireBAM"]
EDGE = 75.0  # where the linear axis ends and the strip begins
LAST = 302.0  # the longest gaps overshoot 300 ms by a few microseconds
RUG_TOP, RUG_BOTTOM = (1.03, 1.08), (-0.08, -0.03)
AXIS_DROP = 20  # points between the plot and its x axis, room for the lower row of marks


def draw(fig, spec, g, period, title, t):
    gs = spec.subgridspec(1, 2, width_ratios=[EDGE, 21], wspace=0.04)
    ax, tail = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    near, far = g[g["s_ms"] <= EDGE], g[g["s_ms"] > EDGE]
    for a, part, xlim in ((ax, near, (0, EDGE)), (tail, far, (EDGE, LAST))):
        for ahead, row in ((1, RUG_TOP), (0, RUG_BOTTOM)):
            a.vlines(part.loc[part["y"] == ahead, "s_ms"], *row, color=t["ink"], lw=0.45, clip_on=False)
        a.set_xlim(*xlim)
        a.set_ylim(0, 1)
        a.spines["bottom"].set_position(("outward", AXIS_DROP))
        a.tick_params(axis="x", which="both", direction="out")
    ax.plot([0, period, EDGE], [1, 0, 0], color=t["claim"], lw=1.25, ls=(0, (5, 3)), zorder=2, clip_on=False)
    tail.plot([EDGE, LAST], [0, 0], color=t["claim"], lw=1.25, ls=(0, (5, 3)), zorder=2, clip_on=False)
    for lo, hi in BINS:
        m = (g["s_ms"] > lo) & (g["s_ms"] <= hi)
        n, k = int(m.sum()), int(g.loc[m, "y"].sum())
        a_lo, a_hi = fit.wilson(k, n)
        x = float(g.loc[m, "s_ms"].median())
        a = ax if hi <= EDGE else tail
        a.plot([x, x], [a_lo, a_hi], color=t["ink"], lw=0.8, zorder=3, clip_on=False)
        a.plot([x], [k / n], "o", ms=5.4, color=t["ink"], mec=t["paper"], mew=0.8, zorder=4, clip_on=False)
    # axes
    ticks = list(range(0, 71, 10))
    ax.set_xticks(ticks, [str(x) for x in ticks])
    ax.set_xticks(range(0, 76, 5), minor=True)
    for label, x in zip(ax.get_xticklabels(), ticks):
        if x == period:
            label.set_color(t["claim"])
    tail.set_xticks([100, 200, 300], ["100", "200", "300"])
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0", "25%", "50%", "75%", "100%"])
    ax.spines["left"].set_position(("outward", 9))
    tail.spines["left"].set_visible(False)
    tail.tick_params(axis="y", left=False, labelleft=False)
    ax.set_xlabel(r"gap $s$ between the two sends, ms", x=0.62)
    # the two pieces of the bottom axis, with the usual marks for a break
    for a, x0 in ((ax, 1.0), (tail, 0.0)):
        dx = 0.012 if a is ax else 0.012 * EDGE / 21
        tr = a.transAxes + ScaledTranslation(0, -AXIS_DROP / 72, fig.dpi_scale_trans)
        a.plot([x0 - dx, x0 + dx], [-0.022, 0.022], transform=tr, color=t["ink"], lw=0.7, clip_on=False)
    ax.text(0, 1.125, title, transform=ax.transAxes, fontsize=12.5, va="bottom")
    return ax, tail


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--derived", default="data/derived")
    ap.add_argument("--out", default="figures")
    a = ap.parse_args()
    df = pd.read_csv(os.path.join(a.derived, "pairs.csv"), low_memory=False)
    cp = pairs.clock_pairs(df)
    cp = cp[cp["series"] == "FEE"]
    harmonic, bam = cp[cp["family"].isin(HARMONIC)], cp[cp["family"].isin(BAM)]
    last = harmonic.loc[harmonic["y"] == 1, "s_ms"].max()
    past = int((harmonic["s_ms"] > last).sum())
    m = (bam["s_ms"] > 75) & (bam["s_ms"] <= 300)
    late_k, late_n = int(bam.loc[m, "y"].sum()), int(m.sum())
    print(f"Harmonic {len(harmonic)} pairs, last overtake {last} ms, {past} pairs past it; BAM {len(bam)} pairs, 75-300 ms {late_k}/{late_n}")
    for theme in figures.THEMES:
        t = figures._style(theme)
        fig = plt.figure(figsize=(10.2, 3.75))
        outer = fig.add_gridspec(1, 2, wspace=0.085)
        ax_h, tail_h = draw(fig, outer[0], harmonic, 50.0, r"$\mathbf{(a)}$ Harmonic publishes 50 ms", t)
        ax_b, tail_b = draw(fig, outer[1], bam, 20.0, r"$\mathbf{(b)}$ BAM publishes 20 ms", t)
        ax_h.set_ylabel(r"share of pairs: dearer $B$ lands first")
        ax_b.tick_params(axis="y", labelleft=False)
        for row, text in ((sum(RUG_TOP) / 2, r"$B$ first"), (sum(RUG_BOTTOM) / 2, r"$A$ first")):
            ax_h.annotate(text, (0, row), xycoords=ax_h.get_yaxis_transform(), xytext=(-14, 0), textcoords="offset points", ha="right", va="center", fontsize=10, color=t["ink2"], annotation_clip=False)
        # what to read
        ax_h.annotate(f"last overtake at {last:.1f} ms,\nthen {past} pairs without one", (last, RUG_TOP[0] - 0.005), xytext=(39, 0.87), ha="left", va="center", fontsize=11, linespacing=1.25,
                      arrowprops={"arrowstyle": "-", "color": t["faint"], "lw": 0.6, "shrinkA": 2, "shrinkB": 1, "relpos": (0, 0.72)}, annotation_clip=False)
        ax_h.text(33.5, 0.42, "a 50 ms clock\nwould give this line", ha="left", va="center", fontsize=10.5, color=t["claim"], linespacing=1.25)
        tail_b.text(1.0, 0.875, f"sent 75 to 300 ms late,\n$B$ still lands first in\n{late_k} of {late_n} pairs", transform=tail_b.get_yaxis_transform(), ha="right", va="center", fontsize=11, linespacing=1.25)
        tail_b.plot([100, 100], [0.76, 0.56], color=t["faint"], lw=0.6)
        ax_b.text(22, 0.055, "a 20 ms clock would give this line", ha="left", va="center", fontsize=10.5, color=t["claim"])
        figures._save(fig, a.out, "fig1-every-pair", theme)


if __name__ == "__main__":
    main()
