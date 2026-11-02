"""The confirmatory family of PLAN §4 (frozen in docs/PREREGISTRATION.md) and the Holm correction.

    V1-V3  vendor claim mu_VIP = 20 / 50 / 50 ms        two-sided LRT, mu fixed at the claim
    E1     HarmonicAgave mu_VIP = HarmonicFiredancer     two-sided LRT, mu shared
    L1-L5  mu_ECO > mu_VIP (one-sided; L5 two-sided)     signed-root LRT, k shared across lanes

In V and E every group keeps its own lapse rates eps1, eps2; in L the two lanes of a family share
them (see `lane_test`).
"""
import math

from scipy import stats

from . import fit

CONFIRMATORY = [
    # id, kind, family (or pair), claim / direction
    ("V1", "claim", "AgaveBam", 20.0),
    ("V2", "claim", "HarmonicAgave", 50.0),
    ("V3", "claim", "HarmonicFiredancer", 50.0),
    ("E1", "equal", ("HarmonicAgave", "HarmonicFiredancer"), None),
    ("L1", "lane", "AgaveBam", "greater"),
    ("L2", "lane", "HarmonicAgave", "greater"),
    ("L3", "lane", "HarmonicFiredancer", "greater"),
    ("L4", "lane", "JitoLabs", "greater"),
    ("L5", "lane", "Firedancer", "two-sided"),
]
ALPHA = 0.05


def claim_test(s, y, claim_ms, best=None):
    """mu = claim against mu free (gamma, k free): LR statistic and p."""
    best = best or fit.fit_cell(s, y)
    th = best.extra["theta"][1:]
    null = fit.fit_groups([(s, y)], fixed_mu=claim_ms, starts=[th, [math.log(4.0), fit._logit_eps(0.03), fit._logit_eps(0.05)],
                                                              [math.log(200.0), fit._logit_eps(0.03), fit._logit_eps(0.05)]])
    d = max(0.0, 2 * (best.loglik - null.loglik))
    return {"mu_hat_ms": best.mu[0], "k_hat": best.k[0], "claim_ms": claim_ms, "lr": d, "p": float(stats.chi2.sf(d, 1))}


def _joint(groups, share_mu, singles, share_eps):
    """Joint gamma fit started from the single-group optima (and their mean)."""
    G = len(groups)
    logk = sum(math.log(f.k[0]) for f in singles) / G
    e1 = [f.extra["theta"][2] for f in singles]
    e2 = [f.extra["theta"][3] for f in singles]
    if share_eps:
        e1, e2 = [sum(e1) / G], [sum(e2) / G]
    if share_mu:
        mus = [[math.log(f.mu[0])] for f in singles] + [[sum(math.log(f.mu[0]) for f in singles) / G]]
    else:
        mus = [[math.log(f.mu[0]) for f in singles]]
    starts = [m + [logk] + e1 + e2 for m in mus] + [mus[-1] + [math.log(kk)] + e1 + e2 for kk in (1.0, 30.0)]
    return fit.fit_groups(groups, share_mu=share_mu, share_k=True, starts=starts, share_eps=share_eps)


def equal_mu_test(a, b, direction="two-sided", single_a=None, single_b=None, share_eps=False):
    """mu_b = mu_a (k shared) against separate mu. `direction` 'greater': H1 mu_b > mu_a.
    `share_eps`: one pair of lapse rates for both groups (the lane tests: same family, same
    validators, same windows); otherwise each group keeps its own."""
    singles = [single_a or fit.fit_cell(*a), single_b or fit.fit_cell(*b)]
    h1 = _joint([a, b], False, singles, share_eps)
    h0 = _joint([a, b], True, singles, share_eps)
    d = max(0.0, 2 * (h1.loglik - h0.loglik))
    mu_a, mu_b = h1.mu
    z = math.copysign(math.sqrt(d), math.log(mu_b / mu_a))
    p = float(stats.norm.sf(z)) if direction == "greater" else float(stats.chi2.sf(d, 1))
    return {"mu_a_ms": mu_a, "mu_b_ms": mu_b, "ratio": mu_b / mu_a, "k_shared": h1.k[0], "lr": d, "z": z, "p": p,
            "direction": direction}


def lane_test(vip, eco, direction="greater", single_vip=None):
    """L1-L5: mu_ECO against mu_VIP within one family, k and lapse rates shared across lanes.
    (With lapse rates per lane the test rejected 5% of simulated nulls at alpha 0.006.)"""
    return equal_mu_test(vip, eco, direction, single_a=single_vip, share_eps=True)


def holm(pvals, alpha=ALPHA):
    """Holm step-down: adjusted p-values and rejections, in the input order."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [None] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj, [a <= alpha for a in adj]


def run_confirmatory(cells):
    """`cells`: {(family, lane): (s, y)} of complete, non-buffered FEE and REV pairs.
    Returns one row per test; a test whose cells are missing is reported as not run."""
    rows = []
    for tid, kind, fam, arg in CONFIRMATORY:
        row = {"id": tid, "kind": kind, "family": fam if isinstance(fam, str) else " vs ".join(fam)}
        try:
            if kind == "claim":
                r = claim_test(*cells[(fam, "VIP")], arg)
            elif kind == "equal":
                r = equal_mu_test(cells[(fam[0], "VIP")], cells[(fam[1], "VIP")])
            else:
                r = lane_test(cells[(fam, "VIP")], cells[(fam, "ECO")], arg)
        except KeyError as e:
            row.update({"run": False, "why": f"no data for {e}"})
            rows.append(row)
            continue
        row.update({"run": True, **r})
        rows.append(row)
    ran = [r for r in rows if r.get("run")]
    adj, rej = holm([r["p"] for r in ran])
    for r, a, x in zip(ran, adj, rej):
        r["p_holm"], r["reject"] = a, x
    return rows
