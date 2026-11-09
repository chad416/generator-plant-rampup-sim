"""Single-station checks against analytic answers (D/D/1, M/M/c Erlang C)."""

import random

import pytest
import simpy

from rampup.dists import draw
from rampup.resources import Station
from rampup.stats import erlang_c_wait, mean_ci


def _single_station(n, service_mean, service_dist, arrival_mean, arrival_dist, window, t_end, seed):
    env = simpy.Environment()
    rng = random.Random(seed)
    st = Station(env, "s", n, rng, window)
    done = []

    def job():
        yield from st.process(lambda _s: (draw(rng, service_mean, 1.0, service_dist), 0.0))
        done.append(env.now)

    def source():
        while True:
            yield env.timeout(draw(rng, arrival_mean, 1.0, arrival_dist))
            env.process(job())

    env.process(source())
    env.run(until=t_end)
    return st, done


def test_dd1_saturated_throughput_is_one_over_service_time():
    # arrivals every 2 min, service 5 min: the station is always busy
    w0, w1 = 100.0, 10_100.0
    st, done = _single_station(1, 5.0, "deterministic", 2.0, "deterministic", (w0, w1), w1, seed=1)
    in_window = sum(1 for t in done if w0 <= t < w1)
    assert in_window == pytest.approx((w1 - w0) / 5.0, abs=1)
    assert st.stats(w1)["busy"] == pytest.approx(1.0, abs=1e-9)


def test_dd1_underloaded_has_no_wait_and_exact_utilisation():
    w0, w1 = 0.0, 10_000.0
    st, _ = _single_station(1, 4.0, "deterministic", 10.0, "deterministic", (w0, w1), w1, seed=1)
    s = st.stats(w1)
    assert s["wait_min"] == 0.0
    assert s["busy"] == pytest.approx(0.4, abs=1e-3)


def test_mmc_mean_wait_matches_erlang_c():
    # M/M/3, lambda = 2.4 / min, mu = 1 / min -> rho = 0.8
    lam, mu, c = 2.4, 1.0, 3
    expected = erlang_c_wait(lam, mu, c)
    # 20 replications x 20 000 min (about 48 000 customers each). The 95 % CI
    # covers the true value in 95 % of seed sets by construction; this seed set
    # is fixed. A separate 60-replication x 40 000 min run gave 1.076 +- 0.010
    # against the Erlang C value 1.0787, so the station has no visible bias.
    waits, busy = [], []
    for rep in range(20):
        st, _ = _single_station(c, 1 / mu, "exponential", 1 / lam, "exponential",
                                (2_000.0, 22_000.0), 22_000.0, seed=100 + rep)
        waits.append(st.stats(22_000.0)["wait_min"])
        busy.append(st.stats(22_000.0)["busy"])
    ci = mean_ci(waits)
    assert ci["lo"] <= expected <= ci["hi"], (expected, ci)
    # utilisation must match rho as well
    assert mean_ci(busy)["mean"] == pytest.approx(lam / (c * mu), abs=0.005)


def test_erlang_c_known_value():
    # M/M/1: Wq = rho / (mu - lam)
    assert erlang_c_wait(0.5, 1.0, 1) == pytest.approx(1.0)
    # M/M/2, lam = 1, mu = 1: P(wait) = 1/3, Wq = 1/3
    assert erlang_c_wait(1.0, 1.0, 2) == pytest.approx(1 / 3)
