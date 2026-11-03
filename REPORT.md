# Report

*Draft. Sections marked TBD are filled after the pilot and the main sessions.*

## 1. Dates of every measurement (UTC)

| When | What | Data |
|---|---|---|
| 2026-11-01 22:14 | Client survey: families, stake, versions, ingress, windows per hour | `data/survey/20261101T221427Z/` |
| 2026-11-01 22:34–22:48 | Probe simulation on mainnet, QUIC handshakes, slot clock, send-gap calibration, first dry-runs | `data/checks/`, `data/runs/20261101T*-dry/` |
| 2026-11-02 12:40 | Market rank: 48 blocks, 15,120 non-vote transactions | `data/survey/20261102T124027Z-market-rank/` |
| 2026-11-02 13:11 | `simulateTransaction` of all five probe variants, both lanes: all succeed, 600 CU consumed | `data/checks/simulate-20261102T131152Z.json` |
| 2026-11-02 13:11–13:38 | Dry-runs of the lane design on mainnet (predicted and event anchor) | `data/runs/20261102T13*-dry/` |
| 2026-11-02 23:15 | Funding of 12 payers (12 transfers, 60,000 lamports in fees) | `data/ledger.jsonl` |
| 2026-11-02 23:17–23:21 | Smoke test: 10 pairs on AgaveBam `5Cchr1XG` and Firedancer `9eGrDohd`, every cell; 20 of 20 probes landed in the target window, spend 195,000 lamports = ledger = balance drop | `data/pilot/20261102T231718Z-live/` |
| 2026-11-03 09:51–09:59 | Drift of our clock against NTP: +52.3 ppm | `data/checks/ntp-drift-20261103T095131Z.json` |
| 2026-11-03 10:13–10:15 | NTP replies delivered twice: 12 duplicates in 400 replies, 365 replies read late by the old loop | `data/checks/ntp-duplicates-20261103T101341Z.json` |
| 2026-11-03 11:11–11:19 | Pilot: 229 pairs on 15 validators of 8 families; 458 of 458 sent probes landed and executed; spend 3,091,500 lamports = landed fees = balance drop; all seven checks pass | `data/pilot/20261103T111104Z-live/`, `data/pilot/pilot_check.json` |
| TBD | Pre-registration frozen; Memo | |
| TBD | Session A | |
| TBD | Session B | |

Alpenglow activated on 21.10.2026 (epoch 1064); every measurement above is after it.

## 2. Confirmatory results

TBD — the table of `data/derived/results.md` (V1–V3, E1, L1–L5 with Holm).

## 3. Exploratory results

TBD — phase in the slot, convexity, per validator, sessions, rank as a covariate, foreign transactions
between A and B, small families, buffered pairs.

## 4. What went wrong

- **Our own timing was off by 0.44 ms (found in dry-run, fixed before any send).** The slot-clock
  estimate was computed between waking up and writing A, which delayed A by ~0.4 ms and shrank every gap
  by that much (median |s_actual − s| 0.44 ms on 182 dry-run pairs). Moved after the writes: median
  |error| 0.001 ms on 175 pairs (`data/runs/20261102T133602Z-dry`). In live mode the analysis uses the
  actual gap anyway.
- **A late pair used to collapse its gap.** When both probes were already behind their plan (late anchor
  event), they went out back to back and s became ~0. Now a late pair is moved as a whole and the shift is
  logged (`shift_ms`); more than 50 ms late, it is not sent.
- **The event anchor does not work on the public RPC.** With `--anchor event` the in-window pairs wait
  for the first-shred notification of the window's first slot; on `api.mainnet-beta.solana.com` the
  WebSocket delivers it 1–5 s late, so most windows were skipped (`data/runs/20261102T131506Z-dry`).
  The main run uses the predicted anchor (prediction error p10 −290 / p90 +370 ms) and computes the phase
  of every pair afterwards from the nodes' own first-shred timestamps; pairs that fall before the window
  are "buffered" and leave the clock fits. With a provider WebSocket the event anchor can be switched on.
- **The window anchor was predicted too early, 20 s ahead (found in the smoke test).** A window was chosen
  up to 20 s before it began and its start predicted once, at that moment, from a line through the last
  150 slots: an extrapolation over ~100 slots of a random walk (slot times under Alpenglow vary by ≈30 ms
  inside a window and ≈55 ms at a leader change). In the smoke test the anchor missed by −957 to +383
  ms, and all five AgaveBam pairs went out before their window. Now the start is predicted again 1.2 s
  before the window, from a line pinned to the newest four timestamps. Offline on 1,365 recorded
  window starts: error p10 −288 / p50 −27 / p90 +145 ms. In a dry-run of 100 windows
  (`data/runs/20261102T233113Z-dry`): 94% within ±300 ms against 69% for the old prediction of the
  same windows; 8% of in-window pairs left before the window.
- **Our clock drifted, and our NTP client read duplicated replies (found in a review before the
  pilot).** The monotonic clock of the measurement PC runs 52.3 ppm fast against NTP (22 samples over 8
  minutes, residual 0.33 ms). Mapped to UTC once at the start of a run, it gains ~0.19 s an hour: pairs
  would have left earlier and earlier relative to the leader's window, and the analysis would have counted
  some pairs that left before the window as in-window. Now NTP is measured every 30 s against the run's
  own clock (`ntp.jsonl`), the slot clock uses the newest offset, and the analysis subtracts a line
  through the samples. In the same measurement, 8 of 30 rounds had a reply 0.7–1 ms "fast" and 0.18–0.39 s
  off, and a dry-run started with one (0.1 ms, +190 ms). The cause: our network delivers some UDP replies
  twice (12 of 400), and the client took each duplicate for the answer to the next request; once behind,
  it stayed behind (365 of 400 replies read late). No measured run was hit (round trips 35–39 ms in every
  `meta.json`). Now every request carries a nonce that the reply must echo (RFC 5905), and a measurement
  takes the fastest of the replies that agree with their median within 25 ms, at least three of them;
  a test with a server that answers everything twice fails without the nonce.
- **The slot clock's fit stole time from the probe writes (found in the same review).** A fit sorts
  ~9,000 slopes (~0.5 ms of CPU) and was computed again on every call, hundreds of times a second, on
  the threads that time the writes. In dry-runs of the pilot configuration on an idle PC, 2 of 229 pairs
  had their gap off by 0.5–1.9 ms (p99 0.24 ms); while builds and analysis jobs ran on the same PC, 8 of
  229, up to 15 ms. The analysis uses the actual gap, but a delayed packet would leave later than its
  recorded write. The fit is now cached until a notification or an NTP measurement arrives: on the idle
  PC, max 0.27 ms, p99 0.05 ms, none above 0.5 ms (`data/dry`, not kept). Live runs get the PC to
  themselves.
- **The window started later than the analysis assumed (found in the pilot).** The analysis placed a
  slot's start 100 ms before the RPC node's first shred of it. In the pilot, no probe landed in a slot
  whose next slot's first shred came less than 29 ms after the probe was written (452 probes; 1st
  percentile 49 ms): our write-to-leader time plus the leader's start-to-RPC-node time is at most
  ~30–70 ms, not 100. Pairs written in the gap would have counted as in-window although they reached
  the leader before the window began. The window now counts as started at its first shred at the RPC
  node, which no buffered pair can pass; it costs 6% of the complete pairs. The pilot's last two
  windows had no slot timestamps at all (the run exited before the WebSocket delivered them, and the
  analysis then extrapolated from 0.2–0.4 s away): the run now waits 10 s at the end, and a window
  whose start cannot be placed from its own slots is left out of the clock fits.
- **BAM ingress drops some unstaked connections (pilot).** `9rkJMARq` (AgaveBam) lost 4 of 38 pairs and
  `9jxgosAf` (FireBAM) 1 of 14 to "closed by peer"; those probes never left, cost nothing and went back
  to the quota. Both stay below the 30% limit.
- **The lane test was anti-conservative with lapse rates per lane** (simulation, before any data): at
  n = 160 it rejected 5% of null replicates at alpha 0.006. The pre-registered test shares the lapse rates
  across the two lanes of a family (docs/POWER.md).
- **k is weakly identified.** Against free lapse rates the regularity k of a gamma clock varies widely
  between replicates (true k = 4: estimates 1.5–26 at 1,500 pairs); mu is the robust number, k is
  reported with its interval and the shape comparison.
- TBD after the live runs.

## 5. Deviations from the pre-registration

TBD (none yet: not frozen).

## 6. What the design does not separate

See README, "What this design does not separate".

## 7. Verification and reproduction

- `docker compose up` recomputes `data/derived` from `data/raw` with no network and compares byte for byte.
- `docker compose --profile verify up` re-reads every block with a probe from mainnet and compares
  position, producer, fee and success (an implementation independent of the Rust collector).
- `python -m analysis recover` writes synthetic raw runs with known clocks in the exact raw format and
  checks that the pipeline recovers them (section 9).

## 8. Cost

TBD — ledger reservations vs on-chain balance differences, to the lamport. Plan: ≈0.033 SOL of a hard
cap of 0.045 SOL.

## 9. Synthetic recovery

`python -m analysis recover` (seed 7) writes two synthetic sessions in the exact raw format — 523 windows,
2,185 pairs, landing losses, prediction error of the window anchor (so some pairs are buffered), foreign
transactions around our probes — with known clocks, runs the whole pipeline and compares (2026-11-03, with
the window start at the first shred, PREREGISTRATION §6.3):

| Family | Lane | True mu, ms | Estimate | 95% interval |
|---|---|---|---|---|
| AgaveBam | VIP / ECO | 20 / 20 (metronome) | 19.4 / 15.5 | [10.4, 27.0] / [3.6, 25.2] |
| HarmonicAgave | VIP / ECO | 50 / 50 (metronome) | 55.0 / 46.8 | [28.6, 65.0] / [32.9, 61.6] |
| HarmonicFiredancer | VIP / ECO | 15 / 15 (gamma k = 30) | 17.6 / 14.4 | [12.4, 20.4] / [5.5, 20.3] |
| JitoLabs | VIP / ECO | 3 / 9 (queue) | 0.6 / 3.0 | [0.2, 3.7] / [1.0, 12.9] |
| Firedancer | VIP / ECO | 10 / 25 (queue) | 19.8 / 30.8 | **[13.3, 24.9]** / [6.8, 67.2] |
| FireBAM, Rakurai, Agave | both | 20; 5; 2 / 4 | — | all cover; Agave VIP and Rakurai VIP fell below 40 clock pairs |

13 of 14 intervals cover the truth (one miss, Firedancer VIP; 0.7 expected at 95%). All nine confirmatory
verdicts come out as built in: V1, V2 kept, V3 rejected (15 vs 50 ms), E1 rejected, L1–L3 kept, L4 and L5
rejected. Placebos: lexicographic rule 50.8% (n = 1,731); s shuffled within a cell — a false rule in 2 of
30 shuffles (5% expected); lanes shuffled within windows — lane-test p-values uniform (KS p = 0.13).
Buffered pairs written more than 100 ms before the window's first shred: B ahead in 98% (n = 66); in the
boundary zone between that and the first shred, 31% (n = 62), as in the window (32%) — which is why
that zone stays out of both. (The synthetic RPC node sees a slot 100 ms after it starts, a longer delay
than the pilot measured, so the strict start excludes more here than on mainnet.)

## Appendix: the psychophysics dictionary

| Here | In psychophysics |
|---|---|
| the validator ordering a pair | an observer in a temporal-order judgement |
| s, B sent after A | stimulus onset asynchrony |
| P(B ahead \| s) | the psychometric function |
| s50 | the point of subjective simultaneity |
| eps1, eps2 | lapse rates |
| the shutter mu | the temporal integration window |
