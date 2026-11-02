"""Reading the raw runs written by `itb run` and `itb collect` (format: docs/DATA.md)."""
import gzip
import json
import os


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run_dirs(raw, mode="live"):
    """Run directories under `raw` whose meta says `mode`, oldest first."""
    if not os.path.isdir(raw):
        return []
    out = []
    for name in sorted(os.listdir(raw)):
        d = os.path.join(raw, name)
        meta = read_json(os.path.join(d, "meta.json"))
        if meta and meta.get("mode") == mode:
            out.append(d)
    return out


def load_run(d):
    """Everything of one run, as lists of dicts."""
    return {
        "dir": d,
        "meta": read_json(os.path.join(d, "meta.json"), {}),
        "txs": read_jsonl(os.path.join(d, "txs.jsonl")),
        "windows": read_jsonl(os.path.join(d, "windows.jsonl")),
        "slots": read_jsonl(os.path.join(d, "slots.jsonl")),
        "gossip": read_jsonl(os.path.join(d, "gossip.jsonl")),
        "landings": read_jsonl(os.path.join(d, "landings.jsonl")),
        "blocks": read_jsonl(os.path.join(d, "blocks.jsonl.gz")),
    }
