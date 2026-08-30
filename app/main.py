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

import logging
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.api_contract import run_baseline, run_scenario_comparison
from app.env import load_env
from app.models import (
    ScenarioComparisonRequest,
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

SAFE_MESSAGES: dict[str, str] = {
    "invalid_request": "The request could not be read.",
    "validation_error": "The request could not be validated.",
    "simulation_failed": "The simulation could not be completed.",
    "execution_unavailable": "The execution service is unavailable.",
    "operation_timeout": "The operation timed out.",
    "gemini_unavailable": "The modelling service is unavailable.",
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
    async def health() -> dict[str, Any]:
        """Liveness, and which execution backend a run would actually use."""
        return {
            "status": "ok",
            "execution": "daytona" if daytona_available() else "local",
            "daytona_configured": daytona_available(),
        }

    @app.post("/api/simulations/baseline")
    async def simulations_baseline(request: Request) -> dict[str, Any]:
        """Run the validated baseline model. Returns a `SimulationResult`."""
        payload = await read_json(request)
        validated = parse_request(SimulationRequest, payload)
        return run_in_executor(
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
        return run_in_executor(
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

        Delegates to `app.requirements_agent` when it is available. Until that
        module lands this returns the documented `gemini_unavailable` error
        rather than a stub, so the frontend exercises its real error path
        instead of being fed a fake success.
        """
        payload = await read_json(request)
        try:
            from app.requirements_agent import handle_requirements_request
        except ImportError as exc:
            raise ApiError(
                "gemini_unavailable",
                "The modelling service is not configured yet.",
                retryable=True,
            ) from exc
        return handle_requirements_request(payload)

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


def run_in_executor(fn: Callable[[dict[str, Any]], Any], payload: dict[str, Any]) -> Any:
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


app = create_app()
