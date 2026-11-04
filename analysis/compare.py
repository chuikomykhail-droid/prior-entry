"""How a recomputation is compared with the committed data/derived.

Counts come out the same on every machine. Numbers from an optimizer do not: it stops at a slightly
different point on another build of the numeric libraries. So words, flags and the shape of every
file must match exactly, numbers must stay within the limits below, and every number that moved is
measured and printed instead of being reduced to "the bytes differ".

The limits come from a full recomputation in the Linux image against the committed run on Windows.
Nearly all numbers moved by less than 0.1%. Four kinds moved more, because the likelihood is flat
there, and each has a limit of its own instead of a wider limit for everything.
"""
import json
import os
import re
from dataclasses import dataclass, field

TOLERANCE = 0.05
ZERO = 1e-9  # differences below this are rounding noise around zero
SHAPE_TOLERANCE = 0.10  # the shape k trades off against the lapse rates
SHAPE_METRONOME = 20.0  # with k above this on both sides the curve is a metronome's to within 0.07
BOOTSTRAP_TOLERANCE = 0.15  # one replicate crossing between two optima moves a median
TIME_NOISE_MS = 0.3  # fit.SIGMA_MS: below the spread of the arrival gap a shutter cannot be told apart
LR_NOISE = 0.01  # a likelihood-ratio statistic around zero
QUICK_SKIPS = frozenset({"boot", "lane_ratio_bootstrap", "shuffle_s", "shuffle_lanes"})  # recomputed only by `check --full`

_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


@dataclass
class Result:
    name: str
    status: str = "same"  # same | close | DIFFERENT
    numbers: int = 0
    differ: int = 0
    above: int = 0
    numeric: list = field(default_factory=list)  # (relative difference, where, committed, recomputed), largest first
    other: list = field(default_factory=list)  # (where, committed, recomputed): anything that is not a number

    @property
    def largest(self):
        return self.numeric[0][0] if self.numeric else 0.0


def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def relative(a, b):
    d = abs(float(a) - float(b))
    return 0.0 if d < ZERO else d / max(abs(float(a)), abs(float(b)))


def within_limit(where, a, b, tolerance=TOLERANCE):
    """Is the move from `a` to `b` allowed for the number at this place in a file?"""
    rel, gap = relative(a, b), abs(float(a) - float(b))
    name = re.sub(r"\[\d+\]", "", where.rsplit(".", 1)[-1])
    if name == "k" or name.startswith("k_"):
        return rel <= SHAPE_TOLERANCE or min(a, b) > SHAPE_METRONOME
    if rel <= (BOOTSTRAP_TOLERANCE if "boot." in where or "lane_ratio_bootstrap" in where else tolerance):
        return True
    if name.endswith("_lr"):
        return gap <= LR_NOISE
    return (name.startswith("mu") or name.endswith("_ms") or "mu_ci" in where) and gap <= TIME_NOISE_MS


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
    """Table text: the words of a row must match; numbers may move by the tolerance or by one printed digit."""
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
            yield f"line {i}, number {n}", float(p), float(q), max(_last_place(p), _last_place(q))


def compare_values(name, pairs_of_values, tolerance):
    res = Result(name)
    for where, a, b, *grace in pairs_of_values:
        if _is_number(a) and _is_number(b):
            res.numbers += 1
            rel = relative(a, b)
            if rel > 0:
                res.differ += 1
                res.numeric.append((rel, where, a, b))
                one_digit = grace and grace[0] is not None and abs(a - b) <= grace[0] * (1 + 1e-9)
                if not one_digit and not within_limit(where, a, b, tolerance):
                    res.above += 1
        elif a != b:
            res.other.append((where, a, b))
    res.numeric.sort(key=lambda t: -t[0])
    res.status = "DIFFERENT" if res.other or res.above else "close" if res.differ else "same"
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
    """Lines for the log: one per file, then its largest differences."""
    if res.status == "same":
        return [f"same      {res.name}"]
    head = f"{res.status:<9} {res.name}: {res.differ} of {res.numbers} numbers moved, largest {100 * res.largest:.3g}%"
    if res.above:
        head += f", {res.above} beyond the limits"
    if res.other:
        head += f", {len(res.other)} words or fields differ"
    lines = [head]
    for where, a, b in res.other[:details]:
        lines.append(f"            {where}: {a!r} / {b!r}")
    for rel, where, a, b in res.numeric[:details]:
        lines.append(f"            {100 * rel:.3g}%  {where}: {a:g} / {b:g}")
    return lines
