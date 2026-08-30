# Backend handoff → frontend

Everything the UI needs, with real values. The API is live and every route below
is covered by tests. Nothing here is a mock.

```bash
pip install -r requirements.txt
python scripts/build_snapshot.py       # one-off, ~1 min: bakes the model into a
                                       # Daytona snapshot so sandboxes start in
                                       # ~0.7s with nothing to upload
uvicorn app.main:app --reload          # serves the API and static/ on one origin
```

Re-run `build_snapshot.py` after any change to the simulator. Its name carries a
content hash, so a stale snapshot is never silently reused — the runner just
falls back to uploading, which is slower but always correct.

Check it before you demo:

```bash
curl 'localhost:8000/api/health?deep=1'
```

`deep=1` provisions a real sandbox and runs a simulation in it. It is the
difference between finding out Daytona is unreachable now and finding out on
stage. Expect ~4 s and:

```json
{"status":"ok","execution":"daytona","daytona_configured":true,
 "daytona":{"status":"ok","roundtrip_seconds":3.68,"sandbox_python":"3.14.4",
            "isolation_mode":"independent_sandboxes"}}
```

`status` is `degraded` only when Daytona is configured but unreachable.
`not_configured` is fine — runs just execute locally.

---

## Routes

| Method | Route | Body | Returns |
|---|---|---|---|
| `GET` | `/api/health` | — | liveness; `?deep=1` round-trips a sandbox |
| `POST` | `/api/simulations/baseline` | `SimulationRequest` | `SimulationResult` |
| `POST` | `/api/scenarios/compare` | `ScenarioComparisonRequest` | `ScenarioComparison` |
| `POST` | `/api/requirements` | `RequirementsRequest` | yours — see below |

Bodies are validated with **your** `app/models.py`, and responses are validated
against it in the test suite. If it type-checks in your models, it will work.

`?execution=local` forces in-process execution (~2 s, no network) — use it while
developing so you are not waiting on sandboxes. `?execution=daytona` forces
sandboxes (~4.5 s: the baseline and all three scenarios are created and executed
in parallel). Omit it and the server picks based on whether the key is set.
It is a query parameter and not a body field because `ContractModel` forbids
extras — your contract stays exactly as you defined it.

### Try it

```bash
curl -X POST 'localhost:8000/api/scenarios/compare?execution=local' \
  -H 'content-type: application/json' \
  -d @static/fixtures/scenario-comparison-request.json | jq .
```

⚠️ Change `tanker_capacity` to **24** in that fixture before demoing. At the
fixture's 30 t, one daily tanker removes 30 t against 24 t/day of production, so
the plant never fills up, loses nothing, and no intervention can pay back — the
response is correct but the demo has no decision in it. At 24 t the collection
capacity exactly matches production, the operation has no recovery capacity, and
a missed collection is permanent. That is the story.

---

## Where every displayed number lives

Real values from a 200-rollout run, 30 days, seed 42, tanker 24 t.

### Baseline KPI tiles → `baseline.result.metrics`

| Display | JSON path | Value |
|---|---|---|
| Expected lost production | `lost_production_t` | `13.08` t |
| P95 lost production | `p95_lost_production_t` | `59.41` t |
| Failure probability | `failure_probability` | `0.45` → render as 45 % |
| Expected output | `total_production_t` | `706.88` t |
| Mean tank utilisation | `tank_utilisation` | `0.478` → 47.8 % |
| Curtailment episodes | `overflow_events` | `1.505` (mean per run) |

`metrics` is `dict[str, NumericValue]` — every value is a finite number, so you
can format without null checks.

### Baseline chart → `baseline.result.timeseries`

720 rows (hourly over 30 days), `time_hours` unique and ascending:

```json
{"time_hours": 1.0, "tank_level_t": 21.008, "cumulative_lost_production_t": 0.0,
 "storage_utilisation": 0.233, "production_t": 1.008, "collected_t": 0.0}
```

* **Storage line** — `tank_level_t` against `time_hours`. Draw the capacity
  ceiling at `baseline.result.metadata.config.tank_count × tank_capacity_t`
  (90 t at baseline). The story is the line hitting that ceiling.
* **Loss area** — `cumulative_lost_production_t`, monotonic, ends at the run's
  `lost_production_t`.
* **Collection bars** — `collected_t`, non-zero only on collection hours.

This is rollout 0 of that scenario's own Monte Carlo batch, i.e. a future that
was actually counted — not a separate run drawn from nowhere.

### Event timeline → `baseline.result.events`

```json
{"time_hours": 32.0, "type": "collection_completed",
 "label": "Tanker collected 24.0 t", "severity": "info",
 "details": {"day": 1, "slot": 0, "collected_t": 24.0, "partial_load": false}}
```

`label` is display-ready. Colour by `severity`: `critical` = storage full /
production curtailed, `warning` = collection missed or delayed, `info` = normal
traffic. Around 70 events per 30-day run, not thousands.

Types: `collection_scheduled`, `collection_completed`, `collection_delayed`,
`collection_missed`, `collection_stood_down`, `storage_capacity_reached`,
`production_curtailed`.

### Scenario cards → `scenarios[].result.metrics`

Same keys as the baseline, plus:

| Display | JSON path |
|---|---|
| CAPEX | `capex_gbp` |
| Annual benefit | `annual_benefit_gbp` |
| Incremental annual cost | `incremental_annual_cost_gbp` |
| Net annual benefit | `net_annual_benefit_gbp` |
| **Annual value** (the ranking number) | `annual_value_gbp` |
| Recovered output | `recovered_output_t_per_year` |
| Payback | `payback_years` — **absent when payback is not meaningful** |

`payback_years` is a metric only when it is a real number. When an intervention
does not pay back, the key is simply not there — read
`scenarios[].result.metadata.financial.payback_status`, which is one of
`pays_back`, `opex_only_positive`, `not_viable`. Never render a negative payback;
there is never one to render.

### Recommendation → `recommendation`

```json
{"scenario_id": "add-third-tank",
 "title": "Add a third storage tank",
 "summary": "...a genuine trade-off.",
 "metric_deltas": {"lost_production_t": {"baseline": 13.08, "scenario": 1.94,
   "absolute_change": -11.14, "percentage_change": -85.2, "unit": "tonnes"}, ...},
 "financials": {"capex_gbp": 80000.0, "annual_value_gbp": 10830.0, ...}}
```

`metric_deltas` covers `lost_production_t`, `p95_lost_production_t` and
`failure_probability`. Every number in here already exists in a backend result —
a test asserts it — so the UI never has to compute a delta or a percentage.

**`recommendation` can be `null`.** That is not an error: it means no
intervention has positive annual value, and the contract requires a
recommendation to name a completed scenario. When it is null, render the
rejection from:

```json
baseline.result.metadata.no_viable_intervention = {
  "reason": "no scenario has a positive annual value",
  "rejected_scenario_id": "add-third-tank",
  "rejected_annual_value_gbp": -9500.0,
  "detail": { ...same shape as a recommendation... }
}
```

### Everything else → `baseline.result.metadata`

`ScenarioComparison` forbids extra fields, so the richer detail rides in
`SimulationResult.metadata`:

| Key | Use |
|---|---|
| `ranking` | ordered interventions with `annual_value_gbp`, `payback_years`, `resilience_rank` |
| `ranking_rule` | the exact rule, as a sentence — show it, the ranking is not a black box |
| `assumptions` | `n_runs`, `base_seed`, `failure_definition`, `finance_config`, `common_random_numbers` |
| `execution` | `mode`, `isolation_mode`, sandbox ids, per-phase timings |
| `unmapped_model_spec_parameters` | ModelSpec fields the simulator does not model — worth surfacing |

Per scenario, `metadata` also carries `financial` (full breakdown incl.
`payback_status`), `stats` (mean/std/p05/p50/p95/min/max per metric),
`economics` and `sandbox_id`.

`assumptions.failure_definition` is a sentence you can put straight under the
failure-probability tile: *"lost_production_t > 1e-06 t in a run (the operation
had to curtail production at all)"*.

---

## States to handle

| State | How it arrives |
|---|---|
| Loading | ~2 s local, ~4.5 s Daytona. Show the phase from `execution.timings` afterwards. |
| Partial | HTTP **200** with `scenarios[i].status == "failed"`, `result: null`, `error: {code, message, retryable}`. Baseline and at least one scenario succeeded. Render the failed card greyed with its message; it is already excluded from `ranking` and the recommendation. |
| No winner | HTTP 200, `recommendation: null` — see above. |
| Error | Non-2xx, always `{"error": {code, message, retryable, field_errors, request_id}}`. `message` is safe to display. Use `retryable`, not the status code. |

Error codes you will actually hit: `validation_error` (422, with dotted-path
`field_errors`), `execution_unavailable` (503, Daytona down — retryable),
`operation_timeout` (504), `simulation_failed` (502).

Every response carries an `x-request-id` header, echoed from your request if you
send one, matching `request_id` in the error body.

---

## `/api/requirements` — already wired to your agent

The route now calls **`app.requirements_agent.build_requirements(description,
draft_spec, answers)`** — your actual signature, verified against your branch. It
runs in a thread, so the blocking Gemini call is fine, and `main.py` needs no
change when you merge.

Your error hierarchy maps straight onto the documented codes:

| Your exception | HTTP | code |
|---|---|---|
| `RequirementsConfigurationError` | 503 | `gemini_unavailable`, message passed through (it is actionable: *"GEMINI_MODEL is required"*), `retryable: false` |
| `RequirementsInputError` | 422 | `validation_error` |
| `RequirementsResponseError` | 502 | `gemini_invalid_response` |
| `RequirementsProviderError` | 503 | `gemini_unavailable` |
| anything else | 500 | `internal_error` |

Provider and schema messages are logged server-side and replaced with a generic
one, since their text can carry prompt or response fragments. Configuration
messages pass through because they tell you what to fix.

Set these before the route works:

```bash
GEMINI_API_KEY=...        # in .env
GEMINI_MODEL=gemini-2.5-flash
```

Until `app/requirements_agent.py` exists on the branch you are running, the
route returns `503 gemini_unavailable` — deliberately, so the frontend exercises
its real error path rather than a stub success.

If you want the ModelSpec straight through to a simulation without an LLM,
`app.api_contract.model_spec_to_config(spec)` does the mapping and
`unmapped_parameters(spec)` tells you what the simulator ignored.

---

## Things I would not change without telling you

* Scenario ids must match `^[a-z][a-z0-9_-]*$` (your own pattern) — the demo uses
  `add-third-tank`, `increase-collections`, `larger-tanker`.
* `parameter_overrides` are echoed back in **your** names (`tanker_capacity`),
  not the simulator's internal ones (`tanker_capacity_t`).
* Passing the same `seed` twice gives byte-identical results, so screenshots and
  a live run will agree.
