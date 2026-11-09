# Specification

Requirements for `generator-plant-rampup-sim` 0.1.0. F = function, P = property (accuracy, speed, honesty).
The test for each requirement is listed in [docs/traceability.md](docs/traceability.md).

## Functions

- **F01** Model three frame sizes (small, medium, large), each with its own process times at every station.
- **F02** Route every unit through stator winding and rotor winding (in parallel), impregnation of both parts, assembly (after both parts arrive), routine test, packing and shipping.
- **F03** Model impregnation as a batch process. Each oven has a capacity in slots and a fixed cycle time. A batch starts when the waiting parts fill the oven, or when the oldest waiting part has waited the fill timeout. Parts are loaded first-fit in arrival order.
- **F04** Offer two assembly modes per scenario: three manual lines, or one robot cell followed by fine-work places. The robot cell has a shorter, less variable cycle and scheduled maintenance.
- **F05** Read per-frame routine test time, type-test extra time and changeover time from `data/test_times.json` (format shared with the routine-test station project). Reject malformed files.
- **F06** Move parts and units between stations with a fleet of K AGVs. Travel time comes from a distance matrix and a speed. AGVs charge after a set active time.
- **F07** Use a calendar of 3 shifts × 7.5 h, 5 days a week. The model clock counts working time only.
- **F08** Apply a learning curve: new hires work at 60 % of trained speed, rising linearly to 100 % over W weeks. In a ramp run, the new-hire share at a staffed station is (new servers − current servers) / new servers.
- **F09** Draw process times from lognormal, triangular, exponential or deterministic distributions. Model breakdowns with MTBF/MTTR per station type.
- **F10** Apply a first-pass yield at test. Failed units go to repair and are re-tested.
- **F11** Report per scenario: throughput per day against demand, utilisation per resource, the bottleneck (highest utilisation) and the longest queue, WIP, lead time, on-time share.
- **F12** Search for the smallest resource set (all stations, ovens, AGVs) that meets the service target at 1×, 2× and 3× demand, using several replications and a 95 % confidence interval.
- **F13** Produce plots: throughput against demand (current and minimum resources), utilisation heat map, lead-time distribution, weekly output during a hiring ramp.
- **F14** Command line: `python -m rampup run --scenario 2x`, `python -m rampup search`, `python -m rampup plots`, each with `--quick`.
- **F15** Keep all assumptions in `config/base.yaml`, with a comment on each number. Keep user scenario files in a git-ignored `config/private/`.

## Properties

- **P01** Little's law holds in the model: mean WIP L equals throughput λ times mean lead time W within 3 % over a 20-week window.
- **P02** Conservation: units released = units shipped + units in the plant, in every run.
- **P03** A single deterministic station matches the analytic result: D/D/1 throughput = 1 / service time; utilisation of an underloaded D/D/1 equals arrival rate × service time.
- **P04** An M/M/3 station's mean queue wait agrees with Erlang C (the analytic value lies inside the 95 % CI of 20 replications).
- **P05** The batch oven starts full batches at once, starts part batches at the timeout, sends overflow to the next cycle or a free oven, and refuses parts larger than an oven.
- **P06** The learning curve starts at the start speed, reaches 100 % at W weeks, never decreases and never exceeds 100 %.
- **P07** The same seed gives the same result, byte for byte; a different seed gives a different result.
- **P08** The observed first-pass yield matches the configured yield within 1 percentage point.
- **P09** The capacity lower bound used by the search is a real bound: one server fewer than the bound cannot keep up with demand.
- **P10** The full search runs in under 10 minutes on a desktop PC; the CI smoke run (`--quick`) finishes in under 5 minutes.
- **P11** Every number in the README comes from a file in `results/` written by the code.
- **P12** No company or brand names in the repository.
