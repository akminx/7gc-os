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

#: The routes answer from the ledger when a DSN is configured and from the Dream
#: fixture when none is, so the tests ask the service which fund-period it has
#: rather than assuming one. Hard-coding the fixture's ids made every assertion
#: below silently a fixture assertion, which is the thing that stopped being
#: true the moment real data landed.
_periods = client.get("/funds").json()["periods"]
FUND: str = _periods[0]["fund_id"]
PERIOD: str = _periods[0]["period_id"]
HOLDING: str = client.get(f"/funds/{FUND}/periods/{PERIOD}/packet").json()["rows"][0]["holding_id"]


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
def test_holding_route_names_its_source_and_its_evidence() -> None:
    """The route answers from the ledger when one is configured and from the
    fixture when none is. Both shapes are the same, and both say which — a demo
    that silently falls back to a fixture shows a number nobody can trace."""
    body = client.get(f"/holdings/{HOLDING}").json()
    assert body["source"] in {"ledger", "fixture"}
    assert body["holding_id"] == HOLDING
    assert isinstance(body["evidence"], list)


def test_an_unknown_holding_is_404_not_an_empty_row() -> None:
    """ "No rows" and "not a thing we have" are different answers."""
    assert client.get("/holdings/nope").status_code == 404


def test_money_crosses_the_wire_as_a_string_not_a_float() -> None:
    """A float would reintroduce the precision loss the whole money path
    refuses. JSON has no decimal type, so the contract serialises to string."""
    raw = client.get(f"/funds/{FUND}/periods/{PERIOD}/totals").content.decode()
    assert '"amount":"' in raw.replace(" ", "")
    assert "e+" not in raw.lower(), "money must not serialise in exponent form"


def test_the_total_cannot_be_read_without_its_qualification() -> None:
    """INV-19 · a caller wanting "the fund's value" must read past the caveat to
    reach it, rather than getting a bare number with the caveat elsewhere."""
    body = client.get(f"/funds/{FUND}/periods/{PERIOD}/totals").json()
    assert body["kind"] == "held_at_date_reported"
    assert body["label"] == ("Tracker-reported amounts for positions held at this date, unaudited")
    # Nothing is assessed yet, so every held position is unsupported and the two
    # figures coincide. That is the honest state, and the packet says so rather
    # than reporting a clean total it cannot support.
    assert body["unsupported_amount"]["amount"] == body["amount"]["amount"]
    assert body["unsupported_positions"] >= 1
    assert body["contains_unsupported_inputs"] is True


def test_packet_route_returns_the_whole_packet() -> None:
    body = client.get(f"/funds/{FUND}/periods/{PERIOD}/packet").json()
    assert body["period"]["audit_scope"] == "packet"
    assert len(body["rows"]) >= 1
    assert body["rows"][0]["approval"] is None
    # The fields the models compute. They are `@property`, which Pydantic does
    # not serialise, so the wire carried the assessments and not the conclusion
    # drawn from them — and the browser must not draw it itself (SPEC §5.3).
    assert "supported" in body["rows"][0]
    assert "unsupported_reasons" in body["rows"][0]
    assert "totals" in body


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
