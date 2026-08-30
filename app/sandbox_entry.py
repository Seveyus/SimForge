"""Entry point executed *inside* a Daytona sandbox.

The sandbox receives a flat directory containing this file plus the simulation
modules, and a JSON payload. It runs the requested work and prints the result
between two markers so the host can extract it from stdout without being
confused by anything else the runtime writes.

Payload::

    {
      "mode": "monte_carlo" | "simulate",
      "config": {...},
      "n_runs": 200,
      "base_seed": 20260830,
      "name": "extra_tank",
      "with_representative_run": true,
      "timeseries_stride": 6
    }

This file has no third-party imports: the sandbox needs no pip install, which
keeps scenario execution fast.
"""

from __future__ import annotations

import json
import platform
import sys
import time
import traceback

RESULT_BEGIN = "<<<SIMFORGE_RESULT_BEGIN>>>"
RESULT_END = "<<<SIMFORGE_RESULT_END>>>"


def main(argv: list[str]) -> int:
    started = time.perf_counter()
    try:
        payload_path = argv[1] if len(argv) > 1 else "payload.json"
        with open(payload_path) as handle:
            payload = json.load(handle)

        from co2_simulation import simulate, validate_result
        from monte_carlo import representative_run, run_monte_carlo

        mode = payload.get("mode", "monte_carlo")
        config = payload.get("config") or {}

        if mode == "simulate":
            result = simulate(config, payload.get("seed"))
            validate_result(result)
            output = {"mode": mode, "result": result}
        elif mode == "monte_carlo":
            mc = run_monte_carlo(
                config,
                n_runs=int(payload.get("n_runs", 200)),
                base_seed=int(payload.get("base_seed", 20260830)),
                name=payload.get("name", "scenario"),
            )
            if payload.get("with_representative_run"):
                mc["representative_run"] = representative_run(
                    config,
                    base_seed=int(payload.get("base_seed", 20260830)),
                    timeseries_stride=int(payload.get("timeseries_stride", 6)),
                )
            output = {"mode": mode, "result": mc}
        else:
            raise ValueError(f"unknown mode: {mode!r}")

        output["ok"] = True
        output["environment"] = {
            "python": platform.python_version(),
            "machine": platform.machine(),
            "node": platform.node(),
        }
        output["sandbox_runtime_seconds"] = time.perf_counter() - started
    except Exception as exc:  # noqa: BLE001 - the host needs the diagnosis
        output = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }

    print(RESULT_BEGIN)
    json.dump(output, sys.stdout)
    print()
    print(RESULT_END)
    return 0 if output.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
