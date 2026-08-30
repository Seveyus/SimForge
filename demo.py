#!/usr/bin/env python3
"""SimForge demo: baseline vs interventions, executed and compared.

    python demo.py                      # local execution
    python demo.py --execution daytona  # each scenario in its own forked sandbox
    python demo.py --json out.json      # dump the full decision payload

Every number printed here is computed by the simulator and the finance module.
Nothing on this screen was written by a language model.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.env import load_env
from app.monte_carlo import DEFAULT_BASE_SEED, DEFAULT_N_RUNS
from app.pipeline import daytona_available, run_decision_pipeline

RULE = "=" * 78


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"£{value:,.0f}"


def print_operational(comparison: dict) -> None:
    base = comparison["baseline"]
    cfg = base["config"]
    print(RULE)
    print("BASELINE")
    print(RULE)
    print(
        f"  {cfg['tank_count']} x {cfg['tank_capacity_t']:.0f} t tanks "
        f"({cfg['tank_count'] * cfg['tank_capacity_t']:.0f} t total)   "
        f"{cfg['production_rate_t_per_hour']:.2f} t/h production   "
        f"{cfg['collections_per_day']} x {cfg['tanker_capacity_t']:.0f} t collection/day"
    )
    print(
        f"  {comparison['assumptions']['n_runs']} stochastic futures, "
        f"{cfg['simulation_days']:.0f} days each, base seed "
        f"{comparison['assumptions']['base_seed']}"
    )
    op = base["operational"]
    print()
    print(f"  Expected lost production   {op['expected_lost_production_t']:8.1f} t")
    print(f"  P95 lost production        {op['p95_lost_production_t']:8.1f} t")
    print(f"  Failure probability        {op['failure_probability'] * 100:8.1f} %")
    print(f"  Expected output            {op['expected_production_t']:8.1f} t")
    print(f"  Peak storage utilisation   {op['max_storage_utilisation'] * 100:8.1f} %")

    for block in comparison["scenarios"]:
        op = block["operational"]
        print()
        print(RULE)
        print(block["label"].upper())
        print(RULE)
        print(f"  overrides: {json.dumps(block['overrides'])}")
        print()
        drop = op["expected_loss_reduction_pct"]
        print(
            f"  Expected lost production   {op['expected_lost_production_t']:8.1f} t"
            + (f"   ({drop:+.0f}% vs baseline)" if drop is not None else "")
        )
        print(f"  P95 lost production        {op['p95_lost_production_t']:8.1f} t")
        print(
            f"  Failure probability        {op['failure_probability'] * 100:8.1f} %"
            f"   ({-op['failure_probability_reduction_pp']:+.1f} pp)"
        )
        print(f"  Tanker trips / period      {op['mean_collections_completed']:8.1f}")


def print_financial(comparison: dict) -> None:
    print()
    print(RULE)
    print("FINANCIAL COMPARISON")
    print(RULE)
    for block in comparison["scenarios"]:
        f = block["financial"]
        print()
        print(f"  {block['label']}")
        print(f"    CAPEX                    {money(f['capex_gbp']):>14}"
              f"   (amortised {money(f['annualised_capex_gbp'])}/y over "
              f"{f['capex_amortisation_years']:.0f}y)")
        print(f"    Annual OPEX delta        {money(f['annual_opex_delta_gbp']):>14}"
              f"   (of which logistics {money(f['annual_collection_cost_delta_gbp'])})")
        print(f"    Recovered output         {f['recovered_output_t_per_year']:>11.1f} t/y")
        print(f"    Annualised benefit       {money(f['annualised_benefit_gbp']):>14}")
        print(f"    Net annual benefit       {money(f['net_annual_benefit_gbp']):>14}")
        print(f"    ANNUAL VALUE             {money(f['annual_value_gbp']):>14}")
        payback = (
            f"{f['payback_years']:.1f} years" if f["payback_years"] is not None
            else f"none ({f['payback_status']})"
        )
        print(f"    Payback                  {payback:>14}")


def print_decision(comparison: dict) -> None:
    print()
    print(RULE)
    print("RANKING")
    print(RULE)
    for row in comparison["ranking"]:
        print(
            f"  {row['rank']}. {row['label']:<46} {money(row['annual_value_gbp']):>12}/y"
            f"   (resilience rank {row['resilience_rank']})"
        )
    print()
    print(f"  rule: {comparison['assumptions']['ranking_rule']}")

    rec = comparison["recommendation"]
    print()
    print(RULE)
    print("RECOMMENDATION")
    print(RULE)
    print(f"  {rec['label']}")
    print(f"  Annual value    {money(rec['annual_value_gbp'])}/y")
    if rec["payback_years"] is not None:
        print(f"  Payback         {rec['payback_years']:.1f} years")
    print(f"  {rec['note']}")


def print_execution(comparison: dict) -> None:
    execution = comparison.get("execution", {})
    print()
    print(RULE)
    print("EXECUTION")
    print(RULE)
    print(f"  mode              {execution.get('mode')}")
    if execution.get("mode") == "daytona":
        print(f"  isolation         {execution.get('isolation_mode')}")
        print(f"  baseline sandbox  {execution.get('baseline_sandbox_id')}")
        env = execution.get("sandbox_environment") or {}
        if env:
            print(f"  sandbox python    {env.get('python')} on {env.get('machine')}")
        for key, value in (execution.get("timings") or {}).items():
            print(f"  {key:<17} {value:.2f}s")
        for block in comparison["scenarios"]:
            if block.get("sandbox_id"):
                print(f"  {block['name']:<17} {block['sandbox_id']}")
    print(f"  total wall clock  {comparison['runtime_seconds']:.2f}s")
    print()
    print(f"  {comparison['assumptions']['common_random_numbers']}")
    print(f"  failure = {comparison['assumptions']['failure_definition']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--execution", choices=["auto", "local", "daytona"], default="local")
    parser.add_argument("--runs", type=int, default=DEFAULT_N_RUNS,
                        help=f"stochastic futures per scenario (default {DEFAULT_N_RUNS})")
    parser.add_argument("--seed", type=int, default=DEFAULT_BASE_SEED)
    parser.add_argument("--json", metavar="PATH", help="write the full decision payload")
    parser.add_argument("--quiet", action="store_true", help="only print the recommendation")
    args = parser.parse_args(argv)
    load_env()

    if args.execution == "daytona" and not daytona_available():
        print("DAYTONA_API_KEY is not set - export it or use --execution local",
              file=sys.stderr)
        return 2

    comparison = run_decision_pipeline(
        n_runs=args.runs,
        base_seed=args.seed,
        execution=args.execution,
        include_representative_run=bool(args.json),
        on_log=None if args.quiet else lambda msg: print(f"  {msg}", file=sys.stderr),
    )

    if not args.quiet:
        print_operational(comparison)
        print_financial(comparison)
    print_decision(comparison)
    if not args.quiet:
        print_execution(comparison)

    if args.json:
        with open(args.json, "w") as handle:
            json.dump(comparison, handle, indent=2)
        print(f"\n  full payload -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
