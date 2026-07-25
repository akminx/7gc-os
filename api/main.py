"""The service boundary.

Step 0 deliberately ships one route beyond identity: a health check that
actually reaches the database and counts the schema it expects. A health check
that returns 200 without touching its dependency proves the process started, not
that the system works — and the whole point of this deploy is to prove the path
from browser to Vercel to Render to Supabase before any feature rides on it.
"""

from __future__ import annotations

import os
from typing import Any

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import dsn

SERVICE = "7gc-os-api"
VERSION = "0.1.0"

app = FastAPI(title="7GC OS — Valuation Evidence Ledger", version=VERSION)

# The browser calls this service directly, so the allowed origins are the
# frontend deployments. Vercel preview URLs are per-branch, hence the regex.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("CORS_ORIGINS", "").split(",") if o]
    or ["http://localhost:5173"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": SERVICE, "version": VERSION}


def _probe(url: str) -> dict[str, Any]:
    """Reach the database and report what schema is actually there."""
    with psycopg.connect(url, connect_timeout=10) as conn:
        row = conn.execute(
            "select count(*) from information_schema.tables where table_schema = 'public'"
        ).fetchone()
    return {"database": "up", "public_tables": int(row[0]) if row else 0}


@app.get("/health")
def health() -> dict[str, Any]:
    """Degraded is a first-class answer.

    Reporting `ok` when the database is unreachable would make the deploy look
    proven when it is not, which is the same class of error the ledger itself
    exists to prevent.
    """
    url = dsn()
    if not url:
        return {"status": "degraded", "database": "unconfigured", "service": SERVICE}
    try:
        return {"status": "ok", "service": SERVICE, **_probe(url)}
    except psycopg.Error as exc:
        return {
            "status": "degraded",
            "service": SERVICE,
            "database": "unreachable",
            "detail": type(exc).__name__,
        }
