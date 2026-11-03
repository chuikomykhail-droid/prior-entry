"""`python -m analysis pilot`: the pilot's checks before the main run (PLAN §6.11).

  1. landing      complete pairs (both probes at the targeted leader, in its window) >= 60% of the sent
                  FEE and REV pairs, in each lane
  2. timing       median |actual s - planned s| < 0.5 ms
  3. window       >= 70% of the sent FEE and REV pairs complete and not buffered
  4. QUIC         no validator loses more than 30% of its windows or pairs to connection errors
  5. rank         median rank of our probes in their blocks: VIP >= 95th percentile, ECO 40th-75th
  6. c            share of the sent FEE and REV pairs that entered the clock fits (q = 0.5 / c, §6.6)
  7. accounting   fees of the landed probes against the ledger's reservations for the run

plus a diagnostic of rpc_lag_ms: a probe written after its landing slot had ended (by our clock) is
impossible, so a share of those above ~0 means the slot starts are placed too early.
"""
import json
import os
from collections import Counter, defaultdict

import numpy as np

from . import pairs, rawio

LANDING_MIN, TIMING_MAX_MS, WINDOW_MIN, QUIC_MAX = 0.60, 0.5, 0.70, 0.30
RANK = {"VIP": (95.0, 100.0), "ECO": (40.0, 75.0)}
CONN_ERRORS = ("open stream", "reconnect", "no connection", "write")


def quic_losses(runs):
    """Per validator: windows, windows without a connection, pairs, pairs lost to stream errors."""
    out = defaultdict(Counter)
    for run in runs:
        for w in run["windows"]:
            v = out[w["leader"]]
            v["windows"] += 1
            v["windows_no_connection"] += int(bool(w.get("connect_error")) or w.get("skipped") == "no connection")
        for t in run["txs"]:
            if t.get("role") != "A":
                continue
            v = out[t["leader"]]
            v["pairs"] += 1
            err = t.get("error") or ""
            v["pairs_stream_error"] += int(err.startswith(CONN_ERRORS))
    rows = {}
    for leader, v in sorted(out.items()):
        wl = v["windows_no_connection"] / v["windows"] if v["windows"] else 0.0
        pl = v["pairs_stream_error"] / v["pairs"] if v["pairs"] else 0.0
        rows[leader] = {**v, "window_loss": wl, "pair_loss": pl, "ok": wl <= QUIC_MAX and pl <= QUIC_MAX}
    return rows


def reserved_by_run(ledger_path, run_ids):
    total = Counter()
    for r in rawio.read_jsonl(ledger_path):
        if r.get("run_id") in run_ids:
            total[r["run_id"]] += r.get("lamports", 0)
    return dict(total)


def check(raw, session, runs=None, ledger="data/ledger.jsonl", out=None):
    dirs = rawio.run_dirs(raw, "live")
    loaded = [rawio.load_run(d) for d in dirs]
    loaded = [r for r in loaded if (runs and r["meta"].get("run_id") in runs) or (not runs and r["meta"].get("session") == session)]
    if not loaded:
        raise SystemExit(f"no live runs of session {session!r} under {raw}")
    ids = [r["meta"]["run_id"] for r in loaded]
    df = pairs.build(raw, "live")
    df = df[df["run_id"].isin(ids)]
    sent = df[df["sent"]]
    clock_series = sent[sent["series"].isin(["FEE", "REV"])]
    res = {"runs": ids, "sent_pairs": int(len(sent)), "checks": {}}

    landing = {}
    for lane, g in clock_series.groupby("lane"):
        landing[lane] = {"sent": int(len(g)), "complete": int(g["complete"].sum()), "share": float(g["complete"].mean())}
    res["checks"]["1_landing"] = {"by_lane": landing, "ok": all(v["share"] >= LANDING_MIN for v in landing.values()),
                                  "by_family_lane": {f"{f}/{l}": float(g["complete"].mean()) for (f, l), g in clock_series.groupby(["family", "lane"])},
                                  "excluded": {str(k): int(v) for k, v in clock_series["excluded"].value_counts().items()}}

    err = (sent["s_ms"] - sent["s_planned_ms"]).abs().dropna()
    res["checks"]["2_timing"] = {"n": int(len(err)), "median_abs_err_ms": float(err.median()) if len(err) else None,
                                 "p99_abs_err_ms": float(err.quantile(0.99)) if len(err) else None,
                                 "ok": bool(len(err)) and float(err.median()) < TIMING_MAX_MS}

    inwin = clock_series["complete"] & ~clock_series["buffered"]
    res["checks"]["3_window"] = {"share_complete_not_buffered": float(inwin.mean()) if len(clock_series) else None,
                                 "buffered_among_complete": float(clock_series.loc[clock_series["complete"], "buffered"].mean())
                                 if clock_series["complete"].any() else None,
                                 "ok": bool(len(clock_series)) and float(inwin.mean()) >= WINDOW_MIN}

    q = quic_losses(loaded)
    res["checks"]["4_quic"] = {"by_validator": q, "ok": all(v["ok"] for v in q.values())}

    comp = df[df["complete"]]
    rank = {}
    for lane, g in comp.groupby("lane"):
        lo, hi = RANK.get(lane, (0.0, 100.0))
        ra, rb = float(g["rank_a"].median()), float(g["rank_b"].median())
        rank[lane] = {"n": int(len(g)), "rank_a_median": ra, "rank_b_median": rb, "ok": lo <= ra <= hi and lo <= rb <= hi}
    res["checks"]["5_rank"] = {"by_lane": rank, "ok": bool(rank) and all(v["ok"] for v in rank.values())}

    c = float(inwin.mean()) if len(clock_series) else None
    res["checks"]["6_c"] = {"c": c, "q": min(1.0, 0.5 / c) if c else None,
                            "by_family": {f: float((g["complete"] & ~g["buffered"]).mean()) for f, g in clock_series.groupby("family")}}

    fees = defaultdict(int)
    sig_run = {t["signature"]: r["meta"]["run_id"] for r in loaded for t in r["txs"]}
    for r in loaded:
        for l in r["landings"]:
            if l.get("fee") is not None and l["signature"] in sig_run:
                fees[sig_run[l["signature"]]] += int(l["fee"])
    reserved = reserved_by_run(ledger, set(ids))
    res["checks"]["7_accounting"] = {"landed_fees": dict(fees), "reserved": reserved,
                                     "ok": all(fees.get(i, 0) <= reserved.get(i, 0) for i in ids),
                                     "note": "the balance drop must equal the landed fees: compare `itb balances` before and after"}

    both = comp[comp["a_slot"].notna() & comp["slot_a"].notna()]
    late = both["a_slot"].astype(float) > both["slot_a"].astype(float)
    res["diagnostic_rpc_lag"] = {"n": int(len(both)), "a_written_after_its_slot_ended": int(late.sum()),
                                 "share": float(late.mean()) if len(both) else None}

    for k, v in res["checks"].items():
        mark = {True: "ok", False: "FAIL", None: "--"}[v.get("ok")]
        print(f"{k:<14} {mark:<5} " + json.dumps({kk: vv for kk, vv in v.items() if kk in
              ("by_lane", "median_abs_err_ms", "share_complete_not_buffered", "c", "q", "landed_fees", "reserved")}, default=float))
    bad = {k: v for k, v in q.items() if not v["ok"]}
    if bad:
        print("QUIC losses above 30%:", {k[:8]: (v["window_loss"], v["pair_loss"]) for k, v in bad.items()})
    print("rpc_lag diagnostic:", res["diagnostic_rpc_lag"])
    if out:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(res, fh, indent=1, sort_keys=True, default=lambda x: x.item() if isinstance(x, np.generic) else str(x))
            fh.write("\n")
        print(out)
    return res
