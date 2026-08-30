"""One call from config to decision - the integration boundary.

This is the single function the API layer (and the teammate's `main.py`) needs:

    run_decision_pipeline(...) -> {"baseline", "scenarios", "ranking",
                                   "recommendation", "assumptions", "execution"}

Nothing above this line needs to know how the rollouts were executed. The
`execution` mode selects where the simulation runs; the decision layer is
identical either way, because both paths use the same simulator and the same
aggregation code.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable

from app.monte_carlo import DEFAULT_BASE_SEED, DEFAULT_N_RUNS
from app.scenario_runner import (
    BASELINE_CONFIG,
    BASELINE_ECONOMICS,
    DEMO_SCENARIOS,
    apply_overrides,
    assemble_comparison,
    compare_scenarios,
)

EXECUTION_LOCAL = "local"
EXECUTION_DAYTONA = "daytona"
EXECUTION_AUTO = "auto"


def daytona_available() -> bool:
    """True when a Daytona API key is configured and the SDK is importable."""
    if not os.environ.get("DAYTONA_API_KEY"):
        return False
    try:
        import daytona  # noqa: F401
    except ImportError:
        return False
    return True


def run_decision_pipeline(
    base_config: dict[str, Any] | None = None,
    scenarios: list[dict[str, Any]] | None = None,
    n_runs: int = DEFAULT_N_RUNS,
    base_seed: int = DEFAULT_BASE_SEED,
    execution: str = EXECUTION_AUTO,
    finance_config: dict[str, Any] | None = None,
    baseline_economics: dict[str, Any] | None = None,
    include_representative_run: bool = True,
    timeseries_stride: int = 6,
    on_log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the baseline and every intervention, and return the decision output.

    Args:
        execution: ``"local"`` runs in this process; ``"daytona"`` executes each
            scenario in its own forked sandbox; ``"auto"`` uses Daytona when an
            API key is present and falls back to local otherwise.

    Raises:
        DaytonaExecutionError: if ``execution="daytona"`` and the sandbox path
            fails. The failure is not swallowed - a demo that silently degrades
            to local execution while claiming to use Daytona would be worse than
            an error.
    """
    base_config = dict(base_config or BASELINE_CONFIG)
    scenarios = list(scenarios if scenarios is not None else DEMO_SCENARIOS)

    if execution == EXECUTION_AUTO:
        execution = EXECUTION_DAYTONA if daytona_available() else EXECUTION_LOCAL

    if execution == EXECUTION_LOCAL:
        return compare_scenarios(
            base_config,
            scenarios,
            n_runs=n_runs,
            base_seed=base_seed,
            finance_config=finance_config,
            baseline_economics=baseline_economics,
            include_representative_run=include_representative_run,
        )

    if execution != EXECUTION_DAYTONA:
        raise ValueError(f"unknown execution mode: {execution!r}")

    # Imported lazily so the local path never needs the Daytona SDK.
    from app.daytona_runner import fork_and_run_scenarios

    started = time.perf_counter()
    prepared = [
        {
            "name": s["name"],
            "label": s.get("label", s["name"]),
            "overrides": s.get("overrides") or {},
            "config": apply_overrides(base_config, s.get("overrides")),
        }
        for s in scenarios
    ]
    execution_result = fork_and_run_scenarios(
        apply_overrides(base_config, None),
        prepared,
        n_runs=n_runs,
        base_seed=base_seed,
        with_representative_run=include_representative_run,
        timeseries_stride=timeseries_stride,
        on_log=on_log,
    )

    comparison = assemble_comparison(
        execution_result["baseline"],
        execution_result["scenarios"],
        scenarios,
        base_config=base_config,
        baseline_economics=baseline_economics or BASELINE_ECONOMICS,
        finance_config=finance_config,
        n_runs=n_runs,
        base_seed=base_seed,
    )
    comparison["runtime_seconds"] = time.perf_counter() - started
    comparison["execution"] = {
        "mode": EXECUTION_DAYTONA,
        # "native_fork" only when Daytona's copy-on-write fork actually ran.
        "isolation_mode": execution_result["isolation_mode"],
        "baseline_sandbox_id": execution_result.get("baseline_sandbox_id"),
        "sandbox_environment": execution_result.get("environment"),
        "timings": execution_result.get("timings", {}),
    }
    return comparison
