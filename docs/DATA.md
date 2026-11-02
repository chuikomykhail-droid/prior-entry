# Raw data format

Every run of `itb run` writes one directory `data/raw/<UTC start>-<live|dry>/`; `itb collect` adds the
landings and block extracts to the same directory. Nothing in `data/derived/` is edited by hand: it is
recomputed from `data/raw/` by `python -m analysis reproduce`.

Times: `*_utc` are from the local clock; the local clock's offset from true time (SNTP, `time.google.com`)
is `ntp_offset_ms` in `meta.json` (local minus true). Gaps between our own writes come from the monotonic
clock and are exact to about a microsecond.

## meta.json

| Field | Meaning |
|---|---|
| `run_id`, `mode` | `<UTC>-live` or `-dry` |
| `network` | genesis hash, `mainnet`, current slot, `after_alpenglow` — checked before anything is sent |
| `not_after_utc`, `cap_lamports` | the live run's deadline and the project-wide spend cap |
| `seed` | RNG seed of the design (cells, gaps, start moments, payer assignment) |
| `timing` | `start_lo_ms`/`start_hi_ms` (in-window probes fire at random moments in this range after the window anchor), `ctrl_offset_ms` (C2 pairs), `rpc_lag_ms`, `anchor` (`predicted` or `event`), `event_wait_ms` |
| `cells` | for every (series, lane): the A and B probe parameters, their cost and key, the quotas |
| `design`, `grid_override_ms`, `rev_grid_ms` | the frozen grid file and any override |
| `targets` | validators targeted: identity, client id, version, TPU, stake (gossip at start) |
| `ntp_offset_ms`, `clock_at_start` | clock calibration |

## txs.jsonl — one line per probe (two per pair)

| Field | Meaning |
|---|---|
| `pair_id`, `window_id`, `role` | pair `<first slot>-<j>`; `A` is the cheap probe (C2: X), `B` the dear one (C2: Y) |
| `series`, `lane` | `FEE`, `REV`, `CTRL_C2`; `VIP` (600 CU) or `ECO` (200,000 CU) |
| `s_ms`, `a_offset_ms`, `anchor` | planned gap (B minus A) and A's planned moment after the window anchor |
| `signature`, `payer`, `dest` | the transaction; `dest` is a fresh address per probe |
| `cu_limit`, `cu_price`, `loaded_data`, `priority_fee`, `total_fee`, `agave_cost`, `agave_priority` | economics and the scheduler key |
| `planned_utc`, `write_utc`, `late_us` | planned moment and the moment the bytes were written to the QUIC stream |
| `a_write_us`, `b_write_us`, `s_actual_ms` | the two write timestamps (µs from the run's anchor) and the **actual gap** used in the analysis |
| `shift_ms` | a pair already behind its plan moves as a whole (gap kept) |
| `sent`, `error` | whether the bytes left (live) and why a pair was not fired |
| `leader`, `family`, `version`, `tpu`, `first_slot`, `window_slots` | the target window |

## windows.jsonl — one line per window

Leader, client id and version at planning time, predicted start, the cells planned, connection time,
blockhash age, the anchor event (`event`: arrival and server timestamp relative to the prediction, or
`missed`), `pairs_fired`, and `skipped` with the reason when the whole window was dropped.

## slots.jsonl, gossip.jsonl

`slots.jsonl`: every `firstShredReceived` the RPC node reported — `server_unix_ms` (the node's own
clock) and `local_unix_ms` (our arrival). A slot starts about `rpc_lag_ms` before `server_unix_ms`; the
analysis computes each pair's phase in its slot from these. `gossip.jsonl`: the targets' client id,
version and TPU every 60 s (client ids change on the fly).

## landings.jsonl (itb collect)

One line per sent probe that has a status: `slot`, `index` (position in the block, all transactions
counted, as `getBlock` returns them), `fee` charged, `cu_consumed`, `ok`, `err`, `producer` (recipient
of the block's fee reward) and the scheduled `leader`. `status_only: true` when the block could not be read.

## blocks.jsonl.gz (itb collect)

One line per block holding a probe: `slot`, `parent_slot`, `block_time`, `blockhash`, `producer`,
`leader`, `n_tx`, and `tx`: columns in block order — `fee`, `sigs`, `writable`, `data_bytes`, `cu_limit`
(requested, or the runtime default when none is set; `cu_limit_set`), `cu_price`, `data_limit`,
`cu_consumed`, `ok`, `vote`. The scheduler key of every transaction is rebuilt from these:

```
key  = (fee - 2500 * sigs) * 10^6 / (cost + 1)
cost = 720 * sigs + 300 * writable + data_bytes / 4 + cu_limit + 8 * ceil(data_limit / 32 KiB)
```

## data/derived/

| File | Content |
|---|---|
| `pairs.csv` | one row per pair: outcome `y` (B ahead), actual `s_ms`, completeness and the exclusion reason, `buffered`, phase in the slot, rank of A and B in their block, block load, foreign transactions between A and B |
| `losses.json` | counts per family, series and lane: planned, complete, buffered, each exclusion reason |
| `key_control.json` | C2 "X first" and FEE at s ≤ 1 ms "B first", per family, with the predictions of four keys |
| `curves.json` | binned share of "B ahead" with Wilson intervals |
| `fits.json` | per (family, lane): mu, k, eps1, eps2, profile and 95% interval of mu, cluster-bootstrap interval, shape comparison, s50/s10, convexity test |
| `confirmatory.json` | V1–V3, E1, L1–L5 with Holm-adjusted p, and the window-bootstrap interval of mu_ECO / mu_VIP |
| `validators.json`, `phase.json`, `sessions.json`, `rank.json`, `buffered.json`, `placebo.json` | exploratory |
| `results.md` | the tables of README and REPORT |
