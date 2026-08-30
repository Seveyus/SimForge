# Ebrahim Work Plan — AI Modelling & UX

## Mission

Build the AI modelling and user-experience side of SimForge on the `ebrahim-work`
branch, while keeping a narrow, schema-driven boundary with the simulation and
decision engine.

The finished work should let a user:

1. describe an operation in plain language;
2. answer only the clarification questions needed to make it executable;
3. review extracted values and visible assumptions;
4. submit a validated `ModelSpec` to the simulator;
5. view baseline and scenario results without the frontend knowing simulator
   implementation details; and
6. understand which recommendation is supported by backend-calculated results.

## Ownership Boundary

### Files owned on this branch

```text
app/models.py
app/requirements_agent.py
app/simulator_generator.py
app/provenance.py
static/
plan.md
agent.md
```

### Integration-owned files

The simulation teammate owns these files and the final wiring:

```text
app/main.py
app/daytona_runner.py
app/scenario_runner.py
app/monte_carlo.py
app/finance.py
reference/co2_simulation.py
tests/
```

Do not make the frontend import, reproduce, or infer logic from those modules.
Do not execute generated Python in the requirements agent or generator. Return
validated data or generated source to the integration layer.

Changes needed in shared root files, such as `requirements.txt` or
`.env.example`, should be called out explicitly during handoff or agreed before
editing to avoid merge conflicts.

## Contract First

These are the stable boundaries between both branches.

### AI modelling to simulator

```json
{
  "objective": "minimise lost production",
  "time": {},
  "parameters": {}
}
```

The model may contain additional agreed fields, such as `process_family`, but
the three fields above must remain present and backward-compatible.

Each important parameter should use one envelope:

```json
{
  "value": 45,
  "unit": "tonnes",
  "source": "user",
  "rationale": null,
  "citation": null
}
```

Wire values for `source` are lowercase:

```text
user | researched | estimated | assumption
```

The frontend may display these as uppercase labels, but must not change their
meaning.

### Simulator to UI

```json
{
  "timeseries": [],
  "metrics": {},
  "events": []
}
```

The UI reads these top-level collections through a small response adapter. It
must not depend on a simulator class, variable name, or internal event loop.

### Scenario comparison to UI

```json
{
  "baseline": {},
  "scenarios": [],
  "recommendation": {}
}
```

The recommendation is rendered from backend output. The browser may format or
sort supplied values, but must not invent operational or financial conclusions.

## Proposed Owned Interfaces

The concrete names can be adjusted before implementation, but keeping these
responsibilities separate will make integration predictable.

### `app/models.py`

- `ProvenanceSource`: enum for the four source categories.
- `ParameterValue`: typed value, optional unit, provenance, rationale and
  citation.
- `TimeConfig`: simulation duration and timestep fields.
- `ModelSpec`: objective, optional process family, time and parameters.
- `ClarificationQuestion`: stable id, parameter key, question, reason and
  optional choices.
- `RequirementsResult`: `needs_clarification` or `ready`, plus questions,
  assumptions and an optional validated `ModelSpec`.
- Contract models for simulation and scenario payloads if the frontend/API
  needs server-side validation of those responses.

Keep models permissive enough for later industries, but validate known physical
constraints such as positive duration, timestep and capacities.

### `app/provenance.py`

- Pure helpers for applying and summarising provenance.
- Never silently upgrade `estimated` or `assumption` to `user`.
- Preserve citations for researched values.
- Make assumptions easy for the UI to list and for the user to review.

### `app/requirements_agent.py`

- Accept the operation description, previous partial spec and clarification
  answers.
- Ask Gemini for schema-constrained extraction, not free-form JSON.
- Validate every response with the Pydantic models before returning it.
- Use deterministic Python rules to identify missing required inputs and decide
  whether the model is ready.
- Return concise clarification questions rather than guessing high-impact plant
  values.
- Allow low-risk defaults only when they are explicitly labelled `assumption`.
- Never calculate or claim simulation KPIs.

### `app/simulator_generator.py`

- Convert a validated `ModelSpec` into a tightly constrained generation prompt.
- Require exactly `simulate(config: dict, seed: int | None = None) -> dict`.
- Require the standard `timeseries`, `metrics` and `events` result shape.
- Require seeded randomness and configuration-driven scenarios.
- Restrict dependencies and prohibit network, filesystem, subprocess, package
  installation and secret access in generated code.
- Return source code and generation metadata; do not execute it.
- Include backend validation or Daytona errors in a single repair prompt when
  the integration layer requests a repair.

### `static/`

- `index.html`: semantic application structure and accessible controls.
- `styles.css`: responsive visual system, source badges, dashboard and compare
  layouts.
- `app.js`: UI state, API client, payload adapters, Chart.js rendering and
  interaction handlers.
- Any mock payloads must match the integration contracts and be clearly isolated
  so they cannot appear as live simulation results.

## Gemini Plan

Use the current Google Gen AI Python SDK, `google-genai`, on the server. The SDK
supports schema-constrained output using Pydantic models. Keep these settings in
the environment:

```text
GEMINI_API_KEY=<never commit this>
GEMINI_MODEL=<chosen Gemini model>
```

Do not hardcode a model version. This lets the team choose a fast model for the
demo and change it without touching application logic.

Recommended request flow:

```text
user description + existing answers
                |
                v
Gemini structured extraction
                |
                v
Pydantic validation
                |
                v
Python completeness/constraint checks
        |                       |
        v                       v
clarification questions     ready ModelSpec
```

Reliability rules:

- low temperature for extraction and code generation;
- explicit timeout and one bounded retry for transient API failures;
- distinguish provider failure from invalid user input;
- never log the API key or full secrets;
- store prompt version and model name in metadata for reproducibility;
- keep a fixture or fake client path so UI and schema work can continue without
  live API calls; and
- show a recoverable UI error if Gemini is unavailable.

Official references:

- [Gemini API getting started](https://ai.google.dev/gemini-api/docs/get-started)
- [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini API key guidance](https://ai.google.dev/gemini-api/docs/api-key)

## Milestones

### M0 — Freeze the handoff contract

Status: contract v0.1 is frozen on `ebrahim-work`; teammate sign-off remains.

Artifacts:

- [`static/fixtures/README.md`](static/fixtures/README.md) defines proposed API
  routes, payload rules, partial-scenario behaviour and the shared error shape.
- `static/fixtures/*.json` contains contract-conforming requests and responses
  for requirements, baseline simulation, scenario comparison and errors.

Deliverables:

- [ ] Confirm required `ModelSpec` fields and parameter envelope with the simulation
  teammate.
- [x] Define exact baseline, scenario and recommendation payload examples.
- [ ] Agree proposed API route names and error response shape with the integration
  teammate before wiring production fetch calls.
- [x] Create representative fixture payloads for frontend development.

Exit gate:

- Both branches can develop against the same JSON examples without importing
  each other's implementation.

### M1 — Models and provenance

Deliverables:

- Implement Pydantic contract models in `app/models.py`.
- Implement provenance helpers in `app/provenance.py`.
- Cover missing values, invalid units/types, invalid time settings and source
  display mapping in the agreed team tests.

Exit gate:

- Valid examples round-trip cleanly and malformed/high-risk input fails with a
  useful validation error.

### M2 — Requirements agent with Gemini

Deliverables:

- Structured natural-language parameter extraction.
- Multi-turn merge of clarification answers into a partial spec.
- Deterministic required-field and constraint checks.
- Clear `needs_clarification` and `ready` responses.
- Fake-client or fixture path for offline development.

Minimum CO2 clarification set:

- objective;
- simulation duration/timestep, or explicit defaults;
- production rate and unit;
- tank count and capacity;
- collection frequency and tanker capacity; and
- uncertain behaviour such as missed collections, represented as user data or a
  visible assumption.

Exit gate:

- The README demo description becomes a valid `ModelSpec`, while an incomplete
  description produces focused questions instead of fabricated plant facts.

### M3 — Safe simulator prompt generation

Deliverables:

- Versioned generation prompt built from a validated `ModelSpec`.
- Exact simulator signature and result contract in the prompt.
- Reproducibility, dependency and sandbox restrictions.
- One repair-prompt path that accepts validation/execution errors.

Exit gate:

- Generated output can be handed to the teammate's validator/Daytona runner
  without this module executing it or depending on Daytona internals.

### M4 — Frontend shell and modelling flow

Deliverables:

- Operation description form.
- Clarification question flow.
- Loading, empty, error and retry states.
- Assumption/provenance review before execution.
- Responsive and keyboard-usable layout.

Exit gate:

- A user can move from description to reviewed spec using mock or live contract
  responses, with no simulator dependency.

### M5 — Baseline dashboard

Deliverables:

- KPI summary cards sourced only from `metrics`.
- Tank/storage time-series chart sourced only from `timeseries`.
- Event markers or event list sourced only from `events`.
- Units, legends, tooltips and no-data handling.

Exit gate:

- Replacing one conforming simulator response with another does not require UI
  logic changes.

### M6 — Scenario comparison and recommendation UX

Deliverables:

- Baseline-versus-scenarios metric comparison.
- Expected and downside outcomes, including P95/failure probability when
  supplied.
- Financial values and payback when supplied by the backend.
- Recommendation panel with provenance-aware assumptions visible nearby.
- Clear distinction between simulation output and AI explanation.

Exit gate:

- The UI can render the full scenario comparison contract, including partial or
  failed scenarios, without calculating a recommendation itself.

### M7 — Integration and demo hardening

Deliverables:

- Replace mock transport with the agreed backend routes while retaining fixtures
  for development.
- Exercise the complete CO2 demo flow with the teammate.
- Verify loading and failure behaviour for Gemini, validation and simulation
  errors.
- Remove hidden defaults, console noise and placeholder claims.
- Produce a concise handoff note listing dependencies, environment variables,
  exported functions and route assumptions.

Exit gate:

- The README demo can be performed from a clean checkout with documented setup,
  and every displayed number can be traced to backend output.

### M8 — Optional research, only after M7

If time remains, add Tavily-backed research for missing benchmark values.

Requirements:

- make research opt-in;
- retain URL/title/date metadata;
- label all returned values `researched`;
- never overwrite a user value;
- require user review before simulation; and
- degrade cleanly when `TAVILY_API_KEY` is absent.

## Suggested Commit Sequence

Keep commits small enough to cherry-pick or review independently:

```text
docs: add AI modelling and UX implementation plan
feat: add ModelSpec and provenance models
feat: add Gemini requirements extraction
feat: add simulator generation prompt
feat: add modelling and assumptions UI
feat: add baseline results dashboard
feat: add scenario comparison UI
chore: harden integration states and handoff docs
```

Do not mix contract changes, broad styling changes and Gemini behaviour changes
in one commit.

## Integration Checklist

- [ ] No secret or `.env` file is committed.
- [ ] `GEMINI_API_KEY` is read server-side only.
- [ ] Gemini model selection is environment-driven.
- [ ] All Gemini structured output is validated before use.
- [ ] Every important parameter has a provenance label.
- [ ] Assumptions are reviewable before running the simulator.
- [ ] Generated code is returned, not locally executed.
- [ ] The simulator signature is exactly preserved.
- [ ] The UI consumes only agreed response contracts.
- [ ] The UI does not calculate or invent recommendation metrics.
- [ ] Mock results are visibly isolated from real results.
- [ ] Error/empty/loading/partial states are handled.
- [ ] Chart labels and displayed values include units where supplied.
- [ ] Shared dependencies and route assumptions are included in handoff notes.

## Definition of Done

This branch is ready to merge when the CO2 demo can move from natural-language
description to reviewed `ModelSpec`, hand that spec/generator output to the
integration layer, and render baseline plus scenario comparison payloads through
stable adapters. All assumptions must be visible, all numbers must originate in
backend responses, and Gemini must be replaceable or mockable without rewriting
the frontend or domain models.
