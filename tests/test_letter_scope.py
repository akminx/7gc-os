"""The scope of the engagement is the letter's, and it is checked rather than assumed.

Harwell & Kent name three measurement dates in ¶2, in parentheses, as an
enumeration:

    "Fair value support as of each measurement date (12/31/2023, 12/31/2024,
     12/31/2025)."

The packet's periods are those three today. Nothing made them so. They are the
three that `ingest/policy_seed.py` happens to mark `packet` scope, and a cross-
family review looking for a rule that could fail found none — "correct by
construction of the seed, not by a letter-literal invariant that would fail if
someone added 25Q3 to `packet`."

That is the shape this project treats as a defect wherever else it appears: a
property everyone believes, held up by nothing. A fourth packet period would
put a measurement date in an auditor's packet that the client did not ask
about, and every "answered for N of M" figure in the acceptance report would
change denominator silently.

The dates are written out here rather than derived from the ledger, for the
reason `tests/test_policy_vs_oracle.py` gives about denominators: a rule that
reads its expectation from the thing it is checking cannot report that the
thing moved.

WHY BOTH FUNDS. `docs/SPEC.md` records the decision to apply the same
categories to Fund I deliberately, because the case study asks for a platform
rather than a one-off. Fund I's three year-ends fall on the same three
calendar dates, so the enumeration holds for both and this asserts it for both.
If Fund I ever needs a period the letter does not name, that is a decision to
record — and this test is where it will surface.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import psycopg
import pytest

from tests.schema_helpers import DSN, Conn

pytestmark = pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")

#: ¶2's parenthesis, transcribed. Not read from `reporting_period`.
LETTER_DATES = (date(2023, 12, 31), date(2024, 12, 31), date(2025, 12, 31))


def _as_date(value: object) -> date:
    """A driver row column, narrowed. Asserted rather than cast: a
    `period_date` that is not a date is a schema change this test should stop
    on, not read through."""
    assert isinstance(value, date), value
    return value


@pytest.fixture(scope="module")
def demo() -> Iterator[Conn]:
    """The loaded fund, read-only — the pattern `tests/test_retrieval.py` set."""
    if DSN is None:
        pytest.skip("no MIGRATION_DATABASE_URL")
    connection = psycopg.connect(DSN, connect_timeout=30, prepare_threshold=None)
    try:
        connection.execute("set search_path to demo")
        connection.execute("set default_transaction_read_only = on")
        rows = connection.execute("select count(*) from reporting_period").fetchone()
        if rows is None or rows[0] == 0:
            pytest.skip("the `demo` schema holds no loaded corpus")
        yield connection
    finally:
        connection.rollback()
        connection.close()


def test_every_packet_period_is_a_date_the_letter_names(demo: Conn) -> None:
    """A packet-scope period the client did not ask about is a reported figure
    they did not request, in a document that says it answers their letter."""
    found = {
        _as_date(r[0])
        for r in demo.execute(
            "select distinct period_date from reporting_period where audit_scope = 'packet'"
        ).fetchall()
    }
    assert found, "no packet-scope periods at all — the packet would be empty"
    unasked = sorted(d for d in found if d not in LETTER_DATES)
    assert not unasked, (
        f"packet scope includes {unasked}, which ¶2 does not enumerate. "
        f"The letter names {[d.isoformat() for d in LETTER_DATES]}."
    )


def test_every_date_the_letter_names_is_actually_in_scope(demo: Conn) -> None:
    """The other direction, and the one a narrowing would hide.

    Dropping a period to `lineage_only` makes every limb's denominator smaller
    and every ratio better, and the packet goes silent about a year the client
    asked about.

    THE DATABASE ALREADY REFUSES THIS, and only sometimes, which is why the
    test is here as well. Demoting a packet period is rejected by
    `pbc_requirement_period_id_audit_scope_fkey` — INV-20's composite key —
    because requirements point at `(period_id, audit_scope)`. That refusal
    depends on requirements EXISTING: `pbc_requirement` is empty on the
    deployed schema, where verdicts are computed on read and nothing is stored.
    So the constraint holds exactly where the seed has run and nowhere else,
    and a guard that is present only in some environments is the shape this
    project keeps finding at the bottom of its false greens.
    """
    by_fund: dict[str, set[date]] = {}
    for fund_id, period_date in demo.execute(
        "select fund_id, period_date from reporting_period where audit_scope = 'packet'"
    ).fetchall():
        by_fund.setdefault(str(fund_id), set()).add(_as_date(period_date))

    assert by_fund, "no packet-scope periods at all"
    for fund_id, dates in sorted(by_fund.items()):
        missing = sorted(d for d in LETTER_DATES if d not in dates)
        assert not missing, (
            f"{fund_id} has no packet period at {[d.isoformat() for d in missing]}, "
            "so the packet is silent about a measurement date the letter names"
        )


def test_a_period_is_packet_scope_or_lineage_only_and_never_both_readings(demo: Conn) -> None:
    """One period, one scope. INV-20 rests on the distinction, and a period
    carrying two rows with different scopes would let a requirement exist for a
    date the packet does not report."""
    duplicated = demo.execute(
        "select fund_id, period_date, count(distinct audit_scope) from reporting_period"
        " group by fund_id, period_date having count(distinct audit_scope) > 1"
    ).fetchall()
    assert not duplicated, f"periods carrying more than one audit scope: {duplicated}"
