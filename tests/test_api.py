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


def test_health_reports_ok_with_the_observed_schema_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "dsn", lambda: "postgresql://somewhere/db")
    monkeypatch.setattr(main, "_probe", lambda url: {"database": "up", "public_tables": 23})
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["public_tables"] == 23
