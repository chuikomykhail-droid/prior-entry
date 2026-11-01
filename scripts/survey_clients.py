"""Read-only mainnet survey: client families, stake, versions, TPU ingress, leader-window frequency.

Usage:
    python scripts/survey_clients.py [--rpc URL] [--slots N] [--out DIR]

Writes raw RPC responses and a summary (JSON + Markdown) to data/survey/<UTC timestamp>/.
Sends no transactions and needs no keys.
"""
import argparse
import collections
import datetime as dt
import json
import os
import time

import requests

DEFAULT_RPC = "https://api.mainnet-beta.solana.com"


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


def leader_windows(leaders):
    """Collapse a per-slot leader list into (leader, first_index, length) runs."""
    runs = []
    for i, ld in enumerate(leaders):
        if runs and runs[-1][0] == ld and i == runs[-1][1] + runs[-1][2]:
            runs[-1][2] += 1
        else:
            runs.append([ld, i, 1])
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default=os.environ.get("ITB_RPC_URL", DEFAULT_RPC))
    ap.add_argument("--slots", type=int, default=20000, help="future slots of leader schedule to sample")
    ap.add_argument("--out", default="data/survey")
    a = ap.parse_args()

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.join(a.out, ts)
    os.makedirs(out, exist_ok=True)

    epoch = rpc(a.rpc, "getEpochInfo")
    nodes = rpc(a.rpc, "getClusterNodes")
    votes = rpc(a.rpc, "getVoteAccounts")
    perf = rpc(a.rpc, "getRecentPerformanceSamples", [10])
    start = epoch["absoluteSlot"] + 20
    leaders = []
    while len(leaders) < a.slots:
        n = min(5000, a.slots - len(leaders))
        leaders += rpc(a.rpc, "getSlotLeaders", [start + len(leaders), n])
    for name, obj in [("epoch", epoch), ("cluster_nodes", nodes), ("vote_accounts", votes),
                      ("performance_samples", perf), ("slot_leaders", {"start_slot": start, "leaders": leaders})]:
        with open(os.path.join(out, f"{name}.json"), "w") as f:
            json.dump(obj, f)

    slot_sec = sum(p["samplePeriodSecs"] for p in perf) / max(1, sum(p["numSlots"] for p in perf))
    node_by_id = {n["pubkey"]: n for n in nodes}
    stake_by_id = collections.Counter()
    for v in votes["current"] + votes["delinquent"]:
        stake_by_id[v["nodePubkey"]] += v["activatedStake"]
    total_stake = sum(stake_by_id.values())

    def family(identity):
        n = node_by_id.get(identity)
        return n.get("clientId") or "Unknown" if n else "NotInGossip"

    windows = leader_windows(leaders)
    hours = len(leaders) * slot_sec / 3600
    fam = collections.defaultdict(lambda: {"nodes": 0, "staked_nodes": 0, "stake": 0, "versions": collections.Counter(),
                                           "tpu_ips": set(), "leader_slots": 0, "windows": 0, "validators": []})
    for n in nodes:
        f = fam[n.get("clientId") or "Unknown"]
        f["nodes"] += 1
        f["versions"][n.get("version")] += 1
        if n.get("tpuQuic"):
            f["tpu_ips"].add(n["tpuQuic"].rsplit(":", 1)[0])
        s = stake_by_id.get(n["pubkey"], 0)
        if s:
            f["staked_nodes"] += 1
            f["stake"] += s
            f["validators"].append({"identity": n["pubkey"], "stake_sol": s / 1e9, "version": n.get("version"),
                                    "tpuQuic": n.get("tpuQuic")})
    wins_by_id = collections.Counter(w[0] for w in windows)
    for ld in leaders:
        fam[family(ld)]["leader_slots"] += 1
    for w in windows:
        fam[family(w[0])]["windows"] += 1

    summary = {"utc": ts, "epoch": epoch["epoch"], "slot": epoch["absoluteSlot"], "slot_seconds": slot_sec,
               "sampled_slots": len(leaders), "sampled_hours": hours, "total_stake_sol": total_stake / 1e9,
               "window_lengths": collections.Counter(w[2] for w in windows), "families": {}}
    for name, f in sorted(fam.items(), key=lambda kv: -kv[1]["stake"]):
        vals = sorted(f["validators"], key=lambda v: -v["stake_sol"])
        for v in vals:
            v["windows_per_hour"] = wins_by_id.get(v["identity"], 0) / hours if hours else 0
        summary["families"][name] = {
            "nodes": f["nodes"], "staked_nodes": f["staked_nodes"],
            "stake_share": f["stake"] / total_stake if total_stake else 0,
            "versions": dict(f["versions"].most_common()),
            "distinct_tpu_ips": len(f["tpu_ips"]),
            "leader_slot_share": f["leader_slots"] / len(leaders),
            "windows_per_hour": f["windows"] / hours if hours else 0,
            "top_validators": vals[:8],
        }
    with open(os.path.join(out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1, default=str)

    lines = [f"# Mainnet client survey {ts}", "",
             f"Epoch {epoch['epoch']}, slot {epoch['absoluteSlot']}. Measured slot time {slot_sec*1000:.0f} ms. "
             f"Leader schedule sampled: {len(leaders)} slots ({hours:.2f} h) from slot {start}. "
             f"Window lengths seen: {dict(summary['window_lengths'])}.", "",
             "| clientId | nodes | staked | stake share | leader-slot share | windows / hour | distinct TPU IPs | versions |",
             "|---|---|---|---|---|---|---|---|"]
    for name, f in summary["families"].items():
        vers = ", ".join(f"{k} ({v})" for k, v in list(f["versions"].items())[:4])
        lines.append(f"| {name} | {f['nodes']} | {f['staked_nodes']} | {f['stake_share']*100:.1f}% | "
                     f"{f['leader_slot_share']*100:.1f}% | {f['windows_per_hour']:.0f} | {f['distinct_tpu_ips']} | {vers} |")
    lines += ["", "## Top validators per family (by stake)", ""]
    for name, f in summary["families"].items():
        if not f["top_validators"]:
            continue
        lines.append(f"### {name}")
        lines.append("| identity | stake, SOL | version | tpuQuic | windows / hour |")
        lines.append("|---|---|---|---|---|")
        for v in f["top_validators"][:5]:
            lines.append(f"| `{v['identity']}` | {v['stake_sol']:,.0f} | {v['version']} | {v['tpuQuic']} | {v['windows_per_hour']:.1f} |")
        lines.append("")
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(os.path.join(out, "summary.md"))


if __name__ == "__main__":
    main()
