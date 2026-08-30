# M0 Integration Contract v0.1

Status: frozen on `ebrahim-work` for teammate review.

These fixtures are development data, not simulation output. They define the
proposed boundary between the browser, FastAPI integration layer, requirements
agent and scenario engine. Production code must never silently fall back to
these files.

## Contract Rules

- Requests and responses use `application/json`.
- Required top-level fields may not be renamed or removed within contract v0.x.
- New fields must be optional so each branch can integrate independently.
- Parameter `source` values are lowercase wire values:
  `user`, `researched`, `estimated` or `assumption`.
- Numeric metric names include their unit when the unit is not dimensionless,
  for example `lost_production_t` or `annual_benefit_gbp`.
- Dimensionless ratios use values from 0 to 1, not percentages. The frontend is
  responsible only for display formatting.
- Times in the CO2 demo are elapsed `time_hours` from the start of a run.
- A scenario result has the same `timeseries`, `metrics`, `events` shape as the
  baseline simulator result.
- The backend calculates metric deltas, financials and the recommendation. The
  frontend displays them without recomputing the decision.

## Routes Proposed for Sign-off

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/requirements` | Extract or refine a `ModelSpec` and return clarification questions. |
| `POST` | `/api/simulations/baseline` | Run the validated baseline model. |
| `POST` | `/api/scenarios/compare` | Run interventions and return a comparison plus recommendation. |

Simulator generation and Daytona execution remain internal backend steps. They
are deliberately not exposed as browser-facing routes.

## Requirements Route

Request fixture: [`requirements-request.json`](requirements-request.json)

```json
{
  "description": "string",
  "draft_spec": null,
  "answers": {}
}
```

`description` is required on the first request. Later requests send back the
previous `draft_spec`, its optional `assumptions` list, and answers keyed by
question id. Returning `assumptions` preserves the provenance of default time
settings across clarification rounds; older requests without it remain valid.

The response is always one of two successful states:

- `needs_clarification`: includes `draft_spec`, one or more `questions`, and a
  null `model_spec`;
- `ready`: includes a validated `model_spec` and an empty `questions` array.

See [`requirements-needs-clarification.json`](requirements-needs-clarification.json)
and [`requirements-ready.json`](requirements-ready.json).

Clarification is a successful domain state and uses HTTP 200. It is not encoded
as an API error.

### Required `ModelSpec` fields

```json
{
  "objective": "minimise lost production",
  "time": {
    "simulation_days": 30,
    "timestep_minutes": 10
  },
  "parameters": {}
}
```

`process_family` is optional at the integration boundary but included for the
CO2 demo. Each important parameter uses this envelope:

```json
{
  "value": 45,
  "unit": "tonnes",
  "source": "user",
  "rationale": null,
  "citation": null
}
```

`value` and `source` are required. The other fields may be null. Assumed time
settings are recorded in the response's `assumptions` list because the README
contract keeps values in `time` as plain numbers.

## Baseline Route

Request fixture: [`baseline-request.json`](baseline-request.json)

The request contains a validated `model_spec`, a seed and a rollout count. The
response uses the simulator contract directly:

```json
{
  "timeseries": [],
  "metrics": {},
  "events": []
}
```

See [`simulation-result.json`](simulation-result.json). `metadata` is optional
and may carry reproducibility information. The UI must remain functional if
metadata is absent.

For the CO2 demo, each time-series point uses `time_hours` and numeric series
keys. Each event contains `time_hours`, `type`, `label`, `severity` and optional
`details`.

## Scenario Comparison Route

Request fixture:
[`scenario-comparison-request.json`](scenario-comparison-request.json)

Each scenario supplies an id, human-readable label and only the parameter
overrides that differ from baseline. The backend applies those overrides to the
same underlying model.

Response fixture: [`scenario-comparison.json`](scenario-comparison.json)

```json
{
  "baseline": {},
  "scenarios": [],
  "recommendation": {}
}
```

`baseline` and each scenario contain:

- `id` and `label`;
- `status`: `completed` or `failed`;
- `result`: simulator result when completed, otherwise null; and
- `error`: null when completed, otherwise a safe structured error.

A failed scenario does not fail the entire comparison when baseline and at least
one scenario completed. In that case the route returns HTTP 200, preserves the
failed scenario, and recommends only among completed scenarios.

The `recommendation` contains backend-produced `metric_deltas` and optional
`financials`. Its prose may be AI-assisted, but every number must already exist
in deterministic backend results.

## Error Shape

Fixture: [`api-error.json`](api-error.json)

All non-2xx responses use:

```json
{
  "error": {
    "code": "validation_error",
    "message": "The request could not be validated.",
    "retryable": false,
    "field_errors": [],
    "request_id": "request-id"
  }
}
```

`message` is safe to show to the user. Provider traces, generated source,
credentials and internal stack traces must not be returned.

| HTTP | Code | Meaning |
| --- | --- | --- |
| 400 | `invalid_request` | Malformed JSON or unsupported request shape. |
| 422 | `validation_error` | Field or domain constraint validation failed. |
| 502 | `gemini_invalid_response` | Gemini returned output that failed schema validation. |
| 502 | `simulation_failed` | Baseline simulation or all compared scenarios failed. |
| 503 | `gemini_unavailable` | Gemini is unavailable or quota-limited. |
| 503 | `execution_unavailable` | Daytona/execution service is unavailable. |
| 504 | `operation_timeout` | Provider or simulation timed out. |
| 500 | `internal_error` | Unclassified server error. |

`field_errors` entries use a dotted `path` and a user-safe `message`. Clients
should use `retryable` rather than guessing retry behaviour from status codes.

## Fixture Index

| File | Direction | Expected route/state |
| --- | --- | --- |
| `requirements-request.json` | Request | First `/api/requirements` call. |
| `requirements-needs-clarification.json` | Response | Missing tanker capacity. |
| `requirements-ready.json` | Response | Validated spec after clarification. |
| `baseline-request.json` | Request | Baseline simulation with fixed seed. |
| `simulation-result.json` | Response | Completed baseline. |
| `scenario-comparison-request.json` | Request | Three configuration-driven interventions. |
| `scenario-comparison.json` | Response | Two completed scenarios and one failed scenario. |
| `api-error.json` | Response | Validation failure envelope. |
| `provenance-labels.json` | UI reference | All four provenance wire/display labels. |

## Teammate Sign-off Checklist

- [ ] Required `ModelSpec` fields and parameter envelope accepted.
- [ ] Route names accepted or replaced before frontend fetch calls are written.
- [ ] Baseline time-series, metrics and event keys can be produced by the
  simulator adapter.
- [ ] Scenario wrapper and partial-failure behaviour accepted.
- [ ] Recommendation delta/financial shapes accepted.
- [ ] Error codes and retry semantics can be emitted by FastAPI.

After sign-off, record any accepted changes here and increment the contract
version before M1. Do not let implementation silently become the contract.
