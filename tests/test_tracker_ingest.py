"""Tracker ingestion: reading the workbooks, and the checks a sheet or a single
tranche can answer on its own.

The date and classification logic is tested with no workbook at all, because it
must be checkable in CI where the fund's private case-study material does not
exist. The tests that read the real workbooks skip when they are absent, the
same way the schema tests skip without a DSN.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

from ingest.trackers.findings import FindingKind, _period_end
from ingest.trackers.read import (
    TrackerMark,
    TrackerSheet,
    Tranche,
    _as_range,
    _dec,
    position_held_at,
    read_master_breakdown,
    read_valuation_tracker,
)
from ingest.trackers.reconcile import reconcile
from tests.tracker_helpers import (
    MASTER,
    VALUATION,
    _priced,
    _tranche,
    needs_workbooks,
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
        if f.kind is FindingKind.MARK_AT_COST_DISAGREES_WITH_PURCHASE_PRICES
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
        fund_label="Fund II",
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
        fund_label="Fund II",
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


def test_a_tranche_that_fails_its_own_arithmetic_is_reported() -> None:
    """`check_tranche_arithmetic` had no positive test at all: deleting it left
    only a negative exit-row assertion, and the suite stayed green."""
    bad = _priced("X", "900", "100", "10", "1/1/2024")
    findings = [
        f for f in reconcile([], [bad]) if f.kind is FindingKind.TRANCHE_ARITHMETIC_DISAGREES
    ]
    assert len(findings) == 1
    assert findings[0].stated == Decimal("900")
    assert findings[0].computed == Decimal("1000")


def test_a_stated_cost_total_that_disagrees_with_its_cells_is_reported() -> None:
    """`check_stated_cost_total` had no test whatsoever — deleting the call from
    `reconcile` changed nothing the suite could see."""
    sheet = TrackerSheet(
        fund_label="Fund II",
        period_labels=[],
        companies=["X", "Y"],
        cost_basis={"X": Decimal("200"), "Y": Decimal("100")},
        marks=[],
        stated_cost_total=Decimal("250"),
    )
    findings = [
        f for f in reconcile([sheet], []) if f.kind is FindingKind.COST_TOTAL_DISAGREES_WITH_CELLS
    ]
    assert len(findings) == 1
    assert findings[0].stated == Decimal("250")
    assert findings[0].computed == Decimal("300")


def test_a_period_column_is_read_from_its_own_header_cell(tmp_path: Path) -> None:
    """This test was named for column binding and asserted only `_period_end`,
    so replacing the binding with an inferred offset left it green. It now reads
    a workbook whose header carries a blank cell — exactly what shifted every
    period by one and made the grid read cleanly against the wrong data."""
    import openpyxl

    wb = openpyxl.Workbook()
    # The default sheet has no `Company` header, so the reader skips it — which
    # is itself the behaviour that lets the real workbook carry divider tabs.
    ws = wb.create_sheet("Fund II Holdings by Quarter")
    ws.append(["Company", "Sector", "Cost Basis", "23Q4", None, "24Q2"])
    ws.append(["Acme", "AI", 1000, 111, None, 222])
    path = tmp_path / "tracker.xlsx"
    wb.save(path)

    sheet = read_valuation_tracker(path)[0]
    assert sheet.period_labels == ["23Q4", "24Q2"]
    assert sheet.amount("Acme", "23Q4") == Decimal("111")
    assert sheet.amount("Acme", "24Q2") == Decimal("222")


def test_exit_proceeds_are_not_checked_as_purchase_arithmetic() -> None:
    """An exit's price and count describe shares SOLD; checking them against
    proceeds asks a question with no meaning and reports it as a discrepancy."""
    exit_row = Tranche(
        company="Jackpocket",
        fund="Fund II",
        kind="Exit",
        investment=Decimal("3100000"),
        entry_valuation="Acquisition",
        share_price=Decimal("4"),
        share_count=Decimal("500000"),
        acquired=None,
    )
    kinds = [f.kind for f in reconcile([], [exit_row])]
    assert FindingKind.TRANCHE_ARITHMETIC_DISAGREES not in kinds


@needs_workbooks
def test_the_real_workbook_findings_match_the_committed_snapshot() -> None:
    """The reconciler's other tests are synthetic, because CI has no workbooks.
    That proves a rule fires; it does not show what the fund's actual books
    produce. Four review rounds moved that output between 11 and 34 findings and
    every move was invisible in a diff. Now it is a file.
    """
    from ingest.trackers.snapshot import SNAPSHOT, build

    assert SNAPSHOT.exists(), "run: .venv/bin/python -m ingest.trackers.snapshot"
    committed = json.loads(SNAPSHOT.read_text())
    fresh = json.loads(json.dumps(build()))
    assert fresh["finding_count"] == committed["finding_count"]
    assert fresh["by_kind"] == committed["by_kind"]
    assert fresh["findings"] == committed["findings"]


@needs_workbooks
def test_the_snapshot_describes_the_whole_workbook() -> None:
    """A snapshot of a subset would drift into looking complete. These are the
    dimensions of the source: 14 positions, 18 tranches, 12 fund-periods."""
    from ingest.trackers.snapshot import build

    shape = build()
    assert shape["positions"] == 14
    assert shape["tranches"] == 18
    assert shape["fund_periods"] == 12


@needs_workbooks
def test_findings_are_marked_packet_scope_or_lineage_only() -> None:
    """SPEC 2 closes the packet date set at six fund-periods. The tracker carries
    twelve, and the reconciler read all of them without distinguishing — so a
    finding about 25Q3, a quarter the audit letter never mentions, was
    indistinguishable from one about 12/31/2025, which it does.

    The database enforces this on `reporting_period.audit_scope`. Enforcing it
    there and not here is the one-side-only defect this project keeps producing.
    """
    from ingest.trackers.snapshot import build

    shape = build()
    assert shape["packet_scope_findings"] == 20
    assert shape["lineage_only_findings"] == 16
    found = cast(list[dict[str, str]], shape["findings"])
    periods = {f["subject"].split(" · ")[1] for f in found if f["scope"] == "packet"}
    # Exactly the dates Harwell & Kent asked about, and no others. Equality,
    # not a subset: `<=` passed vacuously while five true packet findings were
    # unscoped and therefore invisible to the filter.
    assert periods == {"23Q4", "24Q4", "25Q4", "FY2023", "FY2024", "FY2025"}
    # Nothing that names a single period may go unscoped.
    unscoped = {f["subject"] for f in found if f["scope"] is None}
    assert unscoped == {
        "Fund II Holdings by Quarter · cost basis",  # a column, not a period
        "Jio · 7/2020",  # a tranche row
        "Jio (Indirect)",  # a company
    }


# ── held-at-date, over a whole position rather than one row ──────────────
#
# `position_held_at` answers what `Tranche.held_by` cannot: whether the fund
# still held ANY of a position at a date. The mapper reads it to fill
# `HoldingRow.held_at_date`, so every `None` below is a figure that either
# enters a fund total or is dropped from one, and each branch is asserted
# because a mutation run found three of them undefended.
def _held(text: str, *, kind: str = "Fund", count: str | None = "100") -> Tranche:
    return _tranche(kind, "1000", text=text, price="10", count=count)


def test_a_position_bought_before_the_date_is_held_at_it() -> None:
    assert position_held_at([_held("1/1/2020")], date(2025, 12, 31)) is True


def test_a_position_bought_after_the_date_is_not_held_at_it() -> None:
    assert position_held_at([_held("1/1/2026")], date(2025, 12, 31)) is False


def test_an_acquisition_date_spanning_the_measurement_date_cannot_be_decided() -> None:
    """`2020 / 2021 / 2023` spans the date, so the source answers neither yes nor
    no. Collapsing that to `False` drops a position the fund may well have held
    out of the total, with nothing saying which one or by how much — the shape of
    every silent understatement this layer has produced."""
    assert position_held_at([_held("2020 / 2021 / 2023")], date(2021, 6, 30)) is None


def test_a_sale_this_reader_cannot_place_leaves_the_answer_undecided() -> None:
    """An exit whose Date cell names a range straddling the measurement date may
    or may not have happened by then. Treating it as no sale at all asserts the
    position was still held, which is the claim the source declines to make."""
    rows = [
        _held("1/1/2020"),
        _tranche("Exit", "5000", text="2025 / 2026", price="25", count="100"),
    ]
    assert position_held_at(rows, date(2025, 12, 31)) is None


def test_a_sale_of_unstated_size_leaves_the_answer_undecided() -> None:
    """Without a share count on the exit, nothing says whether it consumed the
    position or a tenth of it. `True` here is a held-at-date claim resting on the
    absence of a number."""
    rows = [_held("1/1/2020"), _tranche("Exit", "5000", text="3/1/2024", price="25", count=None)]
    assert position_held_at(rows, date(2025, 12, 31)) is None


def test_a_sale_of_the_whole_position_ends_the_holding() -> None:
    rows = [_held("1/1/2020"), _tranche("Exit", "5000", text="3/1/2024", price="25", count="100")]
    assert position_held_at(rows, date(2025, 12, 31)) is False
    # …and not before it happened.
    assert position_held_at(rows, date(2023, 12, 31)) is True


def test_a_partial_sale_leaves_the_position_held() -> None:
    rows = [_held("1/1/2020"), _tranche("Exit", "2000", text="3/1/2024", price="25", count="40")]
    assert position_held_at(rows, date(2025, 12, 31)) is True


def test_a_position_with_no_master_rows_at_all_cannot_be_decided() -> None:
    assert position_held_at([], date(2025, 12, 31)) is None
