"""Tests for the deterministic financial decision layer.

The point of these: every edge case that could produce a nonsense number on
screen (negative payback, division by zero, CAPEX and OPEX conflated) has a
defined, explicit answer.
"""

from __future__ import annotations

import pytest

from app import finance
from app.finance import (
    STATUS_NOT_VIABLE,
    STATUS_OPEX_ONLY_POSITIVE,
    STATUS_PAYS_BACK,
    evaluate_scenario,
)


def summary(loss_t: float, trips: float = 30.0, days: float = 30.0) -> dict[str, float]:
    return {
        "mean_lost_production_t": loss_t,
        "mean_collections_completed": trips,
        "simulation_days": days,
    }


NO_COST = {"capex_gbp": 0.0, "annual_opex_delta_gbp": 0.0, "cost_per_collection_gbp": 400.0}


# --------------------------------------------------------------------------
# Benefit arithmetic
# --------------------------------------------------------------------------

def test_positive_benefit_with_capex_pays_back():
    r = evaluate_scenario(
        summary(100.0), summary(0.0),
        economics={"capex_gbp": 100_000.0, "annual_opex_delta_gbp": 0.0,
                   "cost_per_collection_gbp": 400.0},
        baseline_economics=NO_COST,
    )
    # 100 t recovered over 30 days at £150/t = £15,000 -> x 365/30 = £182,500/y
    assert r["recovered_output_t"] == 100.0
    assert r["period_benefit_gbp"] == pytest.approx(15_000.0)
    assert r["annualised_benefit_gbp"] == pytest.approx(15_000.0 * 365 / 30)
    assert r["net_annual_benefit_gbp"] == pytest.approx(r["annualised_benefit_gbp"])
    assert r["payback_status"] == STATUS_PAYS_BACK
    assert r["payback_years"] == pytest.approx(100_000.0 / r["net_annual_benefit_gbp"])
    assert 0 < r["payback_years"] < 1


def test_zero_benefit_is_not_viable_and_reports_no_payback():
    r = evaluate_scenario(
        summary(50.0), summary(50.0),
        economics={"capex_gbp": 80_000.0, **{k: v for k, v in NO_COST.items() if k != "capex_gbp"}},
        baseline_economics=NO_COST,
    )
    assert r["recovered_output_t"] == 0.0
    assert r["net_annual_benefit_gbp"] == pytest.approx(0.0)
    assert r["payback_years"] is None
    assert r["payback_status"] == STATUS_NOT_VIABLE


def test_negative_benefit_never_produces_a_negative_payback():
    """A worse scenario must not report 'payback in -4.2 years'."""
    r = evaluate_scenario(
        summary(10.0), summary(60.0),
        economics={"capex_gbp": 80_000.0, "annual_opex_delta_gbp": 0.0,
                   "cost_per_collection_gbp": 400.0},
        baseline_economics=NO_COST,
    )
    assert r["recovered_output_t"] < 0
    assert r["net_annual_benefit_gbp"] < 0
    assert r["payback_years"] is None
    assert r["payback_status"] == STATUS_NOT_VIABLE


# --------------------------------------------------------------------------
# CAPEX vs OPEX
# --------------------------------------------------------------------------

def test_zero_capex_positive_benefit_has_no_payback_but_is_viable():
    """A pure-OPEX win pays back immediately; 'payback years' is meaningless."""
    r = evaluate_scenario(
        summary(100.0), summary(0.0), economics=NO_COST, baseline_economics=NO_COST,
    )
    assert r["capex_gbp"] == 0.0
    assert r["net_annual_benefit_gbp"] > 0
    assert r["payback_years"] is None
    assert r["payback_status"] == STATUS_OPEX_ONLY_POSITIVE
    assert r["roi_first_year"] is None  # ROI on zero capex is undefined
    # with no capex, annual value equals net annual benefit
    assert r["annual_value_gbp"] == pytest.approx(r["net_annual_benefit_gbp"])


def test_capex_is_amortised_into_annual_value():
    r = evaluate_scenario(
        summary(100.0), summary(0.0),
        economics={"capex_gbp": 100_000.0, "annual_opex_delta_gbp": 0.0,
                   "cost_per_collection_gbp": 400.0},
        baseline_economics=NO_COST,
        finance_config={"capex_amortisation_years": 10.0},
    )
    assert r["annualised_capex_gbp"] == pytest.approx(10_000.0)
    assert r["annual_value_gbp"] == pytest.approx(
        r["net_annual_benefit_gbp"] - 10_000.0
    )
    # net annual benefit deliberately excludes capex; annual value includes it
    assert r["net_annual_benefit_gbp"] > r["annual_value_gbp"]


def test_recurring_opex_reduces_net_benefit_but_not_capex():
    r = evaluate_scenario(
        summary(100.0), summary(0.0),
        economics={"capex_gbp": 0.0, "annual_opex_delta_gbp": 50_000.0,
                   "cost_per_collection_gbp": 400.0},
        baseline_economics=NO_COST,
    )
    assert r["capex_gbp"] == 0.0
    assert r["fixed_annual_opex_delta_gbp"] == 50_000.0
    assert r["net_annual_benefit_gbp"] == pytest.approx(
        r["annualised_benefit_gbp"] - 50_000.0
    )


def test_recurring_opex_can_outweigh_a_perfect_operational_fix():
    """Eliminating 100% of the loss is still the wrong call if it costs more."""
    r = evaluate_scenario(
        summary(10.0), summary(0.0),
        economics={"capex_gbp": 0.0, "annual_opex_delta_gbp": 200_000.0,
                   "cost_per_collection_gbp": 400.0},
        baseline_economics=NO_COST,
    )
    assert r["scenario_expected_loss_t"] == 0.0      # operationally perfect
    assert r["net_annual_benefit_gbp"] < 0           # financially wrong
    assert r["payback_status"] == STATUS_NOT_VIABLE


# --------------------------------------------------------------------------
# Collection cost derived from the simulation
# --------------------------------------------------------------------------

def test_collection_cost_delta_comes_from_simulated_trip_counts():
    r = evaluate_scenario(
        summary(10.0, trips=30.0), summary(0.0, trips=45.0),
        economics=NO_COST, baseline_economics=NO_COST,
    )
    # 15 extra trips a month at £400 = £6,000 -> annualised
    assert r["annual_collection_cost_delta_gbp"] == pytest.approx(
        15 * 400.0 * 365 / 30
    )
    assert r["baseline_collections_per_period"] == 30.0
    assert r["scenario_collections_per_period"] == 45.0


def test_dearer_tanker_costs_more_at_the_same_trip_count():
    r = evaluate_scenario(
        summary(10.0, trips=30.0), summary(0.0, trips=30.0),
        economics={"capex_gbp": 0.0, "annual_opex_delta_gbp": 0.0,
                   "cost_per_collection_gbp": 520.0},
        baseline_economics=NO_COST,
    )
    assert r["annual_collection_cost_delta_gbp"] == pytest.approx(
        30 * (520.0 - 400.0) * 365 / 30
    )


def test_identical_logistics_cost_nothing_extra():
    r = evaluate_scenario(
        summary(10.0, trips=27.6), summary(2.0, trips=27.6),
        economics=NO_COST, baseline_economics=NO_COST,
    )
    assert r["annual_collection_cost_delta_gbp"] == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------

def test_mismatched_periods_are_rejected():
    with pytest.raises(ValueError, match="same period"):
        evaluate_scenario(summary(10.0, days=30.0), summary(5.0, days=60.0))


def test_zero_simulation_days_is_rejected():
    with pytest.raises(ValueError, match="simulation_days"):
        evaluate_scenario(summary(10.0, days=0.0), summary(5.0, days=0.0))


def test_zero_amortisation_period_is_rejected():
    with pytest.raises(ValueError, match="capex_amortisation_years"):
        evaluate_scenario(
            summary(10.0), summary(0.0),
            economics={"capex_gbp": 1000.0, "annual_opex_delta_gbp": 0.0,
                       "cost_per_collection_gbp": 400.0},
            finance_config={"capex_amortisation_years": 0.0},
        )


def test_negative_capex_is_rejected():
    with pytest.raises(ValueError, match="capex_gbp"):
        evaluate_scenario(summary(10.0), summary(0.0), economics={"capex_gbp": -1.0})


def test_benefit_cost_ratio_is_none_when_the_change_is_free():
    r = evaluate_scenario(
        summary(10.0, trips=30.0), summary(0.0, trips=30.0),
        economics=NO_COST, baseline_economics=NO_COST,
    )
    assert r["benefit_cost_ratio"] is None  # no cost at all -> ratio undefined


def test_annualisation_factor_is_reported():
    r = evaluate_scenario(summary(10.0, days=30.0), summary(0.0, days=30.0))
    assert r["annualisation_factor"] == pytest.approx(365 / 30)


def test_value_per_tonne_is_configurable():
    a = evaluate_scenario(summary(10.0), summary(0.0),
                          finance_config={"value_per_tonne_gbp": 100.0})
    b = evaluate_scenario(summary(10.0), summary(0.0),
                          finance_config={"value_per_tonne_gbp": 200.0})
    assert b["annualised_benefit_gbp"] == pytest.approx(2 * a["annualised_benefit_gbp"])


def test_finance_is_deterministic():
    args = (summary(12.2), summary(1.5))
    kwargs = {"economics": {"capex_gbp": 80_000.0, "annual_opex_delta_gbp": 1500.0,
                            "cost_per_collection_gbp": 400.0}}
    assert evaluate_scenario(*args, **kwargs) == evaluate_scenario(*args, **kwargs)


def test_summarise_for_finance_pulls_the_right_fields():
    mc = {
        "stats": {
            "lost_production_t": {"mean": 12.0, "p95": 50.0},
            "collections_completed": {"mean": 27.6},
        },
        "config": {"simulation_days": 30},
    }
    out = finance.summarise_for_finance(mc)
    assert out == {
        "mean_lost_production_t": 12.0,
        "p95_lost_production_t": 50.0,
        "mean_collections_completed": 27.6,
        "simulation_days": 30.0,
    }
