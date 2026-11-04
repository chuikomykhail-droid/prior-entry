"""How a recomputation is compared with the committed data/derived.

Counts come out the same on every machine. Numbers from an optimizer do not: it stops at a slightly
different point on another build of the numeric libraries, and even the same image picks different
code paths on another processor. Measured on Windows, Linux x64 and Linux arm64: every count is
identical and no verdict changes, a shutter or its interval moves by less than 1%, and parameters on
a flat likelihood wander (the shape k went from 6 to 300 in a cell whose shutter is below the timing
noise).

So the check fails on what would mean a wrong result: a count, a word, a flag or a verdict that
differs, or a shutter, its interval or a Holm-adjusted p beyond the limits below. Every other number
is measured and printed, and does not fail it.
"""
import json
import os
import re
from dataclasses import dataclass, field

TOLERANCE = 0.10
TIME_NOISE_MS = 0.3  # fit.SIGMA_MS: below the spread of the arrival gap a shutter cannot be told apart
P_NOISE = 0.02
ZERO = 1e-9  # differences below this are rounding noise around zero
QUICK_SKIPS = frozenset({"boot", "lane_ratio_bootstrap", "shuffle_s", "shuffle_lanes"})  # recomputed only by `check --full`
EXPLORATORY = frozenset({"buffer_sensitivity.json", "phase.json", "sessions.json"})  # fits on small splits of a cell
RENDERED = frozenset({"results.md"})  # tables drawn from the JSON files, which are the ones judged
# words that follow a number on a flat likelihood: which shape has the best AIC, a bound that left the grid
FLAT_WORDS = frozenset({"strictness", "best_aic", "lo_censored", "hi_censored", "s10_ms", "convex_mu_from_slope_ms"})

_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


@dataclass
class Result:
    name: str
    status: str = "same"  # same | close | DIFFERENT
    numbers: int = 0
    differ: int = 0
    above: int = 0
    held: list = field(default_factory=list)  # (relative difference, where, committed, recomputed), largest first
    moved: list = field(default_factory=list)  # the same, for numbers that are printed but do not fail the check
    other: list = field(default_factory=list)  # (where, committed, recomputed): counts, words, flags
    loose: list = field(default_factory=list)  # the same, for words that follow a flat number


def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _field(where):
    return re.sub(r"\[\d+\]", "", where.rsplit(".", 1)[-1])


def relative(a, b):
    d = abs(float(a) - float(b))
    return 0.0 if d < ZERO else d / max(abs(float(a)), abs(float(b)))


def is_held(file, where):
    """Does this number fail the check when it moves too far?"""
    if file in EXPLORATORY or file in RENDERED:
        return False
    if file.endswith(".csv"):
        return True
    if "shapes." in where or "boot." in where or "lane_ratio_bootstrap" in where or "profile" in where:
        return False
    name = _field(where)
    return name.startswith("mu") or "mu_ci" in where or name == "p_holm"


def within_limit(where, a, b, tolerance=TOLERANCE):
    rel, gap = relative(a, b), abs(float(a) - float(b))
    if rel <= tolerance:
        return True
    return gap <= (P_NOISE if _field(where) == "p_holm" else TIME_NOISE_MS)


def _leaves(a, b, where, skip):
    """Pairs of values at the same place in two parsed JSON documents."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k in skip:
                continue
            place = f"{where}.{k}" if where else k
            if k in a and k in b:
                yield from _leaves(a[k], b[k], place, skip)
            else:
                yield place, a.get(k, "<absent>"), b.get(k, "<absent>")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            yield where, f"{len(a)} items", f"{len(b)} items"
        for i, (x, y) in enumerate(zip(a, b)):
            yield from _leaves(x, y, f"{where}[{i}]", skip)
    else:
        yield where, a, b


def _last_place(text):
    """One unit in the last printed digit: 35.7 -> 0.1, 8 -> 1, 3e-05 -> 1e-05."""
    mantissa, _, exponent = text.lower().partition("e")
    places = len(mantissa.partition(".")[2])
    return 10.0 ** (int(exponent or 0) - places)


def _text_rows(a, b):
    """Table text, row by row: the words of a row, then its numbers with the size of their last printed digit."""
    rows_a, rows_b = a.splitlines(), b.splitlines()
    if len(rows_a) != len(rows_b):
        yield "file", f"{len(rows_a)} lines", f"{len(rows_b)} lines", None
    for i, (x, y) in enumerate(zip(rows_a, rows_b), 1):
        if x == y:
            continue
        if _NUMBER.split(x) != _NUMBER.split(y):
            yield f"line {i}", x[:160], y[:160], None
            continue
        for n, (p, q) in enumerate(zip(_NUMBER.findall(x), _NUMBER.findall(y)), 1):
            whole = p.lstrip("+-").isdigit() and q.lstrip("+-").isdigit()
            yield f"line {i}, number {n}", int(p) if whole else float(p), int(q) if whole else float(q), max(_last_place(p), _last_place(q))


def compare_values(name, values, tolerance=TOLERANCE):
    res = Result(name)
    for where, a, b, *digit in values:
        if _is_number(a) and _is_number(b):
            res.numbers += 1
            if isinstance(a, int) and isinstance(b, int):  # a count
                if a != b:
                    (res.loose if name in RENDERED else res.other).append((where, a, b))
                continue
            rel = relative(a, b)
            if rel == 0:
                continue
            res.differ += 1
            if not is_held(name, where):
                res.moved.append((rel, where, a, b))
                continue
            res.held.append((rel, where, a, b))
            one_digit = digit and digit[0] is not None and abs(a - b) <= digit[0] * (1 + 1e-9)
            if not one_digit and not within_limit(where, a, b, tolerance):
                res.above += 1
        elif a != b:
            if name in RENDERED or _field(where) in FLAT_WORDS or "mu_ci" in where:
                res.loose.append((where, a, b))
            else:
                res.other.append((where, a, b))
    res.held.sort(key=lambda t: -t[0])
    res.moved.sort(key=lambda t: -t[0])
    res.status = "DIFFERENT" if res.other or res.above else "close" if res.differ or res.loose else "same"
    return res


def compare_file(path_a, path_b, tolerance=TOLERANCE, skip=frozenset()):
    """`path_a` committed, `path_b` recomputed."""
    name = os.path.basename(path_a)
    if not os.path.exists(path_b):
        return Result(name, status="DIFFERENT", other=[("file", "present", "not recomputed")])
    with open(path_a, encoding="utf-8") as fh:
        text_a = fh.read()
    with open(path_b, encoding="utf-8") as fh:
        text_b = fh.read()
    if text_a == text_b:
        return Result(name)
    if name.endswith(".json"):
        return compare_values(name, _leaves(json.loads(text_a), json.loads(text_b), "", skip), tolerance)
    return compare_values(name, _text_rows(text_a, text_b), tolerance)


def describe(res, details=3):
    """Lines for the log: one per file, then what moved, committed / recomputed, what can fail the check first."""
    if res.status == "same":
        return [f"same      {res.name}"]
    head = f"{res.status:<9} {res.name}: {res.differ} of {res.numbers} numbers moved"
    if res.held:
        head += f", held numbers by at most {100 * res.held[0][0]:.3g}%"
    if res.above:
        head += f", {res.above} beyond the limits"
    if res.other:
        head += f", {len(res.other)} counts, words or flags differ"
    lines = [head]
    lines += [f"            differs  {where}: {a!r} / {b!r}" for where, a, b in res.other[:details]]
    lines += [f"            held     {100 * rel:.3g}%  {where}: {a:g} / {b:g}" for rel, where, a, b in res.held[:details]]
    lines += [f"            moved    {100 * rel:.3g}%  {where}: {a:g} / {b:g}" for rel, where, a, b in res.moved[:details]]
    lines += [f"            moved    {where}: {a!r} / {b!r}" for where, a, b in res.loose[:details]]
    return lines


def summary(results, tolerance=TOLERANCE):
    """The closing lines of a check."""
    same = sum(r.status == "same" for r in results)
    close = sum(r.status == "close" for r in results)
    different = sum(r.status == "DIFFERENT" for r in results)
    lines = [f"{len(results)} files: {same} identical, {close} with numbers moved within the limits, {different} different"]
    if not different:
        held = max(((r.held[0], r.name) for r in results if r.held), key=lambda t: t[0][0], default=None)
        lines.append("no count, word, flag or verdict differs" + (
            f"; the largest move of a shutter, its interval or a Holm p is {100 * held[0][0]:.3g}% ({held[1]} {held[0][1]}: {held[0][2]:g} / {held[0][3]:g})" if held else ""))
    lines.append(f"fails on: any count, word, flag or verdict; a shutter or its interval beyond {100 * tolerance:g}% and {TIME_NOISE_MS:g} ms; "
                 f"a Holm p beyond {100 * tolerance:g}% and {P_NOISE:g}. Everything else is printed as \"moved\": see analysis/compare.py")
    return lines
