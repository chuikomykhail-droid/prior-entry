"""Read-only accounting check of one live run: per payer, the balance before its first landed probe minus
the balance after its last one, both from the chain (`getTransaction` pre/post balances), against the fees
of its landed probes as `itb collect` read them from the blocks.

Usage:
    python scripts/balance_drop.py data/raw/<run_id> [--rpc URL] [--out data/checks]

Writes data/checks/balance-drop-<run_id>.json. Assumes nothing else touched the payers during the run
(funding and sweeps happen outside runs). Sends no transactions and needs no keys.
"""
import argparse
import json
import os
import time
from collections import defaultdict

import requests

DEFAULT_RPC = "https://api.mainnet-beta.solana.com"


def rpc(url, method, params):
    for i in range(5):
        try:
            r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30).json()
            if "error" not in r:
                return r["result"]
            err = RuntimeError(r["error"])
        except requests.RequestException as e:
            err = e
        time.sleep(2 + 2 * i)
    raise err


def payer_balance(url, sig, payer, which):
    tx = rpc(url, "getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0, "commitment": "finalized"}])
    keys = tx["transaction"]["message"]["accountKeys"]
    if keys[0] != payer:
        raise SystemExit(f"{sig}: fee payer {keys[0]}, expected {payer}")
    return tx["meta"][which][0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--rpc", default=os.environ.get("ITB_RPC_URL", DEFAULT_RPC))
    ap.add_argument("--out", default="data/checks")
    a = ap.parse_args()
    run_id = os.path.basename(os.path.normpath(a.run))
    with open(os.path.join(a.run, "txs.jsonl"), encoding="utf-8") as fh:
        payer_of = {t["signature"]: t["payer"] for t in map(json.loads, fh) if t.get("sent")}
    fees, first, last = defaultdict(int), {}, {}
    with open(os.path.join(a.run, "landings.jsonl"), encoding="utf-8") as fh:
        for l in map(json.loads, fh):
            p = payer_of.get(l["signature"])
            if p is None or l.get("fee") is None:
                continue
            fees[p] += int(l["fee"])
            k = (l["slot"], l["index"], l["signature"])
            first[p] = min(first.get(p, k), k)
            last[p] = max(last.get(p, k), k)
    rows = {}
    for p in sorted(fees):
        before = payer_balance(a.rpc, first[p][2], p, "preBalances")
        after = payer_balance(a.rpc, last[p][2], p, "postBalances")
        rows[p] = {"before": before, "after": after, "drop": before - after, "landed_fees": fees[p]}
        print(f"{p[:8]}  before {before:>10}  after {after:>10}  drop {before - after:>9}  landed fees {fees[p]:>9}")
    drop, landed = sum(r["drop"] for r in rows.values()), sum(fees.values())
    res = {"run_id": run_id, "rpc": a.rpc, "payers": rows, "drop": drop, "landed_fees": landed, "equal": drop == landed}
    print(f"balance drop {drop}, landed fees {landed}: {'equal' if drop == landed else 'DIFFERENT'}")
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"balance-drop-{run_id}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(path)


if __name__ == "__main__":
    main()
