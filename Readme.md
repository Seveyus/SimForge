# SimForge

### Turn operations into executable worlds. Fork the future before you build it.

SimForge is an AI operations modelling and decision-support system that turns a natural-language description of a physical operation into an executable simulation, then forks that model into multiple possible futures to stress-test operational and CAPEX decisions.

Instead of asking an LLM:

> “Should we buy another tank?”

SimForge builds a model of the operation, executes it, simulates uncertainty, tests alternative interventions, and compares the operational and financial outcomes.

**The LLM explains the result. The simulator produces the numbers.**

---

## Why

Industrial infrastructure decisions are expensive. Storage capacity, logistics schedules, processing equipment and operational buffers are often evaluated using averages, spreadsheets, static assumptions and a small number of scenarios.

But physical systems are dynamic:

- collections are delayed
- equipment fails
- production fluctuates
- queues form
- storage fills

A decision that looks good in an average spreadsheet may fail under operational uncertainty.

SimForge lets teams **test infrastructure decisions in software before committing capital in the physical world**.

---

## Hackathon Demo

The initial end-to-end demo models a CO₂ production, storage and tanker-collection operation.

```text
Continuous production
        |
        v
    CO₂ storage
        |
        v
Tanker collections
```

Example baseline:

```text
Production rate:          1 tonne/hour
Storage tanks:            2
Capacity per tank:        45 tonnes
Collections:              ~1/day
Collection reliability:   stochastic
Objective:                minimise lost production
```

Failure chain:

```text
Tanker collection is missed
        ↓
Storage keeps filling
        ↓
Tank capacity is reached
        ↓
Production must be curtailed
        ↓
Output / revenue is lost
```

SimForge then tests interventions such as:

- add another storage tank
- increase tanker collection frequency
- increase tanker capacity
- modify collection timing
- add temporary buffer capacity
- reduce downtime

The important point: **SimForge executes these interventions as alternative futures rather than merely describing them.**

---

## Core Idea

```text
Natural-language operation
            |
            v
    Requirements Agent
            |
            v
        ModelSpec
            |
            v
   Simulation Generator
            |
            v
   Baseline Simulator
            |
            v
      Daytona Sandbox
            |
            v
       Baseline State
       /    |    |    \
      /     |    |     \
   Fork A Fork B Fork C Fork D
      |     |      |      |
   + tank  + trip larger  schedule
                 tanker   change
      |     |      |      |
      +-----+------+------+
            |
            v
    Parallel simulations
            |
            v
 Monte Carlo / stress testing
            |
            v
 Operational + financial ranking
```

---

## Why Daytona

AI-generated simulation code should not be blindly executed inside the main application.

SimForge uses Daytona as the isolated execution layer.

```text
Generated Python
      |
      v
Static validation
      |
      v
Daytona sandbox
      |
      v
Execution
      |
      v
Structured result
      |
      v
Schema validation
```

### Forking Futures

Once a baseline operational environment exists, SimForge can branch it into several independent scenarios.

```text
                   BASELINE
                       |
        +--------------+--------------+
        |              |              |
        v              v              v
   Extra Tank     Extra Collection  Larger Tanker
        |              |              |
   N rollouts      N rollouts      N rollouts
        +--------------+--------------+
                       |
                       v
               Compare outcomes
```

Each fork starts from the same operational model and changes only the intervention being tested.

> Same operation. Same assumptions. Different decision.

---

## AI + Simulation Responsibilities

SimForge deliberately separates reasoning from numerical truth.

### The LLM is responsible for

- understanding the user's operation
- identifying entities and constraints
- asking clarification questions
- constructing the `ModelSpec`
- generating simulation logic
- explaining simulation results

### Python is responsible for

- time evolution
- resource constraints
- storage behaviour
- queue behaviour
- random events
- Monte Carlo rollouts
- KPIs
- financial calculations
- scenario comparison

### Daytona is responsible for

- isolated execution
- running AI-generated simulation code
- scenario execution
- reproducibility
- failure isolation

**If the backend did not calculate a number, the assistant cannot present it as a simulation result.**

---

## ModelSpec

Before generating code, the system transforms the user's description into a structured model.

```json
{
  "objective": "minimise lost production",
  "process_family": "production_storage_collection",
  "time": {
    "simulation_days": 30,
    "timestep_minutes": 10
  },
  "parameters": {
    "production_rate": {
      "value": 1.0,
      "unit": "tonnes/hour",
      "source": "user"
    },
    "tank_count": {
      "value": 2,
      "source": "user"
    },
    "tank_capacity": {
      "value": 45,
      "unit": "tonnes",
      "source": "user"
    },
    "collections_per_day": {
      "value": 1,
      "source": "user"
    },
    "missed_collection_probability": {
      "value": 0.08,
      "source": "assumption"
    }
  }
}
```

---

## Data Provenance

Every important parameter carries provenance.

```text
USER
Explicitly supplied by the operator

RESEARCHED
Obtained from an external source

ESTIMATED
Derived from available information

ASSUMPTION
Introduced to make the initial model executable
```

Example:

```json
{
  "tank_capex": {
    "value": 80000,
    "unit": "GBP",
    "source": "researched"
  }
}
```

The UI should clearly distinguish these categories. We never silently turn an estimate into a plant-specific fact.

---

## Reality-Anchored Simulation

SimForge does not require a perfect historical dataset.

The MVP combines:

```text
real/user parameters
        +
researched benchmarks
        +
explicit assumptions
        +
physics / operational constraints
        +
stochastic events
        =
executable operational model
```

The goal is not to pretend we know reality perfectly. The goal is to make assumptions explicit and test decisions under uncertainty.

---

## Simulation Contract

Every generated simulator exposes the same interface:

```python
def simulate(config: dict, seed: int | None = None) -> dict:
    ...
```

And returns:

```json
{
  "timeseries": [],
  "metrics": {},
  "events": []
}
```

Example:

```json
{
  "metrics": {
    "total_production_t": 720,
    "lost_production_t": 42,
    "tank_utilisation": 0.81,
    "overflow_events": 3
  }
}
```

---

## Monte Carlo Stress Testing

A single deterministic simulation is not enough.

Each scenario can be executed multiple times with different random seeds.

Random variables can include:

- missed tanker collections
- collection delays
- production variation
- equipment downtime
- processing delays

Example output:

```text
Baseline
--------------------------------
Expected lost production: 124 t
P95 lost production:      201 t
Failure probability:      43%

Add third tank
--------------------------------
Expected lost production:  38 t
P95 lost production:       74 t
Failure probability:       11%
```

This turns:

> “What happens?”

into:

> “What is likely to happen, and how bad can it get?”

---

## Counterfactual Scenario Engine

CAPEX scenarios should not require rewriting the simulation.

The simulator defines behaviour. The configuration defines the world.

Baseline:

```json
{
  "tank_count": 2,
  "tank_capacity": 45,
  "collections_per_day": 1
}
```

Scenario A:

```json
{
  "tank_count": 3
}
```

Scenario B:

```json
{
  "collections_per_day": 2
}
```

Scenario C:

```json
{
  "tanker_capacity": 30
}
```

**Same simulator. Different future.**

---

## Decision Layer

Simulation outputs feed deterministic decision calculations.

Operational metrics:

- lost production
- recovered production
- capacity utilisation
- queue time
- downtime
- failure probability
- P95 downside

Financial metrics:

- CAPEX
- annual recovered output
- annual benefit
- ROI
- payback period

```python
recovered_output = baseline_loss - scenario_loss
period_benefit = recovered_output * value_per_tonne
annual_benefit = period_benefit * 365 / simulation_days
payback_years = capex / annual_benefit
```

These calculations are performed in Python, **not by the LLM**.

---

## Decision Output

The final result should be immediately understandable.

```text
RECOMMENDATION

Increase collection frequency

Expected lost production
142 t → 24 t
-83%

Failure probability
41% → 7%

Estimated annual benefit
£312,000

Estimated incremental cost
£95,000/year
```

Then optionally:

```text
WHY NOT ADD THE TANK?

Third tank:
£80,000 CAPEX
-67% expected lost production

Additional collection:
-83% expected lost production
better downside protection
```

SimForge does not only simulate. **It compares decisions.**

---

## Reliability Loop

Generated code can fail.

```text
Generate simulator
        |
        v
Validate
        |
        v
Execute in Daytona
        |
    success?
     /    \
   yes     no
    |       |
    v       v
 result   error
            |
            v
     AI repair attempt
            |
            v
        Daytona retry
```

For the HackSprint, one repair attempt is sufficient. The goal is safe execution, not a fully autonomous debugger.

---

## Architecture

```text
Frontend
   |
   v
FastAPI
   |
   v
Requirements Agent
   |
   v
ModelSpec
   |
   v
Simulation Generator
   |
   v
Generated Python
   |
   v
Daytona
   |
   +-------- Baseline
   |
   +-------- Scenario Fork A
   |
   +-------- Scenario Fork B
   |
   +-------- Scenario Fork C
   |
   v
Simulation Results
   |
   v
Monte Carlo Aggregation
   |
   v
Financial Engine
   |
   v
Comparison / Recommendation
```

---

## Stack

### Backend
- Python
- FastAPI
- Pydantic

### AI
- OpenAI API

### Execution
- Daytona

### Simulation
- Python
- deterministic time-step engine
- seeded stochastic simulation
- Monte Carlo scenario evaluation

### Frontend
- HTML
- CSS
- JavaScript
- Chart.js

### Optional research
- Tavily

---

## Repository Structure

```text
simforge/
│
├── README.md
├── AGENTS.md
├── PROJECT.md
│
├── app/
│   ├── main.py
│   ├── models.py
│   ├── requirements_agent.py
│   ├── simulator_generator.py
│   ├── daytona_runner.py
│   ├── scenario_runner.py
│   ├── monte_carlo.py
│   ├── finance.py
│   └── provenance.py
│
├── reference/
│   └── co2_simulation.py
│
├── static/
│   ├── index.html
│   ├── styles.css
│   └── app.js
│
├── tests/
│   ├── test_simulation.py
│   ├── test_finance.py
│   └── test_scenarios.py
│
├── requirements.txt
└── .env.example
```

---

## HackSprint Build Order

### P0 — Must Work

1. **Known-good CO₂ simulator**
   - `simulate(config, seed)`
   - tank levels
   - collections
   - lost production
   - events

2. **Daytona execution**

```text
Python simulator
      ↓
Daytona
      ↓
execution
      ↓
structured JSON
```

3. **Baseline UI**
   - tank level over time
   - collection events
   - lost production
   - key KPIs

4. **Scenario comparison**

```text
Baseline
vs
+1 tank
vs
+1 collection/day
```

5. **Stochastic stress test**
   - expected loss
   - P95 loss
   - failure probability

6. **Financial comparison**
   - recovered output
   - annual benefit
   - CAPEX
   - payback

### P1 — Hackathon Differentiators

7. Daytona scenario forks
8. Natural-language `ModelSpec`
9. AI-generated simulator
10. Validation + one repair attempt

### P2 — Only If Everything Else Works

11. External research for missing CAPEX / benchmark values
12. UI polish
13. Additional industrial example

**Do not start with multiple industries. One outstanding end-to-end demo is better than five partially working ones.**

---

## Team Split

### Yoann — Simulation, Daytona & Decision Engine

Ownership:

```text
reference/co2_simulation.py
app/daytona_runner.py
app/scenario_runner.py
app/monte_carlo.py
app/finance.py
tests/
```

Responsibilities:

- build the physical CO₂ simulation
- model missed collections and delays
- implement seeded stochastic runs
- implement Monte Carlo aggregation
- implement baseline vs intervention scenarios
- integrate Daytona execution
- implement Daytona scenario forks if feasible
- calculate operational KPIs
- calculate deterministic financial metrics
- validate simulation correctness
- own final technical integration

### Teammate — AI Modelling & UX

Ownership:

```text
app/models.py
app/requirements_agent.py
app/simulator_generator.py
app/provenance.py
static/
```

Responsibilities:

- natural language → `ModelSpec`
- clarification questions
- structured parameter extraction
- source/provenance labels
- generated simulator prompt
- frontend
- charts
- scenario comparison UI
- assumptions review
- optional Tavily research

---

## Integration Contract

### ModelSpec → simulator

```json
{
  "objective": "minimise lost production",
  "time": {},
  "parameters": {}
}
```

### Simulator → backend

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

Do not couple frontend logic directly to simulation internals.

---

## Demo Script

### 1. Describe the operation

> We produce around one tonne of CO₂ per hour. We have two 45-tonne storage tanks and normally one tanker collection per day.

The AI asks missing questions.

### 2. Build the world

SimForge creates the `ModelSpec` and shows which values are:

- supplied
- assumed
- estimated
- researched

### 3. Execute

The simulator runs inside Daytona.

The dashboard shows the baseline operation.

Then:

> A tanker collection is missed.

Storage approaches capacity, production is curtailed and lost output appears.

### 4. Fork the future

Ask:

> What should we change?

SimForge tests:

```text
Baseline
+ tank
+ collection
larger tanker
```

### 5. Stress-test

Each intervention is run across many stochastic futures.

### 6. Decide

The system ranks interventions by:

```text
Operational resilience
+
Recovered production
+
CAPEX
+
Payback
```

---

## Product Positioning

### Long

An AI operations engineer that turns messy descriptions of physical systems into executable operational models and stress-tests infrastructure decisions before companies spend the money.

### Short

> **Describe your operation. Fork the future before you build it.**

### One-line Pitch

> **SimForge lets companies simulate hundreds of possible futures for a physical operation and test CAPEX decisions before committing capital.**

---

## Principles

1. The simulation owns the numbers.
2. The LLM explains; it does not fabricate KPIs.
3. Every assumption is visible.
4. Scenarios use the same underlying model.
5. Generated code executes in isolation.
6. Prefer reproducible stochastic simulation.
7. Build one excellent end-to-end demo.
8. Daytona must be part of the product architecture, not a checkbox.
9. Decision quality matters more than chatbot complexity.
10. Demo the failure before demoing the solution.
