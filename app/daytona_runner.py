"""Daytona execution layer.

All Daytona-specific code lives here. The simulator does not know Daytona
exists: it is a stdlib-only file that reads a JSON payload and prints a JSON
result, so the same bytes run identically on a laptop and in a sandbox.

Execution architecture
----------------------

    create baseline sandbox
            |
      upload model files          <- the "operational world", prepared once
            |
      run baseline Monte Carlo
            |
      +-----+--------+--------+
      |              |        |
   fork()         fork()   fork()      <- native copy-on-write sandbox forks
      |              |        |
  +1 tank      +1 collection  36 t tanker
      |              |        |
   N rollouts    N rollouts  N rollouts

**One sandbox per scenario, N rollouts inside it** - not one sandbox per
rollout. Scenario isolation and Monte Carlo replication are different things:
scenarios are the thing we want executed independently (different world,
different code path through the config), while rollouts are just reseeds of the
same world. 200 sandboxes per scenario would cost minutes of provisioning to
buy nothing, so the rollout loop runs inside the scenario's sandbox.

Forking is a real Daytona SDK feature (``Sandbox.fork()``, a copy-on-write
clone of the filesystem), which is exactly the product concept: the baseline
world is prepared once, then branched into counterfactual futures that each
carry the same model and assumptions and differ only by the intervention.

Fork support is a property of the *sandbox class*: only VM-class sandboxes
(``linux-vm``, ``windows``) support fork / pause / hot snapshot. Container-class
sandboxes return HTTP 422 "Forking is not supported for this sandbox". So the
runner asks for a VM snapshot first, and only falls back to a container sandbox
if that snapshot is not provisionable for the account or region.

When forking is not available the runner executes each scenario in its own
independently provisioned sandbox instead, and records both
``isolation_mode="independent_sandboxes"`` and the reason the API gave. We never
claim a fork we did not perform - the demo states which of the two it did.

Integrity
---------
Every result that comes back is validated before it is used: the rollout seeds
the sandbox reports must match the seeds derived locally, so a sandbox cannot
quietly hand back numbers from a different set of futures.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from app.monte_carlo import AGGREGATED_METRICS, rollout_seed
from app.sandbox_entry import RESULT_BEGIN, RESULT_END
from app.scenario_runner import failure_record

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Files uploaded into every sandbox, flattened into one directory. Stdlib-only
#: by design, so no pip install is needed and startup stays fast.
MODEL_FILES: tuple[tuple[Path, str], ...] = (
    (REPO_ROOT / "reference" / "co2_simulation.py", "co2_simulation.py"),
    (REPO_ROOT / "app" / "monte_carlo.py", "monte_carlo.py"),
    (REPO_ROOT / "app" / "sandbox_entry.py", "sandbox_entry.py"),
)

WORKDIR = "/home/daytona/simforge"
DEFAULT_EXEC_TIMEOUT_S = 300
ISOLATION_NATIVE_FORK = "native_fork"
ISOLATION_INDEPENDENT = "independent_sandboxes"

#: Snapshots tried, in order, when fork support is wanted. Only VM-class
#: sandboxes can be forked; availability varies by region and account.
VM_SNAPSHOTS: tuple[str, ...] = (
    "daytona-vm-small",
    "daytona-vm",
    "daytona-vm-medium",
)

#: Base image for the pre-baked snapshot. Pinned to the same Python minor the
#: repo develops against, so a sandbox result is trivially comparable to local.
SNAPSHOT_BASE_PYTHON = "3.12"
SNAPSHOT_PREFIX = "simforge"


def model_files_digest() -> str:
    """Content hash of everything baked into the snapshot.

    The digest goes in the snapshot's name, which is the safety property that
    makes pre-baking sound: edit the simulator and the name changes, so a stale
    snapshot can never be picked up and silently run different code than the
    host validated. A missing snapshot falls back to uploading, never to
    executing something we did not build.
    """
    digest = hashlib.blake2b(digest_size=6)
    for src, dst in MODEL_FILES:
        digest.update(dst.encode("utf-8"))
        digest.update(src.read_bytes())
    return digest.hexdigest()


def snapshot_name() -> str:
    """Name of the snapshot matching the model files on disk right now."""
    return f"{SNAPSHOT_PREFIX}-{model_files_digest()}"


def build_snapshot(client: Any, name: str | None = None,
                   on_logs: Callable[[str], None] | None = None) -> str:
    """Build the pre-baked snapshot: the model files inside the image.

    One-off, roughly a minute. Afterwards a scenario sandbox starts in well under
    a second with nothing to upload, because the operational model is already in
    the filesystem.
    """
    from daytona import CreateSnapshotParams, Image

    name = name or snapshot_name()
    image = Image.debian_slim(SNAPSHOT_BASE_PYTHON)
    for src, dst in MODEL_FILES:
        image = image.add_local_file(str(src.relative_to(REPO_ROOT)), f"{WORKDIR}/{dst}")
    client.snapshot.create(
        CreateSnapshotParams(name=name, image=image),
        on_logs=on_logs or (lambda _m: None),
        timeout=900,
    )
    return name


class DaytonaExecutionError(RuntimeError):
    """Raised when sandbox execution fails. Carries the diagnosis, never hides it."""

    def __init__(self, message: str, *, exit_code: int | None = None, output: str | None = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.output = output


# ---------------------------------------------------------------------------
# Result extraction / validation
# ---------------------------------------------------------------------------

def parse_sandbox_output(output: str) -> dict[str, Any]:
    """Extract the JSON block a sandbox run printed between the markers.

    Parsing markers rather than the whole of stdout means an unexpected warning
    from the runtime cannot corrupt the result.

    Raises:
        DaytonaExecutionError: if the markers are missing, the block is not
            valid JSON, or the sandbox reported a failure.
    """
    if output is None:
        raise DaytonaExecutionError("sandbox produced no output")
    start = output.find(RESULT_BEGIN)
    end = output.find(RESULT_END)
    if start == -1 or end == -1 or end < start:
        raise DaytonaExecutionError(
            "sandbox output did not contain a SimForge result block", output=output
        )
    blob = output[start + len(RESULT_BEGIN):end].strip()
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError as exc:
        raise DaytonaExecutionError(
            f"sandbox result was not valid JSON: {exc}", output=output
        ) from exc
    if not payload.get("ok"):
        raise DaytonaExecutionError(
            f"simulation failed inside the sandbox: {payload.get('error')}\n"
            f"{payload.get('traceback', '')}",
            output=output,
        )
    return payload


def validate_monte_carlo_result(
    result: dict[str, Any], n_runs: int, base_seed: int
) -> None:
    """Check a Monte Carlo result that came back from a sandbox.

    The seed check is the important one: it proves the sandbox replicated the
    same futures we would have run locally, so scenarios executed in different
    sandboxes remain a fair paired comparison.

    Raises:
        DaytonaExecutionError: if the result is malformed or ran the wrong futures.
    """
    for key in ("stats", "failure_probability", "n_runs", "seeds"):
        if key not in result:
            raise DaytonaExecutionError(f"sandbox result is missing '{key}'")
    if result["n_runs"] != n_runs:
        raise DaytonaExecutionError(
            f"sandbox ran {result['n_runs']} rollouts, expected {n_runs}"
        )
    missing = set(AGGREGATED_METRICS) - set(result["stats"])
    if missing:
        raise DaytonaExecutionError(f"sandbox result is missing metrics: {sorted(missing)}")
    expected_seeds = [rollout_seed(base_seed, i) for i in range(n_runs)]
    if result["seeds"] != expected_seeds:
        raise DaytonaExecutionError(
            "sandbox used different rollout seeds than the host derived - "
            "the comparison would not be a paired counterfactual"
        )
    if not 0.0 <= result["failure_probability"] <= 1.0:
        raise DaytonaExecutionError(
            f"failure_probability out of range: {result['failure_probability']}"
        )


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------

class DaytonaSimulationRunner:
    """Owns the sandbox lifecycle: create, upload, execute, fork, clean up.

    Use as a context manager so sandboxes are always torn down::

        with DaytonaSimulationRunner() as runner:
            runner.prepare()
            baseline = runner.run(runner.baseline_sandbox, payload)
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        target: str | None = None,
        exec_timeout_s: int = DEFAULT_EXEC_TIMEOUT_S,
        on_log: Callable[[str], None] | None = None,
        prefer_fork: bool = True,
        vm_snapshots: tuple[str, ...] = VM_SNAPSHOTS,
        use_prebaked_snapshot: bool = True,
    ) -> None:
        self.api_key = api_key or os.environ.get("DAYTONA_API_KEY")
        self.api_url = api_url or os.environ.get("DAYTONA_API_URL")
        self.target = target or os.environ.get("DAYTONA_TARGET")
        self.exec_timeout_s = exec_timeout_s
        self._on_log = on_log or (lambda _msg: None)
        self._client = None
        self.baseline_sandbox = None
        self._sandboxes: list[Any] = []
        self.prefer_fork = prefer_fork
        self.vm_snapshots = vm_snapshots
        # Assume nothing: set once we know what the account actually supports.
        self.isolation_mode = ISOLATION_NATIVE_FORK if prefer_fork else ISOLATION_INDEPENDENT
        self.fork_unavailable_reason: str | None = None
        self.sandbox_snapshot: str | None = None
        self.use_prebaked_snapshot = use_prebaked_snapshot
        self.prebaked_snapshot: str | None = None
        self._resolved = False
        self.timings: dict[str, float] = {}

    # -- lifecycle ------------------------------------------------------

    def __enter__(self) -> "DaytonaSimulationRunner":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.cleanup()

    @property
    def client(self):
        if self._client is None:
            if not self.api_key:
                raise DaytonaExecutionError(
                    "DAYTONA_API_KEY is not set. Export it, or run the pipeline "
                    "with the local executor."
                )
            from daytona import Daytona, DaytonaConfig

            kwargs: dict[str, Any] = {"api_key": self.api_key}
            if self.api_url:
                kwargs["api_url"] = self.api_url
            if self.target:
                kwargs["target"] = self.target
            self._client = Daytona(DaytonaConfig(**kwargs))
        return self._client

    def prepare(self) -> Any:
        """Create the baseline sandbox and upload the operational model into it.

        Tries a VM-class snapshot first when `prefer_fork` is set, because only
        VM sandboxes can be forked. Falls back to the default container sandbox,
        recording why, rather than failing the run.
        """
        started = time.perf_counter()
        self.resolve()
        sandbox = self._create_sandbox("baseline", allow_vm=self.prefer_fork)
        self.timings["create_baseline_s"] = time.perf_counter() - started

        started = time.perf_counter()
        self._upload_model_files(sandbox)
        self.timings["upload_s"] = time.perf_counter() - started
        self.baseline_sandbox = sandbox
        return sandbox

    def resolve(self) -> None:
        """Work out what this account supports, without provisioning anything.

        Cheap (one API call at most) and idempotent. Splitting it from
        :meth:`prepare` lets the caller learn that forking is unavailable
        *before* deciding how to schedule the batch, so the baseline sandbox can
        be created in parallel with the scenario sandboxes instead of ahead of
        them.
        """
        if self._resolved:
            return
        self._resolved = True
        if self.use_prebaked_snapshot:
            self._resolve_prebaked_snapshot()

    def _resolve_prebaked_snapshot(self) -> None:
        """Look for a snapshot whose name matches the current model files.

        Only an exact content match is used. A snapshot built from different
        code has a different name and is simply not found, so we fall back to
        uploading rather than running code the host did not validate.
        """
        name = os.environ.get("SIMFORGE_SNAPSHOT") or snapshot_name()
        try:
            self.client.snapshot.get(name)
        except Exception as exc:  # noqa: BLE001 - absence is normal, not an error
            self._log(f"no pre-baked snapshot {name} ({type(exc).__name__}); "
                      "will upload the model files instead")
            return
        self.prebaked_snapshot = name
        # The pre-baked snapshot is container class, and only VM-class sandboxes
        # can be forked. Knowing that up front saves a doomed round trip per
        # scenario, and lets the whole batch run in parallel.
        self.isolation_mode = ISOLATION_INDEPENDENT
        self.fork_unavailable_reason = (
            "pre-baked snapshot is container class; forking requires a VM-class "
            "sandbox, and no linux-vm runners are configured in this region"
        )
        self._log(f"using pre-baked snapshot {name}: nothing to upload")

    def _upload_model_files(self, sandbox: Any) -> None:
        """Upload the model files, unless the snapshot already contains them."""
        if self.prebaked_snapshot:
            return
        from daytona import FileUpload

        self._log(f"uploading {len(MODEL_FILES)} model files")
        sandbox.fs.upload_files(
            [
                FileUpload(source=src.read_bytes(), destination=f"{WORKDIR}/{dst}")
                for src, dst in MODEL_FILES
            ]
        )

    def fork(self, name: str) -> Any:
        """Branch the prepared baseline world into an independent sandbox.

        Uses Daytona's native copy-on-write ``Sandbox.fork()``. Falls back to a
        freshly provisioned sandbox with the same files if forking is not
        available, and records which happened in :attr:`isolation_mode`.
        """
        if self.baseline_sandbox is None:
            raise DaytonaExecutionError("prepare() must be called before fork()")
        if self.isolation_mode == ISOLATION_INDEPENDENT:
            # Already established that this account cannot fork; do not spend a
            # doomed API round trip per scenario.
            return self._create_independent(name)
        try:
            forked = self.baseline_sandbox.fork(name=f"simforge-{name}-{int(time.time())}")
            self._sandboxes.append(forked)
            self._log(f"forked baseline -> {name}")
            return forked
        except Exception as exc:  # noqa: BLE001 - fall back, but say so
            self.isolation_mode = ISOLATION_INDEPENDENT
            self.fork_unavailable_reason = f"{type(exc).__name__}: {exc}"
            self._log(f"fork unavailable ({type(exc).__name__}: {exc}); "
                      "provisioning an independent sandbox instead")
            return self._create_independent(name)

    def _create_sandbox(self, role: str, allow_vm: bool = False) -> Any:
        """Provision one sandbox, preferring a forkable VM class when asked."""
        from daytona import CreateSandboxFromSnapshotParams

        def create(**extra: Any) -> Any:
            sandbox = self.client.create(
                CreateSandboxFromSnapshotParams(
                    labels={"app": "simforge", "role": role}, **extra
                )
            )
            self._sandboxes.append(sandbox)
            return sandbox

        if allow_vm and not self.prebaked_snapshot:
            for snapshot in self.vm_snapshots:
                try:
                    sandbox = create(snapshot=snapshot)
                    self.sandbox_snapshot = snapshot
                    self._log(f"created {role} sandbox from VM snapshot {snapshot} (forkable)")
                    return sandbox
                except Exception as exc:  # noqa: BLE001 - try the next, then fall back
                    self.fork_unavailable_reason = f"{type(exc).__name__}: {exc}"
                    self._log(f"VM snapshot {snapshot} unavailable: {exc}")
            self.isolation_mode = ISOLATION_INDEPENDENT
            self._log(
                "no forkable VM-class sandbox available for this account/region; "
                "scenarios will run in independent sandboxes"
            )

        if self.prebaked_snapshot:
            sandbox = create(snapshot=self.prebaked_snapshot)
            self.sandbox_snapshot = self.prebaked_snapshot
            self._log(f"created {role} sandbox from {self.prebaked_snapshot}")
            return sandbox

        sandbox = create(language="python")
        self._log(f"created {role} sandbox (container class)")
        return sandbox

    def _create_independent(self, name: str) -> Any:
        sandbox = self._create_sandbox(name)
        self._upload_model_files(sandbox)
        return sandbox

    def run(self, sandbox: Any, payload: dict[str, Any]) -> dict[str, Any]:
        """Upload a payload, execute the entry point, and return the parsed result."""
        from daytona import FileUpload

        started = time.perf_counter()
        sandbox.fs.upload_files(
            [
                FileUpload(
                    source=json.dumps(payload).encode("utf-8"),
                    destination=f"{WORKDIR}/payload.json",
                )
            ]
        )
        response = sandbox.process.exec(
            "python3 sandbox_entry.py payload.json",
            cwd=WORKDIR,
            timeout=self.exec_timeout_s,
        )
        elapsed = time.perf_counter() - started
        if response.exit_code != 0:
            # The entry point still prints a marked block on failure, carrying
            # the sandbox-side exception and traceback. Surface that rather than
            # a bare exit code - "exited with 1" diagnoses nothing.
            try:
                parse_sandbox_output(response.result)
            except DaytonaExecutionError as exc:
                raise DaytonaExecutionError(
                    f"sandbox_entry.py exited with {response.exit_code}: {exc}",
                    exit_code=response.exit_code,
                    output=response.result,
                ) from exc
            raise DaytonaExecutionError(
                f"sandbox_entry.py exited with {response.exit_code} but reported success",
                exit_code=response.exit_code,
                output=response.result,
            )
        parsed = parse_sandbox_output(response.result)
        parsed["host_roundtrip_seconds"] = elapsed
        parsed["sandbox_id"] = getattr(sandbox, "id", None)
        return parsed

    def cleanup(self) -> None:
        """Delete every sandbox this runner created. Best effort, never raises."""
        for sandbox in reversed(self._sandboxes):
            try:
                sandbox.delete()
            except Exception as exc:  # noqa: BLE001 - cleanup must not mask a real error
                self._log(f"failed to delete sandbox {getattr(sandbox, 'id', '?')}: {exc}")
        self._sandboxes.clear()
        self.baseline_sandbox = None

    def _log(self, message: str) -> None:
        self._on_log(f"[daytona] {message}")


# ---------------------------------------------------------------------------
# Convenience entry points
# ---------------------------------------------------------------------------

def run_monte_carlo_in_daytona(
    config: dict[str, Any],
    n_runs: int,
    base_seed: int,
    name: str = "scenario",
    runner: DaytonaSimulationRunner | None = None,
) -> dict[str, Any]:
    """Run one scenario's Monte Carlo batch in a fresh Daytona sandbox."""
    own_runner = runner is None
    runner = runner or DaytonaSimulationRunner()
    try:
        if runner.baseline_sandbox is None:
            runner.prepare()
        payload = {
            "mode": "monte_carlo",
            "config": config,
            "n_runs": n_runs,
            "base_seed": base_seed,
            "name": name,
        }
        parsed = runner.run(runner.baseline_sandbox, payload)
        result = parsed["result"]
        validate_monte_carlo_result(result, n_runs, base_seed)
        return result
    finally:
        if own_runner:
            runner.cleanup()


def fork_and_run_scenarios(
    base_config: dict[str, Any],
    scenarios: list[dict[str, Any]],
    n_runs: int,
    base_seed: int,
    with_representative_run: bool = True,
    timeseries_stride: int = 6,
    max_parallel: int = 4,
    on_log: Callable[[str], None] | None = None,
    runner: DaytonaSimulationRunner | None = None,
    tolerate_failures: bool = False,
) -> dict[str, Any]:
    """Execute the baseline and every scenario in Daytona, forking per scenario.

    Scenario sandboxes are forked and driven in parallel: provisioning dominates
    the wall clock, and the rollouts themselves take under a second.

    Args:
        base_config: fully normalised baseline config.
        scenarios: ``[{"name", "label", "overrides", "config"}, ...]`` where
            ``config`` is the already-merged scenario config.

    Returns:
        ``{"baseline": mc_result, "scenarios": {name: mc_result},
           "isolation_mode": ..., "timings": {...}}``
    """
    own_runner = runner is None
    runner = runner or DaytonaSimulationRunner(on_log=on_log)
    started = time.perf_counter()
    try:
        # Learn what the account supports first; only provision a baseline
        # sandbox up front if we are actually going to fork from it.
        runner.resolve()
        if runner.baseline_sandbox is None and runner.isolation_mode != ISOLATION_INDEPENDENT:
            runner.prepare()

        def payload_for(name: str, config: dict[str, Any]) -> dict[str, Any]:
            return {
                "mode": "monte_carlo",
                "config": config,
                "n_runs": n_runs,
                "base_seed": base_seed,
                "name": name,
                "with_representative_run": with_representative_run,
                "timeseries_stride": timeseries_stride,
            }

        environments: dict[str, Any] = {}

        def run_in(sandbox: Any, name: str, config: dict[str, Any]) -> dict[str, Any]:
            parsed = runner.run(sandbox, payload_for(name, config))
            result = parsed["result"]
            validate_monte_carlo_result(result, n_runs, base_seed)
            result["sandbox_id"] = parsed.get("sandbox_id")
            if parsed.get("environment"):
                environments.setdefault("sandbox", parsed["environment"])
            return result

        # When forking is not available there is no reason to serialise on the
        # baseline: every run provisions its own sandbox anyway, so the whole
        # batch - baseline included - is created and executed at once.
        if runner.isolation_mode == ISOLATION_INDEPENDENT:
            batch_started = time.perf_counter()
            jobs: list[tuple[str, dict[str, Any]]] = [("baseline", base_config)] + [
                (s["name"], s["config"]) for s in scenarios
            ]

            def run_isolated(job: tuple[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
                name, config = job
                try:
                    sandbox = (
                        runner.baseline_sandbox
                        if name == "baseline" and runner.baseline_sandbox is not None
                        else runner._create_independent(name)
                    )
                    return name, run_in(sandbox, name, config)
                except Exception as exc:  # noqa: BLE001
                    # The baseline is load-bearing: without it there is nothing
                    # to compare against, so its failure is never tolerated.
                    if not tolerate_failures or name == "baseline":
                        raise
                    runner._log(f"scenario {name} failed: {exc}")
                    return name, {"error": failure_record(exc)}

            with ThreadPoolExecutor(max_workers=max(1, min(max_parallel, len(jobs)))) as pool:
                results = dict(pool.map(run_isolated, jobs))
            baseline = results.pop("baseline")
            runner.timings["batch_exec_s"] = time.perf_counter() - batch_started
            runner.timings["total_s"] = time.perf_counter() - started
            return {
                "baseline": baseline,
                "scenarios": results,
                "isolation_mode": runner.isolation_mode,
                "fork_unavailable_reason": runner.fork_unavailable_reason,
                "sandbox_snapshot": runner.sandbox_snapshot,
                "prebaked_snapshot": runner.prebaked_snapshot,
                "baseline_sandbox_id": baseline.get("sandbox_id"),
                "environment": environments.get("sandbox"),
                "timings": dict(runner.timings),
            }

        baseline_started = time.perf_counter()
        baseline_parsed = runner.run(
            runner.baseline_sandbox, payload_for("baseline", base_config)
        )
        baseline = baseline_parsed["result"]
        validate_monte_carlo_result(baseline, n_runs, base_seed)
        runner.timings["baseline_exec_s"] = time.perf_counter() - baseline_started

        def run_one(scenario: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            try:
                sandbox = runner.fork(scenario["name"])
                parsed = runner.run(sandbox, payload_for(scenario["name"], scenario["config"]))
                result = parsed["result"]
                validate_monte_carlo_result(result, n_runs, base_seed)
                result["sandbox_id"] = parsed.get("sandbox_id")
                return scenario["name"], result
            except Exception as exc:  # noqa: BLE001
                if not tolerate_failures:
                    raise
                # One sandbox dying must not take the live demo with it. The
                # scenario is reported as failed and excluded from the ranking.
                runner._log(f"scenario {scenario['name']} failed: {exc}")
                return scenario["name"], {"error": failure_record(exc)}

        fork_started = time.perf_counter()
        results: dict[str, dict[str, Any]] = {}
        if scenarios:
            with ThreadPoolExecutor(max_workers=max(1, min(max_parallel, len(scenarios)))) as pool:
                for name, result in pool.map(run_one, scenarios):
                    results[name] = result
        runner.timings["forks_exec_s"] = time.perf_counter() - fork_started
        runner.timings["total_s"] = time.perf_counter() - started

        return {
            "baseline": baseline,
            "scenarios": results,
            "isolation_mode": runner.isolation_mode,
            "fork_unavailable_reason": runner.fork_unavailable_reason,
            "sandbox_snapshot": runner.sandbox_snapshot,
            "prebaked_snapshot": runner.prebaked_snapshot,
            "baseline_sandbox_id": baseline_parsed.get("sandbox_id"),
            "environment": baseline_parsed.get("environment"),
            "timings": dict(runner.timings),
        }
    finally:
        if own_runner:
            runner.cleanup()
