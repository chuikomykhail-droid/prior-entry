"""Simulation of the method (PLAN §5.9, extended): pairs sent into windows of a leader whose
clock or queue we choose, then the same fits and tests as on real data.

Mechanisms:
  clock       one renewal process per window and lane (gamma intervals, random phase); with
              equal lane parameters the two lanes share one process ("pure clock")
  slotclock   a metronome that restarts at every slot boundary (phase tied to the slot)
  queue       an independent wait per pair, gamma with lane-specific mean (no shared clock)

Extras: lapses eps1/eps2, blur of the arrival gap, landing losses, and a window-level random
effect on mu (clusters). `python -m analysis sim` writes docs/POWER.md.
"""
import math
import time
from dataclasses import dataclass, field

import numpy as np

from . import fit, hypotheses

SLOT_MS = 200.0
BASE_GRID = [0, 1, 2, 3, 4, 6, 8, 10, 12, 15, 18, 21, 25, 30, 35, 40, 50, 60, 80, 100, 150]
REV_GRID = [-2, -5, -10, -20]


@dataclass
class Scenario:
    name: str
    mechanism: str = "clock"          # clock | slotclock | queue
    mu: dict = field(default_factory=lambda: {"VIP": 20.0, "ECO": 20.0})
    k: dict = field(default_factory=lambda: {"VIP": 200.0, "ECO": 200.0})
    eps1: float = 0.03
    eps2: float = 0.05
    sigma: float = 0.3                # ms, blur of the actual arrival gap
    land: dict = field(default_factory=lambda: {"VIP": 1.0, "ECO": 1.0})
    tau: float = 0.0                  # sd of log mu across windows
    mu_hat: dict = None               # pilot estimate the grid is built from (default: true mu)


def grid_draw(rng, mu_hat, lane, n):
    """FEE gaps by the rule of §6.5: 70% uniform in [0, clamp(2 mu_hat, 10, 300)], 30% base grid."""
    hi = min(max(2 * mu_hat, 10.0), 300.0)
    pts = BASE_GRID + ([200, 300] if lane == "ECO" else [])
    u = rng.random(n) < 0.7
    return np.where(u, np.round(rng.uniform(0, hi, n), 1), rng.choice(pts, n)).astype(float)


def _boundaries(rng, mu, k, t0, t1):
    """Points of a stationary gamma renewal process on [t0, t1] (random phase: burn-in)."""
    th = mu / k
    t = t0 - 20 * mu - rng.uniform(0, mu)
    pts = []
    while t < t1:
        t += rng.gamma(k, th)
        if t >= t0:
            pts.append(t)
    return np.array(pts)


def simulate(sc: Scenario, n_per_lane, rev_per_lane=15, rng=None, pairs_per_window=4):
    """Pairs of one family: dict with s, y, lane, window, a_ms (A's offset in the window),
    landed (bool). FEE pairs per window are split evenly between the lanes."""
    rng = rng or np.random.default_rng()
    mu_hat = sc.mu_hat or sc.mu
    cells = []
    for lane in ("VIP", "ECO"):
        cells += [(lane, s) for s in grid_draw(rng, mu_hat[lane], lane, n_per_lane)]
        cells += [(lane, float(s)) for s in rng.choice(REV_GRID, rev_per_lane)]
    order = rng.permutation(len(cells))
    out = {k: [] for k in ("s", "y", "lane", "window", "a_ms", "landed")}
    for w0 in range(0, len(order), pairs_per_window):
        w = w0 // pairs_per_window
        effect = math.exp(rng.normal(0, sc.tau)) if sc.tau > 0 else 1.0
        procs = {}
        for i in order[w0:w0 + pairs_per_window]:
            lane, s = cells[i]
            a = rng.uniform(120 + max(0, -s), 650 - max(0, s))
            gap = s + rng.normal(0, sc.sigma)
            mu, k = sc.mu[lane] * effect, sc.k[lane]
            if sc.mechanism == "queue":
                behind = rng.gamma(k, mu / k) > gap
            else:
                key = "shared" if (sc.mu["VIP"] == sc.mu["ECO"] and sc.k["VIP"] == sc.k["ECO"]) else lane
                if key not in procs:
                    if sc.mechanism == "slotclock":
                        pts = [slot + j * mu for slot in np.arange(0, 1000, SLOT_MS) for j in range(int(SLOT_MS // mu) + 1)
                               if j * mu < SLOT_MS]
                        procs[key] = np.array(sorted(pts))
                    else:
                        procs[key] = _boundaries(rng, mu, k, 0.0, 1000.0)
                b = procs[key]
                lo, hi = (a, a + gap) if gap >= 0 else (a + gap, a)
                between = np.any((b > lo) & (b <= hi))
                behind = (not between) if gap >= 0 else True
            u = rng.random()
            y = 1 if u < sc.eps1 else 0 if u < sc.eps1 + sc.eps2 else int(behind)
            out["s"].append(s)
            out["y"].append(y)
            out["lane"].append(lane)
            out["window"].append(w)
            out["a_ms"].append(a)
            out["landed"].append(rng.random() < sc.land[lane])
    return {k: np.asarray(v) for k, v in out.items()}


def one_rep(sc, n, rng):
    d = simulate(sc, n, rng=rng)
    m = d["landed"]
    cells = {lane: (d["s"][m & (d["lane"] == lane)], d["y"][m & (d["lane"] == lane)]) for lane in ("VIP", "ECO")}
    vip = fit.fit_cell(*cells["VIP"])
    # coverage of the 95% profile interval at the true mu (LR at the truth)
    th = vip.extra["theta"][1:]
    at_truth = fit.fit_groups([cells["VIP"]], fixed_mu=sc.mu["VIP"], starts=[th])
    covered = 2 * (vip.loglik - at_truth.loglik) <= fit.CHI2_95
    lane = hypotheses.lane_test(cells["VIP"], cells["ECO"], "greater", single_vip=vip)
    return {"mu_vip": vip.mu[0], "k_vip": vip.k[0], "covered": covered, "lane_p": lane["p"], "ratio": lane["ratio"],
            "n_vip": len(cells["VIP"][1]), "n_eco": len(cells["ECO"][1])}


SCENARIOS = [
    # the draft of §5.9
    Scenario("Metronome 20 ms, lanes equal", mu={"VIP": 20, "ECO": 20}),
    Scenario("Metronome 50 ms, lanes equal", mu={"VIP": 50, "ECO": 50}),
    Scenario("Metronome 20 -> 30 ms (x1.5)", mu={"VIP": 20, "ECO": 30}),
    Scenario("Queue, exponential 3 -> 6 ms (x2)", "queue", {"VIP": 3, "ECO": 6}, {"VIP": 1, "ECO": 1}),
    Scenario("Queue, exponential 10 -> 20 ms (x2)", "queue", {"VIP": 10, "ECO": 20}, {"VIP": 1, "ECO": 1}),
    Scenario("Queue, exponential 3 -> 9 ms (x3)", "queue", {"VIP": 3, "ECO": 9}, {"VIP": 1, "ECO": 1}),
    Scenario("Null: exponential 5 -> 5 ms", "queue", {"VIP": 5, "ECO": 5}, {"VIP": 1, "ECO": 1}),
    # extensions
    Scenario("Gamma k=4, 30 ms, lanes equal", mu={"VIP": 30, "ECO": 30}, k={"VIP": 4, "ECO": 4}),
    Scenario("Slot-locked metronome 25 ms", "slotclock", {"VIP": 25, "ECO": 25}),
    Scenario("Slot-locked metronome 30 ms (200/30 not whole)", "slotclock", {"VIP": 30, "ECO": 30}),
    Scenario("Metronome 20 ms, 35% ECO losses", mu={"VIP": 20, "ECO": 20}, land={"VIP": 0.85, "ECO": 0.65}),
    Scenario("Clock 20 ms, window effect sd(log mu)=0.3", mu={"VIP": 20, "ECO": 20}, tau=0.3),
    Scenario("Queue 10 -> 20 ms, window effect 0.3", "queue", {"VIP": 10, "ECO": 20}, {"VIP": 1, "ECO": 1}, tau=0.3),
    Scenario("Metronome 20 ms, pilot mu_hat off x2", mu={"VIP": 20, "ECO": 20}, mu_hat={"VIP": 40, "ECO": 40}),
]


def _worker(args):
    sc, n, seed = args
    return one_rep(sc, n, np.random.default_rng(seed))


def power(scenarios=None, reps=300, alpha=0.05 / 8, seed=2026, workers=None):
    """The draft scenarios at n = 120 / 160 / 200 FEE pairs per lane, the extensions at 160."""
    import concurrent.futures as cf
    import os
    scenarios = scenarios or SCENARIOS
    rows = []
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    with cf.ProcessPoolExecutor(workers) as ex:
        for si, sc in enumerate(scenarios):
            for n in ((120, 160, 200) if si < 7 else (160,)):
                t = time.time()
                jobs = [(sc, n, seed * 1_000_003 + si * 10_007 + n * 101 + r) for r in range(reps)]
                res = list(ex.map(_worker, jobs, chunksize=1))
                mu = np.array([r["mu_vip"] for r in res])
                rows.append({"scenario": sc.name, "mechanism": sc.mechanism, "mu_vip": sc.mu["VIP"], "mu_eco": sc.mu["ECO"],
                             "n_per_lane": n, "reps": reps, "mu_hat_mean": float(np.mean(mu)), "mu_hat_sd": float(np.std(mu)),
                             "mu_hat_median": float(np.median(mu)),
                             "coverage": float(np.mean([r["covered"] for r in res])),
                             "lane_reject": float(np.mean([r["lane_p"] < alpha for r in res])),
                             "seconds": time.time() - t})
                print(f"{sc.name:<48} n={n:<4} mu {rows[-1]['mu_hat_mean']:7.2f} +- {rows[-1]['mu_hat_sd']:5.2f}  "
                      f"cover {rows[-1]['coverage']:.2f}  lane reject {rows[-1]['lane_reject']:.2f}  ({rows[-1]['seconds']:.0f} s)",
                      flush=True)
    return rows


def power_markdown(rows, reps, alpha):
    lines = ["| Scenario | n per lane | mu_VIP true | mu_VIP estimate, mean +- sd | 95% interval covers truth | Lane test rejects |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['scenario']} | {r['n_per_lane']} | {r['mu_vip']:g} | {r['mu_hat_mean']:.1f} +- {r['mu_hat_sd']:.1f} | "
                     f"{r['coverage']:.2f} | {r['lane_reject']:.2f} |")
    return "\n".join(lines)


def conclusions(rows):
    """The design read-outs, computed from the rows (so a rerun rewrites them too)."""
    def r(name, n=160):
        return next(x for x in rows if x["scenario"] == name and x["n_per_lane"] == n)

    def rej(name):
        return " / ".join(f"{r(name, n)['lane_reject']:.2f}" for n in (120, 160, 200))
    nulls = [x for x in rows if x["mu_vip"] == x["mu_eco"]]
    fp = max(x["lane_reject"] for x in nulls)
    cov = [x["coverage"] for x in rows]
    m20 = r("Metronome 20 ms, lanes equal")
    return f"""- **Precision of mu.** A 20 ms metronome is recovered as {m20['mu_hat_mean']:.1f} +- {m20['mu_hat_sd']:.1f} ms with 160
  pairs per lane; a 50 ms one as {r('Metronome 50 ms, lanes equal')['mu_hat_mean']:.1f} +- {r('Metronome 50 ms, lanes equal')['mu_hat_sd']:.1f} ms (metronomes come out a few per cent low:
  the lapse floor absorbs part of the straight edge).
  Fast "on demand" clocks are resolved only roughly: an exponential with mu = 3 ms comes out as
  {r('Queue, exponential 3 -> 6 ms (x2)')['mu_hat_mean']:.1f} +- {r('Queue, exponential 3 -> 6 ms (x2)')['mu_hat_sd']:.1f} ms. A clock between the extremes (gamma k = 4, 30 ms) widens the spread to
  +- {r('Gamma k=4, 30 ms, lanes equal')['mu_hat_sd']:.1f} ms; k itself is weakly identified against the lapse rates, so mu is the number we lead with.
- **Intervals.** The 95% profile interval covers the true mu in {min(cov):.2f}-{max(cov):.2f} of replicates across all rows.
  The lowest coverage is the slot-locked 30 ms metronome ({r('Slot-locked metronome 30 ms (200/30 not whole)')['coverage']:.2f}), where batches restart at
  slot boundaries and the stationary model is only approximate: the reason the phase of every pair is recorded
  and the "first 30 ms of the slot" split is run.
- **False positives of the lane test** stay at or below {fp:.2f} in every row with equal lanes (nominal {0.05 / 8:.4f}),
  including window effects, unequal losses and a pilot estimate off by a factor of two.
- **Power of the lane test** at n = 120 / 160 / 200: a x2 queue at 3 ms {rej('Queue, exponential 3 -> 6 ms (x2)')}; at 10 ms
  {rej('Queue, exponential 10 -> 20 ms (x2)')}; a x1.5 metronome {rej('Metronome 20 -> 30 ms (x1.5)')}; a x3 queue {rej('Queue, exponential 3 -> 9 ms (x3)')}.
  160 FEE pairs per lane in the main families buy ~0.8 power for a doubling and certainty for a tripling;
  a x1.5 shift of a clock is caught about two times in three.
- **Robustness.** Window effects (sd of log mu 0.3 between windows) leave the queue power at
  {r('Queue 10 -> 20 ms, window effect 0.3')['lane_reject']:.2f}; 35% ECO losses and a pilot estimate off by x2 change neither the bias nor the error rate materially."""


def write_power_md(path, rows, reps, alpha, seconds):
    """docs/POWER.md: the tables, the settings and what they mean for the design."""
    draft = [r for r in rows if r["scenario"] in {sc.name for sc in SCENARIOS[:7]}]
    ext = [r for r in rows if r not in draft]
    text = f"""# Power of the design: simulation

Generated by `python -m analysis sim` ({reps} replicates per row, {seconds / 60:.0f} min). The simulator
(`analysis/sim.py`) sends pairs into leader windows exactly as `itb` plans them: 4 pairs per window, FEE
pairs split evenly between the VIP and ECO lanes, A at a random moment in [+120, +650 - s] ms, s drawn by
the grid rule frozen before the post-pilot amendment (70% uniform in [0, 2 mu_hat], 30% the base grid; ECO adds
200 and 300 ms; the amended rule of PREREGISTRATION §3 also sends 10% of FEE pairs at s = 0, kept out of the
clock fits, and, for the families with a published period T, 15% in [1.5 T, 150] ms),
15 REV pairs per lane with s in {{-2, -5, -10, -20}} ms. Then it fits and tests exactly as the analysis does.

Fixed everywhere unless the row says otherwise: floor eps1 = 0.03, ceiling eps2 = 0.05, blur of the actual
gap sigma = 0.3 ms, every pair lands, the pilot estimate mu_hat equals the truth.

- **mu_VIP estimate**: maximum likelihood, gamma model with free k, eps1, eps2.
- **Interval covers truth**: share of replicates whose 95% profile-likelihood interval contains the true mu.
- **Lane test rejects**: share of replicates where the one-sided test mu_ECO > mu_VIP (signed-root
  likelihood ratio, k and lapse rates shared across lanes) rejects at alpha = {alpha:.5f} (0.05 / 8, Bonferroni
  over the lane and claim tests; Holm is uniformly more powerful). In rows where the lanes are equal this is the
  false-positive rate.

## The scenarios of the plan (PLAN §5.9)

{power_markdown(draft, reps, alpha)}

## Extensions

- **Gamma k = 4**: a clock between the metronome and the exponential.
- **Slot-locked metronome**: batches restart at every slot boundary, so the phase is tied to the slot. With
  30 ms the last batch of each slot is 20 ms long: the stationary model is then only approximately right.
- **ECO losses**: 15% of VIP and 35% of ECO pairs never land (or land with another leader).
- **Window effect**: mu differs between windows (log-normal, sd 0.3): pairs of one window share a clock and
  are not independent. The cluster bootstrap by window (`analysis/boot.py`) is the guard for this case.
- **Pilot mu_hat off x2**: the grid is built from a pilot estimate twice the truth.

{power_markdown(ext, reps, alpha)}

## What this means for the design

{conclusions(rows)}
"""
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(path)
