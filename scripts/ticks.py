"""Read-only: the builders' tick transactions in every block of a run that holds a probe.

BAM and Harmonic leaders put a tick transaction into their blocks (program `tickUcsEQegChaAuo9VYQQztB4ZGApY6ZT4FkULWY6N`,
signed by the builder's key). Its 25 bytes of instruction data are
    u8 tag | u64 slot | u64 wall clock, ns since the epoch | u64 declared interval, ns    (little endian)
so the chain records where in each block a builder round ended or began, when, and at what declared period
(20 ms for BAM, 50 ms for Harmonic). Found after the pre-registration: an exploratory source.

Usage:
    python scripts/ticks.py data/raw/<run_id> [--rpc URL] [--census-only] [--out data/checks]

Writes data/raw/<run_id>/ticks.jsonl: one line per block (`slot`, `n_tx`, `producer`, `ticks`: index in the
block as `getBlock` returns it, signer, fee, ok, tag, slot in the data, `unix_ns`, `interval_ns`). Blocks
already in the file are skipped, so an interrupted run resumes. Then a census per family (blocks with ticks,
ticks per block, gaps between consecutive ticks of a block) goes to data/checks/ticks-<run_id>.json. Sends
no transactions and needs no keys.
"""
import argparse
import json
import os
import time
from collections import Counter, defaultdict

import numpy as np
import requests

DEFAULT_RPC = "https://api.mainnet-beta.solana.com"
TICK = "tickUcsEQegChaAuo9VYQQztB4ZGApY6ZT4FkULWY6N"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(s):
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + raw


def get_block(url, slot):
    params = [slot, {"encoding": "json", "transactionDetails": "full", "rewards": False, "maxSupportedTransactionVersion": 1}]
    for i in range(8):
        try:
            r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "getBlock", "params": params}, timeout=60)
            if r.status_code == 429:
                raise requests.RequestException("429")
            r = r.json()
            if "result" in r:
                return r["result"]
            err = RuntimeError(r.get("error"))
        except requests.RequestException as e:
            err = e
        time.sleep(min(30, 2 ** i))
    raise err


def ticks_of(block):
    out = []
    for i, t in enumerate(block["transactions"]):
        msg = t["transaction"]["message"]
        keys = msg["accountKeys"]
        if TICK not in keys:
            continue
        for ins in msg["instructions"]:
            if keys[ins["programIdIndex"]] != TICK:
                continue
            d = b58decode(ins["data"])
            row = {"index": i, "signer": keys[0], "fee": t["meta"]["fee"], "ok": t["meta"]["err"] is None}
            if len(d) == 25:
                row.update(tag=d[0], data_slot=int.from_bytes(d[1:9], "little"),
                           unix_ns=int.from_bytes(d[9:17], "little"), interval_ns=int.from_bytes(d[17:25], "little"))
            else:
                row["data_hex"] = d.hex()
            out.append(row)
    return out


def census(run, out):
    """Per family of the block's producer (meta.json targets; "other" for a producer we did not target)."""
    with open(os.path.join(run, "meta.json"), encoding="utf-8") as fh:
        fam = {t["identity"]: t["client_id"] for t in json.load(fh)["targets"]}
    with open(os.path.join(run, "ticks.jsonl"), encoding="utf-8") as fh:
        blocks = [json.loads(l) for l in fh]
    by = defaultdict(list)
    for b in blocks:
        by[fam.get(b["producer"], "other")].append(b)
    pct = lambda a: [round(float(x), 2) for x in np.percentile(a, [10, 50, 90])] if len(a) else None
    res = {}
    for f, bl in sorted(by.items()):
        n = [len(b["ticks"]) for b in bl]
        gaps, signers, declared = [], Counter(), Counter()
        for b in bl:
            t = sorted(b["ticks"], key=lambda x: x["index"])
            signers.update(x["signer"] for x in t)
            declared.update(str(x.get("interval_ns")) for x in t)
            gaps += list(np.diff([x["unix_ns"] for x in t if "unix_ns" in x]) / 1e6)
        res[f] = {"blocks": len(bl), "blocks_with_ticks": sum(k > 0 for k in n), "ticks_per_block_p10_50_90": pct(n),
                  "gap_ms_p10_50_90": pct(gaps), "gaps": len(gaps), "signers": dict(signers), "declared_interval_ns": dict(declared)}
        print(f"{f:<20} blocks {len(bl):>4}  with ticks {res[f]['blocks_with_ticks']:>4}  ticks/block {pct(n)}  gap ms {pct(gaps)}")
    run_id = os.path.basename(os.path.normpath(run))
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"ticks-{run_id}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"run_id": run_id, "by_family": res}, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--rpc", default=os.environ.get("ITB_RPC_URL", DEFAULT_RPC))
    ap.add_argument("--census-only", action="store_true", help="skip reading blocks, recount ticks.jsonl")
    ap.add_argument("--out", default="data/checks")
    a = ap.parse_args()
    if a.census_only:
        return census(a.run, a.out)
    producer = {}
    with open(os.path.join(a.run, "landings.jsonl"), encoding="utf-8") as fh:
        for l in map(json.loads, fh):
            if l.get("slot") is not None:
                producer[l["slot"]] = l.get("producer")
    path = os.path.join(a.run, "ticks.jsonl")
    done = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            done = {json.loads(l)["slot"] for l in fh}
    todo = sorted(set(producer) - done)
    print(f"{len(producer)} blocks with a probe, {len(done)} already read, {len(todo)} to read")
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        for k, slot in enumerate(todo, 1):
            b = get_block(a.rpc, slot)
            row = {"slot": slot, "n_tx": len(b["transactions"]), "producer": producer[slot], "ticks": ticks_of(b)}
            fh.write(json.dumps(row, sort_keys=True) + "\n")
            fh.flush()
            if k % 50 == 0:
                print(f"{k} blocks read")
            time.sleep(0.2)
    print(path)
    census(a.run, a.out)


if __name__ == "__main__":
    main()
