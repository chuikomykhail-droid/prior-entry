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


def test_verify_waits_out_lost_connections_and_rate_limits(monkeypatch):
    import requests

    from analysis import verify

    class Reply:
        def __init__(self, status, body=None):
            self.status_code, self.headers, self._body = status, {"Retry-After": "0"}, body

        def raise_for_status(self):
            assert self.status_code < 400

        def json(self):
            return self._body

    script = [requests.exceptions.ConnectTimeout("no route"), Reply(429), Reply(503), requests.exceptions.ConnectionError("reset"),
              Reply(200, {"result": 7})]

    def post(*args, **kwargs):
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(verify.requests, "post", post)
    monkeypatch.setattr(verify.time, "sleep", lambda s: None)
    assert verify._rpc("http://x", "getBlock", []) == 7
    assert not script

    # an answer that says the block is not there is a result, not a glitch: it must not be retried
    script[:] = [Reply(200, {"error": {"code": -32009}})]
    with pytest.raises(RuntimeError):
        verify._rpc("http://x", "getBlock", [])

    def down(*args, **kwargs):
        raise requests.exceptions.ConnectTimeout("no route")

    monkeypatch.setattr(verify.requests, "post", down)
    with pytest.raises(RuntimeError):
        verify._rpc("http://x", "getBlock", [], attempts=3)


def _write(folder, name, text):
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_compare_measures_numbers_and_refuses_changed_words(tmp_path):
    import json

    from analysis import compare
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    doc = {"tests": [{"mu": 35.7123, "reject": True, "name": "V2", "boot": {"hi": 40.0}}], "n": 18}

    def case(changes, name="fits.json", skip=frozenset()):
        other = json.loads(json.dumps(doc))
        other["tests"][0].update(changes)
        return compare.compare_file(_write(a, name, json.dumps(doc)), _write(b, name, json.dumps(other)), 0.01, skip)

    assert case({}).status == "same"
    close = case({"mu": 35.7200})
    assert close.status == "close" and close.differ == 1 and close.numbers == 3
    assert close.numeric[0][1] == "tests[0].mu" and close.largest == pytest.approx(0.0002154, rel=0.01)
    assert case({"mu": 40.0}).status == "DIFFERENT"
    # a verdict or a name never gets a tolerance
    assert case({"reject": False}).status == "DIFFERENT"
    assert case({"name": "V3"}).status == "DIFFERENT"
    assert case({"mu": None}).status == "DIFFERENT"
    # fields only the full run recomputes are left out of the quick check, and only there
    assert case({"boot": None}, skip=compare.QUICK_SKIPS).status == "same"
    assert case({"boot": None}).status == "DIFFERENT"
    assert compare.compare_file(_write(a, "gone.json", "{}"), str(b / "absent.json")).status == "DIFFERENT"


def test_compare_lets_a_printed_table_move_by_one_digit(tmp_path):
    from analysis import compare
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()

    def status(x, y):
        return compare.compare_file(_write(a, "results.md", x), _write(b, "results.md", y), 0.01).status

    row = "| HarmonicAgave | 35.7 [21.6–40.4] | 0.00037 | **no** |\n"
    assert status(row, row) == "same"
    assert status(row, row.replace("35.7", "35.8")) == "close"  # 0.3%
    assert status(row, row.replace("0.00037", "0.00038")) == "close"  # 2.6%, but one printed digit
    assert status(row, row.replace("35.7", "37.1")) == "DIFFERENT"
    assert status(row, row.replace("**no**", "kept")) == "DIFFERENT"
    assert status(row, row + row) == "DIFFERENT"


def test_pairs_table_keeps_slots_whole(tmp_path):
    import pandas as pd

    from analysis import report
    df = pd.DataFrame({"slot_a": [465335337.0, float("nan")], "slot_b": [465335338.0, float("nan")], "a_slot": [465335337.0, 465335340.0],
                       "block_cu": [47043623.0, float("nan")], "phase_ms": [96.453601, 4.75659]})
    path = tmp_path / "pairs.csv"
    df.astype(report.WHOLE_COLUMNS).to_csv(path, index=False, float_format="%.6g", lineterminator="\n")
    assert path.read_text().splitlines()[1:] == ["465335337,465335338,465335337,47043623,96.4536", ",,465335340,,4.75659"]
