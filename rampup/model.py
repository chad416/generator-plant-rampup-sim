"""The plant model: one replication of one scenario."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import simpy

from .config import FRAMES, handling_min
from .dists import draw
from .resources import AgvFleet, BatchOven, Station, make_distance_matrix
from .stats import TimeWeighted


def learning_speed(weeks_since_hire: float, start: float, weeks_to_full: float) -> float:
    """Speed of a new hire relative to a trained operator: linear from `start` to 1."""
    if weeks_since_hire <= 0:
        return start
    if weeks_to_full <= 0:
        return 1.0
    return start + (1.0 - start) * min(1.0, weeks_since_hire / weeks_to_full)


def station_speed(t_weeks: float, p_new: float, start: float, weeks_to_full: float) -> float:
    """Mean speed of a station where a share p_new of the operators were hired at t = 0."""
    return 1.0 - p_new * (1.0 - learning_speed(t_weeks, start, weeks_to_full))


def poisson(rng: random.Random, mean: float) -> int:
    """Poisson sample (Knuth's method; fine for the means used here, < 700)."""
    limit = math.exp(-mean)
    k, p = 0, rng.random()
    while p > limit:
        k += 1
        p *= rng.random()
    return k


@dataclass
class Unit:
    uid: int
    frame: str
    release_t: float
    ship_t: float | None = None
    tests: int = 0


class Plant:
    def __init__(self, spec: dict, seed: int):
        self.spec = spec
        self.seed = seed
        self.rng = random.Random(seed)
        self.env = simpy.Environment()
        cal = spec["calendar"]
        self.day = cal["shifts_per_day"] * cal["shift_hours"] * 60.0
        self.week = self.day * cal["days_per_week"]
        self.due = spec["due_days"] * self.day
        run = spec["run"]
        if spec["ramp"]:
            self.w0 = 0.0
            self.w1 = run["ramp_weeks"] * self.week
            self.t_end = self.w1
        else:
            self.w0 = run["warmup_weeks"] * self.week
            self.w1 = self.w0 + run["measure_weeks"] * self.week
            self.t_end = self.w1 + self.due   # lets every measured unit reach its due time
        window = (self.w0, self.w1)
        res = spec["resources"]
        st = spec["stations"]
        self.mode = spec["mode"]

        self.stations: dict[str, Station] = {}
        for name in self._station_names():
            c = st[name]
            self.stations[name] = Station(
                self.env, name, res[name], self.rng, window,
                mtbf=c["mtbf_h"] * 60 if c.get("mtbf_h") else None,
                mttr=c["mttr_h"] * 60 if c.get("mttr_h") else None,
                speed=self._speed_fn(name),
                pm_interval=c["pm_interval_h"] * 60 if c.get("pm_interval_h") else None,
                pm_duration=c["pm_duration_h"] * 60 if c.get("pm_duration_h") else None,
            )
        imp = spec["impregnation"]
        self.oven = BatchOven(
            self.env, res["impregnation"], imp["capacity_slots"], imp["cycle_min"],
            imp["fill_timeout_min"], self.rng, window,
            mtbf=imp["mtbf_h"] * 60 if imp.get("mtbf_h") else None,
            mttr=imp["mttr_h"] * 60 if imp.get("mttr_h") else None,
        )
        agv = spec["agv"]
        self.agv = AgvFleet(
            self.env, res["agv"], make_distance_matrix(agv["distance_m"]), agv["speed_m_per_min"],
            agv["handling_min"], agv["battery_drive_min"], agv["charge_min"], window,
            start=agv["start_location"],
        )
        self.wip = TimeWeighted(*window)
        self.units: list[Unit] = []
        self.released = 0
        self.shipped = 0
        self.changeovers = 0

    # ----------------------------------------------------------------- set-up
    def _station_names(self) -> list[str]:
        if self.mode == "manual":
            asm = ["manual_assembly"]
        else:
            asm = ["robot_cell", "fine_work"]
        return ["stator_winding", "rotor_winding", *asm, "test", "repair", "packing"]

    def _speed_fn(self, name: str):
        p = self.spec["p_new"].get(name, 0.0)
        if p <= 0 or not self.spec["stations"][name].get("staffed"):
            return None
        lc = self.spec["learning"]
        week = self.week
        return lambda t: station_speed(t / week, p, lc["start_speed"], lc["weeks_to_full"])

    # ------------------------------------------------------------- processes
    def _new_unit(self, frame: str) -> None:
        u = Unit(len(self.units), frame, self.env.now)
        self.units.append(u)
        self.released += 1
        self.wip.add(self.env.now, +1)
        self.env.process(self._unit(u))

    def _release(self, frame: str, per_day: float):
        """Release orders into production.

        fixed:   one unit every day/per_day minutes.
        poisson: each day's quantity is Poisson(per_day), spread evenly over that day.
        """
        if per_day <= 0:
            return
        env = self.env
        if self.spec["release"] == "fixed":
            gap = self.day / per_day
            yield env.timeout(self.rng.uniform(0, gap))
            while env.now < self.t_end:
                self._new_unit(frame)
                yield env.timeout(gap)
            return
        while env.now < self.t_end:
            day_start = env.now
            n = poisson(self.rng, per_day)
            if n:
                gap = self.day / n
                yield env.timeout(self.rng.uniform(0, gap))
                for i in range(n):
                    self._new_unit(frame)
                    if i < n - 1:
                        yield env.timeout(gap)
            yield env.timeout(max(0.0, day_start + self.day - env.now))

    def _work(self, name: str, u: Unit):
        c = self.spec["stations"][name]
        mean = c["times_min"][u.frame]

        def duration(_server):
            return draw(self.rng, mean, c["cv"], c["dist"]), 0.0

        yield from self.stations[name].process(duration)

    def _test_duration(self, u: Unit):
        c = self.spec["stations"]["test"]
        tt = self.spec["test_times"]

        def duration(server):
            manual = draw(self.rng, handling_min(c, tt, u.frame), c["cv"], c["dist"])
            if server.last_frame is not None and server.last_frame != u.frame:
                manual += tt["changeover_min"]
                if self.w0 <= self.env.now < self.w1:
                    self.changeovers += 1
            server.last_frame = u.frame
            machine = tt["frames"][u.frame]["routine_min"]
            if u.tests == 0 and self.rng.random() < c["type_test_share"]:
                machine += tt["frames"][u.frame]["type_test_extra_min"]
            return manual, machine

        return duration

    def _part(self, u: Unit, part: str):
        name = f"{part}_winding"
        yield from self._work(name, u)
        yield from self.agv.move(name, "impregnation")
        yield self.oven.load(self.spec["impregnation"]["slots"][u.frame])
        yield from self.agv.move("impregnation", "assembly")

    def _unit(self, u: Unit):
        env = self.env
        stator = env.process(self._part(u, "stator"))
        rotor = env.process(self._part(u, "rotor"))
        yield stator & rotor
        if self.mode == "manual":
            yield from self._work("manual_assembly", u)
        else:
            yield from self._work("robot_cell", u)
            yield from self._work("fine_work", u)
        yield from self.agv.move("assembly", "test")
        c = self.spec["stations"]["test"]
        while True:
            # prefer a free bench that last tested the same frame size (no changeover)
            yield from self.stations["test"].process(
                self._test_duration(u), prefer=lambda s: s.last_frame != u.frame)
            u.tests += 1
            pass_rate = c["first_pass_yield"][u.frame] if u.tests == 1 else c["retest_yield"]
            if self.rng.random() < pass_rate:
                break
            yield from self._work("repair", u)
        yield from self.agv.move("test", "packing")
        yield from self._work("packing", u)
        yield from self.agv.move("packing", "shipping")
        u.ship_t = env.now
        self.shipped += 1
        self.wip.add(env.now, -1)

    # ------------------------------------------------------------------ run
    def run(self) -> dict:
        for f in FRAMES:
            self.env.process(self._release(f, self.spec["demand"][f]))
        self.env.run(until=self.t_end)
        return self._results()

    def _results(self) -> dict:
        now = self.env.now
        w0, w1, day = self.w0, self.w1, self.day
        span = w1 - w0
        days = span / day
        shipped_w = [u for u in self.units if u.ship_t is not None and w0 <= u.ship_t < w1]
        lead = [u.ship_t - u.release_t for u in shipped_w]
        if self.spec["ramp"]:
            measured = [u for u in self.units if u.release_t + self.due <= self.t_end]
        else:
            measured = [u for u in self.units if w0 <= u.release_t < w1]
        on_time = sum(1 for u in measured if u.ship_t is not None and u.ship_t - u.release_t <= self.due)

        util = {name: s.stats(now) for name, s in self.stations.items()}
        util["impregnation"] = self.oven.stats(now)
        util["agv"] = self.agv.stats(now)
        bottleneck = max(util, key=lambda k: util[k]["util"])
        longest_queue = max(util, key=lambda k: util[k]["queue"])

        n_weeks = int(math.ceil(self.t_end / self.week))
        weekly = [0] * n_weeks
        weekly_rel = [0] * n_weeks
        for u in self.units:
            weekly_rel[min(int(u.release_t // self.week), n_weeks - 1)] += 1
            if u.ship_t is not None:
                weekly[min(int(u.ship_t // self.week), n_weeks - 1)] += 1
        tested = [u for u in self.units if u.tests > 0 and u.ship_t is not None]

        heads = 0
        for name in self.stations:
            c = self.spec["stations"][name]
            heads += self.spec["resources"][name] * c.get("operators_per_shift", 0)
        heads += self.spec["resources"]["impregnation"] * self.spec["impregnation"].get("operators_per_shift", 0)
        heads *= self.spec["calendar"]["shifts_per_day"]

        wip_mean = self.wip.mean(now)
        lam = len(shipped_w) / span
        w_mean = sum(lead) / len(lead) if lead else math.nan
        return {
            "seed": self.seed,
            "scenario": self.spec["scenario"],
            "resources": dict(self.spec["resources"]),
            "demand_per_day": sum(self.spec["demand"].values()),
            "throughput_per_day": len(shipped_w) / days,
            "throughput_by_frame": {f: sum(1 for u in shipped_w if u.frame == f) / days for f in FRAMES},
            "service_level": on_time / len(measured) if measured else math.nan,
            "units_measured": len(measured),
            "wip_mean": wip_mean,
            "lead_time_mean_days": w_mean / day,
            "lead_times_days": [x / day for x in lead],
            "little": {"L": wip_mean, "lambda_per_min": lam, "W_min": w_mean,
                       "lambda_W": lam * w_mean if lead else math.nan},
            "util": util,
            "bottleneck": bottleneck,
            "longest_queue": longest_queue,
            "oven_mean_fill": util["impregnation"]["mean_fill"],
            "agv_moves_per_day": self.agv.moves / days,
            "changeovers_per_day": self.changeovers / days,
            "first_pass_yield": (sum(1 for u in tested if u.tests == 1) / len(tested)) if tested else math.nan,
            "weekly_shipped": weekly,
            "weekly_released": weekly_rel,
            "weekly_demand": sum(self.spec["demand"].values()) * self.spec["calendar"]["days_per_week"],
            "released": self.released,
            "shipped": self.shipped,
            "wip_end": self.wip.value,
            "units_open": sum(1 for u in self.units if u.ship_t is None),
            "operators_3_shifts": heads,
            "t_end": self.t_end,
        }


def run_replication(spec: dict, seed: int) -> dict:
    return Plant(spec, seed).run()
