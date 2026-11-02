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
| TBD | Pilot | |
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
transactions around our probes — with known clocks, runs the whole pipeline and compares (2026-11-02):

| Family | Lane | True mu, ms | Estimate | 95% interval |
|---|---|---|---|---|
| AgaveBam | VIP / ECO | 20 / 20 (metronome) | 20.0 / 15.6 | [11.9, 27.3] / [3.6, 24.8] |
| HarmonicAgave | VIP / ECO | 50 / 50 (metronome) | 55.1 / 46.7 | [34.8, 65.1] / [32.9, 61.4] |
| HarmonicFiredancer | VIP / ECO | 15 / 15 (gamma k = 30) | 17.6 / 15.3 | [12.7, 20.4] / [6.7, 20.4] |
| JitoLabs | VIP / ECO | 3 / 9 (queue) | 1.3 / 3.3 | [0.3, 7.2] / [1.2, 17.4] |
| Firedancer | VIP / ECO | 10 / 25 (queue) | 19.7 / 33.0 | **[13.6, 24.6]** / [16.0, 65.8] |
| FireBAM, Rakurai, Agave | both | 20; 5; 2 / 4 | — | all cover |

15 of 16 intervals cover the truth (one miss, Firedancer VIP; 0.8 expected at 95%). All nine confirmatory
verdicts come out as built in: V1, V2 kept, V3 rejected (15 vs 50 ms), E1 rejected, L1–L3 kept, L4 and L5
rejected. Placebos: lexicographic rule 49.7% (n = 1,728); s shuffled within a cell — no false rule in 20
shuffles; lanes shuffled within windows — lane-test p-values uniform (KS p = 0.82). Buffered pairs: B ahead
in 95% (the ceiling eps2 is 5%).

## Appendix: the psychophysics dictionary

| Here | In psychophysics |
|---|---|
| the validator ordering a pair | an observer in a temporal-order judgement |
| s, B sent after A | stimulus onset asynchrony |
| P(B ahead \| s) | the psychometric function |
| s50 | the point of subjective simultaneity |
| eps1, eps2 | lapse rates |
| the shutter mu | the temporal integration window |
