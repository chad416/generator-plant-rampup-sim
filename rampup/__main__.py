"""Command line: run one scenario, search minimum resources, or make the plots.

    python -m rampup run --scenario 2x [--resources minimum] [--set test=4] [--quick]
    python -m rampup search [--scenario 1x 2x 3x] [--quick]
    python -m rampup plots [--quick]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

from . import __version__
from .config import ROOT, load_config, resolve
from .experiment import make_executor, run_reps, search, summarise


def clean(obj):
    """JSON-safe copy: NaN and infinity become null."""
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    return obj


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(obj), indent=1), encoding="utf-8")


def out_dir(args) -> Path:
    if args.out:
        return Path(args.out)
    return ROOT / "results" / ("quick" if args.quick else "")


def load_search(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"{path} not found; run `python -m rampup search` first")
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_run(args, cfg) -> int:
    res = None
    if args.resources == "minimum":
        res = dict(load_search(out_dir(args) / "search.json")[args.scenario]["minimum"])
    for item in args.set or []:
        k, _, v = item.partition("=")
        res = res or {}
        res[k] = int(v)
    spec = resolve(cfg, args.scenario, res, quick=args.quick)
    if args.reps:
        spec["run"]["replications"] = args.reps
    t0 = time.time()
    with make_executor(args.workers) as ex:
        s = summarise(run_reps(spec, ex))
    dt = time.time() - t0
    print(f"scenario {args.scenario}  assembly {spec['mode']}  replications {s['replications']}  "
          f"({dt:.1f} s)")
    print("resources: " + ", ".join(f"{k} {v}" for k, v in spec["resources"].items()))
    tp, sl = s["throughput_per_day"], s["service_level"]
    print(f"demand {s['demand_per_day']:.1f}/day   shipped {tp['mean']:.2f} ± {tp['half']:.2f}/day   "
          f"on-time {sl['mean'] * 100:.1f} % (95 % CI {sl['lo'] * 100:.1f}-{sl['hi'] * 100:.1f})")
    print(f"lead time mean {s['lead_time_mean_days']['mean']:.2f} days, p95 {s['lead_time_days']['p95']:.2f}; "
          f"WIP mean {s['wip_mean']['mean']:.1f} units")
    print(f"{'resource':<18}{'servers':>8}{'busy':>8}{'down':>8}{'util':>8}{'queue':>8}{'wait min':>10}")
    for name, u in s["util"].items():
        print(f"{name:<18}{u['servers']:>8.0f}{u['busy'] * 100:>7.1f}%{(u['down'] + u['pm']) * 100:>7.1f}%"
              f"{u['util'] * 100:>7.1f}%{u['queue']:>8.2f}{u['wait_min']:>10.1f}")
    print(f"bottleneck: {s['bottleneck']}   longest queue: {s['longest_queue']}")
    write_json(out_dir(args) / f"run_{args.scenario}.json", s)
    if args.min_service is not None and sl["mean"] < args.min_service:
        print(f"FAIL: mean on-time share {sl['mean']:.3f} below {args.min_service}")
        return 1
    return 0


def cmd_search(args, cfg) -> int:
    t0 = time.time()
    path = out_dir(args) / "search.json"
    result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    with make_executor(args.workers) as ex:
        for sc in args.scenario:
            print(f"search {sc}")
            result[sc] = search(cfg, sc, lambda spec: run_reps(spec, ex), quick=args.quick)
            print(f"  minimum: {result[sc]['minimum']}")
    result_meta = {"runtime_s": time.time() - t0}
    write_json(path, result)
    write_json(out_dir(args) / "search_meta.json", result_meta)
    print(f"search done in {result_meta['runtime_s']:.0f} s -> {path}")
    return 0


def cmd_plots(args, cfg) -> int:
    from .report import run_study, write_outputs

    out = out_dir(args)
    sr = load_search(out / "search.json")
    with make_executor(args.workers) as ex:
        study = run_study(cfg, sr, ex, args.quick, out)
    pngs = write_outputs(clean(study), sr, cfg, out)
    for p in pngs:
        print(f"wrote {p}")
    print(f"wrote {out / 'summary.md'} ({study['runtime_s']:.0f} s)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rampup", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--config", help="YAML file (default config/base.yaml)")
        p.add_argument("--quick", action="store_true", help="few replications, short run (CI smoke)")
        p.add_argument("--workers", type=int, help="parallel processes (default min(12, CPUs))")
        p.add_argument("--out", help="output folder (default results/, or results/quick/ with --quick)")

    p = sub.add_parser("run", help="simulate one scenario")
    common(p)
    p.add_argument("--scenario", required=True)
    p.add_argument("--resources", choices=("current", "minimum"), default="current")
    p.add_argument("--set", action="append", metavar="NAME=N", help="override one resource count")
    p.add_argument("--reps", type=int, help="number of replications")
    p.add_argument("--min-service", type=float, help="exit 1 if the mean on-time share is lower")

    p = sub.add_parser("search", help="minimum resources per scenario")
    common(p)
    p.add_argument("--scenario", nargs="+", default=["1x", "2x", "3x"])

    p = sub.add_parser("plots", help="current vs minimum, hiring ramp, plots, summary tables")
    common(p)

    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    return {"run": cmd_run, "search": cmd_search, "plots": cmd_plots}[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
