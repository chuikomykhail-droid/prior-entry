"""Prints the Harmonic pairs behind "last overtake at 33.3 ms, none in the next 298": every FEE clock pair of
HarmonicAgave and HarmonicFiredancer sent later than the last pair in which B landed ahead of A.

The gap s comes from my send log. Slot and position come from data/raw/*/landings.jsonl, as collected from the chain.
With --chain N it re-reads N of the pairs, picked at random, from mainnet right now. One pair with B ahead of A on chain
cancels the claim. Standard library only, no keys, nothing is sent.

Usage:
    python scripts/last_overtake.py [--chain N] [--rpc URL] [--derived data/derived] [--raw data/raw]
"""
import argparse
import csv
import errno
import glob
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

FAMILIES = {"HarmonicAgave", "HarmonicFiredancer"}
RPC = os.environ.get("ITB_RPC_URL", "https://api.mainnet-beta.solana.com")


def clock_pairs(path):
    """The FEE rows of analysis.pairs.clock_pairs, for the two Harmonic families."""
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r["family"] in FAMILIES and r["series"] == "FEE" and r["s_ms"] and r["complete"] == "True"
                    and r["timed"] == "True" and r["buffered"] == "False" and r["simultaneous"] == "False"):
                yield r


def landings(raw):
    pos = {}
    for path in glob.glob(os.path.join(raw, "*", "landings.jsonl")):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                pos[r["signature"]] = (r["slot"], r["index"])
    return pos


def get_block(url, slot):
    """The block's signatures in order; the public RPC limits its rate, so wait and try again."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getBlock",
                       "params": [slot, {"transactionDetails": "signatures", "rewards": False, "maxSupportedTransactionVersion": 0}]}).encode()
    for attempt in range(8):
        try:
            req = urllib.request.Request(url, body, {"Content-Type": "application/json", "User-Agent": "last-overtake"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)["result"]["signatures"]
        except (urllib.error.URLError, TimeoutError, KeyError, TypeError) as e:
            if attempt == 7:
                raise SystemExit(f"slot {slot}: {e}")
            time.sleep(2 + 3 * attempt)


def chain(pairs, n, url):
    picked = random.sample(pairs, min(n, len(pairs)))
    blocks, bad = {}, 0
    print(f"\nre-reading {len(picked)} pairs from {url}")
    for p in picked:
        now = []
        for sig, (slot, _) in ((p["sig_a"], p["a"]), (p["sig_b"], p["b"])):
            if slot not in blocks:
                blocks[slot] = get_block(url, slot)
                time.sleep(0.5)
            now.append((slot, blocks[slot].index(sig)))
        agree = now[0] == p["a"] and now[1] == p["b"]
        ahead = now[1] < now[0]
        bad += (not agree) or ahead
        print(f"  s = {p['s']:7.2f} ms  A {now[0][0]}:{now[0][1]:<4}  B {now[1][0]}:{now[1][1]:<4}  {'agrees with the raw data' if agree else 'DIFFERS FROM THE RAW DATA'}, {'B AHEAD' if ahead else 'A ahead'}")
    print("all agree, A ahead in every one" if not bad else f"{bad} PAIRS CONTRADICT THE CLAIM")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--derived", default="data/derived")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--chain", type=int, default=0, metavar="N", help="re-read N random pairs from mainnet")
    ap.add_argument("--rpc", default=RPC)
    a = ap.parse_args()
    pos = landings(a.raw)
    rows = []
    for r in clock_pairs(os.path.join(a.derived, "pairs.csv")):
        rows.append({**r, "s": float(r["s_ms"]), "a": pos[r["sig_a"]], "b": pos[r["sig_b"]]})
    overtakes = [r for r in rows if r["b"] < r["a"]]
    last = max(r["s"] for r in overtakes)
    past = sorted((r for r in rows if r["s"] > last), key=lambda r: r["s"])
    print(f"{len(rows)} FEE clock pairs on HarmonicAgave and HarmonicFiredancer, B ahead of A in {len(overtakes)}.")
    print(f"Last overtake at {last} ms. Pairs sent later: {len(past)}, B ahead of A in {sum(r['b'] < r['a'] for r in past)}.\n")
    print(f"{'s, ms':>8}  {'client':<18}  {'validator':<9}  {'slot A':<9}  {'pos A':>5}  {'slot B':<9}  {'pos B':>5}  signature A, signature B")
    for r in past:
        print(f"{r['s']:8.2f}  {r['family']:<18}  {r['leader'][:8]:<9}  {r['a'][0]:<9}  {r['a'][1]:>5}  {r['b'][0]:<9}  {r['b'][1]:>5}  {r['sig_a']} {r['sig_b']}")
    if a.chain:
        sys.exit(1 if chain(past, a.chain, a.rpc) else 0)


if __name__ == "__main__":
    try:
        main()
    except OSError as e:  # the reader's pipe closed, as with `| head`
        if e.errno not in (errno.EPIPE, errno.EINVAL):
            raise
