"""Read-only projections over the ledger.

Step 0 served these from the hand-written Dream fixture — one holding, 5,000,000
— because the point of the stub was to prove the *contract* path before any
ingestion existed to get it wrong. The source is now the database, and the shape
is unchanged, which is what the fixture was for.

The fixture remains as the fallback when no DSN is configured, so the app still
renders something honest on a machine with no database rather than erroring at
the browser. Which source answered is stated in the response (`source`), because
a demo that silently falls back to a fixture is a demo that shows a number
nobody can trace.

SPEC §3.1 · the public surface is read-only. Every route here is a GET, and
there is no write path to disable later.
"""

from __future__ import annotations

from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException

from api import ledger
from api.config import dsn, ledger_schema
from api.serialize import packet_json, totals_json
from packages.contracts.fixtures.dream import DREAM_ROW, dream_packet
from packages.contracts.models import Packet

router = APIRouter()

#: Kept so the app is demonstrable without a database. Step 0's one holding.
_FIXTURE_ROWS = {DREAM_ROW.holding_id: DREAM_ROW}

#: The one key `GET /holdings/{id}` adds to a `Claim` dump. Named here, and read
#: by `tests/test_web_contracts.py`, because that test previously asserted the
#: browser's shape against the model plus the *literal* `"citations"` — never
#: against this route. So when the route began sending `facts` the assertion
#: went on passing while it described something the route no longer did, and
#: the evidence workspace read `.length` of `undefined` on every claim the
#: ledger held. Only the fixture branch, which serves an empty evidence list,
#: hid it: an empty list agrees with any shape at all.
EVIDENCE_CLAIM_EXTRA = "facts"


def _connect() -> psycopg.Connection[tuple[object, ...]] | None:
    url = dsn("MIGRATION_DATABASE_URL") or dsn("DATABASE_URL")
    if not url:
        return None
    try:
        # `prepare_threshold=None` disables psycopg's automatic prepared
        # statements. Supabase's pooler runs in TRANSACTION mode, where a
        # statement prepared on one backend session is not there on the next —
        # so psycopg preparing a query after its fifth execution produced
        # `DuplicatePreparedStatement` and a 500 on every packet route.
        #
        # It only appeared in production. Locally `MIGRATION_DATABASE_URL` is
        # the direct session-mode connection, which supports prepared
        # statements perfectly well, so the whole test suite passes and the
        # deployed service is down. And it only appeared once Step 3 made
        # `packet()` read the claims behind every assessment, which took the
        # per-request execution count of one query past five for the first
        # time.
        conn = psycopg.connect(url, connect_timeout=10, prepare_threshold=None)
        # Identifier, not a parameter — `set search_path to %s` quotes it as a
        # string literal and silently selects nothing. Restricted to a plain
        # identifier so a stray value cannot become SQL.
        schema = ledger_schema()
        if not schema.replace("_", "").isalnum():
            raise HTTPException(status_code=500, detail="LEDGER_SCHEMA is not an identifier")
        conn.execute(f"set search_path to {schema}")
        return conn
    except psycopg.Error:
        # A database that is configured and unreachable must not silently read
        # as "no database configured" — that would serve the one-row fixture
        # under a real fund's name. Fail the request instead.
        raise HTTPException(status_code=503, detail="ledger unavailable") from None


@router.get("/funds")
def list_funds() -> dict[str, Any]:
    """Every fund-period that can be packeted, so the UI need not hard-code one."""
    conn = _connect()
    if conn is None:
        p = dream_packet()
        return {
            "source": "fixture",
            "periods": [{"fund_id": p.fund_id, "period_id": p.period.id, "label": p.period.label}],
        }
    with conn:
        return {
            "source": "ledger",
            "periods": [
                {"fund_id": f, "period_id": p, "label": lab}
                for f, p, lab in ledger.packet_periods(conn)
            ],
        }


@router.get("/holdings/{holding_id}")
def get_holding(holding_id: str) -> dict[str, Any]:
    """One holding, with every claim made about it and the passage each cites."""
    conn = _connect()
    if conn is None:
        row = _FIXTURE_ROWS.get(holding_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"no holding {holding_id!r}")
        # The same shape either way. An earlier version returned the packet row
        # here for the fixture and a company-plus-evidence object for the
        # ledger, so the route's response depended on which source answered —
        # which is exactly the kind of thing a browser discovers in production.
        return {
            "source": "fixture",
            "holding_id": row.holding_id,
            "company_name": row.company_name,
            "evidence": [],
        }

    with conn:
        found = conn.execute(
            "select h.id, c.display_name from holding h join company c on c.id = h.company_id"
            " where h.id = %s",
            (holding_id,),
        ).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail=f"no holding {holding_id!r}")
        evidence = [
            {
                **claim.model_dump(mode="json"),
                # Each figure, with the passage that states it — not a detached
                # list of quotes. An auditor needs to know which citation
                # supports which number, and `field_name` is that link.
                EVIDENCE_CLAIM_EXTRA: [f.model_dump(mode="json") for f in facts],
            }
            for claim, facts in ledger.claims_for(conn, holding_id)
        ]
        return {
            "source": "ledger",
            "holding_id": str(found[0]),
            "company_name": str(found[1]),
            "evidence": evidence,
        }


def _packet_or_404(fund_id: str, period_id: str) -> tuple[str, Packet]:
    conn = _connect()
    if conn is None:
        p = dream_packet()
        if fund_id != p.fund_id or period_id != p.period.id:
            raise HTTPException(status_code=404, detail=f"no packet {fund_id}/{period_id}")
        return "fixture", p
    with conn:
        built = ledger.packet(conn, fund_id, period_id)
    if built is None:
        raise HTTPException(status_code=404, detail=f"no packet {fund_id}/{period_id}")
    return "ledger", built


@router.get("/funds/{fund_id}/periods/{period_id}/packet")
def get_packet(fund_id: str, period_id: str) -> dict[str, Any]:
    source, built = _packet_or_404(fund_id, period_id)
    return {"source": source, **packet_json(built)}


@router.get("/funds/{fund_id}/periods/{period_id}/totals")
def get_totals(fund_id: str, period_id: str) -> dict[str, Any]:
    """The total, with its kind and its unsupported subtotal attached.

    Deliberately not a bare number. INV-19: a caller that wants "the fund's
    value" has to read past the qualification to get it, rather than receiving an
    unqualified figure and having to remember there was a caveat somewhere.
    """
    source, built = _packet_or_404(fund_id, period_id)
    return {"source": source, **totals_json(built.totals())}
