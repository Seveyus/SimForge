"""Tests for the scenario engine and the Monte Carlo layer.

The two properties that matter most here:
  * every scenario goes through the *same* simulator, only the config differs;
  * scenario i and baseline i are the same stochastic future (common random
    numbers), so the comparison is a genuine counterfactual.
"""

from __future__ import annotations

import pytest

from app.monte_carlo import (
    AGGREGATED_METRICS,
    percentile,
    representative_run,
    rollout_seed,
    run_monte_carlo,
    summarise,
)
from app.scenario_runner import (
    BASELINE_CONFIG,
    DEMO_SCENARIOS,
    RANKING_RULE,
    apply_overrides,
    compare_scenarios,
    rank_scenarios,
    run_scenario,
    run_scenario_monte_carlo,
)

FAST = dict(BASELINE_CONFIG, simulation_days=10)
N = 25  # keep the suite fast; correctness here does not need 200 rollouts


# --------------------------------------------------------------------------
# Config overrides
# --------------------------------------------------------------------------

def test_overrides_change_only_what_they_name():
    base = apply_overrides(BASELINE_CONFIG, None)
    changed = apply_overrides(BASELINE_CONFIG, {"tank_count": 3})
    assert changed["tank_count"] == 3
    assert {k: v for k, v in changed.items() if k != "tank_count"} == {
        k: v for k, v in base.items() if k != "tank_count"
    }


def test_overrides_do_not_mutate_the_baseline_config():
    before = dict(BASELINE_CONFIG)
    apply_overrides(BASELINE_CONFIG, {"tank_count": 9})
    assert BASELINE_CONFIG == before


def test_a_typo_in_an_override_fails_loudly():
    """A silently ignored override would invalidate a whole comparison."""
    with pytest.raises(ValueError, match="unknown config keys"):
        apply_overrides(BASELINE_CONFIG, {"tank_counts": 3})


def test_extra_tank_scenario_changes_capacity_correctly():
    cfg = apply_overrides(BASELINE_CONFIG, {"tank_count": 3})
    assert cfg["tank_count"] * cfg["tank_capacity_t"] == 135.0
    result = run_scenario(BASELINE_CONFIG, {"tank_count": 3}, seed=1)
    assert result["metrics"]["total_capacity_t"] == 135.0


def test_every_demo_scenario_uses_the_same_simulator():
    """All interventions are config overrides on one simulator, by construction."""
    calls: list[dict] = []

    def spy(config, seed=None):
        calls.append(config)
        from reference.co2_simulation import simulate as real
        return real(config, seed)

    for scenario in DEMO_SCENARIOS:
        run_scenario(BASELINE_CONFIG, scenario["overrides"], seed=1, simulate_fn=spy)
    assert len(calls) == len(DEMO_SCENARIOS)
    # the configs differ only in the keys each scenario overrides
    base = apply_overrides(BASELINE_CONFIG, None)
    for cfg, scenario in zip(calls, DEMO_SCENARIOS):
        differing = {k for k in cfg if cfg[k] != base[k]}
        assert differing == set(scenario["overrides"])


def test_demo_scenarios_are_all_valid_configs():
    for scenario in DEMO_SCENARIOS:
        cfg = apply_overrides(BASELINE_CONFIG, scenario["overrides"])
        assert cfg["tank_count"] >= 1


# --------------------------------------------------------------------------
# Monte Carlo
# --------------------------------------------------------------------------

def test_monte_carlo_runs_the_requested_number_of_rollouts():
    mc = run_monte_carlo(FAST, n_runs=N)
    assert mc["n_runs"] == N
    assert len(mc["seeds"]) == N
    assert len(set(mc["seeds"])) == N  # distinct futures
    assert len(mc["runs"]["lost_production_t"]) == N


def test_monte_carlo_is_reproducible():
    a = run_monte_carlo(FAST, n_runs=N, base_seed=7)
    b = run_monte_carlo(FAST, n_runs=N, base_seed=7)
    assert a["stats"] == b["stats"]
    assert a["failure_probability"] == b["failure_probability"]


def test_monte_carlo_aggregates_every_declared_metric():
    mc = run_monte_carlo(FAST, n_runs=N)
    assert set(mc["stats"]) == set(AGGREGATED_METRICS)
    for stat in mc["stats"].values():
        assert set(stat) == {"mean", "std", "min", "p05", "p50", "p95", "max"}
        assert stat["min"] <= stat["p50"] <= stat["max"]
        assert stat["p05"] <= stat["p95"]


def test_failure_probability_is_a_share_of_runs_with_any_loss():
    mc = run_monte_carlo(FAST, n_runs=N)
    losses = mc["runs"]["lost_production_t"]
    expected = sum(1 for x in losses if x > 1e-6) / len(losses)
    assert mc["failure_probability"] == pytest.approx(expected)
    assert 0.0 <= mc["failure_probability"] <= 1.0


def test_failure_probability_is_zero_when_nothing_can_go_wrong():
    safe = dict(FAST, missed_collection_probability=0.0, tanker_capacity_t=40.0,
                collection_delay_probability=0.0)
    assert run_monte_carlo(safe, n_runs=N)["failure_probability"] == 0.0


def test_failure_probability_is_one_when_everything_goes_wrong():
    doomed = dict(FAST, missed_collection_probability=1.0, simulation_days=30)
    assert run_monte_carlo(doomed, n_runs=10)["failure_probability"] == 1.0


def test_monte_carlo_switches_timeseries_off():
    mc = run_monte_carlo(dict(FAST, record_timeseries=True), n_runs=3)
    assert mc["config"]["record_timeseries"] is False


def test_monte_carlo_rejects_zero_runs():
    with pytest.raises(ValueError, match="n_runs"):
        run_monte_carlo(FAST, n_runs=0)


def test_percentile_matches_linear_interpolation():
    data = [1, 2, 3, 4]
    assert percentile(data, 0) == 1
    assert percentile(data, 100) == 4
    assert percentile(data, 50) == pytest.approx(2.5)
    assert percentile([5], 95) == 5


def test_summarise_on_a_constant_sample():
    s = summarise([3.0] * 5)
    assert s["mean"] == 3.0 and s["std"] == 0.0
    assert s["p05"] == s["p95"] == 3.0


def test_representative_run_is_one_of_the_monte_carlo_futures():
    """The plotted trace must be a future that was actually counted."""
    mc = run_monte_carlo(FAST, n_runs=N, base_seed=99)
    rep = representative_run(FAST, base_seed=99, run_index=0)
    assert rep["seed"] == mc["seeds"][0]
    assert rep["timeseries"]  # and it does carry a trace


# --------------------------------------------------------------------------
# Common random numbers
# --------------------------------------------------------------------------

def test_rollout_seed_depends_only_on_base_seed_and_index():
    assert rollout_seed(7, 3) == rollout_seed(7, 3)
    assert rollout_seed(7, 3) != rollout_seed(7, 4)
    assert rollout_seed(7, 3) != rollout_seed(8, 3)


def test_scenarios_share_rollout_seeds_with_the_baseline():
    base = run_monte_carlo(FAST, n_runs=N, base_seed=5)
    tank = run_monte_carlo(dict(FAST, tank_count=3), n_runs=N, base_seed=5)
    assert base["seeds"] == tank["seeds"]


def test_paired_comparison_is_weakly_monotone_run_by_run():
    """Under CRN, extra buffer must not make any individual future worse."""
    base = run_monte_carlo(FAST, n_runs=N, base_seed=5)
    tank = run_monte_carlo(dict(FAST, tank_count=6), n_runs=N, base_seed=5)
    for b, t in zip(base["runs"]["lost_production_t"], tank["runs"]["lost_production_t"]):
        assert t <= b + 1e-9


# --------------------------------------------------------------------------
# Comparison output
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def comparison():
    return compare_scenarios(FAST, n_runs=N, base_seed=5)


def test_comparison_shape(comparison):
    assert set(comparison) >= {
        "baseline", "scenarios", "ranking", "recommendation", "assumptions",
        "runtime_seconds",
    }
    assert len(comparison["scenarios"]) == len(DEMO_SCENARIOS)
    for block in comparison["scenarios"]:
        assert set(block) >= {"name", "label", "overrides", "config",
                              "operational", "financial", "stats"}


def test_comparison_is_json_serialisable(comparison):
    import json
    json.loads(json.dumps(comparison))


def test_baseline_compared_with_itself_shows_no_change(comparison):
    op = comparison["baseline"]["operational"]
    assert op["expected_loss_reduction_t"] == 0.0
    assert op["failure_probability_reduction_pp"] == 0.0


def test_every_scenario_reports_operational_and_financial_metrics(comparison):
    for block in comparison["scenarios"]:
        assert block["operational"]["expected_lost_production_t"] >= 0
        assert "annual_value_gbp" in block["financial"]
        assert block["financial"]["baseline_expected_loss_t"] == pytest.approx(
            comparison["baseline"]["operational"]["expected_lost_production_t"]
        )


def test_ranking_is_ordered_by_the_stated_rule(comparison):
    values = [r["annual_value_gbp"] for r in comparison["ranking"]]
    assert values == sorted(values, reverse=True)
    assert [r["rank"] for r in comparison["ranking"]] == list(range(1, len(values) + 1))
    assert comparison["assumptions"]["ranking_rule"] == RANKING_RULE


def test_ranking_rule_is_stated_in_the_output(comparison):
    assert "annual_value_gbp" in comparison["recommendation"]["rule"]
    assert comparison["recommendation"]["decision"]


def test_recommendation_flags_a_financial_resilience_disagreement():
    blocks = [
        {"name": "cheap", "label": "Cheap",
         "financial": {"annual_value_gbp": 100.0, "net_annual_benefit_gbp": 100.0,
                       "payback_years": None, "payback_status": "opex_only_positive"},
         "operational": {"expected_loss_reduction_pct": 10.0, "p95_lost_production_t": 50.0}},
        {"name": "safe", "label": "Safe",
         "financial": {"annual_value_gbp": -10.0, "net_annual_benefit_gbp": -10.0,
                       "payback_years": None, "payback_status": "not_viable"},
         "operational": {"expected_loss_reduction_pct": 99.0, "p95_lost_production_t": 1.0}},
    ]
    from app.scenario_runner import build_recommendation
    ranking = rank_scenarios(blocks)
    rec = build_recommendation(blocks, ranking)
    assert rec["best_financial"] == "cheap"
    assert rec["most_resilient"] == "safe"
    assert rec["financial_and_resilience_agree"] is False
    assert "trade-off" in rec["note"]


def test_recommendation_is_do_nothing_when_nothing_pays():
    blocks = [
        {"name": "bad", "label": "Bad",
         "financial": {"annual_value_gbp": -5000.0, "net_annual_benefit_gbp": -5000.0,
                       "payback_years": None, "payback_status": "not_viable"},
         "operational": {"expected_loss_reduction_pct": 90.0, "p95_lost_production_t": 2.0}},
    ]
    from app.scenario_runner import build_recommendation
    rec = build_recommendation(blocks, rank_scenarios(blocks))
    assert rec["decision"] == "do_nothing"


def test_assumptions_are_disclosed(comparison):
    a = comparison["assumptions"]
    assert a["n_runs"] == N
    assert a["base_seed"] == 5
    assert "lost_production_t" in a["failure_definition"]
    assert a["finance_config"]["value_per_tonne_gbp"] > 0
    assert "rollout" in a["common_random_numbers"]


def test_comparison_is_reproducible():
    a = compare_scenarios(FAST, n_runs=10, base_seed=3, include_representative_run=False)
    b = compare_scenarios(FAST, n_runs=10, base_seed=3, include_representative_run=False)
    assert a["ranking"] == b["ranking"]
    assert a["recommendation"] == b["recommendation"]


def test_scenario_monte_carlo_carries_its_definition_through():
    mc = run_scenario_monte_carlo(FAST, DEMO_SCENARIOS[0], n_runs=5)
    assert mc["name"] == DEMO_SCENARIOS[0]["name"]
    assert mc["overrides"] == DEMO_SCENARIOS[0]["overrides"]
    assert mc["economics"]["capex_gbp"] == DEMO_SCENARIOS[0]["economics"]["capex_gbp"]
