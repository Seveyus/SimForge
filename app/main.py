"""SimForge API — the wiring between the AI/UX half and the simulation layer.

Routes are the ones agreed in `static/fixtures/README.md`:

    POST /api/requirements           natural language -> ModelSpec (AI half)
    POST /api/simulations/baseline   run the validated baseline model
    POST /api/scenarios/compare      run interventions, return the comparison
    GET  /api/health                 liveness + what execution backend is live

Two rules this module exists to enforce:

* **Every number in a response came from the simulator or the finance module.**
  This layer validates, routes and shapes errors. It computes nothing.
* **Errors never leak internals.** Provider traces, generated source,
  credentials and stack traces stay server-side; the client gets the documented
  envelope with a safe message and a `request_id` to correlate with the log.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api_contract import run_baseline, run_scenario_comparison
from app.env import load_env
from app.models import (
    RequirementsRequest,
    ScenarioComparisonRequest,
    ScenarioSuggestionRequest,
    SimulationRequest,
)
from app.pipeline import daytona_available

logger = logging.getLogger("simforge")

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "static"

# HTTP status for each documented error code (static/fixtures/README.md).
ERROR_STATUS: dict[str, int] = {
    "invalid_request": 400,
    "validation_error": 422,
    "gemini_invalid_response": 502,
    "simulation_failed": 502,
    "gemini_unavailable": 503,
    "execution_unavailable": 503,
    "operation_timeout": 504,
    "internal_error": 500,
}

#: Hard ceiling on one simulation request. A Daytona call that hangs must fail
#: the request rather than hold a connection open for the rest of the demo.
REQUEST_TIMEOUT_S = float(os.environ.get("SIMFORGE_REQUEST_TIMEOUT_S", "180"))

SAFE_MESSAGES: dict[str, str] = {
    "invalid_request": "The request could not be read.",
    "validation_error": "The request could not be validated.",
    "simulation_failed": "The simulation could not be completed.",
    "execution_unavailable": "The execution service is unavailable.",
    "operation_timeout": "The operation timed out.",
    "gemini_unavailable": "The modelling service is unavailable.",
    "gemini_invalid_response": "The modelling service returned an unusable response.",
    "internal_error": "Something went wrong.",
}


class ApiError(Exception):
    """An error already classified into the documented envelope."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        field_errors: list[dict[str, str]] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message or SAFE_MESSAGES.get(code, code))
        self.code = code
        self.message = message or SAFE_MESSAGES.get(code, code)
        self.field_errors = field_errors or []
        self.status = ERROR_STATUS.get(code, 500)
        # Clients are told to use `retryable`, not to infer it from the status.
        self.retryable = self.status >= 500 if retryable is None else retryable


def error_response(error: ApiError, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=error.status,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "retryable": error.retryable,
                "field_errors": error.field_errors,
                "request_id": request_id,
            }
        },
    )


def field_errors_from(exc: ValidationError) -> list[dict[str, str]]:
    """Turn pydantic errors into the documented dotted-path field errors.

    Only the location and pydantic's own message are exposed - never the input
    value, which may carry something the user would not want echoed back.
    """
    return [
        {
            "path": ".".join(str(part) for part in err["loc"]) or "body",
            "message": err["msg"],
        }
        for err in exc.errors()[:20]
    ]


def create_app() -> FastAPI:
    load_env()
    app = FastAPI(
        title="SimForge",
        version="0.1.0",
        description="Turn operations into executable worlds.",
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next: Callable):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.warning("api error %s (%s): %s", exc.code, request_id, exc)
        return error_response(exc, request_id)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        # Logged in full server-side, never returned to the client.
        logger.exception("unhandled error (%s)", request_id)
        return error_response(ApiError("internal_error"), request_id)

    # -- routes ---------------------------------------------------------

    @app.get("/api/health")
    async def health(deep: bool = False) -> dict[str, Any]:
        """Liveness, and which execution backend a run would actually use.

        `?deep=1` actually provisions a sandbox and runs one simulation in it.
        Worth doing once before a demo: it is the difference between finding out
        Daytona is unreachable now, and finding out on stage.
        """
        body: dict[str, Any] = {
            "status": "ok",
            "execution": "daytona" if daytona_available() else "local",
            "daytona_configured": daytona_available(),
        }
        if deep:
            body["daytona"] = await run_in_threadpool(probe_daytona)
            # "not_configured" means local execution, which is a valid mode -
            # only an actually unreachable Daytona is a degraded state.
            if body["daytona"]["status"] == "unavailable":
                body["status"] = "degraded"
        return body

    @app.post("/api/simulations/baseline")
    async def simulations_baseline(request: Request) -> dict[str, Any]:
        """Run the validated baseline model. Returns a `SimulationResult`."""
        payload = await read_json(request)
        validated = parse_request(SimulationRequest, payload)
        return await execute(
            run_baseline,
            {
                "model_spec": validated.model_spec.model_dump(mode="json"),
                "seed": validated.seed,
                "rollout_count": validated.rollout_count,
                "execution": execution_mode(request),
            },
        )

    @app.post("/api/scenarios/compare")
    async def scenarios_compare(request: Request) -> dict[str, Any]:
        """Run interventions and return the comparison plus recommendation.

        A scenario that fails does not fail the request: as long as the baseline
        and at least one scenario completed, this returns 200 with the failed
        scenario preserved and the recommendation drawn only from completed
        ones. That behaviour lives in the scenario engine; this route only
        surfaces it.
        """
        payload = await read_json(request)
        validated = parse_request(ScenarioComparisonRequest, payload)
        return await execute(
            run_scenario_comparison,
            {
                "model_spec": validated.model_spec.model_dump(mode="json"),
                "scenarios": [s.model_dump(mode="json") for s in validated.scenarios],
                "seed": validated.seed,
                "rollout_count": validated.rollout_count,
                "execution": execution_mode(request),
            },
        )

    @app.post("/api/requirements")
    async def requirements(request: Request) -> dict[str, Any]:
        """Extract or refine a `ModelSpec` and return clarification questions.

        Delegates to `app.requirements_agent.build_requirements`. Until that
        module lands, this returns the documented `gemini_unavailable` error
        rather than a stub, so the frontend exercises its real error path
        instead of being fed a fake success.
        """
        payload = await read_json(request)
        validated = parse_request(RequirementsRequest, payload)
        return await run_in_threadpool(run_requirements, validated)

    @app.post("/api/scenarios/suggest")
    async def scenarios_suggest(request: Request) -> dict[str, Any]:
        """Return three validated Gemini interventions for explicit user review."""
        payload = await read_json(request)
        validated = parse_request(ScenarioSuggestionRequest, payload)
        return await run_in_threadpool(run_suggestions, validated.model_spec)

    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

async def read_json(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001 - malformed body
        raise ApiError("invalid_request", "The request body is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ApiError("invalid_request", "The request body must be a JSON object.")
    return payload


def parse_request(model: Any, payload: dict[str, Any]) -> Any:
    """Validate a request against the shared contract models."""
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ApiError("validation_error", field_errors=field_errors_from(exc)) from exc


def execution_mode(request: Request) -> str:
    """Let a caller pin the executor with `?execution=local|daytona`.

    A query parameter, not a body field: the request models forbid extra fields,
    and rightly so - the body is the agreed contract and this is a SimForge
    operational control that the frontend never has to send.
    """
    mode = request.query_params.get("execution", "auto")
    if mode not in ("auto", "local", "daytona"):
        raise ApiError(
            "validation_error",
            "Unknown execution mode.",
            field_errors=[{"path": "execution", "message": "must be auto, local or daytona"}],
        )
    return mode


async def execute(fn: Callable[[dict[str, Any]], Any], payload: dict[str, Any]) -> Any:
    """Run a pipeline call off the event loop, under a timeout.

    The pipeline is synchronous and spends seconds in CPU work and Daytona round
    trips. Calling it directly from an `async def` route would block the event
    loop, so a second request - or the frontend fetching the baseline and the
    comparison at once - would stall behind the first.
    """
    try:
        return await asyncio.wait_for(
            run_in_threadpool(run_pipeline, fn, payload), timeout=REQUEST_TIMEOUT_S
        )
    except asyncio.TimeoutError as exc:
        logger.error("request exceeded %.0fs", REQUEST_TIMEOUT_S)
        raise ApiError("operation_timeout") from exc


def run_pipeline(fn: Callable[[dict[str, Any]], Any], payload: dict[str, Any]) -> Any:
    """Run a pipeline call, mapping its failures onto the documented codes."""
    from app.daytona_runner import DaytonaExecutionError

    try:
        return fn(payload)
    except DaytonaExecutionError as exc:
        logger.error("daytona execution failed: %s", exc)
        raise ApiError("execution_unavailable") from exc
    except TimeoutError as exc:
        raise ApiError("operation_timeout") from exc
    except ValueError as exc:
        # A domain constraint the request violated, e.g. an override the
        # simulator does not model. The message is ours, so it is safe to show.
        raise ApiError("validation_error", str(exc)) from exc
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("simulation failed")
        raise ApiError("simulation_failed") from exc


def run_requirements(validated: Any) -> dict[str, Any]:
    """Call the requirements agent, mapping its errors onto the documented codes.

    The agent raises a small typed hierarchy that lines up exactly with the
    error table in `static/fixtures/README.md`, so the mapping is direct. Only
    configuration messages are passed through - they are ours and actionable
    ("GEMINI_MODEL is required"). Provider and schema failures get a generic
    message, because their text can carry prompt or response fragments.
    """
    try:
        # import_module resolves through sys.modules, so the agent can be
        # substituted in tests; `from app import X` would read the attribute
        # already bound on the package and ignore the substitution.
        requirements_agent = importlib.import_module("app.requirements_agent")
    except ImportError as exc:
        raise ApiError(
            "gemini_unavailable",
            "The modelling service is not configured yet.",
            retryable=True,
        ) from exc

    def error(name: str) -> type[BaseException]:
        return getattr(requirements_agent, name, _Unraisable)

    try:
        result = requirements_agent.build_requirements(
            validated.description,
            validated.draft_spec,
            validated.answers,
        )
    except error("RequirementsConfigurationError") as exc:
        # Our own configuration, safe and useful to surface verbatim.
        logger.error("requirements agent misconfigured: %s", exc)
        raise ApiError("gemini_unavailable", str(exc), retryable=False) from exc
    except error("RequirementsInputError") as exc:
        raise ApiError("validation_error", str(exc)) from exc
    except error("RequirementsResponseError") as exc:
        logger.warning("gemini returned unusable output: %s", exc)
        raise ApiError("gemini_invalid_response") from exc
    except error("RequirementsProviderError") as exc:
        logger.warning("gemini unavailable: %s", exc)
        raise ApiError("gemini_unavailable") from exc
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("requirements agent failed")
        raise ApiError("internal_error") from exc

    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result


def run_suggestions(model_spec: Any) -> dict[str, Any]:
    """Call the shared Gemini adapter and expose only validated suggestions."""
    requirements_agent = importlib.import_module("app.requirements_agent")
    try:
        result = requirements_agent.suggest_scenarios(model_spec)
    except getattr(requirements_agent, "RequirementsConfigurationError", _Unraisable) as exc:
        raise ApiError("gemini_unavailable", str(exc), retryable=False) from exc
    except getattr(requirements_agent, "RequirementsResponseError", _Unraisable) as exc:
        logger.warning("gemini returned unusable scenario suggestions: %s", exc)
        raise ApiError("gemini_invalid_response") from exc
    except getattr(requirements_agent, "RequirementsProviderError", _Unraisable) as exc:
        raise ApiError("gemini_unavailable") from exc
    return result.model_dump(mode="json")


class _Unraisable(BaseException):
    """Placeholder for an exception class the agent does not define.

    Lets the `except` chain above stay declarative even if the agent's error
    hierarchy changes: a missing class simply never matches.
    """


def probe_daytona() -> dict[str, Any]:
    """Round-trip one tiny simulation through a real sandbox.

    Never raises: a health check that 500s tells you less than one that reports
    what went wrong.
    """
    import time

    if not daytona_available():
        return {"status": "not_configured",
                "detail": "DAYTONA_API_KEY is not set; runs execute locally"}
    started = time.perf_counter()
    try:
        from app.daytona_runner import DaytonaSimulationRunner

        with DaytonaSimulationRunner() as runner:
            runner.prepare()
            parsed = runner.run(
                runner.baseline_sandbox,
                {"mode": "simulate", "config": {"simulation_days": 1}, "seed": 1},
            )
        return {
            "status": "ok",
            "roundtrip_seconds": round(time.perf_counter() - started, 2),
            "isolation_mode": runner.isolation_mode,
            "fork_unavailable_reason": runner.fork_unavailable_reason,
            "sandbox_python": (parsed.get("environment") or {}).get("python"),
        }
    except Exception as exc:  # noqa: BLE001 - a probe reports, it does not raise
        logger.warning("daytona probe failed: %s", exc)
        return {
            "status": "unavailable",
            "detail": f"{type(exc).__name__}",
            "roundtrip_seconds": round(time.perf_counter() - started, 2),
        }


app = create_app()
