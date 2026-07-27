"""Fixtures for the schema-invariant suites.

The seed graph is deliberately complete and valid, so every rejection in those
suites is caused by the constraint under test rather than by a dangling
reference. A test that passes because its fixture was broken proves nothing —
that was the defect a cross-family review found in the original INV-14 test.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

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


#: The six fund-periods a packet exists for. Built during fixture setup, while
#: the corpus is still in the transaction that is about to be rolled back.
PACKET_PERIODS = (
    ("fund_i", "fund_i_fy2023"),
    ("fund_i", "fund_i_fy2024"),
    ("fund_i", "fund_i_fy2025"),
    ("fund_ii", "fund_ii_23q4"),
    ("fund_ii", "fund_ii_24q4"),
    ("fund_ii", "fund_ii_25q4"),
)


@pytest.fixture(scope="session")
def policy_ledger(policy_corpus: tuple[object, object]) -> object:
    """The policy inputs built by `policy_corpus`. See that fixture."""
    return policy_corpus[0]


@pytest.fixture(scope="session")
def policy_packets(policy_corpus: tuple[object, object]) -> object:
    """The six packets, assembled from the same corpus. See `policy_corpus`."""
    return policy_corpus[1]


@pytest.fixture(scope="session")
def policy_corpus() -> Iterator[tuple[object, object]]:
    """The real corpus, loaded into a live schema, read back as plain values.

    Yields `(ledger, packets)` — VALUES, with no database session left open.
    That is the whole design of this fixture and it is load-bearing.

    It used to seed the corpus and then hold the transaction open for the
    duration of every test that used it. `addopts = "-n 4 --dist loadfile"`
    sends each FILE to its own worker and this fixture is session-scoped, so it
    is built once per WORKER, not once per run — each copy inserting the same
    FIXED ids (`fund_ii_dream`, `fund_ii_23q4`) into the same schema, in its own
    uncommitted transaction. Every other worker's `insert into company` then
    blocked on rows that would not be written for another twenty-five minutes.
    Three separate gate runs wedged this way, each for ~26 minutes, and the
    shape is indistinguishable from a slow test run.

    An advisory lock was tried first and was not enough: it serialised the two
    copies of THIS fixture against each other, and did nothing about
    `test_document_load.py` and `test_real_data_ledger.py`, which seed the same
    ids through the shared `conn` fixture.

    So the transaction is closed before any test runs. Everything a consumer
    needs — the policy inputs, and the six assembled packets — is read inside
    the transaction and handed out afterwards as values. Zero locks are held
    while tests execute, which removes the conflict rather than scheduling
    around it.

    Built here rather than read from whatever a developer last loaded into
    `demo`: a gate that depends on someone having run a loader is a gate that
    passes because it could not fail.

    `psycopg`'s OUTERMOST `transaction()` block COMMITS on exit, so the rollback
    is explicit rather than left to the context manager's default, which does
    the opposite.
    """
    import psycopg

    from ingest import policy_seed
    from ingest.documents.load import ingest
    from ingest.load import persist
    from ingest.trackers.read import (
        read_master_breakdown,
        read_master_notes,
        read_valuation_tracker,
    )
    from ingest.trackers.to_contracts import map_workbooks
    from policy.from_ledger import load as load_policy
    from tests.tracker_helpers import MASTER, VALUATION

    if DSN is None:
        pytest.skip("no MIGRATION_DATABASE_URL")
    if not (VALUATION.exists() and MASTER.exists()):
        pytest.skip("case-study workbooks are not in the repository")

    from api import ledger as api_ledger

    connection = psycopg.connect(DSN, connect_timeout=30)
    # Two workers can still reach this point at once, and the seeding itself
    # takes two to three minutes. The advisory lock makes the second one wait
    # HERE, holding no row locks, rather than halfway through an insert while
    # holding some.
    #
    # POLLED with `pg_try_advisory_lock`, not the blocking `pg_advisory_lock`.
    # A blocking wait is one long-running statement, and Supabase enforces a
    # `statement_timeout` well below the seeding time — so the wait was
    # CANCELLED, both workers went on to seed concurrently, and the row-lock
    # wedge came back with the lock apparently in place. A guard that is
    # silently cancelled is worse than none: it makes the fix look applied.
    #
    # Each poll is a sub-millisecond statement, so no timeout applies to it.
    deadline = time.monotonic() + 600
    while not connection.execute(
        "select pg_try_advisory_lock(hashtext('policy_ledger_fixture'))"
    ).fetchone()[0]:
        connection.rollback()  # each `execute` opens one; do not accumulate
        if time.monotonic() > deadline:
            connection.close()
            raise TimeoutError(
                "another worker has held the policy-corpus lock for 10 minutes. "
                "Check for an `idle in transaction` session: pg_stat_activity."
            )
        time.sleep(2)
    try:
        with connection.transaction() as outer:
            mapped = map_workbooks(
                read_valuation_tracker(VALUATION),
                read_master_breakdown(MASTER),
                datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
                read_master_notes(MASTER),
            )
            _, refused = persist(connection, mapped)
            assert not refused, f"the workbooks did not load: {refused[:3]}"
            outcomes = ingest(connection)
            failed = [o for o in outcomes if o.error]
            assert not failed, (
                f"documents did not parse: {[(o.path.name, o.error) for o in failed]}"
            )
            policy_seed.seed_claim_requirements(connection)
            policy_seed.seed_document_gaps(connection, read_master_notes(MASTER))
            policy_seed.seed_components(connection)
            connection.execute("set constraints all immediate")
            # Read EVERYTHING now, while the corpus is still here. Whatever is
            # not read before the rollback cannot be read afterwards, which is
            # the price of holding no locks during the tests — and it is worth
            # paying, because the alternative wedged the gate three times.
            built = load_policy(connection)
            packets = {
                (fund_id, period_id): api_ledger.packet(connection, fund_id, period_id)
                for fund_id, period_id in PACKET_PERIODS
            }
            raise psycopg.Rollback(outer)
    finally:
        # Rolled back and CLOSED before the first test runs. The session must
        # not merely be idle — an idle-in-transaction session still holds every
        # row lock it took.
        connection.rollback()
        connection.close()
    yield built, packets
