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
    TrackerMark,
    TrackerSheet,
    Tranche,
    _as_range,
    _dec,
    read_master_breakdown,
    read_valuation_tracker,
)
from ingest.trackers.reconcile import FindingKind, _period_end, reconcile

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


def _priced(company: str, inv: str, price: str, count: str, text: str) -> Tranche:
    return Tranche(
        company=company,
        kind="Fund",
        investment=Decimal(inv),
        entry_valuation=None,
        share_price=Decimal(price),
        share_count=Decimal(count),
        acquired=None,
        acquired_text=text,
        acquired_range=_as_range(text),
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


# ── silence must not look like agreement ─────────────────────────────────
def test_a_company_on_only_one_side_is_reported_not_skipped() -> None:
    """The critical review finding. A tab named `Fluid Stack` while the tracker
    says `Fluidstack` made the join produce nothing, and the report read clean
    because the two cost statements were never compared at all."""
    sheet = TrackerSheet(
        fund_label="F",
        period_labels=[],
        companies=["Fluidstack"],
        cost_basis={"Fluidstack": Decimal("2500000")},
        marks=[],
    )
    kinds = [f.kind for f in reconcile([sheet], [_tranche("Fund", "2500000")])]
    assert FindingKind.COST_BASIS_NEVER_COMPARED in kinds


def test_a_sheet_with_no_stated_total_says_nothing_was_checked() -> None:
    """A footer renamed to `Sum (active)` left stated_totals empty, so every
    period was skipped and the run reported clean."""
    sheet = TrackerSheet(
        fund_label="F",
        period_labels=["23Q4"],
        companies=["X"],
        cost_basis={},
        marks=[TrackerMark("X", "23Q4", Decimal("100"))],
    )
    assert FindingKind.NO_STATED_TOTAL_TO_CHECK in [f.kind for f in reconcile([sheet], [])]


def test_a_number_stored_as_text_still_counts_toward_its_column() -> None:
    """Excel stores pasted numbers as text. Dropping them understated a column
    while the footer still counted them."""
    assert _dec("2500000") == Decimal("2500000")
    assert _dec("$2,500,000") == Decimal("2500000")
    assert _dec("(1000)") == Decimal("-1000")
    assert _dec("Realized 5/20/24") is None


def test_a_period_label_binds_to_its_own_column_not_an_inferred_offset() -> None:
    """A blank or merged header cell shifted every period by one, so the grid
    read cleanly against the wrong data."""
    end = _period_end
    assert end("25Q4") == date(2025, 12, 31)
    assert end("23Q4") == date(2023, 12, 31)
    assert end("FY2024") == date(2024, 12, 31)
    assert end("25Q1") == date(2025, 3, 31)
    assert end("whenever") is None


def test_a_mark_is_never_compared_to_a_round_that_had_not_happened() -> None:
    """Fluidstack's Dec-2024 mark was reported as diverging from a May-2025
    tranche — a price that did not yet exist when the mark was struck."""
    sheet = TrackerSheet(
        fund_label="F",
        period_labels=["24Q4"],
        companies=["Fluidstack"],
        cost_basis={},
        marks=[TrackerMark("Fluidstack", "24Q4", Decimal("1000000"))],
        stated_totals={"24Q4": Decimal("1000000")},
    )
    early = _priced("Fluidstack", "1000000", "10", "100000", "10/10/2024")
    late = _priced("Fluidstack", "1500000", "15", "100000", "5/30/2025")
    kinds = [f.kind for f in reconcile([sheet], [early, late])]
    assert FindingKind.MARK_DIVERGES_FROM_LATER_ROUND not in kinds
    assert FindingKind.MARK_HELD_AT_COST_WHILE_LATER_ROUND_EXISTS not in kinds
