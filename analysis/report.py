"""`python -m analysis reproduce`: raw runs -> data/derived and figures/, the steps of PLAN §8.2.

Everything written is rounded to 6 significant digits and sorted, so a recomputation is easy to
compare (`python -m analysis check`). Slots and compute units stay whole: `getBlock` needs the slot.
"""
import concurrent.futures as cf
import json
import math
import os

import numpy as np

from . import boot, figures, fit, hypotheses, pairs, placebo, rawio

WHOLE_COLUMNS = {"slot_a": "Int64", "slot_b": "Int64", "a_slot": "Int64", "block_cu": "Int64"}  # too long for 6 digits
S_EDGES = [-1000, 0, 1, 2.5, 5, 8, 12, 18, 25, 35, 50, 75, 110, 160, 230, 330, 2000]
MIN_FIT = 40  # pairs per cell for a parametric fit
# The buffered check takes only pairs written this long before the window's first shred at the RPC
# node: they surely reached the leader before the window (the pilot bounds that delay by ~30-70 ms).
# Pairs between this and the first shred are in neither the check nor the clock fits.
SURELY_BUFFERED_MS = 100.0
MIN_VALIDATOR_FIT = 60
# Late overtakes (PREREGISTRATION §5, amended): B still ahead when sent at least 1.5 T after A, T the
# published period (40 ms for families without one), up to 150 ms (itb/src/design.rs, LATE_HI_MS).
# A "tail" when at least MIN_TAIL_N pairs are in the window and the lower Wilson bound of that share
# exceeds TAIL_FLOOR.
LATE_LO_DEFAULT_MS = 40.0
LATE_HI_MS = 150.0
TAIL_FLOOR = 0.05
MIN_TAIL_N = 20
# bands of s for the per-validator table (ms, lower bound excluded); s = 0 comes from the
# simultaneous pairs
BANDS = [("0-20 ms", 0.0, 20.0), ("20-60 ms", 20.0, 60.0), ("60-200 ms", 60.0, 200.0)]
MIN_HETEROGENEITY = 30  # clock pairs per validator and lane for the heterogeneity test


def late_window(family):
    t = figures.CLAIMS.get(family)
    return (1.5 * t if t else LATE_LO_DEFAULT_MS, LATE_HI_MS)


def share(y):
    """Share of B ahead with its Wilson interval."""
    k, n = int(np.sum(y)), len(y)
    lo, hi = fit.wilson(k, n)
    return {"n": n, "b_ahead": k, "share": k / n if n else None, "lo": lo, "hi": hi}


def late_share(g, family):
    lo, hi = late_window(family)
    r = share(g.loc[(g["s_ms"] >= lo) & (g["s_ms"] <= hi), "y"].to_numpy(float))
    return {**r, "window_ms": [lo, hi], "tail": bool(r["n"] >= MIN_TAIL_N and r["lo"] > TAIL_FLOOR)}


def clean(x):
    """Floats to 6 significant digits, NaN/inf to None or strings; recursively."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (float, np.floating)):
        x = float(x)
        if math.isnan(x):
            return None
        if math.isinf(x):
            return "inf" if x > 0 else "-inf"
        return float(f"{x:.6g}")
    return x


def dump(obj, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(clean(obj), fh, indent=1, sort_keys=True)
        fh.write("\n")


def _fit_cell_job(args):
    fam, lane, s, y = args
    f = fit.fit_cell(s, y)
    prof, _ = fit.profile_mu(s, y, best=f)
    ci = fit.profile_interval(prof, f.loglik)
    shapes = fit.compare_shapes(s, y)
    conv = fit.convexity_test(s[s >= 0], y[s >= 0], reps=100)
    convex = fit.convex_fit(s, y)
    return {"family": fam, "lane": lane, "n": len(y), "n_fee": int((s >= 0).sum()), "n_rev": int((s < 0).sum()),
            "mu_ms": f.mu[0], "k": f.k[0], "eps1": f.eps1[0], "eps2": f.eps2[0], "loglik": f.loglik, "mu_ci": ci,
            "profile": prof, **fit.read_outs(f), "shapes": shapes, "convexity": conv,
            "convex_mu_from_slope_ms": convex["mu_from_slope_ms"]}


def _boot_job(args):
    key, g, reps, seed = args
    return key, boot.cell_ci(g, reps=reps, seed=seed)


def _pool():
    return cf.ProcessPoolExecutor(max(1, min(8, (os.cpu_count() or 2) - 1)))


def key_control(df):
    """Step 1: which key? C2 'X first' and FEE pairs at s <= 1 ms 'B first', per family, with the
    predictions of four candidate keys."""
    rows = []
    comp = df[df["complete"]] if len(df) else df
    for fam, g in comp.groupby("family") if len(comp) else []:
        c2 = g[g["series"] == "CTRL_C2"]
        f0 = g[(g["series"] == "FEE") & (g["s_ms"] <= 1.0)]
        x_first = int((1 - c2["y"]).sum())
        b_first = int(f0["y"].sum())
        rows.append({"family": fam, "c2_n": len(c2), "c2_x_first": x_first, "c2_share": x_first / len(c2) if len(c2) else None,
                     "c2_ci": fit.wilson(x_first, len(c2)), "fee0_n": len(f0), "fee0_b_first": b_first,
                     "fee0_share": b_first / len(f0) if len(f0) else None, "fee0_ci": fit.wilson(b_first, len(f0))})
    predictions = {"reward/cost": {"c2": "X", "fee0": "B"}, "CU price": {"c2": "Y", "fee0": "B"},
                   "total fee": {"c2": "Y", "fee0": "B"}, "cost alone": {"c2": "X", "fee0": "tie (50%)"}}
    return {"families": rows, "predictions": predictions}


def losses(df):
    out = {}
    if not len(df):
        return out
    for (fam, series, lane), g in df.groupby(["family", "series", "lane"]):
        out[f"{fam}/{series}/{lane}"] = {"pairs": len(g), "complete": int(g["complete"].sum()),
                                         "buffered": int((g["complete"] & g["buffered"]).sum()),
                                         "untimed": int((g["complete"] & ~g["timed"]).sum()),
                                         "excluded": {str(k): int(v) for k, v in g["excluded"].value_counts().items()}}
    return out


def _validator_fit_job(args):
    key, s, y = args
    f = fit.fit_cell(s, y)
    prof, _ = fit.profile_mu(s, y, best=f)
    sh = fit.compare_shapes(s, y)
    return key, {"mu_ms": f.mu[0], "k": f.k[0], "eps1": f.eps1[0], "eps2": f.eps2[0],
                 "mu_ci": fit.profile_interval(prof, f.loglik),
                 "rule": "key within mu, arrival beyond" if sh["rule_exists_p"] < 0.05 else "no rule detected",
                 "strictness": f"eps1 {f.eps1[0]:.2f}, eps2 {f.eps2[0]:.2f}, k {f.k[0]:.1f}",
                 "rule_exists_p": sh["rule_exists_p"]}


def validators(df, ex=None):
    """Step 12, the main descriptive table (PREREGISTRATION §5, amended): per validator and lane the
    share of B ahead at s = 0 (simultaneous pairs) and in three bands of s, the late overtakes, all
    without the model; mu and its profile interval from MIN_VALIDATOR_FIT clock pairs on."""
    cp, sim = pairs.clock_pairs(df), pairs.simultaneous_pairs(df)
    cols = ["family", "leader", "lane"]
    keys = sorted({tuple(k) for d in (cp, sim) if len(d) for k in d[cols].to_numpy()})
    rows, jobs = [], []
    for fam, leader, lane in keys:
        g = cp[(cp["family"] == fam) & (cp["leader"] == leader) & (cp["lane"] == lane)] if len(cp) else cp
        z = sim[(sim["family"] == fam) & (sim["leader"] == leader) & (sim["lane"] == lane)] if len(sim) else sim
        bands = {"s = 0": share(z["y"].to_numpy(float) if len(z) else [])}
        for name, lo, hi in BANDS:
            bands[name] = share(g.loc[(g["s_ms"] > lo) & (g["s_ms"] <= hi), "y"].to_numpy(float) if len(g) else [])
        rows.append({"validator": leader, "family": fam, "lane": lane, "n": len(g), "bands": bands,
                     "late": late_share(g, fam) if len(g) else None})
        if len(g) >= MIN_VALIDATOR_FIT:
            jobs.append(((fam, leader, lane), g["s_ms"].to_numpy(float), g["y"].to_numpy(float)))
    fits = dict(ex.map(_validator_fit_job, jobs) if ex else map(_validator_fit_job, jobs))
    for r in rows:
        r.update(fits.get((r["family"], r["validator"], r["lane"]), {}))
    return rows


def simultaneous(df):
    """FEE pairs sent at s = 0 in the window, per family and lane: share with B first, no model.
    Per validator: `validators`."""
    sim = pairs.simultaneous_pairs(df)
    return {f"{fam}/{lane}": share(g["y"].to_numpy(float)) for (fam, lane), g in sim.groupby(["family", "lane"])} if len(sim) else {}


def late_overtakes(df):
    """Per family and lane: share of B ahead among the clock pairs in the family's late window."""
    cp = pairs.clock_pairs(df)
    out = {"tail_floor": TAIL_FLOOR, "cells": {}}
    for (fam, lane), g in cp.groupby(["family", "lane"]) if len(cp) else []:
        out["cells"][f"{fam}/{lane}"] = late_share(g, fam)
    return out


def heterogeneity(df):
    """Per family and lane (PREREGISTRATION §5, amended): one mu for all its validators against one
    each, k shared, lapse rates per validator; validators with MIN_HETEROGENEITY clock pairs.
    `flag` (p < 0.05): the family's mu is read per validator; `differ` (Holm over these tests
    < 0.05): "its validators differ" may be claimed."""
    cp = pairs.clock_pairs(df)
    out = {}
    for (fam, lane), g in cp.groupby(["family", "lane"]) if len(cp) else []:
        groups = [(v, h) for v, h in g.groupby("leader") if len(h) >= MIN_HETEROGENEITY]
        row = {"validators": [v for v, _ in groups], "n": [len(h) for _, h in groups]}
        if len(groups) < 2:
            out[f"{fam}/{lane}"] = {**row, "run": False}
            continue
        r = hypotheses.validators_equal_test([(h["s_ms"].to_numpy(float), h["y"].to_numpy(float)) for _, h in groups])
        out[f"{fam}/{lane}"] = {**row, "run": True, **r, "flag": r["p"] < 0.05}
    ran = [k for k in sorted(out) if out[k]["run"]]
    adj, rej = hypotheses.holm([out[k]["p"] for k in ran])
    for k, a, x in zip(ran, adj, rej):
        out[k]["p_holm"], out[k]["differ"] = a, x
    return out


def claims_inside_slot(df):
    """Robustness of V1-V3: the claim tests on the clock pairs whose gap lies inside one slot (a
    slot boundary between A and B cuts the pair whatever the client's clock)."""
    cp = pairs.clock_pairs(df)
    out = {}
    for tid, kind, fam, claim in hypotheses.CONFIRMATORY:
        if kind != "claim":
            continue
        g = cp[(cp["family"] == fam) & (cp["lane"] == "VIP") & cp["inside_slot"]] if len(cp) else cp
        if len(g) < MIN_FIT:
            out[tid] = {"family": fam, "run": False, "n": len(g)}
            continue
        out[tid] = {"family": fam, "run": True, "n": len(g),
                    **hypotheses.claim_test(g["s_ms"].to_numpy(float), g["y"].to_numpy(float), claim)}
    return out


def phase_split(df):
    """Step 7 (exploratory): A in the first 30 ms of its slot vs the rest."""
    out = {}
    cp = pairs.clock_pairs(df)
    for (fam, lane), g in cp.groupby(["family", "lane"]) if len(cp) else []:
        g = g[g["phase_ms"].notna()]
        early = g["phase_ms"] < 30
        r = {}
        for name, h in (("first_30ms", g[early]), ("rest", g[~early])):
            if len(h) >= MIN_FIT:
                f = fit.fit_cell(h["s_ms"].to_numpy(float), h["y"].to_numpy(float))
                r[name] = {"n": len(h), "mu_ms": f.mu[0], "k": f.k[0]}
            else:
                r[name] = {"n": len(h)}
        out[f"{fam}/{lane}"] = r
    return out


def buffer_sensitivity(df):
    """Robustness: mu with the buffered boundary moved 50 ms earlier and 50 ms later than the main
    analysis puts it (the first shred of the window at the RPC node)."""
    out = {}
    if not len(df):
        return out
    base = df["complete"] & df["series"].isin(["FEE", "REV"]) & df["s_ms"].notna()
    for name, shift in (("start_50ms_earlier", 50.0), ("start_50ms_later", -50.0)):
        since = df["a_since_window_ms"] + shift
        m = base & df["timed"] & ~(since < 0)
        for (fam, lane), g in df[m].groupby(["family", "lane"]):
            if len(g) >= MIN_FIT:
                f = fit.fit_cell(g["s_ms"].to_numpy(float), g["y"].to_numpy(float))
                out.setdefault(f"{fam}/{lane}", {})[name] = {"n": len(g), "mu_ms": f.mu[0], "k": f.k[0]}
    return out


def sessions(df):
    out = {}
    cp = pairs.clock_pairs(df)
    for (fam, lane, ses), g in cp.groupby(["family", "lane", "session"]) if len(cp) else []:
        if len(g) >= MIN_FIT:
            f = fit.fit_cell(g["s_ms"].to_numpy(float), g["y"].to_numpy(float))
            out[f"{fam}/{lane}/{ses}"] = {"n": len(g), "mu_ms": f.mu[0], "k": f.k[0],
                                          "median_block_ntx": float(g["block_ntx"].median())}
    return out


def rank_summary(df):
    out = {}
    comp = df[df["complete"]] if len(df) else df
    for (fam, lane), g in comp.groupby(["family", "lane"]) if len(comp) else []:
        out[f"{fam}/{lane}"] = {"n": len(g), "rank_a_median": float(g["rank_a"].median()), "rank_a_p10": float(g["rank_a"].quantile(0.1)),
                                "rank_b_median": float(g["rank_b"].median()), "block_ntx_median": float(g["block_ntx"].median()),
                                "between_median": float(g["between"].median()) if "between" in g else None,
                                "between_key_median": float(g["between_key"].median()) if "between_key" in g else None}
    return out


def two_verdicts_data(df):
    """One validator, two verdicts: the validator with the most clock pairs, s = 0 and s ~ 50 ms in both lanes."""
    cp = pairs.clock_pairs(df)
    if not len(cp):
        return None
    leader = cp["leader"].value_counts().index[0]
    g = cp[cp["leader"] == leader]
    sim = pairs.simultaneous_pairs(df)
    z = sim[sim["leader"] == leader] if len(sim) else sim
    bars = []
    for label, lane, lo, hi in (("s = 0 ms, VIP", "VIP", None, None), ("s = 0 ms, ECO", "ECO", None, None), ("s ~ 50 ms, VIP", "VIP", 35, 70), ("s ~ 50 ms, ECO", "ECO", 35, 70)):
        h = (z[z["lane"] == lane] if len(z) else z) if lo is None else g[(g["lane"] == lane) & (g["s_ms"] >= lo) & (g["s_ms"] < hi)]
        k, n = int(h["y"].sum()), len(h)
        if n:
            a, b = fit.wilson(k, n)
            bars.append({"label": label, "lane": lane, "n": n, "share": k / n, "lo": a, "hi": b})
    return {"validator": leader, "family": g["family"].iloc[0], "bars": bars}


def market(raw_runs):
    """Keys of all foreign non-vote transactions in the blocks we read, for the VIP lane figure."""
    keys = []
    for d in raw_runs:
        for b in rawio.read_jsonl(os.path.join(d, "blocks.jsonl.gz")):
            k, vote, _ = pairs.block_keys(b)
            keys.append(k[~vote])
    return np.concatenate(keys) if keys else np.array([])


PROBES = [("VIP cheap A", "VIP", 1_549_586), ("VIP dear B", "VIP", 2_840_909), ("ECO cheap A", "ECO", 14_900), ("ECO dear B", "ECO", 27_317)]


def results_md(cells_fit, conf, kc, late=None, het=None, vrows=None, inside=None, stake=None):
    """The README / REPORT tables, filled from the fits and the read-outs."""
    def mu_txt(c):
        if not c or not c.get("mu_ci"):
            return "—"
        ci = c["mu_ci"]
        hi = "∞" if ci["hi"] in ("inf", float("inf")) or (isinstance(ci["hi"], float) and math.isinf(ci["hi"])) else f"{ci['hi']:.3g}"
        lo = f"<{ci['lo']:.3g}" if ci.get("lo_censored") else f"{ci['lo']:.3g}"
        return f"{c['mu_ms']:.3g} [{lo}–{hi}]"

    def pct(r):
        if not r or not r.get("n"):
            return "—"
        return f"{r['share'] * 100:.0f}% [{r['lo'] * 100:.0f}–{r['hi'] * 100:.0f}] ({r['n']})"

    by = {(c["family"], c["lane"]): c for c in cells_fit}
    tests = {t["id"]: t for t in conf}
    late_cells, het = (late or {}).get("cells", {}), het or {}
    fams = sorted({c["family"] for c in cells_fit}, key=lambda f: (f not in figures.CLAIMS, f))
    lane_test = {"AgaveBam": "L1", "HarmonicAgave": "L2", "HarmonicFiredancer": "L3", "JitoLabs": "L4", "Firedancer": "L5"}
    claim_test = {"AgaveBam": "V1", "HarmonicAgave": "V2", "HarmonicFiredancer": "V3"}

    def mu_cell(f, lane):
        return mu_txt(by.get((f, lane))) + (" †" if het.get(f"{f}/{lane}", {}).get("flag") else "")

    lines = ["| Client | Shutter, VIP lane, ms [95%] | Shutter, typical lane, ms [95%] | Vendor says | Matches? | "
             "Late overtakes, VIP [95%] (n) | Clock or queue |",
             "|---|---|---|---|---|---|---|"]
    for f in fams:
        claim = figures.CLAIMS.get(f)
        v = tests.get(claim_test.get(f, ""), {})
        lt = tests.get(lane_test.get(f, ""), {})
        lv = late_cells.get(f"{f}/VIP")
        # reading rule (PREREGISTRATION §5): a kept claim with a late tail is "round yes, late overtakes"
        match = "—" if not v.get("run") else ("no" if v.get("reject") else ("round yes, late overtakes" if lv and lv.get("tail") else "yes"))
        cq = "—" if not lt.get("run") else (f"queue (ECO ×{lt['ratio']:.2g})" if lt.get("reject") else "clock (lanes equal)")
        lines.append(f"| {f} | {mu_cell(f, 'VIP')} | {mu_cell(f, 'ECO')} | {f'{claim:g} ms' if claim else '—'} | {match} | {pct(lv)} | {cq} |")
    if any(h.get("flag") for h in het.values()):
        lines += ["", "† One mu for all validators of this client is rejected at p < 0.05: read the per-validator table "
                  "(\"its validators differ\" only where the Holm-adjusted p is below 0.05 too)."]
    if vrows:
        lines += ["", "| Client | Validator | Lane | s = 0: B first | " + " | ".join(b[0] for b in BANDS) + " | Late overtakes | Shutter, ms [95%] |",
                  "|---|---|---|---|" + "---|" * len(BANDS) + "---|---|"]
        frac = lambda r: f"{r['b_ahead']}/{r['n']}" if r and r.get("n") else "—"
        for r in sorted(vrows, key=lambda r: (r["family"] not in figures.CLAIMS, r["family"], r["validator"], r["lane"] != "VIP")):
            cells = [frac(r["bands"]["s = 0"])] + [frac(r["bands"][b[0]]) for b in BANDS]
            lines.append(f"| {r['family']} | `{r['validator'][:8]}` | {r['lane']} | " + " | ".join(cells)
                         + f" | {frac(r.get('late'))} | {mu_txt(r)} |")
    ran = {k: h for k, h in het.items() if h.get("run")}
    if ran:
        lines += ["", "| Client / lane | mu per validator, ms | One mu for all: p | p (Holm) |", "|---|---|---|---|"]
        for k, h in sorted(ran.items()):
            mus = ", ".join(f"`{v[:8]}` {m:.3g}" for v, m in zip(h["validators"], h["mu_ms"]))
            lines.append(f"| {k} | {mus} | {h['p']:.2g} | {h['p_holm']:.2g} |")
    lines += ["", "| Client | Lane | s50, ms | s10, ms |", "|---|---|---|---|"]
    for f in fams:
        for lane in ("VIP", "ECO"):
            c = by.get((f, lane))
            if c:
                fmt = lambda x: "∞" if x in ("inf", None) or (isinstance(x, float) and math.isinf(x)) else f"{x:.3g}"
                lines.append(f"| {f} | {lane} | {fmt(c['s50_ms'])} | {fmt(c['s10_ms'])} |")
    lines += ["", "| Test | Family | Statistic | p | p (Holm) | Verdict |", "|---|---|---|---|---|---|"]
    for t in conf:
        if t.get("run"):
            stat = f"mû {t['mu_hat_ms']:.3g} vs {t['claim_ms']:g} ms" if t["kind"] == "claim" else f"ratio {t['ratio']:.3g}"
            lines.append(f"| {t['id']} | {t['family']} | {stat} | {t['p']:.2g} | {t['p_holm']:.2g} | {'reject' if t['reject'] else 'keep'} |")
        else:
            lines.append(f"| {t['id']} | {t['family']} | not run ({t.get('why')}) | | | |")
    if inside:
        lines += ["", "| Robustness: test on pairs inside one slot | Family | n | mû vs claim | p |", "|---|---|---|---|---|"]
        for tid, r in sorted(inside.items()):
            if r.get("run"):
                lines.append(f"| {tid} | {r['family']} | {r['n']} | {r['mu_hat_ms']:.3g} vs {r['claim_ms']:g} ms | {r['p']:.2g} |")
            else:
                lines.append(f"| {tid} | {r['family']} | {r['n']} | not run | |")
    lines += ["", "| Client | C2: X first (n) | FEE at s ≤ 1 ms: B first (n) |", "|---|---|---|"]
    for r in kc["families"]:
        a = f"{r['c2_share'] * 100:.0f}% ({r['c2_n']})" if r["c2_n"] else "—"
        b = f"{r['fee0_share'] * 100:.0f}% ({r['fee0_n']})" if r["fee0_n"] else "—"
        lines.append(f"| {r['family']} | {a} | {b} |")
    return "\n".join(lines) + "\n"


def reproduce(raw, out, fig_dir, boot_reps=200, placebo_reps=100, mode="live"):
    runs = rawio.run_dirs(raw, mode)
    print(f"{len(runs)} {mode} runs under {raw}")
    df = pairs.build(raw, mode)
    os.makedirs(out, exist_ok=True)
    if len(df):
        df["window_key"] = df["run_id"] + "/" + df["window_id"].astype(str)
        df.astype(WHOLE_COLUMNS).to_csv(os.path.join(out, "pairs.csv"), index=False, float_format="%.6g", lineterminator="\n")
    dump(losses(df), os.path.join(out, "losses.json"))
    kc = key_control(df)
    dump(kc, os.path.join(out, "key_control.json"))
    if not len(df):
        print("no pairs: nothing to fit")
        return
    cp = pairs.clock_pairs(df)
    print(f"{len(df)} pairs, {int(df['complete'].sum())} complete, {len(cp)} in the clock fits")

    # step 2: descriptive curves
    curve_rows = []
    for (fam, lane), g in cp.groupby(["family", "lane"]):
        for r in figures.binned_curve(g["s_ms"].to_numpy(float), g["y"].to_numpy(float), S_EDGES):
            curve_rows.append({"family": fam, "lane": lane, **r})
    dump(curve_rows, os.path.join(out, "curves.json"))

    # steps 3, 5, 6, 11: fits per cell (in parallel)
    jobs = [(fam, lane, g["s_ms"].to_numpy(float), g["y"].to_numpy(float)) for (fam, lane), g in cp.groupby(["family", "lane"])
            if len(g) >= MIN_FIT]
    with _pool() as ex:
        cells_fit = sorted(ex.map(_fit_cell_job, jobs), key=lambda c: (c["family"], c["lane"]))
        bjobs = [((fam, lane), g[["s_ms", "y", "window_key"]], boot_reps, 11) for (fam, lane), g in cp.groupby(["family", "lane"])
                 if len(g) >= MIN_FIT] if boot_reps else []
        bres = dict(ex.map(_boot_job, bjobs)) if bjobs else {}
    for c in cells_fit:
        c["boot"] = bres.get((c["family"], c["lane"]))
    dump({"min_pairs": MIN_FIT, "sigma_ms": fit.SIGMA_MS, "cells": cells_fit}, os.path.join(out, "fits.json"))
    print("fits done")

    # step 4: confirmatory family with Holm
    cell_data = pairs.cells(df)
    conf = hypotheses.run_confirmatory({k: v for k, v in cell_data.items() if len(v[1]) >= MIN_FIT})
    lanes_boot = {}
    if boot_reps:
        for fam in ("AgaveBam", "HarmonicAgave", "HarmonicFiredancer", "JitoLabs", "Firedancer"):
            gv, ge = cp[(cp["family"] == fam) & (cp["lane"] == "VIP")], cp[(cp["family"] == fam) & (cp["lane"] == "ECO")]
            if len(gv) >= MIN_FIT and len(ge) >= MIN_FIT:
                lanes_boot[fam] = boot.lane_ratio_ci(gv, ge, reps=max(20, boot_reps // 4), seed=5)
    dump({"tests": conf, "alpha": hypotheses.ALPHA, "lane_ratio_bootstrap": lanes_boot}, os.path.join(out, "confirmatory.json"))
    print("confirmatory done")

    # read-outs of the amendment: per validator, simultaneous pairs, late overtakes, heterogeneity,
    # claim tests inside one slot
    with _pool() as ex:
        vrows = validators(df, ex)
    dump(vrows, os.path.join(out, "validators.json"))
    dump(simultaneous(df), os.path.join(out, "simultaneous.json"))
    late = late_overtakes(df)
    dump(late, os.path.join(out, "late.json"))
    het = heterogeneity(df)
    dump(het, os.path.join(out, "heterogeneity.json"))
    inside = claims_inside_slot(df)
    dump(inside, os.path.join(out, "claims_inside_slot.json"))
    print("read-outs done")

    # exploratory
    dump(phase_split(df), os.path.join(out, "phase.json"))
    dump(sessions(df), os.path.join(out, "sessions.json"))
    dump(buffer_sensitivity(df), os.path.join(out, "buffer_sensitivity.json"))
    dump(rank_summary(df), os.path.join(out, "rank.json"))
    fee = df[df["complete"] & df["timed"] & (df["series"] == "FEE")]
    buf = fee[fee["a_since_window_ms"] < -SURELY_BUFFERED_MS]
    zone = fee[(fee["a_since_window_ms"] >= -SURELY_BUFFERED_MS) & (fee["a_since_window_ms"] < 0)]
    dump({"written_before_first_shred_ms": SURELY_BUFFERED_MS, "n": len(buf), "b_ahead": int(buf["y"].sum()) if len(buf) else 0,
          "share": float(buf["y"].mean()) if len(buf) else None, "boundary_zone_n": len(zone),
          "boundary_zone_share": float(zone["y"].mean()) if len(zone) else None}, os.path.join(out, "buffered.json"))
    pl = {"lexicographic": placebo.lexicographic(df)}
    if placebo_reps:
        big = max(cp.groupby(["family", "lane"]), key=lambda kv: len(kv[1]))
        pl["shuffle_s"] = {"cell": "/".join(big[0]), **placebo.shuffle_s(big[1], reps=placebo_reps)}
        fam_big = cp["family"].value_counts().index[0]
        sl = placebo.shuffle_lanes(cp[cp["family"] == fam_big], reps=max(10, placebo_reps // 2))
        sl.pop("p_values", None)
        pl["shuffle_lanes"] = {"family": fam_big, **sl}
    dump(pl, os.path.join(out, "placebo.json"))
    print("placebo done")

    with open(os.path.join(out, "results.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(results_md(clean(cells_fit), clean(conf), clean(kc), clean(late), clean(het), clean(vrows), clean(inside)))

    # figures
    mk = market(runs)
    probes = [{"label": lab, "lane": lane, "key": k, "percentile": 100.0 * float(np.mean(mk < k)) if len(mk) else 0.0}
              for lab, lane, k in PROBES]
    cf_clean = clean(cells_fit)
    for c in cf_clean:  # inf comes back as a string from clean()
        c["mu_ci"]["hi"] = float("inf") if c["mu_ci"]["hi"] == "inf" else c["mu_ci"]["hi"]
    paths = figures.shutter(cf_clean, fig_dir) + figures.curves(clean(curve_rows), cf_clean, fig_dir)
    paths += figures.two_verdicts(clean(two_verdicts_data(df)), fig_dir) + figures.vip_lane(mk, clean(probes), fig_dir)
    print(f"{len(paths)} figures -> {fig_dir}")
    print(os.path.join(out, "results.md"))


def pilot_grids(raw, runs, out):
    """mu_hat per family and lane from pilot runs, for `itb freeze-grids`."""
    df = pairs.build(raw, "live")
    if runs:
        df = df[df["run_id"].isin(runs)]
    res = {}
    for (fam, lane), (s, y) in pairs.cells(df).items():
        if len(y) >= 10:
            f = fit.fit_cell(s, y)
            res.setdefault(fam, {})[lane] = round(float(f.mu[0]), 2)
            print(f"{fam:<20} {lane}  n {len(y):>4}  mu_hat {f.mu[0]:.1f} ms  k {f.k[0]:.1f}")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
    print(out)
