"""`python -m analysis reproduce`: raw runs -> data/derived and figures/, the steps of PLAN §8.2.

Everything written is rounded to 6 significant digits and sorted, so a recomputation on another
machine gives the same bytes (`python -m analysis check`).
"""
import concurrent.futures as cf
import json
import math
import os

import numpy as np

from . import boot, figures, fit, hypotheses, pairs, placebo, rawio

S_EDGES = [-1000, 0, 1, 2.5, 5, 8, 12, 18, 25, 35, 50, 75, 110, 160, 230, 330, 2000]
MIN_FIT = 40  # pairs per cell for a parametric fit
MIN_VALIDATOR_FIT = 60


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
                                         "excluded": {str(k): int(v) for k, v in g["excluded"].value_counts().items()}}
    return out


def validators(df, cells_fit):
    """Step 12: the bounty's three questions per validator."""
    rows = []
    cp = pairs.clock_pairs(df)
    for (leader, lane), g in cp.groupby(["leader", "lane"]) if len(cp) else []:
        s, y = g["s_ms"].to_numpy(float), g["y"].to_numpy(float)
        row = {"validator": leader, "family": g["family"].iloc[0], "lane": lane, "n": len(g)}
        if len(g) >= MIN_VALIDATOR_FIT:
            f = fit.fit_cell(s, y)
            sh = fit.compare_shapes(s, y)
            row.update({"mu_ms": f.mu[0], "k": f.k[0], "eps1": f.eps1[0], "eps2": f.eps2[0],
                        "rule": "key within mu, arrival beyond" if sh["rule_exists_p"] < 0.05 else "no rule detected",
                        "strictness": f"eps1 {f.eps1[0]:.2f}, eps2 {f.eps2[0]:.2f}, k {f.k[0]:.1f}",
                        "rule_exists_p": sh["rule_exists_p"]})
        rows.append(row)
    return rows


def phase_split(df):
    """Step 7 (exploratory): A in the first 30 ms of its slot vs the rest."""
    out = {}
    cp = pairs.clock_pairs(df)
    for (fam, lane), g in cp.groupby(["family", "lane"]) if len(cp) else []:
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
    """Fig. 3: the validator with the most clock pairs: s ~ 0, s ~ 50 ms in VIP and in ECO."""
    cp = pairs.clock_pairs(df)
    if not len(cp):
        return None
    leader = cp["leader"].value_counts().index[0]
    g = cp[cp["leader"] == leader]
    bars = []
    for label, lane, lo, hi in (("s ~ 0 ms, VIP", "VIP", -0.5, 1.0), ("s ~ 50 ms, VIP", "VIP", 35, 70), ("s ~ 50 ms, ECO", "ECO", 35, 70)):
        h = g[(g["lane"] == lane) & (g["s_ms"] >= lo) & (g["s_ms"] < hi)]
        k, n = int(h["y"].sum()), len(h)
        if n:
            a, b = fit.wilson(k, n)
            bars.append({"label": label, "lane": lane, "n": n, "share": k / n, "lo": a, "hi": b})
    return {"validator": leader, "family": g["family"].iloc[0], "bars": bars}


def market(raw_runs):
    """Keys of all foreign non-vote transactions in the blocks we read, for Fig. 4."""
    keys = []
    for d in raw_runs:
        for b in rawio.read_jsonl(os.path.join(d, "blocks.jsonl.gz")):
            k, vote, _ = pairs.block_keys(b)
            keys.append(k[~vote])
    return np.concatenate(keys) if keys else np.array([])


PROBES = [("VIP cheap A", "VIP", 1_549_586), ("VIP dear B", "VIP", 2_840_909), ("ECO cheap A", "ECO", 14_900), ("ECO dear B", "ECO", 27_317)]


def results_md(cells_fit, conf, kc, stake=None):
    """The README / REPORT tables, filled from the fits."""
    def mu_txt(c):
        if not c:
            return "—"
        ci = c["mu_ci"]
        hi = "∞" if ci["hi"] in ("inf", float("inf")) or (isinstance(ci["hi"], float) and math.isinf(ci["hi"])) else f"{ci['hi']:.3g}"
        lo = f"<{ci['lo']:.3g}" if ci.get("lo_censored") else f"{ci['lo']:.3g}"
        return f"{c['mu_ms']:.3g} [{lo}–{hi}]"
    by = {(c["family"], c["lane"]): c for c in cells_fit}
    tests = {t["id"]: t for t in conf}
    fams = sorted({c["family"] for c in cells_fit}, key=lambda f: (f not in figures.CLAIMS, f))
    lane_test = {"AgaveBam": "L1", "HarmonicAgave": "L2", "HarmonicFiredancer": "L3", "JitoLabs": "L4", "Firedancer": "L5"}
    claim_test = {"AgaveBam": "V1", "HarmonicAgave": "V2", "HarmonicFiredancer": "V3"}
    lines = ["| Client | Shutter, VIP lane, ms [95%] | Shutter, typical lane, ms [95%] | Vendor says | Matches? | Clock or queue |",
             "|---|---|---|---|---|---|"]
    for f in fams:
        claim = figures.CLAIMS.get(f)
        v = tests.get(claim_test.get(f, ""), {})
        lt = tests.get(lane_test.get(f, ""), {})
        match = "—" if not v.get("run") else ("no" if v.get("reject") else "yes")
        cq = "—" if not lt.get("run") else (f"queue (ECO ×{lt['ratio']:.2g})" if lt.get("reject") else "clock (lanes equal)")
        lines.append(f"| {f} | {mu_txt(by.get((f, 'VIP')))} | {mu_txt(by.get((f, 'ECO')))} | {f'{claim:g} ms' if claim else '—'} | {match} | {cq} |")
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
        df.to_csv(os.path.join(out, "pairs.csv"), index=False, float_format="%.6g", lineterminator="\n")
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

    # exploratory
    dump(validators(df, cells_fit), os.path.join(out, "validators.json"))
    dump(phase_split(df), os.path.join(out, "phase.json"))
    dump(sessions(df), os.path.join(out, "sessions.json"))
    dump(rank_summary(df), os.path.join(out, "rank.json"))
    buf = df[df["complete"] & df["buffered"] & (df["series"] == "FEE")]
    dump({"n": len(buf), "b_ahead": int(buf["y"].sum()) if len(buf) else 0,
          "share": float(buf["y"].mean()) if len(buf) else None}, os.path.join(out, "buffered.json"))
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
        fh.write(results_md(clean(cells_fit), clean(conf), clean(kc)))

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
