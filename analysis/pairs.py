"""From raw runs to one row per pair (PLAN §6.9, §8.1).

Cleaning and attribution, as pre-registered:
  1. a pair is complete when both probes landed, executed without error, in blocks of the same
     producer, that producer is the window's leader and both slots are inside the window;
  2. the family is the client id of the producer in the gossip snapshot nearest to the window;
  3. "buffered" pairs (A written before the window started) do not enter the clock fits;
  4. s is the actual gap, from the two stream-write timestamps;
  5. everything else stays in the table with the reason it was excluded.

Times: our writes are on the local clock; the true time is local minus the NTP offset in
meta.json. A slot starts `rpc_lag_ms` before the RPC node's own first-shred timestamp.
"""
import bisect
import math
from collections import defaultdict

import numpy as np
import pandas as pd

from . import rawio

BASE_REWARD_PER_SIG = 2500  # unburned half of the 5000-lamport base fee


def utc_ms(s):
    """RFC 3339 with up to nanoseconds -> unix ms (float)."""
    if not s:
        return math.nan
    import datetime as dt
    if "." not in s:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1e3
    head, _, rest = s.partition(".")
    frac, tz = rest, "+00:00"
    for sign in ("+", "-", "Z"):
        if sign in rest:
            i = rest.index(sign)
            frac, tz = rest[:i], rest[i:]
            break
    tz = "+00:00" if tz == "Z" else tz
    base = dt.datetime.fromisoformat(head + tz)
    return base.timestamp() * 1e3 + (float("0." + frac) * 1e3 if frac else 0.0)


# --- blocks: the scheduler key of every transaction --------------------------------------------

def block_keys(block):
    """(key, vote, cu_consumed) arrays of one block extract, in block order."""
    t = block["tx"]
    fee = np.asarray(t["fee"], float)
    sigs = np.asarray(t["sigs"], float)
    cost = (720 * sigs + 300 * np.asarray(t["writable"], float) + np.floor(np.asarray(t["data_bytes"], float) / 4)
            + np.asarray(t["cu_limit"], float) + 8 * np.ceil(np.asarray(t["data_limit"], float) / 32768))
    key = (fee - BASE_REWARD_PER_SIG * sigs) * 1e6 / (cost + 1)
    return key, np.asarray(t["vote"], bool), np.asarray(t["cu_consumed"], float)


class Blocks:
    def __init__(self, blocks):
        self.by_slot = {}
        for b in blocks:
            key, vote, cu = block_keys(b)
            nv = np.sort(key[~vote])
            self.by_slot[b["slot"]] = {"key": key, "vote": vote, "cu": cu, "sorted": nv, "producer": b.get("producer"),
                                       "leader": b.get("leader")}

    def rank(self, slot, idx):
        """Percentile of the transaction at (slot, idx) among the block's non-vote transactions."""
        b = self.by_slot.get(slot)
        if b is None or idx is None or idx >= len(b["key"]):
            return math.nan
        return 100.0 * bisect.bisect_left(b["sorted"].tolist(), b["key"][idx]) / max(1, len(b["sorted"]))

    def load(self, slot):
        b = self.by_slot.get(slot)
        if b is None:
            return math.nan, math.nan
        return int((~b["vote"]).sum()), float(b["cu"][~b["vote"]].sum())

    def between(self, slot, ia, ib):
        """Foreign non-vote transactions strictly between our two, and how many of them have a key
        between the two keys."""
        b = self.by_slot.get(slot)
        if b is None:
            return math.nan, math.nan
        lo, hi = sorted((ia, ib))
        sl = slice(lo + 1, hi)
        k, v = b["key"][sl], b["vote"][sl]
        klo, khi = sorted((b["key"][ia], b["key"][ib]))
        return int((~v).sum()), int(((~v) & (k > klo) & (k < khi)).sum())


# --- slot timing --------------------------------------------------------------------------------

class SlotTimes:
    """True start time (unix ms) of each slot: the node's first-shred timestamp minus the RPC lag,
    with a robust line through the observed slots for the missing ones."""

    def __init__(self, slots, rpc_lag_ms):
        pts = sorted((r["slot"], r["server_unix_ms"]) for r in slots if r.get("server_unix_ms") is not None)
        self.obs = {s: t - rpc_lag_ms for s, t in pts}
        self.lag = rpc_lag_ms
        if len(pts) >= 2:
            x = np.array([p[0] for p in pts], float)
            y = np.array([p[1] for p in pts], float) - rpc_lag_ms
            sl = np.diff(y) / np.maximum(np.diff(x), 1)
            self.b = float(np.median(sl[(sl > 150) & (sl < 500)])) if ((sl > 150) & (sl < 500)).any() else 200.0
            self.x0 = x
            self.y0 = y
        else:
            self.b, self.x0, self.y0 = 200.0, None, None

    def start(self, slot):
        if slot in self.obs:
            return self.obs[slot]
        if self.x0 is None:
            return math.nan
        i = int(np.argmin(np.abs(self.x0 - slot)))
        return float(self.y0[i] + self.b * (slot - self.x0[i]))

    def locate(self, t_ms, near_slot):
        """(slot containing t, ms since that slot started)."""
        s = near_slot
        for _ in range(64):
            st = self.start(s)
            if math.isnan(st):
                return None, math.nan
            if t_ms < st:
                s -= 1
            elif t_ms >= self.start(s + 1):
                s += 1
            else:
                return s, t_ms - st
        return None, math.nan


# --- pairs --------------------------------------------------------------------------------------

def _family_at(snapshots, identity, t_ms, fallback):
    """Client id of `identity` in the snapshot nearest to t_ms (within 90 s)."""
    best, best_dt = None, 9e18
    for ts, ids in snapshots:
        d = abs(ts - t_ms)
        if d < best_dt and identity in ids:
            best, best_dt = ids[identity], d
    if best is None or best_dt > 90_000:
        return fallback, "planned"
    return best, "gossip"


def run_pairs(run):
    meta = run["meta"]
    ntp = meta.get("ntp_offset_ms") or 0.0
    lag = (meta.get("timing") or {}).get("rpc_lag_ms", 100.0)
    st = SlotTimes(run["slots"], lag)
    blocks = Blocks(run["blocks"])
    land = {l["signature"]: l for l in run["landings"]}
    windows = {w["window_id"]: w for w in run["windows"]}
    snaps = [(utc_ms(meta.get("gossip_snapshot_utc")), {n["identity"]: n["client_id"] for n in meta.get("targets", [])})]
    snaps += [(utc_ms(g["utc"]), {n["identity"]: n["client_id"] for n in g["targets"]}) for g in run["gossip"]]
    by_pair = defaultdict(dict)
    for t in run["txs"]:
        by_pair[t["pair_id"]][t["role"]] = t
    rows = []
    for pid, p in by_pair.items():
        a, b = p.get("A"), p.get("B")
        if a is None or b is None:
            continue
        w = windows.get(a["window_id"], {})
        la, lb = land.get(a["signature"], {}), land.get(b["signature"], {})
        first, nslots = a["first_slot"], a["window_slots"]
        win_start = st.start(first)
        a_true = utc_ms(a.get("write_utc")) - ntp if a.get("write_utc") else math.nan
        a_slot, phase = st.locate(a_true, first) if not math.isnan(a_true) else (None, math.nan)
        r = {
            "run_id": a["run_id"], "session": meta.get("session") or a["run_id"], "window_id": a["window_id"], "pair_id": f"{a['run_id']}/{pid}",
            "series": a["series"], "lane": a["lane"], "leader": a["leader"], "version": a["version"], "family_planned": a["family"],
            "s_planned_ms": a["s_ms"], "s_ms": a["s_actual_ms"] if a.get("s_actual_ms") is not None else math.nan,
            "a_offset_ms": a["a_offset_ms"], "anchor": a.get("anchor"), "payer": a["payer"],
            "sig_a": a["signature"], "sig_b": b["signature"], "sent": bool(a.get("sent")) and bool(b.get("sent")),
            "error": a.get("error") or b.get("error"),
            "slot_a": la.get("slot"), "idx_a": la.get("index"), "slot_b": lb.get("slot"), "idx_b": lb.get("index"),
            "ok_a": la.get("ok"), "ok_b": lb.get("ok"), "producer_a": la.get("producer"), "producer_b": lb.get("producer"),
            "fee_a": la.get("fee"), "fee_b": lb.get("fee"),
            "a_since_window_ms": a_true - win_start, "a_slot": a_slot, "phase_ms": phase,
            "window_predicted_utc": w.get("predicted_start_utc"),
        }
        fam, src = _family_at(snaps, a["leader"], utc_ms(w.get("predicted_start_utc")) if w else a_true, a["family"])
        r["family"], r["family_source"] = fam, src
        # completeness
        why = None
        if r["error"]:
            why = "not sent: " + r["error"]
        elif r["idx_a"] is None or r["idx_b"] is None:
            why = "not landed" if (r["slot_a"] is None or r["slot_b"] is None) else "landed, block not read"
        elif not (r["ok_a"] and r["ok_b"]):
            why = "execution error"
        elif r["producer_a"] != r["producer_b"]:
            why = "split between producers"
        elif r["producer_a"] != a["leader"]:
            why = "another leader"
        elif not (first <= r["slot_a"] < first + nslots and first <= r["slot_b"] < first + nslots):
            why = "outside the window"
        r["complete"] = why is None
        r["excluded"] = why
        if why is None:
            r["y"] = int((r["slot_b"], r["idx_b"]) < (r["slot_a"], r["idx_a"]))
            r["same_slot"] = r["slot_a"] == r["slot_b"]
            r["rank_a"] = blocks.rank(r["slot_a"], r["idx_a"])
            r["rank_b"] = blocks.rank(r["slot_b"], r["idx_b"])
            r["block_ntx"], r["block_cu"] = blocks.load(r["slot_a"])
            if r["same_slot"]:
                r["between"], r["between_key"] = blocks.between(r["slot_a"], r["idx_a"], r["idx_b"])
            # a placebo rule that cannot exist: lexicographic order of signatures
            r["y_lex"] = int(r["sig_b"] < r["sig_a"])
        r["buffered"] = bool(r["a_since_window_ms"] < 0) if not math.isnan(r["a_since_window_ms"]) else False
        rows.append(r)
    return rows


def build(raw, mode="live"):
    """All pairs of all runs under `raw`; the clock fits use `clock_pairs`."""
    rows = []
    for d in rawio.run_dirs(raw, mode):
        rows += run_pairs(rawio.load_run(d))
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values(["run_id", "window_id", "pair_id"]).reset_index(drop=True)
    return df


def clock_pairs(df):
    """FEE and REV pairs that enter the clock fits: complete, not buffered, actual s known."""
    if not len(df):
        return df
    m = df["complete"] & ~df["buffered"] & df["series"].isin(["FEE", "REV"]) & df["s_ms"].notna()
    return df[m]


def cells(df):
    """{(family, lane): (s, y)} of the clock pairs."""
    out = {}
    for (fam, lane), g in clock_pairs(df).groupby(["family", "lane"]):
        out[(fam, lane)] = (g["s_ms"].to_numpy(float), g["y"].to_numpy(float))
    return out
