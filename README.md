# Ramp-up simulation of an alternator plant

[![ci](https://github.com/chad416/generator-plant-rampup-sim/actions/workflows/ci.yml/badge.svg)](https://github.com/chad416/generator-plant-rampup-sim/actions/workflows/ci.yml)

A discrete-event model (Python, SimPy) of a mid-size plant building low-voltage synchronous alternators in three frame sizes. It asks what happens when demand goes to 2× and 3×:

- where the plant stops keeping up;
- the fewest winders, ovens, test benches, AGVs and other stations that still ship on time;
- how much output a hiring wave costs while new people learn the job.

**Every input is an assumption, not plant data.** The numbers in `config/base.yaml` are plausible round values, each with a comment. The test-bench times come from the sister project [alternator-routine-test-station](https://github.com/chad416/alternator-routine-test-station), which is itself a simulation. The results show how the plant behaves under *these* assumptions. See [Limits](#limits).

![throughput against demand](results/throughput_vs_demand.png)

## The model

Each order is one alternator: small, medium or large frame. Daily order quantities are Poisson around 20 small, 6 medium and 4 large at 1× demand.

1. **Stator winding and rotor winding** run in parallel on separate winders, with times per frame.
2. **Impregnation** is a batch oven (VPI and cure).
   - Each oven holds 12 slots: a small part takes 1, a medium 2, a large 3.
   - The cycle is fixed at 240 min.
   - A batch starts when the oven is full, or when the oldest part has waited 60 min.
3. **Assembly** starts when both stator and rotor have arrived. Two modes:
   - *manual*: three manual lines (today);
   - *robot*: one robot cell (short cycle, low spread, 2 h maintenance every week) followed by manual fine-work places.
4. **Routine test** on test benches.
   - Per unit: the PLC test sequence plus manual handling (mounting, coupling, wiring, removal). Both come per frame from `data/test_times.json`; see [Interface](#interface-with-the-routine-test-station).
   - A frame change on a bench costs a changeover. A free bench that last tested the same frame is preferred.
   - 2 % of units also get type-test steps.
5. Units that fail the test (first-pass yield 97 / 95 / 93 % by frame) go to **repair** and are re-tested.
6. **Packing**, then shipping.

**AGVs** move every part and unit between areas: 7 trips per unit, one load per trip.
- The nearest free AGV takes the oldest request, drives there empty, then loaded.
- Distances come from a matrix (40–260 m).
- An AGV charges for 60 min after 240 active minutes.

**Time:** 3 shifts × 7.5 h, 5 days a week. The clock counts working time only.

**Breakdowns:** every station type has an MTBF (in busy hours) and an MTTR. A failure stops a machine after the job in progress.

**People:** in a ramp run, the added stations are staffed by new hires, so a station going from 2 to 5 servers has 60 % new staff. A new hire works at 60 % speed on day one and at 100 % after 12 weeks (linear). Only the manual part of a job slows down: bench handling slows, the test sequence does not.

**Measurements:**
- 2 weeks of warm-up, then 20 weeks of measurement, 10 replications per configuration.
- A unit is **on time** if it ships within 3 working days of release.
- The **service level** is the on-time share of units released in the measurement window.

## Results

From `results/summary.md` (`python -m rampup plots`), with test times from `alternator-routine-test-station v0.1.0`. ± is the 95 % confidence half-width over 10 replications.

| Scenario | Resources | Demand / day | Shipped / day | On time | Mean lead time (days) | Mean WIP | Bottleneck |
|---|---|---|---|---|---|---|---|
| 1× | current | 30 | 30.0 ± 0.3 | 100.0 % | 0.48 | 14 | rotor winding (80 %) |
| 2× | current | 60 | 37.7 ± 0.2 | 0.0 % | 23.0 (growing) | 1391 (growing) | stator winding (100 %) |
| 2× | minimum | 60 | 59.9 ± 0.5 | 100.0 % | 0.89 | 53 | fine work (98 %) |
| 3× | current | 90 | 37.7 ± 0.2 | 0.0 % | 35.0 (growing) | 3166 (growing) | stator winding (100 %) |
| 3× | minimum | 90 | 89.1 ± 0.6 | 99.0 % ± 1.9 | 1.21 | 110 | impregnation (99 % of slots) |

"Current" at 2× and 3× means today's machines with the robot cell in place of the manual lines.

**Minimum resources** (smallest set whose lower 95 % CI bound of the on-time share is at least 95 %):

| Resource | Today | 1× | 2× | 3× |
|---|---|---|---|---|
| Stator winders | 2 | 2 | 4 | 5 |
| Rotor winders | 1 | 1 | 2 | 3 |
| Impregnation ovens (12 slots) | 2 | 2 | 3 | 4 |
| Manual assembly lines | 3 | 3 | – | – |
| Robot assembly cells | – | – | 1 | 2 |
| Fine-work places | – | – | 1 | 2 |
| Test benches | 2 | 1 | 2 | 3 |
| Repair places | 1 | 1 | 1 | 1 |
| Packing stations | 1 | 1 | 2 | 2 |
| AGVs | 2 | 1 | 2 | 3 |
| Direct operators, 3 shifts | 84 | 81 | 54 | 72 |

What the runs show:
- **Today's plant has no slack at the winders.** At 1× the rotor winder runs at 80 % and the stator winders at 77 %. One test bench and one AGV would still do at 1×, but they then run at 73 % and 96 %, and the lead time doubles to 0.99 days.
- **Winding caps output first.** With today's winders the plant ships 37.7 units a day whatever the demand. At 2× and 3× the queue and lead time grow without limit.
- **At 3× the ovens become the bottleneck.** Batches run 99 % full and parts wait longest for the oven. Four ovens just meet the target. In practice a fifth oven, or a larger one, is the first thing to add for margin.
- **One robot cell covers 2× but not 3×.** At 2× it runs at 88 %. At 3× the model needs a second cell, and the two then run at 66 %.
- **Test benches: 1, 2, 3 at 1×, 2×, 3×.** This is the same answer as the test-station project's simple capacity estimate. Handling (15–40 min per unit), not the 4–7 min test sequence, is most of the bench time.
- **AGV count stays small:** 2 at 2×, 3 at 3×, each busy or charging 94–95 % of the time at the minimum.
- **Fewer direct operators at 3× than today.** The model has 72 operators at 3× against 84 today, because the robot cell replaces 18 people per shift on the manual lines. This depends on the assumed 6 people per manual line, and counts only the modelled stations.
- **The minimum has almost no slack.** Several stations run at 90–99 %. The on-time target is met because 3 days is long compared with the 1-day lead time. The 3× lead-time p95 is 2.66 days, against 0.69 days at 1× with today's resources.

![utilisation heat map](results/utilisation_heatmap.png)

![lead-time distribution](results/lead_time_distribution.png)

### Hiring ramp

Demand steps to 2× or 3× at week 0, with the minimum resources in place. The added stations are staffed by new hires. The run is compared with the same plant fully trained (26 weeks, 10 replications):

| Scenario | Staff | Peak open orders (week) | Open orders at week 26 | Output ≥ 95 % of demand from week | Output lost to learning |
|---|---|---|---|---|---|
| 2× | fully trained | 71 (16) | 55 | 2 | – |
| 2× | new hires | 82 (26) | 82 | 2 | 18 units (0.3 days of demand) |
| 3× | fully trained | 179 (21) | 155 | 2 | – |
| 3× | new hires | 422 (9) | 224 | 8 | 38 units (0.4 days of demand) |

- **At 2× the learning curve costs almost nothing.** The 18 units are within the run-to-run spread.
- **At 3× it costs time more than output.**
  - The stator winders run at 94 % with trained staff, and 60 % of their operators are new.
  - For about seven weeks the plant falls behind: open orders peak at 422 units in week 9, more than twice the trained level.
  - Shipped output over the 26 weeks is down by only 38 units, but orders wait longer. At week 26 there are still 224 open orders, against 155 trained.
- **A ramp needs more than the steady-state minimum.** One extra stator winder during the ramp, or experienced operators moved onto the new machines, would avoid most of this.

![hiring ramp](results/learning_ramp.png)

### Checks

- **Little's law:** mean WIP against throughput × mean lead time is 14.3 against 14.3 units at 1× and 109.5 against 107.9 at 3× (minimum). The tests require agreement within 3 %.
- **Conservation:** units released = shipped + in the plant, in every test run, including the overloaded 2× run.
- **Analytic cases:**
  - a saturated deterministic station ships exactly 1 / service time;
  - an underloaded one is busy exactly arrival rate × service time;
  - an M/M/3 station at 80 % load has a mean wait inside the 95 % CI of 20 replications around the Erlang C value (1.079 min).
- **Observed first-pass yield:** 96.0 % against the 96.1 % expected from the inputs.
- **Runtime** on a 16-thread Windows PC with 12 worker processes:
  - full search 20 s (`results/search_meta.json`);
  - plots 39 s;
  - the 33 tests 19 s.

## Interface with the routine-test station

The sister project writes `data/test_times.json`. The file in this repository comes from `alternator-routine-test-station v0.1.0`:

```json
{"source": "alternator-routine-test-station v0.1.0",
 "frames": {"small": {"routine_s": 249.2, "handling_s": 900, "type_test_extra_s": 216.5}, "medium": {...}, "large": {...}},
 "changeover_s": 600}
```

- `routine_s` is the PLC test sequence, `handling_s` the manual mounting, coupling, wiring and removal.
- When the file gives `handling_s`, it replaces `stations.test.handling_min` for that frame. The learning curve and the handling spread apply to it.
- `type_test_extra_s` is 0 for the large frame, which that bench cannot load for a type test.
- Replace the file and rerun `search` and `plots`. Every summary shows which source it used. A malformed file is rejected with an error.

## Run it

Python 3.12:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
python -m pytest -q                            # 33 tests
python -m rampup run --scenario 2x             # today's resources at 2x demand
python -m rampup run --scenario 3x --resources minimum
python -m rampup run --scenario 3x --resources minimum --set impregnation=5
python -m rampup search                        # minimum resources, writes results/search.json
python -m rampup plots                         # current vs minimum, ramp, PNGs, summary.md
```

- `--quick` uses 3 replications and a 4-week window, and writes to `results/quick/` (CI uses it).
- `--config` points at another YAML file.
- Put your own scenario files in `config/private/`, which git ignores.

## How the search works

1. **Start from a capacity lower bound:** the fewest servers that keep each resource's load below 100 %. The bound ignores changeovers, empty AGV trips and repeat retests, so nothing below it can keep up. A test checks this.
2. **Evaluate the configuration** (10 replications). If the lower 95 % CI bound of the on-time share is below 95 %, add one server to the resource with the highest utilisation, and repeat.
3. **Try removing one server** from each resource that is above its lower bound, least utilised first. Keep any removal that still meets the target. Repeat until no removal works.

The result is minimal one resource at a time: no single server can be removed. It is not proven to be the global minimum. Every evaluation is listed in `results/search.json`. All configurations use the same seeds, so they are compared on the same random demand.

## Limits

- **Assumed data.** Every time, MTBF, yield, distance and demand figure is an assumption. The test times come from a simulated bench. No plant data was used. The results show the method and the shape of the problem, not a capacity plan for a real plant.
- **Working-time clock.** No weekend oven cure, no shift handover loss, no overtime, no absence.
- **Simplified AGV traffic.** No congestion, no blocked aisles, no traffic rules. Charging is time-based, and large frames ride on the same AGVs as small ones.
- **No material shortages.** Copper, laminations, housings and bearings are always available. The plant has no supplier limits and no finished-goods storage limit.
- **Breakdowns only stop a machine between jobs**, so long jobs never break mid-way. MTBF counts busy hours.
- **Learning is one straight line per station.** It is a share-weighted mix of new and trained staff, not a model of each person. Staff turnover during the ramp is not modelled.
- **The search sizes against the on-time target only.** It has no utilisation ceiling, so the minimum leaves several stations above 90 %. A real plan would add margin, as the hiring-ramp result shows.
- **Head count** covers only the modelled direct stations: no logistics, maintenance, quality or indirect staff.

## Layout

```
rampup/            model, resources (stations, batch oven, AGVs), search, report, CLI
tests/             pytest: queueing, oven, learning curve, whole plant, CLI
config/base.yaml   all assumptions, commented
config/private/    your own scenario files (git-ignored)
data/test_times.json   routine-test and handling times from the test-station project
results/           search.json, summary.json, summary.md and the plots above
SPEC.md            numbered requirements; docs/traceability.md maps them to tests
```

MIT licence.
