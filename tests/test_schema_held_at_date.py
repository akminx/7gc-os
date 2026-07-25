"""INV-7 in the schema: a mark values a position the ledger says was held.

`0005_mark_held_at_date.sql`. The database stored `lot.acquired_date`,
`lot.realized_date` and `reporting_period.period_date` and consulted none of
them when a mark was written, so a 2023-12-31 valuation of a position acquired
in 2025 committed happily. Held-at-date was a rule the packet assembler applied
and the ledger did not.

Half of this file is the other direction, and it is the half that matters most.
The obvious constraint — no mark outside the holding window — refuses the
realisation row, and SPEC §7.1's R4 and V9 need exactly that row: it is where
Jackpocket's 3,100,000 of proceeds would be evidenced. An over-strict guard
deletes the audit letter's request #4 while reading green, so every rejection
below is paired with the acceptance it must not take with it.
"""

from __future__ import annotations

import psycopg
import pytest

from tests.schema_helpers import DSN, Conn, rejects

pytestmark = pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")

#: Every insert here is a mark, so the columns never vary.
_MARK = (
    "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
    " derivation_status, derivation_reason) values (%s, %s, 1000, 'USD', 'not_derivable', 'x')"
)


def _period(conn: Conn, seed: dict[str, str], suffix: str, on: str) -> str:
    """A packet-scope period for the seeded fund, at `on`."""
    pid = f"{seed['p']}_{suffix}"
    conn.execute(
        "insert into reporting_period values (%s, %s, %s, 'packet', %s)",
        (pid, seed["fund"], on, suffix),
    )
    return pid


def _bare_holding(conn: Conn, seed: dict[str, str], suffix: str) -> str:
    """A second holding on the same fund, carrying no lot at all.

    Its own company, because `holding` is unique on (fund, company): one fund
    holding one company twice is the thing lots exist to represent.
    """
    hid = f"{seed['h']}_{suffix}"
    company = f"{seed['co']}_{suffix}"
    conn.execute("insert into company values (%s, 'Other Co')", (company,))
    conn.execute(
        "insert into holding (id, fund_id, company_id, position_type, currency)"
        " values (%s, %s, %s, 'direct_equity', 'USD')",
        (hid, seed["fund"], company),
    )
    return hid


def _lot(conn: Conn, holding: str, lot_id: str, acquired: str, realized: str | None = None) -> None:
    conn.execute(
        "insert into lot (id, holding_id, security_class, cost_amount, cost_currency,"
        " acquired_date, realized_date) values (%s, %s, 'series_a', 1000, 'USD', %s, %s)",
        (lot_id, holding, acquired, realized),
    )


# ── the marks that must be refused ───────────────────────────────────────
def test_a_mark_before_the_position_was_acquired_is_refused(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Dream's live shape: the only lot is acquired after the measurement date.

    There is no reading under which this is legitimate. A position the fund did
    not yet own has no fair value to report, and the figure that lands here is
    plausible, self-consistent and about nothing.
    """
    before = _period(conn, seed, "early", "2023-12-31")
    assert "mark_held_at_date" in rejects(conn, _MARK, (seed["h"], before))


def test_a_mark_long_after_the_position_was_realised_is_refused(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Jackpocket's live shape: sold in 2024, still marked at 2025-12-31.

    The seeded lot is never realised, so this needs a holding of its own — one
    whose every lot is gone before the period even opens.

    The fund must have reported before, or there is no interval to be outside
    of: with no previous packet date the window opens at the beginning of time
    and every realisation is inside it, which is what `opened is null` means and
    what the oracle's `realized_in_window` does with the same facts. The seed's
    only other period is lineage-only and deliberately does not count — see
    `test_a_lineage_only_period_does_not_narrow_the_realisation_window`.
    """
    _period(conn, seed, "reported", "2025-01-31")
    sold = _bare_holding(conn, seed, "sold")
    _lot(conn, sold, f"{seed['lot']}_sold", "2024-01-01", "2024-05-20")
    assert "mark_held_at_date" in rejects(conn, _MARK, (sold, seed["p"]))


def test_a_lineage_only_period_does_not_narrow_the_realisation_window(
    conn: Conn, seed: dict[str, str]
) -> None:
    """SPEC 2 / INV-20 · the audited cadence is the PACKET dates, and only those.

    The interval opened at the previous period of any scope, so a lineage-only
    date sitting between two packet dates moved the boundary forward and the
    guard refused a mark it must take. Jackpocket's exact shape: realised
    2024-05-20, with packet dates at 2023-12-31 and 2024-12-31 and a
    lineage-only 24Q2 in between. The oracle derives R4 `sufficient` for that
    holding at that date off the merger notice, and an `evidence_assessment`
    binds to a `mark` — so refusing this row deletes the only thing R4 could
    ever be assessed against, and 3,100,000 of realised value becomes
    permanently unevidenceable.

    Both halves are asserted. Without the second, moving the bound back far
    enough to admit anything would pass.
    """
    opens = _period(conn, seed, "opens", "2023-12-31")
    conn.execute(
        "insert into reporting_period values (%s, %s, '2024-06-30', 'lineage_only', '24Q2')",
        (f"{seed['p']}_lineage", seed["fund"]),
    )
    closes = _period(conn, seed, "closes", "2024-12-31")
    sold = _bare_holding(conn, seed, "sold")
    _lot(conn, sold, f"{seed['lot']}_sold", "2023-01-01", "2024-05-20")
    # The realisation falls inside (2023-12-31, 2024-12-31], so R4's row commits
    # even though the lineage-only 24Q2 sits between the two packet dates.
    conn.execute(_MARK, (sold, closes))
    # And the guard still bites at the next packet date, where the realisation
    # genuinely precedes the interval. An opening bound moved too far back would
    # accept this one too.
    assert "mark_held_at_date" in rejects(conn, _MARK, (sold, seed["p"]))
    assert opens != closes


# ── the marks that must survive it ───────────────────────────────────────
def test_a_mark_for_a_period_the_position_was_held_through_commits(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The ordinary case, and the one an over-strict rule takes down with it."""
    conn.execute(_MARK, (seed["h"], seed["p"]))
    row = conn.execute("select count(*) from mark where holding_id = %s", (seed["h"],)).fetchone()
    assert row == (1,)
    conn.rollback()


def test_a_realisation_only_mark_inside_its_own_period_commits(
    conn: Conn, seed: dict[str, str]
) -> None:
    """SPEC §7.1 R4 / V9, and the reason this guard reads an interval.

    Jackpocket exactly: realised 2024-05-20, inside the period ending
    2024-06-30, held at no point on the measurement date itself. R4 assesses
    realisation support against a `mark`, so refusing this row would make
    3,100,000 of realised proceeds permanently unevidenced — the audit letter's
    request #4, deleted by a guard that looked correct.
    """
    _period(conn, seed, "opens", "2023-12-31")
    during = _period(conn, seed, "exit", "2024-06-30")
    sold = _bare_holding(conn, seed, "sold")
    _lot(conn, sold, f"{seed['lot']}_sold", "2024-01-01", "2024-05-20")
    conn.execute(_MARK, (sold, during))
    conn.rollback()


def test_a_holding_with_no_lot_is_not_decided_either_way(conn: Conn, seed: dict[str, str]) -> None:
    """Jio: its only master-breakdown row is a kind the reader does not
    recognise, so the position reaches the ledger with marks and no lots.

    Held-at-date is then not computable, and a database that cannot compute an
    answer must not assert one. Refusing here would delete the fund's own
    reported figures for a position it does hold, and would make the real corpus
    unloadable — the expensive direction of the same mistake.
    """
    bare = _bare_holding(conn, seed, "bare")
    conn.execute(_MARK, (bare, seed["p"]))
    conn.rollback()


# ── the other insert order ───────────────────────────────────────────────
def test_the_first_lot_may_not_contradict_a_mark_already_written(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The guard above is defeated by insert order on its own.

    A loader that writes every mark before any lot finds every holding lot-less,
    takes the not-computable carve-out, and INV-7 is never checked at all. The
    lot side closes it: the first lot of a holding that already carries marks
    has to agree with them.
    """
    bare = _bare_holding(conn, seed, "bare")
    conn.execute(_MARK, (bare, seed["p"]))
    assert "lot_agrees_with_existing_marks" in rejects(
        conn,
        "insert into lot (id, holding_id, security_class, cost_amount, cost_currency,"
        " acquired_date) values (%s, %s, 'series_a', 1000, 'USD', '2026-03-01')",
        (f"{seed['lot']}_late", bare),
    )


def test_a_first_lot_that_agrees_with_the_existing_marks_commits(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The same insert order, with a lot that does not contradict anything.

    A rule that refused every lot arriving after a mark would make Jio's
    position unrecordable the day someone works out what its `Indirect Fund`
    row means.
    """
    bare = _bare_holding(conn, seed, "bare")
    conn.execute(_MARK, (bare, seed["p"]))
    _lot(conn, bare, f"{seed['lot']}_ok", "2020-07-01")
    conn.rollback()


def test_a_later_lot_does_not_relitigate_the_marks_it_widens(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Fluidstack's second tranche, and Mom Project's third.

    The predicate is an EXISTS over lots, so a further lot can only ever widen
    it. Re-checking every mark on every lot insert would refuse a legitimate
    later tranche whose own dates fall outside a period already marked — which
    is INV-7's original defect, in reverse.
    """
    conn.execute(_MARK, (seed["h"], seed["p"]))
    _lot(conn, seed["h"], f"{seed['lot']}_2", "2030-01-01")
    conn.rollback()


def test_the_guard_reads_the_periods_of_the_marks_own_fund(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The interval's opening bound is the previous period OF THIS FUND.

    Fund I FY2023 and Fund II 23Q4 are both 2023-12-31 in the real corpus, so
    periods are not distinguishable by date. A bound taken from every fund's
    periods at once would move this holding's window onto another fund's
    reporting cadence, and the two funds here report a year apart.
    """
    other_fund = f"{seed['fund']}_other"
    conn.execute("insert into fund values (%s, 'Other Fund')", (other_fund,))
    conn.execute(
        "insert into reporting_period values (%s, %s, '2025-11-30', 'packet', 'X')",
        (f"{seed['p']}_other", other_fund),
    )
    # The seeded fund's own previous PACKET date. Without one the bound is null,
    # the realisation side does not bind at all, and this test would pass
    # whatever the other fund's periods said — green for a reason that has
    # nothing to do with the rule it names.
    _period(conn, seed, "own", "2025-07-31")
    sold = _bare_holding(conn, seed, "sold")
    _lot(conn, sold, f"{seed['lot']}_sold", "2024-01-01", "2025-08-31")
    # The seeded fund's own previous packet date is 2025-07-31, before the
    # realisation, so the position was held during the period ending
    # 2025-12-31. Reading the other fund's 2025-11-30 as the bound would
    # refuse this.
    conn.execute(_MARK, (sold, seed["p"]))
    conn.rollback()


def test_a_mark_naming_a_period_that_does_not_exist_fails_on_the_key(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The guard runs before the foreign key and must not answer for it.

    Reporting "held no lot in the period ending <null>" for a period id that was
    simply mistyped sends the reader looking at lots. The refusal has to name
    the thing that is actually wrong — here `mark_same_fund`, which reaches the
    same missing row and says so.
    """
    err = rejects(conn, _MARK, (seed["h"], "no_such_period"))
    assert "mark_held_at_date" not in err
    assert "no_such_period" in err


def test_the_guard_does_not_pre_empt_the_cross_fund_refusal(
    conn: Conn, seed: dict[str, str]
) -> None:
    """`mark_same_fund` catches a holding and a period belonging to two funds.

    Triggers fire in name order, so this one runs first. It must let the row
    through to the guard that has the right complaint about it, rather than
    reporting a held-at-date problem for what is an identity problem.
    """
    other_fund = f"{seed['fund']}_other"
    conn.execute("insert into fund values (%s, 'Other Fund')", (other_fund,))
    conn.execute(
        "insert into reporting_period values (%s, %s, '2025-12-31', 'packet', 'FY2025')",
        (f"{seed['p']}_other", other_fund),
    )
    err = rejects(conn, _MARK, (seed["h"], f"{seed['p']}_other"))
    assert "mark_same_fund" in err
    assert "mark_held_at_date" not in err


def test_the_seeded_graph_is_valid_without_the_guard_under_test(
    conn: Conn, seed: dict[str, str]
) -> None:
    """A rejection caused by a broken fixture proves nothing about a constraint.

    Every refusal above is asserted by trigger name for the same reason, and
    this one insert proves the shared seed can hold a mark at all.
    """
    with conn.transaction() as inner:
        conn.execute(_MARK, (seed["h"], seed["lp"]))
        raise psycopg.Rollback(inner)
