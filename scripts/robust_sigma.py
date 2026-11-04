"""The robustness check of PREREGISTRATION §5 that `reproduce` does not compute: every cell's fit, and V1-V3, with the
spread of the arrival gap at sigma = 1 ms instead of 0.3 ms. Reported, not used for any verdict.

Usage:
    python scripts/robust_sigma.py [--raw data/raw] [--out data/checks/sigma-1ms.json]
"""
import argparse
import json
import math
import os
import sys

from scipy import stats

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from analysis import fit, pairs  # noqa: E402

CLAIMS = {"V1": ("AgaveBam", 20.0), "V2": ("HarmonicAgave", 50.0), "V3": ("HarmonicFiredancer", 50.0)}
SIGMA = 1.0


def claim(s, y, claim_ms, best):
    th = best.extra["theta"][1:]
    null = fit.fit_groups([(s, y)], fixed_mu=claim_ms, sigma=SIGMA,
                          starts=[th, [math.log(4.0), fit._logit_eps(0.03), fit._logit_eps(0.05)], [math.log(200.0), fit._logit_eps(0.03), fit._logit_eps(0.05)]])
    d = max(0.0, 2 * (best.loglik - null.loglik))
    return {"mu_hat_ms": round(best.mu[0], 3), "claim_ms": claim_ms, "lr": round(d, 3), "p": float(f"{stats.chi2.sf(d, 1):.4g}")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="data/checks/sigma-1ms.json")
    a = ap.parse_args()
    cp = pairs.clock_pairs(pairs.build(a.raw, "live"))
    res = {"sigma_ms": SIGMA, "cells": {}, "claims": {}}
    fits = {}
    for (fam, lane), g in cp.groupby(["family", "lane"]):
        s, y = g["s_ms"].to_numpy(float), g["y"].to_numpy(float)
        if len(g) < 40:
            continue
        fits[(fam, lane)] = (s, y, fit.fit_cell(s, y, sigma=SIGMA))
        f = fits[(fam, lane)][2]
        res["cells"][f"{fam}/{lane}"] = {"n": len(g), "mu_ms": round(f.mu[0], 3), "k": round(f.k[0], 3)}
        print(f"{fam:<20}{lane:<4} n {len(g):>4}  mu {f.mu[0]:>8.3f}  k {f.k[0]:>8.3f}")
    for tid, (fam, claim_ms) in CLAIMS.items():
        s, y, best = fits[(fam, "VIP")]
        res["claims"][tid] = {"family": fam, **claim(s, y, claim_ms, best)}
        print(tid, res["claims"][tid])
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(a.out)


if __name__ == "__main__":
    main()
