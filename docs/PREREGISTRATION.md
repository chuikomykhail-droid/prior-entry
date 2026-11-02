# Pre-registration: the shutter speed of Solana leaders, in two lanes

**Status: DRAFT — not frozen.** Freezing = one commit containing this file with every `TBD` filled from
the pilot, `design/grids.json`, and the analysis code; its SHA-256 goes into a Memo on mainnet from the
measurement wallet before the first main-run window. Hashes:

| Item | Value |
|---|---|
| Commit | TBD |
| SHA-256 of this file | TBD |
| SHA-256 of `design/grids.json` | TBD |
| Tree hash of `analysis/` (`git rev-parse HEAD:analysis`) | TBD |
| Memo transaction | TBD |
| Frozen at (UTC) | TBD |

Anything decided after the freeze is labelled exploratory in REPORT.md, and every deviation from this
document is listed there.

## 1. Question

A Solana leader orders the transactions it holds at once by the scheduler key (reward / cost, Agave's
open formula); transactions that arrive apart are ordered by arrival. We estimate **how far apart is
"apart"** — the shutter speed mu of each client — and whether it depends on where a transaction ranks in
the market (lane).

## 2. Design (fixed)

- **Unit**: a pair of our own transactions with the same fee payer (shared write lock). A is cheap, B is
  dear on every key; B is written s ms after A on the same QUIC connection to the leader's TPU. Outcome
  Y = 1 if B is ahead of A by (slot, index).
- **Lanes**: VIP — CU limit 600, key at ~98th percentile of mainnet; ECO — CU limit 200,000, key at
  ~50th (A) and ~67th (B) percentile. Same lamports in both lanes: 5,500 (A) and 8,000 (B).
- **Series and quotas** per family (complete pairs are the stopping rule, §6):

| Series | What | Main family | Small family |
|---|---|---|---|
| FEE × VIP, FEE × ECO | s ≥ 0 by the grid of §3 | 160 + 160 | 50 + 50 |
| REV × VIP, REV × ECO | B first, s ∈ {−2, −5, −10, −20} ms | 15 + 15 | 5 + 5 |
| CTRL_C2 | X (600 CU, 32 KiB data limit, 500 lamports priority) and Y (600 CU, 64 MiB, 3,000) ~300 ms before the window, order random, 0.3 ms apart | 15 | 10 |

- **Windows**: 4 pairs per window (main), 6 (small); FEE pairs split evenly between the lanes in every
  window; A fires at a uniformly random moment in [+120, +650 − s] ms after the window anchor; at most 8
  stream writes per 100 ms; payers assigned to pairs at random.
- **Families and validators**: main — AgaveBam, JitoLabs, HarmonicAgave, HarmonicFiredancer, Firedancer;
  small — FireBAM, Rakurai, Agave. Validators: TBD after the pilot's QUIC checks (2 per main family, plus
  spares).
- **Two sessions** at least 8 h apart, half of each quota in each.

## 3. Grid of s (FEE)

From the pilot, for every (family, lane) the estimate mu_hat (gamma model, §4) gives the main-run grid:
70% of FEE pairs uniform in [0, clamp(2 mu_hat, 10, 300)] ms, 30% from {0, 1, 2, 3, 4, 6, 8, 10, 12, 15,
18, 21, 25, 30, 35, 40, 50, 60, 80, 100, 150} ms (ECO adds 200 and 300). Applied by `itb freeze-grids`;
the frozen grids are `design/grids.json` (TBD).

## 4. Model

For a cell (family, lane), with s the **actual** gap between the two stream writes:

```
P(Y = 1 | s) = eps1 + (1 − eps1 − eps2) · E[G(s + eta)],  eta ~ N(0, 0.3² ms²)
G(s) = Q(k + 1, s k / mu) − (s / mu) · Q(k, s k / mu)      (s > 0);  G = 1 for s ≤ 0
```

G is the residual survival of a renewal process with gamma(k, mu/k) intervals: k = 1 is the exponential
("on demand"), k → ∞ the metronome. mu, k, eps1 (floor), eps2 (ceiling) are fitted by maximum likelihood
(L-BFGS-B, bounds mu ∈ [0.05, 3000] ms, k ∈ [0.25, 300], eps ∈ (0, 0.45)). The 95% interval of mu is the
profile-likelihood interval (χ²₁); an end that does not cross inside [0.1, 2000] ms is reported as
censored ("mu < X" / "mu > X"). A cell is fitted when it has at least 40 clock pairs.

## 5. Confirmatory tests

Nine tests, Holm correction at familywise alpha = 0.05:

| # | Family | Null | Test |
|---|---|---|---|
| V1 | AgaveBam | mu_VIP = 20 ms (bam.dev, 9.10.2026: "from 25ms to 20ms rounds") | LR, mu fixed at 20 vs free; χ²₁, two-sided |
| V2 | HarmonicAgave | mu_VIP = 50 ms (docs.harmonic.gg: "discrete 50ms batches") | same, 50 |
| V3 | HarmonicFiredancer | mu_VIP = 50 ms | same, 50 |
| E1 | HarmonicAgave vs HarmonicFiredancer | equal mu_VIP | joint fit, k shared, own eps; LR χ²₁, two-sided |
| L1 | AgaveBam | mu_ECO = mu_VIP (pure clock) | joint fit of both lanes, k and eps shared; signed-root LR, one-sided (mu_ECO > mu_VIP) |
| L2 | HarmonicAgave | same | same |
| L3 | HarmonicFiredancer | same | same |
| L4 | JitoLabs | same (prediction: queue, mu_ECO > mu_VIP) | same |
| L5 | Firedancer | same | same, **two-sided** |

Why the lapse rates are shared in L: in a 60-replicate simulation check (n = 160 per lane, exponential
5 → 5 ms) the lane test with lapse rates per lane rejected 5% of null replicates at alpha = 0.006 and 8% at
0.05; with shared lapse rates, 1.7% and 5%. The full simulation (docs/POWER.md) uses the shared version. In V and E each
group keeps its own lapse rates.

**Verdicts.** V: the claim is rejected when its Holm-adjusted p < 0.05 (equivalently, for one test, when
the claim is outside the profile interval). L1–L3 rejected = "the aggregator is not a pure clock: the lower
rank waits longer". L4 rejected = the predicted queue is confirmed. L5 = estimate and interval of
mu_ECO / mu_VIP. A test whose cells have fewer than 40 clock pairs is reported as not run, and Holm runs
over the tests that ran.

**Robustness (reported, not used for the verdict):** window-cluster bootstrap intervals of mu, k and
mu_ECO / mu_VIP (pairs of one window share a clock); sigma = 1 ms instead of 0.3; shape comparison
(metronome, exponential, gamma, constant) by likelihood ratio and AIC.

## 6. Cleaning, attribution, stopping

1. A pair enters the analysis when both probes landed, executed without error, in blocks of the same
   producer, that producer is the targeted leader (fee-reward recipient of the block) and both slots are
   in the targeted window.
2. Family = client id of the producer in the gossip snapshot nearest to the window (within 90 s).
3. Buffered pairs — A written before the first slot of the window started (slot start = the RPC node's
   first-shred timestamp − rpc_lag_ms, our clock corrected by NTP) — do not enter the clock fits; they are
   summarised separately (expected: B ahead nearly always).
4. s is the actual gap from the two stream-write timestamps.
5. Everything else stays in the raw data and is counted in `losses.json`.
6. **Stopping**: a family's session ends when its quota of complete pairs is reached or the session time
   is over — never on results.

## 7. Exploratory (no confirmatory claims)

Phase in the slot (first 30 ms vs rest), convexity of the curve (convex decreasing regression, bootstrap
test), per-validator fits, sessions, rank of A in its block as a continuous covariate, foreign
transactions between A and B, small families, "ms per key" read-outs s50 and s10, placebos (s shuffled
within cell; lanes shuffled within window; lexicographic signature order).

## 8. Any outcome is a result

| Outcome | Headline |
|---|---|
| V1–V3 rejected | The published 20 and 50 ms are not what we measure: X and Y |
| V1–V3 kept | First independent check: the aggregators' clocks run as published |
| L4 or L5 rejected | The rule depends on how much you ask for: the typical transaction's shutter is N times longer |
| L1–L3 rejected | The aggregator is not only a clock: the lower rank waits for a later round |
| No lane effect | The rule does not depend on the market: the shutter is a property of the client |
| Step at zero | The clock is faster than the instrument: mu < X ms |
| Flat curve | No rule |

## 9. Budget and safety

Hard cap 0.045 SOL in code (ledger reservation before every send, worst case: both probes land);
`--live`, `--cap-sol` and `--not-after` required; nothing is sent to RPC; mainnet and post-Alpenglow are
checked before a send permit exists.
