# Changelog

## 0.1.0 (2026-11-09)

First version.

- SimPy model of a plant building low-voltage synchronous alternators in three frame sizes: stator and rotor winding, batch impregnation, manual or robot assembly, routine test with repair loop, packing, AGV transport.
- 3-shift, 5-day calendar; learning curve for new hires; lognormal, triangular, exponential or deterministic times; breakdowns; first-pass yield; Poisson daily order quantities.
- Routine test times read from `data/test_times.json`, produced by alternator-routine-test-station v0.1.0: the PLC sequence plus per-frame handling (`handling_s` replaces the config handling time when present).
- Minimum-resource search for 1×, 2× and 3× demand with 10 replications and a 95 % CI on the on-time share.
- Plots: throughput against demand, utilisation heat map, lead-time distribution, hiring ramp.
- Tests: Little's law, conservation, D/D/1, M/M/3 against Erlang C, batch oven, learning curve, seeds, test-time file interface, CLI.
- CI on Ubuntu 24.04, Python 3.12, with a `--quick` smoke run.
