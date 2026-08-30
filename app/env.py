"""Minimal .env loader.

Avoids a python-dotenv dependency for what is ten lines of parsing. Values
already present in the real environment always win, so an exported key is never
overridden by a stale file.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path | str | None = None) -> dict[str, str]:
    """Load `KEY=value` lines from a .env file into `os.environ`.

    Returns:
        The keys that were actually set (i.e. were not already in the
        environment). Missing file is not an error.
    """
    env_path = Path(path) if path else DEFAULT_ENV_FILE
    loaded: dict[str, str] = {}
    if not env_path.exists():
        return loaded
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded
