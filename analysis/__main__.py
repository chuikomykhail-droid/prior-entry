"""python -m analysis <command>

    reproduce   raw runs -> data/derived (tables, fits, tests) and figures/ (light and dark SVG)
    synth       synthetic raw runs with known clocks, in the exact raw format (data/synthetic)
    recover     synth + reproduce on the synthetic runs + a check that the truth is recovered
    sim         the power simulation -> docs/POWER.md
    grids       pilot estimates of mu per family and lane -> mu_hat.json for `itb freeze-grids`
    pilot       the pilot's checks before the main run (landing, timing, window, QUIC, rank, c, fees)
    verify      re-read every block of the raw runs from the chain and compare (network)
    check       recompute data/derived into a temporary folder and compare (--full: with the bootstrap and placebos)
"""
import argparse
import json
import os
import sys
import time

# one BLAS thread per process: the work is many small fits, run in parallel processes
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m analysis")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("reproduce")
    p.add_argument("--raw", default="data/raw")
    p.add_argument("--out", default="data/derived")
    p.add_argument("--figures", default="figures")
    p.add_argument("--boot", type=int, default=200, help="cluster bootstrap replicates per cell")
    p.add_argument("--placebo", type=int, default=100, help="placebo shuffles")
    p.add_argument("--mode", default="live", help="which runs to read (live; dry for plumbing tests)")

    p = sub.add_parser("synth")
    p.add_argument("--out", default="data/synthetic")
    p.add_argument("--seed", type=int, default=7)

    p = sub.add_parser("recover")
    p.add_argument("--out", default="data/synthetic")
    p.add_argument("--derived", default="data/synthetic-derived")
    p.add_argument("--figures", default="data/synthetic-derived/figures")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--boot", type=int, default=50)
    p.add_argument("--placebo", type=int, default=30)

    p = sub.add_parser("sim")
    p.add_argument("--reps", type=int, default=300)
    p.add_argument("--out", default="docs/POWER.md")
    p.add_argument("--json", default="data/derived/power.json")
    p.add_argument("--quick", action="store_true", help="20 reps, for a smoke test")

    p = sub.add_parser("grids")
    p.add_argument("--raw", default="data/pilot")
    p.add_argument("--runs", nargs="*", help="pilot run ids (default: every live run under --raw)")
    p.add_argument("--out", default="design/mu_hat.json")

    p = sub.add_parser("pilot")
    p.add_argument("--raw", default="data/pilot")
    p.add_argument("--session", default="pilot")
    p.add_argument("--runs", nargs="*", help="run ids instead of the session")
    p.add_argument("--ledger", default="data/ledger.jsonl")
    p.add_argument("--out", default="data/pilot/pilot_check.json")

    p = sub.add_parser("verify")
    p.add_argument("--raw", default="data/raw")
    p.add_argument("--rpc", default=os.environ.get("ITB_RPC_URL", "https://api.mainnet-beta.solana.com"))
    p.add_argument("--limit", type=int, default=None, help="blocks to re-read (default all)")

    p = sub.add_parser("check")
    p.add_argument("--raw", default="data/raw")
    p.add_argument("--derived", default="data/derived")
    p.add_argument("--full", action="store_true", help="also recompute the bootstrap and the placebo shuffles (35-45 minutes)")
    p.add_argument("--tolerance", type=float, default=None, help="relative tolerance for numbers (default: compare.TOLERANCE)")
    p.add_argument("--details", type=int, default=3, help="largest differences to print per file")

    a = ap.parse_args(argv)
    if a.cmd == "reproduce":
        from . import report
        report.reproduce(a.raw, a.out, a.figures, boot_reps=a.boot, placebo_reps=a.placebo, mode=a.mode)
    elif a.cmd == "synth":
        from . import synth
        synth.write_runs(a.out, seed=a.seed)
    elif a.cmd == "recover":
        from . import report, synth
        truth = synth.write_runs(a.out, seed=a.seed)
        report.reproduce(a.out, a.derived, a.figures, boot_reps=a.boot, placebo_reps=a.placebo, mode="live")
        ok = synth.check_recovery(truth, a.derived)
        sys.exit(0 if ok else 1)
    elif a.cmd == "sim":
        from . import sim
        reps = 20 if a.quick else a.reps
        alpha = 0.05 / 8
        t = time.time()
        rows = sim.power(reps=reps, alpha=alpha)
        os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
        with open(a.json, "w") as fh:
            json.dump({"reps": reps, "alpha": alpha, "rows": rows}, fh, indent=1)
        sim.write_power_md(a.out, rows, reps, alpha, time.time() - t)
    elif a.cmd == "grids":
        from . import report
        report.pilot_grids(a.raw, a.runs, a.out)
    elif a.cmd == "pilot":
        from . import pilot
        res = pilot.check(a.raw, a.session, a.runs, a.ledger, a.out)
        sys.exit(0 if all(v.get("ok", True) for v in res["checks"].values()) else 1)
    elif a.cmd == "verify":
        from . import verify
        sys.exit(0 if verify.verify_chain(a.raw, a.rpc, a.limit) else 1)
    elif a.cmd == "check":
        from . import compare, verify
        tolerance = compare.TOLERANCE if a.tolerance is None else a.tolerance
        sys.exit(0 if verify.check_derived(a.raw, a.derived, a.full, tolerance, a.details) else 1)


if __name__ == "__main__":
    main()
