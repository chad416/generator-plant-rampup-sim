"""Random process times."""

from __future__ import annotations

import math
import random

DISTS = ("lognormal", "triangular", "exponential", "deterministic")


def draw(rng: random.Random, mean: float, cv: float = 0.0, dist: str = "lognormal") -> float:
    """One sample with the given mean and coefficient of variation."""
    if mean <= 0:
        return 0.0
    if dist == "deterministic" or (cv == 0 and dist != "exponential"):
        return mean
    if dist == "lognormal":
        s2 = math.log(1.0 + cv * cv)
        return rng.lognormvariate(math.log(mean) - s2 / 2.0, math.sqrt(s2))
    if dist == "exponential":
        return rng.expovariate(1.0 / mean)
    if dist == "triangular":
        # symmetric triangle around the mean; sd = half_width / sqrt(6)
        half = cv * mean * math.sqrt(6.0)
        if half >= mean:
            raise ValueError(f"triangular cv {cv} too large: times would go negative")
        return rng.triangular(mean - half, mean + half, mean)
    raise ValueError(f"unknown distribution {dist!r}; use one of {DISTS}")


def exp_or_inf(rng: random.Random, mean: float | None) -> float:
    """Exponential sample, or infinity when the mean is None (event never happens)."""
    if mean is None or mean <= 0:
        return math.inf
    return rng.expovariate(1.0 / mean)
