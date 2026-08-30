"""Known-good CO2 production / storage / tanker-collection simulator.

This is the *reference* simulator for SimForge: a hand-written, deterministic,
dependency-free (stdlib only) discrete-time model of the demo operation.

    continuous CO2 production  ->  storage tanks  ->  tanker collections

It is intentionally standalone so that the exact same file can be executed
locally, inside a Daytona sandbox, or embedded in a generated simulator, with
no imports beyond the Python standard library.

--------------------------------------------------------------------------
CONTRACT
--------------------------------------------------------------------------

    simulate(config: dict, seed: int | None = None) -> dict

returning::

    {
        "timeseries": [ {...}, ... ],
        "metrics":    { ... },
        "events":     [ {...}, ... ],
        "config":     { ... },   # the fully normalised config actually used
        "seed":       int,
    }

`simulate` is deterministic: the same (config, seed) always yields the same
result, in this process, in another process, and inside a Daytona sandbox.

--------------------------------------------------------------------------
MODELLING ASSUMPTIONS  (explicit on purpose - see README "Data Provenance")
--------------------------------------------------------------------------

1. Storage is modelled in aggregate (total tonnes across all tanks) rather than
   tank-by-tank. For this operation the decision signal ("do we run out of
   buffer?") depends on *total* headroom, so per-tank tracking would add state
   without changing any KPI. `tank_count * tank_capacity_t` is the constraint.

2. Within one timestep the order of operations is:
       (a) any tanker collection due in this step removes material,
       (b) then production is added to whatever headroom remains.
   Rationale: a tanker arriving during the step frees capacity before the
   step's production has to fit. Doing it the other way round would invent
   curtailment that a real operator would not experience.

3. Production that cannot fit in the remaining headroom is *curtailed*: it is
   never produced, and is booked as `lost_production_t`. Material is never
   silently destroyed - see `validate_result` mass balance.

4. Randomness is drawn from independent, named, seed-derived streams so that
   scenarios can be compared under *the same* stochastic future (common random
   numbers). See `build_collection_schedule`.

None of these numbers are claims about a specific real plant. They are demo
assumptions supplied through the config.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from typing import Any

# Tonnage below which we treat a quantity as zero (float noise guard).
EPS_T = 1e-9

#: Baseline demo configuration. These are *example demo assumptions*, not
#: validated plant data. Every value can be overridden by the caller.
DEFAULT_CONFIG: dict[str, Any] = {
    # --- time -----------------------------------------------------------
    "simulation_days": 30,
    "timestep_minutes": 10,
    # --- production -----------------------------------------------------
    "production_rate_t_per_hour": 1.0,
    "production_variability_pct": 0.05,   # std-dev as a fraction of the rate
    # --- storage --------------------------------------------------------
    "tank_count": 2,
    "tank_capacity_t": 45.0,
    "initial_storage_t": 20.0,           # absolute, see note below
    # --- collections ----------------------------------------------------
    "collections_per_day": 1,
    "tanker_capacity_t": 25.0,
    "first_collection_hour": 8.0,        # hour-of-day of the first slot
    "missed_collection_probability": 0.08,
    "collection_delay_probability": 0.35,
    "collection_delay_minutes": 240.0,   # max delay, uniform on [0, this]
    # --- output shaping (does not affect the physics) --------------------
    "record_timeseries": True,
    "timeseries_stride": 1,              # keep 1 row every N steps
}

# `initial_storage_t` is deliberately an *absolute* tonnage rather than a
# fraction of capacity: a counterfactual that adds a tank must start from the
# same physical inventory as the baseline, otherwise the comparison is unfair.

_POSITIVE_KEYS = (
    "simulation_days",
    "timestep_minutes",
    "tank_capacity_t",
    "tanker_capacity_t",
)
_NON_NEGATIVE_KEYS = (
    "production_rate_t_per_hour",
    "production_variability_pct",
    "initial_storage_t",
    "first_collection_hour",
    "collection_delay_minutes",
)
_PROBABILITY_KEYS = (
    "missed_collection_probability",
    "collection_delay_probability",
)


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def derive_seed(*parts: Any) -> int:
    """Derive a stable child seed from arbitrary parts.

    Uses blake2b rather than :func:`hash` because Python randomises string
    hashing per process; a simulation run inside a Daytona sandbox must
    reproduce the local result exactly.
    """
    payload = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def normalise_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Merge `config` over :data:`DEFAULT_CONFIG` and validate it.

    Raises:
        ValueError: if a parameter is missing, of the wrong type, or outside
            its physically meaningful range.
    """
    cfg = dict(DEFAULT_CONFIG)
    if config:
        unknown = set(config) - set(DEFAULT_CONFIG)
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        cfg.update(config)

    cfg["tank_count"] = int(cfg["tank_count"])
    cfg["collections_per_day"] = int(cfg["collections_per_day"])
    cfg["timeseries_stride"] = int(cfg["timeseries_stride"])
    cfg["record_timeseries"] = bool(cfg["record_timeseries"])
    for key in _POSITIVE_KEYS + _NON_NEGATIVE_KEYS + _PROBABILITY_KEYS:
        cfg[key] = float(cfg[key])

    for key in _POSITIVE_KEYS:
        if not cfg[key] > 0:
            raise ValueError(f"{key} must be > 0, got {cfg[key]}")
    for key in _NON_NEGATIVE_KEYS:
        if cfg[key] < 0:
            raise ValueError(f"{key} must be >= 0, got {cfg[key]}")
    for key in _PROBABILITY_KEYS:
        if not 0.0 <= cfg[key] <= 1.0:
            raise ValueError(f"{key} must be in [0, 1], got {cfg[key]}")
    if cfg["tank_count"] < 1:
        raise ValueError(f"tank_count must be >= 1, got {cfg['tank_count']}")
    if cfg["collections_per_day"] < 1:
        raise ValueError(
            f"collections_per_day must be >= 1, got {cfg['collections_per_day']}"
        )
    if cfg["timeseries_stride"] < 1:
        raise ValueError("timeseries_stride must be >= 1")

    total_capacity = cfg["tank_count"] * cfg["tank_capacity_t"]
    if cfg["initial_storage_t"] > total_capacity:
        # Clamp rather than fail: a scenario may shrink capacity below the
        # baseline's starting inventory.
        cfg["initial_storage_t"] = total_capacity
    return cfg


def total_capacity_t(cfg: dict[str, Any]) -> float:
    """Total usable storage capacity in tonnes."""
    return cfg["tank_count"] * cfg["tank_capacity_t"]


# ---------------------------------------------------------------------------
# Collection schedule (the stochastic part of the logistics)
# ---------------------------------------------------------------------------

def build_collection_schedule(cfg: dict[str, Any], seed: int) -> list[dict[str, Any]]:
    """Pre-draw the whole tanker collection schedule for one run.

    Collections are nominally scheduled at evenly spaced slots each day,
    starting at ``first_collection_hour``. Each *scheduled* collection draws
    three uniforms deciding whether it is missed, whether it is delayed, and by
    how much.

    Common random numbers
    ---------------------
    Each collection gets its **own** RNG, seeded from
    ``(seed, "collection", day_index, slot_index)`` rather than from a single
    sequential stream. Consequences, all of which we want:

    * Baseline vs "+1 tank" vs "larger tanker": the schedule is unchanged, so
      *every* collection sees an identical miss/delay draw. The two worlds
      differ only by the intervention.
    * Baseline vs "+1 collection/day": day *d* slot 0 keeps exactly the draws
      it had in the baseline; the newly added slot 1 gets fresh randomness.
      The extra trip is layered onto the same future, it does not reshuffle it.
    * All three uniforms are drawn unconditionally, so changing
      ``missed_collection_probability`` cannot shift the delay draws.
    """
    horizon_h = cfg["simulation_days"] * 24.0
    per_day = cfg["collections_per_day"]
    spacing_h = 24.0 / per_day
    p_miss = cfg["missed_collection_probability"]
    p_delay = cfg["collection_delay_probability"]
    max_delay_min = cfg["collection_delay_minutes"]

    schedule: list[dict[str, Any]] = []
    for day in range(int(math.ceil(cfg["simulation_days"])) + 1):
        for slot in range(per_day):
            scheduled_t = day * 24.0 + cfg["first_collection_hour"] + slot * spacing_h
            if scheduled_t >= horizon_h:
                continue
            rng = random.Random(derive_seed(seed, "collection", day, slot))
            u_miss, u_delay, u_amount = rng.random(), rng.random(), rng.random()
            delay_min = u_amount * max_delay_min if u_delay < p_delay else 0.0
            missed = u_miss < p_miss
            schedule.append(
                {
                    "day": day,
                    "slot": slot,
                    "scheduled_t_hours": scheduled_t,
                    "due_t_hours": scheduled_t + delay_min / 60.0,
                    "missed": missed,
                    "delay_minutes": 0.0 if missed else delay_min,
                }
            )
    schedule.sort(key=lambda c: (c["due_t_hours"], c["day"], c["slot"]))
    return schedule


# ---------------------------------------------------------------------------
# The simulation
# ---------------------------------------------------------------------------

def simulate(config: dict[str, Any] | None = None, seed: int | None = None) -> dict[str, Any]:
    """Run one CO2 production / storage / collection simulation.

    Args:
        config: partial config; missing keys fall back to :data:`DEFAULT_CONFIG`.
        seed: stochastic seed. ``None`` picks a random one (and reports it back
            in the result so the run can be replayed).

    Returns:
        ``{"timeseries": [...], "metrics": {...}, "events": [...],
           "config": {...}, "seed": int}``
    """
    cfg = normalise_config(config)
    if seed is None:
        seed = random.SystemRandom().randrange(2**32)
    seed = int(seed)

    dt_h = cfg["timestep_minutes"] / 60.0
    n_steps = int(round(cfg["simulation_days"] * 24.0 / dt_h))
    capacity = total_capacity_t(cfg)
    rate = cfg["production_rate_t_per_hour"]
    variability = cfg["production_variability_pct"]
    tanker_capacity = cfg["tanker_capacity_t"]
    stride = cfg["timeseries_stride"]
    record = cfg["record_timeseries"]

    level = cfg["initial_storage_t"]
    initial_storage = level

    # Independent stream: identical across every scenario sharing (seed, horizon),
    # so all counterfactuals face the same production shocks.
    prod_rng = random.Random(derive_seed(seed, "production"))
    schedule = build_collection_schedule(cfg, seed)

    timeseries: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    potential_production = 0.0
    accepted_production = 0.0
    lost_production = 0.0
    collected = 0.0
    level_sum = 0.0
    max_level = level
    n_completed = 0
    n_missed = 0
    n_delayed = 0
    curtailment_hours = 0.0

    curtailing = False
    episode_start_t = 0.0
    episode_lost = 0.0

    # Accumulators for one timeseries row. With timeseries_stride > 1 a row
    # covers several steps, so flows (production / loss / collections) are
    # *summed* over the window while levels are sampled at the window's end.
    win_production = 0.0
    win_lost = 0.0
    win_collected = 0.0

    next_collection = 0
    n_scheduled = len(schedule)

    for step in range(n_steps):
        t0 = step * dt_h
        t1 = t0 + dt_h

        step_collected = 0.0

        # (a) collections due within this step
        while next_collection < n_scheduled and schedule[next_collection]["due_t_hours"] < t1:
            col = schedule[next_collection]
            next_collection += 1
            events.append(
                {
                    "t_hours": round(col["scheduled_t_hours"], 4),
                    "type": "collection_scheduled",
                    "day": col["day"],
                    "slot": col["slot"],
                }
            )
            if col["missed"]:
                n_missed += 1
                events.append(
                    {
                        "t_hours": round(col["scheduled_t_hours"], 4),
                        "type": "collection_missed",
                        "day": col["day"],
                        "slot": col["slot"],
                        "storage_level_t": round(level, 4),
                    }
                )
                continue
            if col["delay_minutes"] >= cfg["timestep_minutes"]:
                n_delayed += 1
                events.append(
                    {
                        "t_hours": round(col["scheduled_t_hours"], 4),
                        "type": "collection_delayed",
                        "day": col["day"],
                        "slot": col["slot"],
                        "delay_minutes": round(col["delay_minutes"], 2),
                    }
                )
            loaded = min(tanker_capacity, level)
            level -= loaded
            collected += loaded
            n_completed += 1
            events.append(
                {
                    "t_hours": round(col["due_t_hours"], 4),
                    "type": "collection_completed",
                    "day": col["day"],
                    "slot": col["slot"],
                    "collected_t": round(loaded, 4),
                    "storage_level_t": round(level, 4),
                    "partial_load": loaded < tanker_capacity - EPS_T,
                }
            )
            step_collected += loaded

        # (b) production into whatever headroom is left
        multiplier = 1.0 + prod_rng.gauss(0.0, variability)
        if multiplier < 0.0:
            multiplier = 0.0  # production can slow or stop, never run backwards
        potential = rate * dt_h * multiplier
        headroom = capacity - level
        if headroom < 0.0:
            headroom = 0.0
        accepted = potential if potential <= headroom else headroom
        lost = potential - accepted
        level += accepted

        potential_production += potential
        accepted_production += accepted
        lost_production += lost

        # curtailment episodes (concise: two events per episode, not per step)
        if lost > EPS_T:
            curtailment_hours += dt_h
            if not curtailing:
                curtailing = True
                episode_start_t = t0
                episode_lost = 0.0
                events.append(
                    {
                        "t_hours": round(t0, 4),
                        "type": "storage_capacity_reached",
                        "storage_level_t": round(level, 4),
                        "capacity_t": round(capacity, 4),
                    }
                )
            episode_lost += lost
        elif curtailing:
            curtailing = False
            events.append(
                {
                    "t_hours": round(t0, 4),
                    "type": "production_curtailed",
                    "start_t_hours": round(episode_start_t, 4),
                    "end_t_hours": round(t0, 4),
                    "duration_hours": round(t0 - episode_start_t, 4),
                    "lost_production_t": round(episode_lost, 4),
                }
            )

        level_sum += level
        if level > max_level:
            max_level = level

        if record:
            win_production += accepted
            win_lost += lost
            win_collected += step_collected
            if (step + 1) % stride == 0 or step == n_steps - 1:
                timeseries.append(
                    {
                        "step": step,
                        "t_hours": round(t1, 4),
                        "production_t": round(win_production, 4),
                        "lost_production_t": round(win_lost, 4),
                        "collected_t": round(win_collected, 4),
                        "storage_level_t": round(level, 4),
                        "storage_utilisation": round(level / capacity, 6),
                    }
                )
                win_production = win_lost = win_collected = 0.0

    if curtailing:
        end_t = n_steps * dt_h
        events.append(
            {
                "t_hours": round(end_t, 4),
                "type": "production_curtailed",
                "start_t_hours": round(episode_start_t, 4),
                "end_t_hours": round(end_t, 4),
                "duration_hours": round(end_t - episode_start_t, 4),
                "lost_production_t": round(episode_lost, 4),
            }
        )

    n_curtailment_episodes = sum(1 for e in events if e["type"] == "production_curtailed")
    mean_level = level_sum / n_steps if n_steps else initial_storage

    metrics = {
        # physical throughput
        "potential_production_t": potential_production,
        "total_production_t": accepted_production,
        "lost_production_t": lost_production,
        "lost_production_pct": (
            100.0 * lost_production / potential_production if potential_production > 0 else 0.0
        ),
        "collected_t": collected,
        # storage
        "initial_storage_t": initial_storage,
        "final_storage_t": level,
        "total_capacity_t": capacity,
        "mean_storage_level_t": mean_level,
        "max_storage_level_t": max_level,
        "mean_storage_utilisation": mean_level / capacity,
        "max_storage_utilisation": max_level / capacity,
        # logistics
        "collections_scheduled": n_scheduled,
        "collections_completed": n_completed,
        "collections_missed": n_missed,
        "collections_delayed": n_delayed,
        "collections_pending_at_end": n_scheduled - next_collection,
        # curtailment
        "curtailment_episodes": n_curtailment_episodes,
        "curtailment_hours": curtailment_hours,
        # self-check, see validate_result()
        "mass_balance_residual_t": (
            initial_storage + potential_production - collected - lost_production - level
        ),
        # bookkeeping
        "simulation_days": cfg["simulation_days"],
        "n_steps": n_steps,
    }

    return {
        "timeseries": timeseries,
        "metrics": metrics,
        "events": events,
        "config": cfg,
        "seed": seed,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_result(result: dict[str, Any], tolerance_t: float = 1e-6) -> None:
    """Assert the physical invariants of a simulation result.

    Used by the tests, and re-run on any result that comes back from a Daytona
    sandbox: we never trust a number we have not checked for conservation of
    material.

    Raises:
        AssertionError: if an invariant is violated.
    """
    for key in ("timeseries", "metrics", "events"):
        assert key in result, f"result is missing '{key}'"

    m = result["metrics"]
    capacity = m["total_capacity_t"]

    assert m["lost_production_t"] >= -tolerance_t, "negative lost production"
    assert m["total_production_t"] >= -tolerance_t, "negative production"
    assert m["collected_t"] >= -tolerance_t, "negative collected tonnage"
    assert -tolerance_t <= m["final_storage_t"] <= capacity + tolerance_t, (
        f"storage {m['final_storage_t']} outside [0, {capacity}]"
    )
    assert abs(m["mass_balance_residual_t"]) <= tolerance_t, (
        f"mass balance violated by {m['mass_balance_residual_t']} t"
    )
    assert abs(
        m["potential_production_t"] - m["total_production_t"] - m["lost_production_t"]
    ) <= tolerance_t, "potential != produced + lost"

    for row in result["timeseries"]:
        assert row["production_t"] >= -tolerance_t, "negative production in timeseries"
        assert row["lost_production_t"] >= -tolerance_t, "negative loss in timeseries"
        assert -tolerance_t <= row["storage_level_t"] <= capacity + 1e-4, (
            f"storage {row['storage_level_t']} outside [0, {capacity}] at step {row['step']}"
        )


# ---------------------------------------------------------------------------
# CLI - this is the entry point used inside a Daytona sandbox
# ---------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    """Read a JSON payload on stdin (or from a file) and print a JSON result.

    Payload: ``{"config": {...}, "seed": 123}``
    """
    raw = open(argv[1]).read() if len(argv) > 1 else sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    result = simulate(payload.get("config"), payload.get("seed"))
    validate_result(result)
    json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
