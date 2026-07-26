"""Fixtures for the schema-invariant suites.

The seed graph is deliberately complete and valid, so every rejection in those
suites is caused by the constraint under test rather than by a dangling
reference. A test that passes because its fixture was broken proves nothing —
that was the defect a cross-family review found in the original INV-14 test.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from tests.schema_helpers import DSN, SEED_TEXT, Conn


@pytest.fixture(scope="session")
def _connection() -> Iterator[Conn]:
    """One connection for the whole session, not one per test.

    The database is remote, so connecting per test paid a TLS handshake to
    us-east-1 before the first statement of each of the ~100 schema tests — a
    quarter of the suite's wall clock spent opening sockets.

    Isolation never came from the connection and does not change here: it comes
    from the rollback in `conn` below and from the uuid-suffixed ids every seed
    generates. Nothing in these suites commits.
    """
    assert DSN is not None  # callers guard with skipif
    connection = psycopg.connect(DSN, connect_timeout=30)
    try:
        yield connection
    finally:
        # Explicit, because psycopg's own context manager COMMITS on a clean
        # exit. A suite whose whole isolation story is "nothing commits" must
        # not leave that to a default that does the opposite.
        connection.rollback()
        connection.close()


@pytest.fixture
def conn(_connection: Conn) -> Iterator[Conn]:
    """Each test runs in a transaction that is always rolled back.

    Teardown also clears an aborted transaction, so a test that ends inside a
    failed statement cannot leave the next one unable to execute.
    """
    yield _connection
    _connection.rollback()


@pytest.fixture
def seed(conn: Conn) -> dict[str, str]:
    u = uuid.uuid4().hex[:8]
    i = {k: f"{k}_{u}" for k in ("fund", "co", "h", "sf", "dv", "cl", "p", "lp", "lot")}
    stmts: list[tuple[str, tuple[object, ...]]] = [
        ("insert into fund values (%s, 'Test Fund')", (i["fund"],)),
        ("insert into company values (%s, 'Test Co')", (i["co"],)),
        (
            "insert into holding (id, fund_id, company_id, position_type, currency)"
            " values (%s, %s, %s, 'direct_equity', 'USD')",
            (i["h"], i["fund"], i["co"]),
        ),
        (
            "insert into source_file (id, filename, content_hash, byte_size, bytes)"
            " values (%s, 'f.pdf', %s, 1, '\\x00')",
            (i["sf"], f"hash_{u}"),
        ),
        (
            "insert into document_version"
            " (id, source_file_id, canonical_text, extractor, text_hash, page_count)"
            " values (%s, %s, %s, 'pdftotext@1', %s, 1)",
            (i["dv"], i["sf"], SEED_TEXT, f"th_{u}"),
        ),
        (
            "insert into claim (id, document_version_id, holding_id, claim_key,"
            " source_class, execution_status, issued_date, applicable_from, applicable_to)"
            " values (%s, %s, %s, 'k', 'company_communication', 'executed',"
            " '2025-06-30', '2025-01-01', '2026-12-31')",
            (i["cl"], i["dv"], i["h"]),
        ),
        (
            "insert into reporting_period values (%s, %s, '2025-12-31', 'packet', 'FY2025')",
            (i["p"], i["fund"]),
        ),
        (
            "insert into reporting_period values (%s, %s, '2025-06-30', 'lineage_only', 'H1')",
            (i["lp"], i["fund"]),
        ),
        (
            "insert into lot (id, holding_id, security_class, shares, entry_pps,"
            " cost_amount, cost_currency, acquired_date)"
            " values (%s, %s, 'series_a', 1000, 2.00, 2000, 'USD', '2024-01-01')",
            (i["lot"], i["h"]),
        ),
    ]
    for sql, params in stmts:
        conn.execute(sql, params)
    return i
