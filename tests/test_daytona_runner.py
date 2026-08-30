"""Tests for the Daytona execution layer.

These run without credentials or network. A fake sandbox stands in for the SDK
and executes the real `sandbox_entry.py` in a real flat temp directory - the
same layout a sandbox sees - so the parts we can test offline (the flat-layout
import fallback, the stdout contract, result parsing, seed validation, fork
fallback, cleanup) are genuinely exercised rather than mocked away.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pytest

from app.daytona_runner import (
    ISOLATION_INDEPENDENT,
    ISOLATION_NATIVE_FORK,
    MODEL_FILES,
    DaytonaExecutionError,
    DaytonaSimulationRunner,
    fork_and_run_scenarios,
    parse_sandbox_output,
    validate_monte_carlo_result,
)
from app.monte_carlo import AGGREGATED_METRICS, rollout_seed, run_monte_carlo
from app.sandbox_entry import RESULT_BEGIN, RESULT_END
from app.scenario_runner import BASELINE_CONFIG, apply_overrides

FAST = dict(BASELINE_CONFIG, simulation_days=5)
N = 5
SEED = 4242


# --------------------------------------------------------------------------
# A fake sandbox that runs the real entry point in a real flat directory
# --------------------------------------------------------------------------

class FakeFs:
    def __init__(self, root: Path):
        self.root = root

    def upload_files(self, uploads):
        for upload in uploads:
            dest = self.root / Path(upload.destination).name
            data = upload.source
            dest.write_bytes(data if isinstance(data, bytes) else Path(data).read_bytes())


class FakeProcess:
    def __init__(self, root: Path):
        self.root = root

    def exec(self, command, cwd=None, timeout=None):
        proc = subprocess.run(
            [sys.executable, "sandbox_entry.py", "payload.json"],
            cwd=self.root, capture_output=True, text=True, timeout=timeout,
        )

        class Response:
            exit_code = proc.returncode
            result = proc.stdout + proc.stderr

        return Response()


class FakeSandbox:
    """Stands in for daytona.Sandbox. `can_fork=False` simulates fork being
    unavailable, which must trigger the honest fallback."""

    def __init__(self, tmp_root: Path, name: str, can_fork: bool = True):
        self.id = name
        self.root = tmp_root / name
        self.root.mkdir(parents=True, exist_ok=True)
        self.can_fork = can_fork
        self.deleted = False
        self._tmp_root = tmp_root
        self.fs = FakeFs(self.root)
        self.process = FakeProcess(self.root)

    def fork(self, name=None):
        if not self.can_fork:
            raise RuntimeError("fork not supported on this plan")
        child = FakeSandbox(
            self._tmp_root, f"{name or self.id}-{uuid.uuid4().hex[:8]}", self.can_fork
        )
        # copy-on-write stand-in: the fork starts from the parent's filesystem
        # (files only - a real fork also carries __pycache__, which is harmless)
        for item in self.root.iterdir():
            if item.is_file():
                (child.root / item.name).write_bytes(item.read_bytes())
        return child

    def delete(self):
        self.deleted = True


class FakeClient:
    def __init__(self, tmp_root: Path, can_fork: bool = True):
        self.tmp_root = tmp_root
        self.can_fork = can_fork
        self.created: list[FakeSandbox] = []
        self._lock = threading.Lock()

    def create(self, params=None, **kwargs):
        # Unique ids under concurrency, as real sandbox ids are: scenarios are
        # forked and driven in parallel.
        with self._lock:
            sandbox = FakeSandbox(self.tmp_root, f"sbx-{uuid.uuid4().hex[:8]}", self.can_fork)
            self.created.append(sandbox)
        return sandbox


@pytest.fixture
def runner(tmp_path):
    r = DaytonaSimulationRunner(api_key="test-key")
    r._client = FakeClient(tmp_path)
    return r


@pytest.fixture
def no_fork_runner(tmp_path):
    r = DaytonaSimulationRunner(api_key="test-key")
    r._client = FakeClient(tmp_path, can_fork=False)
    return r


# --------------------------------------------------------------------------
# The model files that get uploaded
# --------------------------------------------------------------------------

def test_uploaded_model_files_exist_and_are_stdlib_only():
    for src, _dst in MODEL_FILES:
        assert src.exists(), f"{src} is uploaded to sandboxes but does not exist"
    banned = ("import numpy", "import pandas", "import daytona", "from daytona")
    for src, _dst in MODEL_FILES:
        text = src.read_text()
        for token in banned:
            assert token not in text, f"{src.name} must stay dependency-free ({token})"


def test_simulator_does_not_import_daytona():
    """The simulator must not know Daytona exists (prose in docstrings aside)."""
    import ast

    tree = ast.parse((MODEL_FILES[0][0]).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "daytona" not in imported
    assert imported <= {"hashlib", "json", "math", "random", "sys", "typing",
                        "__future__"}, f"non-stdlib import: {imported}"


# --------------------------------------------------------------------------
# Result parsing
# --------------------------------------------------------------------------

def test_parse_extracts_the_marked_block_and_ignores_noise():
    payload = {"ok": True, "result": {"x": 1}}
    output = (
        "warning: some unrelated runtime chatter\n"
        f"{RESULT_BEGIN}\n{json.dumps(payload)}\n{RESULT_END}\ntrailing noise\n"
    )
    assert parse_sandbox_output(output)["result"] == {"x": 1}


def test_parse_rejects_missing_markers():
    with pytest.raises(DaytonaExecutionError, match="did not contain"):
        parse_sandbox_output('{"ok": true}')


def test_parse_rejects_invalid_json():
    with pytest.raises(DaytonaExecutionError, match="not valid JSON"):
        parse_sandbox_output(f"{RESULT_BEGIN}\nnot json\n{RESULT_END}")


def test_parse_surfaces_a_sandbox_side_failure():
    payload = {"ok": False, "error": "ValueError: boom", "traceback": "..."}
    with pytest.raises(DaytonaExecutionError, match="ValueError: boom"):
        parse_sandbox_output(f"{RESULT_BEGIN}\n{json.dumps(payload)}\n{RESULT_END}")


def test_parse_rejects_empty_output():
    with pytest.raises(DaytonaExecutionError):
        parse_sandbox_output(None)


# --------------------------------------------------------------------------
# Result validation
# --------------------------------------------------------------------------

def good_result(n_runs=N, base_seed=SEED):
    mc = run_monte_carlo(FAST, n_runs=n_runs, base_seed=base_seed)
    return json.loads(json.dumps(mc))  # round-trip, as it would be over the wire


def test_validation_accepts_a_well_formed_result():
    validate_monte_carlo_result(good_result(), N, SEED)


def test_validation_rejects_a_wrong_rollout_count():
    result = good_result()
    result["n_runs"] = N + 1
    with pytest.raises(DaytonaExecutionError, match="rollouts"):
        validate_monte_carlo_result(result, N, SEED)


def test_validation_rejects_missing_metrics():
    result = good_result()
    del result["stats"][AGGREGATED_METRICS[0]]
    with pytest.raises(DaytonaExecutionError, match="missing metrics"):
        validate_monte_carlo_result(result, N, SEED)


def test_validation_rejects_results_from_different_futures():
    """The seed check is what keeps a cross-sandbox comparison paired."""
    result = good_result()
    result["seeds"][2] = rollout_seed(SEED + 1, 2)
    with pytest.raises(DaytonaExecutionError, match="different rollout seeds"):
        validate_monte_carlo_result(result, N, SEED)


def test_validation_rejects_an_impossible_failure_probability():
    result = good_result()
    result["failure_probability"] = 1.4
    with pytest.raises(DaytonaExecutionError, match="failure_probability"):
        validate_monte_carlo_result(result, N, SEED)


@pytest.mark.parametrize("key", ["stats", "failure_probability", "n_runs", "seeds"])
def test_validation_requires_every_top_level_field(key):
    result = good_result()
    del result[key]
    with pytest.raises(DaytonaExecutionError, match=key):
        validate_monte_carlo_result(result, N, SEED)


# --------------------------------------------------------------------------
# Lifecycle against the fake sandbox
# --------------------------------------------------------------------------

def test_prepare_uploads_every_model_file(runner):
    sandbox = runner.prepare()
    uploaded = {p.name for p in sandbox.root.iterdir()}
    assert uploaded == {dst for _src, dst in MODEL_FILES}
    assert "create_baseline_s" in runner.timings
    assert "upload_s" in runner.timings


def test_run_executes_the_entry_point_and_returns_a_parsed_result(runner):
    sandbox = runner.prepare()
    parsed = runner.run(sandbox, {
        "mode": "monte_carlo", "config": FAST, "n_runs": N,
        "base_seed": SEED, "name": "baseline",
    })
    assert parsed["ok"] is True
    validate_monte_carlo_result(parsed["result"], N, SEED)
    assert parsed["host_roundtrip_seconds"] > 0


def test_sandbox_result_is_identical_to_the_in_process_result(runner):
    """The point of the whole exercise: isolation must not change the numbers."""
    sandbox = runner.prepare()
    remote = runner.run(sandbox, {
        "mode": "monte_carlo", "config": FAST, "n_runs": N,
        "base_seed": SEED, "name": "baseline",
    })["result"]
    local = run_monte_carlo(FAST, n_runs=N, base_seed=SEED)
    assert remote["seeds"] == local["seeds"]
    for metric in AGGREGATED_METRICS:
        assert remote["stats"][metric] == pytest.approx(local["stats"][metric])
    assert remote["failure_probability"] == local["failure_probability"]


def test_single_simulate_mode_round_trips(runner):
    sandbox = runner.prepare()
    parsed = runner.run(sandbox, {"mode": "simulate", "config": FAST, "seed": 7})
    from reference.co2_simulation import simulate
    assert parsed["result"]["metrics"] == pytest.approx(simulate(FAST, 7)["metrics"])


def test_an_invalid_config_fails_loudly_with_the_sandbox_traceback(runner):
    sandbox = runner.prepare()
    with pytest.raises(DaytonaExecutionError) as excinfo:
        runner.run(sandbox, {"mode": "simulate", "config": {"tank_count": 0}})
    assert "tank_count" in str(excinfo.value)


def test_fork_produces_an_independent_sandbox_with_the_same_files(runner):
    runner.prepare()
    forked = runner.fork("extra_tank")
    assert forked.id != runner.baseline_sandbox.id
    assert {p.name for p in forked.root.iterdir()} == {dst for _src, dst in MODEL_FILES}
    assert runner.isolation_mode == ISOLATION_NATIVE_FORK


def test_fork_before_prepare_is_an_error(runner):
    with pytest.raises(DaytonaExecutionError, match="prepare"):
        runner.fork("x")


def test_fork_failure_falls_back_and_says_so(no_fork_runner):
    """We never claim a native fork we did not perform."""
    no_fork_runner.prepare()
    sandbox = no_fork_runner.fork("extra_tank")
    assert no_fork_runner.isolation_mode == ISOLATION_INDEPENDENT
    assert {p.name for p in sandbox.root.iterdir()} == {dst for _src, dst in MODEL_FILES}


def test_cleanup_deletes_every_sandbox(runner):
    runner.prepare()
    runner.fork("a")
    runner.fork("b")
    created = list(runner._sandboxes)
    assert len(created) == 3
    runner.cleanup()
    assert all(s.deleted for s in created)
    assert runner._sandboxes == []


def test_context_manager_cleans_up_even_on_error(tmp_path):
    r = DaytonaSimulationRunner(api_key="k")
    r._client = FakeClient(tmp_path)
    with pytest.raises(ValueError):
        with r:
            r.prepare()
            created = list(r._sandboxes)
            raise ValueError("boom")
    assert all(s.deleted for s in created)


def test_cleanup_survives_a_failing_delete(runner):
    runner.prepare()

    def boom():
        raise RuntimeError("delete failed")

    runner.baseline_sandbox.delete = boom
    runner.cleanup()  # must not raise
    assert runner._sandboxes == []


def test_missing_api_key_gives_an_actionable_error():
    r = DaytonaSimulationRunner(api_key=None)
    r.api_key = None
    with pytest.raises(DaytonaExecutionError, match="DAYTONA_API_KEY"):
        _ = r.client


# --------------------------------------------------------------------------
# Fork-per-scenario orchestration
# --------------------------------------------------------------------------

def prepared_scenarios():
    return [
        {"name": "extra_tank", "label": "Extra tank", "overrides": {"tank_count": 3},
         "config": apply_overrides(FAST, {"tank_count": 3})},
        {"name": "larger_tanker", "label": "Larger tanker",
         "overrides": {"tanker_capacity_t": 36.0},
         "config": apply_overrides(FAST, {"tanker_capacity_t": 36.0})},
    ]


def test_fork_and_run_executes_every_scenario_in_its_own_sandbox(runner):
    out = fork_and_run_scenarios(
        apply_overrides(FAST, None), prepared_scenarios(),
        n_runs=N, base_seed=SEED, with_representative_run=False, runner=runner,
    )
    assert set(out["scenarios"]) == {"extra_tank", "larger_tanker"}
    assert out["isolation_mode"] == ISOLATION_NATIVE_FORK
    # one baseline sandbox + one per scenario
    assert len(runner._sandboxes) == 3
    ids = {out["baseline_sandbox_id"]} | {r["sandbox_id"] for r in out["scenarios"].values()}
    assert len(ids) == 3, "each scenario must run in its own sandbox"


def test_fork_and_run_keeps_scenarios_paired_with_the_baseline(runner):
    out = fork_and_run_scenarios(
        apply_overrides(FAST, None), prepared_scenarios(),
        n_runs=N, base_seed=SEED, with_representative_run=False, runner=runner,
    )
    baseline_seeds = out["baseline"]["seeds"]
    for result in out["scenarios"].values():
        assert result["seeds"] == baseline_seeds


def test_fork_and_run_matches_the_local_pipeline_exactly(runner):
    """Executing in sandboxes must not move a single number."""
    from app.scenario_runner import compare_scenarios

    scenarios = [
        {"name": "extra_tank", "label": "Extra tank", "overrides": {"tank_count": 3},
         "economics": {"capex_gbp": 80000.0}},
    ]
    prepared = [dict(s, config=apply_overrides(FAST, s["overrides"])) for s in scenarios]
    remote = fork_and_run_scenarios(
        apply_overrides(FAST, None), prepared, n_runs=N, base_seed=SEED,
        with_representative_run=False, runner=runner,
    )
    local = compare_scenarios(FAST, scenarios, n_runs=N, base_seed=SEED,
                              include_representative_run=False)
    assert remote["baseline"]["stats"]["lost_production_t"] == pytest.approx(
        local["baseline"]["stats"]["lost_production_t"]
    )
    assert remote["scenarios"]["extra_tank"]["stats"]["lost_production_t"] == pytest.approx(
        local["scenarios"][0]["stats"]["lost_production_t"]
    )


def test_fork_and_run_reports_timings(runner):
    out = fork_and_run_scenarios(
        apply_overrides(FAST, None), prepared_scenarios(),
        n_runs=N, base_seed=SEED, with_representative_run=False, runner=runner,
    )
    assert {"create_baseline_s", "upload_s", "baseline_exec_s", "forks_exec_s",
            "total_s"} <= set(out["timings"])


def test_pipeline_daytona_mode_produces_the_same_decision_as_local(runner, monkeypatch):
    from app import pipeline

    scenarios = [
        {"name": "extra_tank", "label": "Extra tank", "overrides": {"tank_count": 3},
         "economics": {"capex_gbp": 80000.0, "annual_opex_delta_gbp": 1500.0,
                       "cost_per_collection_gbp": 400.0}},
    ]
    monkeypatch.setattr(
        "app.daytona_runner.DaytonaSimulationRunner", lambda **kw: runner
    )
    remote = pipeline.run_decision_pipeline(
        FAST, scenarios, n_runs=N, base_seed=SEED, execution="daytona",
        include_representative_run=False,
    )
    local = pipeline.run_decision_pipeline(
        FAST, scenarios, n_runs=N, base_seed=SEED, execution="local",
        include_representative_run=False,
    )
    assert remote["execution"]["mode"] == "daytona"
    assert remote["execution"]["isolation_mode"] == ISOLATION_NATIVE_FORK
    assert local["execution"]["mode"] == "local"
    assert remote["ranking"] == local["ranking"]
    assert remote["recommendation"] == local["recommendation"]


def test_pipeline_rejects_an_unknown_execution_mode():
    from app import pipeline
    with pytest.raises(ValueError, match="unknown execution mode"):
        pipeline.run_decision_pipeline(FAST, [], execution="magic")
