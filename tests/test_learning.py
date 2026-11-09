"""Learning curve shape and its effect on a station."""

import pytest

from rampup.config import load_config, resolve
from rampup.model import Plant, learning_speed, station_speed


def test_learning_curve_end_points_and_shape():
    assert learning_speed(0, 0.6, 12) == pytest.approx(0.6)
    assert learning_speed(6, 0.6, 12) == pytest.approx(0.8)
    assert learning_speed(12, 0.6, 12) == pytest.approx(1.0)
    assert learning_speed(40, 0.6, 12) == pytest.approx(1.0)   # no overshoot
    assert learning_speed(-1, 0.6, 12) == pytest.approx(0.6)
    xs = [learning_speed(w / 4, 0.6, 12) for w in range(0, 80)]
    assert all(b >= a for a, b in zip(xs, xs[1:]))             # never gets slower


def test_station_speed_blends_new_and_trained_staff():
    assert station_speed(0, 0.0, 0.6, 12) == pytest.approx(1.0)
    assert station_speed(0, 1.0, 0.6, 12) == pytest.approx(0.6)
    assert station_speed(0, 0.5, 0.6, 12) == pytest.approx(0.8)
    assert station_speed(12, 0.5, 0.6, 12) == pytest.approx(1.0)


def test_new_hire_share_is_new_servers_over_all_servers():
    cfg = load_config()
    spec = resolve(cfg, "2x", {"stator_winding": 4, "test": 3}, ramp=True)
    assert spec["p_new"]["stator_winding"] == pytest.approx(0.5)
    assert spec["p_new"]["test"] == pytest.approx(1 / 3)
    assert "impregnation" not in spec["p_new"]                 # ovens have no learning curve
    assert resolve(cfg, "2x", {"stator_winding": 4})["p_new"] == {}


def test_ramp_output_is_lower_early_and_recovers():
    cfg = load_config()
    res = {"stator_winding": 6, "rotor_winding": 3, "impregnation": 4, "robot_cell": 2,
           "fine_work": 2, "test": 5, "repair": 1, "packing": 2, "agv": 3}
    spec = resolve(cfg, "3x", res, ramp=True)
    spec["run"]["ramp_weeks"] = 20
    trained = dict(spec, p_new={})
    a = Plant(spec, 5).run()["weekly_shipped"]
    b = Plant(trained, 5).run()["weekly_shipped"]
    assert sum(a[1:5]) < 0.95 * sum(b[1:5])           # weeks 2-5: new hires slow the plant
    assert sum(a[16:20]) == pytest.approx(sum(b[16:20]), rel=0.10)   # after learning: same rate
