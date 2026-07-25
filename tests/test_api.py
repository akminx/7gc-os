"""The health route must be able to say the system is broken.

A health check that cannot report failure is decoration. These tests drive it
into each outcome — unconfigured, unreachable, and reachable — and assert the
response distinguishes them, because the deploy is only "proven" if a broken
chain would have looked different.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import main
from api.main import app

client = TestClient(app)


def test_root_identifies_the_service() -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"service": "7gc-os-api", "version": main.VERSION}


def test_health_reports_degraded_when_no_dsn_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "dsn", lambda: None)
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["database"] == "unconfigured"


def test_health_reports_degraded_when_the_database_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route must not answer `ok` on a dead dependency."""

    def boom(url: str) -> dict[str, Any]:
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(main, "dsn", lambda: "postgresql://nowhere/db")
    monkeypatch.setattr(main, "_probe", boom)
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"
    assert body["detail"] == "OperationalError"


def _preflight(origin: str) -> str | None:
    r = client.options(
        "/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    allowed: str | None = r.headers.get("access-control-allow-origin")
    return allowed


def test_this_projects_vercel_deployments_are_allowed() -> None:
    """Production plus per-branch and per-commit preview hostnames."""
    assert _preflight("https://7gc-os.vercel.app") == "https://7gc-os.vercel.app"
    assert _preflight("https://7gc-os-git-main-akminx.vercel.app") is not None


def test_a_foreign_vercel_app_is_not_allowed_to_call_this_api() -> None:
    """The first version of this middleware allowed `https://.*\\.vercel\\.app`,
    which let any app on the platform read this API from a visitor's browser.
    """
    assert _preflight("https://attacker.vercel.app") is None
    assert _preflight("https://evil.example.com") is None


def test_health_reports_ok_with_the_observed_schema_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "dsn", lambda: "postgresql://somewhere/db")
    monkeypatch.setattr(main, "_probe", lambda url: {"database": "up", "public_tables": 23})
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["public_tables"] == 23


def test_a_sibling_named_vercel_project_is_not_allowed() -> None:
    """The first CORS narrowing matched by prefix, so `7gc-osattacker.vercel.app`
    — a project name anyone can claim — was accepted."""
    assert _preflight("https://7gc-osattacker.vercel.app") is None
    assert _preflight("https://7gc-os-evil.vercel.app") is not None  # a real preview shape
