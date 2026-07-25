"""Mark checks, rounds 5 and 6: false sentences about true arithmetic.

Split from `test_tracker_marks.py` at the file-size budget. The two rounds
share a shape and it is the one this layer is worst at: the arithmetic is
right, the finding fires for the right reason, and the sentence it prints says
something the workbooks contradict — a full exit reduced to "the 200 shares
then held", two lots on the same day reported as a "later purchase", a lot with
a price but no share count described as stating no price.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ingest.trackers.findings import FindingKind
from ingest.trackers.read import TrackerMark, TrackerSheet, Tranche
from ingest.trackers.reconcile import reconcile
from tests.tracker_helpers import (
    _VALUATION_KINDS,
    _kinds,
    _priced,
    _sheet,
)


def test_a_mark_is_never_compared_to_a_purchase_that_had_not_happened() -> None:
    """Fluidstack's Dec-2024 mark was reported as diverging from a May-2025
    tranche — a price that did not yet exist when the mark was struck.

    The old version of this test forbade a finding kind nothing ever emitted and
    a second kind this fixture could not produce, so it passed with the guard
    deleted. It now asserts the mark draws NO valuation claim of any kind, which
    is the property at stake: at 24Q4 only the first lot is held, and 100,000
    shares at their own $10 is exactly the 1,000,000 carried.
    """
    sheet = _sheet("Fund II", "Fluidstack", {"24Q4": "1000000"})
    early = _priced("Fluidstack", "1000000", "10", "100000", "10/10/2024")
    late = _priced("Fluidstack", "1500000", "15", "100000", "5/30/2025")
    assert not _VALUATION_KINDS & set(_kinds([sheet], [early, late]))


def test_a_later_purchase_is_used_once_the_mark_is_struck_after_it() -> None:
    """The other half of the anachronism guard. A guard that never lets anything
    through is not a guard, so the same fixture one quarter later must produce
    the finding the quarter before must not."""
    sheet = _sheet("Fund II", "Fluidstack", {"25Q2": "2500000"})
    early = _priced("Fluidstack", "1000000", "10", "100000", "10/10/2024")
    late = _priced("Fluidstack", "1500000", "15", "100000", "5/30/2025")
    findings = [f for f in reconcile([sheet], [early, late]) if f.kind in _VALUATION_KINDS]
    assert [f.kind for f in findings] == [FindingKind.MARK_AT_COST_DISAGREES_WITH_PURCHASE_PRICES]
    assert findings[0].computed == Decimal("3000000")


# ── round 5: four false sentences about true arithmetic ──────────────────
def test_sold_shares_are_not_reported_as_still_held() -> None:
    """Exits were dropped before the marks were examined, so a position sold in
    full still reported "the 200 shares then held" — contradicted by an exit row
    in the same workbook. Which lots a sale consumed is not stated, so no claim
    that depends on a share count survives it."""
    sheet = _sheet("Fund II", "X", {"25Q4": "0"})
    lots = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "2000", "20", "100", "1/1/2025"),
        Tranche(
            company="X",
            fund="Fund II",
            kind="Exit",
            investment=Decimal("5000"),
            entry_valuation=None,
            share_price=Decimal("25"),
            share_count=Decimal("200"),
            acquired=None,
            acquired_text="6/1/2025",
            acquired_range=(date(2025, 6, 1), date(2025, 6, 1)),
        ),
    ]
    kinds = _kinds([sheet], lots)
    assert FindingKind.REALISATION_NOT_ALLOCATED_TO_LOTS in kinds
    assert not _VALUATION_KINDS & set(kinds)


def test_a_realisation_after_the_mark_does_not_block_it() -> None:
    """The counterweight: an exit in June 2025 says nothing about a December
    2024 mark, and must not silence it."""
    sheet = _sheet("Fund II", "X", {"24Q4": "3000"})
    lots = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "2000", "20", "100", "6/1/2024"),
        Tranche(
            company="X",
            fund="Fund II",
            kind="Exit",
            investment=Decimal("5000"),
            entry_valuation=None,
            share_price=Decimal("25"),
            share_count=Decimal("200"),
            acquired=None,
            acquired_text="6/1/2025",
            acquired_range=(date(2025, 6, 1), date(2025, 6, 1)),
        ),
    ]
    kinds = _kinds([sheet], lots)
    assert FindingKind.REALISATION_NOT_ALLOCATED_TO_LOTS not in kinds
    assert FindingKind.MARK_AT_COST_DISAGREES_WITH_PURCHASE_PRICES in kinds


def test_a_mark_on_the_trackers_own_disputed_cost_is_reported_and_explained() -> None:
    """Two reviewers disagreed about this one, and the resolution is both.

    Round 5 objected that saying "no row states that basis" was false when the
    tracker's own cost column states exactly that figure. Round 6 objected that
    suppressing the finding was worse: that column is a lifetime total with no
    as-of date, and where it disagrees with the master breakdown it is a figure
    the workbooks CONTRADICT — so the mark has no valuation support, and telling
    an auditor to reconcile two spreadsheets is the wrong letter.

    So the finding fires, and the detail names what the mark actually rests on.
    Both objections are answered; neither is traded for the other.
    """
    sheet = _sheet("Fund II", "X", {"25Q4": "1500"}, cost="1500")
    lots = [
        _priced("X", "500", "10", "50", "1/1/2024"),
        _priced("X", "500", "10", "50", "1/1/2025"),
    ]
    findings = reconcile([sheet], lots)
    basis = [f for f in findings if f.kind in _VALUATION_KINDS]
    assert [f.kind for f in basis] == [FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS]
    assert "equals the cost basis the valuation tracker states" in basis[0].detail
    # And the disagreement itself still surfaces in the check that owns it.
    assert FindingKind.COST_BASIS_DISAGREES_ACROSS_WORKBOOKS in {f.kind for f in findings}


def test_a_mark_on_a_cost_both_workbooks_agree_on_is_not_a_finding() -> None:
    """The counterweight. When the tracker and the master agree, a mark on that
    figure is simply at cost, and nothing is reported."""
    sheet = _sheet("Fund II", "X", {"25Q4": "1000"}, cost="1000")
    lots = [
        _priced("X", "500", "10", "50", "1/1/2024"),
        _priced("X", "500", "10", "50", "1/1/2025"),
    ]
    assert reconcile([sheet], lots) == []


def test_same_day_purchases_are_never_called_a_later_purchase() -> None:
    """Two lots acquired on the same day. Neither follows the other, and the
    finding used to announce a "later purchase" in both its kind and its text."""
    sheet = _sheet("Fund II", "X", {"25Q4": "3000"})
    lots = [
        _priced("X", "1000", "10", "100", "5/30/2025"),
        _priced("X", "2000", "20", "100", "5/30/2025"),
    ]
    findings = [f for f in reconcile([sheet], lots) if f.kind in _VALUATION_KINDS]
    assert [f.kind for f in findings] == [FindingKind.MARK_AT_COST_DISAGREES_WITH_PURCHASE_PRICES]
    assert "later" not in findings[0].detail


def test_a_genuinely_later_purchase_is_still_called_later() -> None:
    """And the word is used when the source earns it — Fluidstack's May 2025
    purchase does follow its October 2024 one."""
    sheet = _sheet("Fund II", "Fluidstack", {"25Q2": "2500000"})
    lots = [
        _priced("Fluidstack", "1000000", "10", "100000", "10/10/2024"),
        _priced("Fluidstack", "1500000", "15", "100000", "5/30/2025"),
    ]
    findings = [f for f in reconcile([sheet], lots) if f.kind in _VALUATION_KINDS]
    assert "later 5/30/2025 purchase" in findings[0].detail


def test_a_missing_share_count_is_not_described_as_a_missing_price() -> None:
    """A lot stating price 10 with no share count was reported as "no lot states
    a share price". It states one."""
    sheet = _sheet("Fund II", "X", {"25Q4": "1500"})
    lots = [
        Tranche(
            company="X",
            fund="Fund II",
            kind="Fund",
            investment=Decimal("1000"),
            entry_valuation=None,
            share_price=Decimal("10"),
            share_count=None,
            acquired=None,
            acquired_text="1/1/2024",
            acquired_range=(date(2024, 1, 1), date(2024, 1, 1)),
        )
    ]
    findings = [f for f in reconcile([sheet], lots) if f.kind in _VALUATION_KINDS]
    assert len(findings) == 1
    assert "no lot states both a share price and a share count" in findings[0].detail


def test_a_mark_that_reaches_no_position_is_reported_not_skipped() -> None:
    """The cost path has always said this; the mark path never did.

    A sheet whose fund label does not normalise onto a tranche fund, or a company
    the master spells differently, was excluded by `_sheets_for` and every mark
    on it went unexamined in silence. On the real workbooks this is Jio: five
    marks, matched against nothing, reported as nothing.
    """
    sheet = _sheet("Fund I / Fund II Combined", "Acme", {"FY2025": "1000"})
    lots = [
        _priced("Acme", "500", "10", "50", "1/1/2024", fund="Fund I"),
        _priced("Acme", "500", "10", "50", "1/1/2025", fund="Fund I"),
    ]
    findings = [f for f in reconcile([sheet], lots) if f.kind is FindingKind.MARK_NEVER_COMPARED]
    # One per period, so each can carry its own packet/lineage scope.
    assert [f.subject for f in findings] == ["Acme · FY2025"]


def test_a_mark_that_does_reach_its_position_is_not_reported_as_unmatched() -> None:
    """A guard that fires on everything says nothing."""
    sheet = _sheet("Fund I Holdings by Year", "Acme", {"FY2025": "1000"})
    lots = [
        _priced("Acme", "500", "10", "50", "1/1/2024", fund="Fund I"),
        _priced("Acme", "500", "10", "50", "1/1/2025", fund="Fund I"),
    ]
    assert FindingKind.MARK_NEVER_COMPARED not in _kinds([sheet], lots)


def test_a_reproduced_mark_and_an_unsupported_one_are_different_findings() -> None:
    """The packet exists to tell investors what evidence to go and collect, and
    these two ask for different things.

    A mark reproduced only by repricing shares nobody repriced needs the fund to
    confirm a treatment. A mark at four times cost with nothing behind it needs
    a valuation memo. Reported under one kind, an auditor cannot tell which.
    """
    lots = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "1000", "20", "50", "1/1/2025"),
    ]
    # 150 shares at the 20.00 price is exactly 3,000 — reproduced, but only by
    # repricing the 100 shares bought at 10.00.
    reproduced = _sheet("Fund II", "X", {"25Q4": "3000"})
    assert [f.kind for f in reconcile([reproduced], lots) if f.kind in _VALUATION_KINDS] == [
        FindingKind.MARK_BASIS_ASSUMES_AN_UNSTATED_TREATMENT
    ]
    # 9,999 is not reproduced by anything in the books.
    unsupported = _sheet("Fund II", "X", {"25Q4": "9999"})
    assert [f.kind for f in reconcile([unsupported], lots) if f.kind in _VALUATION_KINDS] == [
        FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS
    ]


# ── round 6: an exit is not a purchase, and a future sale is not a past one ──
def test_an_exit_is_never_read_as_a_priced_purchase() -> None:
    """`_positions` carries exits so realisations are visible, and an exit has a
    price and a share count too. Reading `lots` instead of `_purchases(lots)`
    announced a sale as a "priced purchase" and entered it into the ordering."""
    sheet = _sheet("Fund II", "X", {"25Q4": "2000"})
    lots = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "1000", "10", "100", "1/1/2025"),
        Tranche(
            company="X",
            fund="Fund II",
            kind="Exit",
            investment=Decimal("5000"),
            entry_valuation=None,
            share_price=Decimal("25"),
            share_count=Decimal("200"),
            acquired=None,
            acquired_text="date unknown",
            acquired_range=None,
        ),
    ]
    findings = reconcile([sheet], lots)
    assert FindingKind.PURCHASE_DATE_UNREADABLE not in {f.kind for f in findings}
    ambiguous = [f for f in findings if f.kind is FindingKind.LATEST_PURCHASE_IS_AMBIGUOUS]
    assert all("date unknown" not in f.detail for f in ambiguous)


def test_a_realisation_total_counts_only_the_sales_that_precede_the_date() -> None:
    """One total across every exit reported a 2026 sale as preceding 25Q4 — a
    share count the source flatly contradicts."""
    # Two DIFFERENT prices, so the allocation genuinely matters and the finding
    # is reached at all — at one price the remainder is the same either way.
    sheet = _sheet("Fund II", "X", {"25Q4": "1000"})
    lots = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "2000", "20", "100", "1/1/2025"),
        Tranche(
            company="X",
            fund="Fund II",
            kind="Exit",
            investment=Decimal("500"),
            entry_valuation=None,
            share_price=Decimal("10"),
            share_count=Decimal("50"),
            acquired=None,
            acquired_text="6/1/2025",
            acquired_range=(date(2025, 6, 1), date(2025, 6, 1)),
        ),
        Tranche(
            company="X",
            fund="Fund II",
            kind="Exit",
            investment=Decimal("1000"),
            entry_valuation=None,
            share_price=Decimal("10"),
            share_count=Decimal("100"),
            acquired=None,
            acquired_text="6/1/2026",
            acquired_range=(date(2026, 6, 1), date(2026, 6, 1)),
        ),
    ]
    findings = [
        f
        for f in reconcile([sheet], lots)
        if f.kind is FindingKind.REALISATION_NOT_ALLOCATED_TO_LOTS
    ]
    assert len(findings) == 1
    assert "a realisation of 50 shares" in findings[0].detail


def test_a_lifetime_cost_basis_does_not_support_a_date_it_predates() -> None:
    """The tracker's cost-basis column carries no as-of date. At a measurement
    date where some lots are not yet held it describes a different position from
    the one being marked — so a 3,000 mark read as supported at 24Q4 because the
    fund's LIFETIME purchases happen to total 3,000, while only 1,000 of cost
    was held and the second lot was still a year away."""
    sheet = TrackerSheet(
        fund_label="Fund II",
        period_labels=["24Q4"],
        companies=["X"],
        cost_basis={"X": Decimal("3000")},
        marks=[TrackerMark("X", "24Q4", Decimal("3000"))],
        stated_totals={"24Q4": Decimal("3000")},
    )
    lots = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "2000", "20", "100", "1/1/2025"),
    ]
    findings = [f for f in reconcile([sheet], lots) if f.kind in _VALUATION_KINDS]
    assert [f.kind for f in findings] == [FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS]
    assert "1,000 cost of the lots held at this date" in findings[0].detail


def test_a_sale_from_one_price_is_allocatable_and_the_basis_gap_is_found() -> None:
    """Which lot a sale consumed only matters when the lots cost different
    amounts. One 100-share lot at 10.00 and a 50-share exit leaves 500 of basis
    under FIFO, specific identification and pro-rata alike — nothing is assumed.

    Blocking it reported an unallocatable realisation, which was false, AND hid
    the 250 gap underneath a 750 mark."""
    sheet = _sheet("Fund II", "X", {"25Q4": "750"})
    lots = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        Tranche(
            company="X",
            fund="Fund II",
            kind="Exit",
            investment=Decimal("500"),
            entry_valuation=None,
            share_price=Decimal("10"),
            share_count=Decimal("50"),
            acquired=None,
            acquired_text="6/1/2025",
            acquired_range=(date(2025, 6, 1), date(2025, 6, 1)),
        ),
    ]
    findings = reconcile([sheet], lots)
    assert FindingKind.REALISATION_NOT_ALLOCATED_TO_LOTS not in {f.kind for f in findings}
    basis = [f for f in findings if f.kind in _VALUATION_KINDS]
    assert [f.kind for f in basis] == [FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS]
    assert "500 cost of the lots held at this date" in basis[0].detail


def test_a_sale_across_two_prices_is_still_unallocatable() -> None:
    """The counterweight. With lots at 10.00 and 20.00, which 50 shares were
    sold changes the remaining basis, and the workbooks do not say."""
    sheet = _sheet("Fund II", "X", {"25Q4": "750"})
    lots = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "2000", "20", "100", "1/1/2025"),
        Tranche(
            company="X",
            fund="Fund II",
            kind="Exit",
            investment=Decimal("500"),
            entry_valuation=None,
            share_price=Decimal("10"),
            share_count=Decimal("50"),
            acquired=None,
            acquired_text="6/1/2025",
            acquired_range=(date(2025, 6, 1), date(2025, 6, 1)),
        ),
    ]
    kinds = _kinds([sheet], lots)
    assert FindingKind.REALISATION_NOT_ALLOCATED_TO_LOTS in kinds
    assert not _VALUATION_KINDS & set(kinds)


def test_an_exit_this_reader_cannot_place_blocks_and_says_so() -> None:
    """An exit whose date cannot be placed against the measurement date leaves
    the share count unknowable exactly as a dated one does.

    `held_by(...) is True` let it through, so the basis check announced "the 150
    shares then held" while a sale of exactly 150 sat on the same sheet — and
    the holding check called the exit "a purchase date". Blocking alone is not
    enough either: a comparison that did not happen must not read as one that
    agreed.
    """
    sheet = _sheet("Fund II", "X", {"25Q4": "9999"})
    lots = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "1000", "20", "50", "1/1/2025"),
        Tranche(
            company="X",
            fund="Fund II",
            kind="Exit",
            investment=Decimal("9999"),
            entry_valuation=None,
            share_price=Decimal("20"),
            share_count=Decimal("150"),
            acquired=None,
            acquired_text="date unknown",
            acquired_range=None,
        ),
    ]
    findings = reconcile([sheet], lots)
    kinds = {f.kind for f in findings}
    assert not _VALUATION_KINDS & kinds
    assert FindingKind.REALISATION_NOT_ALLOCATED_TO_LOTS in kinds
    # And the undecidable row is not described as a purchase.
    assert FindingKind.HOLDING_AT_DATE_UNDECIDABLE not in kinds
    said = next(f for f in findings if f.kind is FindingKind.REALISATION_NOT_ALLOCATED_TO_LOTS)
    assert "cannot place" in said.detail
