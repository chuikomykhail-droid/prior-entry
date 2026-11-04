# Report

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
| 2026-11-04 15:02–15:27 | Builder ticks read from the 708 session B blocks that hold a probe: BAM as in session A, no Harmonic tick in any block (§3) | `data/raw/20261104T134938Z-live/ticks.jsonl`, `data/checks/ticks-20261104T134938Z-live.json` |
| 2026-11-04 16:05 | The tick signers read from the chain: Harmonic's newest transaction is from 3 November 18:20:21, and its wallet cannot pay another tick (§3) | `data/checks/tick-signers-20261104T160507Z.json` |
| 2026-11-04 16:04–17:13 | Every block with a probe re-read from mainnet, before any outcome was read: 5,558 probes in 1,414 blocks, position, producer, fee and success all agree | `data/checks/verify-20261104.txt` |
| 2026-11-04 17:10–17:52 | Main analysis, once, on both sessions; its output stayed unread until the re-read above had passed | `data/derived/`, `figures/` |
| 2026-11-04 17:53–18:10 | Read-outs of §3 and the sigma check of §2 | `data/checks/tick-readouts.json`, `data/checks/sigma-1ms.json` |

Alpenglow activated on 21.10.2026 (epoch 1064); every measurement above is after it.

## 2. Confirmatory results

3,050 pairs, 2,739 complete, 1,905 in the clock fits. All tables, per validator too: `data/derived/results.md`.

| Test | Family | Statistic | p | p (Holm) | Verdict |
|---|---|---|---:|---:|---|
| V1 | AgaveBam | mû 8.04 vs 20 ms | 0.43 | 1 | kept, with a tail |
| V2 | HarmonicAgave | mû 35.7 vs 50 ms | 4.1e-05 | 0.00037 | **rejected** |
| V3 | HarmonicFiredancer | mû 24.3 vs 50 ms | 0.012 | 0.099 | kept |
| E1 | HarmonicAgave vs HarmonicFiredancer | ratio 0.886 | 0.74 | 1 | kept |
| L1 | AgaveBam | mu_ECO / mu_VIP 1.01 | 0.49 | 1 | kept |
| L2 | HarmonicAgave | 0.905 | 0.82 | 1 | kept |
| L3 | HarmonicFiredancer | 0.867 | 0.76 | 1 | kept |
| L4 | JitoLabs | 18.3 | 0.40 | 1 | kept |
| L5 | Firedancer | 0.94 | 0.89 | 1 | kept |

Read by the rules of PREREGISTRATION §5:

- **V2:** the published 50 ms is not what we measure. Profile interval 21.6–40.4 ms, no late overtakes (0 of
  32). The cell is marked † (below), so it is read per validator: `Fd7btgyS` 24.6 [19.5–32.2] ms.
- **V1:** the round matches 20 ms, but 46% [35–56] of the transactions sent at least 30 ms later still
  overtake (37 of 81). The interval, 1.56–36.6 ms, is this wide because the curve levels off near 44%.
- **V3:** kept without a tail, so "consistent with 50 ms batches" by the rule, and Holm is what keeps it: on
  its own the claim lies outside the interval (7.84–42.3 ms, p = 0.012). The frozen grid left this family only
  24 FEE pairs between 25 and 75 ms, because the pilot's estimate was low. We do not claim a rejection.
- **L1–L5:** no lane effect in any family. The bootstrap of mu_ECO / mu_VIP says how much that means:
  HarmonicAgave 0.78–1.15, HarmonicFiredancer 0.43–1.15, AgaveBam 0.46–3.05, Firedancer 0.60–3.33, JitoLabs
  0.02–248. Only Harmonic is pinned down as a pure clock; JitoLabs' predicted queue is neither confirmed nor
  excluded.

Read-outs that go with the tests (shutter in ms, 95% profile interval; late overtakes in the VIP lane):

| Client | VIP lane | Typical lane | Late overtakes | B first at s = 0, VIP / ECO |
|---|---|---|---|---|
| AgaveBam | 8.04 [1.56–36.6] | 8.72 [2.85–43] | 46% [35–56] (81) | 13/13, 20/20 |
| FireBAM | 5.81 [1.11–71.4] | 36.1 [4.66–144] | 50% [31–69] (24) | 8/8, 2/2 |
| HarmonicAgave | 35.7 [21.6–40.4] † | 32.3 [27.6–38.7] | 0% [0–11] (32) | 15/15, 15/15 |
| HarmonicFiredancer | 24.3 [7.84–42.3] | 27.4 [9.77–38.8] | 0% [0–12] (28) | 28/28, 16/16 |
| Firedancer | 2.32 [0.68–12.9] † | 2.72 [0.76–10.5] † | 0% [0–28] (10) | 20/22, 16/23 |
| JitoLabs | <0.1 [<0.1–3.62] | 15 [<0.1–238] † | 29% [19–40] (70) | 10/14, 11/18 |
| Rakurai | 6.65 [0.75–22.4] | 32.1 [<0.1–67.4] | 27% [10–57] (11) | 7/10, 8/8 |
| Agave | 0.89 [<0.1–24.2] | <0.1 [<0.1–121] | 44% [19–73] (9) | 10/12, 2/2 |

- **The validators of one client differ.** Firedancer: `9eGrDohd` 21.5 (VIP) and 32.5 ms (ECO), `JD549Hsb` below
  what we can measure in both (Holm p = 3.1e-05 and 3.8e-14), on the same version. `JD549Hsb` let B overtake in
  1 of 140 FEE pairs at s > 0, and put B first in only 10 of 19 at s = 0: it does not sort what arrives together.
  JitoLabs ECO: `E1r4Psq8` 95.8, `HEL1USMZ` 10.5 ms (Holm p = 0.023). HarmonicAgave VIP (`EkvdKhUL` 41, `Fd7btgyS`
  24.6 ms) is marked † at p = 0.014 and not claimed (Holm p = 0.069).
- **The key.** Pairs X and Y sent 0.3 ms apart, where reward/cost says X and CU price and total fee say Y: X
  first in 17/17 and 20/20 (Harmonic), 20/20 (Firedancer), 18/19 and 9/9 (BAM), against 13/19 (JitoLabs), 11/14
  (Rakurai), 8/13 (Agave). FEE pairs at s ≤ 1 ms, where every key says B: 49/49, 54/54, 50/50, 19/19 on the same
  clients except Firedancer 55/74, against 29/45, 19/25, 14/16. Where the sort is sharp, the key is reward/cost.

Robustness, none of it changes a verdict: window-cluster bootstrap of mu_VIP, AgaveBam 3.5–40.0, HarmonicAgave
23.0–39.8, HarmonicFiredancer 8.5–40.6 ms. Inside one slot: V1 6.91 vs 20 (n = 60, p = 0.48), V2 36.8 vs 50 (n =
84, p = 0.012), V3 10.7 vs 50 (n = 102, p = 0.022). Sigma = 1 ms instead of 0.3: V1 7.15 (p = 0.43), V2 35.6
(p = 4.0e-05), V3 24.5 (p = 0.013) (`data/checks/sigma-1ms.json`, §5). Buffered boundary 50 ms earlier / later:
HarmonicAgave VIP 36.7 / 35.9, HarmonicFiredancer VIP 24.1 / 21.6, AgaveBam VIP 15.2 / 16.8 ms. Shape: metronome by
AIC for HarmonicAgave in both lanes and HarmonicFiredancer ECO (k at its ceiling), exponential by a margin under 3
for HarmonicFiredancer VIP and AgaveBam.

Controls and placebos: REV pairs, B first and dearer, B ahead in 230 of 237. Lexicographic order of signatures:
49.5% [47.6–51.3] (n = 2,739). s shuffled within Firedancer VIP: a false rule in 1 of 100. Lanes shuffled within
windows on Firedancer: p below 0.05 in 7 of 50 shuffles (KS p = 1e-06). So the lane test is not calibrated on a
family whose validators differ; L5 is not rejected anyway.

## 3. Exploratory results

No confirmatory claims here. From the list of PREREGISTRATION §7:

- **Sessions** (`data/derived/sessions.json`, A / B): HarmonicAgave VIP 31.8 / 37.3 and ECO 28.2 / 36.8,
  HarmonicFiredancer ECO 29.3 / 26.0, Firedancer ECO 2.7 / 3.2 ms. Where k is loose or the curve has a floor,
  a fit per session says little: HarmonicFiredancer VIP 11.3 / 40.5, AgaveBam VIP 58.8 / 13.5, JitoLabs ECO 197 /
  34.7 ms; the counts below are the better read.
- **Phase in the slot:** only HarmonicAgave ECO has enough pairs for both fits, 33.5 ms in the first 30 ms of the
  slot (n = 42) and 31.8 ms later (n = 120).
- **Convexity:** rejected in no cell (p 0.13–0.92).
- **Rank in the block**, A / B: VIP 97–98 / 99, ECO 50–57 / 60–69.
- **Foreign transactions between A and B**, median: Harmonic 6–60, Firedancer 10–22, BAM 3–6, Rakurai 0–1, JitoLabs
  and Agave 0.
- **Buffered pairs** written over 100 ms before the window's first shred: B ahead in 141 of 192 (73%); in the boundary
  zone, 48% (n = 192). Both stay out of the fits.
- **Ms per key:** s50 and s10 per client are in `data/derived/results.md`. s10 exists only for Harmonic (VIP / ECO:
  HarmonicAgave 32.2 / 29.1, HarmonicFiredancer 45.5 / 24.7 ms) and Firedancer ECO (31.7 ms); elsewhere the tail
  keeps P(B ahead) above 10% at any gap.

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

### Harmonic's ticks stopped between the sessions

In the 708 blocks of session B that hold a probe, BAM ticks as before (AgaveBam 103 of 103 blocks, FireBAM 26
of 26, 9 per block, median gap 20.0 ms), and no Harmonic block has a tick: 0 of 151 (HarmonicAgave), 0 of 143
(HarmonicFiredancer). The signer's newest transaction on chain is a tick in slot 464,997,261, on 3 November at
18:20:21 UTC, three hours after session A ended. It left `Harmonic8So…` with 653,484 lamports: 3,244 above the
rent-exempt minimum of 650,240, and a tick costs 5,000. Nothing has touched the account since (read on 4
November, `data/checks/tick-signers-20261104T160507Z.json`).

The numbers fit a fee wallet that ran dry, to the lamport. That is our inference: Harmonic's public pages say
nothing about ticks or a change (read on 4 November), and the chain cannot tell whether the rounds went on
without their marker. So session A has the marker and session B does not, on the same validators, which we
did not plan; and in session B only gossip says which validators are Harmonic's.

Fixed on 4 November, before any outcome is read:

- The confirmatory tests stay as frozen, over both sessions. If Harmonic's order changed at that moment, V2,
  V3, E1, L2 and L3 pool two regimes, and the read-out below will show it.
- The round test above runs on session A only for Harmonic, and on both sessions for BAM.
- Exploratory read-out, did the order move when the marker went? For `Fd7btgyS` and `EvnRmnMr` (same
  validators, same client version in both sessions), per lane: the share of B ahead at s = 0 and in (0, 20],
  (20, 60] and (60, 200] ms, session A against session B, Wilson 95%. The same for `5Cchr1XG` and `9rkJMARq`
  (AgaveBam, ticks and version unchanged) as a control for the link and the day. No confirmatory claim.

### What those read-outs found

Both written in `scripts/tick_readouts.py` before any outcome was read (`data/checks/tick-readouts.json`).

**The round test.** Complete FEE and REV pairs in blocks with ticks, share with B ahead:

| Family, lane | Between the same two ticks | Across ticks |
|---|---|---|
| AgaveBam VIP | 98.2% [94–100] (114) | 18.3% [12–27] (93) |
| AgaveBam ECO | 100% [97–100] (138) | 7.4% [3–16] (68) |
| FireBAM VIP | 97.9% [89–100] (47) | 22.7% [10–43] (22) |
| FireBAM ECO | 100% [92–100] (46) | 0% [0–15] (21) |
| HarmonicAgave VIP, session A | 76.4% [64–86] (55) | 3.8% [1–13] (53) |
| HarmonicAgave ECO, session A | 85.5% [74–92] (55) | 5.5% [2–15] (55) |
| HarmonicFiredancer VIP, session A | 85.5% [75–92] (69) | 9.8% [4–23] (41) |
| HarmonicFiredancer ECO, session A | 86.1% [71–94] (36) | 0% [0–5] (77) |

A BAM tick round is a fee-sorted batch: inside it the dearer transaction goes first, nearly always, in both lanes.
A Harmonic tick round is not: inside its 50 ms, A stays ahead in 14–24% of the pairs.

**Did the order move when the marker went?** No sign of it. `Fd7btgyS` VIP, session A / B: (0, 20] ms 58% (19) /
69% (16), (20, 60] ms 0 of 21 / 0 of 17, (60, 200] ms 0 of 11 / 0 of 11. `EvnRmnMr` VIP: s = 0 8 of 8 / 17 of 17, (0,
20] ms 68% (40) / 76% (51), (60, 200] ms 0 of 13 / 0 of 12. The ECO lanes and the BAM control agree, and every
interval overlaps. These cells are small and can only exclude a large change, but what the chain shows fits: the
marker's wallet ran dry and the clock went on.

### Added after the outcomes were read

These three look into the results above; we chose them knowing the results (`data/checks/tick-readouts.json`).

**Harmonic: where the sort ends.** FEE clock pairs by gap, both Harmonic families, B ahead / pairs (session A and B):

| s, ms | ≤ 5 | 5–10 | 10–15 | 15–20 | 20–25 | 25–30 | 30–35 | 35–40 | 40–50 | 50–75 | > 75 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B ahead | 59/68 | 49/63 | 30/57 | 23/46 | 11/32 | 4/16 | 1/21 | 0/21 | 0/50 | 0/30 | 0/190 |

No model is needed here. Between 26 and 50 ms a 50 ms metronome expects 21.8 overtakes in these 102 pairs; there
are 4 (P = 2e-07), and none at all beyond 33.3 ms in 298 pairs. `Fd7btgyS`, the largest, has 34 of 35 at s ≤ 10
ms and nothing beyond 24.9 ms: 0 of 55 between 25 and 50 ms, where that metronome expects 12.4. Meanwhile, in session
A, the same validators' ticks were 50.0 ms apart. So the tick period and the time over which fees decide are not
the same thing: inside one tick round, B ahead falls from 87% at s ≤ 10 ms and 80% at 10–20 ms to 5 of 10 at 20–30
ms and 0 of 10 beyond 30 ms. Harmonic's validators page lists "50ms buffers, double-buffered"
([harmonic.gg/validators](https://harmonic.gg/validators), read on 4 November); two buffers offset by half a period
would give about this, but that is our guess, and the data cannot show the mechanism.

**BAM: what enters a round is not decided by the send order.** The share of in-window FEE pairs that land between
the same two ticks is 91% at s = 0, 78% at 0–10 ms, 53% at 20–30 ms, and then stops falling (36% at 50–75 ms, 40%
at 75–200 ms), and B ahead inside one round is 96–100% at every gap. A 20 ms round cannot hold writes 100 ms apart
unless they wait upstream, and they do. Builder's clock at the next tick minus our write, in true time:

| Probes before a tick of their block | p1 | p10 | median | p90 | p99 | Negative |
|---|---:|---:|---:|---:|---:|---:|
| BAM (698) | 36.8 | 55.6 | 119.6 | 368.6 | 515.3 | 0 |
| Harmonic, session A (566) | 33.6 | 45.0 | 73.9 | 99.7 | 116.4 | 0 |

A BAM probe typically waits several rounds, and one in ten over a third of a second. That, rather than a wrong
period, is the likely source of the late overtakes: the ticks are 20.0 ms apart and the sort inside them is nearly
exact, but a send gap of 100 ms is small next to the wait. We cannot see from outside where the wait is (validator, BAM node, or how they treat
unstaked connections), and a staked sender may see something else.

**The largest gap at which B overtook** (FEE clock pairs): `Fd7btgyS` 24.9, `EvnRmnMr` 25.0, `EkvdKhUL` 26.2, `Awes4Tr6`
33.3, `9eGrDohd` 32.1 ms; `5Cchr1XG` 127.1, `9rkJMARq` 142.4 ms.

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

One file under `analysis/` has changed since the Memo's commit: `verify.py`, with its test, now waits out lost
connections and server errors, after a two-minute connection timeout killed a check. It is not part of
`reproduce` and changes no result; `git diff 399eedd..HEAD -- analysis itb design` shows all of it.

One pre-registered robustness check is missing from `reproduce`: sigma = 1 ms (§5). We noticed when reading the
results and computed it with a separate script (`scripts/robust_sigma.py`); it changes no verdict.

## 6. What the design does not separate

See README, "What this design does not separate".

## 7. Verification and reproduction

- `docker compose up` recomputes `data/derived` from `data/raw` with no network and compares byte for byte.
  GitHub Actions builds the image and runs the tests on every push (`.github/workflows/docker.yml`); the
  full recomputation takes hours on a runner, so it runs on request. Run on 4 November on the measurement PC
  (Windows, the image's Python and library versions, `python -m analysis check`): all 18 files identical, 43
  minutes (`data/checks/check-20261104.txt`). We have not yet run it inside the Linux image, where the last
  digits of a fit may differ.
- `docker compose --profile verify up` re-reads every block with a probe from mainnet and compares
  position, producer, fee and success (an implementation independent of the Rust collector). Run on 4
  November over both sessions: 5,558 probes in 1,414 blocks, 0 differ (`data/checks/verify-20261104.txt`).
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
