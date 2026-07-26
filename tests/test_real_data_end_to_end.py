"""The real 14 positions, from the workbooks to the packet and into the ledger.

Gate D1. Before this file, `grep -rl read_valuation_tracker` returned the reader
and its own test: the contracts, the database and the packet API had only ever
been handed `fixtures/dream.py`, which was written by hand to fit the contracts.
A fixture shaped to fit a contract cannot test that contract, so three of the
five pipeline layers were untested rather than passing.

What these tests assert is deliberately mixed. Some record that something works.
Most record that something is **lost**: a field the contract demands and the
source does not state, a row the contract cannot hold, a figure the database
accepts that nothing in the corpus supports. Those assertions are the
deliverable. If one starts failing because the loss was fixed, delete it and say
so in `.captain/review/triage/d1-real-data-end-to-end.md`; if one starts failing
because the mapper learned to invent more confidently, that is the regression
this file exists to catch.

The workbook tests skip when the fund's private case-study material is absent,
exactly as `tests/test_tracker_ingest.py` does, and the database tests skip
without a DSN. The mapper tests that need neither run everywhere.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from ingest.trackers.read import (
    SheetNote,
    TrackerMark,
    TrackerSheet,
    read_master_breakdown,
    read_master_notes,
    read_valuation_tracker,
)
from ingest.trackers.to_contracts import (
    Mapped,
    map_workbooks,
)
from ingest.trackers.to_lots import ASSUMED_CURRENCY, ASSUMED_SECURITY_CLASS
from packages.contracts.enums import AuditScope, RequirementCode
from packages.contracts.fixtures.dream import dream_packet
from packages.contracts.models import TotalKind
from tests.tracker_helpers import MASTER, VALUATION, _sheet, _tranche, needs_workbooks

GENERATED_AT = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

#: The tracker's tab names, as `map_workbooks` keys them.
_FUND_OF_SHEET = {
    "Fund II Holdings by Quarter": "fund_ii",
    "Fund I Holdings by Year": "fund_i",
}


def _mapped() -> Mapped:
    # The breakdown's prose lines are an argument, not an option: without them
    # every position reads as direct equity with an unstated security class,
    # which is where this started and what the policy layer could not use.
    return map_workbooks(
        read_valuation_tracker(VALUATION),
        read_master_breakdown(MASTER),
        GENERATED_AT,
        read_master_notes(MASTER),
    )


# ── the shape of the mapper, checkable with no workbook ──────────────────
def test_a_date_range_is_refused_only_when_the_day_would_decide_held_at_date() -> None:
    """Jio's cell says `7/2020`, a month. `Lot.acquired_date` is a required
    `date`, so the range has nowhere to go.

    Refusing outright cost more than it saved: the lot vanished, held-at-date
    had nothing to ask about a live $1,000,000 position, and `api/ledger.py`
    carried a fallback so it would not drop out of every Fund I total. The
    invented day only MATTERS when a measurement date falls inside the range —
    that is the case where it decides the answer (INV-7). Both branches are
    asserted here, because a rule that accepts everything passes the first."""
    sheet = _sheet("Fund II Holdings by Quarter", "X", {"25Q4": "1000"}, cost="1000")
    outside = map_workbooks([sheet], [_tranche("Fund", "1000", text="7/2020")], GENERATED_AT)
    assert [lot.acquired_date for lot in outside.lots] == [date(2020, 7, 1)]
    assert [s.subject for s in outside.substituted("Lot.acquired_date")] == ["X lot 1"]

    # `2020 / 2021 / 2023` spans 2020-01-01..2023-12-31, and FY2022 — a real
    # Fund I measurement date — falls inside it. Here the day chosen decides
    # whether the position was held at that date, so the lot is still refused
    # and the refusal is still counted.
    straddling = _sheet("Fund I Positions", "X", {"FY2022": "1000"}, cost="1000")
    inside = map_workbooks(
        [straddling],
        [_tranche("Fund", "1000", text="2020 / 2021 / 2023", fund="Fund I")],
        GENERATED_AT,
    )
    assert inside.lots == []
    assert [r.subject for r in inside.refused("Lot.acquired_date")] == [
        "X lot 1 (2020 / 2021 / 2023)"
    ]


def test_a_row_kind_the_reader_does_not_recognise_becomes_no_lot() -> None:
    """`is_recognised` has no third state between investment and exit, so an
    unfamiliar kind becomes a finding rather than a guess. The money leaves no
    trace, so the drop is recorded rather than inferred from a count.

    `Indirect Fund` used to be the example and is now recognised — the word
    `fund` appears and where it appears in the phrase was never the
    distinction. A genuinely unfamiliar kind still refuses."""
    sheet = _sheet("Fund II Holdings by Quarter", "X", {"25Q4": "1000"})
    mapped = map_workbooks([sheet], [_tranche("Warrant Exercise", "1000000")], GENERATED_AT)
    assert mapped.lots == []
    assert "1,000,000 of stated investment" in mapped.refused("Lot")[0].detail


def test_a_feeder_subscription_is_an_investment_wherever_the_word_sits() -> None:
    """Jio's row kind is `Indirect Fund`, and `startswith("fund")` missed it.

    A live $1,000,000 feeder position became no lot at all, held-at-date had
    nothing to ask, and `api/ledger.py` carried a fallback so it would not drop
    out of every Fund I total — as it had once before. Asserted without the
    workbooks, because the real position that proves it is in the fund's
    private material and a guard proved only there is not proved.
    """
    sheet = _sheet("Fund II Holdings by Quarter", "X", {"25Q4": "1000"}, cost="1000")
    row = _tranche("Indirect Fund", "1000000", text="1/1/2020", price="10", count="100")
    assert row.is_investment is True
    assert row.is_recognised is True
    m = map_workbooks([sheet], [row], GENERATED_AT)
    assert [lot.cost.amount for lot in m.lots] == [Decimal(1000000)]
    assert m.refused("Lot") == []
    # An exit still wins, so a row naming both does not become a purchase.
    assert _tranche("Exit — Fund", "1000").is_investment is False


def test_a_recapitalisation_row_becomes_a_conversion_not_a_silent_reclass() -> None:
    """Sway's recap changes which class the fund holds, at a date.

    INV-17 compares the class HELD against the class PRICED, so a lot flattened
    to one immutable class reads as cross-class forever — post-recap the two
    are the same class and Sway is not. The exchange ratio is derived from the
    two share counts the workbook states rather than read from a cell, because
    no cell states it."""
    sheet = _sheet("Fund II Holdings by Quarter", "X", {"25Q4": "1000"}, cost="1000")
    lot = _tranche("Fund", "2000000", text="10/18/2023", price="2.5", count="800000")
    notes = [
        SheetNote(
            company="X",
            fund="Fund II",
            text="Post-Recap",
            source_sheet="X",
            ordinal=1,
            cells=("Post-Recap", None, "$10M", 0.4, 875000, "9/30/2025"),
        ),
        SheetNote(
            company="X",
            fund="Fund II",
            text="X - Series A-3 Recapitalization - Pro Forma Cap Table (September 30, 2025)",
            source_sheet="X",
            ordinal=2,
            cells=(),
        ),
    ]
    m = map_workbooks([sheet], [lot], GENERATED_AT, notes)
    assert len(m.conversions) == 1
    conversion = m.conversions[0]
    assert conversion.to_security_class == "series_a3"
    assert conversion.to_shares == Decimal(875000)
    # 800,000 x 1.09375 = 875,000 exactly. A ratio producing a fractional share
    # count fails rather than rounding into a plausible number (V13).
    assert conversion.exchange_ratio == Decimal("1.09375")
    assert conversion.exchange_ratio * Decimal(800000) == Decimal(875000)


def test_a_holding_with_no_assessments_is_unsupported_rather_than_clean() -> None:
    """The load-bearing default. The workbooks carry no evidence at all, so the
    mapper attaches no assessments — and `HoldingRow.supported` must then be
    False for the reason "not assessed", not True for lack of a complaint."""
    sheet = _sheet("Fund II Holdings by Quarter", "X", {"25Q4": "1000"})
    row = map_workbooks([sheet], [], GENERATED_AT).packets[0].rows[0]
    assert row.supported is False
    assert row.unsupported_reasons == {
        RequirementCode.R1: "not assessed",
        RequirementCode.R2: "not assessed",
    }


# ── the real workbooks reach the contract layer ──────────────────────────
@needs_workbooks
def test_all_fourteen_positions_and_twelve_fund_periods_map() -> None:
    """The headline of Gate D1: every real position builds a contract model."""
    m = _mapped()
    assert len(m.holdings) == 14
    assert len(m.periods) == 12
    assert len(m.marks) == 72
    # Six, not twelve. SPEC 2 closes the packet date set; the other six
    # fund-periods are ingested and appear in the ledger as `lineage_only`.
    assert len(m.packets) == 6
    assert {p.period.label for p in m.packets} == {
        "23Q4",
        "24Q4",
        "25Q4",
        "FY2023",
        "FY2024",
        "FY2025",
    }
    assert {p.fund_id for p in m.packets} == {"fund_i", "fund_ii"}


@needs_workbooks
def test_seventeen_of_the_eighteen_tranches_become_lots() -> None:
    """One does not, and correctly: Jackpocket's Exit row is proceeds, not a
    purchase, so it becomes a realisation date rather than a lot.

    It was two. Jio's `Indirect Fund` row became nothing at all, because
    `Tranche.is_investment` matched `startswith("fund")` — so a live $1,000,000
    feeder position reached the ledger with no lot, held-at-date had nothing to
    ask, and `api/ledger.py` carried a fallback to stop it vanishing from every
    Fund I total, as it had once before."""
    m = _mapped()
    assert len(read_master_breakdown(MASTER)) == 18
    assert len(m.lots) == 17
    assert [lot.id for lot in m.lots if lot.realized_date] == ["fund_ii_jackpocket_1"]
    assert [lot.realized_date for lot in m.lots if lot.realized_date] == [date(2024, 5, 20)]


@needs_workbooks
def test_jio_joins_on_the_company_the_label_names_not_on_the_label() -> None:
    """The tracker calls it `Jio (Indirect)`; the master breakdown sheet is
    `Jio`. The raw strings never met, so 1,000,000 of stated investment reached
    no holding at all and was reported from both ends of a join that had simply
    missed. `company_key` joins them.

    The tracker's own words are kept on the holding. `(Indirect)` is one of the
    two signals in either workbook that this is a feeder rather than a direct
    position, so the key normalises and the label does not — and the position
    type is read off the `Type` cell, which says `Indirect Fund`.

    Its lot used to be refused twice over: once because `Indirect Fund` did not
    match `startswith("fund")`, once because `7/2020` names a month rather than
    a day. So a live $1,000,000 feeder position reached the ledger with no lot
    at all. Both are read now, and the money leaves a trace."""
    m = _mapped()
    assert m.refused("Holding") == []
    assert m.refused("Lot") == []
    jio = next(h for h in m.holdings if h.id == "fund_i_jio_indirect")
    assert jio.company_name == "Jio (Indirect)"
    assert jio.position_type.value == "indirect_feeder"
    assert [
        (lot.security_class, lot.cost.amount) for lot in m.lots if lot.holding_id == jio.id
    ] == [("lp_interest", Decimal(1000000))]
    assert len([mk for mk in m.marks if mk.holding_id == jio.id]) == 5


def test_a_single_exit_selling_the_whole_position_realises_every_lot() -> None:
    """One sale of the entire position leaves nothing to allocate.

    `_realised_date` also required a single purchase lot, so the ordinary shape —
    one exit against two tranches — was refused as unallocatable and every lot
    reached the ledger with `realized_date` null, reading as still held. The
    packet then carried the position at every later measurement date, and
    `check_realisations_are_allocatable` stays silent on a full exit because the
    allocation genuinely is invariant. A position sold in March 2024, reported as
    held at 24Q4 and 25Q4, with nothing anywhere saying otherwise.

    FIFO, specific identification and pro-rata all agree when everything is
    sold, so this is forced rather than chosen — and it is recorded as a
    substitution regardless."""
    sheet = _sheet(
        "Fund II Holdings by Quarter", "X", {"24Q4": "2000", "25Q4": "2000"}, cost="2000"
    )
    lots = [
        _tranche("Fund", "1000", text="1/1/2023", price="10", count="100"),
        _tranche("Fund", "1000", text="6/1/2023", price="10", count="100"),
        _tranche("Exit", "5000", text="3/1/2024", price="25", count="200"),
    ]
    m = map_workbooks([sheet], lots, GENERATED_AT)
    assert {lot.realized_date for lot in m.lots} == {date(2024, 3, 1)}
    assert m.refused("Lot.realized_date") == []
    assert [s.field_path for s in m.substituted("Lot.realized_date")] == ["Lot.realized_date"]
    for packet in m.packets:
        assert [row.held_at_date for row in packet.rows] == [False]
        assert packet.totals().amount.amount == Decimal(0)


def test_a_partial_exit_is_still_refused_rather_than_allocated() -> None:
    """The direction the fix above must not take with it. When the sale does not
    consume the position, which lot it came out of decides what remains, and the
    workbooks name no allocation method — so nothing is chosen and the refusal
    stands."""
    sheet = _sheet("Fund II Holdings by Quarter", "X", {"25Q4": "2000"}, cost="2000")
    lots = [
        _tranche("Fund", "1000", text="1/1/2023", price="10", count="100"),
        _tranche("Fund", "1000", text="6/1/2023", price="20", count="50"),
        _tranche("Exit", "2000", text="3/1/2024", price="25", count="80"),
    ]
    m = map_workbooks([sheet], lots, GENERATED_AT)
    assert {lot.realized_date for lot in m.lots} == {None}
    assert len(m.refused("Lot.realized_date")) == 1
    # Still held: the sale left shares behind, whichever lot it consumed.
    assert [row.held_at_date for row in m.packets[0].rows] == [True]


def test_a_position_acquired_after_the_measurement_date_is_not_held_at_it() -> None:
    """Held-at-date is read from the source rows, so a row the contract layer
    cannot hold still answers the question.

    An unrecognised row becomes no lot, and a holding with no lots took the
    not-computable carve-out and recorded `True` — putting the fund's reported
    figure into a total for a position the master breakdown dates two months
    later. The row's kind is what the reader does not understand; its Date cell
    is the same column it reads everywhere else."""
    sheet = _sheet("Fund II Holdings by Quarter", "X", {"25Q4": "1000"})
    m = map_workbooks(
        [sheet], [_tranche("Warrant Exercise", "1000", text="1/1/2026")], GENERATED_AT
    )
    assert m.lots == []
    assert [row.held_at_date for row in m.packets[0].rows] == [False]
    assert m.packets[0].totals().amount.amount == Decimal(0)


def test_a_lot_dropped_for_naming_a_month_still_answers_held_at_date() -> None:
    """The other direction, and the more expensive one.

    A date cell naming a month is deliberately preserved as a range, so the lot
    is refused — `Lot.acquired_date` is a required `date`. Reading held-at-date
    off the surviving lots then answered `False` for a position the source
    places five years earlier, and the fund total silently lost it. The range
    answers `held at 2025-12-31` perfectly well; it is only a *day* it cannot
    give."""
    sheet = _sheet("Fund II Holdings by Quarter", "X", {"25Q4": "1000"}, cost="1000")
    lots = [
        _tranche("Fund", "1000", text="7/2020", price="10", count="100"),
        _tranche("Fund", "1000", text="1/1/2026", price="10", count="100"),
    ]
    m = map_workbooks([sheet], lots, GENERATED_AT)
    assert [lot.acquired_date for lot in m.lots] == [date(2020, 7, 1), date(2026, 1, 1)]
    assert [row.held_at_date for row in m.packets[0].rows] == [True]
    assert m.packets[0].totals().amount.amount == Decimal("1000")


def test_two_master_sheets_reducing_to_one_company_are_left_unjoined() -> None:
    """The same collision as the test below, on the other side of the same join.

    `company_key` is applied to the master workbook's TAB NAME at read time, so
    `Acme (US)` and `Acme (UK)` are one company before any join runs — and a
    single tracker row took both companies' lots, with no refusal and no orphan.
    `Tranche.source_sheet` keeps what the normalisation discarded so the
    multiplicity is still visible. The tracker side has refused this since it
    was written; enforcing it on one side only is this project's recurring
    defect, and here it fabricates cost."""
    sheet = _sheet("Fund II Holdings by Quarter", "Acme (US)", {"25Q4": "1000"}, cost="1000")
    lots = [
        _tranche(
            "Fund",
            "1000",
            text="1/1/2020",
            price="10",
            count="100",
            sheet="Acme (US)",
            company="Acme",
        ),
        _tranche(
            "Fund",
            "2000",
            text="1/1/2021",
            price="10",
            count="200",
            sheet="Acme (UK)",
            company="Acme",
        ),
    ]
    m = map_workbooks([sheet], lots, GENERATED_AT)
    assert m.lots == []
    assert [r.subject for r in m.refused("Lot")] == ["Acme (US)"]
    assert "more than one master-breakdown sheet names the company 'Acme'" in (
        m.refused("Lot")[0].detail
    )
    # The money is named rather than silently attached to the holding.
    assert [r.subject for r in m.refused("Holding")] == ["Fund II · Acme"]
    assert "3,000" in m.refused("Holding")[0].detail


def test_two_tracker_rows_reducing_to_one_company_are_left_unjoined() -> None:
    """The join key is a normalisation, and a normalisation can collide. Two
    tracker rows that both reduce to `X` cannot each take X's tranches without
    counting the same cost and the same lots twice, so neither takes them and
    the master rows report as orphans naming the money — louder than a
    fabricated 2,000,000."""
    sheet = TrackerSheet(
        fund_label="Fund II Holdings by Quarter",
        period_labels=["25Q4"],
        companies=["X (Series A)", "X (Series B)"],
        cost_basis={},
        marks=[TrackerMark(c, "25Q4", Decimal("1000")) for c in ("X (Series A)", "X (Series B)")],
    )
    mapped = map_workbooks([sheet], [_tranche("Fund", "1000000", text="1/1/2020")], GENERATED_AT)
    assert mapped.lots == []
    assert [r.subject for r in mapped.refused("Lot")] == ["X (Series A)", "X (Series B)"]
    assert "names the company 'X'" in mapped.refused("Lot")[0].detail
    assert [r.subject for r in mapped.refused("Holding")] == ["Fund II · X"]


@needs_workbooks
def test_held_at_date_is_read_from_the_source_rows_not_from_the_surviving_lots() -> None:
    """INV-7, and the set it is computed over.

    It used to be computed from the `Lot`s that reached the contract layer, which
    is not the same set as the rows the source states: a row of a kind the reader
    does not recognise and a lot whose date cell names a month both fail to
    become a `Lot`. So held-at-date answered with whichever rows happened to be
    contractable, and it was wrong in both directions — a position acquired after
    the measurement date read as held because its only row became no lot at all,
    and a position the source places years earlier read as NOT held because the
    lot carrying that date was dropped for naming a month. Both put a false
    figure in a fund total.

    Jio was the corpus case: its only master row is `Indirect Fund` dated
    `7/2020`, and neither survived to become a lot. Both are read now, so the
    two sets finally agree — but the rule stays source-based, because agreement
    on this corpus is not the same as the rule being right."""
    m = _mapped()
    assert m.substituted("HoldingRow.held_at_date") == []
    assert m.refused("HoldingRow.held_at_date") == []
    assert all(row.held_at_date for p in m.packets for row in p.rows)
    jio = next(h for h in m.holdings if h.company_name == "Jio (Indirect)")
    assert [lot.acquired_date for lot in m.lots if lot.holding_id == jio.id] == [date(2020, 7, 1)]


@needs_workbooks
def test_a_realisation_note_reaches_the_packet_as_nothing() -> None:
    """Jackpocket's 24Q2 cell reads `Realized 5/20/24: 3,100,000`. `Mark.reported`
    is `Money`, and neither `Mark` nor `HoldingRow` carries proceeds or a note, so
    3,100,000 of realised value appears nowhere in any packet. The position simply
    stops having rows."""
    m = _mapped()
    refusal = next(r for r in m.refused("Mark.reported"))
    assert refusal.subject == "Jackpocket · 24Q2"
    assert "3,100,000" in refusal.detail
    assert not any(
        row.mark.reported.amount == Decimal("3100000") for p in m.packets for row in p.rows
    )
    jackpocket = [
        row for p in m.packets for row in p.rows if row.holding_id == "fund_ii_jackpocket"
    ]
    assert [row.mark.period_id for row in jackpocket] == ["fund_ii_23q4"]


# ── what the contract forced the mapper to invent ────────────────────────
@needs_workbooks
def test_every_figure_in_the_packet_is_denominated_by_the_mapper() -> None:
    """No cell, header or footer in either workbook names a currency, and `Money`
    refuses to exist without one (INV-11). So the currency on all 72 marks is an
    assertion by this repository, not by the fund."""
    m = _mapped()
    assert len(m.substituted("Money.currency")) == 14
    assert {mk.reported.currency for mk in m.marks} == {ASSUMED_CURRENCY}


@needs_workbooks
def test_the_security_class_is_read_from_the_line_that_names_it() -> None:
    """Fifteen of seventeen lots get their real class from the workbook.

    Every lot used to carry the same sentinel, which meant INV-17's cross-class
    rule could never fire on ingested data — ingested data had exactly one
    class. The classes were in the breakdown's prose the whole time, in lines
    the tranche reader dropped because they carry no number.

    The one that remains is the finding, not the residue: **Anthropic's class is
    stated nowhere in the corpus** — not in either workbook, and not in the one
    document the fund holds, which is a press article.

    Dream was here too, on the rule "never read a class off a cap table". A
    cross-family review found that too coarse. Dream's table has a section
    headed "Series A-1 Preferred — Holders of Record" listing `7GC Fund II,
    L.P.` at 625,000 shares — the PRICED class is Series B at $8.00, and the
    HOLDERS-OF-RECORD section is what the fund owns. Reading the first as the
    held class collapses INV-17; reading the second is what INV-17 needs."""
    m = _mapped()
    unstated = {lot.id for lot in m.lots if lot.security_class == ASSUMED_SECURITY_CLASS}
    assert unstated == {"fund_ii_anthropic_1"}
    assert len(m.substituted("Lot.security_class")) == 1
    assert {lot.security_class for lot in m.lots} == {
        "series_b1",
        "fund_interest",
        "series_a",
        ASSUMED_SECURITY_CLASS,
        "series_a1",
        "series_b",
        "series_a2",
        "conv_note",
        "series_e",
        "lp_interest",
        "series_c",
        "common",
    }
    assert next(x.security_class for x in m.lots if x.id == "fund_ii_dream_1") == "series_a1"


@needs_workbooks
def test_the_recapitalisation_becomes_a_conversion_event() -> None:
    """Sway's `Post-Recap` row states 875,000 shares effective 9/30/2025.

    Recorded as an event rather than as an edit to the lot, so class-at-date
    stays derivable: post-recap the held class equals the class the recap cap
    table prices, and Sway is therefore NOT cross-class. A lot flattened to one
    immutable class cannot say that. The exchange ratio is derived from the two
    share counts the workbook states — 800,000 into 875,000 is 1.09375 exactly,
    which is what V13 asserts."""
    m = _mapped()
    assert len(m.conversions) == 1
    conversion = m.conversions[0]
    assert conversion.lot_id == "fund_ii_sway_1"
    assert conversion.to_security_class == "series_a3"
    assert conversion.to_shares == Decimal(875000)
    assert conversion.exchange_ratio == Decimal("1.09375")


@needs_workbooks
def test_the_three_positions_that_are_not_direct_equity_are_read_as_such() -> None:
    """All fourteen used to be `direct_equity`, and three demonstrably were not.

    That is not a cosmetic mislabel: the sufficiency matrix is keyed on position
    type, so Banzai's market quote, Jio's administrator statement and Moonfare's
    FX memo had no cell at all and the policy layer refused all three. The
    signals are in the workbook — a `Type` cell reading `Indirect Fund`, a
    `De-SPAC` row, a note about a EUR-denominated interest."""
    m = _mapped()
    typed = {h.id: h.position_type.value for h in m.holdings}
    assert typed["fund_i_jio_indirect"] == "indirect_feeder"
    assert typed["fund_i_banzai"] == "public_listed"
    assert typed["fund_ii_moonfare"] == "fx_denominated_interest"
    assert len(m.substituted("HoldingRow.position_type")) == 11

    assert any(h.company_name == "Jio (Indirect)" for h in m.holdings)


@needs_workbooks
def test_every_period_takes_its_audit_scope_from_the_spec_not_an_assumption() -> None:
    """`Packet` refuses a lineage-only period (INV-20), and the mapper used to
    declare all twelve packet-scope so the rule could never bite — which put
    26Q1, a quarter AFTER the last measurement date under audit, into the
    auditor's packet.

    The scope now comes from SPEC 2's closed date set. Nothing is assumed, so
    nothing is recorded as a substitution.
    """
    m = _mapped()
    assert m.substituted("Period.audit_scope") == []
    scopes = {p.label: p.audit_scope for p in m.periods}
    assert scopes["25Q4"] is AuditScope.PACKET
    assert scopes["FY2023"] is AuditScope.PACKET
    # Asked about by nobody: after the last measurement date, and before the
    # first fiscal year under audit.
    assert scopes["26Q1"] is AuditScope.LINEAGE_ONLY
    assert scopes["FY2021"] is AuditScope.LINEAGE_ONLY


@needs_workbooks
def test_no_mark_carries_a_basis_or_a_validated_amount() -> None:
    """`Mark.basis` is optional, so the mapper leaves it None rather than
    guessing — but that means every one of the 72 marks reaches the packet with
    no valuation basis and no independently derived figure."""
    m = _mapped()
    assert {mk.basis for mk in m.marks} == {None}
    assert {mk.validated for mk in m.marks} == {None}


# ── what the packet says, and what it cannot ─────────────────────────────
@needs_workbooks
def test_every_packet_is_entirely_unsupported() -> None:
    """72 of 72 rows, 12 of 12 packets. The workbooks contain no evidence, so
    `unsupported_amount` equals the total everywhere and `approved_fair_value`
    is unconstructible for every fund-period in the corpus."""
    m = _mapped()
    for packet in m.packets:
        totals = packet.totals()
        assert totals.unsupported_positions == sum(1 for r in packet.rows if r.held_at_date)
        assert totals.unsupported_amount == totals.amount
        assert totals.contains_unsupported_inputs is True


@needs_workbooks
def test_the_fund_ii_23q4_packet_contradicts_the_sheets_own_total() -> None:
    """`Packet.totals()` sums the rows held at the date, so it reports 6,000,000
    where the tracker footer states 4,000,000 — Jackpocket, held at 2023-12-31
    and realised five months later, which the sheet's `TOTAL (active)` row drops.
    The packet is right and the sheet is wrong, and `PacketTotals` has no field
    in which to say either: nothing on it carries the source's own total, so the
    2,000,000 disagreement is invisible to anyone reading the packet alone."""
    m = _mapped()
    packet = m.packet("fund_ii", "23Q4")
    sheet = next(s for s in read_valuation_tracker(VALUATION) if "Fund II" in s.fund_label)
    totals = packet.totals()
    assert totals.amount.amount == Decimal("6000000")
    assert sheet.stated_totals["23Q4"] == Decimal("4000000")
    assert all(row.held_at_date for row in packet.rows)
    assert "stated" not in " ".join(type(totals).model_fields)


@needs_workbooks
def test_no_fund_i_total_is_short_of_the_sheet_it_came_from() -> None:
    """The most expensive finding in this file, and it is arithmetic, not opinion.

    The tracker named the row `Jio (Indirect)` and the master breakdown sheet is
    `Jio`. The join produced nothing, so the holding had no lot; with no lot
    `held_at_date` computed False; and `Packet.totals()` excludes rows that are
    not held. Every Fund I period reported 1,000,000 less than the sheet it came
    from — a plausible, self-consistent, wrong number caused by a parenthesis
    four layers upstream, visible in `PacketTotals` only as
    `packet_gap_positions` exceeding `unsupported_positions` by one, with no
    company named and no amount attached.

    What closes the arithmetic is the second half: a holding with no lot records
    the tracker's own answer for held-at-date rather than a `False` that drops it
    from the total. Joining the two labels does not move this number at all —
    Jio's master row is an `Indirect Fund` tranche the reader does not recognise,
    so it becomes no lot either way. The join decides where the 1,000,000 is
    *reported*, not whether the total contains it, and it is defended by its own
    test above; a mutation run proves each is red on its own.

    Fund II 23Q4 still differs, in the other direction and correctly: the packet
    is 2,000,000 ABOVE the sheet, because the sheet's `TOTAL (active)` row drops
    Jackpocket, which was held at 2023-12-31 and realised five months later.
    """
    m = _mapped()
    stated = {
        (_FUND_OF_SHEET[s.fund_label], label): value
        for s in read_valuation_tracker(VALUATION)
        for label, value in s.stated_totals.items()
    }
    shortfalls = {
        (p.fund_id, p.period.label): stated[(p.fund_id, p.period.label)] - p.totals().amount.amount
        for p in m.packets
    }
    # Only the six packet-scope periods build a packet, so only those can be
    # compared. No packet is short of its sheet; the one difference is the
    # packet exceeding a sheet total that is itself wrong.
    assert shortfalls == {
        ("fund_ii", "23Q4"): Decimal("-2000000"),
        ("fund_ii", "24Q4"): Decimal(0),
        ("fund_ii", "25Q4"): Decimal(0),
        ("fund_i", "FY2023"): Decimal(0),
        ("fund_i", "FY2024"): Decimal(0),
        ("fund_i", "FY2025"): Decimal(0),
    }
    fy2025 = m.packet("fund_i", "FY2025").totals()
    assert len(m.packet("fund_i", "FY2025").rows) == 5
    # Jio is inside the total now, and inside the unsupported subtotal beside it
    # — the packet carries the million rather than dropping it.
    assert fy2025.unsupported_positions == 5
    assert fy2025.packet_gap_positions == 5
    assert fy2025.amount.amount == Decimal("5881000")
    assert fy2025.unsupported_amount == fy2025.amount


@needs_workbooks
def test_the_packet_carries_the_held_at_date_answer_but_not_its_evidence() -> None:
    """`HoldingRow.held_at_date` is a `bool` that some upstream computes from the
    source rows — and no lot is reachable from a `Packet`, so nothing downstream
    can check it, and there is no third value for the case where the source
    cannot say. That gap is still open.

    What is closed is the label. `totals()` applies the held-at-date filter
    unconditionally, so the figure it returns is never the tracker's own total —
    at any date where something was realised the two differ. Calling it
    `tracker_reported` stated something false about what the number IS, which is
    what INV-19 forbids, and it left `HELD_AT_DATE_REPORTED` unreachable while
    the oracle called the identical quantity `held_at_date_reported_total`."""
    m = _mapped()
    row = m.packet("fund_ii", "25Q4").rows[0]
    assert "lots" not in type(row).model_fields
    assert "lots" not in type(m.packets[0]).model_fields
    assert {p.totals().kind for p in m.packets} == {TotalKind.HELD_AT_DATE_REPORTED}
    assert "held at this date" in m.packets[0].totals().label


@needs_workbooks
def test_the_packet_carries_no_cost_basis_at_all() -> None:
    """Both workbooks state a cost basis per company and both state a cost total
    — and the Fund II ones disagree, 16,000,000 of cells against a stated
    14,000,000. Cost reaches the contract layer only on `Lot.cost`, which the
    packet cannot see, so R1 (existence and cost) has no figure to be about."""
    m = _mapped()
    fields = set(type(m.packet("fund_ii", "25Q4").rows[0]).model_fields)
    assert "cost" not in fields
    assert not fields & {"cost", "cost_basis", "shares", "security_class"}


@needs_workbooks
def test_the_api_serves_a_fifth_of_the_real_25q4_packet() -> None:
    """`api/routes.py` answers `fund_ii / f2_25q4` from the Dream fixture: one
    row, 5,000,000. The real Fund II 25Q4 packet is eight rows and 25,648,515.
    Gate D2 — recorded here because it took real data to make it visible."""
    real = _mapped().packet("fund_ii", "25Q4")
    served = dream_packet()
    assert real.period.period_date == served.period.period_date
    assert served.totals().amount.amount == Decimal("5000000")
    assert real.totals().amount.amount == Decimal("25648515")
    assert len(served.rows) == 1
    assert len(real.rows) == 8
