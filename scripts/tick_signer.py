"""Read-only: the builders' tick signers as the chain shows them now.

Harmonic's ticks stopped between our two sessions (REPORT §3). This records what the chain says about why: each
signer's balance against the rent-exempt minimum and its newest transactions. A later run shows a later state.

Usage:
    python scripts/tick_signer.py [--rpc URL] [--out data/checks]

Writes data/checks/tick-signers-<utc>.json. Sends no transactions and needs no keys.
"""
import argparse
import json
import os
import time

import requests

DEFAULT_RPC = "https://api.mainnet-beta.solana.com"
SIGNERS = {"Harmonic": "Harmonic8SoAfZixJqUxxdSeyWzr6q7XFjuiXS5Z2zPg", "BAM": "BAMgx3XPWrXkNUuQiVWUZU6eB2HQZdwz9HNnT4tpo8LG"}
TICK_FEE = 5000  # lamports, every Harmonic tick in session A


def rpc(url, method, params):
    for _ in range(10):
        r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=60)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 5)))
            continue
        j = r.json()
        if "error" in j:
            raise RuntimeError(f"{method}: {j['error']}")
        return j["result"]
    raise RuntimeError(f"{method}: rate limited")


def utc(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default=os.environ.get("ITB_RPC_URL", DEFAULT_RPC))
    ap.add_argument("--out", default="data/checks")
    a = ap.parse_args()
    rent = rpc(a.rpc, "getMinimumBalanceForRentExemption", [0])
    res = {"read_utc": utc(time.time()), "rent_exempt_minimum": rent, "tick_fee": TICK_FEE, "signers": {}}
    for name, key in SIGNERS.items():
        balance = rpc(a.rpc, "getBalance", [key])["value"]
        sigs = rpc(a.rpc, "getSignaturesForAddress", [key, {"limit": 5}])
        tx = rpc(a.rpc, "getTransaction", [sigs[0]["signature"], {"encoding": "json", "maxSupportedTransactionVersion": 1}])
        res["signers"][name] = {
            "key": key, "balance": balance, "above_rent": balance - rent, "can_pay_a_tick": balance - rent >= TICK_FEE,
            "newest": [{"slot": s["slot"], "utc": utc(s.get("blockTime")), "ok": s.get("err") is None, "signature": s["signature"]} for s in sigs],
            "newest_tx": {"slot": tx["slot"], "utc": utc(tx.get("blockTime")), "fee": tx["meta"]["fee"], "ok": tx["meta"]["err"] is None,
                          "signer_before": tx["meta"]["preBalances"][0], "signer_after": tx["meta"]["postBalances"][0]},
        }
        n = res["signers"][name]
        print(f"{name:<9} balance {balance:>12}  above rent {n['above_rent']:>12}  newest {n['newest_tx']['utc']} slot {n['newest_tx']['slot']}")
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "tick-signers-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(path)


if __name__ == "__main__":
    main()
