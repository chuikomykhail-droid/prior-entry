"""Figures of PLAN §9.4, each written twice: figures/<name>-light.svg and <name>-dark.svg.

One palette everywhere: the VIP lane is blue, the ECO lane orange (categorical slots 1 and 2 of
the reference palette, stepped separately for each surface); vendor claims are drawn in muted ink.
The SVGs are deterministic (fixed hash salt, no date), so `check` can compare them byte for byte.
"""
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from . import fit, models  # noqa: E402

THEMES = {
    "light": {"surface": "#fcfcfb", "text": "#0b0b0b", "text2": "#52514e", "muted": "#8a8984", "grid": "#e6e5e1",
              "VIP": "#2a78d6", "ECO": "#eb6834"},
    "dark": {"surface": "#1a1a19", "text": "#f0efec", "text2": "#c3c2b7", "muted": "#8f8e88", "grid": "#33332f",
             "VIP": "#3987e5", "ECO": "#d95926"},
}
LANE_LABEL = {"VIP": "VIP lane (600 CU)", "ECO": "ECO lane (200,000 CU)"}
CLAIMS = {"AgaveBam": 20.0, "FireBAM": 20.0, "HarmonicAgave": 50.0, "HarmonicFiredancer": 50.0}
CLAIM_LABEL = {20.0: "BAM: 20 ms", 50.0: "Harmonic: 50 ms"}


def _style(theme):
    t = THEMES[theme]
    plt.rcParams.update({
        "svg.hashsalt": "inside-the-block", "svg.fonttype": "none", "font.family": "DejaVu Sans", "font.size": 10,
        "figure.facecolor": t["surface"], "axes.facecolor": t["surface"], "savefig.facecolor": t["surface"],
        "text.color": t["text"], "axes.labelcolor": t["text2"], "xtick.color": t["text2"], "ytick.color": t["text2"],
        "axes.edgecolor": t["grid"], "grid.color": t["grid"], "grid.linewidth": 0.8, "axes.grid": True,
        "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 2, "legend.frameon": False,
    })
    return t


def _save(fig, out, name, theme):
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"{name}-{theme}.svg")
    fig.savefig(path, format="svg", metadata={"Date": None, "Creator": None}, bbox_inches="tight")
    plt.close(fig)
    return path


def shutter(cells, out):
    """Fig. 1: mu with its 95% interval per client; filled dot VIP, hollow dot ECO; claims ticked."""
    fams = sorted({c["family"] for c in cells}, key=lambda f: (f not in CLAIMS, f))
    if not fams:
        return []
    paths = []
    for theme in THEMES:
        t = _style(theme)
        fig, ax = plt.subplots(figsize=(7.2, 0.55 * len(fams) + 1.4))
        labelled, claimed = set(), set()
        for i, fam in enumerate(fams):
            yy = len(fams) - 1 - i
            for lane, dy in (("VIP", 0.12), ("ECO", -0.12)):
                c = next((x for x in cells if x["family"] == fam and x["lane"] == lane), None)
                if not c or c.get("mu_ms") is None:
                    continue
                lo, hi = c["mu_ci"]["lo"], min(c["mu_ci"]["hi"], 3000)
                ax.plot([lo, hi], [yy + dy, yy + dy], color=t[lane], lw=2, solid_capstyle="round")
                ax.plot([c["mu_ms"]], [yy + dy], "o", ms=8, color=t[lane], mfc=t[lane] if lane == "VIP" else t["surface"],
                        mew=2, label=None if lane in labelled else LANE_LABEL[lane])
                labelled.add(lane)
            if fam in CLAIMS:
                ax.plot([CLAIMS[fam]] * 2, [yy - 0.35, yy + 0.35], color=t["muted"], lw=1.5, ls=(0, (2, 2)))
                if CLAIMS[fam] not in claimed:  # label each claim once, at its top row
                    claimed.add(CLAIMS[fam])
                    ax.annotate(CLAIM_LABEL[CLAIMS[fam]], (CLAIMS[fam], yy + 0.36), xytext=(4, 0), textcoords="offset points",
                                color=t["text2"], fontsize=8, ha="left", va="bottom")
        ax.set_yticks(range(len(fams)), list(reversed(fams)))
        ax.set_xscale("log")
        ax.set_xlabel("shutter speed mu, ms (log scale): the mean batch interval, with 95% interval")
        ax.grid(axis="y", visible=False)
        ax.set_ylim(-0.7, len(fams) - 0.3)
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, fontsize=9, borderaxespad=0.2)
        ax.set_title("Shutter speed by client and lane", loc="left", fontsize=12, color=t["text"], pad=26)
        paths.append(_save(fig, out, "fig1-shutter", theme))
    return paths


def curves(curve_rows, cells, out):
    """Fig. 2: P(B ahead | s) per client, binned points with Wilson intervals, model curves."""
    fams = sorted({c["family"] for c in cells}, key=lambda f: (f not in CLAIMS, f))
    if not fams:
        return []
    paths = []
    ncol = min(3, len(fams))
    nrow = math.ceil(len(fams) / ncol)
    for theme in THEMES:
        t = _style(theme)
        fig, axes = plt.subplots(nrow, ncol, figsize=(3.4 * ncol, 2.7 * nrow), squeeze=False, sharey=True)
        for i, fam in enumerate(fams):
            ax = axes[i // ncol][i % ncol]
            for lane in ("VIP", "ECO"):
                pts = [r for r in curve_rows if r["family"] == fam and r["lane"] == lane and r["n"] > 0 and r["s_mid_ms"] > 0]
                if pts:
                    x = [r["s_mid_ms"] for r in pts]
                    ax.errorbar(x, [r["share"] for r in pts], yerr=[[max(0.0, r["share"] - r["lo"]) for r in pts], [max(0.0, r["hi"] - r["share"]) for r in pts]],
                                fmt="o", ms=4, color=t[lane], ecolor=t[lane], elinewidth=1, capsize=0, alpha=0.9)
                c = next((x for x in cells if x["family"] == fam and x["lane"] == lane), None)
                if c and c.get("mu_ms"):
                    ss = np.exp(np.linspace(math.log(0.3), math.log(400), 200))
                    ax.plot(ss, models.p_ahead(ss, c["mu_ms"], c["k"], c["eps1"], c["eps2"]), color=t[lane], lw=2,
                            label=LANE_LABEL[lane] if i == 0 else None)
            if fam in CLAIMS:
                ax.axvline(CLAIMS[fam], color=t["muted"], lw=1.2, ls=(0, (2, 2)))
            ax.set_xscale("log")
            ax.set_ylim(-0.03, 1.03)
            ax.set_title(fam, loc="left", fontsize=10, color=t["text"])
            if i % ncol == 0:
                ax.set_ylabel("share with B ahead")
            if i // ncol == nrow - 1:
                ax.set_xlabel("B sent s ms after A (log)")
        for j in range(len(fams), nrow * ncol):
            axes[j // ncol][j % ncol].set_visible(False)
        fig.legend(loc="upper right", fontsize=9)
        fig.suptitle("Fee wins inside the shutter, arrival outside it", x=0.01, ha="left", fontsize=12, color=t["text"])
        fig.tight_layout()
        paths.append(_save(fig, out, "fig2-curves", theme))
    return paths


def two_verdicts(v, out):
    """Fig. 3: one validator, the same pair design, opposite verdicts depending on s and lane."""
    if not v:
        return []
    paths = []
    for theme in THEMES:
        t = _style(theme)
        fig, ax = plt.subplots(figsize=(6.4, 2.8))
        for i, r in enumerate(v["bars"]):
            col = t[r["lane"]]
            ax.plot([r["lo"], r["hi"]], [i, i], color=col, lw=2)
            ax.plot([r["share"]], [i], "o", ms=9, color=col, mfc=col if r["lane"] == "VIP" else t["surface"], mew=2)
            ax.annotate(f"{r['share'] * 100:.0f}%  (n = {r['n']})", (r["hi"], i), xytext=(6, 0), textcoords="offset points",
                        va="center", fontsize=9, color=t["text2"])
        ax.set_yticks(range(len(v["bars"])), [r["label"] for r in v["bars"]])
        ax.axvline(0.5, color=t["muted"], lw=1, ls=(0, (2, 2)))
        ax.set_xlim(0, 1.15)
        ax.set_xlabel("share of pairs where the dearer B lands ahead of A")
        ax.invert_yaxis()
        ax.grid(axis="y", visible=False)
        ax.set_title(f"One validator, two verdicts: {v['validator'][:8]} ({v['family']})", loc="left", fontsize=11, color=t["text"])
        paths.append(_save(fig, out, "fig3-two-verdicts", theme))
    return paths


def vip_lane(market_keys, probes, out):
    """Fig. 4: the scheduler key across mainnet transactions, with our probes marked."""
    if market_keys is None or len(market_keys) == 0:
        return []
    paths = []
    keys = np.log10(np.clip(np.asarray(market_keys, float), 1, None))
    for theme in THEMES:
        t = _style(theme)
        fig, ax = plt.subplots(figsize=(7.2, 2.9))
        ax.hist(keys, bins=80, color=t["muted"], alpha=0.55, edgecolor=t["surface"], linewidth=0.5)
        top = ax.get_ylim()[1]
        for j, p in enumerate(probes):
            x = math.log10(p["key"])
            col = t[p["lane"]]
            ax.axvline(x, color=col, lw=2)
            ax.annotate(f"{p['label']}\n{p['percentile']:.0f}th pct", (x, top * (0.95 - 0.22 * (j % 2))), xytext=(4, 0),
                        textcoords="offset points", fontsize=8, color=t["text2"], va="top")
        ax.set_xlabel("reward / cost, the scheduler's key (log10)")
        ax.set_ylabel("transactions")
        ax.grid(axis="x", visible=False)
        ax.set_title("The VIP lane: a tiny probe outranks almost all of mainnet", loc="left", fontsize=12, color=t["text"])
        paths.append(_save(fig, out, "fig4-vip-lane", theme))
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
