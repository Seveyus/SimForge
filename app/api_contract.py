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
    "inflow_rate": "production_rate_t_per_hour",
    "inflow_variability": "production_variability_pct",
    "buffer_count": "tank_count",
    "buffer_capacity": "tank_capacity_t",
    "initial_buffer": "initial_storage_t",
    "outbound_events_per_day": "collections_per_day",
    "outbound_capacity": "tanker_capacity_t",
    "missed_outbound_probability": "missed_collection_probability",
    "outbound_delay_probability": "collection_delay_probability",
    "outbound_delay_minutes": "collection_delay_minutes",
    "min_outbound_load": "min_collection_load_t",
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


def request_to_scenarios(
    scenarios: list[dict[str, Any]] | None, *, use_demo_economics: bool = True
) -> list[dict[str, Any]]:
    """Turn request scenarios into internal scenario definitions."""
    out: list[dict[str, Any]] = []
    for scenario in scenarios or []:
        overrides = overrides_to_config_keys(scenario.get("parameter_overrides"))
        out.append(
            {
                "name": scenario["id"],
                "label": scenario.get("label", scenario["id"]),
                "overrides": overrides,
                # echoed back verbatim in the response: the caller should see the
                # names it sent, not our internal unit-suffixed keys
                "parameter_overrides": dict(scenario.get("parameter_overrides") or {}),
                "economics": scenario.get("economics") or (
                    default_economics(overrides) if use_demo_economics else None
                ),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Response shaping
#
# `app/models.py` is strict: ContractModel forbids extra fields, metrics must be
# finite numbers, events need a label and a severity, and a Recommendation must
# name a completed scenario. Everything below exists to emit payloads that pass
# those validators on the first try. `SimulationResult.metadata` is the one
# free-form field in the contract, so the richer simulation detail (stats,
# financials, ranking, assumptions, execution) is carried there rather than
# bolted onto the response as extra keys that would be rejected.
# ---------------------------------------------------------------------------

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

#: Simulator event type -> (severity, human label builder). The simulator emits
#: machine-readable events; the contract also wants something displayable.
EVENT_PRESENTATION: dict[str, tuple[str, Any]] = {
    "collection_scheduled": (
        SEVERITY_INFO,
        lambda e: f"Collection scheduled (day {e.get('day')}, slot {e.get('slot')})",
    ),
    "collection_completed": (
        SEVERITY_INFO,
        lambda e: f"Tanker collected {e.get('collected_t', 0):.1f} t"
        + (" (partial load)" if e.get("partial_load") else ""),
    ),
    "collection_delayed": (
        SEVERITY_WARNING,
        lambda e: f"Collection delayed by {e.get('delay_minutes', 0):.0f} min",
    ),
    "collection_missed": (
        SEVERITY_WARNING,
        lambda e: f"Collection missed, storage at {e.get('storage_level_t', 0):.1f} t",
    ),
    "collection_stood_down": (
        SEVERITY_INFO,
        lambda e: f"Collection stood down, only {e.get('storage_level_t', 0):.1f} t to collect",
    ),
    "storage_capacity_reached": (
        SEVERITY_CRITICAL,
        lambda e: f"Storage full at {e.get('capacity_t', 0):.0f} t",
    ),
    "production_curtailed": (
        SEVERITY_CRITICAL,
        lambda e: f"Production curtailed for {e.get('duration_hours', 0):.1f} h, "
        f"{e.get('lost_production_t', 0):.1f} t lost",
    ),
}

#: Metric keys that are not numbers and therefore cannot live in
#: `SimulationResult.metrics` (which is `dict[str, NumericValue]`).
NON_NUMERIC_METRICS = ("payback_status",)


def to_contract_events(
    events: list[dict[str, Any]] | None,
    *,
    quantity_unit: str = "tonnes",
    neutral: bool = False,
) -> list[dict[str, Any]]:
    """Reshape simulator events into the contract's event schema.

    The simulator emits ``{t_hours, type, ...fields}``; the contract wants
    ``{time_hours, type, label, severity, details}`` with everything else nested
    under `details`.
    """
    out: list[dict[str, Any]] = []
    for event in events or []:
        severity, label_for = EVENT_PRESENTATION.get(
            event["type"], (SEVERITY_INFO, lambda e: e["type"].replace("_", " ").capitalize())
        )
        details = {k: v for k, v in event.items() if k not in ("t_hours", "type")}
        label = label_for(event)
        if neutral:
            type_aliases = {
                "collection_scheduled": "outbound_scheduled",
                "collection_completed": "outbound_completed",
                "collection_delayed": "outbound_delayed",
                "collection_missed": "outbound_missed",
                "collection_stood_down": "outbound_stood_down",
                "storage_capacity_reached": "buffer_capacity_reached",
                "production_curtailed": "inflow_curtailed",
            }
            labels = {
                "collection_scheduled": f"Outbound removal scheduled (day {event.get('day')}, slot {event.get('slot')})",
                "collection_completed": f"Outbound event removed {event.get('collected_t', 0):.1f} {quantity_unit}",
                "collection_delayed": f"Outbound removal delayed by {event.get('delay_minutes', 0):.0f} min",
                "collection_missed": f"Outbound removal missed, buffer at {event.get('storage_level_t', 0):.1f} {quantity_unit}",
                "collection_stood_down": f"Outbound removal stood down, only {event.get('storage_level_t', 0):.1f} {quantity_unit} available",
                "storage_capacity_reached": f"Buffer full at {event.get('capacity_t', 0):.1f} {quantity_unit}",
                "production_curtailed": f"Inflow curtailed for {event.get('duration_hours', 0):.1f} h, {event.get('lost_production_t', 0):.1f} {quantity_unit} lost",
            }
            label = labels.get(event["type"], label)
            detail_aliases = {
                "collected_t": "outbound_quantity", "storage_level_t": "buffer_level",
                "capacity_t": "buffer_capacity", "lost_production_t": "lost_output",
                "min_load_t": "min_outbound_load",
            }
            details = {detail_aliases.get(key, key): value for key, value in details.items()}
        out.append(
            {
                "time_hours": event["t_hours"],
                "type": type_aliases.get(event["type"], event["type"]) if neutral else event["type"],
                "label": label,
                "severity": severity,
                "details": details,
            }
        )
    return out


def to_frontend_timeseries(run: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Reshape a representative run into the contract's timeseries rows.

    The frontend plots a *cumulative* loss curve, so the per-window losses are
    accumulated here rather than in the simulator, which keeps the simulator's
    output additive and its mass balance checkable. `time_hours` is unique and
    ascending, as `SimulationResult` requires.
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
                "buffer_level": row["storage_level_t"],
                "cumulative_lost_output": round(cumulative, 4),
                "accepted_inflow": row["production_t"],
                "outbound_quantity": row["collected_t"],
                # extra series are allowed on TimeseriesPoint, for richer charts
                "storage_utilisation": row["storage_utilisation"],
                "production_t": row["production_t"],
                "collected_t": row["collected_t"],
            }
        )
    return rows


def _numeric_only(metrics: dict[str, Any]) -> dict[str, float]:
    """Drop anything the contract's `dict[str, NumericValue]` cannot hold.

    `payback_years` is None when payback is not meaningful, and `payback_status`
    is a string; both are moved into `metadata` instead of being forced into a
    numeric field or, worse, rendered as a nonsense number.
    """
    return {
        key: value
        for key, value in metrics.items()
        if key not in NON_NUMERIC_METRICS and isinstance(value, (int, float))
    }


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
                "recovered_output_t_per_year": fin["recovered_output_t_per_year"],
            }
        )
        if fin["payback_years"] is not None:
            metrics["payback_years"] = fin["payback_years"]
    return _numeric_only(metrics)


def _block_to_entry(
    block: dict[str, Any], is_baseline: bool = False, *,
    quantity_unit: str = "tonnes", neutral: bool = False,
) -> dict[str, Any]:
    if block.get("status") == STATUS_FAILED:
        entry = {
            "id": block["name"],
            "label": block["label"],
            "status": STATUS_FAILED,
            "result": None,
            "error": block["error"],
        }
        if not is_baseline:
            entry["parameter_overrides"] = block.get("parameter_overrides") or block.get(
                "overrides"
            ) or None
        return entry

    run = block.get("representative_run")
    metadata: dict[str, Any] = {
        "config": block.get("config"),
        "stats": block.get("stats"),
        "failure_probability": block.get("failure_probability"),
    }
    if block.get("financial"):
        metadata["financial"] = block["financial"]
    if block.get("economics"):
        metadata["economics"] = block["economics"]
    if block.get("sandbox_id"):
        metadata["sandbox_id"] = block["sandbox_id"]
    if run:
        metadata["representative_run_seed"] = run.get("seed")
        metadata["representative_run_metrics"] = run.get("metrics")

    entry = {
        "id": block["name"],
        "label": block["label"],
        "status": STATUS_COMPLETED,
        "result": {
            "timeseries": to_frontend_timeseries(run),
            "metrics": _result_metrics(block),
            "events": to_contract_events(
                (run or {}).get("events"), quantity_unit=quantity_unit, neutral=neutral
            ),
            "metadata": metadata,
        },
        "error": None,
    }
    if not is_baseline:
        entry["parameter_overrides"] = (
            block.get("parameter_overrides") or block.get("overrides") or None
        )
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


def _recommendation_for(
    block: dict[str, Any], comparison: dict[str, Any], quantity_unit: str = "tonnes",
    neutral: bool = False,
) -> dict[str, Any]:
    op, fin = block["operational"], block.get("financial")
    financials = _numeric_only(
        {
            "capex_gbp": fin["capex_gbp"],
            "annual_benefit_gbp": fin["annualised_benefit_gbp"],
            "incremental_annual_cost_gbp": fin["annual_opex_delta_gbp"],
            "net_annual_benefit_gbp": fin["net_annual_benefit_gbp"],
            "annual_value_gbp": fin["annual_value_gbp"],
            **({"payback_years": fin["payback_years"]}
               if fin["payback_years"] is not None else {}),
        } if fin else {}
    )
    return {
        "scenario_id": block["name"],
        "title": block["label"],
        "summary": comparison["recommendation"]["note"],
        "metric_deltas": {
            ("lost_output" if neutral else "lost_production_t"): _metric_delta(
                op["baseline_expected_lost_production_t"],
                op["expected_lost_production_t"],
                quantity_unit,
            ),
            ("p95_lost_output" if neutral else "p95_lost_production_t"): _metric_delta(
                op["baseline_p95_lost_production_t"],
                op["p95_lost_production_t"],
                quantity_unit,
            ),
            "failure_probability": _metric_delta(
                op["baseline_failure_probability"],
                op["failure_probability"],
                "fraction",
            ),
        },
        "financials": financials,
    }


def to_comparison_response(
    comparison: dict[str, Any], quantity_unit: str = "tonnes", neutral: bool = False
) -> dict[str, Any]:
    """Reshape a decision payload into a contract-valid `ScenarioComparison`.

    The response carries exactly the three fields the contract allows. The
    ranking, assumptions, execution metadata and - when no intervention pays for
    itself - the explanation of *why* nothing is recommended, all travel in the
    baseline result's `metadata`, which is the contract's free-form field.

    `recommendation` is `None` when no scenario has positive annual value. That
    is the honest answer and the contract permits it; the rejected best option is
    still described in the baseline metadata so the UI has numbers to show.
    """
    entries = [
        _block_to_entry(b, quantity_unit=quantity_unit, neutral=neutral)
        for b in comparison["scenarios"]
    ]
    completed_ids = {e["id"] for e in entries if e["status"] == STATUS_COMPLETED}

    winner_id = comparison["recommendation"].get("decision")
    winner = next(
        (b for b in comparison["scenarios"]
         if b["name"] == winner_id and b["name"] in completed_ids),
        None,
    )

    rejected = None
    if winner is None and comparison["ranking"]:
        best_name = comparison["ranking"][0]["name"]
        rejected = next(
            (b for b in comparison["scenarios"] if b["name"] == best_name), None
        )

    recommendation = (
        _recommendation_for(winner, comparison, quantity_unit, neutral) if winner else None
    )

    baseline_entry = _block_to_entry(
        comparison["baseline"], is_baseline=True,
        quantity_unit=quantity_unit, neutral=neutral,
    )
    baseline_entry["result"]["metadata"].update(
        {
            "ranking": comparison["ranking"],
            "ranking_rule": comparison["recommendation"]["rule"],
            "assumptions": comparison["assumptions"],
            "execution": comparison.get("execution", {}),
            "runtime_seconds": comparison.get("runtime_seconds"),
            "decision": comparison["recommendation"].get("decision"),
            "ranking_mode": comparison.get("ranking_mode", "financial"),
        }
    )
    if recommendation is None:
        baseline_entry["result"]["metadata"]["no_viable_intervention"] = {
            "reason": "no scenario has a positive annual value",
            "rejected_scenario_id": rejected["name"] if rejected else None,
            "rejected_annual_value_gbp": (
                rejected.get("financial", {}).get("annual_value_gbp") if rejected else None
            ),
            "detail": _recommendation_for(rejected, comparison, quantity_unit, neutral) if rejected else None,
        }

    return {
        "baseline": baseline_entry,
        "scenarios": entries,
        "recommendation": recommendation,
    }


def validate_contract_response(response: dict[str, Any]) -> Any:
    """Validate a response against `app/models.py`, raising if it does not fit.

    Kept as an explicit call rather than done automatically, so the simulation
    layer never depends on pydantic at runtime - but the tests, and any API
    layer, can assert the contract holds.
    """
    from app.models import ScenarioComparison

    return ScenarioComparison.model_validate(response)


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
    scenarios = request_to_scenarios(
        request.get("scenarios"), use_demo_economics=not bool((model_spec or {}).get("material"))
    )

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
    # carry the caller's original override names onto the blocks for echoing back
    original = {s["name"]: s.get("parameter_overrides") for s in scenarios}
    for block in comparison["scenarios"]:
        if original.get(block["name"]):
            block["parameter_overrides"] = original[block["name"]]

    quantity_unit = ((model_spec or {}).get("material") or {}).get("quantity_unit", "tonnes")
    if (model_spec or {}).get("material"):
        comparison["baseline"]["label"] = "Baseline"
    response = to_comparison_response(comparison, quantity_unit, neutral=bool((model_spec or {}).get("material")))
    response["baseline"]["result"]["metadata"]["unmapped_model_spec_parameters"] = (
        unmapped_parameters(model_spec)
    )
    _add_material_metadata(response["baseline"]["result"], model_spec)
    for scenario in response["scenarios"]:
        if scenario.get("result"):
            _add_material_metadata(scenario["result"], model_spec)
    return response


def run_baseline(request: dict[str, Any]) -> dict[str, Any]:
    """Execute a `baseline-request`: the baseline only, no interventions.

    Returns a `SimulationResult`, not a `ScenarioComparison` - the contract
    requires a comparison to hold at least one scenario, and a baseline run has
    none by definition.
    """
    model_spec = request.get("model_spec")
    comparison = run_decision_pipeline(
        base_config=model_spec_to_config(model_spec),
        scenarios=[],
        n_runs=int(request.get("rollout_count") or DEFAULT_N_RUNS),
        base_seed=int(request.get("seed") if request.get("seed") is not None
                      else DEFAULT_BASE_SEED),
        execution=request.get("execution", "auto"),
        finance_config=model_spec_to_finance_config(model_spec) or None,
        include_representative_run=True,
        tolerate_failures=True,
    )
    material = (model_spec or {}).get("material") or {}
    entry = _block_to_entry(
        comparison["baseline"], is_baseline=True,
        quantity_unit=material.get("quantity_unit", "tonnes"), neutral=bool(material),
    )
    result = entry["result"]
    result["metadata"].update(
        {
            "assumptions": comparison["assumptions"],
            "execution": comparison.get("execution", {}),
            "runtime_seconds": comparison.get("runtime_seconds"),
            "unmapped_model_spec_parameters": unmapped_parameters(model_spec),
        }
    )
    _add_material_metadata(result, model_spec)
    return result


def _add_material_metadata(result: dict[str, Any], model_spec: dict[str, Any] | None) -> None:
    """Attach neutral labels and numeric aliases without breaking CO2 clients."""
    material = (model_spec or {}).get("material") or {
        "name": "carbon dioxide", "quantity_unit": "tonnes"
    }
    metadata = result.setdefault("metadata", {})
    metadata["process_family"] = (
        (model_spec or {}).get("process_family") or "production_storage_collection"
    )
    metadata["material"] = material
    metrics = result.get("metrics", {})
    for generic, legacy in {
        "lost_output": "lost_production_t",
        "p95_lost_output": "p95_lost_production_t",
        "total_output": "total_production_t",
        "potential_output": "potential_production_t",
        "outbound_total": "collected_t",
        "buffer_capacity": "total_capacity_t",
        "final_buffer": "final_storage_t",
        "buffer_utilisation": "tank_utilisation",
    }.items():
        if legacy in metrics:
            metrics[generic] = metrics[legacy]


def validate_baseline_result(result: dict[str, Any]) -> Any:
    """Validate a baseline result against `app/models.py`."""
    from app.models import SimulationResult

    return SimulationResult.model_validate(result)
