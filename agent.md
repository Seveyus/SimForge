# Branch Agent Brief — AI Modelling & UX

## Role

You are the implementation agent for the `ebrahim-work` branch of SimForge.
Your scope is the AI modelling pipeline and user experience described in
`plan.md`. Work as if another developer is simultaneously building the
simulation, Daytona, Monte Carlo and finance layers.

Read `Readme.md` and `plan.md` before changing code. Treat their integration
contracts as the source of truth. If the two documents disagree, preserve the
minimal contracts from `Readme.md` and record the decision before expanding a
schema.

## Objective

Implement a clean path from natural-language operation description to validated
`ModelSpec`, plus a frontend that renders contract-shaped simulation results.
Use Gemini as a schema-constrained backend dependency, not as the owner of
business calculations or application state.

## Files You May Own

```text
app/models.py
app/requirements_agent.py
app/simulator_generator.py
app/provenance.py
static/
plan.md
agent.md
```

Avoid editing teammate-owned simulation and integration files. If a shared file
must change, explain the exact need and keep the change minimal and separable.
Never overwrite unrelated work in a dirty worktree.

## Non-Negotiable Invariants

1. The simulator owns numerical results.
2. Gemini may extract, classify, ask and explain; it may not fabricate KPIs.
3. Every important input carries `user`, `researched`, `estimated` or
   `assumption` provenance.
4. User values always win over assumptions or research unless the user explicitly
   replaces them.
5. The frontend depends on JSON contracts, not simulator internals.
6. Generated simulator code is never executed in the AI modules or the browser.
7. The Gemini API key remains server-side and is never logged or exposed to
   `static/`.
8. Mock payloads are test/development data and must never be presented as a live
   run.
9. Invalid or uncertain high-impact values trigger clarification, not guessing.
10. Any schema change that affects the other branch is an integration decision,
    not a local refactor.

## Required Contracts

### `ModelSpec`

```json
{
  "objective": "minimise lost production",
  "time": {},
  "parameters": {}
}
```

### Simulator result

```json
{
  "timeseries": [],
  "metrics": {},
  "events": []
}
```

### Scenario comparison

```json
{
  "baseline": {},
  "scenarios": [],
  "recommendation": {}
}
```

Additional fields must be optional or explicitly agreed. Do not rename or remove
these top-level fields.

## Implementation Order

Follow the milestone gates in `plan.md`:

1. contract examples and payload fixtures;
2. Pydantic models and provenance helpers;
3. Gemini requirements extraction and clarification flow;
4. constrained simulator-generation prompt;
5. frontend modelling and assumptions flow;
6. baseline charts and events;
7. scenario comparison and recommendation presentation;
8. integration, failure-state and demo hardening; and
9. optional Tavily research only after the main path works.

Do not start optional research or generic multi-industry abstractions before the
CO2 path passes its milestone gates.

## Gemini Implementation Rules

- Use the `google-genai` Python package.
- Read `GEMINI_API_KEY` and `GEMINI_MODEL` from environment/configuration.
- Do not hardcode credentials or a model version.
- Define structured response schemas with Pydantic where supported.
- Validate provider output again at the application boundary.
- Keep prompts versioned and testable as plain data/functions.
- Prefer one extraction call over a chain of opaque autonomous calls.
- Use Python rules for completeness, bounds and conflict resolution.
- Make timeout, quota/provider failure and schema-validation failure distinct.
- Allow a fake client to be injected; module import must not make a network call.
- Keep retries bounded and do not retry invalid user content as a transient
  provider error.

The requirements agent should have explicit inputs and outputs. A good shape is:

```python
build_requirements(
    description: str,
    existing_spec: ModelSpec | None = None,
    answers: dict[str, object] | None = None,
) -> RequirementsResult
```

The exact sync/async form should match the integration layer, but it must be
dependency-injectable and deterministic outside the Gemini call.

## Clarification Policy

Ask a question when a missing or ambiguous value would materially change model
behaviour, constraints or recommendations. Group related questions and keep the
first round focused.

An assumption is acceptable only when:

- it is low-risk enough for the demo;
- it has a clear value and unit;
- it is labelled `assumption`;
- its rationale is visible; and
- the user can change it before execution.

Do not silently infer plant-specific capacity, cost, reliability or production
facts. If units are ambiguous, ask rather than applying a hidden conversion.

## Generated Simulator Prompt Rules

The generator must require:

```python
def simulate(config: dict, seed: int | None = None) -> dict:
    ...
```

It must also require:

- output keys `timeseries`, `metrics` and `events`;
- JSON-serialisable values;
- seeded stochastic behaviour;
- config-driven scenarios rather than copied simulators;
- no network, filesystem, subprocess, shell, dynamic package installation or
  secret access;
- only explicitly allowed standard-library or pre-agreed dependencies;
- no module-level execution with side effects; and
- no prose or markdown around the returned source when raw source is expected.

The generator produces code and metadata only. Daytona/static validation and
execution belong to the integration teammate. A repair request may contain the
original source and a sanitised error, but only one repair attempt is required
for the hackathon path.

## Frontend Rules

- Keep API route definitions together rather than scattering fetch calls.
- Pass backend payloads through adapters before rendering.
- Keep chart lifecycle management separate from data fetching.
- Read operational values from `metrics`, chart points from `timeseries`, and
  event markers from `events`.
- Render recommendations from the `recommendation` payload; do not calculate
  them in JavaScript.
- Include loading, empty, validation, provider-error, execution-error and partial
  scenario states.
- Preserve units and provenance labels.
- Make assumptions editable/reviewable before the run.
- Use semantic HTML, visible focus states and keyboard-accessible controls.
- Ensure the dashboard remains understandable without relying only on colour.
- Destroy or update existing Chart.js instances before re-rendering.

When a backend route is not yet available, build against a contract-conforming
fixture behind an explicit mock flag or injected transport. The production path
must not silently fall back to mock results.

## Verification Expectations

For each milestone:

1. inspect existing code and current git status before editing;
2. make the smallest coherent change within owned files;
3. validate representative success and failure payloads;
4. run the relevant existing tests or lightweight checks;
5. inspect the browser at desktop and narrow/mobile widths for UI changes;
6. report anything that requires the teammate's branch; and
7. leave the worktree free of generated secrets, caches and debug output.

At minimum, verify these behaviours:

- a complete CO2 description produces a valid spec;
- an incomplete description produces clarification questions;
- malformed Gemini output is rejected safely;
- user answers replace prior assumptions with `user` provenance;
- source labels survive serialisation;
- simulator and scenario fixtures render without simulator imports;
- missing series/metrics/events produce useful empty states;
- partial scenario failure does not hide successful scenarios; and
- no displayed KPI is sourced from Gemini prose.

## Collaboration and Handoff

Before changing a shared contract, describe:

- the current payload;
- the proposed payload;
- why the current form is insufficient; and
- whether the change is backward-compatible.

Keep commits scoped by milestone. Do not reformat or rename teammate-owned code.
At handoff, provide:

- exported functions/classes and their signatures;
- dependency additions such as `google-genai`;
- required environment variables, without values;
- expected API routes and example request/response payloads;
- prompt versions/model metadata behaviour;
- known limitations and mock-mode instructions; and
- commands/checks that passed.

## Stop Conditions

Pause and request alignment if:

- an integration payload must lose or rename a required field;
- the only proposed solution couples UI code to simulator implementation;
- generated code would need to execute outside the teammate's isolation layer;
- a secret would need to be committed or sent to the browser;
- the frontend would need to manufacture a missing result; or
- a change requires broad edits to teammate-owned files.

Otherwise, make reasonable implementation assumptions, document them, and keep
moving toward the next milestone gate.
