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


def ledger_schema() -> str:
    """Which schema the application reads. `public` unless told otherwise.

    The test suites and the demo want opposite things from the same database:
    the schema tests need an empty ledger they can seed and roll back, and the
    demo needs the fund loaded and nothing else. Sharing one schema meant
    `test_the_database_accepts_every_mapped_row` — which asserts the database
    refuses nothing about the real corpus — started failing the moment the real
    corpus was loaded for the demo, because every insert was then a duplicate.

    Two schemas in one database rather than two databases: no console access is
    needed, the same migrations build both, and `search_path` is the only thing
    that differs between them.
    """
    return load_env().get("LEDGER_SCHEMA") or "public"
