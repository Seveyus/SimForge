"""Tests for the frontend/AI contract adapter.

Driven by the teammate's own fixtures (copied from `static/fixtures/` on their
branch into `tests/fixtures/`), so the shape we emit is checked against the
shape their UI was built against, not against my idea of it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.api_contract import (
    ECONOMICS_BY_OVERRIDE,
    config_key_for,
    default_economics,
    model_spec_to_config,
    model_spec_to_finance_config,
    overrides_to_config_keys,
    request_to_scenarios,
    run_baseline,
    run_scenario_comparison,
    to_comparison_response,
    to_frontend_timeseries,
    unmapped_parameters,
)
from app.api_contract import validate_baseline_result, validate_contract_response
from app.scenario_runner import STATUS_COMPLETED, STATUS_FAILED

# The teammate's fixtures are the source of truth for the contract shape.
FIXTURES = Path(__file__).parent.parent / "static" / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


# --------------------------------------------------------------------------
# ModelSpec -> config
# --------------------------------------------------------------------------

def test_model_spec_from_the_fixture_maps_onto_the_simulator():
    spec = fixture("baseline-request")["model_spec"]
    config = model_spec_to_config(spec)
    assert config["production_rate_t_per_hour"] == 1.0
    assert config["tank_count"] == 2
    assert config["tank_capacity_t"] == 45
    assert config["collections_per_day"] == 1
    assert config["tanker_capacity_t"] == 24       # "tanker_capacity" in the spec
    assert config["missed_collection_probability"] == 0.08
    assert config["simulation_days"] == 30         # from model_spec["time"]
    assert config["timestep_minutes"] == 10


def test_a_mapped_config_actually_runs():
    from reference.co2_simulation import simulate, validate_result

    config = model_spec_to_config(fixture("baseline-request")["model_spec"])
    validate_result(simulate(config, seed=1))


def test_missing_model_spec_falls_back_to_the_demo_baseline():
    from app.scenario_runner import BASELINE_CONFIG

    assert model_spec_to_config(None) == BASELINE_CONFIG


def test_unknown_model_spec_parameters_are_reported_not_fatal():
    """A ModelSpec is LLM-generated; it may carry fields we do not model."""
    spec = {"parameters": {"tank_count": {"value": 3},
                           "operator_headcount": {"value": 4},
                           "tank_capex": {"value": 80000}}}
    assert model_spec_to_config(spec)["tank_count"] == 3
    assert unmapped_parameters(spec) == ["operator_headcount", "tank_capex"]


def test_finance_parameters_are_picked_out_of_the_model_spec():
    spec = {"parameters": {"value_per_tonne": {"value": 220.0},
                           "tank_count": {"value": 2}}}
    assert model_spec_to_finance_config(spec) == {"value_per_tonne_gbp": 220.0}


def test_plain_values_are_accepted_as_well_as_provenance_dicts():
    assert model_spec_to_config({"parameters": {"tank_count": 4}})["tank_count"] == 4


@pytest.mark.parametrize(
    "name,expected",
    [
        ("tanker_capacity", "tanker_capacity_t"),
        ("tank_capacity", "tank_capacity_t"),
        ("production_rate", "production_rate_t_per_hour"),
        ("tank_count", "tank_count"),
        ("nonsense", None),
    ],
)
def test_parameter_aliases(name, expected):
    assert config_key_for(name) == expected


# --------------------------------------------------------------------------
# Scenario overrides
# --------------------------------------------------------------------------

def test_request_scenarios_from_the_fixture_become_internal_scenarios():
    request = fixture("scenario-comparison-request")
    scenarios = request_to_scenarios(request["scenarios"])
    assert [s["name"] for s in scenarios] == [
        "add-third-tank", "increase-collections", "larger-tanker"
    ]
    assert scenarios[0]["overrides"] == {"tank_count": 3}
    assert scenarios[2]["overrides"] == {"tanker_capacity_t": 40}   # renamed key
    assert scenarios[0]["economics"]["capex_gbp"] == ECONOMICS_BY_OVERRIDE["tank_count"]["capex_gbp"]


def test_an_override_the_simulator_cannot_model_is_rejected():
    """Unlike a spare ModelSpec field, a dead override invalidates a comparison."""
    with pytest.raises(ValueError, match="not a simulator parameter"):
        overrides_to_config_keys({"number_of_lorries": 3})


def test_economics_are_inferred_from_what_the_intervention_changes():
    assert default_economics({"tank_count": 3})["capex_gbp"] > 0
    assert default_economics({"collections_per_day": 2})["capex_gbp"] == 0
    # a bigger tanker is not capex, it is a dearer trip
    assert default_economics({"tanker_capacity_t": 40})["cost_per_collection_gbp"] > 400.0


def test_explicit_economics_win_over_the_inferred_default():
    scenarios = request_to_scenarios([
        {"id": "x", "parameter_overrides": {"tank_count": 3},
         "economics": {"capex_gbp": 1.0, "annual_opex_delta_gbp": 0.0,
                       "cost_per_collection_gbp": 400.0}}
    ])
    assert scenarios[0]["economics"]["capex_gbp"] == 1.0


# --------------------------------------------------------------------------
# Response shape vs the fixture
# --------------------------------------------------------------------------

def stressed_request(**overrides):
    """The fixture request, but with a baseline that actually fails.

    The fixture's ModelSpec uses a 30 t tanker against 24 t/day of production,
    which leaves so much recovery capacity that the baseline loses nothing and
    no intervention can pay for itself. Correct, but it exercises none of the
    decision path - so these tests tighten the tanker to 24 t.
    """
    request = fixture("scenario-comparison-request")
    request["model_spec"]["parameters"]["tanker_capacity"]["value"] = 24
    request.update({"rollout_count": 20, "execution": "local", **overrides})
    return request


@pytest.fixture(scope="module")
def response():
    return run_scenario_comparison(stressed_request())


def test_a_baseline_that_never_fails_recommends_nothing_but_still_explains():
    """The fixture's own numbers: nothing to recover, so nothing pays back."""
    request = fixture("scenario-comparison-request")
    # A generous tanker leaves so much recovery capacity that nothing is lost.
    request["model_spec"]["parameters"]["tanker_capacity"]["value"] = 30
    request.update(rollout_count=10, execution="local")
    request["model_spec"]["time"]["simulation_days"] = 10
    response = run_scenario_comparison(request)
    assert response["baseline"]["result"]["metrics"]["lost_production_t"] == 0.0
    # The contract requires a recommendation to name a *completed* scenario, so
    # "recommend nothing" is expressed as a null recommendation, not a fake one.
    assert response["recommendation"] is None
    explain = response["baseline"]["result"]["metadata"]["no_viable_intervention"]
    assert explain["rejected_scenario_id"] in {e["id"] for e in response["scenarios"]}
    assert explain["rejected_annual_value_gbp"] < 0
    assert explain["detail"]["metric_deltas"], "the UI still needs numbers to show"
    validate_contract_response(response)


def test_response_matches_the_fixture_top_level_shape(response):
    expected = fixture("scenario-comparison")
    assert set(expected) <= set(response)


def test_baseline_entry_matches_the_fixture_shape(response):
    expected = fixture("scenario-comparison")["baseline"]
    assert set(expected) <= set(response["baseline"])
    assert response["baseline"]["id"] == "baseline"
    assert response["baseline"]["status"] == STATUS_COMPLETED
    assert response["baseline"]["error"] is None
    assert set(expected["result"]) <= set(response["baseline"]["result"])


def test_scenario_entries_match_the_fixture_shape(response):
    expected = fixture("scenario-comparison")["scenarios"][0]
    for entry in response["scenarios"]:
        assert set(expected) <= set(entry)
        assert entry["status"] in (STATUS_COMPLETED, STATUS_FAILED)
    assert [e["id"] for e in response["scenarios"]] == [
        "add-third-tank", "increase-collections", "larger-tanker"
    ]


def test_every_metric_the_fixture_declares_is_present(response):
    expected_baseline = fixture("scenario-comparison")["baseline"]["result"]["metrics"]
    assert set(expected_baseline) <= set(response["baseline"]["result"]["metrics"])

    # `payback_years` is the one fixture metric we cannot always supply: metrics
    # is dict[str, NumericValue], and payback is None when it is not meaningful.
    declared: set[str] = set()
    for s in fixture("scenario-comparison")["scenarios"]:
        if s["result"]:
            declared |= set(s["result"]["metrics"])
    declared -= {"payback_years"}
    for entry in response["scenarios"]:
        if entry["status"] == STATUS_COMPLETED:
            assert declared <= set(entry["result"]["metrics"])


def test_metrics_are_all_finite_numbers(response):
    """SimulationResult.metrics is dict[str, NumericValue] - no strings, no None."""
    import math

    entries = [response["baseline"]] + response["scenarios"]
    for entry in entries:
        if entry["status"] != STATUS_COMPLETED:
            continue
        for key, value in entry["result"]["metrics"].items():
            assert isinstance(value, (int, float)) and not isinstance(value, bool), key
            assert math.isfinite(value), key


def test_payback_status_is_available_even_though_it_is_not_a_metric(response):
    """It is a string, so it lives in metadata rather than being forced numeric."""
    for entry in response["scenarios"]:
        if entry["status"] == STATUS_COMPLETED:
            assert entry["result"]["metadata"]["financial"]["payback_status"]


def test_recommendation_matches_the_fixture_shape(response):
    expected = fixture("scenario-comparison")["recommendation"]
    rec = response["recommendation"]
    assert rec is not None
    assert set(rec) <= set(expected), "ScenarioComparison forbids extra fields"
    assert set(expected) - {"summary"} <= set(rec) or set(rec) >= {
        "scenario_id", "title", "summary", "metric_deltas", "financials"
    }
    assert set(expected["metric_deltas"]) <= set(rec["metric_deltas"])
    for delta in rec["metric_deltas"].values():
        assert set(delta) == {"baseline", "scenario", "absolute_change",
                              "percentage_change", "unit"}
    assert set(expected["financials"]) <= set(rec["financials"])
    assert rec["scenario_id"] in {e["id"] for e in response["scenarios"]}


def test_recommendation_deltas_are_arithmetically_consistent(response):
    for delta in response["recommendation"]["metric_deltas"].values():
        assert delta["absolute_change"] == pytest.approx(
            delta["scenario"] - delta["baseline"]
        )


def test_timeseries_matches_the_fixture_field_names(response):
    expected_row = fixture("simulation-result")["timeseries"][0]
    rows = response["baseline"]["result"]["timeseries"]
    assert rows
    assert set(expected_row) <= set(rows[0])


def test_cumulative_loss_is_monotonic_and_ends_at_the_run_total():
    from app.monte_carlo import representative_run
    from app.scenario_runner import BASELINE_CONFIG

    run = representative_run(dict(BASELINE_CONFIG, simulation_days=10))
    rows = to_frontend_timeseries(run)
    values = [r["cumulative_lost_production_t"] for r in rows]
    assert values == sorted(values)
    assert values[-1] == pytest.approx(run["metrics"]["lost_production_t"], abs=1e-2)


def test_timeseries_of_a_missing_run_is_empty():
    assert to_frontend_timeseries(None) == []


def test_response_is_json_serialisable(response):
    json.loads(json.dumps(response))


def test_assumptions_and_execution_travel_in_baseline_metadata(response):
    """ScenarioComparison forbids extra fields, so the richer detail rides in
    SimulationResult.metadata - the contract's one free-form field."""
    meta = response["baseline"]["result"]["metadata"]
    assert meta["assumptions"]["ranking_rule"]
    assert meta["unmapped_model_spec_parameters"] == []
    assert meta["execution"]["mode"] == "local"
    assert meta["ranking"]
    assert meta["runtime_seconds"] > 0


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------

def test_a_failing_scenario_is_reported_not_fatal(monkeypatch):
    """One dead scenario must not take the whole comparison down."""
    import app.scenario_runner as sr

    real = sr.run_scenario_monte_carlo

    def flaky(base_config, scenario, **kwargs):
        if scenario["name"] == "increase-collections":
            raise RuntimeError("sandbox vanished")
        return real(base_config, scenario, **kwargs)

    monkeypatch.setattr(sr, "run_scenario_monte_carlo", flaky)

    response = run_scenario_comparison(stressed_request(rollout_count=10))

    failed = [e for e in response["scenarios"] if e["status"] == STATUS_FAILED]
    assert [e["id"] for e in failed] == ["increase-collections"]
    assert failed[0]["result"] is None
    assert set(failed[0]["error"]) == set(fixture("api-error")["error"]) | {"retryable"} \
        or {"code", "message", "retryable"} <= set(failed[0]["error"])
    assert "sandbox vanished" in failed[0]["error"]["message"]

    # the rest still produced a decision, and the failure is not ranked
    assert response["recommendation"] is not None
    ranking = response["baseline"]["result"]["metadata"]["ranking"]
    assert "increase-collections" not in {r["name"] for r in ranking}
    assert len(ranking) == 2
    validate_contract_response(response)


def test_baseline_request_runs_without_scenarios():
    request = fixture("baseline-request")
    request.update(rollout_count=10, execution="local")
    request["model_spec"]["time"]["simulation_days"] = 5
    result = run_baseline(request)
    # A baseline run returns a SimulationResult: ScenarioComparison requires at
    # least one scenario, and a baseline has none by definition.
    assert set(result) == {"timeseries", "metrics", "events", "metadata"}
    assert result["metrics"]["total_production_t"] > 0
    validate_baseline_result(result)


def test_seed_and_rollout_count_from_the_request_are_honoured():
    response = run_scenario_comparison(stressed_request(seed=42, rollout_count=15))
    assumptions = response["baseline"]["result"]["metadata"]["assumptions"]
    assert assumptions["base_seed"] == 42
    assert assumptions["n_runs"] == 15


def test_the_same_request_gives_the_same_response():
    request = stressed_request(seed=7, rollout_count=10)
    a = run_scenario_comparison(request)
    b = run_scenario_comparison(request)
    assert a["recommendation"] == b["recommendation"]
    assert (a["baseline"]["result"]["metadata"]["ranking"]
            == b["baseline"]["result"]["metadata"]["ranking"])


# --------------------------------------------------------------------------
# The contract actually validates against app/models.py
#
# This is the test that matters for integration: not "does my dict look right"
# but "does the teammate's own pydantic model accept it".
# --------------------------------------------------------------------------

def test_response_validates_against_the_pydantic_contract(response):
    parsed = validate_contract_response(response)
    assert parsed.baseline.status.value == STATUS_COMPLETED
    assert len(parsed.scenarios) == 3


def test_recommendation_references_a_completed_scenario(response):
    parsed = validate_contract_response(response)
    completed = {s.id for s in parsed.scenarios if s.status.value == STATUS_COMPLETED}
    assert parsed.recommendation.scenario_id in completed


def test_events_carry_a_label_and_severity(response):
    events = response["baseline"]["result"]["events"]
    assert events
    for event in events:
        assert set(event) == {"time_hours", "type", "label", "severity", "details"}
        assert event["severity"] in ("info", "warning", "critical")
        assert event["label"]


def test_curtailment_events_are_critical():
    from app.api_contract import to_contract_events

    events = to_contract_events([
        {"t_hours": 5.0, "type": "production_curtailed", "duration_hours": 3.0,
         "lost_production_t": 2.5},
        {"t_hours": 1.0, "type": "collection_completed", "collected_t": 24.0},
    ])
    assert events[0]["severity"] == "critical"
    assert "2.5 t lost" in events[0]["label"]
    assert events[1]["severity"] == "info"


def test_an_unknown_event_type_still_gets_a_label():
    from app.api_contract import to_contract_events

    event = to_contract_events([{"t_hours": 1.0, "type": "new_thing"}])[0]
    assert event["label"] and event["severity"] == "info"


def test_timeseries_times_are_unique_and_ascending(response):
    """SimulationResult enforces this."""
    times = [r["time_hours"] for r in response["baseline"]["result"]["timeseries"]]
    assert times == sorted(times)
    assert len(times) == len(set(times))


def test_parameter_overrides_are_echoed_in_the_callers_own_names(response):
    """The caller sent `tanker_capacity`; it should not get back `tanker_capacity_t`."""
    by_id = {e["id"]: e for e in response["scenarios"]}
    assert by_id["larger-tanker"]["parameter_overrides"] == {"tanker_capacity": 40}
    assert by_id["add-third-tank"]["parameter_overrides"] == {"tank_count": 3}


def test_a_failed_scenario_still_validates(monkeypatch):
    import app.scenario_runner as sr

    real = sr.run_scenario_monte_carlo

    def flaky(base_config, scenario, **kwargs):
        if scenario["name"] == "larger-tanker":
            raise RuntimeError("sandbox vanished")
        return real(base_config, scenario, **kwargs)

    monkeypatch.setattr(sr, "run_scenario_monte_carlo", flaky)
    response = run_scenario_comparison(stressed_request(rollout_count=10))
    parsed = validate_contract_response(response)
    failed = [s for s in parsed.scenarios if s.status.value == STATUS_FAILED]
    assert len(failed) == 1
    assert failed[0].error.retryable is True
