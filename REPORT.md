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
| 2026-11-03 11:52 | Pre-registration frozen after the pilot (first freeze) | commit `375c598` |
| 2026-11-03 12:20–13:55 | Review of the pilot per validator, slot boundaries and late overtakes; quick simulations; vendor pages read again (unchanged); pre-registration amended before the Memo, grids frozen again | `docs/PREREGISTRATION.md` §10, `scripts/amendment/`, `design/grids.json` |
| 2026-11-03 13:47–13:50 | Dry-run of the amended design: 42 windows, quotas of q = 0.646, 12 of 156 planned FEE pairs at s = 0 | `data/runs/20261103T134717Z-dry/` |
| 2026-11-03 14:33 | Pre-registration fixed on mainnet: Memo from the funder `41htrFv3CVxh34fs4wLUZBQtZGSRqti7oG8LJe5da3ft`, slot 464,933,869, text `shutter-speed prereg sha256 92596a366e1ed86f244de17c40beb48120689f963c3123a168ba1e5417d3e04b commit 399eedd2e2be7c6f3e9dae50dadc652891c5bd6f` (SHA-256 of `docs/PREREGISTRATION.md` and the commit that holds it); fee 5,000 lamports | tx `4YVHq5kTCkB3erDZvgBoizrRAAGFJBq3vci9pA5y65zcgpchBxRC1zMCot6Bd38h3MtmLTCRDHAMuY4gk14F7gZW`, `data/ledger.jsonl` |
| 2026-11-03 14:43–15:27 | Session A: 1,433 pairs fired on 15 validators of 8 families in 355 windows, every quota filled; 2,769 of 2,865 sent probes landed; 67 pairs lost their connection before A was written and went back to their quotas; spend 18,684,500 lamports = landed fees = balance drop; the pilot's checks: landing, timing, window and rank pass, one Agave validator lost 40% of its pairs to closed connections (§4) | `data/raw/20261103T144313Z-live/`, `data/checks/session-A-20261103T144313Z.json`, `data/checks/balance-drop-20261103T144313Z-live.json` |
| 2026-11-03 18:30 | Top-up of the 12 payers for session B, each to 2,500,000 lamports above rent (12 transfers, 15,911,000 lamports moved from the funder, 60,000 in fees); session A had left every payer below the run's balance check | `data/ledger.jsonl` |
| 2026-11-03 19:23 | Builder ticks read from the 706 session A blocks that hold a probe: BAM every 20 ms, Harmonic every 50 ms, none in other families (§3) | `data/raw/20261103T144313Z-live/ticks.jsonl`, `data/checks/ticks-20261103T144313Z-live.json` |
| 2026-11-03 23:24 – 2026-11-04 13:49 | Link watch before session B: one SNTP round trip to `time.google.com` every 10 s, with the link in use (§4). Session B was held back on these measures alone | `data/checks/link-before-B.csv` |
| 2026-11-04 13:44 | QUIC handshakes over the cable, no transactions: 24 of 24 | `data/checks/quic-probe-20261104T134446Z.json` |
| 2026-11-04 13:49–14:34 | Session B, 23 h after session A: 1,433 pairs fired on 15 validators of 8 families in 365 windows, every quota filled; 2,789 of 2,864 sent probes landed; 117 pairs went back to their quotas (114 lost their connection before A was written, 3 were too late); spend 18,822,000 lamports = landed fees = balance drop; the pilot's checks: landing, timing, window and rank pass, one FireBAM validator lost 46% of its pairs to closed connections (§4) | `data/raw/20261104T134938Z-live/`, `data/checks/session-B-20261104T134938Z.json`, `data/checks/balance-drop-20261104T134938Z-live.json` |

Alpenglow activated on 21.10.2026 (epoch 1064); every measurement above is after it.

## 2. Confirmatory results

TBD — the table of `data/derived/results.md` (V1–V3, E1, L1–L5 with Holm).

## 3. Exploratory results

TBD — phase in the slot, convexity, per validator, sessions, rank as a covariate, foreign transactions
between A and B, small families, buffered pairs.

### Builder ticks (found after the pre-registration)

BAM and Harmonic leaders write a tick transaction into their blocks. Its data hold the slot, a wall-clock
time in ns and the declared round length (`docs/DATA.md`, `scripts/ticks.py`). In the 706 blocks of
session A that hold a probe:

| Family of the producer | Blocks | With ticks | Ticks per block (median) | Gap between ticks, ms (p10 / median / p90) | Declared |
|---|---:|---:|---:|---|---:|
| AgaveBam | 95 | 95 | 9 | 19.8 / 20.0 / 21.3 | 20 ms |
| FireBAM | 24 | 24 | 9 | 19.4 / 20.0 / 21.5 | 20 ms |
| HarmonicAgave | 137 | 137 | 4 | 50.0 / 50.0 / 50.1 | 50 ms |
| HarmonicFiredancer | 150 | 150 | 4 | 50.0 / 50.0 / 50.0 | 50 ms |
| Agave, Firedancer, JitoLabs, Rakurai | 294 | 0 | — | — | — |

The rounds exist and run at the published periods, as the builders' own clocks record them, and the
families we took from gossip match the chain marker in every block (`data/checks/ticks-20261103T144313Z-live.json`).
That is not yet the claim we test: a 20 ms round says nothing by itself about whether a dearer transaction
that arrives later in the same round goes first, and that is what the probes measure. Fixed before any
outcome is read: for each complete pair in a builder block, whether A and B lie between the same two ticks,
and P(B ahead) within one round against across rounds.

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
- **The first freeze planned for neither validators of one client disagreeing nor overtakes long after
  the published period (found in a review of the pilot, before the Memo).** In the pilot `E1r4Psq8`
  (JitoLabs) and `JD549Hsb` (Firedancer) kept A first even at a 2–3 µs gap, while `HEL1USMZ` and
  `9eGrDohd` of the same clients sorted; on the BAM validators B was still ahead at s > 50 ms in 5 of 11
  pairs. Fitted per family, the first gives a shutter that describes neither validator; the second hides
  in the lapse rate eps1 (in simulation V1 was kept in 30 of 30 replicates with 30% of A waiting ~100 ms
  longer). Amended before any main-run send: simultaneous pairs, a per-validator table, late overtakes,
  the claim tests inside one slot (PREREGISTRATION §10).
- **Session A gave fewer clock pairs than q was set for (found after its collection, before session B).**
  912 of the 1,361 fired FEE and REV pairs entered the clock fits (0.670), against the c' = 0.774 behind
  q = 0.646: 17.5% of the complete pairs were buffered (pilot 11.4%; AgaveBam 31%, JitoLabs 20%), 45 were
  untimed (13 reconnects of the public RPC's slot WebSocket) and 116 simultaneous, out by design. Each
  session thus gives ~87% of the planned clock pairs, AgaveBam ~60 per lane instead of 88. q stays as
  frozen: a session never changes on its own data, and making up the gap in session B would take ~25.3M
  lamports of the 21.4M left under the cap.
- **One Agave validator closed its connection under 40% of its pairs (session A).** `5Us18hLZ` dropped the
  QUIC connection ("closed by peer") under 18 of its 45 planned pairs, above the pilot's 30% limit;
  `7QQGNm3p` (Agave) under 18 of 72, three BAM validators under 8–13 each. 67 of these pairs never left and
  went back to their quotas, which later windows filled; one lost only its B. The ledger keeps their
  reservations.
- **The sender's link to the internet changed between the sessions (the pre-registration does not fix it).**
  Session A ran on 2.4 GHz Wi-Fi. Checked before session B, that link had gone bad: on the night of 3–4
  November the SNTP round trip to `time.google.com` was 110–135 ms for at least 1.5 h (session A: median
  35.5, max 39.2 ms), with the Wi-Fi gateway itself at about 100 ms, and on 4 November the internet dropped
  three times for 3–9 minutes (`data/checks/link-before-B.csv`). We do not know why. So session B did not
  start at the first allowed moment (22:43 UTC on 3 November) but 15 hours later, over a 1 Gbit/s cable.
  That choice looked only at these link measures, before any outcome of either session was read. In
  session B the round trip was median 33.7, p90 34.2, max 41.5 ms (85 samples, no errors; session A 35.5,
  37.5, 39.2), and QUIC round trips to the validators were a median 2.3 ms shorter than on the Wi-Fi on 1
  November (21 validators). A and B of a pair always share the link, but any difference between the
  sessions mixes in this change, with the day and the versions below.
- **Validators changed between the sessions.** `Awes4Tr6` moved from HarmonicFiredancer (version 26.10.5)
  to HarmonicAgave (4.4.0). PREREGISTRATION §2 lists it under the first, and §6 takes a pair's family from
  the gossip snapshot nearest to its window, so its pairs count as HarmonicFiredancer in session A and
  HarmonicAgave in session B. In session B HarmonicFiredancer therefore rests on `EvnRmnMr` alone, and
  HarmonicAgave on three validators. `7QQGNm3p`, `5Us18hLZ` (the whole Agave family) and `EkvdKhUL` moved
  from 4.3.2 to 4.4.0, `E3mDbFMr` and `ana2y2Yv` (Rakurai) changed their TPU address, and the epoch changed
  (1076 to 1077). No target changed client or version during a session.
- **BAM ingress closed more connections in session B, and Agave stopped closing them.** `9jxgosAf`
  (FireBAM) dropped the QUIC connection under 70 of its 152 planned pairs (46%; session A 14%), above the
  pilot's 30% limit, `5Cchr1XG` (AgaveBam) under 36 of 148 (24%; 9%) and `9rkJMARq` under 10 of 135 (7%; 6%).
  The two Agave validators, at 40% and 25% in session A, lost none on 4.4.0, and no other family lost any.
  114 of these pairs never left and went back to their quotas, which later windows filled (FireBAM took 26
  windows instead of 16); two lost only their B. A pair that never left cannot select on which probe goes
  first. Three more pairs were over 50 ms late, were skipped before any reservation and went back too.
- **Session B gave more clock pairs than session A, still fewer than q was set for.** 993 of the 1,360 fired
  FEE and REV pairs entered the clock fits (0.730; session A 0.670; c' = 0.774): 15.1% of the complete pairs
  were buffered (AgaveBam 27%), 7 were untimed (3 reconnects of the slot WebSocket; session A 45 and 13) and
  110 simultaneous, out by design. Both sessions together: 1,905 clock pairs, about 90% of the plan, AgaveBam
  130 per lane instead of 176. Whether the cable helped cannot be separated from the day.

## 5. Deviations from the pre-registration

None yet. The pre-registration was frozen after the pilot (commit `375c598`) and amended once, after a
review of the pilot and before the Memo and any main-run send (`docs/PREREGISTRATION.md` §10); the Memo
holds the amended version. Both sessions ran its command and filled its quotas, 23 h apart, and no outcome
was read before both were collected. The changes of link and of validators between them are in §4: the
pre-registration does not fix the link, and its §6 decides the family of `Awes4Tr6`.

## 6. What the design does not separate

See README, "What this design does not separate".

## 7. Verification and reproduction

- `docker compose up` recomputes `data/derived` from `data/raw` with no network and compares byte for byte.
  GitHub Actions builds the image and runs the tests on every push (`.github/workflows/docker.yml`), and
  the full recomputation once `data/derived` holds the results.
- `docker compose --profile verify up` re-reads every block with a probe from mainnet and compares
  position, producer, fee and success (an implementation independent of the Rust collector).
- `python -m analysis recover` writes synthetic raw runs with known clocks in the exact raw format and
  checks that the pipeline recovers them (section 9).

## 8. Cost

Plan: both sessions at q = 0.646 cost at most 38,691,000 lamports (every probe lands), with the 3,359,000
already reserved (funding, smoke test, pilot, Memo) at most 0.042 SOL of the hard cap of 0.045 SOL. The
ledger reserves a pair's worst case before it is fired and keeps it whether or not the pair leaves or
lands; the cap counts these reservations.

| | Reserved | Spent (landed fees) |
|---|---:|---:|
| Funding, smoke test | 195,000 | 195,000 |
| Pilot | 3,159,000 | 3,091,500 |
| Memo | 5,000 | 5,000 |
| Session A | 20,250,000 | 18,684,500 |
| Top-up before session B | 60,000 | 60,000 |
| Session B | 20,884,500 | 18,822,000 |
| Total | 44,553,500 | 40,858,000 |

The reservations ended 446,500 lamports (33 pairs) under the cap, above the plan because the ledger keeps
those of the 181 pairs that never left and went back to their quotas (67 in session A, 114 in session B).
The cap stopped nothing.

For the smoke test, the pilot and both sessions the spend equals the payers' balance drop to the lamport
(per payer, from the chain: `data/checks/balance-drop-20261103T144313Z-live.json` and
`data/checks/balance-drop-20261104T134938Z-live.json`, written by
`python scripts/balance_drop.py data/raw/<run>`); for the top-up, the funder's drop less the 15,911,000
lamports it moved to the payers.

## 9. Synthetic recovery

`python -m analysis recover` (seed 7) writes two synthetic sessions in the exact raw format — 684 windows,
2,866 pairs (each session fires the main run's quotas, q = 0.646), landing losses, prediction error of the
window anchor (so some pairs are buffered), foreign transactions around our probes — with known clocks,
runs the whole pipeline and compares (2026-11-03, the amended design: simultaneous pairs, late part of the
grid; PREREGISTRATION §10):

| Family | Lane | True mu, ms | Estimate | 95% interval |
|---|---|---|---|---|
| AgaveBam | VIP / ECO | 20 / 20 (metronome) | 15.5 / 22.3 | [11.7, 20.2] / [13.6, 28.2] |
| HarmonicAgave | VIP / ECO | 50 / 50 (metronome) | 58.0 / 44.6 | [48.2, 73.7] / [29.5, 56.1] |
| HarmonicFiredancer | VIP / ECO | 15 / 15 (gamma k = 30) | 17.4 / 15.0 | [13.2, 20.7] / [12.5, 17.8] |
| JitoLabs | VIP / ECO | 3 / 9 (queue) | 5.3 / 10.9 | [0.9, 8.6] / [3.0, 14.8] |
| Firedancer | VIP / ECO | 10 / 25 (queue) | 13.0 / 36.1 | [3.1, 24.7] / [4.7, 46.1] |
| FireBAM | VIP / ECO | 20 / 20 (metronome) | 9.1 / 3.4 | [2.0, 35.3] / **[1.0, 19.5]** |
| Rakurai | VIP / ECO | 5 / 5 (queue) | 10.9 / 4.7 | [2.7, 15.3] / [0.5, 12.4] |
| Agave | VIP / ECO | 2 / 4 (queue) | 0.8 / 6.4 | [0.4, 8.9] / [1.1, 9.4] |

15 of 16 intervals cover the truth (one miss, FireBAM ECO, a small family; 0.8 expected at 95%). Eight of
the nine confirmatory verdicts come out as built in: V1, V2 kept, V3 rejected (15 vs 50 ms), E1 rejected,
L2, L3 kept, L4 and L5 rejected. **L1 is a false positive**: AgaveBam is built with one clock for both
lanes, and the lane test rejects at Holm-adjusted p = 0.04, so `recover` prints RECOVERY FAILED. We report
this realization rather than pick another seed. The late part of the grid is not the cause: with the same
20 ms clock in both lanes the lane test rejected 1 of 100 null replicates at alpha 0.0056 with the late part
and 1 of 100 without it (`scripts/amendment/latecal.py`). A single realization of nine verdicts can fail
by chance; before the amendment, with fewer pairs, the same seed got all nine right and missed one interval.

The amended read-outs on the same data: simultaneous pairs B first in 186 of 194 (the rest are lapses); a
late tail only where the truth has one (Firedancer ECO, a 25 ms queue: 5 of 25); heterogeneity one of ten
tests below 0.05 (AgaveBam ECO, p = 0.028) although every family's validators share one clock — after Holm
p = 0.28, which is why only the Holm-adjusted p may say "the validators differ"; V1–V3 inside one slot
(n = 73, 50, 78) agree with the full tests. Placebos: lexicographic rule 50.2% (n = 2,238); s shuffled
within a cell — a false rule in 1 of 30 shuffles; lanes shuffled within windows — no lane-test p below 0.05
in 15 shuffles (the p-values lean high, KS p = 0.015). Buffered pairs written more than 100 ms before the
window's first shred: B ahead in 95% (n = 105); in the boundary zone between that and the first shred, 36%
(n = 129) — which is why that zone stays out of both. (The synthetic RPC node sees a slot 100 ms after it
starts, a longer delay than the pilot measured, so the strict start excludes more here than on mainnet.)

## Appendix: the psychophysics dictionary

| Here | In psychophysics |
|---|---|
| the validator ordering a pair | an observer in a temporal-order judgement |
| s, B sent after A | stimulus onset asynchrony |
| P(B ahead \| s) | the psychometric function |
| s50 | the point of subjective simultaneity |
| eps1, eps2 | lapse rates |
| the shutter mu | the temporal integration window |
