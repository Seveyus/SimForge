# SimForge — handover

State of `main` as of the last commit. Everything below was run and verified,
not assumed. Read the **Demo runbook** first; the rest is reference.

---

## Demo runbook

Requires Python 3.10 or newer. macOS's system Python 3.9 cannot install the
pinned FastAPI, Daytona or pytest versions.

```bash
pip install -r requirements.txt
cp .env.example .env          # DAYTONA_API_KEY, GEMINI_API_KEY, GEMINI_MODEL=gemini-3.6-flash
python scripts/build_snapshot.py
uvicorn app.main:app
```

Open **http://localhost:8000** — it opens in live mode.

### ⚠️ Warm it up before presenting

```bash
python demo.py --execution daytona --runs 200
```

A **cold run takes ~25 s**; warm runs take **5–6 s**. The difference is Daytona
runners pulling the snapshot image for the first time. Run the demo once, a few
minutes before you present, or the first live click on stage will hang for
twenty-five seconds. This is the single biggest avoidable demo failure.

Also run `curl 'localhost:8000/api/health?deep=1'` — it provisions a real
sandbox and reports the round trip. If that is not `ok`, do not start the demo.

### The story to tell

```
baseline           E[lost] 13.1 t   P95 59.4 t   fail 45%
+ 3rd tank          1.9 t   -85%    →  +£10.8k/y, payback 4.2 y   ← recommended
+ 2nd collection    0.0 t  -100%    →  -£111k/y
36 t tanker         0.0 t  -100%    →  -£16.4k/y
```

The punchline: **the two operationally perfect fixes are the financially wrong
ones.** The tank does not eliminate the loss and still wins. No LLM produced any
of those numbers.

The baseline fails because a 24 t tanker against 24 t/day of production leaves
zero recovery capacity, so a missed collection is permanent. Do not raise the
tanker to 30 t — the plant then never fills and there is no decision to show.

---

## What is true about Daytona (say this, not more)

**True:** each counterfactual executes in its own isolated Daytona sandbox, in
parallel; the simulator never runs in the application process; the model is
pre-baked into a Daytona snapshot so sandboxes start with nothing to upload;
every result is rejected unless its rollout seeds match the ones the host
derived. The execution panel in the UI shows the real sandbox ids.

**Not true — do not claim it:** native sandbox forking. `Sandbox.fork()` is
implemented in `app/daytona_runner.py` and would be used automatically, but this
account cannot fork. Proven four ways:

- container sandboxes → `422 "Forking is not supported for this sandbox"`
- `daytona-vm-*` snapshots → `"not available in region eu"` (and `us`)
- building our own VM snapshot → `"No runners are configured in region 'eu' for
  sandbox class 'linux-vm'"` (and `us`)
- every `daytona-vm-*` snapshot lists `region_ids=[]`

If a judge asks: forking needs a VM-class sandbox, no region serves them on this
key, so we execute one isolated sandbox per scenario instead. The UI says so on
screen. If VM access is ever enabled, `isolation_mode` flips to `native_fork`
with no code change.

---

## Architecture

```
static/          browser UI                     (Ebrahim)
  ↓ fetch
app/main.py      FastAPI, 3 routes, error envelope
  ↓
app/api_contract.py   ModelSpec ⇄ simulator config, response shaping
  ↓
app/pipeline.py       local or Daytona
  ↓
app/daytona_runner.py sandbox lifecycle, snapshot, validation
  ↓
app/monte_carlo.py    N seeded futures per scenario
  ↓
reference/buffer_logistics.py generic simulator facade — stdlib only
reference/co2_simulation.py   numerical compatibility kernel
  ↓
app/finance.py        CAPEX vs OPEX, payback, annual value
```

`app/requirements_agent.py` and `app/simulator_generator.py` (Gemini) are
Ebrahim's; `app/models.py` holds the shared pydantic contracts.

### Routes

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/health` | `?deep=1` round-trips a real sandbox |
| `POST` | `/api/simulations/baseline` | → `SimulationResult` |
| `POST` | `/api/scenarios/compare` | → `ScenarioComparison` |
| `POST` | `/api/scenarios/suggest` | → exactly three editable Gemini suggestions |
| `POST` | `/api/requirements` | → Gemini agent |

### Buffer-logistics contract

`ModelSpec.process_family` is `buffer_logistics` and `material` declares a name
plus one of `tonnes`, `kilograms`, `litres`, `cubic_metres`, or `items`.
Canonical inputs are `inflow_rate`, `buffer_count`, `buffer_capacity`,
`outbound_events_per_day`, and `outbound_capacity`. Legacy CO₂ aliases remain
accepted. Without confirmed scenario economics, ranking is operational and
`metadata.ranking_mode` is `operational`.

`?execution=local` skips Daytona (~2 s, no network) — useful when the network is
bad. `?execution=daytona` forces it. Default picks by whether the key is set.

---

## Verified

- **260 tests**, ~8 s: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`
- Sandbox results are **bit-identical** to local, including every timeseries row
- Mass balance holds to ~1e-13 on every run; asserted on results returning from
  Daytona too
- Same seed → identical output, across processes and Python versions
- Responses validate against Ebrahim's own pydantic models
  (`validate_contract_response`), asserted on every response in the tests
- His frontend validators, extracted from `app.js` and run against a live
  response, accept it
- Zero leaked sandboxes after every run
- **The whole demo flow, live end to end** (Gemini + Daytona):
  natural language → `needs_clarification` (it asks for the objective) → answer →
  `ready` ModelSpec with provenance → baseline 13.08 t lost → three scenarios in
  three isolated sandboxes in ~3 s → recommends the third tank
- Live browser-level Gemini → Daytona end-to-end run passed on 2026-08-30:
  Gemini produced a `ModelSpec` after clarification, the UI rendered the
  100-rollout baseline and 720-point chart, and all three counterfactual
  scenarios succeeded with zero browser console errors
- Live process-water generalisation passed on 2026-08-30: Gemini extracted a
  `cubic_metres` ModelSpec and proposed three editable interventions; Daytona
  completed the 100-rollout baseline plus all three scenarios; operational
  ranking returned no financial claims; charts, events, and comparisons used
  neutral cubic-metre labels; zero browser console errors and zero active
  sandboxes remained.

---

## Known gaps and risks

| | |
|---|---|
| **Cold start ~25 s** | Warm up before presenting. Highest-impact risk. |
| `metadata.ranking` unused by the UI | The ranking and its stated rule are in the payload but not rendered. Cheap win if there is time. |
| Metric labels are raw keys | The comparison table shows `annual_value_gbp` rather than "Annual value". Cosmetic. |
| Gemini requires a configured key | Live extraction is verified. If `GEMINI_API_KEY` is unset, `/api/requirements` returns `503 gemini_unavailable` and the UI shows its error state — the simulation half still works. |
| No `simulator_generator` route | AI-generated simulators exist as a module but are not wired to an endpoint. The demo uses the known-good simulator, which is the stronger claim anyway. |

If Daytona fails on stage, add `?execution=local` — everything still works and
the numbers are identical. Say so plainly rather than hiding it.

---

## If you change the simulator

Re-run `python scripts/build_snapshot.py`. The snapshot name carries a content
hash of the baked files, so stale snapshots are never silently reused — the
runner falls back to uploading, which is slower but always correct.

---

## Where the numbers come from

Every figure on screen traces through `reference/buffer_logistics.py` to the
validated compatibility kernel (physics) or
`app/finance.py` (economics), through `app/monte_carlo.py`. The LLM writes the
`ModelSpec` and can phrase the recommendation; it cannot change a number. If
someone asks "where did that come from", the answer is a function, and
`HANDOFF.md` maps every displayed value to its exact JSON path.

`baseline.result.metadata.assumptions` carries the ranking rule, the failure
definition, the finance config and the CRN explanation — all meant to be shown.
