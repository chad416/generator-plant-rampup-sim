# Traceability: requirement → test

Requirements are in [SPEC.md](../SPEC.md). Test files are in `tests/`.

| Req | Test or evidence |
|---|---|
| F01 | `test_plant.py::test_stable_plant_meets_demand` (all three frames released and shipped), `results/summary.json` (`throughput_by_frame`) |
| F02 | `test_plant.py::test_conservation`, `test_plant.py::test_littles_law` (every released unit passes the full route or is counted as WIP) |
| F03 | `test_oven.py` (all 8 tests) |
| F04 | `test_plant.py::test_littles_law_at_3x` (robot mode), `test_plant.py::test_stable_plant_meets_demand` (manual mode) |
| F05 | `test_plant.py::test_default_test_times_file_loads`, `test_sister_project_file_shape_is_accepted`, `test_malformed_test_times_rejected` (3 cases), `test_longer_test_times_load_the_benches_more` |
| F06 | `test_plant.py::test_littles_law_at_3x` (3 AGVs carry 90 units a day); AGV utilisation in `results/summary.md` |
| F07 | `rampup/config.py::day_minutes`; weekly demand in `results/summary.json` (`weekly_demand` = 5 × daily demand) |
| F08 | `test_learning.py` (all 4 tests) |
| F09 | `test_queueing.py` (deterministic and exponential), breakdown time in `results/summary.json` (`down`) |
| F10 | `test_plant.py::test_observed_first_pass_yield_matches_input` |
| F11 | `test_plant.py::test_overloaded_plant_is_capped_by_its_bottleneck`, `test_cli_run_quick` |
| F12 | `test_plant.py::test_below_capacity_bound_cannot_keep_up`; `results/search.json` (history of every evaluation) |
| F13 | `results/*.png`; CI step "Smoke search and plots" |
| F14 | `test_plant.py::test_cli_run_quick`; CI steps "Smoke run" and "Smoke search and plots" |
| F15 | `config/base.yaml`, `.gitignore`, `config/private/.gitignore` |
| P01 | `test_plant.py::test_littles_law`, `test_littles_law_at_3x` |
| P02 | `test_plant.py::test_conservation` (stable 1× and overloaded 2×) |
| P03 | `test_queueing.py::test_dd1_saturated_throughput_is_one_over_service_time`, `test_dd1_underloaded_has_no_wait_and_exact_utilisation` |
| P04 | `test_queueing.py::test_mmc_mean_wait_matches_erlang_c`, `test_erlang_c_known_value` |
| P05 | `test_oven.py` |
| P06 | `test_learning.py::test_learning_curve_end_points_and_shape`, `test_station_speed_blends_new_and_trained_staff` |
| P07 | `test_plant.py::test_same_seed_same_result` |
| P08 | `test_plant.py::test_observed_first_pass_yield_matches_input` |
| P09 | `test_plant.py::test_below_capacity_bound_cannot_keep_up` |
| P10 | Runtimes in `results/search_meta.json` and `results/summary.md`; CI job time |
| P11 | README tables are copied from `results/summary.md` |
| P12 | Manual check before each commit (`git grep -i` for the excluded names) |
