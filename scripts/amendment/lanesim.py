"""Lane test under the frozen per-lane grids: false positives when the true curve is the same in
both lanes but is not a single gamma clock (two validators with different clocks pooled in one
family), and precision of mu when the pilot mu_hat was far off."""
import os, sys, math, time, json
import numpy as np
import concurrent.futures as cf
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from analysis import fit, hypotheses, models

BASE = [0, 1, 2, 3, 4, 6, 8, 10, 12, 15, 18, 21, 25, 30, 35, 40, 50, 60, 80, 100, 150]
REV = [-2, -5, -10, -20]
GRIDS = {  # frozen uniform upper ends (design/grids.json)
    "HarmonicFiredancer": {"VIP": 19.34, "ECO": 286.86},
    "JitoLabs": {"VIP": 113.54, "ECO": 300.0},
    "AgaveBam": {"VIP": 118.92, "ECO": 34.88},
    "Firedancer": {"VIP": 39.68, "ECO": 13.9},
    "HarmonicAgave": {"VIP": 60.0, "ECO": 54.46},
}

def draw_s(rng, hi, lane, n):
    pts = BASE + ([200, 300] if lane == "ECO" else [])
    u = rng.random(n) < 0.7
    return np.where(u, np.round(rng.uniform(0, hi, n), 1), rng.choice(pts, n)).astype(float)

def curve(name, s):
    s = np.asarray(s, float)
    if name == "metronome20":
        g = models.g_metronome(s, 20.0)
    elif name == "exp5":
        g = models.g_exponential(s, 5.0)
    elif name == "mix_exp2_met50":      # two validators: one on-demand 2 ms, one 50 ms rounds
        g = 0.5 * models.g_exponential(s, 2.0) + 0.5 * models.g_metronome(s, 50.0)
    elif name == "mix_exp3_met100":
        g = 0.5 * models.g_exponential(s, 3.0) + 0.5 * models.g_metronome(s, 100.0)
    elif name == "met20_tail":          # 20 ms rounds, 15% of A wait for a later round (~100 ms)
        g = 0.85 * models.g_metronome(s, 20.0) + 0.15 * models.g_exponential(s, 100.0)
    g = np.where(s <= 0, 1.0, g)
    return 0.03 + 0.92 * g

def one(args):
    fam, cname, n, seed, common = args
    rng = np.random.default_rng(seed)
    cells = {}
    for lane in ("VIP", "ECO"):
        hi = GRIDS[fam][lane] if not common else max(GRIDS[fam].values())
        s = np.concatenate([draw_s(rng, hi, "ECO" if common else lane, n), rng.choice(REV, 15).astype(float)])
        g = s + rng.normal(0, 0.3, len(s))
        y = (rng.random(len(s)) < curve(cname, g)).astype(float)
        cells[lane] = (s, y)
    r = hypotheses.lane_test(cells["VIP"], cells["ECO"], "two-sided")
    return r["mu_a_ms"], r["mu_b_ms"], r["p"], r["z"]

if __name__ == "__main__":
    reps = int(sys.argv[1])
    jobs = []
    plan = [("HarmonicFiredancer", c) for c in ("metronome20", "exp5", "mix_exp2_met50", "met20_tail")] + \
           [("AgaveBam", c) for c in ("mix_exp2_met50", "met20_tail")] + \
           [("JitoLabs", c) for c in ("exp5", "mix_exp3_met100")] + \
           [("Firedancer", c) for c in ("mix_exp2_met50",)]
    t0 = time.time()
    out = []
    with cf.ProcessPoolExecutor(int(sys.argv[2])) as ex:
        for common in (False, True):
            for fam, c in plan:
                if common and fam not in ("HarmonicFiredancer", "AgaveBam"):
                    continue
                res = list(ex.map(one, [(fam, c, 160, 1000 * i + 7, common) for i in range(reps)]))
                mv = np.array([r[0] for r in res]); me = np.array([r[1] for r in res]); p = np.array([r[2] for r in res]); z = np.array([r[3] for r in res])
                row = dict(fam=fam, curve=c, common_grid=common, reps=reps,
                           mu_vip_med=float(np.median(mv)), mu_eco_med=float(np.median(me)),
                           ratio_med=float(np.median(me / mv)),
                           reject_0056=float(np.mean(p < 0.05 / 9)), reject_05=float(np.mean(p < 0.05)),
                           eco_gt=float(np.mean(z > 0)))
                out.append(row)
                print(json.dumps(row), f"{time.time()-t0:.0f}s", flush=True)
