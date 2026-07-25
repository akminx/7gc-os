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
    TrackerMark,
    TrackerSheet,
    read_master_breakdown,
    read_valuation_tracker,
)
from ingest.trackers.to_contracts import (
    ASSUMED_CURRENCY,
    ASSUMED_SECURITY_CLASS,
    Mapped,
    map_workbooks,
)
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
    return map_workbooks(
        read_valuation_tracker(VALUATION), read_master_breakdown(MASTER), GENERATED_AT
    )


# ── the shape of the mapper, checkable with no workbook ──────────────────
def test_a_lot_whose_date_cell_names_a_range_is_dropped_not_guessed() -> None:
    """Jio's cell says `7/2020`. `Lot.acquired_date` is a required `date`, so a
    month the reader deliberately preserved as a range has nowhere to go. Picking
    July 1st would fabricate the day that decides held-at-date (INV-7), so the
    lot is refused instead — and the refusal is counted."""
    sheet = _sheet("Fund II Holdings by Quarter", "X", {"25Q4": "1000"}, cost="1000")
    mapped = map_workbooks([sheet], [_tranche("Fund", "1000", text="7/2020")], GENERATED_AT)
    assert mapped.lots == []
    assert [r.subject for r in mapped.refused("Lot.acquired_date")] == ["X lot 1 (7/2020)"]


def test_a_row_kind_the_reader_does_not_recognise_becomes_no_lot() -> None:
    """`is_recognised` is false for `Indirect Fund`, and the contract layer has
    no third state between investment and exit. The money leaves no trace, so the
    drop is recorded rather than inferred from a count."""
    sheet = _sheet("Fund II Holdings by Quarter", "X", {"25Q4": "1000"})
    mapped = map_workbooks([sheet], [_tranche("Indirect Fund", "1000000")], GENERATED_AT)
    assert mapped.lots == []
    assert "1,000,000 of stated investment" in mapped.refused("Lot")[0].detail


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
def test_sixteen_of_the_eighteen_tranches_become_lots() -> None:
    """Two do not, for different reasons. Jackpocket's Exit row is proceeds, not
    a purchase, and correctly becomes a realisation date rather than a lot. Jio's
    `Indirect Fund` row becomes nothing at all."""
    m = _mapped()
    assert len(read_master_breakdown(MASTER)) == 18
    assert len(m.lots) == 16
    assert [lot.id for lot in m.lots if lot.realized_date] == ["fund_ii_jackpocket_1"]
    assert [lot.realized_date for lot in m.lots if lot.realized_date] == [date(2024, 5, 20)]


@needs_workbooks
def test_jio_joins_on_the_company_the_label_names_not_on_the_label() -> None:
    """The tracker calls it `Jio (Indirect)`; the master breakdown sheet is
    `Jio`. The raw strings never met, so 1,000,000 of stated investment reached
    no holding at all and was reported from both ends of a join that had simply
    missed. `company_key` joins them, and what is left is the one true statement:
    the row's kind is `Indirect Fund`, which the reader does not recognise, so it
    becomes no lot and the money leaves no trace in the contract layer.

    The tracker's own words are kept on the holding. `(Indirect)` is the only
    signal in either workbook that this is a feeder rather than a direct
    position, so the key normalises and the label does not."""
    m = _mapped()
    assert m.refused("Holding") == []
    kinds = m.refused("Lot")
    assert [r.subject for r in kinds] == ["Jio (Indirect) · Indirect Fund"]
    assert "1,000,000 of stated investment" in kinds[0].detail
    # It still reaches the packet — as a mark with no cost, no class and no date.
    jio = next(h for h in m.holdings if h.id == "fund_i_jio_indirect")
    assert jio.company_name == "Jio (Indirect)"
    assert [lot for lot in m.lots if lot.holding_id == jio.id] == []
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
    m = map_workbooks([sheet], [_tranche("Indirect Fund", "1000", text="1/1/2026")], GENERATED_AT)
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
    assert [lot.acquired_date for lot in m.lots] == [date(2026, 1, 1)]
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

    Jio is the corpus case and it is why this looks like a no-op: its only master
    row is `Indirect Fund` dated `7/2020`, so no lot survives — but the row's
    date cell answers the question perfectly well, and the answer is the same one
    the substitution used to guess. Nothing is substituted now, because nothing
    is being guessed."""
    m = _mapped()
    assert m.substituted("HoldingRow.held_at_date") == []
    assert m.refused("HoldingRow.held_at_date") == []
    assert all(row.held_at_date for p in m.packets for row in p.rows)
    # The lot-based rule would have said False here, and dropped the position.
    jio = next(h for h in m.holdings if h.company_name == "Jio (Indirect)")
    assert [lot for lot in m.lots if lot.holding_id == jio.id] == []


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
def test_every_lot_lands_in_one_invented_security_class() -> None:
    """`Lot.security_class` is required and no master-breakdown row states one.
    Every lot therefore carries the same sentinel — which means INV-17's
    cross-class rule can never fire on ingested data, because ingested data has
    exactly one class."""
    m = _mapped()
    assert len(m.substituted("Lot.security_class")) == 16
    assert {lot.security_class for lot in m.lots} == {ASSUMED_SECURITY_CLASS}


@needs_workbooks
def test_every_position_is_typed_direct_equity_including_the_ones_that_are_not() -> None:
    """`PositionType` is closed and required; the workbooks classify nothing. The
    tracker's own row label says `Jio (Indirect)`, so at least one of these 14 is
    demonstrably wrong from the source itself."""
    m = _mapped()
    assert len(m.substituted("HoldingRow.position_type")) == 14
    assert {h.position_type for h in m.holdings} == {m.holdings[0].position_type}
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
