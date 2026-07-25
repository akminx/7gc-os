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
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from api.config import dsn
from api.routes import router

SERVICE = "7gc-os-api"
VERSION = "0.1.0"

app = FastAPI(title="7GC OS — Valuation Evidence Ledger", version=VERSION)

# The browser calls this service directly, so the allowed origins are the
# frontend deployments. Vercel mints a fresh hostname per branch and per commit,
# so previews need a pattern — but it is anchored to this project's own prefix.
# A bare `.*\.vercel\.app` would let anyone's Vercel app call this API from a
# visitor's browser, which is a wide door to leave open for a convenience.
# The production host, or a preview host — which Vercel always builds as
# `<project>-<branch-or-hash>-<scope>`. The separator is load-bearing: a bare
# prefix match also allowed `7gc-osattacker.vercel.app`, so anyone could claim a
# sibling project name and call this API from a visitor's browser.
PREVIEW_ORIGIN = r"https://7gc-os(-[a-z0-9-]+)?\.vercel\.app"

app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("CORS_ORIGINS", "").split(",") if o]
    or ["http://localhost:5173"],
    allow_origin_regex=PREVIEW_ORIGIN,
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


# ── SPEC §3.2 · liveness and readiness are different questions ───────────
# A single /health conflated them and could report 200 while the database was
# down. /health above stays the DIAGNOSTIC probe: it returns 200 even when
# degraded, so a human can ask "what is actually there" without the answer being
# an outage. /ready is the honest answer for a caller deciding whether to trust
# the data, it is what Render monitors, and it never converts a failure to 200.

READY_TIMEOUT_SECONDS = 2


def _ready_probe(url: str) -> None:
    """SPEC §3.2 verbatim: `SELECT 1`, 2 second timeout, nothing else.

    /ready previously reused `_probe`, which counts `information_schema.tables`
    with a 10 second connect timeout. That answers a different question: a
    reachable but empty or wrong database returns a count of zero, which is a
    successful query, so the route reported 200. Both halves of the locked
    contract are bounded here — the connection AND the statement — because a
    connect timeout alone leaves a hung query unbounded.
    """
    with psycopg.connect(
        url,
        connect_timeout=READY_TIMEOUT_SECONDS,
        options=f"-c statement_timeout={READY_TIMEOUT_SECONDS * 1000}",
    ) as conn:
        conn.execute("select 1").fetchone()


@app.get("/live")
def live() -> dict[str, str]:
    """The process is up. Says nothing about its dependencies, on purpose."""
    return {"status": "live", "service": SERVICE}


@app.get("/ready")
def ready(response: Response) -> dict[str, str]:
    """Reaches the database. 503 on failure — never a 200 with bad news inside."""
    url = dsn()
    if not url:
        response.status_code = 503
        return {"status": "not_ready", "database": "unconfigured"}
    try:
        _ready_probe(url)
    except psycopg.Error as exc:
        response.status_code = 503
        return {"status": "not_ready", "database": "unreachable", "detail": type(exc).__name__}
    return {"status": "ready", "database": "up"}
