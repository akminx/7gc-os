"""Write the mapped corpus into the ledger. The demo's data path.

This was already written, and it lived inside a test fixture that always rolled
back — so the code that turns two workbooks into a ledger existed, was exercised
on every run, and had never once left a row behind. The development database
held no real data at all as a result: 353 uuid-suffixed seed graphs and nothing
else.

Moved here rather than copied. `tests/test_real_data_ledger.py` imports the same
`persist()` it always used and keeps rolling back; this module adds the one
thing it deliberately lacked, which is a caller that commits.

    .venv/bin/python -m ingest.load            # what would be written
    .venv/bin/python -m ingest.load --commit   # write it

Idempotent by re-run: every row carries a deterministic id derived from the
workbook, so a second run refuses each insert on its primary key and reports it
rather than duplicating. A refusal list is the output either way — the point is
the complete list, not the first failure.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import psycopg

from ingest.trackers.to_contracts import Mapped

Conn = psycopg.Connection[tuple[object, ...]]

#: In dependency order. A later table's foreign keys are satisfied by an
#: earlier one, so the sequence is part of the contract, not a formatting
#: choice.
INSERTS: tuple[tuple[str, str], ...] = (
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
        "lot_conversion",
        "insert into lot_conversion (lot_id, effective_date, to_security_class, to_shares,"
        " exchange_ratio) values (%s, %s, %s, %s, %s)",
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


def rows(m: Mapped) -> dict[str, list[tuple[object, ...]]]:
    """Every mapped row as the tuple its table expects."""
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
        "lot_conversion": [
            (
                c.lot_id,
                c.effective_date,
                c.to_security_class,
                c.to_shares,
                c.exchange_ratio,
            )
            for c in m.conversions
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


def persist(conn: Conn, m: Mapped) -> tuple[dict[str, int], list[str]]:
    """Write everything; return what landed and every rejection, by row.

    Each row gets its own savepoint so one refusal does not abort the rest. The
    caller owns the outer transaction and decides whether to commit — which is
    the whole difference between the test's use of this and the demo's.
    """
    landed: dict[str, int] = {}
    refused: list[str] = []
    params = rows(m)
    for table, sql in INSERTS:
        for row in params[table]:
            try:
                with conn.transaction():
                    conn.execute(sql, row)
                landed[table] = landed.get(table, 0) + 1
            except psycopg.Error as exc:
                refused.append(f"{table} {row[0]!r}: {str(exc).strip().splitlines()[0]}")
    return landed, refused


@dataclass(frozen=True)
class Loaded:
    """What a load did: the mapping, the counts that landed, the refusals."""

    mapped: Mapped
    landed: dict[str, int]
    refused: list[str]


def main(argv: list[str] | None = None) -> int:
    from datetime import UTC, datetime
    from pathlib import Path

    from api.config import SchemaNameError, dsn, resolve_schema
    from ingest.trackers.read import (
        read_master_breakdown,
        read_master_notes,
        read_valuation_tracker,
    )
    from ingest.trackers.to_contracts import map_workbooks

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="write; otherwise roll back")
    parser.add_argument(
        "--schema",
        default=None,
        help="schema to write into; defaults to LEDGER_SCHEMA, else public",
    )
    parser.add_argument(
        "--trackers",
        default="7GC Audit Case Study/01_Internal Trackers",
        help="directory holding the two workbooks",
    )
    args = parser.parse_args(argv)

    trackers = Path(args.trackers)
    valuation = trackers / "Funds I & II - Valuation Tracker (Case Study).xlsx"
    master = trackers / "Master Investment Breakdown - Funds I & II (Case Study).xlsx"
    if not (valuation.exists() and master.exists()):
        print(f"workbooks not found under {trackers}", file=sys.stderr)
        return 1

    url = dsn("MIGRATION_DATABASE_URL")
    if not url:
        print("MIGRATION_DATABASE_URL is not set", file=sys.stderr)
        return 1

    # A fixed instant, not `now()`: the packet's `generated_at` is part of what
    # a manifest records, and a load that stamps a different one each run makes
    # two identical loads look like two different assertions.
    mapped = map_workbooks(
        read_valuation_tracker(valuation),
        read_master_breakdown(master),
        datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
        read_master_notes(master),
    )
    # psycopg's OUTERMOST `transaction()` block COMMITS on exit; only a nested
    # one is a savepoint. `ingest()` opens one per document, so without an outer
    # block around them each document committed itself and `--commit` was
    # decorative — the dry run had already written everything, and the real run
    # then reported nineteen duplicate-key failures against its own output.
    #
    # This is the same trap `tests/test_real_data_ledger.py` documents in as many
    # words, and it arrived here by moving code out of the fixture that used to
    # supply the outer transaction. The rollback is therefore explicit.
    landed: dict[str, int] = {}
    refused: list[str] = []
    try:
        schema = resolve_schema(args.schema)
    except SchemaNameError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    with psycopg.connect(url, connect_timeout=30) as conn:
        # An identifier, so it is formatted rather than parameterised —
        # `set search_path to %s` quotes it as a literal and selects nothing.
        conn.execute(f"set search_path to {schema}")
        try:
            with conn.transaction() as outer:
                landed, refused = persist(conn, mapped)
                if not args.commit:
                    raise psycopg.Rollback(outer)
        except psycopg.Rollback:
            pass

    for table, _ in INSERTS:
        print(f"  {table:20} {landed.get(table, 0)}")
    if refused:
        print(f"\n{len(refused)} refused:")
        for line in refused[:40]:
            print(f"  {line}")
    print("\ncommitted" if args.commit else "\nrolled back — pass --commit to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
