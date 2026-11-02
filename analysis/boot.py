"""Cluster bootstrap by window (PLAN §8.2 step 3): pairs of one window share one clock and one
load, so windows, not pairs, are resampled."""
import numpy as np

from . import fit, hypotheses


def cell_ci(g, reps=200, seed=0, level=0.95):
    """Percentile interval of mu and k for one (family, lane) cell; `g` has s_ms, y, window_key."""
    rng = np.random.default_rng(seed)
    by_w = {w: (x["s_ms"].to_numpy(float), x["y"].to_numpy(float)) for w, x in g.groupby("window_key")}
    wins = list(by_w)
    mus, ks = [], []
    for _ in range(reps):
        pick = rng.choice(len(wins), len(wins), replace=True)
        s = np.concatenate([by_w[wins[i]][0] for i in pick])
        y = np.concatenate([by_w[wins[i]][1] for i in pick])
        f = fit.fit_cell(s, y)
        mus.append(f.mu[0])
        ks.append(f.k[0])
    a = (1 - level) / 2
    return {"reps": reps, "windows": len(wins), "mu_lo": float(np.quantile(mus, a)), "mu_hi": float(np.quantile(mus, 1 - a)),
            "k_lo": float(np.quantile(ks, a)), "k_hi": float(np.quantile(ks, 1 - a)), "mu_median": float(np.median(mus))}


def lane_ratio_ci(g_vip, g_eco, reps=200, seed=0, level=0.95):
    """Percentile interval of mu_ECO / mu_VIP, resampling windows jointly (both lanes of a window
    come and go together, so the within-window comparison is kept)."""
    rng = np.random.default_rng(seed)
    wins = sorted(set(g_vip["window_key"]) | set(g_eco["window_key"]))
    bv = {w: x for w, x in g_vip.groupby("window_key")}
    be = {w: x for w, x in g_eco.groupby("window_key")}
    ratios = []
    for _ in range(reps):
        pick = [wins[i] for i in rng.choice(len(wins), len(wins), replace=True)]
        v = [bv[w] for w in pick if w in bv]
        e = [be[w] for w in pick if w in be]
        if not v or not e:
            continue
        sv = np.concatenate([x["s_ms"].to_numpy(float) for x in v])
        yv = np.concatenate([x["y"].to_numpy(float) for x in v])
        se = np.concatenate([x["s_ms"].to_numpy(float) for x in e])
        ye = np.concatenate([x["y"].to_numpy(float) for x in e])
        r = hypotheses.lane_test((sv, yv), (se, ye))
        ratios.append(r["ratio"])
    a = (1 - level) / 2
    return {"reps": len(ratios), "ratio_lo": float(np.quantile(ratios, a)), "ratio_hi": float(np.quantile(ratios, 1 - a)),
            "ratio_median": float(np.median(ratios)), "share_above_1": float(np.mean(np.array(ratios) > 1))}
