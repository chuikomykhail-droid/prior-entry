"""The models of PLAN §5: what share of pairs ends with B ahead, as a function of the send gap s.

A clock that cuts batches at the points of a stationary renewal process with mean interval mu
lets B (sent s ms after A) overtake A exactly when no batch boundary falls between the two
arrivals. That probability is the stationary survival function of the residual time,

    G(s) = (1/mu) * integral_s^inf S(u) du,         G(s) = 1 for s <= 0.

Gamma intervals (shape k, mean mu) contain both extremes: k = 1 is the exponential
("on demand", G = exp(-s/mu)), k -> inf the metronome (G = (1 - s/mu)+). The observed share adds
lapses and a blur of the actual arrival gap:

    P(Y = 1 | s) = eps1 + (1 - eps1 - eps2) * E[G(s + eta)],   eta ~ N(0, sigma^2)

eps2 is the noise ceiling (REV pairs: B first and still behind), eps1 the floor (B far behind
and still ahead).
"""
import numpy as np
from scipy import special

# Gauss-Hermite nodes for the blur E[G(s + eta)], eta ~ N(0, sigma^2)
_GH_X, _GH_W = np.polynomial.hermite_e.hermegauss(9)
_GH_W = _GH_W / _GH_W.sum()

SHAPES = ("gamma", "metronome", "exponential", "constant")


def g_gamma(s, mu, k):
    """Residual survival of a gamma(k, mu/k) renewal process; 1 for s <= 0."""
    s = np.asarray(s, dtype=float)
    x = np.maximum(s, 0.0) * k / mu
    g = special.gammaincc(k + 1.0, x) - (np.maximum(s, 0.0) / mu) * special.gammaincc(k, x)
    return np.where(s <= 0, 1.0, np.clip(g, 0.0, 1.0))


def g_metronome(s, mu):
    s = np.asarray(s, dtype=float)
    return np.clip(1.0 - np.maximum(s, 0.0) / mu, 0.0, 1.0)


def g_exponential(s, mu):
    s = np.asarray(s, dtype=float)
    return np.exp(-np.maximum(s, 0.0) / mu)


def g_shape(shape, s, mu, k=None):
    if shape == "gamma":
        return g_gamma(s, mu, k)
    if shape == "metronome":
        return g_metronome(s, mu)
    if shape == "exponential":
        return g_exponential(s, mu)
    if shape == "constant":
        return np.full(np.shape(s), 0.5)
    raise ValueError(shape)


def blurred(shape, s, mu, k=None, sigma=0.0):
    """E[G(s + eta)] with eta ~ N(0, sigma^2)."""
    s = np.asarray(s, dtype=float)
    # a blur far below the time scale changes nothing measurable; skip it for speed
    if sigma <= 0 or sigma < 0.01 * mu:
        return g_shape(shape, s, mu, k)
    pts = s[..., None] + sigma * _GH_X
    return (g_shape(shape, pts, mu, k) * _GH_W).sum(axis=-1)


def p_ahead(s, mu, k=None, eps1=0.0, eps2=0.0, sigma=0.0, shape="gamma"):
    """P(B ahead | s) under the full model of §5.6."""
    if shape == "constant":
        # "no rule": one share regardless of s; eps1 carries it
        return np.full(np.shape(s), eps1)
    return eps1 + (1.0 - eps1 - eps2) * blurred(shape, s, mu, k, sigma)


def interval_density(u, mu, k):
    """Density of the batch interval (gamma) — what the inversion G'' recovers (§5.7)."""
    return np.exp(special.xlogy(k - 1, u) - u * k / mu - special.gammaln(k) + k * np.log(k / mu))


def s_at(p, mu, k=None, eps1=0.0, eps2=0.0, shape="gamma", hi=5000.0):
    """The send gap at which P(B ahead) falls to p (s50: p = 0.5; s10: p = 0.1); inf if never."""
    if p <= eps1:
        return float("inf")
    if p >= 1.0 - eps2:
        return 0.0
    lo, up = 0.0, hi
    if p_ahead(np.array([up]), mu, k, eps1, eps2, 0.0, shape)[0] > p:
        return float("inf")
    for _ in range(80):
        mid = 0.5 * (lo + up)
        if p_ahead(np.array([mid]), mu, k, eps1, eps2, 0.0, shape)[0] > p:
            lo = mid
        else:
            up = mid
    return 0.5 * (lo + up)
