"""Unit-agnostic buffer-logistics simulation facade.

The physics are quantities rather than tonnes: continuous inflow enters finite
buffer capacity and scheduled outbound events remove it.  The established CO2
kernel remains the numerical compatibility baseline; this facade translates
neutral configuration names at the boundary so the same deterministic engine
can model liquids, bulk solids, waste, or discrete items without converting
units.
"""

from __future__ import annotations

from typing import Any

try:
    from reference import co2_simulation as _kernel
except ImportError:  # flattened Daytona upload
    import co2_simulation as _kernel  # type: ignore


CONFIG_ALIASES = {
    "inflow_rate": "production_rate_t_per_hour",
    "inflow_variability": "production_variability_pct",
    "buffer_count": "tank_count",
    "buffer_capacity": "tank_capacity_t",
    "initial_buffer": "initial_storage_t",
    "outbound_events_per_day": "collections_per_day",
    "outbound_capacity": "tanker_capacity_t",
    "min_outbound_load": "min_collection_load_t",
    "missed_outbound_probability": "missed_collection_probability",
    "outbound_delay_probability": "collection_delay_probability",
    "outbound_delay_minutes": "collection_delay_minutes",
}

DEFAULT_CONFIG = dict(_kernel.DEFAULT_CONFIG)
derive_seed = _kernel.derive_seed


def _to_kernel_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if config is None:
        return None
    mapped: dict[str, Any] = {}
    for key, value in config.items():
        target = CONFIG_ALIASES.get(key, key)
        if target in mapped and mapped[target] != value:
            raise ValueError(f"conflicting aliases supplied for {target}")
        mapped[target] = value
    return mapped


def normalise_config(config: dict[str, Any] | None) -> dict[str, Any]:
    return _kernel.normalise_config(_to_kernel_config(config))


def simulate(config: dict[str, Any] | None = None, seed: int | None = None) -> dict[str, Any]:
    return _kernel.simulate(_to_kernel_config(config), seed)


def validate_result(result: dict[str, Any]) -> None:
    _kernel.validate_result(result)

