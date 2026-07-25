"""What the tracker's marks and the master breakdown's purchases say about
each other — one test per check in `ingest/trackers/marks.py`.

Every test here was written to go red when the guard it names is removed. That
is not a style preference: the previous round of this suite stayed green while
the anachronism guard, the column binding, the ambiguity branch and two whole
checks were deleted one at a time.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ingest.trackers.findings import FindingKind, _fund_of, _period_end
from ingest.trackers.read import TrackerMark, TrackerSheet, Tranche
from ingest.trackers.reconcile import reconcile
from tests.tracker_helpers import (
    _VALUATION_KINDS,
    _kinds,
    _priced,
    _sheet,
    _tranche,
    _unpriced,
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


# ── the second reviewer's findings, from a different model family ────────
def test_a_synthesised_figure_does_not_buy_silence() -> None:
    """The Mom Project's mark is reproducible, and still unexplained.

    500,000 shares at 5.00 plus the 250,000 note at cost is 2,750,000 — the
    carried mark to the dollar. That is a coincidence worth reporting, not a
    verification: no row states 500,000 shares at 5.00. The 5.00 lot covers
    100,000 of them; the other 400,000 were bought at 2.50. The figure is
    synthesised by repricing shares nothing repriced, and by assuming a note
    with no stated price is worth exactly its cost.

    Reproducing a mark that way is fine for RAISING a question. Letting it
    ANSWER one is how a number this reader invented becomes an audit
    conclusion — so the finding stands, and the detail names every assumption.
    """
    mom = [
        _priced("The Mom Project", "1000000", "2.5", "400000", "4/23/2020", fund="Fund I"),
        _priced("The Mom Project", "500000", "5", "100000", "9/15/2021", fund="Fund I"),
        _unpriced("The Mom Project", "250000", "3/22/2023", fund="Fund I"),
    ]
    sheet = _sheet(
        "Fund I Holdings by Year",
        "The Mom Project",
        {"FY2021": "2500000", "FY2023": "2750000"},
        cost="1750000",
    )
    findings = [f for f in reconcile([sheet], mom) if f.kind in _VALUATION_KINDS]
    # The precise kind matters: this mark IS reproduced, just not by anything
    # the workbooks state. An auditor asks the fund to confirm a treatment here,
    # and to send a valuation memo for a mark with no support at all. One kind
    # for both cannot tell them which letter to write.
    assert [f.kind for f in findings] == [FindingKind.MARK_BASIS_ASSUMES_AN_UNSTATED_TREATMENT] * 2
    assert {f.subject.split(" · ")[1] for f in findings} == {"FY2021", "FY2023"}
    # The detail must disclose what was assumed to reach the figure, not just
    # print it. A synthesised number that reads like a quoted one is worse than
    # no number at all.
    assert "reprices shares bought at other prices" in findings[1].detail
    assert "no share price, carried at its own cost" in findings[1].detail


def test_one_purchase_price_across_one_price_is_not_a_repricing() -> None:
    """The counterweight. When every held lot was bought at the same price, the
    implied figure is arithmetic on stated rows rather than a synthesis, and a
    mark that matches it reconciles genuinely. Treating that as unexplained
    would make the check fire on everything and mean nothing."""
    sheet = _sheet("Fund II", "X", {"25Q4": "4000"})
    tranches = [
        _priced("X", "2000", "20", "100", "1/1/2024"),
        _priced("X", "2000", "20", "100", "5/30/2025"),
    ]
    assert not _VALUATION_KINDS & set(_kinds([sheet], tranches))


def test_a_position_with_no_priced_lot_at_all_is_still_checked() -> None:
    """Moonfare: one investment of 1,000,000 with no share price and no share
    count, carried at 1,048,515. Nothing in the workbooks implies that value —
    and the position was skipped entirely rather than reported, because the
    fact layer returned nothing when no held lot carried a price."""
    sheet = _sheet("Fund II", "Moonfare", {"24Q4": "1048515"})
    lots = [_unpriced("Moonfare", "1000000", "3/17/2023")]
    findings = [f for f in reconcile([sheet], lots) if f.kind in _VALUATION_KINDS]
    assert [f.kind for f in findings] == [FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS]
    assert findings[0].stated == Decimal("1048515")
    assert findings[0].computed == Decimal("1000000")


def test_a_single_priced_lot_position_is_not_exempt_from_the_basis_check() -> None:
    """The two-lot scope boundary belongs only to questions that need a LATER
    purchase to compare against an earlier one. A lone purchase of 100 shares at
    10.00 for 1,000, marked at 1,500, is exactly as unexplained — and every mark
    check used to skip it."""
    sheet = _sheet("Fund II", "X", {"25Q4": "1500"})
    lots = [_priced("X", "1000", "10", "100", "1/1/2024")]
    findings = [f for f in reconcile([sheet], lots) if f.kind in _VALUATION_KINDS]
    assert [f.kind for f in findings] == [FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS]
    assert findings[0].computed == Decimal("1000")


def test_a_mark_the_workbooks_cannot_reproduce_is_still_reported() -> None:
    """The companion to the test above: dropping the note from the implied
    figure must not be fixed by dropping the check. Move the FY2023 mark off the
    reproducible total and the finding returns."""
    mom = [
        _priced("The Mom Project", "1000000", "2.5", "400000", "4/23/2020", fund="Fund I"),
        _priced("The Mom Project", "500000", "5", "100000", "9/15/2021", fund="Fund I"),
        _unpriced("The Mom Project", "250000", "3/22/2023", fund="Fund I"),
    ]
    sheet = _sheet("Fund I Holdings by Year", "The Mom Project", {"FY2023": "4000000"})
    findings = [f for f in reconcile([sheet], mom) if f.kind in _VALUATION_KINDS]
    assert [f.kind for f in findings] == [FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS]
    assert findings[0].computed == Decimal("2750000")
    assert "no share price" in findings[0].detail


def test_an_undateable_period_stops_the_check_rather_than_the_guard() -> None:
    """A label like `Q4 2024` returned None from _period_end, and skipping the
    guard rather than the comparison silently re-enabled the anachronism it
    exists to prevent."""
    sheet = TrackerSheet(
        fund_label="Fund II",
        period_labels=["Q4 2024"],
        companies=["Fluidstack"],
        cost_basis={},
        marks=[TrackerMark("Fluidstack", "Q4 2024", Decimal("1000000"))],
        stated_totals={"Q4 2024": Decimal("1000000")},
    )
    tranches = [
        _priced("Fluidstack", "1000000", "10", "100000", "10/10/2024"),
        _priced("Fluidstack", "1500000", "15", "100000", "5/30/2025"),
    ]
    kinds = [f.kind for f in reconcile([sheet], tranches)]
    assert FindingKind.UNRECOGNISED_PERIOD_LABEL in kinds
    assert FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS not in kinds


def test_an_imprecise_tranche_date_is_not_treated_as_definitely_earlier() -> None:
    """`low > measured` accepted a tranche whose range merely STARTS before the
    measurement date. held_by() answers the three-state question the range was
    built for."""
    sheet = TrackerSheet(
        fund_label="Fund II Holdings by Quarter",
        period_labels=["FY2021"],
        companies=["X"],
        cost_basis={"X": Decimal("1400000")},
        marks=[TrackerMark("X", "FY2021", Decimal("1000000"))],
        stated_totals={"FY2021": Decimal("1000000")},
    )
    tranches = [
        _priced("X", "500000", "1", "500000", "1/1/2019"),
        _priced("X", "900000", "9", "100000", "2020 / 2021 / 2023"),
    ]
    findings = reconcile([sheet], tranches)
    # No claim about the mark — the second lot's cell spans FY2021's year end,
    # so whether it was held then is genuinely not knowable from the source.
    assert not _VALUATION_KINDS & {f.kind for f in findings}
    # And the fact that it could not be determined is itself reported, because
    # a comparison that did not happen must not read as a comparison that
    # agreed. Silence here is what the whole layer exists to prevent.
    assert [f.kind for f in findings] == [FindingKind.HOLDING_AT_DATE_UNDECIDABLE]


def test_the_same_company_in_two_funds_is_not_merged() -> None:
    """Fund identity was discarded, so both correct fund-level costs would be
    reported as disagreeing with a merged global total."""
    fund_ii = TrackerSheet(
        fund_label="Fund II Holdings by Quarter",
        period_labels=[],
        companies=["X"],
        cost_basis={"X": Decimal("2000000")},
        marks=[],
    )
    fund_i = TrackerSheet(
        fund_label="Fund I Holdings by Year",
        period_labels=[],
        companies=["X"],
        cost_basis={"X": Decimal("1000000")},
        marks=[],
    )
    a = _tranche("Fund", "2000000")
    b = Tranche(
        company="X",
        fund="Fund I",
        kind="Fund",
        investment=Decimal("1000000"),
        entry_valuation=None,
        share_price=None,
        share_count=None,
        acquired=None,
    )
    assert reconcile([fund_ii, fund_i], [a, b]) == []


# ── the third review round: one test per guard, each able to go red ──────
def test_a_fund_numeral_ends_at_a_word_boundary() -> None:
    """`"Fund III".startswith("Fund II")` is true, so every fund numbered above
    II collapsed onto a lower one — III onto II, IV onto I — and two funds' costs
    were compared as though they were one."""
    assert _fund_of("Fund II Holdings by Quarter") == "Fund II"
    assert _fund_of("Fund I Holdings by Year") == "Fund I"
    assert _fund_of("Fund III") == "Fund III"
    assert _fund_of("Fund III Holdings by Quarter") == "Fund III"
    assert _fund_of("Fund IV") == "Fund IV"
    # A label naming two funds is not the first of them. Answering `Fund I`
    # here joins a combined figure against one fund's tranches and reports the
    # difference as a discrepancy; returning the raw label joins with nothing
    # and surfaces as never-compared, which is loud and true.
    assert _fund_of("Fund I / Fund II Combined") == "Fund I / Fund II Combined"
    assert _fund_of(None) is None


def test_marks_are_not_merged_across_funds() -> None:
    """The cost path was keyed by (fund, company); the marks path was left
    unkeyed. Each fund must see only its own sheet.

    The fixture has to be able to TELL. An earlier version gave each fund a mark
    equal to its own stated cost basis, which a later fix then treated as
    supported — so cross-fund leakage produced no finding and the test passed
    while the sheet lookup was fund-blind. Now each fund produces exactly one
    finding, at its own period, and leakage doubles that to four.
    """
    fund_i = _sheet("Fund I Holdings by Year", "Acme", {"FY2025": "6000"}, cost="4000")
    fund_ii = _sheet("Fund II Holdings by Quarter", "Acme", {"25Q4": "8000"}, cost="6000")
    tranches = [
        _priced("Acme", "1000", "10", "100", "1/1/2023", fund="Fund I"),
        _priced("Acme", "3000", "30", "100", "1/1/2024", fund="Fund I"),
        _priced("Acme", "2000", "20", "100", "1/1/2023", fund="Fund II"),
        _priced("Acme", "4000", "40", "100", "1/1/2024", fund="Fund II"),
    ]
    findings = [f for f in reconcile([fund_i, fund_ii], tranches) if f.kind in _VALUATION_KINDS]
    # Count, not set: leakage produces a DUPLICATE subject, and a set would
    # quietly absorb it — the same shape of mistake as the bug under test.
    assert len(findings) == 2
    assert {f.subject for f in findings} == {"Acme · FY2025", "Acme · 25Q4"}


def test_a_mark_equal_to_total_cost_including_an_unpriced_lot_is_held_at_cost() -> None:
    """Cost summed over the priced lots only understates it, so a mark sitting
    exactly on total cost fell through to "matches neither cost nor any purchase
    price" — a false statement about a figure that reconciles exactly. The kind
    is the assertion here: this is at-cost, not an unverifiable basis."""
    sheet = _sheet("Fund II", "X", {"25Q4": "3500"})
    tranches = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "2000", "20", "100", "5/30/2025"),
        _unpriced("X", "500", "1/1/2024"),
    ]
    findings = [f for f in reconcile([sheet], tranches) if f.kind in _VALUATION_KINDS]
    assert [f.kind for f in findings] == [FindingKind.MARK_AT_COST_DISAGREES_WITH_PURCHASE_PRICES]
    # 200 shares at 20.00, plus the 500 note carried at its own cost.
    assert findings[0].computed == Decimal("4500")


def test_a_small_position_is_governed_by_the_relative_test() -> None:
    """The absolute floor is the SMALLER of the two thresholds, not the only
    one. A flat 1,000 floor would let a 100 gap on a 4,000 position pass, which
    is 2.5% of the holding."""
    sheet = _sheet("Fund II", "X", {"25Q4": "3900"})
    tranches = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "2000", "20", "100", "5/30/2025"),
    ]
    findings = [f for f in reconcile([sheet], tranches) if f.kind in _VALUATION_KINDS]
    assert [f.kind for f in findings] == [FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS]
    assert findings[0].difference == Decimal("100")


def test_an_undecidable_order_does_not_silence_a_mark_sitting_on_cost() -> None:
    """An ordinary month-only follow-on made "which is most recent" undecidable,
    and the check abandoned the whole company — so a mark carried at exactly cost
    was never reported. The at-cost fact holds whichever purchase came last, so
    it is reported, and the ambiguity is reported alongside it rather than
    instead of it."""
    sheet = _sheet("Fund II", "X", {"25Q4": "2500000"})
    tranches = [
        _priced("X", "1000000", "10", "100000", "5/10/2025"),
        _priced("X", "1500000", "15", "100000", "5/2025"),
    ]
    kinds = _kinds([sheet], tranches)
    assert FindingKind.LATEST_PURCHASE_IS_AMBIGUOUS in kinds
    assert FindingKind.MARK_AT_COST_DISAGREES_WITH_PURCHASE_PRICES in kinds


def test_ambiguity_is_reported_only_when_it_changes_an_answer() -> None:
    """Two lots on the same day at the same price are not ambiguous in any way
    that matters. Reporting them buried real findings, and the `continue` that
    followed suppressed the at-cost finding this fixture must still produce."""
    sheet = _sheet("Fund II", "X", {"25Q4": "5000"})
    tranches = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "2000", "20", "100", "5/30/2025"),
        _priced("X", "2000", "20", "100", "5/30/2025"),
    ]
    kinds = _kinds([sheet], tranches)
    assert FindingKind.LATEST_PURCHASE_IS_AMBIGUOUS not in kinds
    assert FindingKind.MARK_AT_COST_DISAGREES_WITH_PURCHASE_PRICES in kinds


def test_a_conflicting_order_still_suppresses_a_claim_it_would_change() -> None:
    """The counterweight to the two tests above. When the ordering genuinely
    decides whether there is a gap at all, no claim may be made — otherwise
    "report it under every ordering" degrades into "report it under one"."""
    # Carried at 2,000, which is cost. Across the 200 shares held, the 5/10
    # purchase implies 4,000 and the May purchase implies exactly the 2,000
    # carried — so whether there is any gap at all depends on which came last.
    sheet = _sheet("Fund II", "X", {"25Q4": "2000"})
    tranches = [
        _priced("X", "1000", "20", "100", "5/10/2025"),
        _priced("X", "1000", "10", "100", "5/2025"),
    ]
    kinds = _kinds([sheet], tranches)
    assert FindingKind.LATEST_PURCHASE_IS_AMBIGUOUS in kinds
    assert not _VALUATION_KINDS & set(kinds)


def test_an_absolute_gap_is_reported_however_large_the_position() -> None:
    """A purely relative threshold scales with the position, so 0.1% of a
    60,000,000 mark swallowed a 40,000 gap — a number an auditor chases on a
    named holding."""
    # Both lots at the same price, so `repriced` is false and materiality is
    # genuinely what decides. With differing prices the repricing rule reports
    # the mark regardless, and this test would pass without the floor existing.
    sheet = _sheet("Fund II", "X", {"25Q4": "59960000"})
    tranches = [
        _priced("X", "30000000", "25", "1200000", "1/1/2024"),
        _priced("X", "30000000", "25", "1200000", "5/30/2025"),
    ]
    findings = [f for f in reconcile([sheet], tranches) if f.kind in _VALUATION_KINDS]
    assert [f.kind for f in findings] == [FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS]
    assert findings[0].difference == Decimal("40000")


def test_rounding_noise_is_still_not_a_finding() -> None:
    """The absolute floor must not turn every cent into a finding — the relative
    test still governs small positions."""
    # Both lots at the same price, so the implied 4,000 is stated arithmetic
    # rather than a repricing and materiality is what decides. The mark is one
    # dollar off — 0.025% of the position, and the relative test governs because
    # it is the smaller of the two thresholds on a position this size.
    sheet = _sheet("Fund II", "X", {"25Q4": "3999"})
    tranches = [
        _priced("X", "2000", "20", "100", "1/1/2024"),
        _priced("X", "2000", "20", "100", "5/30/2025"),
    ]
    assert not _VALUATION_KINDS & set(_kinds([sheet], tranches))


def test_a_purchase_with_no_readable_date_is_reported_not_valued() -> None:
    """An undated lot was excluded from the ordering but still had its shares
    valued at another lot's price, and its cost counted — so a mark was compared
    against a figure nothing showed it followed."""
    sheet = _sheet("Fund II", "X", {"24Q4": "3000"})
    tranches = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "2000", "20", "100", "sometime later"),
    ]
    kinds = _kinds([sheet], tranches)
    assert FindingKind.PURCHASE_DATE_UNREADABLE in kinds
    # An undated lot is one nothing can be shown to follow, so it remains a
    # candidate for "most recent" and the ordering stays undecided. Dropping it
    # from the candidates instead would quietly hand the title to the dated lot.
    assert FindingKind.LATEST_PURCHASE_IS_AMBIGUOUS in kinds
    assert not _VALUATION_KINDS & set(kinds)


def test_a_held_at_cost_finding_never_claims_a_direction_it_did_not_compute() -> None:
    """The detail said the later purchase "implies a higher value" without ever
    checking, and printed it next to a lower number."""
    sheet = _sheet("Fund II", "X", {"25Q4": "3000"})
    tranches = [
        _priced("X", "2000", "20", "100", "1/1/2024"),
        _priced("X", "1000", "10", "100", "5/30/2025"),
    ]
    findings = [f for f in reconcile([sheet], tranches) if f.kind in _VALUATION_KINDS]
    assert [f.kind for f in findings] == [FindingKind.MARK_AT_COST_DISAGREES_WITH_PURCHASE_PRICES]
    assert findings[0].computed == Decimal("2000")
    assert findings[0].stated == Decimal("3000")
    assert "higher" not in findings[0].detail


# ── round 4: four ways the previous round's fixes were wrong ─────────────
def test_a_mark_at_cost_with_no_priced_purchase_held_does_not_crash() -> None:
    """`max()` on an empty candidate list raised ValueError and aborted the
    ENTIRE reconciliation — every finding for every company lost, not one.

    At 24Q4 only the unpriced lot is held; both priced purchases are still in
    the future, so there is no later purchase to be carried at cost against."""
    sheet = _sheet("Fund II", "X", {"24Q4": "500"})
    lots = [
        _unpriced("X", "500", "1/1/2024"),
        _priced("X", "1000", "10", "100", "5/1/2025"),
        _priced("X", "2000", "20", "100", "1/1/2026"),
    ]
    assert not _VALUATION_KINDS & set(_kinds([sheet], lots))


def test_a_quarter_digit_outside_one_to_four_is_not_a_period() -> None:
    """`25Q5` parsed as a fifth quarter ending 2026-03-31 and `25Q0` as one
    ending 2024-12-31, so a typo in a header moved the measurement date across a
    year boundary and compared a mark against the wrong year's purchases."""
    assert _period_end("25Q5") is None
    assert _period_end("25Q0") is None
    assert _period_end("25Q4") == date(2025, 12, 31)
    assert _period_end("25Q1") == date(2025, 3, 31)


def test_two_funds_in_one_label_are_caught_without_the_word_repeated() -> None:
    """`Fund I & II Combined` names two funds but writes `Fund` once, so
    counting occurrences of the full pattern saw only the first and answered
    `Fund I` — joining a combined figure against one fund's tranches."""
    assert _fund_of("Fund I & II Combined") == "Fund I & II Combined"
    assert _fund_of("Fund I and II") == "Fund I and II"
    assert _fund_of("Fund I, II") == "Fund I, II"
    assert _fund_of("Fund II Holdings by Quarter") == "Fund II"


def test_a_mark_a_fraction_off_cost_is_not_an_unexplained_basis() -> None:
    """Letting `repriced` bypass materiality entirely reported a mark one cent
    from total cost as a basis nothing supports. It is at cost, to within the
    rounding this layer already declines to chase."""
    sheet = _sheet("Fund II", "X", {"25Q4": "3000.01"})
    tranches = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "2000", "20", "100", "5/30/2025"),
    ]
    assert FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS not in _kinds([sheet], tranches)


def test_a_finding_never_claims_the_workbooks_lack_what_it_did_not_read() -> None:
    """The reader drops rows with no numeric investment, including the
    documentation line that states The Mom Project's basis. Saying the basis is
    "not stated in these workbooks" asserts something about rows this code
    never looked at."""
    sheet = _sheet("Fund II", "X", {"25Q4": "9999"})
    tranches = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "2000", "20", "100", "5/30/2025"),
    ]
    findings = [f for f in reconcile([sheet], tranches) if f.kind in _VALUATION_KINDS]
    assert len(findings) == 1
    # The trackers do not state it — but the fund supplied a documentation pack
    # alongside them, so the finding must point at the evidence to obtain rather
    # than imply none was provided.
    assert "no row in these trackers states that basis" in findings[0].detail
    assert "the supporting document is the evidence to obtain" in findings[0].detail
    assert "not stated in these workbooks" not in findings[0].detail


def test_an_undecided_ordering_does_not_buy_a_basis_claim_either() -> None:
    """The mirror of `test_a_synthesised_figure_does_not_buy_silence`.

    Lots 100@$10 on 5/10/2025 and 100@$20 in 5/2025 overlap, so which came last
    is undecided. A 2,000 mark equals what the $10 lot implies exactly. Saying
    it "matches no purchase price" is false under a reading the source still
    permits — and the at-cost check, given identical facts, refuses to claim.
    The repricing rule overrides materiality; it must not override ordering.
    """
    sheet = _sheet("Fund II", "X", {"25Q4": "2000"})
    tranches = [
        _priced("X", "1000", "10", "100", "5/10/2025"),
        _priced("X", "2000", "20", "100", "5/2025"),
    ]
    kinds = _kinds([sheet], tranches)
    assert FindingKind.LATEST_PURCHASE_IS_AMBIGUOUS in kinds
    # No valuation claim of ANY kind. Naming one kind here let the finding come
    # back under the other one after the basis kinds were split.
    assert not _VALUATION_KINDS & set(kinds)


def test_a_decided_ordering_still_reports_a_synthesised_match() -> None:
    """The counterweight: The Mom Project's shape. One candidate, so the
    ordering is decided, and the exact synthesised match still reports."""
    sheet = _sheet("Fund II", "X", {"25Q4": "3000"})
    tranches = [
        _priced("X", "1000", "10", "100", "1/1/2024"),
        _priced("X", "1000", "20", "100", "5/30/2025"),
    ]
    findings = [f for f in reconcile([sheet], tranches) if f.kind in _VALUATION_KINDS]
    assert [f.kind for f in findings] == [FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS]
    assert findings[0].computed == Decimal("4000")


def test_a_mark_a_fraction_off_cost_is_still_carried_at_cost() -> None:
    """The other half of the at-cost/basis boundary.

    Round 4 replaced exact equality with materiality on both sides so a mark a
    fraction off cost could not fall between the two checks and be claimed by
    neither. Only the basis half got a test: swapping the at-cost check back to
    `amount != facts.cost` left the suite green, so the fix was undefended in
    the direction it was actually made.
    """
    sheet = _sheet("Fund II", "X", {"25Q2": "2500000.50"})
    tranches = [
        _priced("X", "1000000", "10", "100000", "10/10/2024"),
        _priced("X", "1500000", "15", "100000", "5/30/2025"),
    ]
    findings = [f for f in reconcile([sheet], tranches) if f.kind in _VALUATION_KINDS]
    assert [f.kind for f in findings] == [FindingKind.MARK_AT_COST_DISAGREES_WITH_PURCHASE_PRICES]
    assert findings[0].computed == Decimal("3000000")
