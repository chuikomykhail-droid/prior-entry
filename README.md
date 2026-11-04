# Shutter speed
[![docker](https://github.com/chuikomykhail-droid/prior-entry/actions/workflows/docker.yml/badge.svg)](https://github.com/chuikomykhail-droid/prior-entry/actions/workflows/docker.yml)
### Solana leaders sort by fee — but only what they see at once. How long is "at once"?

**A tiny test transaction outranks 98 % of mainnet by the scheduler's own key** — even with no priority
fee it beats 96 % (`docker compose --profile survey up`, [summary](data/survey/20261102T124027Z-market-rank/summary.md)).
Measurements built from tiny probes describe the VIP lane. We measured the VIP lane and the lane a
typical transaction rides in.

**The rule has two halves.** The key — reward ÷ cost — is the documented half: what a leader holds at
once, it sorts by it. The undocumented half is time: transactions closer than a client's *shutter speed* are
sorted by fee; farther apart, by arrival. We fired 2,866 pairs of transactions at 15 validators of 8 clients, in
two pre-registered sessions on mainnet, measured each shutter and checked it against what BAM (20 ms) and
Harmonic (50 ms) publish:

- **Harmonic's shutter is 25–36 ms, not 50.** The claim is rejected for HarmonicAgave (35.7 ms [21.6–40.4], Holm
  p = 0.0004). Between 26 and 50 ms a 50 ms clock expects 22 overtakes in our 102 pairs; there are 4, and none
  past 33 ms. Its ticks on chain really are 50.0 ms apart: the period is real, but fees decide over a shorter time.
- **BAM's rounds are real and sorted almost perfectly, but they do not decide who is first.** Inside one 20 ms round
  the dearer transaction goes first in 98–100% of pairs. Yet 46% of transactions sent 30 ms or more later still
  overtake, because a probe waits a median of 120 ms (one in ten over 369 ms) before the round that takes it.
- **The validator sets the shutter, not the client.** On the same Firedancer version, `9eGrDohd` sorts over 20–30
  ms, and `JD549Hsb` is first come, first served: 1 overtake in 140 pairs, and 10 of 19 even at s = 0.
- **The lane does not matter.** We found no lane effect in any client: a typical transaction gets the VIP's
  shutter. This is tight only for Harmonic.

![Shutter speed by client and lane](figures/fig1-shutter-light.svg#gh-light-mode-only)
![Shutter speed by client and lane](figures/fig1-shutter-dark.svg#gh-dark-mode-only)

| Client | Stake | Shutter, VIP lane, ms [95%] | Shutter, typical lane, ms [95%] | Vendor says | Matches? | Late overtakes, VIP | Clock or queue |
|---|---|---|---|---|---|---|---|
| AgaveBam | 35.7 % | 8.04 [1.56–36.6] | 8.72 [2.85–43] | 20 ms | round yes, late overtakes | 46% [35–56] (81) | lanes equal |
| JitoLabs | 24.0 % | <0.1 [<0.1–3.62] | 15 [<0.1–238] † | — | — | 29% [19–40] (70) | queue not confirmed |
| HarmonicAgave | 21.0 % | 35.7 [21.6–40.4] † | 32.3 [27.6–38.7] | 50 ms | **no** | 0% [0–11] (32) | clock, lanes equal |
| HarmonicFiredancer | 9.0 % | 24.3 [7.84–42.3] | 27.4 [9.77–38.8] | 50 ms | kept ‡ | 0% [0–12] (28) | clock, lanes equal |
| Firedancer | 5.4 % | 2.32 [0.68–12.9] † | 2.72 [0.76–10.5] † | — | — | 0% [0–28] (10) | lanes equal |
| FireBAM | 1.9 % | 5.81 [1.11–71.4] | 36.1 [4.66–144] | 20 ms | (descriptive) | 50% [31–69] (24) | (descriptive) |
| Rakurai | 1.2 % | 6.65 [0.75–22.4] | 32.1 [<0.1–67.4] | — | — | 27% [10–57] (11) | (descriptive) |
| Agave | 1.0 % | 0.89 [<0.1–24.2] | <0.1 [<0.1–121] | — | — | 44% [19–73] (9) | (descriptive) |

*Shutter speed* mu: the mean interval between the moments the client (with its block-building partner)
takes a batch of waiting transactions. *Late overtakes*: share of pairs where B still lands ahead although
sent at least 1.5 published periods after A (40 ms for clients without one) — a clock with the published
period cannot do that. Stake: gossip and vote accounts, 1.11.2026. † One mu for all validators of this client
is rejected at p < 0.05, so read the table per validator. ‡ V3 is kept after Holm (p = 0.099), though on its own
the 50 ms lies outside the interval (p = 0.012); its grid has few pairs between 25 and 75 ms.

**Per validator.** B ahead / pairs at s = 0, in three bands of s and among the late overtakes, and the shutter from
60 clock pairs on.

<details><summary>The table for all 15 validators</summary>

| Client | Validator | Lane | s = 0 | 0–20 ms | 20–60 ms | 60–200 ms | Late overtakes | Shutter, ms [95%] |
|---|---|---|---|---|---|---|---|---|
| AgaveBam | `5Cchr1XG` | VIP | 3/3 | 12/15 | 8/19 | 9/24 | 16/40 | 27.1 [1.37–73.2] |
| AgaveBam | `5Cchr1XG` | ECO | 9/9 | 18/22 | 13/31 | 2/5 | 7/17 | 27.8 [3.04–73.4] |
| AgaveBam | `9rkJMARq` | VIP | 10/10 | 10/15 | 10/18 | 13/28 | 21/41 | 12.2 [0.242–264] |
| AgaveBam | `9rkJMARq` | ECO | 11/11 | 21/31 | 10/20 | 4/9 | 6/16 | 6.2 [1.01–114] |
| FireBAM | `9jxgosAf` | VIP | 8/8 | 13/17 | 7/17 | 8/12 | 12/24 | — |
| FireBAM | `9jxgosAf` | ECO | 2/2 | 16/19 | 7/11 | 5/18 | 8/24 | — |
| HarmonicAgave | `Awes4Tr6` (session B) | VIP | 2/2 | 4/6 | 3/10 | 0/3 | 0/3 | — |
| HarmonicAgave | `Awes4Tr6` (session B) | ECO | 5/5 | 1/2 | 2/5 | 0/2 | 0/2 | — |
| HarmonicAgave | `EkvdKhUL` | VIP | 4/4 | 6/9 | 4/19 | 0/9 | 0/8 | — |
| HarmonicAgave | `EkvdKhUL` | ECO | 4/4 | 9/15 | 1/13 | 0/6 | 0/6 | — |
| HarmonicAgave | `Fd7btgyS` | VIP | 9/9 | 22/35 | 0/38 | 0/22 | 0/21 | 24.6 [19.5–32.2] |
| HarmonicAgave | `Fd7btgyS` | ECO | 6/6 | 29/37 | 2/48 | 0/13 | 0/11 | 30.8 [24.6–39] |
| HarmonicFiredancer | `Awes4Tr6` (session A) | VIP | 3/3 | 9/18 | — | 0/5 | 0/5 | — |
| HarmonicFiredancer | `Awes4Tr6` (session A) | ECO | 1/1 | 3/5 | 0/4 | 0/13 | 0/8 | — |
| HarmonicFiredancer | `EvnRmnMr` | VIP | 25/25 | 66/91 | 4/11 | 0/25 | 0/23 | 32.4 [9.38–48.7] |
| HarmonicFiredancer | `EvnRmnMr` | ECO | 15/15 | 12/16 | 0/17 | 0/64 | 0/46 | 27.3 [12.9–40.3] |
| Agave | `5Us18hLZ` | VIP | 2/3 | 2/6 | 1/4 | 1/1 | 2/2 | — |
| Agave | `5Us18hLZ` | ECO | 1/1 | 4/8 | 0/2 | 0/5 | 0/2 | — |
| Agave | `7QQGNm3p` | VIP | 8/9 | 3/10 | 6/17 | 0/2 | 2/7 | — |
| Agave | `7QQGNm3p` | ECO | 1/1 | 3/14 | 6/10 | 4/6 | 4/8 | — |
| Firedancer | `9eGrDohd` | VIP | 16/16 | 29/44 | 11/37 | 0/2 | 0/2 | 21.4 [4.18–44.8] |
| Firedancer | `9eGrDohd` | ECO | 10/10 | 55/69 | 1/7 | 0/9 | 0/10 | 32.5 [16.3–49] |
| Firedancer | `JD549Hsb` | VIP | 4/6 | 0/30 | 0/40 | 0/5 | 0/8 | <0.1 [<0.1–2.42] |
| Firedancer | `JD549Hsb` | ECO | 6/13 | 0/60 | 0/3 | 1/2 | 1/2 | <0.1 [<0.1–0.955] |
| JitoLabs | `E1r4Psq8` | VIP | 2/3 | 7/23 | 7/23 | 9/24 | 10/30 | 2.19 [<0.1–4.93] |
| JitoLabs | `E1r4Psq8` | ECO | 8/11 | 5/11 | 12/19 | 2/16 | 4/19 | 95.8 [13.7–334] |
| JitoLabs | `HEL1USMZ` | VIP | 8/11 | 5/22 | 5/31 | 7/30 | 10/40 | 0.465 [<0.1–5.43] |
| JitoLabs | `HEL1USMZ` | ECO | 3/7 | 6/16 | 3/17 | 9/30 | 5/20 | 10.5 [0.141–38.8] |
| Rakurai | `E3mDbFMr` | VIP | 1/2 | 4/7 | 1/7 | 0/1 | 1/4 | — |
| Rakurai | `E3mDbFMr` | ECO | 3/3 | 1/2 | 1/3 | 3/5 | 2/4 | — |
| Rakurai | `ana2y2Yv` | VIP | 6/8 | 5/15 | 3/8 | 3/8 | 2/7 | — |
| Rakurai | `ana2y2Yv` | ECO | 5/5 | 8/12 | 5/12 | 2/7 | 2/8 | — |

</details>

**Ms per key.** Arrive at least s₁₀ earlier and in 9 cases of 10 you are ahead even of a transaction with
a 1.8× larger key. ∞: no such gap, because the tail keeps B ahead in over 10% of the pairs however late it is sent.

| Client | VIP lane, s₁₀ | Typical lane, s₁₀ |
|---|---|---|
| HarmonicAgave | 32.2 ms | 29.1 ms |
| HarmonicFiredancer | 45.5 ms | 24.7 ms |
| Firedancer | ∞ | 31.7 ms |
| AgaveBam, FireBAM, JitoLabs, Rakurai, Agave | ∞ | ∞ |

Reproduce everything from the raw data with one command (no keys, no network for the recomputation; about 45
minutes on 12 cores):

```bash
docker compose up
```

What the bounty asked for and where it is answered: [the checklist](#what-the-bounty-asks-and-where-it-is-answered).

---

## Act 1. The key — the documented half

Two controls tell the candidate keys apart. In **C2**, X (32 KiB data limit, 500 lamports of priority fee) and Y (64
MiB, 3,000 lamports) go out about 300 ms before the window, 0.3 ms apart, in random order. In **FEE at s ≤ 1 ms**, B
beats A on every key.

| Key | C2: who goes first | FEE at s ≤ 1 ms |
|---|---|---|
| reward / cost | X | B |
| cost alone | X | tie |
| CU price | Y | B |
| total fee | Y | B |

| Client | C2: X first | FEE at s ≤ 1 ms: B first |
|---|---:|---:|
| HarmonicAgave | 17/17 | 49/49 |
| HarmonicFiredancer | 20/20 | 54/54 |
| AgaveBam | 18/19 | 50/50 |
| FireBAM | 9/9 | 19/19 |
| Firedancer | 20/20 | 55/74 |
| Rakurai | 11/14 | 19/25 |
| JitoLabs | 13/19 | 29/45 |
| Agave | 8/13 | 14/16 |

Where the sort is sharp, only reward / cost fits. Firedancer's 55/74 is its two validators averaged: `JD549Hsb`
does not sort what arrives together. JitoLabs, Rakurai and Agave sort only part of the time, even at 0.3 ms.

## Act 2. One validator, two verdicts

![One validator, two verdicts](figures/fig3-two-verdicts-light.svg#gh-light-mode-only)
![One validator, two verdicts](figures/fig3-two-verdicts-dark.svg#gh-dark-mode-only)

`EvnRmnMr` put B first in 25 of 25 pairs sent together: "by fee". At about 50 ms it kept A first in all 16: "by
arrival". Both pictures are right. The rule is the curve between them.

## Act 3. The shutter

![Share of pairs with B ahead as a function of s](figures/fig2-curves-light.svg#gh-light-mode-only)
![Share of pairs with B ahead as a function of s](figures/fig2-curves-dark.svg#gh-dark-mode-only)

| Test | Client | Measured vs published | p (Holm) | Verdict |
|---|---|---|---:|---|
| V1 | AgaveBam | 8.04 vs 20 ms | 1 | kept, with a tail: 46% of late pairs still overtake |
| V2 | HarmonicAgave | 35.7 vs 50 ms | 0.00037 | **rejected** |
| V3 | HarmonicFiredancer | 24.3 vs 50 ms | 0.099 | kept, no tail |

**Harmonic looks like a clean clock running faster than published.** In three of its four cells the regularity k sits
at its ceiling (a metronome), and no cell needs a lapse rate. Counting FEE pairs needs no model at all:

| s, ms | ≤ 5 | 5–10 | 10–15 | 15–20 | 20–25 | 25–30 | 30–35 | 35–40 | 40–50 | 50–75 | > 75 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B ahead | 59/68 | 49/63 | 30/57 | 23/46 | 11/32 | 4/16 | 1/21 | 0/21 | 0/50 | 0/30 | 0/190 |

On `Fd7btgyS`, the largest, nothing overtakes past 24.9 ms: 0 of 55 between 25 and 50 ms, where a 50 ms clock expects 12.

**BAM's round is exact; what enters it is not.** BAM and Harmonic write a tick transaction into their blocks with the
builder's clock in it (`docs/DATA.md`). So we can ask directly: did A and B land between the same two ticks?

| | B ahead, same tick round | B ahead, across ticks | Ticks apart (median) |
|---|---:|---:|---:|
| AgaveBam VIP / ECO | 98% (114) / 100% (138) | 18% (93) / 7% (68) | 20.0 ms |
| FireBAM VIP / ECO | 98% (47) / 100% (46) | 23% (22) / 0% (21) | 20.0 ms |
| HarmonicAgave VIP / ECO, session A | 76% (55) / 85% (55) | 4% (53) / 5% (55) | 50.0 ms |
| HarmonicFiredancer VIP / ECO, session A | 86% (69) / 86% (36) | 10% (41) / 0% (77) | 50.0 ms |

A BAM round is a fee-sorted batch, nearly without exception. But 40% of pairs land in one round even when sent 75–200
ms apart: they wait upstream for longer than the gap. From our write to the next tick, in the builder's clock, a BAM probe
takes a median of 120 ms, p90 369, p99 515; a Harmonic probe 74, 100, 116. In a wait that long, send order means little.
A Harmonic tick round is not one sorted batch: inside it, B's lead fades from 87% at s ≤ 10 ms to 0 of 10 beyond 30 ms.
Its [validators page](https://harmonic.gg/validators) lists "50ms buffers, double-buffered"; two buffers offset by half a
period would look like this, but that is our guess.

**A marker that stopped in the middle.** Harmonic's ticks ended on all its validators on 3 November at 18:20:21 UTC,
between our sessions. The signer was left 3,244 lamports above the rent-exempt minimum, and a tick costs 5,000: it looks
like a fee wallet that ran dry. Harmonic's order did not move. On the same validators and versions, session A with
ticks and session B without them give the same counts within their intervals, and we fixed that comparison before
reading any outcome ([REPORT §3](REPORT.md#3-exploratory-results)).

## Twist: the VIP lane

![The VIP lane: a tiny probe outranks almost everything](figures/fig4-vip-lane-light.svg#gh-light-mode-only)
![The VIP lane: a tiny probe outranks almost everything](figures/fig4-vip-lane-dark.svg#gh-dark-mode-only)

A queue would make a lower rank wait for a later round. None of the five lane tests L1–L5 finds it (all p (Holm) = 1). For Harmonic that is a measurement: mu_ECO / mu_VIP is 0.78–1.15 on HarmonicAgave, a pure clock that does not
care about the market. For JitoLabs the ratio is 0.02–248, so the predicted queue is neither confirmed nor excluded.

---

## How it works

**A pair.** Two of our transactions, A (cheap) and B (dear on every key: reward/cost ×1.83, CU price ×6,
total fee ×1.45), paid by the same payer, so they write-lock the same account and the leader must put one
before the other. B is written to the leader's TPU over QUIC **s ms after A**, on the same connection.
Outcome: is B ahead of A in the block?

**The model.** If the client takes batches at the moments of a renewal process with mean interval mu,
B overtakes A exactly when no batch boundary falls between their arrivals:
G(s) = (1/mu) ∫ₛ^∞ S(u) du. With gamma intervals (shape k) this spans the "on demand" exponential (k = 1)
and the metronome (k → ∞). Lapses eps1 (floor) and eps2 (ceiling) absorb noise. In the language of
psychophysics this is a temporal-order judgement with the validator as the observer (REPORT, appendix).

**Two lanes.** The lane changes only the requested CU limit — 600 (key at ~98th percentile) or 200,000
(the wallet default; ~50th–67th percentile) — never the lamports. A pure clock gives the same curve in
both lanes; a queue shifts the typical lane's curve to the right.

**Random phase.** A fires at a uniformly random moment in [+120, +650 − s] ms of the leader's window,
so the batch boundaries are crossed at random phase, as the renewal model needs. The phase in the slot is
recorded for every pair.

**Read without the model.** One FEE pair in ten goes at s = 0: whether a validator sorts transactions
that arrive together is counted for each validator directly. For BAM and Harmonic, 15% of the pairs go
1.5 published periods or more late: a clock with the published period cannot let B overtake there, so
any overtaking is counted, not absorbed into a lapse rate.

**Pre-registered.** Hypotheses, grids, exclusions and tests are in [docs/PREREGISTRATION.md](docs/PREREGISTRATION.md),
frozen after the pilot, amended after its review (§10) and fixed before the main run with its SHA-256 in
a mainnet Memo (slot 464,933,869, tx `4YVHq5kTCkB3erDZvgBoizrRAAGFJBq3vci9pA5y65zcgpchBxRC1zMCot6Bd38h3MtmLTCRDHAMuY4gk14F7gZW`).
The analysis ran once, after both sessions. Every landed probe was re-read from the chain first (5,558 of 5,558 agree).
The simulation of the method (recovery of mu and k, power of the lane test) is [docs/POWER.md](docs/POWER.md). What
went wrong, and what differed between the sessions, is in [REPORT.md](REPORT.md#4-what-went-wrong).

## Commands

```bash
docker compose up                                  # recompute data/derived from data/raw, compare byte for byte; then a 1-minute dry-run
docker compose --profile dryrun up                 # dry-run: real schedule and windows, signed probes, simulateTransaction, QUIC handshakes; nothing is sent
docker compose --profile verify up                 # re-read every block from the chain and compare positions, producer, fees
docker compose --profile survey up                 # client and market surveys (read-only)
docker compose --profile live run --rm live --live --cap-sol 0.045 --not-after 2026-11-04T18:00:00Z
```

Without Docker: `cargo build --release` in `itb/`, `pip install -r analysis/requirements.txt`, then
`itb run` (dry-run), `python -m analysis reproduce`. The pipeline can be checked end to end on synthetic
data with known clocks: `python -m analysis recover`.

**Safety.** Dry-run is the default. Probe bytes can only reach a socket through a send permit, which exists
only with `--live`, a cap of at most 0.045 SOL, a `--not-after` deadline, mainnet by genesis hash and a slot
after Alpenglow. Every send first reserves its worst-case fee in a project-wide ledger (`data/ledger.jsonl`);
the run stops at the cap. Keys are mounted read-only from `./keys`, never part of the image or the repository.

## What the bounty asks and where it is answered

| Point | Answer |
|---|---|
| Leader schedule and types | `getSlotLeaders`; gossip snapshot per window (client id, version, ingress); attribution by the producer that actually built the block; client ids change on the fly (REPORT) |
| Transaction path | direct QUIC to the advertised TPU, no RPC on the path; BAM and Harmonic ingress is part of the path, so their clock is the clock of the whole "aggregator + validator" pair |
| Our transactions interacting | within a pair, an intended conflict (shared payer) removes the race between execution threads; between pairs, different payers assigned at random; ≤ 8 streams per 100 ms |
| Competition inside the block | an experimental factor: the lane puts the pair at a different market rank; plus each probe's rank in its own block, block load, foreign transactions between A and B |
| Send order | the controlled variable s; REV reverses the order |
| Noise vs rule | REV (ceiling), floor eps1, placebos, simulation with known clocks, window-cluster bootstrap, convexity test, pre-registration, Holm |
| Alpenglow | all measurements after 21.10.2026; checked in code before a send permit; v1 transactions parsed |
| Jito bundles and tips | not sent, not analysed |

## What this design does not separate

- **Rank and request size travel together in a lane.** ECO is both lower in rank and asks for 333× more
  CU. A lane effect may come from a queue by key, from capacity (block, round, CU pacing) or both; we say
  "lane effect", not "rank effect".
- **The queue's mechanism** (by key, carry-over to the next round, CU pacing) is not resolved.
- **Arrival at the leader is not observed**, only our write; the remainder goes into sigma and eps.
- **BAM and Harmonic**: we measure the pair "aggregator + validator"; they cannot be told apart from outside.
- **One key ratio** (1.8×); with key bucketing or ties it may matter.
- **Foreign transactions' rank** is reconstructed approximately (precompile signatures, default limits).
- **Load** is recorded, not controlled: the result is "the clock at the observed load, on the dates measured".
- **Operator configuration** (Harmonic strategy, Jito relayer, Firedancer pacing): split by validator where data allow.
- **Client or validator**: two validators per client cannot say how a client's validators vary in general;
  when its two validators differ, the client row pools them and the per-validator table is the answer.
- **Slot boundaries**: a slot boundary between A and B cuts the pair whatever the client's clock, so long
  shutters come out a little short; the vendor-claim tests are repeated on pairs inside one slot.
- **Selection by landing**: pairs that did not land (more often in the typical lane) are not in the curves.
- **Unstaked ingress**: staked (SWQoS) transactions may take another path.
- **Independent transactions**: we measure conflicting pairs; for independent ones the thread race is added.
- **Where BAM's wait is**: our write to the next tick is measured between two clocks; which part is the path, the
  validator or the BAM node cannot be told from outside.
- **Why Harmonic's sort is shorter than its tick**: the counts show it; they do not show the mechanism.
- **Between the sessions** the link (Wi-Fi, then cable), the day, the epoch and some client versions changed
  (REPORT §4). Both ran at about the same hour, so we say nothing about other hours.

## Repository

```
README.md                this page
REPORT.md                dates of every measurement, results, what went wrong, deviations
docs/PREREGISTRATION.md  hypotheses and rules, frozen before the main run
docs/POWER.md            simulation: recovery of mu and k, power of the lane test
docs/DATA.md             raw data format
docker-compose.yml       profiles: default (reproduce + short dry-run), dryrun, verify, survey, live
itb/                     Rust: windows, slot clock, probe building and signing, QUIC, spend ledger, collection
analysis/                Python: pairs, models, fits, tests, bootstrap, placebos, simulation, figures
scripts/                 surveys, builder ticks and their read-outs, balance check, sigma check
data/survey/             client and market surveys
data/raw/<run>/          every send and landing: signatures, slots, positions, block extracts, builder ticks
data/pilot/<run>/        smoke test and pilot, same format; they set the grids, not the results
data/checks/             quality of each session, balance drops, re-read from the chain, tick read-outs, link log
data/derived/            tables and fits, recomputed from data/raw
figures/                 light and dark SVG
```
