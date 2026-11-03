"""Lane test calibration with the late part of the grid: a 20 ms metronome shared by both lanes
(AgaveBam in the synthetic check), the main-run grid with and without the late part [30, 150] ms.
Usage: python latecal.py <reps> <workers>"""
import os, sys, json
import numpy as np
import concurrent.futures as cf
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from analysis import hypotheses

BASE = [0, 1, 2, 3, 4, 6, 8, 10, 12, 15, 18, 21, 25, 30, 35, 40, 50, 60, 80, 100, 150]


def draw(rng, late, n, lane):
    pts = BASE + ([200, 300] if lane == "ECO" else [])
    out = []
    for _ in range(n):
        u = rng.random()
        if u < 0.1:
            continue  # simultaneous: out of the clock fits
        if late and u < 0.25:
            out.append(round(rng.uniform(30, 150), 1))
        elif rng.random() < 0.7:
            out.append(round(rng.uniform(0, 40), 1))
        else:
            out.append(float(rng.choice(pts)))
    return np.array(out)


def one(args):
    late, seed = args
    rng = np.random.default_rng(seed)
    cells = {}
    for lane in ("VIP", "ECO"):
        s = np.concatenate([draw(rng, late, 165, lane), rng.choice([-2, -5, -10, -20], 20).astype(float)])
        gap = s + rng.normal(0, 0.12, len(s)) + rng.normal(0, 0.3, len(s))
        g = np.where(gap <= 0, 1.0, np.clip(1 - gap / 20.0, 0, 1))
        u = rng.random(len(s))
        y = np.where(u < 0.03, 1, np.where(u < 0.08, 0, (rng.random(len(s)) < g).astype(int))).astype(float)
        cells[lane] = (s, y)
    return hypotheses.lane_test(cells["VIP"], cells["ECO"], "greater")["p"]


if __name__ == "__main__":
    reps, workers = int(sys.argv[1]), int(sys.argv[2])
    with cf.ProcessPoolExecutor(workers) as ex:
        for late in (False, True):
            p = np.array(list(ex.map(one, [(late, 5000 + i) for i in range(reps)])))
            print(json.dumps({"late_part": late, "reps": reps, "reject_p<0.0056": float(np.mean(p < 0.05 / 9)),
                              "reject_p<0.05": float(np.mean(p < 0.05)), "p_median": round(float(np.median(p)), 3)}), flush=True)
