"""Figures, each written twice: figures/<name>-light.svg and <name>-dark.svg.

One hand everywhere: Computer Modern, black ink, axes on the left and below, ticks inward, no grid. Vermilion is kept
for the numbers the vendors publish and nothing else. The lanes differ by a filled and a hollow mark, so they survive
greyscale and colour blindness. The background is transparent and every glyph is a path, so a file looks the same on
any page and needs no font. The SVGs are deterministic (fixed hash salt, no date).
"""
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.ticker import NullLocator  # noqa: E402

from . import fit, models  # noqa: E402

THEMES = {
    "light": {"ink": "#14181f", "ink2": "#4b5563", "faint": "#8b93a1", "claim": "#c2371a", "paper": "#ffffff"},
    "dark": {"ink": "#e8e6e1", "ink2": "#b4b2ab", "faint": "#7d7b75", "claim": "#ff7a59", "paper": "#0d1117"},
}
CLAIMS = {"AgaveBam": 20.0, "FireBAM": 20.0, "HarmonicAgave": 50.0, "HarmonicFiredancer": 50.0}
ORDER = ["HarmonicAgave", "HarmonicFiredancer", "AgaveBam", "FireBAM", "Firedancer", "JitoLabs", "Rakurai", "Agave"]


def _families(cells):
    """The clients in reading order: the builders that publish a clock first."""
    return sorted({c["family"] for c in cells}, key=lambda f: (ORDER.index(f) if f in ORDER else len(ORDER), f))


def _style(theme):
    t = THEMES[theme]
    plt.rcdefaults()
    plt.rcParams.update({
        "svg.hashsalt": "shutter-speed", "svg.fonttype": "path",
        "font.family": "cmr10", "mathtext.fontset": "cm", "axes.formatter.use_mathtext": True, "axes.unicode_minus": False,
        "font.size": 11.5, "axes.titlesize": 12.5, "axes.labelsize": 11.5,
        "figure.facecolor": "none", "axes.facecolor": "none", "savefig.facecolor": "none", "savefig.transparent": True,
        "text.color": t["ink"], "axes.labelcolor": t["ink"], "axes.edgecolor": t["ink"], "xtick.color": t["ink"], "ytick.color": t["ink"],
        "axes.linewidth": 0.7, "xtick.direction": "in", "ytick.direction": "in", "xtick.major.width": 0.7, "ytick.major.width": 0.7,
        "xtick.minor.width": 0.5, "ytick.minor.width": 0.5, "xtick.major.size": 4, "ytick.major.size": 4, "xtick.minor.size": 2.2, "ytick.minor.size": 2.2,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": False, "legend.frameon": False, "lines.solid_capstyle": "butt",
    })
    return t


def _save(fig, out, name, theme):
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"{name}-{theme}.svg")
    fig.savefig(path, format="svg", metadata={"Date": None, "Creator": None}, bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)
    return path


def _lane_marks(ax, t, curve=False):
    """The two lanes and the published period, for a legend; with their line style where a curve is drawn."""
    ax.plot([], [], "o", ms=5.6, mfc=t["ink"], mec=t["ink"], color=t["ink"], lw=1.2, ls="-" if curve else "none", label="VIP lane, 600 CU")
    ax.plot([], [], "o", ms=5.6, mfc=t["paper"], mec=t["ink"], mew=0.95, color=t["ink2"], lw=0.9, ls=(0, (4, 2)) if curve else "none", label="typical lane, 200,000 CU")
    ax.plot([], [], color=t["claim"], lw=1.6, label="the period the vendor publishes")


def shutter(cells, out):
    """Fig. 2: the shutter of every client with its 95% interval, in ms and on a camera's dial."""
    fams = _families(cells)
    if not fams:
        return []
    lo_axis, hi_axis = 0.1, 300.0
    dial = [8000, 4000, 2000, 1000, 500, 250, 125, 60, 30, 15, 8, 4]
    paths = []
    for theme in THEMES:
        t = _style(theme)
        fig, ax = plt.subplots(figsize=(8.6, 0.42 * len(fams) + 0.8))
        labelled = set()
        for i, fam in enumerate(fams):
            y = len(fams) - 1 - i
            if fam in CLAIMS:
                ax.plot([CLAIMS[fam]] * 2, [y - 0.36, y + 0.36], color=t["claim"], lw=1.6, zorder=2)
                if CLAIMS[fam] not in labelled:  # each published number named once, at its top row
                    labelled.add(CLAIMS[fam])
                    side = 1 if CLAIMS[fam] > 30 else -1  # the shorter number on the left of its mark, clear of the other
                    ax.annotate(f"published: {CLAIMS[fam]:.0f} ms", (CLAIMS[fam], y + 0.36), xytext=(4 * side, 0), textcoords="offset points", fontsize=10, color=t["claim"], ha="left" if side > 0 else "right", va="bottom")
            for lane, dy in (("VIP", 0.13), ("ECO", -0.13)):
                c = next((x for x in cells if x["family"] == fam and x["lane"] == lane), None)
                if not c or c.get("mu_ms") is None:
                    continue
                lo, hi = c["mu_ci"]["lo"], c["mu_ci"]["hi"]
                ax.plot([max(lo, lo_axis), min(hi, hi_axis)], [y + dy] * 2, color=t["ink"], lw=0.85, zorder=3)
                if lo <= lo_axis:  # below what the grid can measure; clear of the dot when the estimate sits there too
                    ax.plot([lo_axis * (0.9 if c["mu_ms"] <= lo_axis else 1.0)], [y + dy], marker="<", ms=3.6, color=t["ink"], clip_on=False, zorder=3)
                if hi >= hi_axis:
                    ax.plot([hi_axis], [y + dy], marker=">", ms=3.6, color=t["ink"], clip_on=False, zorder=3)
                ax.plot([max(c["mu_ms"], lo_axis)], [y + dy], "o", ms=5.6, mfc=t["ink"] if lane == "VIP" else t["paper"], mec=t["ink"], mew=0.95, zorder=4, clip_on=False)
        ax.set_yticks(range(len(fams)), list(reversed(fams)))
        ax.tick_params(axis="y", length=0, pad=13)
        ax.spines["left"].set_visible(False)
        ax.set_xscale("log")
        ax.set_xlim(lo_axis, hi_axis)
        ax.set_ylim(-0.6, len(fams) - 0.05)
        ax.set_xticks([0.1, 1, 10, 100], ["0.1", "1", "10", "100"])
        ax.set_xlabel(r"shutter $\mu$, ms, with its 95% interval (an arrow: below what I can measure)")
        ax.spines["bottom"].set_position(("outward", 6))
        top = ax.secondary_xaxis("top", functions=(lambda x: x, lambda x: x))
        top.set_xscale("log")
        top.set_xticks([1000 / n for n in dial], [str(n) for n in dial], fontsize=9.5)
        top.xaxis.set_minor_locator(NullLocator())
        top.tick_params(axis="x", direction="in", length=3.5, pad=2)
        top.spines["top"].set_position(("outward", 2))
        top.spines["top"].set_linewidth(0.7)
        top.set_xlabel(r"the same on a camera dial, $1/n$ s", fontsize=10.5, labelpad=5)
        _lane_marks(ax, t)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, fontsize=10.5, handlelength=1.3, columnspacing=1.8)
        paths.append(_save(fig, out, "fig2-shutter", theme))
    return paths


def curves(curve_rows, cells, out):
    """Fig. 4: P(B first | s) per client: the model's curve, and the counts with area growing with the pairs."""
    fams = _families(cells)
    if not fams:
        return []
    ncol = min(4, len(fams))
    nrow = math.ceil(len(fams) / ncol)
    paths = []
    for theme in THEMES:
        t = _style(theme)
        fig, axes = plt.subplots(nrow, ncol, figsize=(2.55 * ncol, 2.3 * nrow), sharex=True, sharey=True, squeeze=False, gridspec_kw={"wspace": 0.08, "hspace": 0.28})
        for i, fam in enumerate(fams):
            ax = axes[i // ncol][i % ncol]
            if fam in CLAIMS:
                ax.axvline(CLAIMS[fam], color=t["claim"], lw=1.1, zorder=1)
            for lane, face, ink, lw in (("ECO", t["paper"], t["ink2"], 0.9), ("VIP", t["ink"], t["ink"], 1.2)):
                pts = [r for r in curve_rows if r["family"] == fam and r["lane"] == lane and r["n"] > 0 and r["s_mid_ms"] > 0]
                c = next((x for x in cells if x["family"] == fam and x["lane"] == lane), None)
                if c and c.get("mu_ms"):
                    ss = np.exp(np.linspace(math.log(0.3), math.log(400), 240))
                    ax.plot(ss, models.p_ahead(ss, c["mu_ms"], c["k"], c["eps1"], c["eps2"]), color=ink, lw=lw, zorder=2, ls="-" if lane == "VIP" else (0, (4, 2)))
                ax.scatter([r["s_mid_ms"] for r in pts], [r["share"] for r in pts], s=[2.2 + 1.5 * r["n"] for r in pts], facecolors=face, edgecolors=ink, linewidths=0.7, zorder=3, clip_on=False)
            ax.set_xscale("log")
            ax.set_xlim(0.3, 400)
            ax.set_ylim(0, 1)
            ax.set_xticks([1, 10, 100], ["1", "10", "100"])
            ax.set_yticks([0, 0.5, 1], ["0", "50%", "100%"])
            ax.text(0.5, 1.03, fam, transform=ax.transAxes, ha="center", va="bottom", fontsize=11)
        for j in range(len(fams), nrow * ncol):
            axes[j // ncol][j % ncol].set_visible(False)
        fig.supxlabel(r"gap $s$ between the two sends, ms", fontsize=11.5, y=0.0)
        fig.supylabel(r"share of pairs: dearer $B$ lands first", fontsize=11.5, x=0.055)
        ax0 = axes[0][0]
        _lane_marks(ax0, t, curve=True)
        fig.legend(*ax0.get_legend_handles_labels(), loc="upper center", bbox_to_anchor=(0.5, -0.03), ncol=3, fontsize=10.5, handlelength=1.3, columnspacing=1.8)
        paths.append(_save(fig, out, "fig4-curves", theme))
    return paths


def two_verdicts(v, out):
    """Fig. 3: one validator, one square per pair: sent together, then sent apart. Both sessions."""
    if not v:
        return []
    rows = {}
    for r in v["bars"]:
        key = "sent together, $s$ = 0" if r["label"].startswith("s = 0") else "sent 35 to 70 ms apart"
        k, n = rows.get(key, (0, 0))
        rows[key] = (k + round(r["share"] * r["n"]), n + r["n"])
    paths = []
    for theme in THEMES:
        t = _style(theme)
        widest = max(n for _, n in rows.values())
        fig, ax = plt.subplots(figsize=(0.15 * widest + 3.4, 1.15))
        for i, (label, (k, n)) in enumerate(rows.items()):
            y = -1.75 * i
            for j in range(n):
                ax.add_patch(Rectangle((j, y), 0.8, 0.8, fc=t["ink"] if j < k else "none", ec=t["ink"], lw=0.7))
            ax.text(-0.9, y + 0.4, label, ha="right", va="center")
            ax.text(widest + 0.5, y + 0.4, f"{k} of {n}", ha="left", va="center")
            ax.text(widest + 5.2, y + 0.4, "by fee" if k > n / 2 else "by arrival", ha="left", va="center", family="cmti10")
        ax.set_xlim(0, widest + 12)
        ax.set_ylim(-1.75 * (len(rows) - 1) - 0.2, 1.0)
        ax.set_aspect("equal")
        ax.axis("off")
        paths.append(_save(fig, out, "fig3-two-verdicts", theme))
    return paths


def vip_lane(market_keys, probes, out):
    """Fig. 5: where the probes stand in the market: the share of mainnet transactions below each key."""
    if market_keys is None or len(market_keys) == 0:
        return []
    keys = np.clip(np.asarray(market_keys, float), 1, None)
    q = np.linspace(0, 1, 1201)
    x = np.quantile(keys, q)
    paths = []
    for theme in THEMES:
        t = _style(theme)
        fig, ax = plt.subplots(figsize=(7.4, 3.2))
        ax.plot(x, q * 100, color=t["ink"], lw=1.1, zorder=2, solid_joinstyle="round")
        for p in probes:
            ax.plot([p["key"]], [p["percentile"]], "o", ms=6.2, mfc=t["ink"] if p["lane"] == "VIP" else t["paper"], mec=t["ink"], mew=0.95, zorder=4, clip_on=False)
            at = (0, -12) if p["lane"] == "VIP" else (-8, 3)  # under the flat top, or in the free space left of the climb
            ax.annotate(f"${p['label'][-1]}$", (p["key"], p["percentile"]), xytext=at, textcoords="offset points", ha="center", va="center", fontsize=10.5)
        pct = {p["label"]: p["percentile"] for p in probes}
        for lane, name, xy, ha in (("VIP", "VIP lane, 600 CU", (2.6e5, 76.0), "left"), ("ECO", "typical lane, 200,000 CU", (4.2e4, 50.0), "left")):
            a, b = (next((v for k, v in pct.items() if k.startswith(lane) and k.endswith(end)), None) for end in ("A", "B"))
            if a is None or b is None:
                continue
            ax.text(*xy, f"{name}\n$A$ above {a:.0f}% of mainnet, $B$ above {b:.0f}%", ha=ha, va="center", fontsize=10.5, linespacing=1.3)
        ax.set_xscale("log")
        ax.set_xlim(1e3, 1e8)
        ax.set_ylim(0, 100)
        ax.set_yticks([0, 25, 50, 75, 100], ["0", "25%", "50%", "75%", "100%"])
        ax.set_xlabel(r"reward / cost, the scheduler's key")
        ax.set_ylabel("mainnet transactions below it")
        ax.spines["left"].set_position(("outward", 6))
        ax.spines["bottom"].set_position(("outward", 6))
        paths.append(_save(fig, out, "fig5-vip-lane", theme))
    return paths


def binned_curve(s, y, edges):
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (s >= lo) & (s < hi)
        n, k = int(m.sum()), int(y[m].sum())
        a, b = fit.wilson(k, n)
        rows.append({"s_lo_ms": lo, "s_hi_ms": hi, "s_mid_ms": float(np.median(s[m])) if n else (lo + hi) / 2, "n": n, "k": k,
                     "share": k / n if n else None, "lo": a, "hi": b})
    return rows
