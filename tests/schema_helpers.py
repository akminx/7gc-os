"""Helpers shared by the schema-invariant suites.

Separate from `conftest.py` because conftest is auto-loaded by pytest but is not
reliably importable by name; these are plain functions the suites import.
"""

from __future__ import annotations

import psycopg
import pytest

from api.config import dsn

DSN = dsn("MIGRATION_DATABASE_URL")

Conn = psycopg.Connection[tuple[object, ...]]


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
        "insert into extracted_fact (claim_id, field_name, value_text, citation_quote,"
        " span_start, span_end) values (%s, 'pps', '8.00', 'q', 0, 1) returning id",
        (seed["cl"],),
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
