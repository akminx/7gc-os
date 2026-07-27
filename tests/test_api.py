"""The health route must be able to say the system is broken.

A health check that cannot report failure is decoration. These tests drive it
into each outcome — unconfigured, unreachable, and reachable — and assert the
response distinguishes them, because the deploy is only "proven" if a broken
chain would have looked different.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import ledger as api_ledger
from api import main, routes
from api.config import resolve_schema
from api.main import app
from policy.from_ledger import load as load_policy
from tests.schema_helpers import DSN

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
    # The two figures used to coincide, because nothing was assessed and every
    # held position was therefore unsupported. The policy layer now assesses
    # them, and Jio's administrator statements support its $1,000,000 — so the
    # unsupported subtotal is strictly SMALLER than the total, which is the
    # arrangement INV-19 exists to make legible. Asserting equality would now
    # pass only while the policy layer found nothing.
    total = Decimal(body["amount"]["amount"])
    unsupported = Decimal(body["unsupported_amount"]["amount"])
    assert Decimal(0) < unsupported < total
    assert body["contains_unsupported_inputs"] is True
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


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_ledger_connection_never_prepares_statements() -> None:
    """Supabase's pooler runs in TRANSACTION mode, where a statement prepared on
    one backend session is not there on the next.

    psycopg prepares a query automatically after its fifth execution. Step 3
    made `packet()` read the claims behind every assessment, which took one
    query past five for the first time — and every packet route began returning
    500 in production while the whole suite stayed green, because the tests
    connect through `MIGRATION_DATABASE_URL`, the direct session-mode
    connection, which supports prepared statements perfectly well.

    The property is asserted on the connection rather than by driving a pooled
    request, so it holds in CI where no pooler URL exists. A test that needed
    the pooler to fail would be a test that never runs.
    """
    conn = routes._connect()
    assert conn is not None
    try:
        assert conn.prepare_threshold is None, (
            "the ledger connection prepares statements; against a transaction-mode "
            "pooler that is a 500 on every route that runs one query six times"
        )
    finally:
        conn.close()


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_packet_route_loads_the_policy_ledger_once_not_twice() -> None:
    """`from_ledger.load` is fourteen statements, and this route needs it twice —
    once to assemble the packet and once to run SPEC §8's validators over it.

    It used to load it twice, which took `GET …/packet` from 18 round trips to
    32. Nothing there is slow on the server: every one of those queries executes
    in 0.1-15 ms, and the cost is entirely the round trip. Deployed, across a
    continent, it is about half a second on the one screen a demo opens.

    The bound is on the COUNT, not on the clock. `test_retrieval.py` carried a
    wall-clock assertion of this shape and it failed three runs in five on an
    unchanged tree, because the denominator was network jitter. A query count is
    what the fix actually changed, and it is deterministic.

    A ceiling of 24 rather than a pin at 18: this notices a reintroduced N+1 or a
    second ledger load, without going red every time a plan shifts by a query.
    A per-holding query would add eight at once and blow through it.

    `psycopg.connect(..., cursor_factory=...)` is not used to count because the
    subclass hook is on the connection. It is a local class rather than a
    module-level one so nothing else can accidentally connect through it.
    """
    counted: list[str] = []
    base = psycopg.Connection

    class Counting(base):
        def execute(self, query, *args, **kwargs):
            counted.append(str(query))
            return super().execute(query, *args, **kwargs)

    conn = Counting.connect(DSN, prepare_threshold=None)
    try:
        with conn:
            conn.execute(f"set search_path to {resolve_schema(None)}")
            counted.clear()
            built = api_ledger.packet(conn, FUND, PERIOD, policy=load_policy(conn))
            assert built is not None, f"no packet for {FUND}/{PERIOD}"
            rows = len(built.rows)
    finally:
        conn.close()

    assert len(counted) <= 24, (
        f"the packet route ran {len(counted)} queries for {rows} holdings. Fourteen "
        f"of them are one `from_ledger.load`; a count near 32 means the caller is "
        f"loading a second ledger instead of sharing the one it already has."
    )


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_both_approval_outcomes_are_reachable_in_the_loaded_schema() -> None:
    """`0003`'s approval prerequisites join `pbc_requirement`,
    `evidence_assessment` and `evidence_link`. While all three were empty, EVERY
    valuation approval — supported or not — was refused with `INV-10: valuation
    approval N names no evidence set`.

    That is a real Postgres refusal, and it is the wrong one: it is plumbing
    rather than the audit finding, and it made an ACCEPTED approval unreachable.
    A demo where every click fails identically cannot show that the database
    refuses the UNSUPPORTED mark specifically.

    So the property is that BOTH outcomes exist in the loaded corpus: at least
    one mark whose every applicable requirement is `sufficient` (approvable) and
    at least one where some applicable requirement is not (refused). Asserting
    only the refusal is what the empty tables already satisfied.

    `ingest/policy_seed.py::seed_assessments` is what writes them, so this goes
    red if that step is dropped from the loader or if it stops running last.
    """
    conn = psycopg.connect(DSN, prepare_threshold=None)
    try:
        conn.execute(f"set search_path to {resolve_schema(None)}")
        rows = conn.execute(
            "select ea.mark_id,"
            "       bool_and(ea.verdict = 'sufficient') as every_one_sufficient"
            "  from evidence_assessment ea"
            "  join pbc_requirement pr on pr.id = ea.requirement_id"
            " where pr.applicable"
            " group by ea.mark_id"
        ).fetchall()
    finally:
        conn.close()

    assert rows, (
        "no evidence assessments in the loaded schema — every valuation approval "
        "will be refused with INV-10 for want of an evidence set, which hides the "
        "refusal the walkthrough is about"
    )
    approvable = [m for m, every in rows if every]
    refused = [m for m, every in rows if not every]
    assert approvable, "no mark is fully supported, so no approval can ever be ACCEPTED"
    assert refused, "every mark is fully supported, so the database's refusal is unreachable"
