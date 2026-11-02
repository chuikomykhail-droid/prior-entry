# Shutter speed
### Every Solana leader sorts by fee — but only what it sees at once. How long is "at once"?

**A tiny test transaction outranks 98 % of mainnet by the scheduler's own key** — even with no priority
fee it beats 96 % (`docker compose --profile survey up`, [summary](data/survey/20261102T124027Z-market-rank/summary.md)).
Measurements built from tiny probes describe the VIP lane. We measured the VIP lane and the lane a
typical transaction rides in.

**The rule has two halves.** The key — reward ÷ cost — is the documented half: every client we measured
sorts by it. The undocumented half is time: transactions closer than a client's *shutter speed* are
sorted by fee; farther apart, by arrival. We measured each client's shutter, checked it against what BAM
(20 ms) and Harmonic (50 ms) publish, and found **[FINDING — after the main run]**.

![Shutter speed by client and lane](figures/fig1-shutter-light.svg#gh-light-mode-only)
![Shutter speed by client and lane](figures/fig1-shutter-dark.svg#gh-dark-mode-only)

| Client | Stake | Shutter, VIP lane, ms [95%] | Shutter, typical lane, ms [95%] | Vendor says | Matches? | Clock or queue |
|---|---|---|---|---|---|---|
| AgaveBam | 35.7 % | | | 20 ms | | |
| JitoLabs | 24.0 % | | | — | — | |
| HarmonicAgave | 21.0 % | | | 50 ms | | |
| HarmonicFiredancer | 9.0 % | | | 50 ms | | |
| Firedancer | 5.4 % | | | — | — | |
| FireBAM | 1.9 % | | | 20 ms | | (descriptive) |
| Rakurai | 1.2 % | | | — | — | (descriptive) |
| Agave | 1.0 % | | | — | — | (descriptive) |

*Shutter speed* mu: the mean interval between the moments the client (with its block-building partner)
takes a batch of waiting transactions. Stake: gossip and vote accounts, 1.11.2026.

**Ms per key.** Arrive at least s₁₀ earlier and in 9 cases of 10 you are ahead even of a transaction with
a 1.8× larger key:

| Client | VIP lane, s₁₀ | Typical lane, s₁₀ |
|---|---|---|
| | | |

Reproduce everything from the raw data with one command (no keys, no network for the recomputation):

```bash
docker compose up
```

What the bounty asked for and where it is answered: [the checklist](#what-the-bounty-asks-and-where-it-is-answered).

---

## Act 1. The key — the documented half

[TBD after the main run: one table — C2 control (X first) and FEE pairs at s ≈ 0 (B first), per client,
against the predictions of four candidate keys.]

## Act 2. One validator, two verdicts

[TBD: Fig. 3. The same validator looks "by fee" at s ≈ 0 and "by arrival" at s = 50 ms — and in the typical
lane at 50 ms possibly "by fee" again. Both pictures are right; the rule is the curve between them.]

## Act 3. The shutter

[TBD: Fig. 2 — share of pairs with B ahead as a function of s, per client and lane, with the model; mu and
regularity k; the vendor-claim tests V1–V3.]

## Twist: the VIP lane

[TBD: Fig. 4 and the lane tests L1–L5: in the typical lane the curve is [the same / shifted] — the client
runs [a clock / a queue].]

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

**Pre-registered.** Hypotheses, grids, exclusions and tests are in [docs/PREREGISTRATION.md](docs/PREREGISTRATION.md),
frozen before the main run with its SHA-256 in a mainnet Memo (TBD). The simulation of the method
(recovery of mu and k, power of the lane test) is [docs/POWER.md](docs/POWER.md).

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
- **Unstaked ingress**: staked (SWQoS) transactions may take another path.
- **Independent transactions**: we measure conflicting pairs; for independent ones the thread race is added.

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
scripts/                 survey_clients.py, market_rank.py
data/survey/             client and market surveys
data/raw/<run>/          every send and landing: signatures, slots, positions, block extracts
data/pilot/<run>/        smoke test and pilot, same format; they set the grids, not the results
data/derived/            tables and fits, recomputed from data/raw
figures/                 light and dark SVG
```
