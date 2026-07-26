"""Gate D1, the database half: the real corpus, written into a live schema.

Split from `test_real_data_end_to_end.py` at the file-size budget. That file
takes the two workbooks as far as the contract layer; this one takes what it
produced and writes it, so the invariants enforced as database constraints meet
the fund's actual rows rather than a fixture shaped to fit them.

Every test here needs both the case-study workbooks and a DSN, and skips without
either — so it is listed in `DB_GUARD_TARGETS` (`scripts/check_all.py`), which
turns a skip in CI into a red gate rather than a silent pass.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import psycopg
import pytest

from ingest.trackers.to_contracts import Mapped
from tests.schema_helpers import DSN, Conn
from tests.test_real_data_end_to_end import _mapped
from tests.tracker_helpers import needs_workbooks

# ── the database ─────────────────────────────────────────────────────────
_INSERTS: tuple[tuple[str, str], ...] = (
    ("fund", "insert into fund values (%s, %s)"),
    ("company", "insert into company values (%s, %s)"),
    (
        "holding",
        "insert into holding (id, fund_id, company_id, position_type, currency)"
        " values (%s, %s, %s, %s, %s)",
    ),
    ("reporting_period", "insert into reporting_period values (%s, %s, %s, %s, %s)"),
    (
        "lot",
        "insert into lot (id, holding_id, security_class, shares, entry_pps, cost_amount,"
        " cost_currency, acquired_date, realized_date) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
    ),
    (
        "mark",
        "insert into mark (holding_id, period_id, revision, reported_amount, reported_currency,"
        " derivation_status, derivation_reason) values (%s, %s, %s, %s, %s, %s, %s)",
    ),
    (
        "packet_version",
        "insert into packet_version (id, fund_id, period_id, audit_scope, state, schema_version,"
        " policy_version, generator_ref) values (%s, %s, %s, %s, %s, %s, %s, %s)",
    ),
)


def _params(m: Mapped) -> dict[str, list[tuple[object, ...]]]:
    """Every mapped row as the tuple its table expects, in dependency order."""
    return {
        "fund": [(f, f) for f in sorted({h.fund_id for h in m.holdings})],
        "company": [(h.company_id, h.company_name) for h in m.holdings],
        "holding": [
            (h.id, h.fund_id, h.company_id, h.position_type.value, h.currency) for h in m.holdings
        ],
        "reporting_period": [
            (p.id, p.fund_id, p.period_date, p.audit_scope.value, p.label) for p in m.periods
        ],
        "lot": [
            (
                lot.id,
                lot.holding_id,
                lot.security_class,
                lot.shares,
                lot.entry_pps,
                lot.cost.amount,
                lot.cost.currency,
                lot.acquired_date,
                lot.realized_date,
            )
            for lot in m.lots
        ],
        "mark": [
            (
                mk.holding_id,
                mk.period_id,
                mk.revision,
                mk.reported.amount,
                mk.reported.currency,
                mk.derivation_status.value,
                mk.derivation_reason,
            )
            for mk in m.marks
        ],
        "packet_version": [
            (
                f"pk_{p.period.id}",
                p.fund_id,
                p.period.id,
                p.period.audit_scope.value,
                "draft",
                p.schema_version,
                p.policy_version,
                "ingest.trackers.to_contracts.map_workbooks",
            )
            for p in m.packets
        ],
    }


def _persist(conn: Conn, m: Mapped) -> tuple[dict[str, int], list[str]]:
    """Write everything; return what landed and every rejection, by row.

    Each row gets its own savepoint so one refusal does not abort the rest —
    the point is the complete list of refusals, not the first one. The caller
    supplies the outer transaction and always rolls it back.
    """
    landed: dict[str, int] = {}
    refused: list[str] = []
    params = _params(m)
    for table, sql in _INSERTS:
        for row in params[table]:
            try:
                with conn.transaction():
                    conn.execute(sql, row)
                landed[table] = landed.get(table, 0) + 1
            except psycopg.Error as exc:
                refused.append(f"{table} {row[0]!r}: {str(exc).strip().splitlines()[0]}")
    return landed, refused


#: What `_persist` hands back: the mapping, the per-table counts that landed,
#: and one line per row the database refused.
Loaded = tuple[Mapped, dict[str, int], list[str]]


@pytest.fixture
def loaded(conn: Conn) -> Iterator[Loaded]:
    """The real corpus, written into a transaction that is never committed.

    psycopg's OUTERMOST `transaction()` block COMMITS on exit; only a nested one
    is a savepoint. Writing this the obvious way left 2 funds, 14 holdings, 16
    lots, 72 marks and 12 packet versions permanently on the development
    database. The outer block is therefore aborted explicitly with
    `psycopg.Rollback`, and `conn` rolls back again on teardown.
    """
    m = _mapped()
    try:
        with conn.transaction() as outer:
            yield (m, *_persist(conn, m))
            raise psycopg.Rollback(outer)
    except psycopg.Rollback:
        pass


@needs_workbooks
@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_database_accepts_every_mapped_row(
    loaded: Loaded,
) -> None:
    """Zero rejections — which is a finding, not a pass.

    The database refuses nothing about the real corpus because everything it
    could have refused was substituted before it arrived: the currency, the
    security class, the position type and the audit scope. A schema cannot reject
    a silence that a mapper has already filled in.
    """
    _m, landed, refused = loaded
    assert refused == []
    assert landed == {
        "fund": 2,
        "company": 14,
        "holding": 14,
        "reporting_period": 12,
        "lot": 17,
        "mark": 72,
        # Six, not twelve: SPEC 2 closes the packet date set, and the other six
        # fund-periods reach the ledger as `reporting_period` rows without ever
        # being packeted.
        "packet_version": 6,
    }


@needs_workbooks
@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_database_refuses_a_mark_for_a_date_the_position_was_not_held(
    conn: Conn, loaded: Loaded
) -> None:
    """INV-7 in the schema, on real rows.

    Dream's only lot was acquired 2025-08-01 and Jackpocket's only lot was
    realised 2024-05-20, and the ledger took a 2023-12-31 mark for the first and
    a 2025-12-31 mark for the second: held-at-date was computable from `lot` and
    nothing consulted it when a mark was written, so the guard that makes INV-7
    real existed only in whatever assembled the packet. `0005` closes it.
    """
    for holding, period in (
        ("fund_ii_dream", "fund_ii_23q4"),
        ("fund_ii_jackpocket", "fund_ii_25q4"),
    ):
        with conn.transaction() as inner:
            with pytest.raises(psycopg.Error) as exc:
                conn.execute(
                    "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
                    " derivation_status, derivation_reason)"
                    " values (%s, %s, 1, 'USD', 'not_derivable', 'probe')",
                    (holding, period),
                )
            assert "mark_held_at_date" in str(exc.value)
            raise psycopg.Rollback(inner)


@needs_workbooks
@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_database_still_takes_a_mark_for_a_date_the_position_was_held(
    conn: Conn, loaded: Loaded
) -> None:
    """The direction that must survive the guard, on the same real rows.

    Jackpocket was held at 2023-12-31 and Dream at 2025-12-31. An over-strict
    held-at-date rule refuses these as confidently as it refuses the two above,
    and a packet missing a position it does hold is the failure this whole file
    exists to catch.
    """
    for holding, period in (
        ("fund_ii_jackpocket", "fund_ii_23q4"),
        ("fund_ii_dream", "fund_ii_25q4"),
    ):
        with conn.transaction() as inner:
            conn.execute(
                "insert into mark (holding_id, period_id, revision, reported_amount,"
                " reported_currency, derivation_status, derivation_reason)"
                " values (%s, %s, 2, 1, 'USD', 'not_derivable', 'probe')",
                (holding, period),
            )
            raise psycopg.Rollback(inner)


@needs_workbooks
@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_database_refuses_a_mark_whose_period_belongs_to_another_fund(
    conn: Conn, loaded: Loaded
) -> None:
    """Fund I FY2023 and Fund II 23Q4 are both 2023-12-31, so the two funds'
    periods are indistinguishable by date. `mark_same_fund` catches it."""
    with pytest.raises(psycopg.Error) as exc:
        conn.execute(
            "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
            " derivation_status, derivation_reason)"
            " values ('fund_i_capsule', 'fund_ii_23q4', 600000, 'USD', 'not_derivable', 'x')"
        )
    assert "mark_same_fund" in str(exc.value)


@needs_workbooks
@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_ledger_and_the_packet_report_the_same_fund_totals(loaded: Loaded, conn: Conn) -> None:
    """The round trip, and it closes.

    Summing `mark.reported_amount` out of the database gives the tracker's
    figure. `Packet.totals()` gives that figure minus every row whose
    `held_at_date` is False — and the database stores no such column, only the
    lots it is derivable from. The two layers disagreed by Jio's 1,000,000 in
    every Fund I period: five of twelve fund-periods reporting two different
    numbers for the same fund on the same facts, only one of them qualified.

    They now agree in all six. This is a weaker statement than it looks and is
    deliberately kept: it closes only because no row in the real corpus is
    excluded from its total. The moment one legitimately is — a position realised
    before a measurement date it still has a mark for — these two numbers part
    company again, correctly, and `PacketTotals` has no field in which to say so.
    """
    m, _landed, _refused = loaded
    differ: dict[str, Decimal] = {}
    for packet in m.packets:
        row = conn.execute(
            "select sum(reported_amount) from mark where period_id = %s", (packet.period.id,)
        ).fetchone()
        assert row is not None
        ledger_total = Decimal(str(row[0]))
        if ledger_total != packet.totals().amount.amount:
            differ[packet.period.label] = ledger_total - packet.totals().amount.amount
    assert differ == {}
    assert len(m.packets) == 6
