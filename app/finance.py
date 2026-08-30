"""Deterministic financial decision layer.

The simulator produces *physical* metrics (tonnes lost, tanker trips made).
This module turns them into *decision* metrics (annual benefit, payback, annual
value). It is pure arithmetic on numbers that came out of the simulation - no
LLM is involved in producing any figure the interface displays.

Two things this module is deliberately careful about:

1. **CAPEX is not OPEX.** Adding a storage tank is a one-off capital spend.
   Running an extra tanker trip every day is a recurring cost. Forcing both
   through a single "payback" formula gives nonsense, so both are represented
   explicitly and payback is only reported when it is mathematically meaningful.

2. **Recurring collection cost is derived from the simulation**, not assumed.
   The number of tanker trips a scenario actually performs is a simulation
   output (a second daily collection is stood down when there is nothing worth
   collecting), so the OPEX delta is computed from simulated trip counts times a
   per-trip cost, rather than from a hand-waved annual figure.
"""

from __future__ import annotations

from typing import Any

#: Default economic assumptions. All of these are *assumptions* for the demo,
#: not validated market data; they are surfaced in the output so the UI can
#: label them as such.
DEFAULT_FINANCE_CONFIG: dict[str, Any] = {
    "value_per_tonne_gbp": 150.0,
    "capex_amortisation_years": 10.0,
    "days_per_year": 365.0,
}

#: Economics attached to a scenario. `cost_per_collection_gbp` is the cost of
#: one tanker trip *in that scenario* (a larger tanker costs more per trip).
DEFAULT_SCENARIO_ECONOMICS: dict[str, Any] = {
    "capex_gbp": 0.0,
    "annual_opex_delta_gbp": 0.0,
    "cost_per_collection_gbp": 400.0,
}

# Status codes for the payback calculation, so the caller never has to
# interpret a `None` on its own.
STATUS_PAYS_BACK = "pays_back"
STATUS_OPEX_ONLY_POSITIVE = "opex_only_positive"
STATUS_NOT_VIABLE = "not_viable"


def _merge_economics(economics: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_SCENARIO_ECONOMICS)
    if economics:
        merged.update({k: v for k, v in economics.items() if k in DEFAULT_SCENARIO_ECONOMICS})
        merged.update({k: v for k, v in economics.items() if k not in DEFAULT_SCENARIO_ECONOMICS})
    for key in ("capex_gbp", "annual_opex_delta_gbp", "cost_per_collection_gbp"):
        merged[key] = float(merged[key])
    if merged["capex_gbp"] < 0:
        raise ValueError("capex_gbp must be >= 0")
    if merged["cost_per_collection_gbp"] < 0:
        raise ValueError("cost_per_collection_gbp must be >= 0")
    return merged


def evaluate_scenario(
    baseline: dict[str, float],
    scenario: dict[str, float],
    economics: dict[str, Any] | None = None,
    baseline_economics: dict[str, Any] | None = None,
    finance_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Financial comparison of one scenario against the baseline.

    Args:
        baseline / scenario: physical summaries, each requiring
            ``mean_lost_production_t``, ``mean_collections_completed`` and
            ``simulation_days``.
        economics: :data:`DEFAULT_SCENARIO_ECONOMICS` for the scenario.
        baseline_economics: the same for the baseline (defaults to the scenario's
            per-trip cost being compared against the default baseline trip cost).
        finance_config: :data:`DEFAULT_FINANCE_CONFIG` overrides.

    Returns:
        A flat dict of decision metrics. ``payback_years`` is ``None`` whenever
        payback is not mathematically meaningful, and ``payback_status`` says
        why.

    Note:
        Annualisation multiplies a `simulation_days`-long result by
        ``days_per_year / simulation_days``. That assumes the simulated window
        is representative of the year - an explicit assumption, reported back as
        ``annualisation_factor``.
    """
    cfg = dict(DEFAULT_FINANCE_CONFIG)
    if finance_config:
        cfg.update(finance_config)
    econ = _merge_economics(economics)
    base_econ = _merge_economics(baseline_economics)

    sim_days = float(baseline["simulation_days"])
    if sim_days <= 0:
        raise ValueError("simulation_days must be > 0")
    if float(scenario["simulation_days"]) != sim_days:
        raise ValueError("baseline and scenario must cover the same period")

    value_per_tonne = float(cfg["value_per_tonne_gbp"])
    annualisation = float(cfg["days_per_year"]) / sim_days

    # --- operational recovery, in tonnes -------------------------------
    baseline_loss = float(baseline["mean_lost_production_t"])
    scenario_loss = float(scenario["mean_lost_production_t"])
    recovered_t = baseline_loss - scenario_loss           # may be negative
    recovered_t_per_year = recovered_t * annualisation

    # --- benefit --------------------------------------------------------
    period_benefit = recovered_t * value_per_tonne
    annualised_benefit = period_benefit * annualisation

    # --- recurring cost, derived from simulated tanker trips ------------
    base_trips = float(baseline["mean_collections_completed"])
    scen_trips = float(scenario["mean_collections_completed"])
    period_collection_cost_delta = (
        scen_trips * econ["cost_per_collection_gbp"]
        - base_trips * base_econ["cost_per_collection_gbp"]
    )
    annual_collection_cost_delta = period_collection_cost_delta * annualisation
    annual_opex_delta = econ["annual_opex_delta_gbp"] + annual_collection_cost_delta

    # --- headline decision metrics --------------------------------------
    capex = econ["capex_gbp"]
    net_annual_benefit = annualised_benefit - annual_opex_delta
    amortisation_years = float(cfg["capex_amortisation_years"])
    if amortisation_years <= 0:
        raise ValueError("capex_amortisation_years must be > 0")
    annualised_capex = capex / amortisation_years

    # `annual_value_gbp` is the apples-to-apples number: it puts a one-off
    # capital spend and a recurring cost on the same annual footing by
    # straight-lining CAPEX over its assumed life. No discounting - at this
    # horizon and for a hackathon demo, NPV machinery would add opacity, not
    # accuracy.
    annual_value = net_annual_benefit - annualised_capex

    if net_annual_benefit <= 0:
        payback_years: float | None = None
        status = STATUS_NOT_VIABLE
    elif capex <= 0:
        payback_years = None
        status = STATUS_OPEX_ONLY_POSITIVE
    else:
        payback_years = capex / net_annual_benefit
        status = STATUS_PAYS_BACK

    total_annual_cost = annual_opex_delta + annualised_capex
    benefit_cost_ratio = (
        annualised_benefit / total_annual_cost if total_annual_cost > 0 else None
    )
    roi_first_year = net_annual_benefit / capex if capex > 0 else None

    return {
        # physical
        "baseline_expected_loss_t": baseline_loss,
        "scenario_expected_loss_t": scenario_loss,
        "recovered_output_t": recovered_t,
        "recovered_output_t_per_year": recovered_t_per_year,
        # cost structure
        "capex_gbp": capex,
        "annualised_capex_gbp": annualised_capex,
        "capex_amortisation_years": amortisation_years,
        "annual_opex_delta_gbp": annual_opex_delta,
        "annual_collection_cost_delta_gbp": annual_collection_cost_delta,
        "fixed_annual_opex_delta_gbp": econ["annual_opex_delta_gbp"],
        "baseline_collections_per_period": base_trips,
        "scenario_collections_per_period": scen_trips,
        "cost_per_collection_gbp": econ["cost_per_collection_gbp"],
        # benefit
        "value_per_tonne_gbp": value_per_tonne,
        "period_benefit_gbp": period_benefit,
        "annualised_benefit_gbp": annualised_benefit,
        "net_annual_benefit_gbp": net_annual_benefit,
        "annual_value_gbp": annual_value,
        # decision
        "payback_years": payback_years,
        "payback_status": status,
        "roi_first_year": roi_first_year,
        "benefit_cost_ratio": benefit_cost_ratio,
        # provenance / assumptions
        "annualisation_factor": annualisation,
        "simulation_days": sim_days,
    }


def summarise_for_finance(mc: dict[str, Any]) -> dict[str, float]:
    """Extract the physical inputs :func:`evaluate_scenario` needs from a
    Monte Carlo result."""
    stats = mc["stats"]
    return {
        "mean_lost_production_t": stats["lost_production_t"]["mean"],
        "p95_lost_production_t": stats["lost_production_t"]["p95"],
        "mean_collections_completed": stats["collections_completed"]["mean"],
        "simulation_days": float(mc["config"]["simulation_days"]),
    }
