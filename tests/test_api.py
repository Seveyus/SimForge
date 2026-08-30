"""Tests for the HTTP API.

The routes, the error envelope and the partial-failure rule all come from
`static/fixtures/README.md`; these tests hold the implementation to it, and to
the pydantic contracts in `app/models.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api_contract import validate_baseline_result, validate_contract_response
from app.main import ERROR_STATUS, app

FIXTURES = Path(__file__).parent.parent / "static" / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def compare_payload(**overrides):
    """The fixture request, with a baseline that actually fails.

    The fixture's 30 t tanker leaves so much recovery capacity that nothing is
    lost and no intervention can pay back - correct, but it exercises none of
    the decision path.
    """
    payload = fixture("scenario-comparison-request")
    payload["model_spec"]["parameters"]["tanker_capacity"]["value"] = 24
    payload.update({"rollout_count": 15, **overrides})
    return payload


# `execution` is a query parameter, not a body field: the contract models forbid
# extra fields, so the body stays exactly what the frontend sends.
COMPARE = "/api/scenarios/compare?execution=local"
BASELINE = "/api/simulations/baseline?execution=local"


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------

def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["execution"] in ("local", "daytona")


# --------------------------------------------------------------------------
# Baseline
# --------------------------------------------------------------------------

def test_baseline_returns_a_valid_simulation_result(client):
    payload = fixture("baseline-request")
    payload["rollout_count"] = 10
    response = client.post(BASELINE, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"timeseries", "metrics", "events", "metadata"}
    validate_baseline_result(body)
    assert body["metrics"]["total_production_t"] > 0


def test_baseline_timeseries_is_plottable(client):
    payload = fixture("baseline-request")
    payload["rollout_count"] = 5
    rows = client.post(BASELINE, json=payload).json()["timeseries"]
    assert rows
    expected_row = fixture("simulation-result")["timeseries"][0]
    assert set(expected_row) <= set(rows[0])


# --------------------------------------------------------------------------
# Scenario comparison
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def comparison(client):
    response = client.post(COMPARE, json=compare_payload())
    assert response.status_code == 200, response.text
    return response.json()


def test_comparison_validates_against_the_contract(comparison):
    parsed = validate_contract_response(comparison)
    assert len(parsed.scenarios) == 3
    assert parsed.recommendation is not None


def test_comparison_recommends_a_completed_scenario(comparison):
    completed = {s["id"] for s in comparison["scenarios"] if s["status"] == "completed"}
    assert comparison["recommendation"]["scenario_id"] in completed


def test_every_recommendation_number_exists_in_a_backend_result(comparison):
    """The UI must never need to compute or invent a figure."""
    rec = comparison["recommendation"]
    winner = next(s for s in comparison["scenarios"]
                  if s["id"] == rec["scenario_id"])
    baseline_metrics = comparison["baseline"]["result"]["metrics"]
    deltas = rec["metric_deltas"]
    assert deltas["lost_production_t"]["baseline"] == pytest.approx(
        baseline_metrics["lost_production_t"]
    )
    assert deltas["lost_production_t"]["scenario"] == pytest.approx(
        winner["result"]["metrics"]["lost_production_t"]
    )
    for key, value in rec["financials"].items():
        assert winner["result"]["metrics"][key] == pytest.approx(value)


def test_execution_metadata_is_reported(comparison):
    meta = comparison["baseline"]["result"]["metadata"]
    assert meta["execution"]["mode"] == "local"
    assert meta["ranking"]
    assert meta["assumptions"]["ranking_rule"]


def test_seed_makes_the_route_reproducible(client):
    a = client.post(COMPARE, json=compare_payload(seed=99)).json()
    b = client.post(COMPARE, json=compare_payload(seed=99)).json()
    assert a["recommendation"] == b["recommendation"]
    assert a["baseline"]["result"]["metrics"] == b["baseline"]["result"]["metrics"]


def test_a_failing_scenario_returns_200_and_is_preserved(client, monkeypatch):
    """Documented rule: a failed scenario does not fail the comparison."""
    import app.scenario_runner as sr

    real = sr.run_scenario_monte_carlo

    def flaky(base_config, scenario, **kwargs):
        if scenario["name"] == "larger-tanker":
            raise RuntimeError("sandbox vanished")
        return real(base_config, scenario, **kwargs)

    monkeypatch.setattr(sr, "run_scenario_monte_carlo", flaky)
    response = client.post(COMPARE, json=compare_payload())
    assert response.status_code == 200
    body = response.json()
    failed = [s for s in body["scenarios"] if s["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["id"] == "larger-tanker"
    assert failed[0]["result"] is None
    assert failed[0]["error"]["retryable"] is True
    assert body["recommendation"]["scenario_id"] != "larger-tanker"
    validate_contract_response(body)


def test_a_failed_scenario_error_does_not_leak_internals(client, monkeypatch):
    import app.scenario_runner as sr

    def boom(*a, **k):
        raise RuntimeError("/home/secret/path traceback token=abc123")

    monkeypatch.setattr(sr, "run_scenario_monte_carlo", boom)
    body = client.post(COMPARE, json=compare_payload()).json()
    # every scenario failed, but the baseline still completed
    for scenario in body["scenarios"]:
        assert "Traceback" not in json.dumps(scenario["error"])


# --------------------------------------------------------------------------
# Error envelope
# --------------------------------------------------------------------------

def assert_error_envelope(response, code: str):
    assert response.status_code == ERROR_STATUS[code], response.text
    error = response.json()["error"]
    assert set(error) == {"code", "message", "retryable", "field_errors", "request_id"}
    assert error["code"] == code
    assert isinstance(error["retryable"], bool)
    assert error["request_id"]
    return error


def test_malformed_json_is_a_400(client):
    response = client.post(
        COMPARE, content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert_error_envelope(response, "invalid_request")


def test_a_non_object_body_is_a_400(client):
    response = client.post(COMPARE, json=[1, 2, 3])
    assert_error_envelope(response, "invalid_request")


def test_a_missing_model_spec_is_a_422_with_field_errors(client):
    response = client.post(COMPARE, json={"scenarios": []})
    error = assert_error_envelope(response, "validation_error")
    assert error["field_errors"]
    assert any(f["path"].startswith("model_spec") for f in error["field_errors"])
    assert error["retryable"] is False


def test_a_bad_parameter_value_is_a_422(client):
    payload = compare_payload()
    payload["model_spec"]["time"]["simulation_days"] = -5
    error = assert_error_envelope(
        client.post(COMPARE, json=payload), "validation_error"
    )
    assert any("simulation_days" in f["path"] for f in error["field_errors"])


def test_an_override_the_simulator_cannot_model_is_a_422(client):
    payload = compare_payload()
    payload["scenarios"][0]["parameter_overrides"] = {"number_of_lorries": 3}
    error = assert_error_envelope(
        client.post(COMPARE, json=payload), "validation_error"
    )
    assert "not a simulator parameter" in error["message"]


def test_an_unknown_execution_mode_is_a_422(client):
    error = assert_error_envelope(
        client.post("/api/scenarios/compare?execution=magic", json=compare_payload()),
        "validation_error",
    )
    assert error["field_errors"][0]["path"] == "execution"


def test_daytona_being_down_is_503_execution_unavailable(client, monkeypatch):
    from app.daytona_runner import DaytonaExecutionError

    def down(*a, **k):
        raise DaytonaExecutionError("sandbox provisioning failed")

    monkeypatch.setattr("app.api_contract.run_decision_pipeline", down)
    error = assert_error_envelope(
        client.post(COMPARE, json=compare_payload()),
        "execution_unavailable",
    )
    assert error["retryable"] is True
    assert "sandbox provisioning failed" not in error["message"]


def test_an_unexpected_failure_is_a_safe_502(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr("app.api_contract.run_decision_pipeline", boom)
    error = assert_error_envelope(
        client.post(COMPARE, json=compare_payload()),
        "simulation_failed",
    )
    assert "secret internal detail" not in error["message"]


def test_the_error_shape_matches_the_fixture(client):
    expected = fixture("api-error")["error"]
    error = client.post(COMPARE, json={}).json()["error"]
    assert set(error) == set(expected)


def test_request_id_is_echoed_when_supplied(client):
    response = client.post(
        COMPARE, json={},
        headers={"x-request-id": "trace-me"},
    )
    assert response.json()["error"]["request_id"] == "trace-me"
    assert response.headers["x-request-id"] == "trace-me"


# --------------------------------------------------------------------------
# Requirements route (owned by the AI half)
# --------------------------------------------------------------------------

def test_requirements_reports_unavailable_until_the_agent_lands(client):
    """A stub success would let the frontend build against a fake happy path."""
    response = client.post("/api/requirements", json=fixture("requirements-request"))
    if response.status_code == 200:
        pytest.skip("requirements_agent is implemented")
    assert_error_envelope(response, "gemini_unavailable")


# --------------------------------------------------------------------------
# Concurrency, timeouts and the pre-demo probe
# --------------------------------------------------------------------------

def test_requests_do_not_block_each_other(client):
    """A slow simulation must not stall the event loop for everyone else.

    The routes are `async def` but the pipeline is synchronous and spends
    seconds in CPU work and Daytona round trips, so it has to run in a thread.
    """
    import threading
    import time

    import app.api_contract as ac

    real = ac.run_decision_pipeline
    started = threading.Event()

    def slow(*args, **kwargs):
        started.set()
        time.sleep(1.0)
        return real(*args, **kwargs)

    ac.run_decision_pipeline = slow
    try:
        result: dict = {}

        def fire():
            result["compare"] = client.post(COMPARE, json=compare_payload()).status_code

        worker = threading.Thread(target=fire)
        worker.start()
        assert started.wait(timeout=10)
        # while the comparison is mid-flight, health must still answer promptly
        t0 = time.perf_counter()
        assert client.get("/api/health").status_code == 200
        assert time.perf_counter() - t0 < 0.8, "the event loop was blocked"
        worker.join(timeout=60)
        assert result["compare"] == 200
    finally:
        ac.run_decision_pipeline = real


def test_a_hanging_simulation_times_out_instead_of_hanging_forever(client, monkeypatch):
    import time

    import app.main as main

    monkeypatch.setattr(main, "REQUEST_TIMEOUT_S", 0.3)
    monkeypatch.setattr(
        "app.api_contract.run_decision_pipeline",
        lambda *a, **k: time.sleep(5),
    )
    error = assert_error_envelope(
        client.post(COMPARE, json=compare_payload()), "operation_timeout"
    )
    assert error["retryable"] is True


def test_deep_health_probe_reports_without_raising(client, monkeypatch):
    """A probe that 500s tells you less than one that says what went wrong."""
    monkeypatch.setattr("app.main.daytona_available", lambda: True)
    monkeypatch.setattr(
        "app.daytona_runner.DaytonaSimulationRunner.prepare",
        lambda self: (_ for _ in ()).throw(RuntimeError("api key rejected")),
    )
    body = client.get("/api/health?deep=1").json()
    assert body["status"] == "degraded"
    assert body["daytona"]["status"] == "unavailable"
    assert "api key rejected" not in json.dumps(body), "probe must not leak detail"


def test_deep_health_says_when_daytona_is_not_configured(client, monkeypatch):
    monkeypatch.setattr("app.main.daytona_available", lambda: False)
    body = client.get("/api/health?deep=1").json()
    assert body["daytona"]["status"] == "not_configured"
    assert body["status"] == "ok"  # local execution is a valid mode, not a fault
