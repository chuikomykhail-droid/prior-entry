# Quick checks behind the amendment of the pre-registration

`docs/PREREGISTRATION.md` §10 cites these. They reuse the analysis' own fits and tests (`analysis/fit.py`,
`analysis/hypotheses.py`), with n = 160 FEE pairs per lane (+15 REV), lapses 0.03 / 0.05, and the frozen
uniform ranges of `design/grids.json`. Seeds are fixed: the commands below print the numbers quoted.
They are rough checks (30–60 replicates per case), not the power study of `docs/POWER.md`.

| Command | What | Result (2026-11-03) |
|---|---|---|
| `python scripts/amendment/lanesim.py 60 10` | Lane test with the same curve in both lanes (clocks, two-validator mixtures, a tail), frozen per-lane grids and one grid for both lanes | null rejections at alpha 0.0056: 7 of 540 (frozen grids), 3 of 360 (one grid); at 0.05: 6.1% and 7.5% |
| `python scripts/amendment/sim2.py lane JitoLabs fifo50_exp5 0 40 31` | Half the pairs from a validator that takes every transaction on arrival, half from a 5 ms exponential clock, both lanes | family mu 0.96 / 0.85 ms, k at 0.25; lane test 0 of 40 at 0.0056 |
| `python scripts/amendment/tail.py 0.3 42 30` | 20 ms rounds, 30% of A wait ~100 ms more | V1 kept 30 of 30; mu 18.9 ms, eps1 0.17; B ahead in 18% at 40–150 ms |
| `python scripts/amendment/tail.py 0.15 41 30` | the same with 15% | V1 kept 28 of 30; eps1 0.10; B ahead in 10% at 40–150 ms |
| `python scripts/amendment/sim2.py claim HarmonicAgave 50 0 40 33` | 50 ms clock, no slot cuts | mu 49.3 ms; V2 rejected at 0.05 in 1 of 40 |
| `python scripts/amendment/sim2.py claim HarmonicAgave 50 1 40 20` | 50 ms clock, cuts at 213 ms slot boundaries | mu 46.0 ms; 4 of 40 |
| `python scripts/amendment/sim2.py claim AgaveBam 20 1 40 21` | 20 ms clock, slot cuts | mu 17.9 ms; 0 of 40 |
