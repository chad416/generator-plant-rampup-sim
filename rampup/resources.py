"""Building blocks: server pool, station, batch oven, AGV fleet.

All of them count statistics only inside the measurement window [w0, w1].
"""

from __future__ import annotations

import heapq
import itertools
import math
import random
from typing import Callable

import simpy

from .dists import exp_or_inf
from .stats import TimeWeighted, overlap


def in_progress(starts, now: float, w0: float, w1: float) -> float:
    """Busy time inside the window of jobs that started but have not finished yet."""
    return sum(overlap(t, now, w0, w1) for t in starts)


class Server:
    """One machine, bench, line, operator place or AGV."""

    __slots__ = ("name", "idx", "busy_since_repair", "ttf", "last_frame", "location", "active")

    def __init__(self, name: str, idx: int):
        self.name = name
        self.idx = idx
        self.busy_since_repair = 0.0
        self.ttf = math.inf          # busy minutes until the next failure
        self.last_frame: str | None = None
        self.location: str | None = None
        self.active = 0.0            # AGV: active minutes since last charge


class ServerPool:
    """Pool of individual servers with prioritised, optionally filtered requests.

    Lower priority number is served first. A request whose filter matches no free
    server does not block requests behind it. `prefer` picks among free servers
    (smallest key wins).
    """

    def __init__(self, env: simpy.Environment, servers: list[Server]):
        self.env = env
        self.free: list[Server] = list(servers)
        self._waiting: list = []
        self._seq = itertools.count()

    def get(self, priority: int = 1, filt: Callable | None = None, prefer: Callable | None = None):
        ev = self.env.event()
        heapq.heappush(self._waiting, (priority, next(self._seq), ev, filt, prefer))
        self._dispatch()
        return ev

    def put(self, server: Server) -> None:
        self.free.append(server)
        self._dispatch()

    def _dispatch(self) -> None:
        skipped = []
        while self._waiting and self.free:
            item = heapq.heappop(self._waiting)
            _, _, ev, filt, prefer = item
            cands = [s for s in self.free if filt is None or filt(s)]
            if not cands:
                skipped.append(item)
                continue
            s = min(cands, key=prefer) if prefer else cands[0]
            self.free.remove(s)
            ev.succeed(s)
        for item in skipped:
            heapq.heappush(self._waiting, item)


class Station:
    """A group of identical servers with breakdowns, optional scheduled maintenance
    and an optional speed factor (learning curve) on the manual part of each job."""

    def __init__(self, env: simpy.Environment, name: str, n: int, rng: random.Random,
                 window: tuple[float, float], mtbf: float | None = None, mttr: float | None = None,
                 speed: Callable[[float], float] | None = None,
                 pm_interval: float | None = None, pm_duration: float | None = None):
        if n < 1:
            raise ValueError(f"{name}: needs at least one server")
        self.env, self.name, self.n, self.rng = env, name, n, rng
        self.w0, self.w1 = window
        self.mtbf, self.mttr = mtbf, mttr
        self.speed = speed
        servers = [Server(name, i) for i in range(n)]
        for s in servers:
            s.ttf = exp_or_inf(rng, mtbf)
        self.pool = ServerPool(env, servers)
        self.busy = 0.0
        self.down = 0.0
        self.pm = 0.0
        self.running: dict[int, float] = {}   # job id -> start, for jobs not finished yet
        self._job_ids = itertools.count()
        self.queue = TimeWeighted(*window)
        self.wait_sum = 0.0
        self.wait_n = 0
        self.jobs_done = 0
        if pm_interval and pm_duration:
            for i, s in enumerate(servers):
                env.process(self._maintenance(s, pm_interval, pm_duration, pm_interval * (i + 1) / n))

    def process(self, duration: Callable[[Server], tuple[float, float]], prefer: Callable | None = None):
        """Seize a server, work, release. `duration(server)` returns
        (manual_minutes, machine_minutes); only the manual part is slowed by learning."""
        env = self.env
        t_req = env.now
        self.queue.add(env.now, +1)
        s = yield self.pool.get(1, prefer=prefer)
        self.queue.add(env.now, -1)
        if self.w0 <= env.now < self.w1:
            self.wait_sum += env.now - t_req
            self.wait_n += 1
        manual, machine = duration(s)
        if self.speed is not None:
            manual /= self.speed(env.now)
        d = manual + machine
        start = env.now
        job = next(self._job_ids)
        self.running[job] = start
        yield env.timeout(d)
        del self.running[job]
        self.busy += overlap(start, env.now, self.w0, self.w1)
        self.jobs_done += 1
        s.busy_since_repair += d
        if s.busy_since_repair >= s.ttf:
            env.process(self._repair(s))
        else:
            self.pool.put(s)
        return s

    def _repair(self, s: Server):
        start = self.env.now
        yield self.env.timeout(exp_or_inf(self.rng, self.mttr) if self.mttr else 0.0)
        self.down += overlap(start, self.env.now, self.w0, self.w1)
        s.busy_since_repair = 0.0
        s.ttf = exp_or_inf(self.rng, self.mtbf)
        self.pool.put(s)

    def _maintenance(self, server: Server, interval: float, duration: float, first: float):
        env = self.env
        yield env.timeout(first)
        while True:
            s = yield self.pool.get(0, filt=lambda x: x is server)
            start = env.now
            yield env.timeout(duration)
            self.pm += overlap(start, env.now, self.w0, self.w1)
            self.pool.put(s)
            yield env.timeout(interval)

    def stats(self, now: float) -> dict:
        cap = self.n * (self.w1 - self.w0)
        busy = self.busy + in_progress(self.running.values(), now, self.w0, self.w1)
        busy, down, pm = busy / cap, self.down / cap, self.pm / cap
        return {
            "servers": self.n,
            "busy": busy,
            "down": down,
            "pm": pm,
            "util": busy + down + pm,
            "queue": self.queue.mean(now),
            "wait_min": self.wait_sum / self.wait_n if self.wait_n else 0.0,
        }


class BatchOven:
    """Batch process (VPI + cure oven). Each oven starts a batch when the waiting
    parts fill it, or when the oldest waiting part has waited `fill_timeout`.
    Parts are loaded first-fit in arrival order. The cycle time is fixed."""

    def __init__(self, env: simpy.Environment, n: int, capacity: int, cycle: float,
                 fill_timeout: float, rng: random.Random, window: tuple[float, float],
                 mtbf: float | None = None, mttr: float | None = None):
        if n < 1:
            raise ValueError("impregnation: needs at least one oven")
        self.env, self.n, self.capacity, self.cycle = env, n, capacity, cycle
        self.fill_timeout, self.rng = fill_timeout, rng
        self.w0, self.w1 = window
        self.mtbf, self.mttr = mtbf, mttr
        self.waiting: list[list] = []   # [slots, arrival time, done event]
        self._arrival = env.event()
        self.busy = 0.0
        self.slot_busy = 0.0
        self.down = 0.0
        self.running: dict[int, tuple[float, int]] = {}   # oven -> (start, slots) of the cycle in progress
        self.batches = 0
        self.fill_sum = 0
        self.queue = TimeWeighted(*window)
        self.wait_sum = 0.0
        self.wait_n = 0
        self.log: list[tuple[int, float, int]] = []   # (oven, start, slots) of every batch
        for i in range(n):
            env.process(self._controller(i))

    def load(self, slots: int):
        """Queue a part; returns an event that fires when its cycle is done."""
        if slots > self.capacity:
            raise ValueError(f"part needs {slots} slots, oven holds {self.capacity}")
        ev = self.env.event()
        self.waiting.append([slots, self.env.now, ev])
        self.queue.add(self.env.now, +1)
        if not self._arrival.triggered:
            self._arrival.succeed()
        return ev

    def _next_arrival(self):
        if self._arrival.triggered:
            self._arrival = self.env.event()
        return self._arrival

    def _controller(self, idx: int):
        env = self.env
        busy_since_repair = 0.0
        ttf = exp_or_inf(self.rng, self.mtbf)
        while True:
            if not self.waiting:
                yield self._next_arrival()
                continue
            queued = sum(item[0] for item in self.waiting)
            deadline = self.waiting[0][1] + self.fill_timeout
            if queued < self.capacity and env.now < deadline:
                yield self._next_arrival() | env.timeout(deadline - env.now)
                continue
            batch, used = [], 0
            for item in self.waiting:
                if used + item[0] <= self.capacity:
                    batch.append(item)
                    used += item[0]
                    if used == self.capacity:
                        break
            for item in batch:
                self.waiting.remove(item)
                self.queue.add(env.now, -1)
                if self.w0 <= env.now < self.w1:
                    self.wait_sum += env.now - item[1]
                    self.wait_n += 1
            start = env.now
            self.log.append((idx, start, used))
            self.running[idx] = (start, used)
            yield env.timeout(self.cycle)
            del self.running[idx]
            ov = overlap(start, env.now, self.w0, self.w1)
            self.busy += ov
            self.slot_busy += used * ov
            if self.w0 <= start < self.w1:
                self.batches += 1
                self.fill_sum += used
            for item in batch:
                item[2].succeed()
            busy_since_repair += self.cycle
            if busy_since_repair >= ttf:
                rstart = env.now
                yield env.timeout(exp_or_inf(self.rng, self.mttr) if self.mttr else 0.0)
                self.down += overlap(rstart, env.now, self.w0, self.w1)
                busy_since_repair = 0.0
                ttf = exp_or_inf(self.rng, self.mtbf)

    def stats(self, now: float) -> dict:
        span = self.w1 - self.w0
        busy = self.busy + in_progress((t for t, _ in self.running.values()), now, self.w0, self.w1)
        slot_busy = self.slot_busy + sum(used * overlap(t, now, self.w0, self.w1)
                                         for t, used in self.running.values())
        busy = busy / (self.n * span)
        down = self.down / (self.n * span)
        slot_util = slot_busy / (self.n * self.capacity * span)
        return {
            "servers": self.n,
            "busy": busy,
            "down": down,
            "pm": 0.0,
            # A part-full batch still blocks the oven, so the bottleneck measure
            # for a batch process is slot utilisation, not time busy.
            "util": slot_util + down,
            "occupancy": busy + down,
            "mean_fill": self.fill_sum / (self.batches * self.capacity) if self.batches else 0.0,
            "queue": self.queue.mean(now),
            "wait_min": self.wait_sum / self.wait_n if self.wait_n else 0.0,
        }


class AgvFleet:
    """K AGVs, one load per trip. The nearest free AGV takes the oldest request.
    An AGV drives empty to the pickup, then loaded to the drop point. After
    `battery` active minutes it drives to the charger and charges."""

    def __init__(self, env: simpy.Environment, n: int, dist: dict, speed: float, handling: float,
                 battery: float, charge: float, window: tuple[float, float], start: str = "charger"):
        if n < 1:
            raise ValueError("agv: needs at least one AGV")
        self.env, self.n, self.dist, self.speed = env, n, dist, speed
        self.handling, self.battery, self.charge = handling, battery, charge
        self.w0, self.w1 = window
        agvs = [Server("agv", i) for i in range(n)]
        for a in agvs:
            a.location = start
        self.pool = ServerPool(env, agvs)
        self.running: dict[int, float] = {}
        self.busy = 0.0
        self.down = 0.0
        self.moves = 0
        self.queue = TimeWeighted(*window)
        self.wait_sum = 0.0
        self.wait_n = 0

    def move(self, src: str, dst: str):
        env = self.env
        t_req = env.now
        self.queue.add(env.now, +1)
        a = yield self.pool.get(1, prefer=lambda x: self.dist[x.location][src])
        self.queue.add(env.now, -1)
        if self.w0 <= env.now < self.w1:
            self.wait_sum += env.now - t_req
            self.wait_n += 1
        d = (self.dist[a.location][src] + self.dist[src][dst]) / self.speed + self.handling
        start = env.now
        self.running[a.idx] = start
        yield env.timeout(d)
        del self.running[a.idx]
        self.busy += overlap(start, env.now, self.w0, self.w1)
        if self.w0 <= start < self.w1:
            self.moves += 1
        a.location = dst
        a.active += d
        if a.active >= self.battery:
            env.process(self._charge(a))
        else:
            self.pool.put(a)

    def _charge(self, a: Server):
        start = self.env.now
        yield self.env.timeout(self.dist[a.location]["charger"] / self.speed + self.charge)
        self.down += overlap(start, self.env.now, self.w0, self.w1)
        a.location = "charger"
        a.active = 0.0
        self.pool.put(a)

    def stats(self, now: float) -> dict:
        cap = self.n * (self.w1 - self.w0)
        busy = self.busy + in_progress(self.running.values(), now, self.w0, self.w1)
        busy, down = busy / cap, self.down / cap
        return {
            "servers": self.n,
            "busy": busy,
            "down": down,
            "pm": 0.0,
            "util": busy + down,
            "queue": self.queue.mean(now),
            "wait_min": self.wait_sum / self.wait_n if self.wait_n else 0.0,
        }


def make_distance_matrix(upper: dict) -> dict:
    """Symmetric full matrix (with zero diagonal) from a one-direction listing."""
    nodes = set(upper)
    for row in upper.values():
        nodes |= set(row)
    full = {a: {b: 0.0 for b in nodes} for a in nodes}
    for a, row in upper.items():
        for b, d in row.items():
            full[a][b] = full[b][a] = float(d)
    for a in nodes:
        for b in nodes:
            if a != b and full[a][b] == 0.0:
                raise ValueError(f"distance {a} -> {b} missing")
    return full

