"""Monte Carlo stress testing for buffer-logistics operations.

A single stochastic run answers "what happened in one future". The demo needs
"what is likely to happen, and how bad can it get" - so every scenario is
replicated across many seeded futures and summarised into distribution
statistics.

Stdlib only, and the simulator import is deliberately tolerant of a flat
layout, because this module is also uploaded into a Daytona sandbox where the
files sit side by side rather than inside the `app` / `reference` packages.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Iterable

try:  # normal repo layout
    from reference.buffer_logistics import derive_seed, simulate, validate_result
except ImportError:  # flat layout inside a Daytona sandbox
    from buffer_logistics import derive_seed, simulate, validate_result  # type: ignore

#: Default number of stochastic futures per scenario.
DEFAULT_N_RUNS = 200

#: Default root seed for the demo. Fixed so the demo is reproducible.
DEFAULT_BASE_SEED = 20260830

#: A run "fails" when the operation lost *any* production to curtailment.
#: Stated explicitly rather than left implicit: `failure_probability` is the
#: share of futures in which the plant had to curtail at all.
FAILURE_THRESHOLD_T = 1e-6

#: Metrics summarised across runs. Anything not listed is dropped, to keep the
#: payload small enough to ship back from a sandbox and into the frontend.
AGGREGATED_METRICS: tuple[str, ...] = (
    "lost_production_t",
    "lost_production_pct",
    "total_production_t",
    "potential_production_t",
    "collected_t",
    "final_storage_t",
    "mean_storage_utilisation",
    "max_storage_utilisation",
    "curtailment_episodes",
    "curtailment_hours",
    "collections_completed",
    "collections_missed",
    "collections_delayed",
)


# ---------------------------------------------------------------------------
# Statistics (no numpy: this has to run in a bare sandbox)
# ---------------------------------------------------------------------------

def percentile(values: Iterable[float], q: float) -> float:
    """Linear-interpolated percentile, `q` in [0, 100]. Matches numpy's default."""
    data = sorted(values)
    if not data:
        raise ValueError("percentile of an empty sample")
    if len(data) == 1:
        return float(data[0])
    pos = (len(data) - 1) * (q / 100.0)
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return float(data[int(pos)])
    return float(data[low] + (data[high] - data[low]) * (pos - low))


def summarise(values: list[float]) -> dict[str, float]:
    """Mean / spread / tail summary of one metric across runs."""
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
    return {
        "mean": mean,
        "std": math.sqrt(variance),
        "min": min(values),
        "p05": percentile(values, 5),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "max": max(values),
    }


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def rollout_seed(base_seed: int, run_index: int) -> int:
    """Seed for rollout `run_index`.

    Depends on `(base_seed, run_index)` **only** - never on the config. That is
    what makes common random numbers work across scenarios: rollout 42 of the
    baseline and rollout 42 of "+1 tank" are the same underlying future.
    """
    return derive_seed(base_seed, "rollout", run_index)


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------

def run_monte_carlo(
    config: dict[str, Any],
    n_runs: int = DEFAULT_N_RUNS,
    base_seed: int = DEFAULT_BASE_SEED,
    name: str = "scenario",
    validate: bool = True,
    simulate_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Replicate `config` across `n_runs` seeded futures and summarise them.

    Timeseries recording is forced off: the rollouts only feed statistics, and
    keeping 200 x 4320 rows would dominate both runtime and payload size. Use
    :func:`representative_run` for the one trace the UI plots.

    Returns:
        ``{"name", "n_runs", "base_seed", "stats", "failure_probability",
           "runs", "runtime_seconds", ...}`` where ``stats`` maps each metric in
        :data:`AGGREGATED_METRICS` to a mean/std/percentile summary and ``runs``
        holds the per-run values (kept for histograms and for auditing).
    """
    if n_runs < 1:
        raise ValueError(f"n_runs must be >= 1, got {n_runs}")
    sim = simulate_fn or simulate

    mc_config = dict(config)
    mc_config["record_timeseries"] = False

    started = time.perf_counter()
    samples: dict[str, list[float]] = {k: [] for k in AGGREGATED_METRICS}
    seeds: list[int] = []
    failures = 0

    for i in range(n_runs):
        seed = rollout_seed(base_seed, i)
        seeds.append(seed)
        result = sim(mc_config, seed)
        if validate:
            validate_result(result)
        metrics = result["metrics"]
        for key in AGGREGATED_METRICS:
            samples[key].append(float(metrics[key]))
        if metrics["lost_production_t"] > FAILURE_THRESHOLD_T:
            failures += 1

    runtime = time.perf_counter() - started

    return {
        "name": name,
        "n_runs": n_runs,
        "base_seed": base_seed,
        "config": mc_config,
        "stats": {key: summarise(values) for key, values in samples.items()},
        "failure_probability": failures / n_runs,
        "failure_definition": (
            f"lost_production_t > {FAILURE_THRESHOLD_T} t in a run "
            "(the operation had to curtail production at all)"
        ),
        "runs": {key: samples[key] for key in ("lost_production_t", "max_storage_utilisation")},
        "seeds": seeds,
        "runtime_seconds": runtime,
    }


def representative_run(
    config: dict[str, Any],
    base_seed: int = DEFAULT_BASE_SEED,
    run_index: int = 0,
    timeseries_stride: int = 6,
    simulate_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One fully-recorded rollout, for plotting.

    Uses the *same* seed as rollout `run_index` of the Monte Carlo batch, so the
    trace the user sees is genuinely one of the futures that was counted in the
    statistics - not a separate run drawn from nowhere.
    """
    sim = simulate_fn or simulate
    cfg = dict(config)
    cfg["record_timeseries"] = True
    cfg["timeseries_stride"] = timeseries_stride
    result = sim(cfg, rollout_seed(base_seed, run_index))
    validate_result(result)
    return result


def headline(mc: dict[str, Any]) -> dict[str, float]:
    """The four numbers the demo actually shows for a scenario."""
    return {
        "expected_lost_production_t": mc["stats"]["lost_production_t"]["mean"],
        "p95_lost_production_t": mc["stats"]["lost_production_t"]["p95"],
        "failure_probability": mc["failure_probability"],
        "expected_production_t": mc["stats"]["total_production_t"]["mean"],
    }
