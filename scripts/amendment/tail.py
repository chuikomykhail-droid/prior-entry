"""Vendor-claim test when a share of pairs overtakes long after the claimed round:
true curve (1 - w) * metronome(20) + w * exponential(100), AgaveBam frozen VIP grid.
Usage: python tail.py <w> <seed> <reps>"""
import os, sys, json, time
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analysis import fit, hypotheses
import sim2
rng = np.random.default_rng(int(sys.argv[2]))
w = float(sys.argv[1])
rows = []
for _ in range(int(sys.argv[3])):
    s = np.concatenate([sim2.draw_s(rng, sim2.GRIDS["AgaveBam"]["VIP"], "VIP", 160), rng.choice(sim2.REV, 15).astype(float)])
    g = s + rng.normal(0, 0.3, len(s))
    from analysis import models
    G = (1 - w) * models.g_metronome(g, 20.0) + w * models.g_exponential(g, 100.0)
    G = np.where(g <= 0, 1.0, G)
    y = (rng.random(len(s)) < 0.03 + 0.92 * G).astype(float)
    best = fit.fit_cell(s, y)
    r = hypotheses.claim_test(s, y, 20.0, best=best)
    far = (s >= 40) & (s <= 150)
    rows.append((best.mu[0], best.eps1[0], r["p"], y[far].mean() if far.any() else np.nan))
a = np.array(rows)
print(json.dumps({"tail_share": w, "reps": len(a), "mu_med": round(float(np.median(a[:, 0])), 1),
                  "eps1_med": round(float(np.median(a[:, 1])), 3), "V1_reject_p<0.05": float(np.mean(a[:, 2] < 0.05)),
                  "share_B_ahead_s40_150": round(float(np.nanmedian(a[:, 3])), 3)}), flush=True)
