"""Batch oven logic: fill, timeout, first-fit, several ovens."""

import random

import pytest
import simpy

from rampup.resources import BatchOven


def _run(n_ovens, arrivals, capacity=4, cycle=100.0, timeout=30.0, t_end=1_000.0):
    """arrivals: list of (time, slots). Returns completion time per part and the batch log."""
    env = simpy.Environment()
    oven = BatchOven(env, n_ovens, capacity, cycle, timeout, random.Random(0), (0.0, t_end))
    finished = {}

    def part(i, t, slots):
        yield env.timeout(t)
        yield oven.load(slots)
        finished[i] = env.now

    for i, (t, s) in enumerate(arrivals):
        env.process(part(i, t, s))
    env.run(until=t_end)
    return finished, oven


def test_full_batch_starts_at_once():
    done, oven = _run(1, [(0, 1)] * 4)
    assert sorted(done.values()) == [100.0] * 4
    assert oven.log == [(0, 0.0, 4)]


def test_part_batch_waits_for_timeout():
    done, oven = _run(1, [(0, 1)])
    assert done[0] == 130.0          # waited 30 min for more parts, then 100 min cycle
    assert oven.log == [(0, 30.0, 1)]


def test_timeout_counts_from_oldest_part():
    done, oven = _run(1, [(0, 1), (20, 1)])
    assert done == {0: 130.0, 1: 130.0}


def test_overflow_waits_for_next_cycle():
    done, oven = _run(1, [(0, 1)] * 6)
    assert sorted(done.values()) == [100.0] * 4 + [200.0] * 2
    assert [b[2] for b in oven.log] == [4, 2]


def test_second_oven_takes_overflow():
    done, oven = _run(2, [(0, 1)] * 6)
    assert sorted(done.values()) == [100.0] * 4 + [130.0] * 2


def test_first_fit_in_arrival_order():
    # 3 + 3 slots do not fit in 4; the 1-slot part behind them joins the first batch
    done, oven = _run(1, [(0, 3), (0, 3), (0, 1)])
    assert done[0] == 100.0 and done[2] == 100.0 and done[1] == 200.0
    assert [b[2] for b in oven.log] == [4, 3]


def test_part_larger_than_oven_is_rejected():
    env = simpy.Environment()
    oven = BatchOven(env, 1, 4, 100.0, 30.0, random.Random(0), (0.0, 100.0))
    with pytest.raises(ValueError):
        oven.load(5)


def test_slot_utilisation_and_fill():
    # four 1-slot parts every 100 min: every batch is full, oven always busy
    arrivals = [(100.0 * k, 1) for k in range(10) for _ in range(4)]
    done, oven = _run(1, arrivals, t_end=1_000.0)
    s = oven.stats(1_000.0)
    assert s["mean_fill"] == pytest.approx(1.0)
    assert s["util"] == pytest.approx(1.0)
