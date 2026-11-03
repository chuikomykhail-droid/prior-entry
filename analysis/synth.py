"""Synthetic raw runs with known clocks, written in exactly the format of `itb run` + `itb collect`
(meta.json, windows.jsonl, txs.jsonl, slots.jsonl, gossip.jsonl, landings.jsonl,
blocks.jsonl.gz). The whole pipeline runs on them unchanged, and `check_recovery` compares what
it finds with the truth below.

What is simulated, per window: the true slot starts (with jitter), our slot-clock prediction
error (so some pairs land "buffered"), the actual send gap, one batch process per lane (shared
when the lanes have the same clock), lapses, losses, foreign transactions with market-like keys
around our probes, and the producer.
"""
import gzip
import json
import math
import os
import random as pyrandom
import shutil

import numpy as np

from . import figures


B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
SLOT_MS = 200.0
NTP_OFFSET_MS = 560.0
RPC_LAG_MS = 100.0
T0_UNIX_MS = 1_794_000_000_000.0  # 2026-11-08, after Alpenglow
FIRST_SLOT = 465_000_000

# family: (class, validators, {lane: (mechanism, mu, k)}, eps1, eps2, landing share)
# Queues use exponential waits: their survival P(W > s) is then exactly a renewal G with the same mu.
# (A gamma wait with k > 1 is S-shaped, which no single clock produces: the case of PLAN §5.7.)
TRUTH = {
    "AgaveBam": ("main", 2, {"VIP": ("clock", 20.0, 200.0), "ECO": ("clock", 20.0, 200.0)}, 0.03, 0.05, 0.8),
    "HarmonicAgave": ("main", 2, {"VIP": ("clock", 50.0, 200.0), "ECO": ("clock", 50.0, 200.0)}, 0.03, 0.05, 0.8),
    "HarmonicFiredancer": ("main", 2, {"VIP": ("clock", 15.0, 30.0), "ECO": ("clock", 15.0, 30.0)}, 0.02, 0.04, 0.8),
    "JitoLabs": ("main", 2, {"VIP": ("queue", 3.0, 1.0), "ECO": ("queue", 9.0, 1.0)}, 0.03, 0.05, 0.75),
    "Firedancer": ("main", 2, {"VIP": ("queue", 10.0, 1.0), "ECO": ("queue", 25.0, 1.0)}, 0.04, 0.06, 0.75),
    "FireBAM": ("small", 1, {"VIP": ("clock", 20.0, 200.0), "ECO": ("clock", 20.0, 200.0)}, 0.03, 0.05, 0.8),
    "Rakurai": ("small", 2, {"VIP": ("queue", 5.0, 1.0), "ECO": ("queue", 5.0, 1.0)}, 0.03, 0.05, 0.8),
    "Agave": ("small", 2, {"VIP": ("queue", 2.0, 1.0), "ECO": ("queue", 4.0, 1.0)}, 0.03, 0.05, 0.8),
}
QUOTA = {"main": {("FEE", "VIP"): 160, ("FEE", "ECO"): 160, ("REV", "VIP"): 15, ("REV", "ECO"): 15, ("CTRL_C2", "VIP"): 15},
         "small": {("FEE", "VIP"): 50, ("FEE", "ECO"): 50, ("REV", "VIP"): 5, ("REV", "ECO"): 5, ("CTRL_C2", "VIP"): 10}}
PAIRS_PER_WINDOW = {"main": 4, "small": 6}
PARAMS = {  # (cu_limit, cu_price, loaded_data) of A and B, as in itb/src/design.rs
    ("FEE", "VIP"): ((600, 833_333, 32768), (600, 5_000_000, 32768)),
    ("FEE", "ECO"): ((200_000, 2_500, 32768), (200_000, 15_000, 32768)),
    ("CTRL_C2", "VIP"): ((600, 833_333, 32768), (600, 5_000_000, 64 * 1024 * 1024)),
}
PARAMS[("REV", "VIP")] = PARAMS[("FEE", "VIP")]
PARAMS[("REV", "ECO")] = PARAMS[("FEE", "ECO")]
# market: log10 of reward/cost keys of foreign transactions (median ~15k, ~2% above 1.5M)
MARKET_LOG10 = (4.15, 0.75)


def _b58(rng, n):
    return "".join(rng.choice(B58) for _ in range(n))


def _utc(ms):
    import datetime as dt
    t = dt.datetime.fromtimestamp(math.floor(ms / 1e3), dt.timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(round(ms * 1000)) % 1_000_000:06d}000+00:00"


def _priority_fee(cu_limit, cu_price):
    return -(-cu_price * cu_limit // 1_000_000)


def _plan_window(rng, cls, left):
    """Cells of one window: FEE split evenly between lanes, REV/C2 by what is left."""
    n = PAIRS_PER_WINDOW[cls]
    fee = left[("FEE", "VIP")] + left[("FEE", "ECO")]
    other = sum(v for c, v in left.items() if c[0] != "FEE")
    if fee + other == 0:
        return []
    n_other = min(other, sum(rng.random() < other / (fee + other) for _ in range(n)))
    picks = []
    for j in range(n - n_other):
        lane = ("VIP", "ECO")[j % 2]
        if left[("FEE", lane)] == 0:
            lane = "ECO" if lane == "VIP" else "VIP"
        if left[("FEE", lane)] > 0:
            picks.append(("FEE", lane))
            left[("FEE", lane)] -= 1
    while len(picks) < n:
        cands = [c for c, v in left.items() if v > 0 and (c[0] != "FEE" or len(picks) >= n - n_other)]
        if not cands:
            break
        c = cands[rng.integers(len(cands))] if len(cands) > 1 else cands[0]
        picks.append(c)
        left[c] -= 1
    rng.shuffle(picks)
    return picks


def _gaps(rng, cell, mu, fam):
    """The main-run grid as amended (itb/src/design.rs, GridSpec::main_run): 10% at s = 0, 15% in
    [1.5 T, 150] ms for a family with a published period T, the rest 70% uniform / 30% base grid."""
    series, lane = cell
    if series == "REV":
        return float(rng.choice([-2, -5, -10, -20]))
    if series == "CTRL_C2":
        return float(rng.choice([-0.3, 0.3]))
    u, t = rng.random(), figures.CLAIMS.get(fam)
    if u < 0.1:
        return 0.0
    if t and u < 0.25:
        return round(float(rng.uniform(1.5 * t, 150.0)), 1)
    hi = min(max(2 * mu, 10.0), 300.0)
    if rng.random() < 0.7:
        return round(float(rng.uniform(0, hi)), 1)
    pts = [0, 1, 2, 3, 4, 6, 8, 10, 12, 15, 18, 21, 25, 30, 35, 40, 50, 60, 80, 100, 150] + ([200, 300] if lane == "ECO" else [])
    return float(rng.choice(pts))


def _boundaries(rng, mu, k, t0, t1):
    t = t0 - 20 * mu - rng.uniform(0, mu)
    pts = []
    while t < t1:
        t += rng.gamma(k, mu / k)
        if t >= t0:
            pts.append(t)
    return np.array(pts)


def write_runs(out, seed=7, sessions=2):
    """Writes `sessions` synthetic runs under `out` (replacing it) and returns the truth."""
    rng = np.random.default_rng(seed)
    prng = pyrandom.Random(seed)
    if os.path.isdir(out):
        shutil.rmtree(out)
    validators = {f: [_b58(prng, 44) for _ in range(TRUTH[f][1])] for f in TRUTH}
    left = {f: dict(QUOTA[TRUTH[f][0]]) for f in TRUTH}
    per_session = {f: {c: [v // sessions + (1 if i < v % sessions else 0) for i in range(sessions)] for c, v in left[f].items()} for f in TRUTH}
    slot = FIRST_SLOT
    t_true = T0_UNIX_MS
    for si in range(sessions):
        run_id = f"2026110{8 + si}T120000Z-live"
        d = os.path.join(out, run_id)
        os.makedirs(d)
        sess_left = {f: {c: per_session[f][c][si] for c in per_session[f]} for f in TRUTH}
        targets = [{"identity": v, "client_id": f, "version": "4.4.0" if "Fire" not in f else "26.10.5",
                    "tpu_quic": "10.0.0.1:8009", "stake": 1} for f in TRUTH for v in validators[f]]
        meta = {"run_id": run_id, "mode": "live", "session": f"S{si + 1}", "started_utc": _utc(t_true), "synthetic": True,
                "seed": seed, "ntp_offset_ms": NTP_OFFSET_MS, "timing": {"rpc_lag_ms": RPC_LAG_MS, "start_lo_ms": 120.0,
                                                                         "start_hi_ms": 650.0, "anchor": "predicted"},
                "targets": targets, "gossip_snapshot_utc": _utc(t_true), "network": {"mainnet": True, "after_alpenglow": True}}
        windows, txs, slots, landings, blocks, gossip = [], [], [], [], [], []
        fams = [f for f in TRUTH]
        while any(sum(sess_left[f].values()) for f in fams):
            fam = fams[rng.integers(len(fams))]
            if not sum(sess_left[fam].values()):
                slot += 4
                t_true += 4 * SLOT_MS
                continue
            cls, _, lanes, e1, e2, p_land = TRUTH[fam]
            leader = validators[fam][rng.integers(len(validators[fam]))]
            starts = [t_true + i * SLOT_MS + rng.normal(0, 3) for i in range(5)]
            for i in range(4):
                slots.append({"slot": slot + i, "server_unix_ms": round(starts[i] + RPC_LAG_MS),
                              "local_unix_ms": starts[i] + RPC_LAG_MS + NTP_OFFSET_MS + 60})
            pred = starts[0] + rng.normal(40, 220)  # our anchor: the slot clock's prediction
            cells = _plan_window(rng, cls, sess_left[fam])
            win = {"run_id": run_id, "mode": "live", "window_id": slot, "leader": leader, "family": fam, "family_class": cls,
                   "version": "4.4.0", "first_slot": slot, "window_slots": 4, "anchor_mode": "predicted",
                   "predicted_start_utc": _utc(pred + NTP_OFFSET_MS), "pairs": len(cells)}
            windows.append(win)
            shared = lanes["VIP"] == lanes["ECO"]
            procs = {}
            block_txs = {}  # slot -> list of (order key time, row dict, signature or None)
            for j, cell in enumerate(cells):
                series, lane = cell
                mech, mu, k = lanes[lane]
                s = _gaps(rng, cell, lanes[lane][1], fam)
                if series == "CTRL_C2":
                    a_off = -300 + rng.uniform(-20, 20)
                else:
                    a_off = round(float(rng.uniform(120 + max(0, -s), 650 - max(0, s))), 1)
                ta = pred + a_off
                s_act = s + rng.normal(0, 0.12)
                tb = ta + s_act
                gap = s_act + rng.normal(0, 0.3)  # arrival gap
                # outcome
                if ta < starts[0] or series == "CTRL_C2":
                    # buffered: sorted by key at the window start; B (or Y for C2) has the larger key
                    behind_by_key = series != "CTRL_C2"  # FEE/REV: B ahead; C2: X (= A) ahead
                    mech_y = int(behind_by_key)
                elif gap <= 0:
                    mech_y = 1
                elif mech == "queue":
                    mech_y = int(rng.gamma(k, mu / k) > gap)
                else:
                    key = "shared" if shared else lane
                    if key not in procs:
                        procs[key] = _boundaries(rng, mu, k, starts[0] - 400, starts[0] + 1200)
                    b = procs[key]
                    mech_y = int(not np.any((b > ta) & (b <= ta + gap)))
                u = rng.random()
                y = 1 if u < e1 else 0 if u < e1 + e2 else mech_y
                payer = _b58(prng, 44)
                pa, pb = PARAMS[cell]
                sig_a, sig_b = _b58(prng, 88), _b58(prng, 88)
                base = {"run_id": run_id, "mode": "live", "window_id": slot, "pair_id": f"{slot}-{j}", "series": series, "lane": lane,
                        "a_offset_ms": a_off, "s_ms": s, "anchor": "predicted", "payer": payer, "leader": leader, "family": fam,
                        "version": "4.4.0", "tpu": "10.0.0.1:8009", "first_slot": slot, "window_slots": 4,
                        "s_actual_ms": round(s_act, 4), "shift_ms": 0.0, "sent": True, "error": None}
                for role, sig, pr, t in (("A", sig_a, pa, ta), ("B", sig_b, pb, tb)):
                    fee = 5000 + _priority_fee(pr[0], pr[1])
                    txs.append({**base, "role": role, "send_rank": int((role == "B") == (s >= 0)), "signature": sig,
                                "cu_limit": pr[0], "cu_price": pr[1], "loaded_data": pr[2], "priority_fee": fee - 5000,
                                "total_fee": fee, "write_utc": _utc(t + NTP_OFFSET_MS),
                                "a_write_us": None, "b_write_us": None})
                # landing
                if rng.random() > p_land:
                    continue
                t_land = max(ta, starts[0]) + rng.uniform(0, 30)
                sl = int(min(3, max(0, (t_land - starts[0]) // SLOT_MS)))
                order = rng.uniform(0, 1)
                first_sig, second_sig = (sig_b, sig_a) if y else (sig_a, sig_b)
                first_p, second_p = (pb, pa) if y else (pa, pb)
                block_txs.setdefault(slot + sl, []).append((order, first_sig, first_p))
                sl2 = sl if (y or rng.random() < 0.8) else min(3, sl + 1)
                block_txs.setdefault(slot + sl2, []).append((order + 1e-6 + rng.uniform(0, 0.05) * (sl2 == sl), second_sig, second_p))
            for sl, ours in block_txs.items():
                n_foreign = int(rng.integers(80, 200))
                rows = [(rng.uniform(0, 1.06), None, None) for _ in range(n_foreign)] + ours
                rows.sort(key=lambda r: r[0])
                cols = {k: [] for k in ("fee", "sigs", "writable", "data_bytes", "cu_limit", "cu_limit_set", "cu_price",
                                        "data_limit", "cu_consumed", "ok", "vote")}
                for i, (_, sig, pr) in enumerate(rows):
                    if sig is None:
                        vote = rng.random() < 0.15
                        cu = 200_000 if rng.random() < 0.5 else int(rng.integers(1_000, 1_400_000))
                        cost = 720 + 300 * 3 + 50 + cu + 8 * 2048
                        key = 10 ** rng.normal(*MARKET_LOG10)
                        fee = int(2500 + key * (cost + 1) / 1e6) + 2500
                        row = (fee, 1, 3, 200, cu, 1, 0, 64 * 1024 * 1024, cu // 3, 1, int(vote))
                    else:
                        fee = 5000 + _priority_fee(pr[0], pr[1])
                        row = (fee, 1, 2, 31, pr[0], 1, pr[1], pr[2], 600, 1, 0)
                        landings.append({"signature": sig, "slot": sl, "index": i, "fee": fee, "cu_consumed": 600, "ok": True,
                                         "err": None, "producer": leader, "leader": leader})
                    for kname, v in zip(cols, row):
                        cols[kname].append(v)
                blocks.append({"slot": sl, "parent_slot": sl - 1, "block_time": int(starts[0] / 1e3), "producer": leader,
                               "leader": leader, "n_tx": len(rows), "tx": cols})
            if len(windows) % 75 == 0:
                gossip.append({"utc": _utc(t_true + NTP_OFFSET_MS), "targets": targets})
            slot += 4 + int(rng.integers(0, 3)) * 4
            t_true = starts[0] + (slot - win["first_slot"]) * SLOT_MS
        for name, rows in (("windows.jsonl", windows), ("txs.jsonl", txs), ("slots.jsonl", slots), ("gossip.jsonl", gossip),
                           ("landings.jsonl", landings)):
            with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r) + "\n")
        with gzip.open(os.path.join(d, "blocks.jsonl.gz"), "wt", encoding="utf-8") as fh:
            for b in sorted(blocks, key=lambda b: b["slot"]):
                fh.write(json.dumps(b) + "\n")
        with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=1)
        t_true += 8 * 3600 * 1000  # the next session starts 8 h later
        slot += int(8 * 3600 * 1000 / SLOT_MS)
        print(f"{d}: {len(windows)} windows, {len(txs) // 2} pairs, {len(landings)} landings")
    truth = {f: {"lanes": {l: {"mechanism": m, "mu_ms": mu, "k": k} for l, (m, mu, k) in TRUTH[f][2].items()},
                 "eps1": TRUTH[f][3], "eps2": TRUTH[f][4]} for f in TRUTH}
    with open(os.path.join(out, "truth.json"), "w", encoding="utf-8") as fh:
        json.dump(truth, fh, indent=1)
    return truth


EXPECTED = {"V1": False, "V2": False, "V3": True, "E1": True, "L1": False, "L2": False, "L3": False, "L4": True, "L5": True}


def check_recovery(truth, derived):
    """Does the pipeline find the truth? Every main cell's 95% interval should cover the true mu
    (allowing one miss in ten), and every confirmatory verdict should match the truth."""
    with open(os.path.join(derived, "fits.json"), encoding="utf-8") as fh:
        fits = json.load(fh)
    with open(os.path.join(derived, "confirmatory.json"), encoding="utf-8") as fh:
        conf = json.load(fh)
    covered, total = 0, 0
    print(f"{'family':<20}{'lane':<5}{'true mu':>9}{'mu hat':>9}  95% interval")
    for c in fits["cells"]:
        t = truth.get(c["family"], {}).get("lanes", {}).get(c["lane"])
        if not t:
            continue
        ci = c["mu_ci"]
        ok = ci["lo"] <= t["mu_ms"] <= ci["hi"]
        total += 1
        covered += ok
        print(f"{c['family']:<20}{c['lane']:<5}{t['mu_ms']:>9.1f}{c['mu_ms']:>9.2f}  [{ci['lo']:.2f}, {ci['hi']:.2f}] {'ok' if ok else 'MISS'}")
    verdicts_ok = True
    for r in conf["tests"]:
        exp = EXPECTED.get(r["id"])
        got = r.get("reject")
        good = got == exp
        verdicts_ok &= good
        print(f"{r['id']:<4}{r['family']:<40} p_holm {r.get('p_holm', float('nan')):.2g}  reject {got}  expected {exp}  {'ok' if good else 'WRONG'}")
    ok = covered >= math.floor(0.9 * total) and verdicts_ok
    print(f"intervals cover the truth in {covered} of {total} cells; verdicts {'all as expected' if verdicts_ok else 'NOT as expected'}")
    print("RECOVERY OK" if ok else "RECOVERY FAILED")
    return ok
