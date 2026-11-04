"""Exploratory read-outs of the builders' ticks, fixed in REPORT §3 before any outcome was read. No confirmatory claim.

  rounds    per builder family and lane: complete pairs in blocks with ticks, whether A and B lie between the same
            two ticks, and the share of B ahead within one round against across rounds. Harmonic stopped ticking
            between the sessions, so its pairs come from session A only; BAM's from both.
  sessions  did the order move when Harmonic's marker went? For the validators in COMPARE, per lane and session:
            the share of B ahead at s = 0 and in the three bands, Wilson 95%.

Usage:
    python scripts/tick_readouts.py [--raw data/raw] [--out data/checks/tick-readouts.json]

Not in data/derived: `python -m analysis check` compares that folder with what `reproduce` writes.
"""
import argparse
import bisect
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from analysis import pairs, rawio, report  # noqa: E402

BUILDERS = ("AgaveBam", "FireBAM", "HarmonicAgave", "HarmonicFiredancer")
SERIES = ("FEE", "REV")
COMPARE = {"marker stopped": ("Fd7btgyS", "EvnRmnMr"), "control, ticks in both": ("5Cchr1XG", "9rkJMARq")}


def tick_index(raw):
    """Slot -> sorted block indices of its ticks, for the blocks that have any."""
    out = {}
    for d in rawio.run_dirs(raw, "live"):
        for row in rawio.read_jsonl(os.path.join(d, "ticks.jsonl")):
            if row["ticks"]:
                out[int(row["slot"])] = sorted(t["index"] for t in row["ticks"])
    return out


def same_round(slot_a, idx_a, slot_b, idx_b, ticks):
    """True when A and B lie between the same two ticks, False when not, None when a block has no ticks."""
    a, b = ticks.get(int(slot_a)), ticks.get(int(slot_b))
    if a is None or b is None:
        return None
    if int(slot_a) != int(slot_b):
        return False
    return bisect.bisect(a, int(idx_a)) == bisect.bisect(a, int(idx_b))


def band_rows(g, sim):
    """s = 0 and the three bands of report.py, as (name, subset)."""
    rows = [("s = 0", sim)]
    for name, lo, hi in report.BANDS:
        rows.append((name, g[(g["s_ms"] > lo) & (g["s_ms"] <= hi)]))
    return rows


def rounds(df, ticks):
    comp = df[df["complete"] & df["family"].isin(BUILDERS) & df["series"].isin(SERIES)].copy()
    comp["same_round"] = [same_round(a, i, b, j, ticks) for a, i, b, j in zip(comp["slot_a"], comp["idx_a"], comp["slot_b"], comp["idx_b"])]
    out = {}
    for (fam, lane), g in comp.groupby(["family", "lane"]):
        marked = g[g["same_round"].notna()]
        within, across = marked[marked["same_round"] == True], marked[marked["same_round"] == False]  # noqa: E712
        row = {"complete": len(g), "with_ticks": len(marked), "sessions_with_ticks": dict(Counter(marked["session"])),
               "within": report.share(within["y"].to_numpy(float)), "across": report.share(across["y"].to_numpy(float))}
        # how often a pair shares a round, by how far apart it was sent: pairs in the window only
        win = marked[marked.index.isin(pairs.in_window(df).index)]
        clock = win[~win["simultaneous"] & (win["series"] == "FEE")]
        row["share_same_round_in_window"] = {
            name: {"n": len(x), "same_round": int((x["same_round"] == True).sum())}  # noqa: E712
            for name, x in band_rows(clock, win[win["simultaneous"]])}
        out[f"{fam}/{lane}"] = row
    return out


def sessions(df):
    clock, sim = pairs.clock_pairs(df), pairs.simultaneous_pairs(df)
    out = {}
    for group, leaders in COMPARE.items():
        for leader in leaders:
            for lane in ("VIP", "ECO"):
                for ses in sorted(df["session"].dropna().unique()):
                    pick = lambda d: d[d["leader"].str.startswith(leader) & (d["lane"] == lane) & (d["session"] == ses)]
                    out[f"{leader}/{lane}/{ses}"] = {"group": group, **{name: report.share(x["y"].to_numpy(float)) for name, x in band_rows(pick(clock), pick(sim))}}
    return out


def pct(s):
    return f"{s['share'] * 100:5.1f}% [{s['lo'] * 100:3.0f},{s['hi'] * 100:3.0f}] n={s['n']:<3}" if s["n"] else "    —"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="data/checks/tick-readouts.json")
    a = ap.parse_args()
    df = pairs.build(a.raw, "live")
    res = {"rounds": rounds(df, tick_index(a.raw)), "sessions": sessions(df)}
    print("P(B ahead): within one round | across rounds")
    for k, r in res["rounds"].items():
        print(f"  {k:<24} {pct(r['within'])} | {pct(r['across'])}   pairs with ticks {r['with_ticks']} {r['sessions_with_ticks']}")
    print("P(B ahead) per session: s = 0 | bands")
    for k, r in res["sessions"].items():
        print(f"  {k:<16} " + " | ".join(pct(r[b]) for b in ["s = 0"] + [x[0] for x in report.BANDS]))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, indent=1, sort_keys=True, default=float)
        fh.write("\n")
    print(a.out)


if __name__ == "__main__":
    main()
