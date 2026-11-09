"""Load assumptions and turn a scenario into a run specification."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "base.yaml"
FRAMES = ("small", "medium", "large")

COMMON_STATIONS = ("stator_winding", "rotor_winding", "test", "repair", "packing")
ASSEMBLY_STATIONS = {"manual": ("manual_assembly",), "robot": ("robot_cell", "fine_work")}


def load_test_times(path: str | Path) -> dict:
    """Read test_times.json (interface with the routine-test station project).

    Returns times in minutes: {"source", "frames": {f: {"routine_min", "type_test_extra_min"}},
    "changeover_min"}.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw.get("source"), str):
        raise ValueError(f"{path}: 'source' must be a string")
    frames = raw.get("frames")
    if not isinstance(frames, dict) or set(frames) != set(FRAMES):
        raise ValueError(f"{path}: 'frames' must have exactly {FRAMES}")
    out = {"source": raw["source"], "frames": {}}
    for f in FRAMES:
        entry = frames[f]
        for key in ("routine_s", "type_test_extra_s"):
            v = entry.get(key)
            if not isinstance(v, (int, float)) or v < 0 or math.isnan(v):
                raise ValueError(f"{path}: frames.{f}.{key} must be a number >= 0")
        out["frames"][f] = {
            "routine_min": entry["routine_s"] / 60.0,
            "type_test_extra_min": entry["type_test_extra_s"] / 60.0,
        }
    c = raw.get("changeover_s")
    if not isinstance(c, (int, float)) or c < 0:
        raise ValueError(f"{path}: 'changeover_s' must be a number >= 0")
    out["changeover_min"] = c / 60.0
    return out


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else DEFAULT_CONFIG
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    tt = Path(cfg["test_times_file"])
    if not tt.is_absolute():
        tt = ROOT / tt
    cfg["_test_times"] = load_test_times(tt)
    return cfg


def day_minutes(cfg: dict) -> float:
    cal = cfg["calendar"]
    return cal["shifts_per_day"] * cal["shift_hours"] * 60.0


def week_minutes(cfg: dict) -> float:
    return day_minutes(cfg) * cfg["calendar"]["days_per_week"]


def active_stations(mode: str) -> tuple[str, ...]:
    if mode not in ASSEMBLY_STATIONS:
        raise ValueError(f"assembly mode must be one of {tuple(ASSEMBLY_STATIONS)}")
    return COMMON_STATIONS[:2] + ASSEMBLY_STATIONS[mode] + COMMON_STATIONS[2:]


def resource_keys(mode: str) -> tuple[str, ...]:
    """Resources that can be sized: every active station, the ovens and the AGVs."""
    s = active_stations(mode)
    return s[:2] + ("impregnation",) + s[2:] + ("agv",)


def current_resources(cfg: dict, mode: str) -> dict:
    res = {name: cfg["stations"][name]["servers"] for name in active_stations(mode)}
    res["impregnation"] = cfg["impregnation"]["ovens"]
    res["agv"] = cfg["agv"]["fleet"]
    return {k: res[k] for k in resource_keys(mode)}


def resolve(cfg: dict, scenario: str, resources: dict | None = None, ramp: bool = False,
            quick: bool = False) -> dict:
    """Build the plain-dict specification that one simulation run needs.

    ramp=True: the run starts at the new demand with the given resources and the
    share of new hires per staffed station is 1 - current / new servers (new
    servers are staffed by new hires). Otherwise everyone is fully trained.
    """
    if scenario not in cfg["scenarios"]:
        raise ValueError(f"unknown scenario {scenario!r}; have {list(cfg['scenarios'])}")
    sc = cfg["scenarios"][scenario]
    mode = sc["assembly"]
    mult = float(sc["demand_mult"])
    cur = current_resources(cfg, mode)
    res = dict(cur)
    if resources:
        unknown = set(resources) - set(res)
        if unknown:
            raise ValueError(f"unknown resources {sorted(unknown)} for assembly mode {mode}")
        res.update({k: int(v) for k, v in resources.items()})
    run = copy.deepcopy(cfg["run"])
    if quick:
        run["replications"] = min(run["replications"], 3)
        run["warmup_weeks"] = 1
        run["measure_weeks"] = 4
        run["ramp_weeks"] = min(run["ramp_weeks"], 8)
    p_new = {}
    if ramp:
        for name in active_stations(mode):
            if cfg["stations"][name].get("staffed"):
                p_new[name] = max(0.0, 1.0 - cur[name] / res[name])
    return {
        "scenario": scenario,
        "mode": mode,
        "demand_mult": mult,
        "demand": {f: cfg["demand"][f] * mult for f in FRAMES},
        "resources": res,
        "calendar": copy.deepcopy(cfg["calendar"]),
        "due_days": cfg["due_days"],
        "release": cfg.get("release", "poisson"),
        "run": run,
        "ramp": ramp,
        "learning": copy.deepcopy(cfg["learning"]),
        "p_new": p_new,
        "stations": copy.deepcopy(cfg["stations"]),
        "impregnation": copy.deepcopy(cfg["impregnation"]),
        "agv": copy.deepcopy(cfg["agv"]),
        "test_times": copy.deepcopy(cfg["_test_times"]),
    }
