"""Tracker ingestion, and the reconciliation it produces.

Split in two on purpose. The date and classification logic is tested with no
workbook at all, because it must be checkable in CI where the fund's private
case-study material does not exist. The reconciliation tests skip when the
workbooks are absent, the same way the schema tests skip without a DSN.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ingest.trackers.read import (
    Tranche,
    _as_range,
    read_master_breakdown,
    read_valuation_tracker,
)
from ingest.trackers.reconcile import FindingKind, reconcile

TRACKERS = Path("7GC Audit Case Study/01_Internal Trackers")
VALUATION = TRACKERS / "Funds I & II - Valuation Tracker (Case Study).xlsx"
MASTER = TRACKERS / "Master Investment Breakdown - Funds I & II (Case Study).xlsx"
needs_workbooks = pytest.mark.skipif(
    not (VALUATION.exists() and MASTER.exists()),
    reason="case-study workbooks are not in the repository",
)


def _tranche(kind: str, investment: str = "1000", text: str | None = None) -> Tranche:
    return Tranche(
        company="X",
        kind=kind,
        investment=Decimal(investment),
        entry_valuation=None,
        share_price=None,
        share_count=None,
        acquired=None,
        acquired_text=text,
        acquired_range=_as_range(text) if text else None,
    )


# ── dates the source states imprecisely ──────────────────────────────────
def test_an_exact_date_becomes_a_single_day() -> None:
    assert _as_range("10/10/2024") == (date(2024, 10, 10), date(2024, 10, 10))


def test_a_month_only_date_becomes_that_month_not_the_first() -> None:
    """Jio's cell says `7/2020`. Collapsing it to July 1st invents a day the
    source never stated, and the day decides whether a lot was held at a quarter
    boundary."""
    assert _as_range("7/2020") == (date(2020, 7, 1), date(2020, 7, 31))


def test_a_multi_year_cell_spans_all_of_them() -> None:
    assert _as_range("2020 / 2021 / 2023") == (date(2020, 1, 1), date(2023, 12, 31))


def test_february_month_range_ends_on_the_real_last_day() -> None:
    assert _as_range("2/2024") == (date(2024, 2, 1), date(2024, 2, 29))


def test_an_unparseable_cell_is_none_rather_than_a_guess() -> None:
    assert _as_range("sometime later") is None
    assert _as_range(None) is None


def test_held_by_answers_yes_no_or_cannot_tell() -> None:
    """The whole point of the range: an imprecise date still answers definitely
    when the entire range falls on one side of the question."""
    jio = _tranche("Indirect Fund", text="7/2020")
    assert jio.held_by(date(2021, 12, 31)) is True  # whole range is earlier
    assert jio.held_by(date(2020, 1, 1)) is False  # whole range is later
    assert jio.held_by(date(2020, 7, 15)) is None  # inside the range


# ── which rows are money going in ────────────────────────────────────────
def test_an_exit_row_is_not_an_investment() -> None:
    """Jackpocket's Exit row carries 3,100,000 of PROCEEDS in the same column
    purchases use for cost. Counting it produced a confident false finding."""
    exit_row = _tranche("Exit", "3100000")
    assert exit_row.is_investment is False
    assert exit_row.is_exit is True
    assert exit_row.is_recognised is True


def test_a_convertible_note_is_an_investment() -> None:
    """The Mom Project's third row is `Fund (Conv. Note)`. Requiring the kind to
    be exactly `Fund` excluded a real 250,000 and invented a second false
    finding — an over-narrow rule in place of an over-broad one."""
    note = _tranche("Fund (Conv. Note)", "250000")
    assert note.is_investment is True
    assert note.is_recognised is True


def test_an_unfamiliar_row_kind_is_flagged_not_bucketed() -> None:
    """Both earlier bugs were a row quietly counted as something it was not, so
    an unrecognised kind becomes a finding rather than a default."""
    unknown = _tranche("Secondary Purchase", "500000")
    assert unknown.is_recognised is False
    findings = reconcile([], [unknown])
    assert [f.kind for f in findings] == [FindingKind.UNRECOGNISED_TRANCHE_KIND]


# ── the real workbooks ───────────────────────────────────────────────────
@needs_workbooks
def test_reads_every_position_and_tranche() -> None:
    sheets = read_valuation_tracker(VALUATION)
    tranches = read_master_breakdown(MASTER)
    assert sum(len(s.companies) for s in sheets) == 14
    assert len(tranches) == 18


@needs_workbooks
def test_the_fund_ii_2023_total_excludes_a_position_it_held() -> None:
    """INV-7 in the source data. The 23Q4 column sums to 6,000,000 and states
    4,000,000 — exactly Jackpocket's mark. The row is labelled `TOTAL (active)`,
    and a position realised in May 2024 has been removed from a December 2023
    total. Held-at-date is not active-today.
    """
    sheets = read_valuation_tracker(VALUATION)
    findings = [
        f
        for f in reconcile(sheets, read_master_breakdown(MASTER))
        if f.kind is FindingKind.STATED_TOTAL_DISAGREES_WITH_CELLS
    ]
    assert len(findings) == 1
    finding = findings[0]
    assert "23Q4" in finding.subject
    assert finding.computed == Decimal("6000000")
    assert finding.stated == Decimal("4000000")
    assert finding.difference == Decimal("2000000")


@needs_workbooks
def test_fluidstack_is_carried_at_cost_while_its_own_round_says_more() -> None:
    """100,000 shares at $10 then 100,000 at $15. Carried at 2,500,000 — exactly
    cost — while the fund's own May 2025 tranche implies 3,000,000."""
    findings = [
        f
        for f in reconcile(read_valuation_tracker(VALUATION), read_master_breakdown(MASTER))
        if f.kind is FindingKind.MARK_HELD_AT_COST_WHILE_LATER_ROUND_EXISTS
    ]
    assert {f.subject.split(" · ")[1] for f in findings} == {"25Q2", "25Q3"}
    assert all(f.stated == Decimal("2500000") for f in findings)
    assert all(f.computed == Decimal("3000000") for f in findings)


@needs_workbooks
def test_no_finding_claims_the_workbooks_disagree_about_cost() -> None:
    """Two false findings of this kind were produced and fixed: an exit counted
    as cost, then a convertible note excluded from it. Both workbooks agree."""
    findings = reconcile(read_valuation_tracker(VALUATION), read_master_breakdown(MASTER))
    assert [
        f for f in findings if f.kind is FindingKind.COST_BASIS_DISAGREES_ACROSS_WORKBOOKS
    ] == []


@needs_workbooks
def test_fund_i_reconciles_completely() -> None:
    """Only Fund II has stated-total findings; Fund I's five columns all add up,
    which is what makes the Fund II result meaningful rather than noise."""
    sheets = read_valuation_tracker(VALUATION)
    fund_i = next(s for s in sheets if "Fund I " in s.fund_label)
    for period in fund_i.period_labels:
        assert fund_i.cells_total(period) == fund_i.stated_totals[period]
