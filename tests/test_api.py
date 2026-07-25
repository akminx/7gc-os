"""The health route must be able to say the system is broken.

A health check that cannot report failure is decoration. These tests drive it
into each outcome — unconfigured, unreachable, and reachable — and assert the
response distinguishes them, because the deploy is only "proven" if a broken
chain would have looked different.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import main
from api.main import app

ROOT = Path(__file__).resolve().parents[1]

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


# ── Step 0 stub routes · the contract path end to end ────────────────────
def test_holding_route_serves_the_fixture_through_the_contract() -> None:
    body = client.get("/holdings/dream").json()
    assert body["holding_id"] == "dream"
    assert body["mark"]["reported"]["amount"] == "5000000"
    # INV-13 · reported is present, validated is absent, and they are separate.
    assert body["mark"]["validated"] is None
    assert body["mark"]["derivation_reason"] == "NO_PRICE_FOR_CLASS:series_a1"


def test_an_unknown_holding_is_404_not_an_empty_row() -> None:
    """ "No rows" and "not a thing we have" are different answers."""
    assert client.get("/holdings/nope").status_code == 404


def test_money_crosses_the_wire_as_a_string_not_a_float() -> None:
    """A float would reintroduce the precision loss the whole money path
    refuses. JSON has no decimal type, so the contract serialises to string."""
    raw = client.get("/funds/fund_ii/periods/f2_25q4/totals").content.decode()
    assert '"amount":"5000000"' in raw.replace(" ", "")


def test_the_total_cannot_be_read_without_its_qualification() -> None:
    """INV-19 · a caller wanting "the fund's value" must read past the caveat to
    reach it, rather than getting a bare number with the caveat elsewhere."""
    body = client.get("/funds/fund_ii/periods/f2_25q4/totals").json()
    assert body["kind"] == "held_at_date_reported"
    assert body["label"] == ("Tracker-reported amounts for positions held at this date, unaudited")
    assert body["unsupported_amount"]["amount"] == body["amount"]["amount"]
    assert body["unsupported_positions"] == 1


def test_packet_route_returns_the_whole_packet() -> None:
    body = client.get("/funds/fund_ii/periods/f2_25q4/packet").json()
    assert body["period"]["audit_scope"] == "packet"
    assert len(body["rows"]) == 1
    assert body["rows"][0]["approval"] is None


def test_an_unknown_packet_is_404() -> None:
    assert client.get("/funds/fund_i/periods/nope/packet").status_code == 404


def test_live_says_nothing_about_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Liveness is about the process. Conflating it with readiness is how a
    service reports healthy while its data is unreachable."""
    monkeypatch.setattr(main, "dsn", lambda: None)
    assert client.get("/live").status_code == 200


def test_ready_returns_503_rather_than_a_200_carrying_bad_news(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPEC §3.2 · /ready never converts a failure into a 200."""
    monkeypatch.setattr(main, "dsn", lambda: None)
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["database"] == "unconfigured"

    def boom(url: str) -> None:
        raise psycopg.OperationalError("refused")

    monkeypatch.setattr(main, "dsn", lambda: "postgresql://nowhere/db")
    monkeypatch.setattr(main, "_ready_probe", boom)
    assert client.get("/ready").status_code == 503


def _capture_ready_probe(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Drive the real `_ready_probe` and record what it asks the database."""
    seen: dict[str, Any] = {}

    class FakeConn:
        def __enter__(self) -> FakeConn:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def execute(self, sql: str) -> SimpleNamespace:
            seen["sql"] = sql
            return SimpleNamespace(fetchone=lambda: (1,))

    def fake_connect(url: str, **kwargs: Any) -> FakeConn:
        seen["kwargs"] = kwargs
        return FakeConn()

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    monkeypatch.setattr(main, "dsn", lambda: "postgresql://somewhere/db")
    return seen


def test_ready_executes_the_locked_probe_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPEC §3.2 locks /ready to `SELECT 1` with a 2 second timeout.

    It ran `select count(*) from information_schema.tables` on a 10 second
    connect timeout instead — a query a reachable but empty or wrong database
    answers successfully, so the route reported ready when it was not.
    """
    seen = _capture_ready_probe(monkeypatch)
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "database": "up"}
    assert seen["sql"].strip().lower() == "select 1"
    assert "information_schema" not in seen["sql"]
    assert seen["kwargs"]["connect_timeout"] == 2
    assert "statement_timeout=2000" in seen["kwargs"]["options"]


def test_render_monitors_readiness_not_the_diagnostic_health_route() -> None:
    """A platform health check pointed at /health is monitoring a route that
    returns 200 while reporting `degraded`, so the database being gone would
    never have been noticed."""
    declared = re.findall(
        r"^\s*healthCheckPath:\s*(\S+)", (ROOT / "render.yaml").read_text(), re.MULTILINE
    )
    assert declared == ["/ready"]
