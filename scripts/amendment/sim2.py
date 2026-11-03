"""One scenario, sequential: python sim2.py <mode> <family> <curve> <common> <reps> <seed>
mode lane : lane test (two-sided) with the same true curve in both lanes, frozen per-lane grids
mode claim: vendor-claim test on VIP with a free-running metronome plus forced cuts at slot boundaries"""
import os, sys, json, time
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from analysis import hypotheses, models

BASE = [0, 1, 2, 3, 4, 6, 8, 10, 12, 15, 18, 21, 25, 30, 35, 40, 50, 60, 80, 100, 150]
REV = [-2, -5, -10, -20]
GRIDS = {"HarmonicFiredancer": {"VIP": 19.34, "ECO": 286.86}, "JitoLabs": {"VIP": 113.54, "ECO": 300.0},
         "AgaveBam": {"VIP": 118.92, "ECO": 34.88}, "Firedancer": {"VIP": 39.68, "ECO": 13.9},
         "HarmonicAgave": {"VIP": 60.0, "ECO": 54.46}}
SLOT = 213.0

def draw_s(rng, hi, lane, n):
    pts = BASE + ([200, 300] if lane == "ECO" else [])
    u = rng.random(n) < 0.7
    return np.where(u, np.round(rng.uniform(0, hi, n), 1), rng.choice(pts, n)).astype(float)

def g_true(name, s):
    s = np.asarray(s, float)
    g = {"metronome20": lambda: models.g_metronome(s, 20.0),
         "exp5": lambda: models.g_exponential(s, 5.0),
         "mix_exp2_met50": lambda: 0.5 * models.g_exponential(s, 2.0) + 0.5 * models.g_metronome(s, 50.0),
         "mix_exp3_met100": lambda: 0.5 * models.g_exponential(s, 3.0) + 0.5 * models.g_metronome(s, 100.0),
         "met20_tail": lambda: 0.85 * models.g_metronome(s, 20.0) + 0.15 * models.g_exponential(s, 100.0),
         "fifo50_exp5": lambda: 0.5 * models.g_exponential(s, 5.0)}[name]()
    return np.where(s <= 0, 1.0, g)

def lane_rep(rng, fam, curve, common):
    cells = {}
    for lane in ("VIP", "ECO"):
        hi = max(GRIDS[fam].values()) if common else GRIDS[fam][lane]
        s = np.concatenate([draw_s(rng, hi, "ECO" if common else lane, 160), rng.choice(REV, 15).astype(float)])
        p = 0.03 + 0.92 * g_true(curve, s + rng.normal(0, 0.02 if curve.startswith("fifo") else 0.3, len(s)))
        cells[lane] = (s, (rng.random(len(s)) < p).astype(float))
    r = hypotheses.lane_test(cells["VIP"], cells["ECO"], "two-sided")
    return {"mu_vip": r["mu_a_ms"], "mu_eco": r["mu_b_ms"], "p": r["p"], "z": r["z"], "k": r["k_shared"]}

def claim_rep(rng, fam, period, slotcuts):
    s = np.concatenate([draw_s(rng, GRIDS[fam]["VIP"], "VIP", 160), rng.choice(REV, 15).astype(float)])
    a = rng.uniform(0, 4 * SLOT, len(s))          # A's arrival, uniform over the window
    b = a + s + rng.normal(0, 0.3, len(s))
    phase0 = rng.uniform(0, period, len(s))       # free-running clock, random phase per pair
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    clock_cut = np.floor((hi - phase0) / period) > np.floor((lo - phase0) / period)
    slot_cut = np.floor(hi / SLOT) > np.floor(lo / SLOT) if slotcuts else np.zeros(len(s), bool)
    behind_a = (b > a) & (clock_cut | slot_cut)
    u = rng.random(len(s))
    y = np.where(u < 0.03, 1, np.where(u < 0.08, 0, (~behind_a).astype(int))).astype(float)
    r = hypotheses.claim_test(s, y, period)
    return {"mu": r["mu_hat_ms"], "p": r["p"]}

if __name__ == "__main__":
    mode, fam, curve, common, reps, seed = sys.argv[1:7]
    rng = np.random.default_rng(int(seed))
    t0 = time.time()
    res = []
    for i in range(int(reps)):
        res.append(lane_rep(rng, fam, curve, common == "1") if mode == "lane" else claim_rep(rng, fam, float(curve), common == "1"))
    if mode == "lane":
        mv = np.array([r["mu_vip"] for r in res]); me = np.array([r["mu_eco"] for r in res]); p = np.array([r["p"] for r in res])
        row = {"mode": mode, "fam": fam, "curve": curve, "common_grid": common == "1", "reps": len(res),
               "mu_vip_med": round(float(np.median(mv)), 2), "mu_eco_med": round(float(np.median(me)), 2),
               "ratio_med": round(float(np.median(me / mv)), 2), "reject_p<0.0056": float(np.mean(p < 0.05 / 9)),
               "reject_p<0.05": float(np.mean(p < 0.05)), "k_med": round(float(np.median([r["k"] for r in res])), 2)}
    else:
        mu = np.array([r["mu"] for r in res]); p = np.array([r["p"] for r in res])
        row = {"mode": mode, "fam": fam, "period": float(curve), "slot_cuts": common == "1", "reps": len(res),
               "mu_med": round(float(np.median(mu)), 2), "mu_q10_q90": [round(float(np.quantile(mu, 0.1)), 1), round(float(np.quantile(mu, 0.9)), 1)],
               "reject_p<0.0056": float(np.mean(p < 0.05 / 9)), "reject_p<0.05": float(np.mean(p < 0.05))}
    row["sec"] = round(time.time() - t0)
    print(json.dumps(row), flush=True)
