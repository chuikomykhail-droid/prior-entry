"""Read-only mainnet survey: where our probe designs rank among real transactions by the scheduler's key.

The key is Agave's priority, reward * 10^6 / (cost + 1). For every non-vote transaction in a sample of
recent blocks we rebuild it from the block itself:
    reward = fee - 2500 * signatures              (priority fee + the unburned half of the base fee)
    cost   = 720 * signatures + 300 * writable accounts + instruction data bytes / 4
             + requested CU limit + 8 * ceil(loaded-data limit / 32 KiB)
and report the percentiles, overall and per leader client, plus the percentile our probe designs would
occupy (CU limit 600 = "VIP lane", 200,000 = the wallet default and the market median).

Usage:
    python scripts/market_rank.py [--rpc URL] [--blocks N] [--step SLOTS] [--out DIR]

Writes a summary (JSON + Markdown) and the sampled slots to data/survey/<UTC timestamp>-market-rank/.
Sends no transactions and needs no keys. Approximations: precompile signatures and per-builtin default
CU limits are simplified; the order of magnitude, not the last percentile point, is the point.
"""
import argparse
import bisect
import collections
import datetime as dt
import json
import math
import os
import time

import requests

DEFAULT_RPC = "https://api.mainnet-beta.solana.com"
COMPUTE_BUDGET = "ComputeBudget111111111111111111111111111111"
SYSTEM = "11111111111111111111111111111111"
VOTE = "Vote111111111111111111111111111111111111111"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
# our probe: 1 signature, 2 writable accounts, 31 bytes of instruction data, 32 KiB loaded-data limit
PROBE_BASE_COST = 720 + 300 * 2 + 31 // 4 + 8
PROBES = [  # (label, CU limit, priority fee in lamports)
    ("VIP cheap (CU 600, fee 500)", 600, 500),
    ("VIP dear (CU 600, fee 3000)", 600, 3000),
    ("VIP no priority fee (CU 600, fee 0)", 600, 0),
    ("ECO cheap (CU 200k, fee 500)", 200_000, 500),
    ("ECO dear (CU 200k, fee 3000)", 200_000, 3000),
    ("CU 50k, fee 500", 50_000, 500),
    ("CU 400k, fee 500", 400_000, 500),
]


def rpc(url, method, params=None, retries=5):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}
    for attempt in range(retries):
        r = requests.post(url, json=body, timeout=120)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 5)))
            continue
        r.raise_for_status()
        j = r.json()
        if "error" in j:
            raise RuntimeError(f"{method}: {j['error']}")
        return j["result"]
    raise RuntimeError(f"{method}: rate limited {retries} times")


def b58decode(s):
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + raw


def priority(tx):
    """(reward / (cost + 1) * 10^6, CU price, requested CU limit) of one transaction, None for votes."""
    msg, meta, h = tx["transaction"]["message"], tx["meta"], tx["transaction"]["message"]["header"]
    keys = list(msg["accountKeys"])
    loaded = meta.get("loadedAddresses") or {}
    all_keys = keys + loaded.get("writable", []) + loaded.get("readonly", [])
    sigs = len(tx["transaction"]["signatures"])
    nrs = h["numRequiredSignatures"]
    writable = (nrs - h["numReadonlySignedAccounts"]) + (len(keys) - nrs - h["numReadonlyUnsignedAccounts"]) \
        + len(loaded.get("writable", []))
    cu_limit, cu_price, data_limit, data_bytes, default_cu = None, 0, 64 * 1024 * 1024, 0, 0
    for ix in msg["instructions"]:
        program = all_keys[ix["programIdIndex"]]
        data = b58decode(ix["data"])
        data_bytes += len(data)
        if program == VOTE:
            return None
        if program == COMPUTE_BUDGET and data:
            if data[0] == 2:
                cu_limit = int.from_bytes(data[1:5], "little")
            elif data[0] == 3:
                cu_price = int.from_bytes(data[1:9], "little")
            elif data[0] == 4:
                data_limit = int.from_bytes(data[1:5], "little")
            default_cu += 3000
        elif program == SYSTEM:
            default_cu += 3000
        else:
            default_cu += 200_000
    if cu_limit is None:
        cu_limit = min(default_cu, 1_400_000)
    cost = 720 * sigs + 300 * writable + data_bytes // 4 + cu_limit + 8 * math.ceil(data_limit / 32768)
    return (meta["fee"] - 2500 * sigs) * 1e6 / (cost + 1), cu_price, cu_limit


def percentile_rank(sorted_values, x):
    return 100.0 * bisect.bisect_left(sorted_values, x) / len(sorted_values)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default=os.environ.get("ITB_RPC_URL", DEFAULT_RPC))
    ap.add_argument("--blocks", type=int, default=48, help="blocks to sample")
    ap.add_argument("--step", type=int, default=61, help="slots between sampled blocks")
    ap.add_argument("--out", default="data/survey")
    a = ap.parse_args()

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.join(a.out, f"{ts}-market-rank")
    os.makedirs(out, exist_ok=True)

    top = rpc(a.rpc, "getSlot", [{"commitment": "finalized"}]) - 30
    first = top - a.step * (a.blocks + 20)
    leaders = []
    while len(leaders) < top - first + 1:
        n = min(5000, top - first + 1 - len(leaders))
        leaders += rpc(a.rpc, "getSlotLeaders", [first + len(leaders), n])
    client = {n["pubkey"]: n.get("clientId") or "Unknown" for n in rpc(a.rpc, "getClusterNodes")}

    rows, sampled, slot = [], [], top
    while len(sampled) < a.blocks and slot >= first:
        try:
            block = rpc(a.rpc, "getBlock", [slot, {"encoding": "json", "transactionDetails": "full", "rewards": False,
                                                   "maxSupportedTransactionVersion": 1, "commitment": "finalized"}])
        except RuntimeError:  # skipped slot or not available
            block = None
        if block:
            fam = client.get(leaders[slot - first], "NotInGossip")
            n = 0
            for tx in block["transactions"]:
                try:
                    p = priority(tx)
                except (KeyError, IndexError, ValueError):
                    continue
                if p:
                    rows.append((fam,) + p)
                    n += 1
            sampled.append({"slot": slot, "leader": leaders[slot - first], "client": fam, "transactions": n})
        slot -= a.step
        time.sleep(1.5)

    rc_all = sorted(r[1] for r in rows)
    rc_by_client = collections.defaultdict(list)
    for r in rows:
        rc_by_client[r[0]].append(r[1])
    for v in rc_by_client.values():
        v.sort()
    cu_limits = sorted(r[3] for r in rows)
    q = lambda arr, p: arr[min(len(arr) - 1, int(p * len(arr)))]
    probes = []
    for label, limit, fee in PROBES:
        rc = (fee + 2500) * 1e6 / (PROBE_BASE_COST + limit + 1)
        probes.append({"probe": label, "cu_limit": limit, "priority_fee": fee, "rc": rc,
                       "percentile": percentile_rank(rc_all, rc),
                       "percentile_by_client": {c: percentile_rank(v, rc) for c, v in rc_by_client.items() if len(v) >= 300}})
    summary = {
        "utc": ts, "rpc": a.rpc, "blocks": len(sampled), "transactions": len(rows),
        "rc_percentiles": {f"p{p * 100:g}": q(rc_all, p) for p in (0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 0.999)},
        "cu_limit_percentiles": {f"p{p * 100:g}": q(cu_limits, p) for p in (0.1, 0.25, 0.5, 0.75, 0.9)},
        "zero_cu_price_share": sum(1 for r in rows if r[2] == 0) / len(rows),
        "transactions_by_client": {c: len(v) for c, v in sorted(rc_by_client.items(), key=lambda kv: -len(kv[1]))},
        "probes": probes,
    }
    with open(os.path.join(out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1)
    with open(os.path.join(out, "slots.json"), "w") as fh:
        json.dump(sampled, fh, indent=1)

    clients = [c for c, v in summary["transactions_by_client"].items() if v >= 300]
    lines = [f"# Market rank of probe designs {ts}", "",
             f"{len(sampled)} blocks (every {a.step}th slot below {top}), {len(rows)} non-vote transactions. "
             f"Key: reward * 10^6 / (cost + 1), rebuilt from each block. "
             f"Zero CU price: {summary['zero_cu_price_share'] * 100:.1f}% of transactions. "
             f"Requested CU limit: median {summary['cu_limit_percentiles']['p50']:,}.", "",
             "| market percentile | " + " | ".join(summary["rc_percentiles"]) + " |",
             "|---|" + "---|" * len(summary["rc_percentiles"]),
             "| reward / cost | " + " | ".join(f"{v:,.0f}" for v in summary["rc_percentiles"].values()) + " |", "",
             "| probe design | key | percentile, all blocks | " + " | ".join(clients) + " |",
             "|---|---|---|" + "---|" * len(clients)]
    for p in probes:
        lines.append(f"| {p['probe']} | {p['rc']:,.0f} | {p['percentile']:.1f} | "
                     + " | ".join(f"{p['percentile_by_client'].get(c, float('nan')):.1f}" for c in clients) + " |")
    lines += ["", "Transactions per leader client: "
              + ", ".join(f"{c} {n}" for c, n in summary["transactions_by_client"].items()) + "."]
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(os.path.join(out, "summary.md"))


if __name__ == "__main__":
    main()
