# SimForge

> Turn an operation into an executable model, stress-test possible futures, and compare interventions before committing capital.

SimForge is an AI-assisted operations modelling and decision-support application. A user describes a physical process in plain language, reviews the extracted assumptions, runs a stochastic baseline simulation, and compares three editable intervention scenarios.

The language model structures the problem and suggests scenarios. Deterministic Python code validates the inputs, runs the simulation, calculates every metric, and ranks the results.

**The simulator owns the numbers. The AI does not invent them.**

## What SimForge models

The current model family is `buffer_logistics`:

```text
Continuous inflow → finite buffer/storage → scheduled outbound removal
```

This pattern covers operations such as:

- captured CO₂ entering tanks before tanker collection;
- process water entering holding tanks before removal;
- grain entering silos before outbound dispatch; and
- custom materials or items following the same flow pattern.

A model uses one quantity unit throughout: `tonnes`, `kilograms`, `litres`, `cubic_metres`, or `items`. SimForge does not silently convert or mix units.

## Features

- Natural-language requirements extraction with Gemini
- Targeted clarification questions for missing parameters
- Structured, validated `ModelSpec` output
- Visible provenance for user values and assumptions
- CO₂, process-water, grain, and custom-process inputs
- Seeded, reproducible Monte Carlo simulation
- Local execution or isolated Daytona sandbox execution
- Three validated and editable AI-suggested interventions
- Operational ranking when costs are unavailable
- Optional user-supplied financial ranking with CAPEX, OPEX change, annual value, and payback
- Interactive metrics, events, scenario comparison, and selectable chart series
- Backward-compatible CO₂ parameter aliases and response fields

## How it works

```text
Operation description
        ↓
Gemini requirements extraction
        ↓
Validated ModelSpec + provenance review
        ↓
Baseline Monte Carlo simulation
        ↓
Three reviewed scenario interventions
        ↓
Local Python or Daytona sandboxes
        ↓
Operational / financial comparison
        ↓
Recommendation with simulator-produced evidence
```

Gemini is used for requirements extraction and scenario suggestions. Python remains authoritative for schema validation, physical constraints, stochastic execution, metrics, and ranking. The web application does not execute arbitrary Gemini-generated simulation code.

## Quick start

### Requirements

- Python 3.10 or newer; Python 3.12 is recommended
- A Gemini API key for live requirements extraction and scenario suggestions
- A Daytona API key only if simulations should run in remote sandboxes

### Install and run

```bash
git clone https://github.com/Seveyus/SimForge.git
cd SimForge

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Add your credentials to `.env`:

```dotenv
GEMINI_API_KEY=your-gemini-key
GEMINI_MODEL=gemini-3.5-flash-lite

# Optional: omit this to run simulations locally.
DAYTONA_API_KEY=your-daytona-key
```

Never commit `.env` or API keys.

Start the application:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The FastAPI service hosts both the API and the static frontend.

Without a Gemini key, the simulation API remains usable but live requirements extraction and scenario suggestions return `gemini_unavailable`. Without a Daytona key, simulation requests run locally.

## Use SimForge locally

### Run a live local session

1. Start the server with the command above and open `http://127.0.0.1:8000`.
2. Leave **Live API** selected.
3. Describe an operation, or select a CO₂, process-water, grain, or custom-process example.
4. Select **Build model**, answer any clarification questions, and review the extracted values and assumptions.
5. Select **Approve ModelSpec**, then **Run baseline**.
6. Select **Generate scenario ideas** and edit the suggested labels or parameter overrides if needed.
7. To compare economics, enable **Include economics**, then enter the confirmed value per unit, amortisation period, baseline outbound-event cost, and each scenario's CAPEX, fixed annual OPEX change, and outbound-event cost. Leave it disabled for operational ranking.
8. Select **Compare reviewed scenarios**. Financial outputs are calculated by Python only when every required economic input is present.
9. Use the time-series labels above the chart to show or hide individual lines. The accessible data table always retains the complete result.

The local web server still uses your configured Gemini and Daytona services when their keys are present. If `DAYTONA_API_KEY` is omitted, baseline and scenario simulations run in the local Python process instead.

### Work without external services

For interface development or a deterministic walkthrough without Gemini or Daytona, open:

```text
http://127.0.0.1:8000/?mode=mock
```

This uses bundled contract fixtures and is visibly labelled as demo data. It is not live simulation output.

## Configuration

Environment variables take precedence over values in `.env`.

| Variable | Required | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | For live AI | Gemini API key. `GOOGLE_API_KEY` is also accepted. |
| `GEMINI_MODEL` | For live AI | Gemini model used for extraction and suggestions. |
| `DAYTONA_API_KEY` | No | Enables Daytona execution when the request uses automatic execution. |
| `DAYTONA_API_URL` | No | Overrides the default Daytona API endpoint. |
| `DAYTONA_TARGET` | No | Selects a Daytona target or region configuration. |
| `SIMFORGE_SNAPSHOT` | No | Overrides the content-addressed Daytona snapshot name. |
| `SIMFORGE_REQUEST_TIMEOUT_S` | No | API simulation timeout in seconds; defaults to `180`. |

## Execution modes

Baseline and comparison endpoints accept an execution query parameter:

```text
?execution=auto
?execution=local
?execution=daytona
```

- `auto` uses Daytona when `DAYTONA_API_KEY` is configured and otherwise runs locally.
- `local` runs the deterministic simulator in the application environment.
- `daytona` requires Daytona and fails explicitly if sandbox execution is unavailable.

If Daytona is configured but a remote run fails, SimForge does not silently present a local result as a sandbox result.

### Optional Daytona snapshot

Daytona works without a pre-built snapshot, but a snapshot reduces cold-start time. Build one after configuring `DAYTONA_API_KEY`:

```bash
python scripts/build_snapshot.py
```

Snapshot names include a hash of the simulator files. After changing the simulator or sandbox entry point, run the command again. A missing current snapshot falls back to uploading the current files rather than executing stale code.

## API

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness and active execution backend |
| `POST` | `/api/requirements` | Natural language to a validated or clarifying `ModelSpec` |
| `POST` | `/api/simulations/baseline` | Run the approved baseline model |
| `POST` | `/api/scenarios/suggest` | Return exactly three validated scenario suggestions |
| `POST` | `/api/scenarios/compare` | Run reviewed interventions and return a recommendation |

Use `/api/health?deep=1` for a one-off Daytona round-trip check. A deep check provisions a real sandbox and should not be configured as a frequent platform health probe.

### Core contracts

The simulator input is a validated `ModelSpec`:

```json
{
  "objective": "minimise lost process output",
  "process_family": "buffer_logistics",
  "material": {
    "name": "process water",
    "quantity_unit": "cubic_metres"
  },
  "time": {
    "simulation_days": 3,
    "timestep_minutes": 10
  },
  "parameters": {
    "inflow_rate": {
      "value": 12,
      "unit": "cubic_metres/hour",
      "source": "user"
    }
  }
}
```

Simulation responses preserve the stable shape:

```json
{
  "timeseries": [],
  "metrics": {},
  "events": [],
  "metadata": {}
}
```

Financial comparison is optional. When supplied, the comparison request adds
operation-wide economics and a complete cost set for every scenario:

```json
{
  "economics": {
    "value_per_unit_gbp": 150,
    "capex_amortisation_years": 10,
    "baseline_cost_per_outbound_event_gbp": 400
  },
  "scenarios": [
    {
      "id": "more-buffer",
      "label": "Add buffer capacity",
      "parameter_overrides": {"buffer_count": 3},
      "economics": {
        "capex_gbp": 80000,
        "annual_opex_delta_gbp": 1500,
        "cost_per_collection_gbp": 400
      }
    }
  ]
}
```

`annual_opex_delta_gbp` is signed, so a negative value represents an annual
saving. SimForge does not fill incomplete financial requests with demo cost
assumptions. Without a complete financial context, generic models retain the
deterministic operational ranking.

Scenario comparison responses contain:

```json
{
  "baseline": {},
  "scenarios": [],
  "recommendation": {}
}
```

Financial recommendations are produced only when usable costs are confirmed. Otherwise `metadata.ranking_mode` is `operational`, using this deterministic order:

1. Lowest P95 lost output
2. Lowest expected lost output
3. Lowest failure probability
4. Scenario ID as the tie-breaker

## Deployment

SimForge deploys as one Python ASGI web service. The frontend is served by the same FastAPI process, so no separate frontend build or hosting service is required.

Use these settings on a Python-capable platform such as a container service or buildpack-based web host:

```text
Runtime:       Python 3.12
Build command: pip install -r requirements.txt
Start command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Health path:   /api/health
```

Set the required environment variables in the platform's secret manager rather than uploading `.env`.

### Deployment checklist

1. Configure `GEMINI_API_KEY` and `GEMINI_MODEL`.
2. Optionally configure Daytona credentials.
3. Deploy the repository with the build and start commands above.
4. Confirm `GET /api/health` returns `status: "ok"`.
5. If using Daytona, run one manual `GET /api/health?deep=1` check.
6. Submit one requirements request and one small baseline before opening access to users.

For a Daytona-backed demonstration, warming the sandbox once before presenting avoids the first-run image and snapshot startup delay.

### Production warning

The current application does not include user authentication, tenant isolation, persistent storage, or application-level rate limiting. Do not expose cost-incurring Gemini and Daytona endpoints publicly without adding access control and request limits at the application or gateway layer.

## Testing

Run the complete automated suite:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Check the browser JavaScript syntax:

```bash
node --check static/app.js
```

The current suite covers simulation invariants, reproducibility, unit validation, legacy CO₂ compatibility, API contracts, scenario ranking, partial failures, and Daytona cleanup/equivalence behaviour.

## Command-line demo

The decision pipeline can also be run without the browser:

```bash
python demo.py --execution local --runs 200
python demo.py --execution daytona --runs 200
python demo.py --execution local --json result.json
```

## Repository structure

```text
app/
  main.py                 FastAPI routes and static hosting
  models.py               Pydantic request and response contracts
  requirements_agent.py   Gemini extraction and scenario suggestions
  api_contract.py         ModelSpec-to-simulator mapping and response shaping
  pipeline.py             Local/Daytona execution boundary
  daytona_runner.py       Sandbox lifecycle and result validation
  monte_carlo.py          Seeded stochastic aggregation
  scenario_runner.py      Scenario execution and comparison
  finance.py              Financial metrics and ranking inputs

reference/
  buffer_logistics.py     Generic simulator facade
  co2_simulation.py       Validated compatibility kernel

static/
  index.html              Application interface
  styles.css              Responsive visual system
  app.js                  Requirements, chart, and comparison interactions

scripts/
  build_snapshot.py       Content-addressed Daytona snapshot builder

tests/                    Automated simulation and integration tests
demo.py                   Command-line decision-pipeline demo
```

## Current scope and limitations

- SimForge models buffer-logistics operations, not arbitrary physical systems.
- Every model uses one quantity unit; automatic conversion is intentionally unsupported.
- Gemini availability and quotas affect extraction and scenario suggestions.
- Native Daytona sandbox forking depends on account and region support. When it is unavailable, scenarios use independent isolated sandboxes and report that execution mode.
- The deployed application needs authentication and rate limiting before public production use.
- AI-generated simulator code is not executed by the web workflow.

## Design principles

1. The simulator owns every reported number.
2. Python validation is authoritative over model output.
3. Assumptions and provenance remain visible to the user.
4. Baseline and interventions share the same underlying model and seeded futures.
5. Remote execution must be isolated, validated, and honestly labelled.
6. Operational recommendations must not imply unconfirmed financial value.
