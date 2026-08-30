"""Counterfactual scenario engine.

One simulator, many worlds. A scenario is *config overrides* applied to the
baseline config plus the economics of the intervention - never a different
simulator. That is what makes the comparison honest: baseline and scenario
differ by the intervention and nothing else.

    baseline_config
          |
   apply overrides
          |
    run_monte_carlo   (same rollout seeds as every other scenario)
          |
      finance
          |
     comparison
"""

from __future__ import annotations

import time
from typing import Any, Callable

try:  # normal repo layout
    from reference.co2_simulation import normalise_config, simulate
except ImportError:  # flat layout inside a Daytona sandbox
    from co2_simulation import normalise_config, simulate  # type: ignore

from app import finance
from app.monte_carlo import (
    DEFAULT_BASE_SEED,
    DEFAULT_N_RUNS,
    representative_run,
    run_monte_carlo,
)

#: How CAPEX and OPEX interventions are made comparable. Stated in the output
#: so the ranking is never a black box.
RANKING_RULE = (
    "annual_value_gbp = annualised benefit - annual opex delta - "
    "capex / capex_amortisation_years (straight line, no discounting). "
    "Scenarios are ranked by annual_value_gbp, descending."
)

#: The demo baseline. Example demo assumptions, not validated plant data.
#:
#: The 24 t tanker against 24 t/day of production is the point of the demo: the
#: collection capacity exactly matches production, so the operation has no
#: recovery capacity and every missed collection is permanent.
BASELINE_CONFIG: dict[str, Any] = {
    "simulation_days": 30,
    "timestep_minutes": 10,
    "production_rate_t_per_hour": 1.0,
    "production_variability_pct": 0.05,
    "tank_count": 2,
    "tank_capacity_t": 45.0,
    "initial_storage_t": 20.0,
    "collections_per_day": 1,
    "tanker_capacity_t": 24.0,
    "first_collection_hour": 8.0,
    "missed_collection_probability": 0.08,
    "collection_delay_probability": 0.35,
    "collection_delay_minutes": 240.0,
    "min_collection_load_t": 0.0,
}

BASELINE_ECONOMICS: dict[str, Any] = {
    "capex_gbp": 0.0,
    "annual_opex_delta_gbp": 0.0,
    "cost_per_collection_gbp": 400.0,
    "source": "assumption",
}

#: The interventions the demo tests. Generic config overrides - adding a fourth
#: intervention means adding a dict here, not touching the simulator.
DEMO_SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "extra_tank",
        "label": "Add a third 45 t storage tank",
        "overrides": {"tank_count": 3},
        "economics": {
            "capex_gbp": 80000.0,
            "annual_opex_delta_gbp": 1500.0,   # inspection / maintenance
            "cost_per_collection_gbp": 400.0,  # logistics unchanged
            "source": "assumption",
        },
    },
    {
        "name": "extra_collection",
        "label": "Second daily collection (stood down below 12 t)",
        # The min-load policy is part of the intervention: an operator would not
        # dispatch a tanker for a nearly empty pickup. Without it this scenario
        # pays a full trip cost ~55 times a month instead of ~39.
        "overrides": {"collections_per_day": 2, "min_collection_load_t": 12.0},
        "economics": {
            "capex_gbp": 0.0,
            "annual_opex_delta_gbp": 0.0,
            "cost_per_collection_gbp": 400.0,
            "source": "assumption",
        },
    },
    {
        "name": "larger_tanker",
        "label": "Switch to a 36 t tanker",
        "overrides": {"tanker_capacity_t": 36.0},
        "economics": {
            "capex_gbp": 0.0,
            "annual_opex_delta_gbp": 0.0,
            "cost_per_collection_gbp": 520.0,  # bigger vehicle, dearer per trip
            "source": "assumption",
        },
    },
]


# ---------------------------------------------------------------------------
# Config overrides
# ---------------------------------------------------------------------------

def apply_overrides(
    base_config: dict[str, Any], overrides: dict[str, Any] | None
) -> dict[str, Any]:
    """Return `base_config` with `overrides` applied, validated.

    Raises:
        ValueError: if an override names a parameter the simulator does not have
            (a typo in a scenario definition must fail loudly, not silently do
            nothing).
    """
    merged = dict(base_config)
    if overrides:
        merged.update(overrides)
    return normalise_config(merged)


def run_scenario(
    base_config: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    seed: int | None = None,
    simulate_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One simulation of `base_config + overrides`. The single-run entry point."""
    sim = simulate_fn or simulate
    return sim(apply_overrides(base_config, overrides), seed)


def run_scenario_monte_carlo(
    base_config: dict[str, Any],
    scenario: dict[str, Any],
    n_runs: int = DEFAULT_N_RUNS,
    base_seed: int = DEFAULT_BASE_SEED,
    simulate_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Monte Carlo one scenario definition."""
    config = apply_overrides(base_config, scenario.get("overrides"))
    mc = run_monte_carlo(
        config,
        n_runs=n_runs,
        base_seed=base_seed,
        name=scenario["name"],
        simulate_fn=simulate_fn,
    )
    mc["label"] = scenario.get("label", scenario["name"])
    mc["overrides"] = dict(scenario.get("overrides") or {})
    mc["economics"] = dict(scenario.get("economics") or {})
    return mc


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def operational_delta(baseline_mc: dict[str, Any], scenario_mc: dict[str, Any]) -> dict[str, Any]:
    """Operational comparison of a scenario against the baseline."""
    b, s = baseline_mc["stats"], scenario_mc["stats"]
    b_mean = b["lost_production_t"]["mean"]
    s_mean = s["lost_production_t"]["mean"]
    b_p95 = b["lost_production_t"]["p95"]
    s_p95 = s["lost_production_t"]["p95"]

    def pct_drop(before: float, after: float) -> float | None:
        return None if before <= 0 else 100.0 * (before - after) / before

    return {
        "expected_lost_production_t": s_mean,
        "baseline_expected_lost_production_t": b_mean,
        "expected_loss_reduction_t": b_mean - s_mean,
        "expected_loss_reduction_pct": pct_drop(b_mean, s_mean),
        "p95_lost_production_t": s_p95,
        "baseline_p95_lost_production_t": b_p95,
        "p95_loss_reduction_t": b_p95 - s_p95,
        "p95_loss_reduction_pct": pct_drop(b_p95, s_p95),
        "failure_probability": scenario_mc["failure_probability"],
        "baseline_failure_probability": baseline_mc["failure_probability"],
        "failure_probability_reduction_pp": 100.0
        * (baseline_mc["failure_probability"] - scenario_mc["failure_probability"]),
        "expected_production_t": s["total_production_t"]["mean"],
        "mean_storage_utilisation": s["mean_storage_utilisation"]["mean"],
        "max_storage_utilisation": s["max_storage_utilisation"]["mean"],
        "mean_collections_completed": s["collections_completed"]["mean"],
        "mean_collections_missed": s["collections_missed"]["mean"],
        "mean_curtailment_episodes": s["curtailment_episodes"]["mean"],
    }


def compare_scenarios(
    base_config: dict[str, Any] | None = None,
    scenarios: list[dict[str, Any]] | None = None,
    n_runs: int = DEFAULT_N_RUNS,
    base_seed: int = DEFAULT_BASE_SEED,
    finance_config: dict[str, Any] | None = None,
    baseline_economics: dict[str, Any] | None = None,
    include_representative_run: bool = True,
    simulate_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the baseline and every scenario locally, and assemble the decision.

    Every scenario uses the same rollout seeds as the baseline, so scenario *i*
    and baseline *i* are the same stochastic future with a different
    intervention (common random numbers).

    Returns:
        See :func:`assemble_comparison`.
    """
    base_config = dict(base_config or BASELINE_CONFIG)
    scenarios = list(scenarios if scenarios is not None else DEMO_SCENARIOS)
    started = time.perf_counter()

    baseline_mc = run_monte_carlo(
        apply_overrides(base_config, None),
        n_runs=n_runs,
        base_seed=base_seed,
        name="baseline",
        simulate_fn=simulate_fn,
    )
    if include_representative_run:
        baseline_mc["representative_run"] = representative_run(
            base_config, base_seed=base_seed, simulate_fn=simulate_fn
        )

    scenario_mcs: dict[str, dict[str, Any]] = {}
    for scenario in scenarios:
        mc = run_scenario_monte_carlo(
            base_config, scenario, n_runs=n_runs, base_seed=base_seed,
            simulate_fn=simulate_fn,
        )
        if include_representative_run:
            mc["representative_run"] = representative_run(
                mc["config"], base_seed=base_seed, simulate_fn=simulate_fn
            )
        scenario_mcs[scenario["name"]] = mc

    comparison = assemble_comparison(
        baseline_mc,
        scenario_mcs,
        scenarios,
        base_config=base_config,
        baseline_economics=baseline_economics,
        finance_config=finance_config,
        n_runs=n_runs,
        base_seed=base_seed,
    )
    comparison["runtime_seconds"] = time.perf_counter() - started
    comparison["execution"] = {"mode": "local"}
    return comparison


def assemble_comparison(
    baseline_mc: dict[str, Any],
    scenario_mcs: dict[str, dict[str, Any]],
    scenarios: list[dict[str, Any]],
    base_config: dict[str, Any] | None = None,
    baseline_economics: dict[str, Any] | None = None,
    finance_config: dict[str, Any] | None = None,
    n_runs: int | None = None,
    base_seed: int | None = None,
) -> dict[str, Any]:
    """Build the decision output from Monte Carlo results.

    Deliberately independent of *where* the rollouts ran: the results may come
    from this process or from a Daytona sandbox, since both are produced by the
    same :func:`~app.monte_carlo.run_monte_carlo`. That keeps the decision layer
    free of any execution concern.

    Returns:
        ``{"baseline": {...}, "scenarios": [...], "ranking": [...],
           "recommendation": {...}, "assumptions": {...}}``
    """
    base_econ = dict(baseline_economics or BASELINE_ECONOMICS)
    baseline_summary = finance.summarise_for_finance(baseline_mc)

    baseline_block: dict[str, Any] = {
        "name": "baseline",
        "label": "Baseline (2 x 45 t tanks, 1 collection/day)",
        "config": baseline_mc["config"],
        "operational": operational_delta(baseline_mc, baseline_mc),
        "stats": baseline_mc["stats"],
        "failure_probability": baseline_mc["failure_probability"],
        "runs": baseline_mc.get("runs", {}),
        "economics": base_econ,
    }
    if "representative_run" in baseline_mc:
        baseline_block["representative_run"] = baseline_mc["representative_run"]

    scenario_blocks: list[dict[str, Any]] = []
    for scenario in scenarios:
        mc = scenario_mcs[scenario["name"]]
        block = {
            "name": scenario["name"],
            "label": scenario.get("label", scenario["name"]),
            "overrides": dict(scenario.get("overrides") or {}),
            "config": mc["config"],
            "operational": operational_delta(baseline_mc, mc),
            "financial": finance.evaluate_scenario(
                baseline_summary,
                finance.summarise_for_finance(mc),
                economics=scenario.get("economics"),
                baseline_economics=base_econ,
                finance_config=finance_config,
            ),
            "stats": mc["stats"],
            "failure_probability": mc["failure_probability"],
            "runs": mc.get("runs", {}),
            "economics": dict(scenario.get("economics") or {}),
        }
        if "representative_run" in mc:
            block["representative_run"] = mc["representative_run"]
        if mc.get("sandbox_id"):
            block["sandbox_id"] = mc["sandbox_id"]
        scenario_blocks.append(block)

    ranking = rank_scenarios(scenario_blocks)
    fin_cfg = dict(finance.DEFAULT_FINANCE_CONFIG)
    if finance_config:
        fin_cfg.update(finance_config)

    return {
        "baseline": baseline_block,
        "scenarios": scenario_blocks,
        "ranking": ranking,
        "recommendation": build_recommendation(scenario_blocks, ranking),
        "assumptions": {
            "n_runs": n_runs if n_runs is not None else baseline_mc["n_runs"],
            "base_seed": base_seed if base_seed is not None else baseline_mc["base_seed"],
            "ranking_rule": RANKING_RULE,
            "failure_definition": baseline_mc.get("failure_definition", ""),
            "finance_config": fin_cfg,
            "baseline_economics": base_econ,
            "common_random_numbers": (
                "Scenario i and baseline i share rollout seed "
                "derive_seed(base_seed, 'rollout', i): the same stochastic future, "
                "a different intervention."
            ),
        },
    }


def rank_scenarios(scenario_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank by `annual_value_gbp`, descending. See :data:`RANKING_RULE`.

    The rule is a single, stated number rather than a weighted composite, so
    nothing arbitrary is hidden inside it. The operational ordering (which can
    differ) is reported alongside so the trade-off stays visible.
    """
    by_value = sorted(
        scenario_blocks, key=lambda b: b["financial"]["annual_value_gbp"], reverse=True
    )
    by_resilience = sorted(
        scenario_blocks, key=lambda b: b["operational"]["p95_lost_production_t"]
    )
    resilience_rank = {b["name"]: i + 1 for i, b in enumerate(by_resilience)}
    return [
        {
            "rank": i + 1,
            "name": b["name"],
            "label": b["label"],
            "annual_value_gbp": b["financial"]["annual_value_gbp"],
            "net_annual_benefit_gbp": b["financial"]["net_annual_benefit_gbp"],
            "payback_years": b["financial"]["payback_years"],
            "payback_status": b["financial"]["payback_status"],
            "expected_loss_reduction_pct": b["operational"]["expected_loss_reduction_pct"],
            "p95_lost_production_t": b["operational"]["p95_lost_production_t"],
            "resilience_rank": resilience_rank[b["name"]],
        }
        for i, b in enumerate(by_value)
    ]


def build_recommendation(
    scenario_blocks: list[dict[str, Any]], ranking: list[dict[str, Any]]
) -> dict[str, Any]:
    """The backend's own answer, plus the caveat the presentation layer must show.

    An LLM may phrase this; it may not change it.
    """
    if not ranking:
        return {"decision": "no_scenarios", "rule": RANKING_RULE}

    best = ranking[0]
    best_is_viable = best["annual_value_gbp"] > 0
    most_resilient = min(
        scenario_blocks, key=lambda b: b["operational"]["p95_lost_production_t"]
    )
    return {
        "decision": best["name"] if best_is_viable else "do_nothing",
        "label": best["label"] if best_is_viable else "No intervention pays for itself",
        "rule": RANKING_RULE,
        "annual_value_gbp": best["annual_value_gbp"],
        "payback_years": best["payback_years"],
        "payback_status": best["payback_status"],
        "best_financial": best["name"],
        "most_resilient": most_resilient["name"],
        "financial_and_resilience_agree": best["name"] == most_resilient["name"],
        "note": (
            "The financially best option is also the most resilient."
            if best["name"] == most_resilient["name"]
            else (
                f"{most_resilient['label']} gives the lowest P95 loss but "
                f"{best['label']} has the higher annual value - a genuine trade-off."
            )
        ),
    }
