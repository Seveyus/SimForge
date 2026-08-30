#!/usr/bin/env python3
"""Build the pre-baked Daytona snapshot for the current model files.

    python scripts/build_snapshot.py            # build if missing
    python scripts/build_snapshot.py --force    # rebuild even if present
    python scripts/build_snapshot.py --list     # show SimForge snapshots
    python scripts/build_snapshot.py --prune    # delete stale SimForge snapshots

The snapshot bakes the simulator, the Monte Carlo driver and the sandbox entry
point into the image, so a scenario sandbox starts in well under a second with
nothing to upload.

Its name carries a content hash of those files. Change the simulator and the
name changes, so a stale snapshot is never silently reused - the runner simply
does not find one and falls back to uploading. Run this again after changing
anything the sandbox executes.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.daytona_runner import (  # noqa: E402
    MODEL_FILES,
    SNAPSHOT_PREFIX,
    build_snapshot,
    model_files_digest,
    snapshot_name,
)
from app.env import load_env  # noqa: E402


def client():
    from daytona import Daytona, DaytonaConfig

    api_key = os.environ.get("DAYTONA_API_KEY")
    if not api_key:
        raise SystemExit("DAYTONA_API_KEY is not set (put it in .env)")
    kwargs = {"api_key": api_key}
    if os.environ.get("DAYTONA_API_URL"):
        kwargs["api_url"] = os.environ["DAYTONA_API_URL"]
    return Daytona(DaytonaConfig(**kwargs))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="rebuild even if it exists")
    parser.add_argument("--list", action="store_true", help="list SimForge snapshots")
    parser.add_argument("--prune", action="store_true",
                        help="delete SimForge snapshots that do not match the current code")
    parser.add_argument("--quiet", action="store_true", help="do not stream build logs")
    args = parser.parse_args(argv)

    load_env()
    daytona = client()
    name = snapshot_name()

    if args.list or args.prune:
        # snapshot.list() returns a PaginatedSnapshots model; iterating the model
        # itself yields (field, value) pairs, so go through .items explicitly.
        listing = daytona.snapshot.list()
        snapshots = [
            s for s in getattr(listing, "items", listing)
            if (getattr(s, "name", "") or "").startswith(f"{SNAPSHOT_PREFIX}-")
        ]
        for snapshot in snapshots:
            current = " (current)" if snapshot.name == name else ""
            print(f"  {snapshot.name}  {getattr(snapshot, 'state', '')}{current}")
        if args.prune:
            for snapshot in snapshots:
                if snapshot.name != name:
                    daytona.snapshot.delete(snapshot)
                    print(f"  deleted {snapshot.name}")
        if not args.force:
            return 0

    print(f"model files ({len(MODEL_FILES)}): digest {model_files_digest()}")
    print(f"snapshot name: {name}")

    if not args.force:
        try:
            daytona.snapshot.get(name)
            print("already exists - nothing to do (use --force to rebuild)")
            return 0
        except Exception:
            pass

    print("building (roughly a minute)...")
    started = time.perf_counter()
    build_snapshot(
        daytona, name,
        on_logs=None if args.quiet else lambda m: print(f"  {m[:120]}"),
    )
    print(f"built {name} in {time.perf_counter() - started:.0f}s")
    print("\nScenario sandboxes will now start from it with nothing to upload.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
