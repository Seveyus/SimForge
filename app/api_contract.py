"""Adapter between the frontend/AI contract and the simulation layer.

The AI + UX half speaks `ModelSpec` in and `{id, label, status, result, error}`
out (see `static/fixtures/*.json`). The simulation layer speaks a flat config in
and a richer decision payload out. This module is the seam.

It lives on the simulation side on purpose: the simulator, the scenario engine
and the finance module stay unaware of any transport shape, and the AI/UX side
does not have to learn the internals. Nothing here computes a number - it only
renames, reshapes and selects.
"""

from __future__ import annotations

from typing import Any

from app.finance import DEFAULT_FINANCE_CONFIG
from app.monte_carlo import DEFAULT_BASE_SEED, DEFAULT_N_RUNS
from app.pipeline import run_decision_pipeline
from app.scenario_runner import (
    BASELINE_CONFIG,
    BASELINE_ECONOMICS,
    STATUS_COMPLETED,
    STATUS_FAILED,
)
from reference.co2_simulation import DEFAULT_CONFIG

#: ModelSpec parameter name -> simulator config key. The ModelSpec uses
#: unit-free names ("tank_capacity"); the simulator carries the unit in the key
#: ("tank_capacity_t") so a config can never be misread.
PARAMETER_ALIASES: dict[str, str] = {
    "production_rate": "production_rate_t_per_hour",
    "production_rate_t_per_hour": "production_rate_t_per_hour",
    "production_variability": "production_variability_pct",
    "tank_capacity": "tank_capacity_t",
    "tanker_capacity": "tanker_capacity_t",
    "initial_storage": "initial_storage_t",
    "min_collection_load": "min_collection_load_t",
    "collection_delay": "collection_delay_minutes",
}

#: ModelSpec parameters that feed the finance layer rather than the simulator.
FINANCE_ALIASES: dict[str, str] = {
    "value_per_tonne": "value_per_tonne_gbp",
    "value_per_tonne_gbp": "value_per_tonne_gbp",
    "capex_amortisation_years": "capex_amortisation_years",
}

#: Default economics inferred from *which* parameter an intervention changes.
#: These are demo assumptions; a caller can pass explicit economics instead.
ECONOMICS_BY_OVERRIDE: dict[str, dict[str, Any]] = {
    "tank_count": {"capex_gbp": 80000.0, "annual_opex_delta_gbp": 1500.0,
                   "cost_per_collection_gbp": 400.0},
    "tank_capacity_t": {"capex_gbp": 120000.0, "annual_opex_delta_gbp": 2000.0,
                        "cost_per_collection_gbp": 400.0},
    "collections_per_day": {"capex_gbp": 0.0, "annual_opex_delta_gbp": 0.0,
                            "cost_per_collection_gbp": 400.0},
    "tanker_capacity_t": {"capex_gbp": 0.0, "annual_opex_delta_gbp": 0.0,
                          "cost_per_collection_gbp": 520.0},
}


def config_key_for(name: str) -> str | None:
    """Map a ModelSpec parameter name onto a simulator config key, or None."""
    key = PARAMETER_ALIASES.get(name, name)
    return key if key in DEFAULT_CONFIG else None


def model_spec_to_config(model_spec: dict[str, Any] | None) -> dict[str, Any]:
    """Turn a ModelSpec into a simulator config.

    `time` and `parameters[*].value` are mapped by name. Parameters the
    simulator does not model are ignored rather than raising: a ModelSpec is
    LLM-generated and may legitimately carry economic or descriptive fields.
    What was ignored is reported by :func:`unmapped_parameters` so it can be
    shown rather than silently dropped.
    """
    config = dict(BASELINE_CONFIG)
    if not model_spec:
        return config

    for key, value in (model_spec.get("time") or {}).items():
        if key in DEFAULT_CONFIG:
            config[key] = value

    for name, param in (model_spec.get("parameters") or {}).items():
        key = config_key_for(name)
        if key is None:
            continue
        config[key] = param["value"] if isinstance(param, dict) else param
    return config


def unmapped_parameters(model_spec: dict[str, Any] | None) -> list[str]:
    """ModelSpec parameter names the simulator does not model."""
    if not model_spec:
        return []
    return sorted(
        name
        for name in (model_spec.get("parameters") or {})
        if config_key_for(name) is None
    )


def model_spec_to_finance_config(model_spec: dict[str, Any] | None) -> dict[str, Any]:
    """Pull any finance parameters the ModelSpec carries (e.g. value_per_tonne)."""
    finance_config: dict[str, Any] = {}
    for name, param in ((model_spec or {}).get("parameters") or {}).items():
        key = FINANCE_ALIASES.get(name)
        if key and key in DEFAULT_FINANCE_CONFIG:
            finance_config[key] = param["value"] if isinstance(param, dict) else param
    return finance_config


def overrides_to_config_keys(overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Map a scenario's `parameter_overrides` onto simulator config keys.

    Raises:
        ValueError: if an override names something the simulator does not model.
            Unlike a ModelSpec parameter, a *scenario override* that does
            nothing would silently invalidate the whole comparison.
    """
    mapped: dict[str, Any] = {}
    for name, value in (overrides or {}).items():
        key = config_key_for(name)
        if key is None:
            raise ValueError(
                f"scenario override {name!r} is not a simulator parameter; "
                f"known names: {sorted(set(PARAMETER_ALIASES) | set(DEFAULT_CONFIG))}"
            )
        mapped[key] = value
    return mapped


def default_economics(overrides: dict[str, Any]) -> dict[str, Any]:
    """Infer an intervention's economics from the parameter it changes."""
    economics = dict(BASELINE_ECONOMICS)
    economics["source"] = "assumption"
    for key in overrides:
        if key in ECONOMICS_BY_OVERRIDE:
            economics.update(ECONOMICS_BY_OVERRIDE[key])
    return economics


def request_to_scenarios(scenarios: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Turn request scenarios into internal scenario definitions."""
    out: list[dict[str, Any]] = []
    for scenario in scenarios or []:
        overrides = overrides_to_config_keys(scenario.get("parameter_overrides"))
        out.append(
            {
                "name": scenario["id"],
                "label": scenario.get("label", scenario["id"]),
                "overrides": overrides,
                "economics": scenario.get("economics") or default_economics(overrides),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Response shaping
# ---------------------------------------------------------------------------

def to_frontend_timeseries(run: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Reshape a representative run into the frontend's timeseries rows.

    The frontend plots a *cumulative* loss curve, so the per-window losses are
    accumulated here rather than in the simulator, which keeps the simulator's
    output additive and its mass balance checkable.
    """
    if not run:
        return []
    cumulative = 0.0
    rows = []
    for row in run.get("timeseries", []):
        cumulative += row["lost_production_t"]
        rows.append(
            {
                "time_hours": row["t_hours"],
                "tank_level_t": row["storage_level_t"],
                "cumulative_lost_production_t": round(cumulative, 4),
                # kept alongside the contract fields, for richer charts
                "storage_utilisation": row["storage_utilisation"],
                "production_t": row["production_t"],
                "collected_t": row["collected_t"],
            }
        )
    return rows


def _result_metrics(block: dict[str, Any]) -> dict[str, Any]:
    op = block["operational"]
    metrics = {
        "total_production_t": op["expected_production_t"],
        "lost_production_t": op["expected_lost_production_t"],
        "p95_lost_production_t": op["p95_lost_production_t"],
        "failure_probability": op["failure_probability"],
        "tank_utilisation": op["mean_storage_utilisation"],
        "overflow_events": op["mean_curtailment_episodes"],
    }
    fin = block.get("financial")
    if fin:
        metrics.update(
            {
                "capex_gbp": fin["capex_gbp"],
                "annual_benefit_gbp": fin["annualised_benefit_gbp"],
                "incremental_annual_cost_gbp": fin["annual_opex_delta_gbp"],
                "net_annual_benefit_gbp": fin["net_annual_benefit_gbp"],
                "annual_value_gbp": fin["annual_value_gbp"],
                "payback_years": fin["payback_years"],
                "payback_status": fin["payback_status"],
            }
        )
    return metrics


def _block_to_entry(block: dict[str, Any], is_baseline: bool = False) -> dict[str, Any]:
    if block.get("status") == STATUS_FAILED:
        entry = {
            "id": block["name"],
            "label": block["label"],
            "status": STATUS_FAILED,
            "result": None,
            "error": block["error"],
        }
        if not is_baseline:
            entry["parameter_overrides"] = block.get("overrides", {})
        return entry

    entry = {
        "id": block["name"],
        "label": block["label"],
        "status": STATUS_COMPLETED,
        "result": {
            "timeseries": to_frontend_timeseries(block.get("representative_run")),
            "metrics": _result_metrics(block),
            "events": (block.get("representative_run") or {}).get("events", []),
        },
        "error": None,
    }
    if not is_baseline:
        entry["parameter_overrides"] = block.get("overrides", {})
    return entry


def _metric_delta(before: float, after: float, unit: str) -> dict[str, Any]:
    return {
        "baseline": before,
        "scenario": after,
        "absolute_change": after - before,
        "percentage_change": (
            round(100.0 * (after - before) / before, 2) if before else None
        ),
        "unit": unit,
    }


def to_comparison_response(comparison: dict[str, Any]) -> dict[str, Any]:
    """Reshape a decision payload into the frontend's scenario-comparison shape.

    Adds `assumptions` and `execution` on top of the contract, because the UI is
    meant to show what was assumed and where the code ran. Everything the
    fixture declares keeps its name and meaning.
    """
    baseline_block = comparison["baseline"]
    entries = [_block_to_entry(b) for b in comparison["scenarios"]]

    winner_id = comparison["recommendation"].get("decision")
    winner = next(
        (b for b in comparison["scenarios"]
         if b["name"] == winner_id and b.get("status") != STATUS_FAILED),
        None,
    )

    # When nothing pays for itself the honest answer is "recommend nothing", but
    # the UI still needs numbers to explain *why*. So scenario_id stays null and
    # the deltas describe the best-ranked option, named by rejected_scenario_id.
    rejected: dict[str, Any] | None = None
    if winner is None and comparison["ranking"]:
        best_name = comparison["ranking"][0]["name"]
        rejected = next(
            (b for b in comparison["scenarios"]
             if b["name"] == best_name and b.get("status") != STATUS_FAILED),
            None,
        )

    subject = winner or rejected
    if subject is None:
        recommendation = {
            "scenario_id": None,
            "title": comparison["recommendation"].get("label", "No intervention pays for itself"),
            "summary": comparison["recommendation"].get("note", ""),
            "metric_deltas": {},
            "financials": {},
            "rule": comparison["recommendation"]["rule"],
        }
    else:
        op, fin = subject["operational"], subject["financial"]
        recommendation = {
            "scenario_id": subject["name"] if winner else None,
            "rejected_scenario_id": None if winner else subject["name"],
            "title": subject["label"] if winner else "No intervention pays for itself",
            "summary": (
                comparison["recommendation"]["note"] if winner
                else f"{subject['label']} is the best-ranked option but its annual "
                     f"value is negative, so the recommendation is to do nothing."
            ),
            "metric_deltas": {
                "lost_production_t": _metric_delta(
                    op["baseline_expected_lost_production_t"],
                    op["expected_lost_production_t"],
                    "tonnes",
                ),
                "p95_lost_production_t": _metric_delta(
                    op["baseline_p95_lost_production_t"],
                    op["p95_lost_production_t"],
                    "tonnes",
                ),
                "failure_probability": _metric_delta(
                    op["baseline_failure_probability"],
                    op["failure_probability"],
                    "fraction",
                ),
            },
            "financials": {
                "capex_gbp": fin["capex_gbp"],
                "annual_benefit_gbp": fin["annualised_benefit_gbp"],
                "incremental_annual_cost_gbp": fin["annual_opex_delta_gbp"],
                "net_annual_benefit_gbp": fin["net_annual_benefit_gbp"],
                "annual_value_gbp": fin["annual_value_gbp"],
                "payback_years": fin["payback_years"],
                "payback_status": fin["payback_status"],
            },
            "rule": comparison["recommendation"]["rule"],
        }

    return {
        "baseline": _block_to_entry(baseline_block, is_baseline=True),
        "scenarios": entries,
        "ranking": comparison["ranking"],
        "recommendation": recommendation,
        "assumptions": comparison["assumptions"],
        "execution": comparison.get("execution", {}),
        "runtime_seconds": comparison.get("runtime_seconds"),
    }


# ---------------------------------------------------------------------------
# The one call the API layer makes
# ---------------------------------------------------------------------------

def run_scenario_comparison(request: dict[str, Any]) -> dict[str, Any]:
    """Execute a `scenario-comparison-request` and return the response shape.

    Request::

        {"model_spec": {...}, "scenarios": [{"id", "label", "parameter_overrides"}],
         "seed": 42, "rollout_count": 100, "execution": "auto"}

    Scenario failures are tolerated: a scenario that cannot be executed comes
    back with ``status: "failed"`` and an error, and is left out of the ranking,
    rather than failing the whole request.
    """
    model_spec = request.get("model_spec")
    config = model_spec_to_config(model_spec)
    scenarios = request_to_scenarios(request.get("scenarios"))

    comparison = run_decision_pipeline(
        base_config=config,
        scenarios=scenarios,
        n_runs=int(request.get("rollout_count") or DEFAULT_N_RUNS),
        base_seed=int(request.get("seed") if request.get("seed") is not None
                      else DEFAULT_BASE_SEED),
        execution=request.get("execution", "auto"),
        finance_config=model_spec_to_finance_config(model_spec) or None,
        include_representative_run=True,
        tolerate_failures=True,
    )
    response = to_comparison_response(comparison)
    response["assumptions"]["unmapped_model_spec_parameters"] = unmapped_parameters(
        model_spec
    )
    return response


def run_baseline(request: dict[str, Any]) -> dict[str, Any]:
    """Execute a `baseline-request`: the baseline only, no interventions."""
    return run_scenario_comparison({**request, "scenarios": []})
