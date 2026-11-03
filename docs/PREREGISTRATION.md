# Pre-registration: the shutter speed of Solana leaders, in two lanes

**Status: FROZEN on 2026-11-03, after the pilot and before the first main-run window; AMENDED the same
day after a review of the pilot, before the Memo and before any main-run window (§10: what changed and
why; the first freeze is commit `375c598`).** The commit that holds this file also holds
`design/grids.json` and the analysis code as they will be run. The SHA-256 of this file and that commit go
into a Memo on mainnet from the measurement wallet before session A; the hash, the commit and the Memo
signature are listed in REPORT.md §1 (a file cannot hold its own hash).

| Item | Value |
|---|---|
| SHA-256 of `design/grids.json` | `b7657263e450d03d66a892cc14a05b6913a5ad9211ca03021a296d593409e605` |
| Tree hash of `analysis/` (`git rev-parse <commit>:analysis`) | `21feb6c95a8641629432867d738c6c32650c3fe0` |
| Pilot | `data/pilot/20261103T111104Z-live/`, checks in `data/pilot/pilot_check.json` |

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
  ~50th (A) and ~67th (B) percentile (pilot, in their own blocks: VIP 98th / 99th, ECO 51st / 64th).
  Same lamports in both lanes: 5,500 (A) and 8,000 (B).
- **Series and quotas** per family (quotas count fired pairs; the stopping rule is §6):

| Series | What | Main family | Small family |
|---|---|---|---|
| FEE × VIP, FEE × ECO | s ≥ 0 by the grid of §3; 10% at s = 0 ("simultaneous", read without the model) | 160 + 160 | 50 + 50 |
| REV × VIP, REV × ECO | B first, s ∈ {−2, −5, −10, −20} ms | 15 + 15 | 5 + 5 |
| CTRL_C2 | X (600 CU, 32 KiB data limit, 500 lamports priority) and Y (600 CU, 64 MiB, 3,000) ~300 ms before the window, order random, 0.3 ms apart | 15 | 10 |

- **Windows**: 4 pairs per window (main), 6 (small); FEE pairs split evenly between the lanes in every
  window; A fires at a uniformly random moment in [+120, +650 − s] ms after the window anchor; at most 8
  stream writes per 100 ms; payers assigned to pairs at random.
- **Families and validators**: main — AgaveBam, JitoLabs, HarmonicAgave, HarmonicFiredancer, Firedancer;
  small — FireBAM, Rakurai, Agave. Fifteen validators, every one of them in the pilot (QUIC losses at
  most 10.5%, `9rkJMARq`):

| Family | Validators |
|---|---|
| AgaveBam | `5Cchr1XGEg7dbBXByV5NY2ad8jfxAM7HA3x8D56rq9Ux`, `9rkJMARqK6VBkcxGfKBAwnA44gPAfGxPbPsfsggFNDSQ` |
| JitoLabs | `HEL1USMZKAL2odpNBj2oCjffnFGaYwmbGmyewGv1e2TU`, `E1r4Psq84tHfQ6aPTvvDka4U3u8zPVD7gEUrH25RdxHL` |
| HarmonicAgave | `Fd7btgySsrjuo25CJCj7oE7VPMyezDhnx7pZkj2v69Nk`, `EkvdKhULbMFqjKBKotAzGi3kwMvMpYNDKJXXQQmi6C1f` |
| HarmonicFiredancer | `Awes4Tr6TX8JDzEhCZY2QVNimT6iD1zWHzf1vNyGvpLM`, `EvnRmnMrd69kFdbLMxWkTn1icZ7DCceRhvmb2SJXqDo4` |
| Firedancer | `9eGrDohdNTAo61DRHyfMuqKWXqYnA3i254Wiszxe8FoY`, `JD549HsbJHeEKKUrKgg4Fj2iyv2RGjsV7NTZjZUrHybB` |
| FireBAM | `9jxgosAfHgHzwnxsHw4RAZYaLVokMbnYtmiZBreynGFP` |
| Rakurai | `ana2y2YvQ3ZPMwm6qhnN3nJoUSiT3qx5Pvetkq9xcfY`, `E3mDbFMr8yZcCAZx5wPUFCRmLX31u8Nnj4jPoPc54h3F` |
| Agave | `7QQGNm3ptwinipDCyaCF7jY5katgmFUu1ieP2f7nwLpE`, `5Us18hLZPXJTS4QVuGSsUw137Dyd2tgBaem24Xsf5nBS` |

  A validator that leaves gossip or loses its stake before a session is left out of that session (the
  run refuses unknown or unstaked identities), and REPORT.md says so.
- **Two sessions** starting at least 8 h apart, each firing the quotas scaled by q (§6.7):
  `itb run --live --cap-sol 0.045 --not-after <UTC> --session A|B --design design/grids.json
  --quota-scale 0.646 --validators <the fifteen> --minutes 180 --out data/raw`.

## 3. Grid of s (FEE)

The FEE pairs of a (family, lane) draw s in this order (amended, §10):

1. **10% at s = 0** — the simultaneous pairs, read without the model (§5) and kept out of the clock fits;
2. for a family with a published period T (AgaveBam and FireBAM: 20 ms; HarmonicAgave and
   HarmonicFiredancer: 50 ms), **15% uniform in [1.5 T, 150] ms**, where a T-ms clock no longer lets B
   overtake: the late overtakes of §5 are read there;
3. the rest: 70% uniform in [0, clamp(2 mu_hat, 10, 300)] ms, with mu_hat the pilot estimate (gamma
   model, §4), and 30% from the base grid {0, 1, 2, 3, 4, 6, 8, 10, 12, 15, 18, 21, 25, 30, 35, 40, 50, 60,
   80, 100, 150} ms (ECO adds 200 and 300). A (family, lane) with fewer than 10 clock pairs in the pilot
   has no uniform part.

Applied by `itb freeze-grids` (`GridSpec::main_run` in `itb/src/design.rs`), which writes a grid for every
family; the frozen grids are `design/grids.json` (SHA-256 above). The uniform ranges are those of the first
freeze (`design/mu_hat.json` unchanged). The simulation of docs/POWER.md used the rule before the
amendment (70% / 30%, no s = 0 or late part). The pilot estimates (10–18 clock pairs per cell, rough by
design: they set only where the uniform part of the grid ends):

| Family | VIP: mu_hat → uniform part | ECO: mu_hat → uniform part |
|---|---|---|
| AgaveBam | 59.5 ms → [0, 118.9] | 17.4 ms → [0, 34.9] |
| JitoLabs | 56.8 ms → [0, 113.5] | 266.0 ms → [0, 300] |
| HarmonicAgave | 30.0 ms → [0, 60.0] | 27.2 ms → [0, 54.5] |
| HarmonicFiredancer | 9.7 ms → [0, 19.3] | 143.4 ms → [0, 286.9] |
| Firedancer | 19.8 ms → [0, 39.7] | 7.0 ms → [0, 13.9] |
| FireBAM, Rakurai, Agave | no uniform part | no uniform part |

Expected shares of FEE pairs at s = 0: 10% plus the base grid's own zero (1–1.3% in the main families,
3–4% in the small ones); in [1.5 T, 150] ms for the Harmonic VIP cells: 18% (was 4%).

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

The simultaneous pairs (planned s = 0) do not enter the fits. With sigma = 0.3 ms the model gives a client
that takes every transaction on arrival about half "B ahead" at s = 0; in the pilot two validators kept A
first at a 2–3 µs gap in all 4 such pairs in the window. They are read without the model (§5).

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

**Read-outs that go with the tests** (amended, §10; pre-registered, outside the Holm family):

1. **Per validator** — the main descriptive table, the bounty's question for each validator. For every
   validator and lane: the share of B ahead among the simultaneous pairs (s = 0) and among the clock
   pairs with s in (0, 20], (20, 60] and (60, 200] ms, each with its Wilson 95% interval; the late
   overtakes (3); mu and its profile interval from 60 clock pairs on.
2. **Heterogeneity** — per family and lane, over its validators with at least 30 clock pairs: one mu for
   all against one each (k shared, lapse rates per validator), LR, χ² with G − 1 degrees of freedom. At
   p < 0.05 the family's mu is marked † and that family's results are read per validator; "the
   validators of this client differ" is claimed only when the Holm-adjusted p over these tests is below
   0.05 too.
3. **Late overtakes** — the share of B ahead among the clock pairs with s in [1.5 T, 150] ms (T the
   published period; [40, 150] ms for the other families), Wilson 95%. A **tail** when at least 20 pairs
   are in that window and the lower bound exceeds 5%.
4. **Reading of V** — rejected: "the published T is not what we measure"; kept without a tail:
   "consistent with T-ms batches"; kept with a tail: "the round matches T, but X% of the transactions sent
   1.5 T or more later still overtake". The LR test alone cannot tell these apart: a tail is absorbed in
   eps1 (§10).

**Robustness (reported, not used for the verdict):** window-cluster bootstrap intervals of mu, k and
mu_ECO / mu_VIP (pairs of one window share a clock); sigma = 1 ms instead of 0.3; shape comparison
(metronome, exponential, gamma, constant) by likelihood ratio and AIC; the buffered boundary (§6.3)
moved 50 ms earlier and 50 ms later; V1–V3 on the clock pairs whose gap lies inside one slot by the RPC
node's timing (both writes in the same slot, the later one at least 50 ms before the next slot's first
shred), since a slot boundary between A and B cuts the pair whatever the client's clock (amended, §10).

## 6. Cleaning, attribution, stopping

1. A pair enters the analysis when both probes landed, executed without error, in blocks of the same
   producer, that producer is the targeted leader (fee-reward recipient of the block) and both slots are
   in the targeted window.
2. Family = client id of the producer in the gossip snapshot nearest to the window (within 90 s).
3. Buffered pairs — A written before the window started — do not enter the clock fits. The window
   counts as started when the RPC node received the first shred of its first slot (the node's own
   timestamp; our clock corrected by NTP, a line through the run's NTP samples). The leader started
   earlier, and our probe reaches the leader after we write it, so a pair written later certainly
   arrived in the window. In the pilot no probe landed in a slot whose next slot's first shred came less
   than 29 ms after the probe was written: the true boundary lies up to ~30–70 ms earlier, and the rule
   errs toward excluding (6% of the pilot's complete pairs). Pairs written more than 100 ms before the
   first shred surely reached the leader before the window and are summarised separately (expected: B
   ahead nearly always); those in between are in neither. A first slot without a first-shred timestamp
   starts ~200 ms per slot before the nearest of the window's next three slots; with none of them, the
   pair is "untimed" and stays out of the clock fits too. (The run aims its probes at the predicted
   first shred minus 100 ms.)
4. s is the actual gap from the two stream-write timestamps.
5. FEE pairs planned at s = 0 are the simultaneous pairs: those that passed 1–3 (in the window) are read
   without the model and do not enter the clock fits.
6. Everything else stays in the raw data and is counted in `losses.json`.
7. **Stopping**: quotas count *fired* pairs — a planned pair that never left goes back to its quota;
   complete pairs are only known after collection. Each session fires the quotas of §2 scaled by q,
   rounded up per cell: q = 0.5 / c', where c' is the expected share of fired FEE and REV pairs that
   enter the clock fits, lowered if needed so that the worst case of both sessions (every fired pair
   lands) stays under the cap (§9). From the pilot c = 0.852 (184 of 216 sent FEE and REV pairs entered
   the clock fits); the simultaneous pairs (10% of FEE) now stay out, so c' = 0.852 × (1 − 0.1 × 320 / 350)
   = 0.774 and q = 0.646 (first freeze: 0.587): per session a main family fires FEE 104 + 104, REV 10 + 10
   and C2 10 pairs, a small family FEE 33 + 33, REV 4 + 4 and C2 7 — 1,433 pairs; the worst case of both
   sessions, 38,691,000 lamports, plus the 3,354,000 already reserved, stays under the 45,000,000 cap. A
   session ends when every quota is fired or at its `--not-after` — never on results.

## 7. Exploratory (no confirmatory claims)

Phase in the slot (first 30 ms vs rest), convexity of the curve (convex decreasing regression, bootstrap
test), sessions, rank of A in its block as a continuous covariate, foreign transactions between A and B,
small families, "ms per key" read-outs s50 and s10, placebos (s shuffled within cell; lanes shuffled
within window; lexicographic signature order). (Per-validator fits moved to §5.)

## 8. Any outcome is a result

| Outcome | Headline |
|---|---|
| V1–V3 rejected | The published 20 and 50 ms are not what we measure: X and Y |
| V1–V3 kept, no tail | First independent check: the aggregators' clocks run as published |
| V kept with a tail | The round is as published, but X% of transactions wait for a later one |
| Validators of one client differ | The client does not set the shutter, the validator does: X and Y |
| L4 or L5 rejected | The rule depends on how much you ask for: the typical transaction's shutter is N times longer |
| L1–L3 rejected | The aggregator is not only a clock: the lower rank waits for a later round |
| No lane effect | The rule does not depend on the market: the shutter is a property of the client |
| Step at zero | The clock is faster than the instrument: mu < X ms |
| Flat curve | No rule |

## 9. Budget and safety

Hard cap 0.045 SOL in code (ledger reservation before every send, worst case: both probes land);
`--live`, `--cap-sol` and `--not-after` required; nothing is sent to RPC; mainnet and post-Alpenglow are
checked before a send permit exists.

## 10. Amendment after the pilot review (2026-11-03, before the Memo)

The first freeze (commit `375c598`) was reviewed against the pilot's pairs and a few quick simulations
(`scripts/amendment/`, fixed seeds, 30–60 replicates per case). Nothing of the main run had been sent.
What changed:

1. **Simultaneous pairs, read per validator.** In the pilot two validators put A first even at a 2–3 µs
   gap: `E1r4Psq8` (JitoLabs) in all 7 pairs in the window up to 5 ms, `JD549Hsb` (Firedancer) in all 9
   FEE pairs in the window. The other validators of the same clients sorted (`HEL1USMZ` B first in 5 of 6
   pairs at s ≤ 0.5 ms, `9eGrDohd` in 3 of 3). The first freeze gave 2–5 pairs at s ≤ 1 ms per validator
   and lane: too few to tell the two behaviours apart. Now 10% of FEE pairs go at s = 0 (§3), read without
   the model (§4, §5).
2. **Per-validator table and heterogeneity test (§5).** When a family pools a validator that takes every
   transaction on arrival with one that sorts, its mu describes neither: in a simulation (half the pairs
   instantly, half with a 5 ms exponential clock) the family's mu came out 0.9 ms with k at its lower bound.
   The lane test kept its error rate there (0 of 40 replicates at alpha 0.0056).
3. **Late overtakes and the reading of V (§5); late part of the grid (§3).** With 20 ms rounds and 30% of
   A waiting ~100 ms more, V1 was kept in 30 of 30 replicates: the tail went into eps1 (0.17), while B was
   ahead in 18% of the pairs at 40–150 ms. In the pilot B was still ahead at s > 50 ms in 5 of 11 pairs
   on the BAM validators and 2 of 6 on HarmonicFiredancer (0 of 14 on HarmonicAgave). The first freeze put
   4% of the Harmonic VIP pairs in [75, 150] ms.
4. **V1–V3 inside one slot (§5, robustness).** Of the pilot's 69 clock pairs with s ≥ 20 ms, 27 landed in
   different slots, all with A first. In simulation, cuts at 213 ms slot boundaries move a 50 ms clock's
   estimate from 49.3 to 46.0 ms and its false rejections at 0.05 from 1 to 4 of 40.
5. **q from 0.587 to 0.646 (§6.7)**, so that the clock fits keep their expected size without the
   simultaneous pairs.

Checked and left as they were: the per-lane grids (a lane test with the frozen grids and the same curve in
both lanes rejected 7 of 540 null replicates at alpha 0.0056; with one grid for both lanes, 3 of 360);
the hypotheses, tests, model, lanes, validators, uniform ranges and cap. The vendor pages were read again
on 2026-11-03: BAM still gives 20 ms rounds at 200 ms slots ("auction cadence is derived from slot
length"), Harmonic's FBA 50 ms batches sorted by priority fees and tips.
