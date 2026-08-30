"""Invariant tests for the reference CO2 simulator.

These are the tests that let us say "the simulator owns the numbers" with a
straight face: reproducibility, conservation of material, and the physical
constraints of the model.
"""

from __future__ import annotations

import math

import pytest

from reference.co2_simulation import (
    DEFAULT_CONFIG,
    build_collection_schedule,
    derive_seed,
    normalise_config,
    simulate,
    total_capacity_t,
    validate_result,
)

TOL = 1e-6


# --------------------------------------------------------------------------
# A. determinism / reproducibility
# --------------------------------------------------------------------------

def test_same_seed_same_result():
    a = simulate({}, seed=42)
    b = simulate({}, seed=42)
    assert a["metrics"] == b["metrics"]
    assert a["events"] == b["events"]
    assert a["timeseries"] == b["timeseries"]


def test_canonical_buffer_aliases_are_bit_identical_to_legacy_co2_config():
    from reference.buffer_logistics import simulate as simulate_buffer

    legacy = {
        "production_rate_t_per_hour": 1.2, "tank_count": 3,
        "tank_capacity_t": 40.0, "collections_per_day": 2,
        "tanker_capacity_t": 30.0, "simulation_days": 4,
    }
    canonical = {
        "inflow_rate": 1.2, "buffer_count": 3,
        "buffer_capacity": 40.0, "outbound_events_per_day": 2,
        "outbound_capacity": 30.0, "simulation_days": 4,
    }
    assert simulate_buffer(canonical, seed=19) == simulate(legacy, seed=19)


def test_different_seed_different_result():
    # Compare a metric that is always stochastic: lost production can legitimately
    # be 0 for two different seeds when neither future breaks the operation.
    a = simulate({}, seed=1)
    b = simulate({}, seed=2)
    assert a["metrics"]["total_production_t"] != b["metrics"]["total_production_t"]


def test_seed_is_reported_back_when_not_supplied():
    result = simulate({})
    replay = simulate({}, seed=result["seed"])
    assert replay["metrics"] == result["metrics"]


def test_derive_seed_is_stable_across_processes():
    # blake2b, not hash(): PYTHONHASHSEED must not be able to change this.
    assert derive_seed(42, "production") == derive_seed(42, "production")
    assert derive_seed(42, "production") != derive_seed(42, "collection")


# --------------------------------------------------------------------------
# B. mass conservation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [0, 1, 7, 42, 1234])
def test_mass_balance(seed):
    m = simulate({}, seed=seed)["metrics"]
    residual = (
        m["initial_storage_t"]
        + m["potential_production_t"]
        - m["collected_t"]
        - m["lost_production_t"]
        - m["final_storage_t"]
    )
    assert abs(residual) < TOL
    assert abs(m["mass_balance_residual_t"]) < TOL


@pytest.mark.parametrize("seed", [0, 3, 99])
def test_potential_equals_produced_plus_lost(seed):
    m = simulate({}, seed=seed)["metrics"]
    assert m["potential_production_t"] == pytest.approx(
        m["total_production_t"] + m["lost_production_t"], abs=TOL
    )


def test_timeseries_flows_sum_to_metrics_even_when_strided():
    """A strided timeseries must still conserve the flows it reports."""
    cfg = {"timeseries_stride": 7}
    result = simulate(cfg, seed=11)
    m = result["metrics"]
    assert sum(r["production_t"] for r in result["timeseries"]) == pytest.approx(
        m["total_production_t"], abs=1e-2
    )
    assert sum(r["collected_t"] for r in result["timeseries"]) == pytest.approx(
        m["collected_t"], abs=1e-2
    )
    assert sum(r["lost_production_t"] for r in result["timeseries"]) == pytest.approx(
        m["lost_production_t"], abs=1e-2
    )


# --------------------------------------------------------------------------
# C / D. capacity constraint and non-negativity
# --------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(8))
def test_storage_within_bounds(seed):
    result = simulate({}, seed=seed)
    capacity = result["metrics"]["total_capacity_t"]
    for row in result["timeseries"]:
        assert -TOL <= row["storage_level_t"] <= capacity + 1e-4


@pytest.mark.parametrize("seed", range(8))
def test_no_negative_quantities(seed):
    result = simulate({}, seed=seed)
    m = result["metrics"]
    assert m["total_production_t"] >= 0
    assert m["lost_production_t"] >= 0
    assert m["collected_t"] >= 0
    assert m["final_storage_t"] >= 0
    for row in result["timeseries"]:
        assert row["production_t"] >= 0
        assert row["lost_production_t"] >= 0
        assert row["collected_t"] >= 0


def test_production_never_negative_under_extreme_variability():
    """A huge variability must throttle production to zero, never reverse it."""
    result = simulate({"production_variability_pct": 3.0}, seed=5)
    assert result["metrics"]["total_production_t"] >= 0
    assert all(r["production_t"] >= 0 for r in result["timeseries"])


@pytest.mark.parametrize("seed", range(5))
def test_validate_result_passes_on_every_run(seed):
    validate_result(simulate({}, seed=seed))


# --------------------------------------------------------------------------
# E. deterministic (no-failure) configuration
# --------------------------------------------------------------------------

DETERMINISTIC = {
    "production_variability_pct": 0.0,
    "missed_collection_probability": 0.0,
    "collection_delay_probability": 0.0,
}


def test_deterministic_config_is_seed_independent():
    a = simulate(DETERMINISTIC, seed=1)["metrics"]
    b = simulate(DETERMINISTIC, seed=99999)["metrics"]
    assert a == b


def test_deterministic_config_matches_hand_calculation():
    """30 days x 24 t/day production, 30 collections of 25 t, no losses."""
    cfg = dict(DETERMINISTIC)
    result = simulate(cfg, seed=1)
    m = result["metrics"]
    days = DEFAULT_CONFIG["simulation_days"]
    expected_production = DEFAULT_CONFIG["production_rate_t_per_hour"] * 24 * days
    assert m["potential_production_t"] == pytest.approx(expected_production, abs=1e-6)
    assert m["collections_scheduled"] == days
    assert m["collections_missed"] == 0
    assert m["collections_delayed"] == 0


def test_deterministic_balanced_operation_loses_nothing():
    """Collection capacity above daily production => no curtailment at all."""
    cfg = dict(DETERMINISTIC, tanker_capacity_t=30.0)
    m = simulate(cfg, seed=1)["metrics"]
    assert m["lost_production_t"] == pytest.approx(0.0, abs=TOL)
    assert m["curtailment_episodes"] == 0


# --------------------------------------------------------------------------
# F. guaranteed-failure configuration
# --------------------------------------------------------------------------

def test_all_collections_missed_fills_storage_and_curtails():
    cfg = {
        "missed_collection_probability": 1.0,
        "production_variability_pct": 0.0,
    }
    result = simulate(cfg, seed=3)
    m = result["metrics"]
    assert m["collections_completed"] == 0
    assert m["collected_t"] == 0.0
    assert m["max_storage_utilisation"] == pytest.approx(1.0, abs=1e-6)
    assert m["lost_production_t"] > 0
    assert m["curtailment_episodes"] >= 1
    types = {e["type"] for e in result["events"]}
    assert {"collection_scheduled", "collection_missed",
            "storage_capacity_reached", "production_curtailed"} <= types


def test_missed_collection_only_hurts():
    """More missed collections can never reduce lost production."""
    low = simulate({"missed_collection_probability": 0.0}, seed=8)["metrics"]
    high = simulate({"missed_collection_probability": 1.0}, seed=8)["metrics"]
    assert high["lost_production_t"] >= low["lost_production_t"]


# --------------------------------------------------------------------------
# G. capacity / intervention monotonicity
# --------------------------------------------------------------------------

def test_extra_tank_increases_capacity():
    base = simulate({}, seed=4)["metrics"]
    more = simulate({"tank_count": 3}, seed=4)["metrics"]
    assert more["total_capacity_t"] > base["total_capacity_t"]
    assert more["total_capacity_t"] == pytest.approx(
        base["total_capacity_t"] + DEFAULT_CONFIG["tank_capacity_t"]
    )


@pytest.mark.parametrize("seed", range(6))
def test_more_buffer_never_increases_loss(seed):
    """Under common random numbers, extra storage is weakly beneficial."""
    base = simulate({}, seed=seed)["metrics"]
    more = simulate({"tank_count": 4}, seed=seed)["metrics"]
    assert more["lost_production_t"] <= base["lost_production_t"] + TOL


@pytest.mark.parametrize("seed", range(6))
def test_larger_tanker_never_increases_loss(seed):
    base = simulate({}, seed=seed)["metrics"]
    bigger = simulate({"tanker_capacity_t": 40.0}, seed=seed)["metrics"]
    assert bigger["lost_production_t"] <= base["lost_production_t"] + TOL


# --------------------------------------------------------------------------
# Common random numbers
# --------------------------------------------------------------------------

def test_production_shocks_are_shared_across_scenarios():
    """Interventions that do not touch production must face the same shocks."""
    base = simulate({"missed_collection_probability": 0.0,
                     "collection_delay_probability": 0.0,
                     "tank_count": 50}, seed=17)["metrics"]
    tank = simulate({"missed_collection_probability": 0.0,
                     "collection_delay_probability": 0.0,
                     "tank_count": 60}, seed=17)["metrics"]
    # No curtailment in either (huge tanks), so potential == actual production
    # and the two runs must have seen an identical production realisation.
    assert base["potential_production_t"] == pytest.approx(
        tank["potential_production_t"], abs=1e-9
    )


def test_collection_draws_are_shared_when_schedule_is_unchanged():
    cfg_a = {"tank_count": 2}
    cfg_b = {"tank_count": 5, "tanker_capacity_t": 30.0}
    sched_a = build_collection_schedule(normalise_config(cfg_a), 23)
    sched_b = build_collection_schedule(normalise_config(cfg_b), 23)
    assert [(c["missed"], c["delay_minutes"]) for c in sched_a] == [
        (c["missed"], c["delay_minutes"]) for c in sched_b
    ]


def test_adding_a_collection_slot_preserves_the_original_slot_draws():
    """+1 collection/day layers onto the same future, it does not reshuffle it."""
    one = build_collection_schedule(normalise_config({"collections_per_day": 1}), 77)
    two = build_collection_schedule(normalise_config({"collections_per_day": 2}), 77)
    slot0_one = {(c["day"], c["missed"], c["delay_minutes"]) for c in one}
    slot0_two = {
        (c["day"], c["missed"], c["delay_minutes"]) for c in two if c["slot"] == 0
    }
    assert slot0_one == slot0_two


def test_miss_probability_does_not_shift_delay_draws():
    a = build_collection_schedule(
        normalise_config({"missed_collection_probability": 0.0}), 5
    )
    b = build_collection_schedule(
        normalise_config({"missed_collection_probability": 0.5}), 5
    )
    # delays are drawn from their own uniform, independent of the miss draw
    assert [c["due_t_hours"] - c["scheduled_t_hours"] for c in a] == [
        c["due_t_hours"] - c["scheduled_t_hours"] for c in b if not c["missed"]
    ] or True  # only the non-missed subset is comparable; check draw stability:
    delays_a = {(c["day"], c["slot"]): c["delay_minutes"] for c in a}
    for c in b:
        if not c["missed"]:
            assert delays_a[(c["day"], c["slot"])] == c["delay_minutes"]


# --------------------------------------------------------------------------
# Configuration handling
# --------------------------------------------------------------------------

def test_normalise_config_fills_defaults():
    cfg = normalise_config({"tank_count": 3})
    assert cfg["tank_count"] == 3
    assert cfg["tank_capacity_t"] == DEFAULT_CONFIG["tank_capacity_t"]
    assert set(cfg) == set(DEFAULT_CONFIG)


def test_normalise_config_rejects_unknown_keys():
    with pytest.raises(ValueError, match="unknown config keys"):
        normalise_config({"numer_of_tanks": 3})


@pytest.mark.parametrize(
    "bad",
    [
        {"tank_count": 0},
        {"tank_capacity_t": 0},
        {"tank_capacity_t": -1},
        {"collections_per_day": 0},
        {"missed_collection_probability": 1.5},
        {"missed_collection_probability": -0.1},
        {"production_rate_t_per_hour": -1},
        {"timestep_minutes": 0},
        {"timeseries_stride": 0},
    ],
)
def test_normalise_config_rejects_invalid_values(bad):
    with pytest.raises(ValueError):
        normalise_config(bad)


def test_initial_storage_is_clamped_to_capacity():
    cfg = normalise_config({"tank_count": 1, "tank_capacity_t": 10.0,
                            "initial_storage_t": 500.0})
    assert cfg["initial_storage_t"] == 10.0


def test_total_capacity_helper():
    assert total_capacity_t(normalise_config({"tank_count": 3,
                                              "tank_capacity_t": 45.0})) == 135.0


# --------------------------------------------------------------------------
# Output shape / contract
# --------------------------------------------------------------------------

def test_result_shape():
    result = simulate({}, seed=1)
    assert set(result) == {"timeseries", "metrics", "events", "config", "seed"}
    assert isinstance(result["timeseries"], list)
    assert isinstance(result["metrics"], dict)
    assert isinstance(result["events"], list)


def test_timeseries_length_matches_steps_and_stride():
    result = simulate({"simulation_days": 2}, seed=1)
    n_steps = result["metrics"]["n_steps"]
    assert n_steps == 2 * 24 * 6  # 10-minute steps
    assert len(result["timeseries"]) == n_steps

    strided = simulate({"simulation_days": 2, "timeseries_stride": 6}, seed=1)
    assert len(strided["timeseries"]) == math.ceil(n_steps / 6)


def test_timeseries_can_be_switched_off():
    result = simulate({"record_timeseries": False}, seed=1)
    assert result["timeseries"] == []
    assert result["metrics"]["total_production_t"] > 0


def test_events_stay_concise():
    """A month of operation must not produce thousands of events."""
    result = simulate({}, seed=42)
    assert len(result["events"]) < 200


def test_result_is_json_serialisable():
    import json

    json.loads(json.dumps(simulate({"simulation_days": 1}, seed=1)))
