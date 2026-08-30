# SimForge — simulation / Daytona / decision layer

Integration contract for the backend half (Yoann). Written for the AI + UX half
so the two sides can be wired together without reading each other's internals.

## For the AI/UX half: use the contract adapter

`app/api_contract.py` speaks the shape in `static/fixtures/*.json` — ModelSpec
in, `{id, label, status, result, error}` out. One call:

```python
from app.api_contract import run_scenario_comparison, run_baseline

response = run_scenario_comparison({
    "model_spec": {...},                       # as in baseline-request.json
    "scenarios": [{"id": "add-third-tank",
                   "label": "Add a third storage tank",
                   "parameter_overrides": {"tank_count": 3}}],
    "seed": 42,
    "rollout_count": 200,
    "execution": "auto",                       # "local" | "daytona" | "auto"
})
```

It handles the naming gap between the two sides:

| ModelSpec / overrides | simulator config |
|---|---|
| `production_rate` | `production_rate_t_per_hour` |
| `tank_capacity` | `tank_capacity_t` |
| `tanker_capacity` | `tanker_capacity_t` |
| `tank_count`, `collections_per_day`, `missed_collection_probability` | unchanged |
| `time.simulation_days`, `time.timestep_minutes` | unchanged |

A ModelSpec parameter the simulator does not model is **ignored and listed** in
`assumptions.unmapped_model_spec_parameters` — an LLM-written spec may carry
economic or descriptive fields. A *scenario override* that maps to nothing
**raises**, because a dead override would silently invalidate the comparison.

Scenario economics are inferred from the parameter being changed
(`tank_count` → CAPEX, `collections_per_day` → per-trip cost,
`tanker_capacity` → dearer trips), or you can pass an explicit `economics` block
per scenario.

**Scenario failures are tolerated.** A scenario that cannot execute comes back
`status: "failed"` with `{code, message, retryable}` and is left out of the
ranking; the rest still produce a decision. One dead sandbox will not take the
live demo down.

**When nothing pays for itself**, `recommendation.scenario_id` is `null` and
`rejected_scenario_id` names the best-ranked option, with its deltas and
financials still filled in so the UI can explain the rejection.

⚠️ The fixture ModelSpec uses `tanker_capacity: 30` against 24 t/day of
production. That leaves so much recovery capacity that the baseline loses
**nothing**, so no intervention can pay back and the demo has no decision to
make. Use **24 t** for the demo — collection capacity exactly matching
production is what creates the failure mode.

## One call (internal shape)

```python
from app.pipeline import run_decision_pipeline

comparison = run_decision_pipeline(
    base_config=None,        # None -> app.scenario_runner.BASELINE_CONFIG
    scenarios=None,          # None -> app.scenario_runner.DEMO_SCENARIOS
    n_runs=200,
    base_seed=20260830,
    execution="auto",        # "local" | "daytona" | "auto"
)
```

`execution="auto"` uses Daytona when `DAYTONA_API_KEY` is set, otherwise runs
in-process. Both paths use the same simulator and produce the same numbers.

The whole result is JSON-serialisable. Nothing else needs importing.

## What comes back

```jsonc
{
  "baseline": {
    "name": "baseline",
    "label": "Baseline (2 x 45 t tanks, 1 collection/day)",
    "config": { "tank_count": 2, "tank_capacity_t": 45.0, ... },
    "operational": {
      "expected_lost_production_t": 12.2,
      "p95_lost_production_t": 57.9,
      "failure_probability": 0.465,
      "expected_production_t": 714.8,
      "max_storage_utilisation": 0.93,
      "mean_collections_completed": 27.6
    },
    "stats": { "lost_production_t": {"mean":…, "std":…, "p05":…, "p50":…, "p95":…, "min":…, "max":…}, … },
    "runs": { "lost_production_t": [ … per-rollout values, for histograms … ] },
    "representative_run": { "timeseries": [ … ], "metrics": {…}, "events": [ … ] }
  },

  "scenarios": [
    {
      "name": "extra_tank",
      "label": "Add a third 45 t storage tank",
      "overrides": { "tank_count": 3 },
      "config": { … },
      "operational": { …same keys as above, plus… 
        "expected_loss_reduction_t": 10.7,
        "expected_loss_reduction_pct": 87.9,
        "p95_loss_reduction_pct": 77.7,
        "failure_probability_reduction_pp": 38.5
      },
      "financial": {
        "capex_gbp": 80000.0,
        "annualised_capex_gbp": 8000.0,
        "annual_opex_delta_gbp": 1500.0,
        "annual_collection_cost_delta_gbp": 0.0,
        "recovered_output_t_per_year": 130.7,
        "annualised_benefit_gbp": 19609.0,
        "net_annual_benefit_gbp": 18109.0,
        "annual_value_gbp": 10109.0,
        "payback_years": 4.4,
        "payback_status": "pays_back",
        "roi_first_year": 0.226,
        "benefit_cost_ratio": 2.06
      },
      "stats": { … }, "runs": { … }, "representative_run": { … },
      "sandbox_id": "…"          // only when executed in Daytona
    }
  ],

  "ranking": [
    { "rank": 1, "name": "extra_tank", "annual_value_gbp": 10109.0,
      "payback_years": 4.4, "payback_status": "pays_back",
      "expected_loss_reduction_pct": 87.9, "p95_lost_production_t": 12.9,
      "resilience_rank": 3 }
  ],

  "recommendation": {
    "decision": "extra_tank",          // or "do_nothing" if nothing pays back
    "label": "Add a third 45 t storage tank",
    "rule": "annual_value_gbp = …",
    "annual_value_gbp": 10109.0,
    "payback_years": 4.4,
    "best_financial": "extra_tank",
    "most_resilient": "extra_collection",
    "financial_and_resilience_agree": false,
    "note": "… a genuine trade-off."
  },

  "assumptions": {
    "n_runs": 200, "base_seed": 20260830,
    "ranking_rule": "…", "failure_definition": "…",
    "finance_config": { "value_per_tonne_gbp": 150.0, "capex_amortisation_years": 10.0,
                        "days_per_year": 365.0 },
    "common_random_numbers": "…"
  },

  "execution": {
    "mode": "daytona",
    "isolation_mode": "native_fork",   // or "independent_sandboxes"
    "baseline_sandbox_id": "…",
    "sandbox_environment": { "python": "3.13.x", "machine": "x86_64" },
    "timings": { "create_baseline_s": …, "upload_s": …, "baseline_exec_s": …,
                 "forks_exec_s": …, "total_s": … }
  },

  "runtime_seconds": 1.99
}
```

### Notes for the UI

* `payback_years` is `null` whenever payback is not mathematically meaningful.
  Read `payback_status` (`pays_back` / `opex_only_positive` / `not_viable`) —
  never render a negative payback.
* `expected_loss_reduction_pct` is `null` when the baseline lost nothing.
* `representative_run.timeseries` rows are
  `{step, t_hours, production_t, lost_production_t, collected_t, storage_level_t, storage_utilisation}`.
  Flows are summed over the row's window, levels are sampled at its end, so
  striding never loses material. Default stride 6 → hourly, 720 rows for 30 days.
* `representative_run` is rollout 0 of that scenario's own Monte Carlo batch —
  a future that was actually counted, not a separate run.
* `runs.lost_production_t` is the raw per-rollout sample, ready for a histogram.
* Everything in `assumptions` is meant to be shown. The ranking rule is stated
  so the recommendation is never a black box.

## ModelSpec → config

`ModelSpec.parameters` maps onto the simulator config by name. The full set,
with the demo defaults:

| config key | default | meaning |
|---|---|---|
| `simulation_days` | 30 | horizon |
| `timestep_minutes` | 10 | timestep |
| `production_rate_t_per_hour` | 1.0 | continuous production |
| `production_variability_pct` | 0.05 | std-dev as a fraction of the rate |
| `tank_count` | 2 | number of tanks |
| `tank_capacity_t` | 45.0 | capacity per tank |
| `initial_storage_t` | 20.0 | starting inventory (absolute, so scenarios start equal) |
| `collections_per_day` | 1 | scheduled tanker slots per day |
| `tanker_capacity_t` | 24.0 | tonnes per trip |
| `first_collection_hour` | 8.0 | hour-of-day of the first slot |
| `missed_collection_probability` | 0.08 | per scheduled collection |
| `collection_delay_probability` | 0.35 | per scheduled collection |
| `collection_delay_minutes` | 240.0 | max delay, uniform on `[0, this]` |
| `min_collection_load_t` | 0.0 | stand a trip down below this level |
| `record_timeseries` | true | |
| `timeseries_stride` | 1 | keep one row every N steps |

A config key that is not in this table raises `ValueError`. That is deliberate:
a typo in a generated ModelSpec must fail loudly rather than be ignored and
silently invalidate a comparison.

To turn a ModelSpec into a run:

```python
config = {k: p["value"] for k, p in model_spec["parameters"].items()
          if k in reference.co2_simulation.DEFAULT_CONFIG}
comparison = run_decision_pipeline(base_config=config)
```

## Adding an intervention

A scenario is config overrides plus economics — never a new simulator:

```python
scenarios = [{
    "name": "bigger_tanks",
    "label": "Replace both tanks with 70 t units",
    "overrides": {"tank_capacity_t": 70.0},
    "economics": {
        "capex_gbp": 250000.0,
        "annual_opex_delta_gbp": 3000.0,
        "cost_per_collection_gbp": 400.0,   # per trip, in this scenario
    },
}]
```

The recurring logistics cost is derived from the number of tanker trips the
simulation actually performed, not assumed.

## Daytona execution — what is real

Verified against the live API (region `eu`, 2026-08-30):

| | |
|---|---|
| Baseline sandbox create + upload | ~3.9 s |
| 200 rollouts inside the sandbox | ~0.7 s |
| 3 scenario sandboxes, in parallel | ~3.0 s |
| **Full comparison, end to end** | **~8 s** (local: ~2 s) |
| Sandbox Python | 3.14.4 (local: 3.12.3) |
| Numbers vs local | **bit-identical**, including the representative timeseries |
| Sandboxes leaked | 0 |

Reproducibility holds across a Python minor-version gap and a different machine,
which is the point of deriving seeds with `blake2b` rather than `hash()`.

### On forking

`Sandbox.fork()` is a real, stable SDK feature (copy-on-write clone) and the
runner implements it — `prepare()` asks for a VM-class snapshot precisely so the
baseline is forkable, and `fork()` is called per scenario.

**It does not run on this account.** Fork / pause / hot-snapshot are supported
only on VM-class sandboxes; container-class sandboxes return

```
422 Unprocessable Entity — "Forking is not supported for this sandbox"
```

and no VM snapshot (`daytona-vm-small`, `daytona-vm`, `daytona-vm-medium`, …) is
provisionable in region `eu` or `us` for this key:

```
400 — "Snapshot daytona-vm-small is not available in region eu"
```

So the runner detects this once during `prepare()`, then executes **each
scenario in its own independently provisioned sandbox** and reports:

```json
"execution": {
  "isolation_mode": "independent_sandboxes",
  "fork_unavailable_reason": "DaytonaBadRequestError: … not available in region eu"
}
```

Detecting it once rather than per scenario is also worth ~11 s of demo latency
(19.3 s → 8.0 s), since each doomed `fork()` is a full API round trip.

**Do not claim native forks in the pitch while `isolation_mode` says
`independent_sandboxes`.** What is true: scenarios are executed in isolated
Daytona sandboxes, one per counterfactual, in parallel, and each result is
rejected unless its rollout seeds match the host's. If a VM-capable region or
account is enabled, `isolation_mode` flips to `native_fork` with no code change.

## Guarantees this layer provides

1. Same `(config, seed)` → same result, in-process or in a sandbox.
2. Mass balance and capacity bounds are asserted on every run, including
   results returning from Daytona.
3. Scenario *i* and baseline *i* are the same stochastic future
   (`derive_seed(base_seed, "rollout", i)`), so a comparison isolates the
   intervention.
4. A result from a sandbox is rejected unless its rollout seeds match the ones
   the host derived.
5. No KPI in the payload requires a language model to produce it.

## Running it

```bash
python -m pytest tests/ -q          # 166 tests, ~2s
python demo.py                      # local, ~2s
python demo.py --execution daytona  # one forked sandbox per scenario
python demo.py --json out.json      # full payload incl. representative runs
```
