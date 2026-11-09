"""Small statistics helpers: windowed time averages, confidence intervals, Erlang C."""

from __future__ import annotations

import math
from statistics import mean, stdev

# Student t, two-sided 95 % (0.975 quantile), by degrees of freedom.
_T975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
    9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 25: 2.060, 30: 2.042,
    40: 2.021, 60: 2.000, 120: 1.980,
}


def t975(df: int) -> float:
    """0.975 quantile of Student t; uses the next lower tabulated df (conservative)."""
    if df < 1:
        return math.nan
    keys = [k for k in _T975 if k <= df]
    return _T975[max(keys)] if df <= 120 else 1.960


def mean_ci(xs: list[float]) -> dict:
    """Mean and 95 % confidence half-width over replications."""
    n = len(xs)
    if n == 0:
        return {"mean": math.nan, "half": math.nan, "lo": math.nan, "hi": math.nan, "n": 0}
    m = mean(xs)
    if n < 2:
        return {"mean": m, "half": math.nan, "lo": m, "hi": m, "n": n}
    h = t975(n - 1) * stdev(xs) / math.sqrt(n)
    return {"mean": m, "half": h, "lo": m - h, "hi": m + h, "n": n}


def overlap(a: float, b: float, w0: float, w1: float) -> float:
    """Length of [a, b] inside the window [w0, w1]."""
    return max(0.0, min(b, w1) - max(a, w0))


class TimeWeighted:
    """Time-weighted average of a step signal, counted only inside [w0, w1]."""

    def __init__(self, w0: float, w1: float, value: float = 0.0):
        self.w0, self.w1 = w0, w1
        self.value = value
        self._t = 0.0
        self._area = 0.0

    def _accumulate(self, now: float) -> None:
        self._area += self.value * overlap(self._t, now, self.w0, self.w1)
        self._t = now

    def add(self, now: float, delta: float) -> None:
        self._accumulate(now)
        self.value += delta

    def mean(self, now: float) -> float:
        self._accumulate(now)
        span = self.w1 - self.w0
        return self._area / span if span > 0 else math.nan


def erlang_c_wait(lam: float, mu: float, c: int) -> float:
    """Mean wait in queue Wq for an M/M/c queue (Erlang C)."""
    a = lam / mu
    rho = a / c
    if rho >= 1:
        return math.inf
    term = 1.0
    s = 1.0  # sum_{k=0}^{c-1} a^k / k!
    for k in range(1, c):
        term *= a / k
        s += term
    last = term * a / c  # a^c / c!
    p_wait = last / (1 - rho) / (s + last / (1 - rho))
    return p_wait / (c * mu - lam)
