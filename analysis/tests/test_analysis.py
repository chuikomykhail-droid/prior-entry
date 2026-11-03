"""Fast checks of the analysis (the full recovery test is `python -m analysis recover`)."""
import math

import numpy as np
import pytest

from analysis import fit, hypotheses, models, pairs, sim


def test_gamma_contains_both_extremes():
    s = np.array([0.0, 5, 10, 20, 30])
    assert np.allclose(models.g_gamma(s, 20, 1), np.exp(-s / 20))
    assert np.allclose(models.g_gamma(s, 20, 300), np.clip(1 - s / 20, 0, 1), atol=0.03)
    assert np.all(models.g_gamma(-s - 1, 20, 4) == 1)


def test_residual_survival_is_convex_and_decreasing():
    s = np.linspace(0, 100, 400)
    g = models.g_gamma(s, 25, 3)
    assert np.all(np.diff(g) <= 1e-12)
    assert np.all(np.diff(g, 2) >= -1e-9)
    # slope at zero is -1/mu (PLAN §5.7)
    assert (g[1] - g[0]) / (s[1] - s[0]) == pytest.approx(-1 / 25, rel=0.02)


def test_s_at_reads_the_curve():
    s50 = models.s_at(0.5, 20, 300, 0.0, 0.0)
    assert s50 == pytest.approx(10, abs=0.3)
    assert models.s_at(0.1, 20, 1, 0.2, 0.0) == math.inf  # floor above 10%


def test_fit_recovers_a_clock_on_simulated_pairs():
    sc = sim.Scenario("t", mu={"VIP": 30.0, "ECO": 30.0}, k={"VIP": 4.0, "ECO": 4.0})
    d = sim.simulate(sc, 1500, rng=np.random.default_rng(1))
    m = d["lane"] == "VIP"
    f = fit.fit_cell(d["s"][m], d["y"][m])
    assert f.mu[0] == pytest.approx(30, rel=0.2)
    # k is weakly identified against the lapse rates (1.5-26 across seeds at this n): only its range
    assert 1 < f.k[0] < 60
    assert f.eps1[0] == pytest.approx(0.03, abs=0.03)


def test_holm():
    adj, rej = hypotheses.holm([0.01, 0.04, 0.03, 0.2])
    assert adj == pytest.approx([0.04, 0.09, 0.09, 0.2])
    assert rej == [True, False, False, False]


def test_profile_interval_handles_censoring():
    prof = [(m, -abs(math.log(m)) * 10) for m in np.exp(np.linspace(math.log(0.1), math.log(2000), 61))]
    ci = fit.profile_interval(prof, 0.0)
    assert ci["lo"] < 1 < ci["hi"]
    flat = [(m, 0.0) for m, _ in prof]
    ci = fit.profile_interval(flat, 0.0)
    assert ci["lo_censored"] and ci["hi_censored"] and ci["hi"] == math.inf


def test_block_key_matches_the_design():
    block = {"tx": {"fee": [8000, 5500], "sigs": [1, 1], "writable": [2, 2], "data_bytes": [31, 31], "cu_limit": [600, 200000],
                    "data_limit": [32768, 32768], "vote": [0, 0], "cu_consumed": [600, 600]}}
    key, vote, _ = pairs.block_keys(block)
    assert int(key[0]) == 2_840_909  # DEAR_VIP in itb/src/design.rs
    assert int(key[1]) == 14_900     # CHEAP_ECO


def test_utc_ms_reads_nanoseconds():
    a = pairs.utc_ms("2026-11-01T22:48:26.376691200+00:00")
    b = pairs.utc_ms("2026-11-01T22:48:26+00:00")
    assert a - b == pytest.approx(376.6912, abs=1e-3)


def test_clock_drift_is_taken_from_the_ntp_samples():
    # +52 ppm for an hour, sampled every 30 s with 0.3 ms jitter, one reply from a foreign clock
    rng = np.random.default_rng(1)
    t = 1.7e12 + np.arange(0, 3600e3, 30e3)
    off = 2270 + 52e-6 * (t - t[0]) + rng.normal(0, 0.3, len(t))
    off[10] += 200
    f = pairs.ntp_offset_fn({}, [{"local_unix_ms": x, "offset_ms": y} for x, y in zip(t, off)])
    assert f(t[0]) == pytest.approx(2270, abs=0.3)
    assert f(t[-1]) == pytest.approx(2270 + 52e-6 * (t[-1] - t[0]), abs=0.3)
    # without samples: the constant measured at the start
    assert pairs.ntp_offset_fn({"ntp_offset_ms": 327.0}, [])(t[0]) == 327.0


def test_a_missing_window_start_comes_back_from_its_own_window():
    # the last leader's slot 9 starts at 0; a leader change (270 ms); our window's slot 10 is missing,
    # slots 11-13 come every 200 ms
    slots = [{"slot": 9, "server_unix_ms": 0.0}] + [{"slot": 10 + k, "server_unix_ms": 270.0 + 200.0 * k} for k in (1, 2, 3)]
    st = pairs.SlotTimes(slots, 0.0)
    assert st.b == pytest.approx(200.0)
    assert st.start(10) == pytest.approx(270.0)
    # nothing observed within three slots after: unknown, not guessed from far away
    assert math.isnan(st.start(20))


def test_simultaneous_pairs_stay_out_of_the_clock_fits():
    import pandas as pd
    df = pd.DataFrame({"complete": [True] * 4 + [False], "timed": True, "buffered": [False, False, False, True, False],
                       "series": ["FEE", "FEE", "REV", "FEE", "FEE"], "s_ms": [0.003, 7.0, -5.0, 0.002, 0.004],
                       "simultaneous": [True, False, False, True, True], "y": [1, 0, 1, 1, 1]})
    assert pairs.clock_pairs(df)["s_ms"].tolist() == [7.0, -5.0]
    # in the window only: the buffered and the incomplete ones are not read either
    assert pairs.simultaneous_pairs(df)["s_ms"].tolist() == [0.003]


def test_a_gap_inside_one_slot():
    st = pairs.SlotTimes([{"slot": 10 + k, "server_unix_ms": 200.0 * k} for k in range(4)], 0.0)
    assert pairs._inside_slot(st, 20.0, 100.0, 10) == (True, 80.0)
    assert pairs._inside_slot(st, 20.0, 140.0, 10)[0] is False  # 40 ms before the next slot: too close
    assert pairs._inside_slot(st, 150.0, 100.0, 10)[0] is False  # B in the next slot
    assert pairs._inside_slot(st, 260.0, -50.0, 10) == (True, 140.0)  # REV: B first, both in slot 11


def test_late_overtakes_call_a_tail_only_above_the_floor():
    import pandas as pd
    from analysis import report
    assert report.late_window("HarmonicAgave") == (75.0, 150.0)
    assert report.late_window("JitoLabs") == (40.0, 150.0)
    s = np.r_[np.full(40, 100.0), np.full(10, 10.0)]
    tail = report.late_share(pd.DataFrame({"s_ms": s, "y": np.r_[np.ones(10), np.zeros(30), np.ones(10)]}), "HarmonicAgave")
    assert tail["n"] == 40 and tail["b_ahead"] == 10 and tail["tail"]
    none = report.late_share(pd.DataFrame({"s_ms": s, "y": np.r_[np.ones(1), np.zeros(39), np.ones(10)]}), "HarmonicAgave")
    assert not none["tail"]
    # too few pairs in the window: no tail, whatever the share
    few = report.late_share(pd.DataFrame({"s_ms": np.full(3, 100.0), "y": [1.0, 0.0, 0.0]}), "HarmonicAgave")
    assert few["lo"] > 0.05 and not few["tail"]


def test_heterogeneity_separates_a_fifo_validator_from_a_sorting_one():
    rng = np.random.default_rng(3)
    s = np.round(rng.uniform(0.5, 40, 120), 1)
    sorting = (rng.random(120) < 0.03 + 0.92 * models.g_metronome(s, 20.0)).astype(float)
    fifo = (rng.random(120) < 0.03 + 0.92 * models.g_exponential(s, 0.3)).astype(float)
    twin = (rng.random(120) < 0.03 + 0.92 * models.g_metronome(s, 20.0)).astype(float)
    assert hypotheses.validators_equal_test([(s, sorting), (s, fifo)])["p"] < 0.001
    assert hypotheses.validators_equal_test([(s, sorting), (s, twin)])["p"] > 0.01
