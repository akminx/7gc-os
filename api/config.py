"""Environment resolution.

`.env` is read only as a local-development convenience; the process environment
always wins, because that is what Render actually sets. Nothing here reads a
credential at import time — the DSN is resolved per call so a missing variable
surfaces as a degraded health response rather than a crash at startup.
"""

from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    """Merge `.env` under the real environment. Absent `.env` is normal in production."""
    env: dict[str, str] = {}
    f = ROOT / ".env"
    if f.exists():
        for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return {**env, **os.environ}


def dsn(key: str = "DATABASE_URL") -> str | None:
    return load_env().get(key) or None
