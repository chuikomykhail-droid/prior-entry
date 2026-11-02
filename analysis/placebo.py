"""Placebos (PLAN §8.2 step 10): the pipeline run on data where the answer is known to be "no".

  shuffle s     s permuted within (family, lane): the curve must come out flat ("no clock")
  shuffle lane  lanes permuted within each window: lane-test p-values must be uniform
  lexicographic a rule that cannot exist (B ahead when its signature sorts first): ~50%
"""
import numpy as np
from scipy import stats

from . import fit, hypotheses


def shuffle_s(g, reps=100, seed=0, alpha=0.05):
    """Share of shuffles in which "a rule exists" (gamma beats constant at alpha)."""
    rng = np.random.default_rng(seed)
    s, y = g["s_ms"].to_numpy(float), g["y"].to_numpy(float)
    hits = 0
    for _ in range(reps):
        sp = rng.permutation(s)
        d = 2 * (fit.fit_cell(sp, y).loglik - fit.fit_cell(sp, y, "constant").loglik)
        hits += stats.chi2.sf(max(d, 0), 3) < alpha
    return {"reps": reps, "false_rule_rate": hits / reps}


def shuffle_lanes(g, reps=100, seed=0):
    """Lane-test p-values with lanes permuted within windows; returns them and a KS test against
    the uniform distribution."""
    rng = np.random.default_rng(seed)
    g = g[g["series"].isin(["FEE", "REV"])]
    ps = []
    for _ in range(reps):
        lanes = g.groupby("window_key")["lane"].transform(lambda x: rng.permutation(x.to_numpy()))
        v, e = g[lanes == "VIP"], g[lanes == "ECO"]
        if len(v) < 20 or len(e) < 20:
            continue
        r = hypotheses.lane_test((v["s_ms"].to_numpy(float), v["y"].to_numpy(float)), (e["s_ms"].to_numpy(float), e["y"].to_numpy(float)))
        ps.append(r["p"])
    ks = stats.kstest(ps, "uniform") if len(ps) >= 5 else None
    return {"reps": len(ps), "p_values": ps, "share_below_0.05": float(np.mean(np.array(ps) < 0.05)) if ps else None,
            "ks_p": float(ks.pvalue) if ks else None}


def lexicographic(df):
    """Agreement of B-ahead with "B's signature sorts first"."""
    d = df[df["complete"] & df["y_lex"].notna()] if len(df) else df
    if not len(d):
        return {"n": 0}
    agree = int((d["y"] == d["y_lex"]).sum())
    lo, hi = fit.wilson(agree, len(d))
    return {"n": int(len(d)), "agree": agree, "share": agree / len(d), "ci": [lo, hi]}
