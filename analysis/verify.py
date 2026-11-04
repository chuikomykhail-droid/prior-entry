"""Two checks anyone can run.

  verify_chain   re-read every block that holds one of our probes with getBlock and compare,
                 independently of the Rust collector: position of each probe, producer (fee
                 reward recipient), fee charged, success. Read-only, needs the network.
  check_derived  recompute data/derived from data/raw into a temporary folder and compare every
                 file (no network): quick without the bootstrap and the placebo shuffles, whole
                 with `full`. See compare.py for what "the same" means.
"""
import os
import tempfile
import time

import requests

from . import compare, rawio


def _rpc(url, method, params, attempts=40):
    """Waits out rate limits and lost connections: a full check reads ~1,400 blocks and starts over if it dies."""
    for attempt in range(attempts):
        try:
            r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=60)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            time.sleep(min(60, 5 + 5 * attempt))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(float(r.headers.get("Retry-After", 2 + min(attempt, 30))))
            continue
        r.raise_for_status()
        j = r.json()
        if "error" in j:
            raise RuntimeError(f"{method}: {j['error']}")
        return j["result"]
    raise RuntimeError(f"{method}: no answer after {attempts} attempts")


def verify_chain(raw, rpc, limit=None):
    bad, checked, blocks = 0, 0, 0
    for d in rawio.run_dirs(raw, "live"):
        meta = rawio.read_json(os.path.join(d, "meta.json"), {})
        if meta.get("synthetic"):
            print(f"{d}: synthetic, skipped")
            continue
        land = [l for l in rawio.read_jsonl(os.path.join(d, "landings.jsonl")) if l.get("index") is not None]
        by_slot = {}
        for l in land:
            by_slot.setdefault(l["slot"], []).append(l)
        for slot, ls in sorted(by_slot.items()):
            if limit is not None and blocks >= limit:
                break
            b = _rpc(rpc, "getBlock", [slot, {"encoding": "json", "transactionDetails": "full", "rewards": True,
                                              "maxSupportedTransactionVersion": 1, "commitment": "finalized"}])
            blocks += 1
            index = {tx["transaction"]["signatures"][0]: (i, tx) for i, tx in enumerate(b["transactions"])}
            producer = next((r["pubkey"] for r in b.get("rewards") or [] if r.get("rewardType") == "Fee"), None)
            for l in ls:
                checked += 1
                got = index.get(l["signature"])
                problems = []
                if got is None:
                    problems.append("not in block")
                else:
                    i, tx = got
                    if i != l["index"]:
                        problems.append(f"index {i} != {l['index']}")
                    if tx["meta"]["fee"] != l.get("fee"):
                        problems.append(f"fee {tx['meta']['fee']} != {l.get('fee')}")
                    if (tx["meta"]["err"] is None) != bool(l.get("ok")):
                        problems.append("success differs")
                if producer != l.get("producer"):
                    problems.append(f"producer {producer} != {l.get('producer')}")
                if problems:
                    bad += 1
                    print(f"{l['signature'][:16]}… slot {slot}: {'; '.join(problems)}")
            time.sleep(1.5)
    print(f"verified {checked} probes in {blocks} blocks: {checked - bad} agree, {bad} differ")
    return bad == 0


def check_derived(raw, derived, full=False, tolerance=compare.TOLERANCE, details=3):
    from . import report
    if not rawio.run_dirs(raw, "live"):
        print(f"no live runs under {raw} yet: nothing to recompute")
        return True
    if not os.path.isdir(derived):
        print(f"{derived} does not exist: nothing to compare")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        out, figs = os.path.join(tmp, "derived"), os.path.join(tmp, "figures")
        if full:
            report.reproduce(raw, out, figs)
        else:
            report.reproduce(raw, out, figs, boot_reps=0, placebo_reps=0)
        results = []
        for name in sorted(os.listdir(derived)):
            a = os.path.join(derived, name)
            if not os.path.isfile(a) or name == "power.json":
                continue
            results.append(compare.compare_file(a, os.path.join(out, name), tolerance, frozenset() if full else compare.QUICK_SKIPS))
            print("\n".join(compare.describe(results[-1], details)))
    same = sum(r.status == "same" for r in results)
    close = sum(r.status == "close" for r in results)
    different = sum(r.status == "DIFFERENT" for r in results)
    print(f"{len(results)} files: {same} identical, {close} within {100 * tolerance:g}% or one printed digit, {different} different")
    if not full:
        print("quick check: bootstrap and placebo fields were not recomputed (`docker compose run --rm full` does)")
    return different == 0
