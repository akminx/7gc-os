"""Helpers shared by the schema-invariant suites.

Separate from `conftest.py` because conftest is auto-loaded by pytest but is not
reliably importable by name; these are plain functions the suites import.
"""

from __future__ import annotations

from decimal import Decimal

import psycopg
import pytest

from api.config import dsn

DSN = dsn("MIGRATION_DATABASE_URL")

Conn = psycopg.Connection[tuple[object, ...]]

#: The seed document's canonical text, and one citation into it that resolves.
#:
#: 0008 binds every `extracted_fact` to the text of its claim's document version,
#: so the placeholder these suites used — quote `'q'` at span (0, 1) against a
#: canonical text of `'text'` — no longer inserts. That is the point of the
#: migration: it was a citation that resolved to nothing, and it was legal.
#:
#: The offsets are computed from the text rather than written down, here as
#: everywhere else. A hand-typed offset is the failure INV-8 names, and a test
#: fixture is not exempt — these are the rows the guard is proved against.
SEED_TEXT = "Series B Preferred Stock issued at $8.00 per share."
CITED_QUOTE = "issued at $8.00 per share"
CITED_VALUE = "8.00"
#: The figure the text states. 0008 enforces the equality in BOTH directions, so
#: figure-shaped text with no number beside it is refused — a cited `$8.00` that
#: every downstream reader would see as stating no figure at all.
CITED_NUMBER = Decimal("8.00")
CITED_START = SEED_TEXT.index(CITED_QUOTE)
CITED_END = CITED_START + len(CITED_QUOTE)

#: `value_text, value_numeric, citation_quote, span_start, span_end`, in that
#: column order. Passed as parameters rather than interpolated so the SQL stays
#: a constant.
CITED: tuple[object, ...] = (CITED_VALUE, CITED_NUMBER, CITED_QUOTE, CITED_START, CITED_END)


def rejects(conn: Conn, sql: str, params: tuple[object, ...] = ()) -> str:
    """Assert the statement is refused; return the error text."""
    with pytest.raises(psycopg.Error) as exc:
        conn.execute(sql, params)
    conn.rollback()
    return str(exc.value)


def returned_id(conn: Conn, sql: str, params: tuple[object, ...] = ()) -> int:
    """Run an INSERT ... RETURNING id and hand back the id, typed."""
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    new_id = row[0]
    assert isinstance(new_id, int)
    return new_id


def make_mark(conn: Conn, seed: dict[str, str]) -> int:
    return returned_id(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " derivation_status, derivation_reason)"
        " values (%s, %s, 1000000, 'USD', 'not_derivable', 'x') returning id",
        (seed["h"], seed["p"]),
    )


def make_fact(conn: Conn, seed: dict[str, str]) -> int:
    return returned_id(
        conn,
        "insert into extracted_fact (claim_id, field_name, value_text, value_numeric,"
        " citation_quote, span_start, span_end)"
        " values (%s, 'pps', %s, %s, %s, %s, %s) returning id",
        (seed["cl"], *CITED),
    )


def make_assessment(conn: Conn, seed: dict[str, str], mark_id: int, code: str = "R1") -> int:
    """A requirement plus its assessment, both bound to the mark's own period."""
    req = returned_id(
        conn,
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, %s, true) returning id",
        (seed["h"], seed["p"], code),
    )
    return returned_id(
        conn,
        "insert into evidence_assessment (requirement_id, mark_id, holding_id, period_id,"
        " verdict, policy_version) values (%s, %s, %s, %s, 'sufficient', 'v1') returning id",
        (req, mark_id, seed["h"], seed["p"]),
    )


def cite_price(conn: Conn, claim_id: str) -> None:
    """The cited fact that makes a claim's price traceable. 0009 requires it.

    A claim carrying `price_per_share` with no fact stating that figure is a
    price stored *beside* the citations rather than through them — the shape two
    independent reviews found on the same day, where a claim read 800 next to a
    passage reading $8.00.

    These suites are about other constraints, so their priced claims use the one
    price the seed document states and this supplies its evidence.
    """
    conn.execute(
        "insert into extracted_fact (claim_id, field_name, value_text, value_numeric,"
        " citation_quote, span_start, span_end) values (%s, 'pps', %s, %s, %s, %s, %s)",
        (claim_id, *CITED),
    )
