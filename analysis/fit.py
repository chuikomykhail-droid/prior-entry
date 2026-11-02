"""Maximum likelihood for the models of `models`, profile intervals, shape comparison, the
"ms per key" read-outs and the non-parametric convex fit (PLAN §8.2 steps 3, 5, 6, 11).

A fit takes one or more groups of pairs (s in ms, y = 1 if B landed ahead). Every group has its
own lapse rates eps1 and eps2; mu and k are either one per group or shared, or mu is fixed
(for the profile and for the vendor-claim tests).
"""
import math
from dataclasses import dataclass, field

import numpy as np
from scipy import optimize, special, stats

from . import models

LOG_MU = (math.log(0.05), math.log(3000.0))
LOG_K = (math.log(0.25), math.log(300.0))
EPS_MAX = 0.45
SIGMA_MS = 0.3  # spread of the actual arrival gap around the recorded s (§5.6); 1.0 for sensitivity
CHI2_95 = stats.chi2.ppf(0.95, 1)


def _eps(z):
    return EPS_MAX * special.expit(z)


def _logit_eps(e):
    e = min(max(e, 1e-4), EPS_MAX - 1e-4)
    return math.log(e / (EPS_MAX - e))


def bernoulli_ll(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(np.sum(y * np.log(p) + (1 - y) * np.log1p(-p)))


@dataclass
class Fit:
    shape: str
    loglik: float
    mu: list
    k: list
    eps1: list
    eps2: list
    n: list
    n_params: int
    converged: bool = True
    extra: dict = field(default_factory=dict)

    @property
    def aic(self):
        return 2 * self.n_params - 2 * self.loglik

    def as_dict(self):
        return {"shape": self.shape, "loglik": self.loglik, "aic": self.aic, "mu_ms": self.mu, "k": self.k,
                "eps1": self.eps1, "eps2": self.eps2, "n": self.n, "n_params": self.n_params, "converged": self.converged,
                **self.extra}


def aggregate(s, y):
    """Unique gaps (0.01 ms) with the counts of B ahead and B behind."""
    s, y = np.round(np.asarray(s, float), 2), np.asarray(y, float)
    u, inv = np.unique(s, return_inverse=True)
    n1 = np.bincount(inv, weights=y, minlength=len(u))
    n0 = np.bincount(inv, minlength=len(u)) - n1
    return u, n1, n0


def crude_mu(s, y):
    """Start value: best exponential mu on a log grid with eps fixed at (0.03, 0.05)."""
    u, n1, n0 = aggregate(s, y)
    grid = np.exp(np.linspace(math.log(0.2), math.log(1500.0), 40))
    p = np.clip(0.03 + 0.92 * np.exp(-np.maximum(u, 0)[None, :] / grid[:, None]), 1e-9, 1 - 1e-9)
    ll = np.log(p) @ n1 + np.log1p(-p) @ n0
    return float(grid[int(np.argmax(ll))])


def fit_groups(groups, shape="gamma", share_mu=False, share_k=True, fixed_mu=None, sigma=SIGMA_MS, starts=None, share_eps=False):
    """MLE over `groups` = [(s, y), ...]. `fixed_mu`: one value, or one per group. `share_eps`: one
    pair of lapse rates for all groups."""
    G = len(groups)
    groups = [(np.asarray(s, float), np.asarray(y, float)) for s, y in groups]
    if shape == "constant":
        ll, c = 0.0, []
        for s, y in groups:
            ci = float(np.clip(y.mean() if len(y) else 0.5, 1e-6, 1 - 1e-6))
            c.append(ci)
            ll += bernoulli_ll(np.full(len(y), ci), y)
        return Fit("constant", ll, [None] * G, [None] * G, c, [0.0] * G, [len(y) for _, y in groups], G)

    has_k = shape == "gamma"
    if fixed_mu is not None:
        fm = list(fixed_mu) if np.ndim(fixed_mu) else [fixed_mu] * G
        n_mu = 0
    else:
        n_mu = 1 if share_mu else G
    n_k = (1 if share_k else G) if has_k else 0
    n_e = 1 if share_eps else G

    def unpack(th):
        i = 0
        if fixed_mu is not None:
            mu = fm
        else:
            mu = [math.exp(v) for v in th[i:i + n_mu]]
            mu = mu * G if n_mu == 1 else mu
            i += n_mu
        if has_k:
            k = [math.exp(v) for v in th[i:i + n_k]]
            k = k * G if n_k == 1 else k
            i += n_k
        else:
            k = [None] * G
        e1 = [_eps(v) for v in th[i:i + n_e]]
        e2 = [_eps(v) for v in th[i + n_e:i + 2 * n_e]]
        return mu, k, e1 * (G // n_e), e2 * (G // n_e)

    agg = [aggregate(s, y) for s, y in groups]

    def nll(th):
        mu, k, e1, e2 = unpack(th)
        tot = 0.0
        for g, (u, n1, n0) in enumerate(agg):
            p = np.clip(models.p_ahead(u, mu[g], k[g], e1[g], e2[g], sigma, shape), 1e-9, 1 - 1e-9)
            tot -= float(n1 @ np.log(p) + n0 @ np.log1p(-p))
        return tot

    bounds = [LOG_MU] * n_mu + [LOG_K] * n_k + [(-12, 12)] * (2 * n_e)
    if starts is None:
        starts = []
        m0 = float(np.exp(np.mean([math.log(crude_mu(s, y)) for s, y in groups])))
        mus = [m0 / 3, m0, m0 * 3] if n_mu else [None]
        ks = [1.5, 5.0, 30.0] if has_k else [None]
        for m in mus:
            for kk in ks:
                th = ([math.log(m)] * n_mu) + ([math.log(kk)] * n_k if has_k else []) + [_logit_eps(0.03)] * n_e + [_logit_eps(0.05)] * n_e
                starts.append(th)
    best = None
    for th0 in starts:
        r = optimize.minimize(nll, np.asarray(th0, float), method="L-BFGS-B", bounds=bounds)
        if best is None or r.fun < best.fun:
            best = r
    mu, k, e1, e2 = unpack(best.x)
    n_params = n_mu + n_k + 2 * n_e
    f = Fit(shape, -float(best.fun), mu, k, e1, e2, [len(y) for _, y in groups], n_params, bool(best.success))
    f.extra["theta"] = [float(v) for v in best.x]
    return f


def fit_cell(s, y, shape="gamma", sigma=SIGMA_MS):
    return fit_groups([(s, y)], shape=shape, sigma=sigma)


def profile_mu(s, y, shape="gamma", grid=None, sigma=SIGMA_MS, best=None):
    """Profile log-likelihood of mu for one cell: [(mu, loglik)], maximised over the rest."""
    if grid is None:
        grid = np.exp(np.linspace(math.log(0.1), math.log(2000.0), 61))
    best = best or fit_cell(s, y, shape, sigma)
    th = best.extra["theta"][1:]  # without log mu
    out = []
    for m in grid:
        f = fit_groups([(s, y)], shape=shape, fixed_mu=float(m), sigma=sigma, starts=[th, [math.log(4.0)] * (shape == "gamma")
                                                                                      + [_logit_eps(0.03), _logit_eps(0.05)]])
        th = f.extra["theta"]
        out.append((float(m), f.loglik))
    return out, best


def profile_interval(profile, loglik_max, level=0.95):
    """Interval of mu from the profile; ends that do not cross inside the grid are reported as
    censored (the lower end as the grid minimum, the upper as inf)."""
    thr = stats.chi2.ppf(level, 1) / 2
    mus = np.array([m for m, _ in profile])
    dev = loglik_max - np.array([l for _, l in profile])
    inside = dev <= thr
    if not inside.any():
        i = int(np.argmin(dev))
        return {"lo": float(mus[i]), "hi": float(mus[i]), "lo_censored": False, "hi_censored": False}
    idx = np.where(inside)[0]
    i0, i1 = idx[0], idx[-1]

    def cross(a, b):
        la, lb = math.log(mus[a]), math.log(mus[b])
        da, db = dev[a] - thr, dev[b] - thr
        return float(math.exp(la + (lb - la) * (0 - da) / (db - da))) if db != da else float(mus[a])

    lo = cross(i0 - 1, i0) if i0 > 0 else float(mus[0])
    hi = cross(i1, i1 + 1) if i1 < len(mus) - 1 else float("inf")
    return {"lo": lo, "hi": hi, "lo_censored": i0 == 0, "hi_censored": i1 == len(mus) - 1}


def compare_shapes(s, y, sigma=SIGMA_MS):
    """Gamma, metronome, exponential and constant on one cell: log-likelihoods, AIC, and the
    likelihood-ratio statistics of the nested pairs."""
    fits = {sh: fit_cell(s, y, sh, sigma) for sh in models.SHAPES}
    g = fits["gamma"]
    out = {sh: {"loglik": f.loglik, "aic": f.aic, "mu_ms": f.mu[0], "k": f.k[0]} for sh, f in fits.items()}
    best = min(out, key=lambda sh: out[sh]["aic"])
    # gamma vs constant: is there a rule at all?
    d_const = 2 * (g.loglik - fits["constant"].loglik)
    return {"fits": out, "best_aic": best,
            "rule_exists_lr": d_const, "rule_exists_p": float(stats.chi2.sf(max(d_const, 0), 3)),
            "gamma_vs_metronome_lr": 2 * (g.loglik - fits["metronome"].loglik),
            "gamma_vs_exponential_lr": 2 * (g.loglik - fits["exponential"].loglik)}


def read_outs(f, g=0):
    """s50 and s10 of a fitted group: the head start after which B (key x1.8) overtakes in at
    most half / a tenth of pairs."""
    args = (f.mu[g], f.k[g], f.eps1[g], f.eps2[g], f.shape)
    return {"s50_ms": models.s_at(0.5, *args), "s10_ms": models.s_at(0.1, *args)}


# --- non-parametric: convex decreasing regression (§5.7, exploratory) ---------------------------

def _pava_decreasing(y, w):
    """Weighted antitonic regression (pool adjacent violators)."""
    blocks = [[float(y[i]), float(w[i]), 1] for i in range(len(y))]
    out = []
    for b in blocks:
        out.append(b)
        while len(out) > 1 and out[-2][0] < out[-1][0]:
            v2, w2, n2 = out.pop()
            v1, w1, n1 = out.pop()
            out.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, n1 + n2])
    return np.concatenate([[v] * n for v, _, n in out])


def convex_fit(s, y):
    """Decreasing convex least squares on s >= 0: f(s) = a + sum_j b_j (t_j - s)+, a, b >= 0.
    Returns knots (unique s), fitted values, and the implied mu = 1 / |f'(0+)| when f(0) > 0."""
    s, y = np.asarray(s, float), np.asarray(y, float)
    m = s >= 0
    s, y = s[m], y[m]
    xs, inv = np.unique(np.round(s, 1), return_inverse=True)
    w = np.bincount(inv).astype(float)
    ybar = np.bincount(inv, weights=y) / w
    basis = np.column_stack([np.ones_like(xs)] + [np.maximum(t - xs, 0.0) for t in xs[1:]])
    sw = np.sqrt(w)
    coef, _ = optimize.nnls(basis * sw[:, None], ybar * sw)
    fv = basis @ coef
    slope0 = -coef[1:].sum()
    iso = _pava_decreasing(ybar, w)
    sse_convex = float(np.sum(w * (ybar - fv) ** 2))
    sse_iso = float(np.sum(w * (ybar - iso) ** 2))
    span = fv[0] - fv[-1]
    mu = float(span / -slope0) if slope0 < 0 else float("inf")
    return {"s": xs.tolist(), "fit": fv.tolist(), "isotonic": iso.tolist(), "n": w.tolist(),
            "sse_convex": sse_convex, "sse_isotonic": sse_iso, "mu_from_slope_ms": mu}


def convexity_test(s, y, reps=200, seed=0):
    """Parametric bootstrap of the gap SSE_convex - SSE_isotonic under the convex fit."""
    rng = np.random.default_rng(seed)
    base = convex_fit(s, y)
    stat = base["sse_convex"] - base["sse_isotonic"]
    s = np.asarray(s, float)
    m = s >= 0
    xs = np.array(base["s"])
    p = np.clip(np.interp(np.round(s[m], 1), xs, base["fit"]), 0, 1)
    null = []
    for _ in range(reps):
        yb = (rng.random(len(p)) < p).astype(float)
        b = convex_fit(s[m], yb)
        null.append(b["sse_convex"] - b["sse_isotonic"])
    pval = (1 + sum(v >= stat for v in null)) / (reps + 1)
    return {"gap": stat, "p": pval, "reps": reps}


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)
