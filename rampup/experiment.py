"""Replications, summaries and the minimum-resource search."""

from __future__ import annotations

import math
import os
from collections import Counter
from concurrent.futures import Executor, ProcessPoolExecutor
from statistics import mean
from typing import Callable

from .config import FRAMES, active_stations, day_minutes, resolve, resource_keys
from .model import run_replication
from .resources import make_distance_matrix
from .stats import mean_ci

SCALARS = (
    "throughput_per_day", "service_level", "wip_mean", "lead_time_mean_days",
    "oven_mean_fill", "agv_moves_per_day", "changeovers_per_day", "first_pass_yield",
)


def seeds(spec: dict) -> list[int]:
    base = spec["run"]["base_seed"]
    return [base * 1000 + i for i in range(spec["run"]["replications"])]


def _one(args):
    spec, seed = args
    return run_replication(spec, seed)


def run_reps(spec: dict, executor: Executor | None = None) -> list[dict]:
    jobs = [(spec, s) for s in seeds(spec)]
    if executor is None:
        return [_one(j) for j in jobs]
    return list(executor.map(_one, jobs))


def make_executor(max_workers: int | None = None) -> ProcessPoolExecutor:
    n = max_workers or min(12, os.cpu_count() or 1)
    return ProcessPoolExecutor(max_workers=n)


def _percentile(xs: list[float], q: float) -> float:
    if not xs:
        return math.nan
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def summarise(results: list[dict], keep_lead_times: bool = False) -> dict:
    """Mean and 95 % CI over replications, plus pooled distributions."""
    r0 = results[0]
    out: dict = {
        "scenario": r0["scenario"],
        "resources": r0["resources"],
        "demand_per_day": r0["demand_per_day"],
        "replications": len(results),
        "operators_3_shifts": r0["operators_3_shifts"],
    }
    for k in SCALARS:
        out[k] = mean_ci([r[k] for r in results])
    out["throughput_by_frame"] = {f: mean(r["throughput_by_frame"][f] for r in results) for f in FRAMES}
    util = {}
    for name in r0["util"]:
        util[name] = {m: mean(r["util"][name][m] for r in results)
                      for m in ("servers", "busy", "down", "pm", "util", "queue", "wait_min")}
    out["util"] = util
    out["bottleneck"] = max(util, key=lambda k: util[k]["util"])
    out["longest_queue"] = max(util, key=lambda k: util[k]["queue"])
    out["bottleneck_votes"] = dict(Counter(r["bottleneck"] for r in results))
    lead = [x for r in results for x in r["lead_times_days"]]
    out["lead_time_days"] = {
        "p50": _percentile(lead, 0.50), "p90": _percentile(lead, 0.90),
        "p95": _percentile(lead, 0.95), "max": max(lead) if lead else math.nan, "n": len(lead),
    }
    if keep_lead_times:
        out["lead_times_days"] = lead
    n_weeks = len(r0["weekly_shipped"])
    out["weekly_shipped"] = [mean(r["weekly_shipped"][w] for r in results) for w in range(n_weeks)]
    out["weekly_released"] = [mean(r["weekly_released"][w] for r in results) for w in range(n_weeks)]
    out["weekly_demand"] = r0["weekly_demand"]
    out["little"] = {
        "L": mean(r["little"]["L"] for r in results),
        "lambda_W": mean(r["little"]["lambda_W"] for r in results),
    }
    return out


# --------------------------------------------------------------------- search
def lower_bound(cfg: dict, scenario: str) -> dict:
    """Capacity lower bound: the fewest servers with utilisation below 1.

    Optimistic on purpose (no changeovers, no empty AGV trips, no second retest),
    so no configuration below it can keep up with demand.
    """
    spec = resolve(cfg, scenario)
    day = day_minutes(cfg)
    dem = spec["demand"]
    st = spec["stations"]

    def avail(c: dict) -> float:
        a = 1.0
        if c.get("mtbf_h") and c.get("mttr_h"):
            a = c["mtbf_h"] / (c["mtbf_h"] + c["mttr_h"])
        if c.get("pm_interval_h") and c.get("pm_duration_h"):
            a *= 1 - c["pm_duration_h"] / (c["pm_interval_h"] + c["pm_duration_h"])
        return a

    lb = {}
    tt = spec["test_times"]
    for name in active_stations(spec["mode"]):
        c = st[name]
        if name == "test":
            load = sum(
                dem[f] * (2 - c["first_pass_yield"][f])
                * (c["handling_min"] + tt["frames"][f]["routine_min"])
                + dem[f] * c["type_test_share"] * tt["frames"][f]["type_test_extra_min"]
                for f in FRAMES)
        elif name == "repair":
            load = sum(dem[f] * (1 - st["test"]["first_pass_yield"][f]) * c["times_min"][f] for f in FRAMES)
        else:
            load = sum(dem[f] * c["times_min"][f] for f in FRAMES)
        lb[name] = max(1, math.ceil(load / (day * avail(c)) - 1e-9))
    imp = spec["impregnation"]
    slots = 2 * sum(dem[f] * imp["slots"][f] for f in FRAMES)
    per_oven = imp["capacity_slots"] * day / imp["cycle_min"] * avail(imp)
    lb["impregnation"] = max(1, math.ceil(slots / per_oven - 1e-9))
    agv = spec["agv"]
    d = make_distance_matrix(agv["distance_m"])
    legs = [("stator_winding", "impregnation"), ("rotor_winding", "impregnation"),
            ("impregnation", "assembly"), ("impregnation", "assembly"),
            ("assembly", "test"), ("test", "packing"), ("packing", "shipping")]
    per_unit = sum(d[a][b] / agv["speed_m_per_min"] + agv["handling_min"] for a, b in legs)
    active = sum(dem.values()) * per_unit
    with_charge = active * (1 + agv["charge_min"] / agv["battery_drive_min"])
    lb["agv"] = max(1, math.ceil(with_charge / day - 1e-9))
    return {k: lb[k] for k in resource_keys(spec["mode"])}


def _brief(s: dict) -> dict:
    return {
        "resources": dict(s["resources"]),
        "service_level": s["service_level"],
        "throughput_per_day": s["throughput_per_day"]["mean"],
        "bottleneck": s["bottleneck"],
    }


def search(cfg: dict, scenario: str, runner: Callable[[dict], list[dict]], quick: bool = False,
           log: Callable[[str], None] = print) -> dict:
    """Smallest resource set that meets the service target.

    1. Start at the capacity lower bound.
    2. Grow: while the target is missed, add one server to the bottleneck
       (highest mean utilisation).
    3. Prune: try removing one server from each resource that is above its lower
       bound, least utilised first; keep every removal that still meets the target.
       Repeat until no removal works.

    The result is minimal one resource at a time (no single server can be taken
    away); it is not proven to be the global minimum.
    """
    target = cfg["run"]["service_target"]
    cache: dict[tuple, dict] = {}
    history: list[dict] = []

    def evaluate(res: dict) -> dict:
        key = tuple(sorted(res.items()))
        if key not in cache:
            spec = resolve(cfg, scenario, res, quick=quick)
            s = summarise(runner(spec))
            s["meets_target"] = s["service_level"]["lo"] >= target
            cache[key] = s
            h = _brief(s)
            h["meets_target"] = s["meets_target"]
            history.append(h)
            sl = s["service_level"]
            log(f"  [{scenario}] {_fmt_res(res)}  service {sl['mean']:.3f} "
                f"(lo {sl['lo']:.3f})  {'PASS' if s['meets_target'] else 'fail'}  "
                f"bottleneck {s['bottleneck']}")
        return cache[key]

    lb = lower_bound(cfg, scenario)
    res = dict(lb)
    for _ in range(100):
        s = evaluate(res)
        if s["meets_target"]:
            break
        res[s["bottleneck"]] += 1
    else:
        raise RuntimeError(f"{scenario}: no feasible configuration found in 100 steps")

    changed = True
    while changed:
        changed = False
        util = evaluate(res)["util"]
        for k in sorted(res, key=lambda name: util[name]["util"]):
            if res[k] > lb[k]:
                trial = dict(res)
                trial[k] -= 1
                if evaluate(trial)["meets_target"]:
                    res = trial
                    changed = True
                    break
    final = evaluate(res)
    return {
        "scenario": scenario,
        "service_target": target,
        "lower_bound": lb,
        "minimum": res,
        "evaluations": len(history),
        "history": history,
        "final": {k: v for k, v in final.items() if k not in ("weekly_shipped", "weekly_released")},
    }


def _fmt_res(res: dict) -> str:
    short = {"stator_winding": "SW", "rotor_winding": "RW", "impregnation": "OV",
             "manual_assembly": "MA", "robot_cell": "RC", "fine_work": "FW",
             "test": "TB", "repair": "RP", "packing": "PK", "agv": "AGV"}
    return " ".join(f"{short.get(k, k)}={v}" for k, v in res.items())
