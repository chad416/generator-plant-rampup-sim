"""Full study: current vs minimum resources, hiring ramp, plots and summary tables."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .config import resolve  # noqa: E402
from .experiment import run_reps, summarise  # noqa: E402

SCENARIOS = ("1x", "2x", "3x")
RESOURCE_ORDER = ("stator_winding", "rotor_winding", "impregnation", "manual_assembly", "robot_cell",
                  "fine_work", "test", "repair", "packing", "agv")
LABEL = {
    "stator_winding": "Stator winders", "rotor_winding": "Rotor winders",
    "impregnation": "Impregnation ovens", "manual_assembly": "Manual assembly lines",
    "robot_cell": "Robot assembly cells", "fine_work": "Fine-work places",
    "test": "Test benches", "repair": "Repair places", "packing": "Packing stations", "agv": "AGVs",
}
# Reference categorical palette (validated order), plus neutrals.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def _style():
    plt.rcParams.update({
        "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
        "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True,
        "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False,
        "axes.spines.right": False, "font.size": 10, "axes.titleweight": "bold",
        "legend.frameon": False,
    })


def _strip(s: dict) -> dict:
    return {k: v for k, v in s.items() if k != "lead_times_days"}


def run_study(cfg: dict, search_result: dict, executor, quick: bool, out: Path,
              log=print) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    study: dict = {"quick": quick, "test_times_source": cfg["_test_times"]["source"], "scenarios": {}, "ramp": {}}
    for sc in SCENARIOS:
        if sc not in search_result:
            continue
        cur = summarise(run_reps(resolve(cfg, sc, quick=quick), executor), keep_lead_times=True)
        mn = summarise(run_reps(resolve(cfg, sc, search_result[sc]["minimum"], quick=quick), executor),
                       keep_lead_times=True)
        study["scenarios"][sc] = {"current": cur, "minimum": mn}
        log(f"  {sc}: current {cur['throughput_per_day']['mean']:.1f}/day, "
            f"minimum {mn['throughput_per_day']['mean']:.1f}/day (demand {mn['demand_per_day']:.0f})")
    for sc in ("2x", "3x"):
        if sc not in search_result:
            continue
        res = search_result[sc]["minimum"]
        spec_new = resolve(cfg, sc, res, ramp=True, quick=quick)
        spec_trained = resolve(cfg, sc, res, ramp=True, quick=quick)
        spec_trained["p_new"] = {}
        new = summarise(run_reps(spec_new, executor))
        trained = summarise(run_reps(spec_trained, executor))
        r = {"p_new": spec_new["p_new"], "new_hires": _ramp_metrics(new), "trained": _ramp_metrics(trained)}
        r["lost_output"] = r["trained"]["shipped_total"] - r["new_hires"]["shipped_total"]
        r["lost_output_days"] = r["lost_output"] / new["demand_per_day"]
        study["ramp"][sc] = r
        log(f"  ramp {sc}: new-hire share {spec_new['p_new']}")
    study["runtime_s"] = time.time() - t0
    return study


def _ramp_metrics(s: dict) -> dict:
    """Weekly output during the ramp. Open orders = released so far - shipped so far."""
    weekly = s["weekly_shipped"]
    dem = s["weekly_demand"]
    open_orders = np.cumsum(s["weekly_released"]) - np.cumsum(weekly)
    ok = [w >= 0.95 * dem for w in weekly]
    first_ok = None
    for i in range(len(ok)):
        if all(ok[i:]):
            first_ok = i + 1
            break
    return {
        "weekly_shipped": weekly,
        "weekly_demand": dem,
        "shipped_total": float(sum(weekly)),
        "open_orders": open_orders.tolist(),
        "peak_open_orders": float(open_orders.max()),
        "peak_open_week": int(open_orders.argmax()) + 1,
        "final_open_orders": float(open_orders[-1]),
        "first_week_steady_95": first_ok,
    }


# ------------------------------------------------------------------- plots
def plot_all(study: dict, cfg: dict, out: Path) -> list[Path]:
    _style()
    return [_plot_throughput(study, out), _plot_heatmap(study, out),
            _plot_lead_time(study, cfg, out), _plot_ramp(study, cfg, out)]


def _plot_throughput(study: dict, out: Path) -> Path:
    scs = list(study["scenarios"])
    x = np.arange(len(scs))
    w = 0.26
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    dem = [study["scenarios"][s]["minimum"]["demand_per_day"] for s in scs]
    ax.bar(x - w, dem, w - 0.02, color="#b9b8b2", label="Demand", zorder=3)
    for off, key, color, label in ((0, "current", ORANGE, "Current resources"),
                                   (w, "minimum", BLUE, "Minimum resources (search)")):
        m = [study["scenarios"][s][key]["throughput_per_day"]["mean"] for s in scs]
        h = [study["scenarios"][s][key]["throughput_per_day"]["half"] for s in scs]
        ax.bar(x + off, m, w - 0.02, color=color, label=label, zorder=3,
               yerr=[0 if math.isnan(v) else v for v in h], ecolor=INK, capsize=3)
        for xi, v in zip(x + off, m):
            ax.text(xi, v + 1.2, f"{v:.1f}", ha="center", va="bottom", fontsize=8, color=INK)
    for xi, v in zip(x - w, dem):
        ax.text(xi, v + 1.2, f"{v:.0f}", ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks(x, [f"{s} demand" for s in scs])
    ax.set_ylabel("Units shipped per working day")
    ax.set_title("Throughput against demand (mean, 95 % CI)")
    ax.set_ylim(0, max(dem) * 1.18)
    ax.legend(loc="upper left")
    fig.tight_layout()
    p = out / "throughput_vs_demand.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p


def _plot_heatmap(study: dict, out: Path) -> Path:
    cols, data, counts = [], [], []
    for sc, both in study["scenarios"].items():
        for key in ("current", "minimum"):
            s = both[key]
            cols.append(f"{sc}\n{key}")
            data.append([s["util"][r]["util"] if r in s["util"] else np.nan for r in RESOURCE_ORDER])
            counts.append([s["resources"].get(r) for r in RESOURCE_ORDER])
    m = np.array(data).T
    fig, ax = plt.subplots(figsize=(8.2, 5.4))
    cmap = plt.get_cmap("Blues").copy()
    cmap.set_bad("#f1f0ec")
    im = ax.imshow(np.ma.masked_invalid(m), cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i, r in enumerate(RESOURCE_ORDER):
        for j in range(len(cols)):
            v = m[i, j]
            if np.isnan(v):
                ax.text(j, i, "not used", ha="center", va="center", fontsize=7, color=MUTED)
                continue
            ax.text(j, i, f"{v * 100:.0f} %\n({counts[j][i]})", ha="center", va="center", fontsize=7.5,
                    color="white" if v > 0.6 else INK)
    ax.set_xticks(range(len(cols)), cols)
    ax.set_yticks(range(len(RESOURCE_ORDER)), [LABEL[r] for r in RESOURCE_ORDER])
    ax.grid(False)
    ax.set_title("Utilisation by resource (busy + down; ovens: slot use)\n(number of servers in brackets)")
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("Utilisation")
    fig.tight_layout()
    p = out / "utilisation_heatmap.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p


def _plot_lead_time(study: dict, cfg: dict, out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    for sc, color in zip(study["scenarios"], (BLUE, ORANGE, AQUA)):
        lt = np.sort(np.array(study["scenarios"][sc]["minimum"].get("lead_times_days", [])))
        if lt.size == 0:
            continue
        y = np.arange(1, lt.size + 1) / lt.size
        ax.step(lt, y, where="post", color=color, lw=2, label=f"{sc}, minimum resources")
    due = cfg["due_days"]
    ax.axvline(due, color=INK, lw=1, ls="--")
    ax.text(due, 0.55, f"quoted lead time {due} days ", color=INK, fontsize=8, ha="right")
    ax.set_xlabel("Lead time, release to shipping (working days)")
    ax.set_ylabel("Share of units shipped within")
    ax.set_title("Lead-time distribution (all replications pooled)")
    ax.set_xlim(0, due * 1.25)
    ax.set_ylim(0, 1.01)
    ax.legend(loc="lower right")
    fig.tight_layout()
    p = out / "lead_time_distribution.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p


def _plot_ramp(study: dict, cfg: dict, out: Path) -> Path:
    scs = list(study["ramp"])
    fig, axes = plt.subplots(1, len(scs), figsize=(5.2 * len(scs), 4.0), sharey=False, squeeze=False)
    lc = cfg["learning"]
    for ax, sc in zip(axes[0], scs):
        r = study["ramp"][sc]
        weeks = np.arange(1, len(r["new_hires"]["weekly_shipped"]) + 1)
        ax.plot(weeks, r["trained"]["weekly_shipped"], color=BLUE, lw=2, marker="o", ms=4,
                label="Fully trained staff")
        ax.plot(weeks, r["new_hires"]["weekly_shipped"], color=ORANGE, lw=2, marker="o", ms=4,
                label="New hires on added stations")
        ax.axhline(r["new_hires"]["weekly_demand"], color=INK, lw=1, ls="--", label="Weekly demand")
        ax.axvline(lc["weeks_to_full"], color=MUTED, lw=1, ls=":")
        ax.text(lc["weeks_to_full"], ax.get_ylim()[0], " learning done", color=MUTED, fontsize=8,
                va="bottom")
        ax.set_title(f"{sc} demand, minimum resources")
        ax.set_xlabel("Week after demand step and hiring")
        ax.set_ylabel("Units shipped per week")
    axes[0][0].legend(loc="lower right")
    fig.suptitle(f"Hiring ramp: new hires start at {lc['start_speed'] * 100:.0f} % speed, "
                 f"100 % after {lc['weeks_to_full']} weeks", fontweight="bold")
    fig.tight_layout()
    p = out / "learning_ramp.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p


# ------------------------------------------------------------------- tables
def _pct(ci: dict) -> str:
    if math.isnan(ci["half"]):
        return f"{ci['mean'] * 100:.1f} %"
    return f"{ci['mean'] * 100:.1f} % ± {ci['half'] * 100:.1f}"


def _num(ci: dict, nd: int = 1) -> str:
    if math.isnan(ci["half"]):
        return f"{ci['mean']:.{nd}f}"
    return f"{ci['mean']:.{nd}f} ± {ci['half']:.{nd}f}"


def summary_markdown(study: dict, search_result: dict) -> str:
    lines = ["# Results summary", "",
             f"Generated by `python -m rampup plots`{' --quick' if study['quick'] else ''}. "
             f"Test times source: `{study['test_times_source']}`.", "",
             "## Scenarios", "",
             "| Scenario | Resources | Demand / day | Shipped / day | On-time share | Mean lead time (days) "
             "| Mean WIP (units) | Bottleneck | Longest queue |",
             "|---|---|---|---|---|---|---|---|---|"]
    for sc, both in study["scenarios"].items():
        for key in ("current", "minimum"):
            s = both[key]
            lines.append(
                f"| {sc} | {key} | {s['demand_per_day']:.0f} | {_num(s['throughput_per_day'])} | "
                f"{_pct(s['service_level'])} | {_num(s['lead_time_mean_days'], 2)} | "
                f"{_num(s['wip_mean'], 0)} | {s['bottleneck']} ({s['util'][s['bottleneck']]['util'] * 100:.0f} %) | "
                f"{s['longest_queue']} |")
    lines += ["", "± is the 95 % confidence half-width over replications.", "",
              "## Minimum resources (search result)", "",
              "| Resource | " + " | ".join(f"{sc} current | {sc} minimum" for sc in study["scenarios"]) + " |",
              "|---|" + "---|---|" * len(study["scenarios"])]
    for r in RESOURCE_ORDER:
        row = [LABEL[r]]
        for sc, both in study["scenarios"].items():
            row += [str(both["current"]["resources"].get(r, "-")), str(both["minimum"]["resources"].get(r, "-"))]
        lines.append("| " + " | ".join(row) + " |")
    row = ["Direct operators (3 shifts)"]
    for sc, both in study["scenarios"].items():
        row += [str(both["current"]["operators_3_shifts"]), str(both["minimum"]["operators_3_shifts"])]
    lines.append("| " + " | ".join(row) + " |")
    lines += ["", "| Scenario | Search evaluations | Capacity lower bound |", "|---|---|---|"]
    for sc, sr in search_result.items():
        lb = ", ".join(f"{k} {v}" for k, v in sr["lower_bound"].items())
        lines.append(f"| {sc} | {sr['evaluations']} | {lb} |")
    if study["ramp"]:
        weeks = len(next(iter(study["ramp"].values()))["trained"]["weekly_shipped"])
        lines += ["", f"## Hiring ramp ({weeks} weeks, minimum resources)", "",
                  "| Scenario | Staff | Shipped in ramp | Peak open orders (week) | Open orders at end | "
                  "Output >= 95 % of demand from week |", "|---|---|---|---|---|---|"]
        for sc, r in study["ramp"].items():
            for key, label in (("trained", "fully trained"), ("new_hires", "new hires")):
                m = r[key]
                lines.append(f"| {sc} | {label} | {m['shipped_total']:.0f} | {m['peak_open_orders']:.0f} "
                             f"({m['peak_open_week']}) | {m['final_open_orders']:.0f} | {m['first_week_steady_95']} |")
        lines += [""]
        for sc, r in study["ramp"].items():
            lines.append(f"- {sc}: output lost to the learning curve {r['lost_output']:.0f} units "
                         f"({r['lost_output_days']:.1f} days of demand).")
        lines += ["", "New-hire share per station (new servers / all servers):", ""]
        for sc, r in study["ramp"].items():
            share = ", ".join(f"{k} {v * 100:.0f} %" for k, v in r["p_new"].items() if v > 0)
            lines.append(f"- {sc}: {share}")
    lines += ["", f"Study runtime: {study['runtime_s']:.0f} s.", ""]
    return "\n".join(lines)


def write_outputs(study: dict, search_result: dict, cfg: dict, out: Path) -> list[Path]:
    pngs = plot_all(study, cfg, out)
    slim = {"quick": study["quick"], "test_times_source": study["test_times_source"],
            "runtime_s": study["runtime_s"], "ramp": study["ramp"],
            "scenarios": {sc: {k: _strip(v) for k, v in both.items()} for sc, both in study["scenarios"].items()}}
    (out / "summary.json").write_text(json.dumps(slim, indent=1), encoding="utf-8")
    (out / "summary.md").write_text(summary_markdown(study, search_result), encoding="utf-8")
    return pngs
