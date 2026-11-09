"""Whole-plant checks: Little's law, conservation, seeds, test-time interface, CLI."""

import json
import math

import pytest

from rampup.__main__ import main
from rampup.config import ROOT, load_config, load_test_times, resolve
from rampup.experiment import lower_bound
from rampup.model import Plant


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def run_1x(cfg):
    return Plant(resolve(cfg, "1x"), 11).run()


def test_littles_law(run_1x):
    lit = run_1x["little"]
    # L = lambda * W over the 20-week window; edge effects only
    assert lit["L"] == pytest.approx(lit["lambda_W"], rel=0.03), lit


def test_littles_law_at_3x(cfg):
    res = {"stator_winding": 6, "rotor_winding": 3, "impregnation": 5, "robot_cell": 2,
           "fine_work": 2, "test": 5, "repair": 1, "packing": 2, "agv": 3}
    lit = Plant(resolve(cfg, "3x", res), 12).run()["little"]
    assert lit["L"] == pytest.approx(lit["lambda_W"], rel=0.03), lit


@pytest.mark.parametrize("scenario", ["1x", "2x"])   # 2x on current resources is overloaded
def test_conservation(cfg, scenario):
    r = Plant(resolve(cfg, scenario), 3).run()
    assert r["released"] == r["shipped"] + r["wip_end"]
    assert r["units_open"] == r["wip_end"]
    assert r["released"] > 0 and r["shipped"] > 0


def test_stable_plant_meets_demand(run_1x):
    assert run_1x["throughput_per_day"] == pytest.approx(run_1x["demand_per_day"], rel=0.03)
    assert run_1x["service_level"] > 0.95


def test_overloaded_plant_is_capped_by_its_bottleneck(cfg):
    r = Plant(resolve(cfg, "2x"), 3).run()
    assert r["throughput_per_day"] < 0.8 * r["demand_per_day"]
    assert r["util"][r["bottleneck"]]["util"] > 0.97
    assert r["service_level"] < 0.5


def test_same_seed_same_result(cfg):
    spec = resolve(cfg, "1x", quick=True)
    a, b = Plant(spec, 42).run(), Plant(spec, 42).run()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    c = Plant(spec, 43).run()
    assert a["lead_times_days"] != c["lead_times_days"]


def test_observed_first_pass_yield_matches_input(cfg, run_1x):
    fpy = cfg["stations"]["test"]["first_pass_yield"]
    d = cfg["demand"]
    expected = sum(fpy[f] * d[f] for f in d) / sum(d.values())
    assert run_1x["first_pass_yield"] == pytest.approx(expected, abs=0.01)


def test_below_capacity_bound_cannot_keep_up(cfg):
    lb = lower_bound(cfg, "1x")
    r = Plant(resolve(cfg, "1x", {"test": lb["test"] - 1}), 4).run()
    assert lb["test"] - 1 >= 1
    assert r["throughput_per_day"] < 0.95 * r["demand_per_day"]


# ------------------------------------------------- test_times.json interface
def test_default_test_times_file_loads():
    tt = load_test_times(ROOT / "data" / "test_times.json")
    assert tt["source"] == "placeholder"
    assert tt["frames"]["small"]["routine_min"] == pytest.approx(25.0)
    assert tt["changeover_min"] == pytest.approx(10.0)


def test_sister_project_file_shape_is_accepted(tmp_path):
    p = tmp_path / "test_times.json"
    p.write_text(json.dumps({
        "source": "alternator-routine-test-station v0.1.0",
        "frames": {f: {"routine_s": 1000 + i, "type_test_extra_s": 300}
                   for i, f in enumerate(("small", "medium", "large"))},
        "changeover_s": 450,
    }), encoding="utf-8")
    tt = load_test_times(p)
    assert tt["source"].startswith("alternator-routine-test-station")
    assert tt["frames"]["large"]["routine_min"] == pytest.approx(1002 / 60)


@pytest.mark.parametrize("bad", [
    {"frames": {}, "changeover_s": 1},
    {"source": "x", "frames": {"small": {"routine_s": 1, "type_test_extra_s": 1}}, "changeover_s": 1},
    {"source": "x", "frames": {f: {"routine_s": -1, "type_test_extra_s": 0}
                               for f in ("small", "medium", "large")}, "changeover_s": 1},
])
def test_malformed_test_times_rejected(tmp_path, bad):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError):
        load_test_times(p)


def test_longer_test_times_load_the_benches_more(cfg):
    spec = resolve(cfg, "1x", quick=True)
    base = Plant(spec, 8).run()["util"]["test"]["busy"]
    slow = resolve(cfg, "1x", quick=True)
    for f in slow["test_times"]["frames"].values():
        f["routine_min"] *= 1.5
    assert Plant(slow, 8).run()["util"]["test"]["busy"] > base + 0.1


# --------------------------------------------------------------------- CLI
def test_cli_run_quick(tmp_path, capsys):
    assert main(["run", "--scenario", "1x", "--quick", "--workers", "1", "--out", str(tmp_path)]) == 0
    out = json.loads((tmp_path / "run_1x.json").read_text(encoding="utf-8"))
    assert out["scenario"] == "1x"
    assert not math.isnan(out["throughput_per_day"]["mean"])
    assert "bottleneck" in capsys.readouterr().out
