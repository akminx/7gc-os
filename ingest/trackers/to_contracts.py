"""Turn what the workbooks say into the frozen wire contract.

This module exists to be **refused**. `packages/contracts/models.py` had only
ever been handed `fixtures/dream.py`, a fixture written by hand to fit it, so
every field it demands was a field the fixture supplied by construction. A
mapper fed the real 14 positions asks the only question that matters about a
contract: does the source actually carry what the shape requires?

So nothing here quietly fills a hole. Two records come back beside the models:

* `Substitution` — the contract required a value, the workbooks state none, and
  one was put in anyway. Every one is a place the packet asserts something no
  source supports.
* `Refusal` — the contract could not be satisfied at all, so the row does not
  exist. A dropped row is louder than an invented one, and it must be counted
  rather than skipped.

Neither list is decoration: `tests/test_real_data_end_to_end.py` asserts their
contents, so a later change that stops recording a substitution fails rather
than reading clean.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from ingest.trackers import classify
from ingest.trackers.findings import _fund_of, _period_end, _period_scope
from ingest.trackers.read import SheetNote, TrackerSheet, Tranche, company_key, position_held_at
from ingest.trackers.records import Holding, Mapped, Refusal, Substitution
from ingest.trackers.to_lots import (
    ASSUMED_CURRENCY,
    add_lots,
)
from packages.contracts.enums import AuditScope, DerivationStatus, PositionType
from packages.contracts.models import HoldingRow, Mark, Money, Packet, Period

#: Only where no line signals otherwise. `classify.position_type` reads the
#: feeder, the listing and the foreign denomination off the sheet.
ASSUMED_POSITION_TYPE = PositionType.DIRECT_EQUITY

#: NOT an assumption any more. SPEC 2 closes the packet date set at six
#: fund-periods — Fund II at the three measurement dates the audit letter names,
#: Fund I at the same year ends — and the other six the tracker carries are
#: `lineage_only`. Declaring all twelve in packet scope put 26Q1, a quarter
#: AFTER the last measurement date under audit, into the auditor's packet.
_SCOPE_OF = {"packet": AuditScope.PACKET, "lineage_only": AuditScope.LINEAGE_ONLY}

SCHEMA_VERSION = "1"
POLICY_VERSION = "v1"

#: `Mark.derivation_reason` is required and non-null. The tracker states a
#: figure and no derivation for it, so the reason is the absence itself.
NO_DERIVATION = "TRACKER_FIGURE_ONLY:workbooks_state_no_derivation"

#: A cell holding only an em dash says "not held", which is already carried by
#: the absence of a mark. Any other text is a statement the packet loses.
_EMPTY_NOTES = frozenset({"", "—", "-", "–"})


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _usd(amount: Decimal) -> Money:
    return Money(amount=amount, currency=ASSUMED_CURRENCY)


def _add_periods(sheet: TrackerSheet, fund_id: str, out: Mapped) -> dict[str, Period]:
    periods: dict[str, Period] = {}
    for label in sheet.period_labels:
        measured = _period_end(label)
        if measured is None:
            out.refusals.append(
                Refusal(
                    f"{sheet.fund_label} · {label}",
                    "Period.period_date",
                    "the period label cannot be dated, and `Period.period_date` is required",
                )
            )
            continue
        scope = _SCOPE_OF[_period_scope(_fund_of(sheet.fund_label), label)]
        period = Period(
            id=f"{fund_id}_{_slug(label)}",
            fund_id=fund_id,
            period_date=measured,
            audit_scope=scope,
            label=label,
        )
        periods[label] = period
    out.periods.extend(periods.values())
    return periods


def _add_holding(
    sheet: TrackerSheet,
    fund_id: str,
    company: str,
    out: Mapped,
    notes: list[SheetNote],
    own: list[Tranche],
) -> Holding:
    read = classify.position_type(notes, own)
    holding = Holding(
        id=f"{fund_id}_{_slug(company)}",
        fund_id=fund_id,
        company_id=_slug(company),
        company_name=company,
        position_type=PositionType(read.value),
        currency=ASSUMED_CURRENCY,
    )
    if holding.position_type is ASSUMED_POSITION_TYPE:
        out.substitutions.append(
            Substitution(
                company,
                "HoldingRow.position_type",
                ASSUMED_POSITION_TYPE.value,
                f"{read.source_text}, so the position is read as direct equity",
            )
        )
    out.substitutions.append(
        Substitution(
            company,
            "Money.currency",
            ASSUMED_CURRENCY,
            "no cell, header or footer in either workbook names a currency, and `Money` "
            "cannot be constructed without one (INV-11)",
        )
    )
    out.holdings.append(holding)
    return holding


def _add_marks(
    sheet: TrackerSheet,
    holding: Holding,
    company: str,
    periods: dict[str, Period],
    own: list[Tranche],
    out: Mapped,
) -> dict[str, HoldingRow]:
    """One row per period the tracker states a number for.

    No assessments and no gaps are attached, because the workbooks contain no
    evidence of any kind. That is not a shortcut: `HoldingRow.supported` derives
    from the assessments, so an empty list makes every row read `not assessed`,
    which is exactly what the source supports. Fabricating a `sufficient` R1
    here is the single cheapest way to make this whole exercise look clean.

    `held_at_date` is computed by `position_held_at` from the SOURCE rows
    (INV-7), not from the lots that survived into the contract layer. Those are
    different sets — a row of an unrecognised kind and a lot whose date cell
    names a month both fail to become a `Lot` — and reading held-at-date off the
    survivors answered with whichever rows happened to be contractable, wrongly
    in both directions.

    Where the source cannot say, the field is a `bool` with no third state, so
    one of two wrong answers has to be recorded. `False` is the more expensive
    one: it removes every mark of the holding from `Packet.totals()`, so the
    fund total silently drops a position the tracker states a figure for. The
    substitution below records the other choice and what it rests on.
    """
    undecidable = [
        label
        for label, period in periods.items()
        if position_held_at(own, period.period_date) is None
    ]
    if undecidable:
        out.substitutions.append(
            Substitution(
                company,
                "HoldingRow.held_at_date",
                "True",
                "the master breakdown does not say whether this position was held at "
                f"{', '.join(sorted(undecidable))} — it names no row for it, or dates one in "
                "a form no day can be read from — and `HoldingRow.held_at_date` is a `bool` "
                "with no third state for that. The only thing either workbook then says is "
                "that the tracker states a figure at that date, so that is what is recorded "
                "— a `False` would remove the position from `Packet.totals()` and understate "
                "the fund by its own reported mark with nothing in the packet saying so",
            )
        )
    rows: dict[str, HoldingRow] = {}
    for label, period in periods.items():
        amount = sheet.amount(company, label)
        if amount is None:
            note = next(
                (
                    m.note
                    for m in sheet.marks
                    if m.company == company and m.period_label == label and m.note
                ),
                None,
            )
            if note is not None and note.strip() not in _EMPTY_NOTES:
                out.refusals.append(
                    Refusal(
                        f"{company} · {label}",
                        "Mark.reported",
                        f"the cell states {note!r} rather than a number; `Mark.reported` is "
                        "`Money`, and neither `Mark` nor `HoldingRow` carries realisation "
                        "proceeds or a cell note, so the figure and its explanation are lost",
                    )
                )
            continue
        mark = Mark(
            id=len(out.marks) + 1,
            holding_id=holding.id,
            period_id=period.id,
            reported=_usd(amount),
            validated=None,
            derivation_status=DerivationStatus.NOT_DERIVABLE,
            derivation_reason=NO_DERIVATION,
        )
        out.marks.append(mark)
        rows[label] = HoldingRow(
            holding_id=holding.id,
            company_name=company,
            position_type=holding.position_type,
            held_at_date=position_held_at(own, period.period_date) is not False,
            mark=mark,
        )
    return rows


def map_workbooks(
    sheets: list[TrackerSheet],
    tranches: list[Tranche],
    generated_at: datetime,
    notes: list[SheetNote] | None = None,
) -> Mapped:
    """The two workbooks, as far into the contract layer as they reach.

    `notes` are the breakdown's prose lines. They default to empty so a caller
    that has not been updated still maps — every position then reads as direct
    equity with an unstated class, which is where this started and is recorded
    as a substitution rather than passing silently.
    """
    out = Mapped()
    by_position: dict[tuple[str | None, str], list[Tranche]] = {}
    for t in tranches:
        by_position.setdefault((_fund_of(t.fund), company_key(t.company)), []).append(t)
    notes_by_company: dict[str, list[SheetNote]] = {}
    for note in notes or []:
        notes_by_company.setdefault(company_key(note.company), []).append(note)

    # The same collision, on the other side of the same join. `company_key` is
    # applied to the master workbook's TAB NAME at read time, so `Acme (US)` and
    # `Acme (UK)` are already one company before any join runs — and a single
    # tracker row then took both companies' lots, with no refusal and no orphan.
    # `Tranche.source_sheet` keeps what the normalisation discarded so the
    # multiplicity is still visible here. The tracker side of this has been
    # refused since it was written; enforcing it on one side only is this
    # project's recurring defect.
    merged = {
        key
        for key, rows_for in by_position.items()
        if len({t.source_sheet for t in rows_for if t.source_sheet}) > 1
    }

    claimed: set[tuple[str | None, str]] = set()
    for sheet in sheets:
        fund_key = _fund_of(sheet.fund_label)
        fund_id = _slug(fund_key or sheet.fund_label)
        periods = _add_periods(sheet, fund_id, out)
        by_period: dict[str, list[HoldingRow]] = {label: [] for label in periods}
        measured = [p.period_date for p in periods.values()]
        # Both sides join on the company the label NAMES, not on the label. The
        # tracker writes `Jio (Indirect)` and the master breakdown's sheet is
        # `Jio`; the raw strings never met, and the miss cost Fund I its whole
        # Jio position. Two tracker rows that reduce to the same company are a
        # different matter — see below.
        shared = {
            key
            for key in map(company_key, sheet.companies)
            if len({c for c in sheet.companies if company_key(c) == key}) > 1
        }

        for company in sheet.companies:
            key = company_key(company)
            if key in shared:
                # Attributing one company's tranches to two tracker rows would
                # count its cost and its lots twice, which is worse than not
                # joining at all. The rows stay unjoined and the master side
                # reports as an orphan below, naming the money.
                own: list[Tranche] = []
                out.refusals.append(
                    Refusal(
                        company,
                        "Lot",
                        f"more than one row on this tracker sheet names the company {key!r}, "
                        "so no master-breakdown tranche can be attributed to this one without "
                        "guessing which row it belongs to; the rows are left unjoined rather "
                        "than counted under both",
                    )
                )
            elif (fund_key, key) in merged:
                # More than one master tab reduces to this company. Taking them
                # all would attach another company's cost and lots to this
                # holding; picking one would be a guess. Neither is reportable,
                # so nothing is joined and the money is named below as an orphan.
                own = []
                claimed.discard((fund_key, key))
                tabs = sorted({t.source_sheet or "?" for t in by_position[fund_key, key]})
                out.refusals.append(
                    Refusal(
                        company,
                        "Lot",
                        f"more than one master-breakdown sheet names the company {key!r} under "
                        f"this fund ({', '.join(tabs)}), so no tranche can be attributed to this "
                        "holding without guessing which sheet belongs to it; the sheets are left "
                        "unjoined rather than counted under one",
                    )
                )
            else:
                claimed.add((fund_key, key))
                own = by_position.get((fund_key, key), [])
            if not own and key not in shared and (fund_key, key) not in merged:
                out.refusals.append(
                    Refusal(
                        company,
                        "Lot",
                        "no master-breakdown sheet is named for this company under this "
                        "fund, so the holding reaches the packet with no lot, no cost and "
                        "no acquisition date",
                    )
                )
            # The holding is built AFTER its tranches are resolved: the sheet's
            # own prose is what says whether this is a feeder, a listed position
            # or a foreign-denominated interest, and the `Type` cells are half
            # of that signal. Building it first meant classifying a position
            # without having read the rows that describe it.
            mine = notes_by_company.get(key, [])
            holding = _add_holding(sheet, fund_id, company, out, mine, own)
            add_lots(holding, company, own, out, mine, measured)
            for label, row in _add_marks(sheet, holding, company, periods, own, out).items():
                by_period[label].append(row)

        for label, period in periods.items():
            rows = by_period[label]
            # SPEC 2 / INV-20: a lineage-only period is ingested, appears in the
            # ledger and can serve as an R3 predecessor, and is NOT packeted.
            # `Packet` enforces this; the mapper used to declare every period
            # packet-scope so the rule could never bite, which put 26Q1 — after
            # the last measurement date under audit — into the auditor's packet.
            if period.audit_scope is not AuditScope.PACKET:
                continue
            if not rows:
                out.refusals.append(
                    Refusal(
                        f"{sheet.fund_label} · {label}",
                        "Packet.rows",
                        "no holding states a figure for this period, and `Packet.totals()` "
                        "refuses a packet with no rows",
                    )
                )
                continue
            out.substitutions.append(
                Substitution(
                    period.id,
                    "Packet.policy_version",
                    POLICY_VERSION,
                    "a packet must name the policy it was assembled under; the workbooks "
                    "name none, and no policy has been applied to these rows",
                )
            )
            out.packets.append(
                Packet(
                    fund_id=fund_id,
                    period=period,
                    rows=rows,
                    schema_version=SCHEMA_VERSION,
                    policy_version=POLICY_VERSION,
                    generated_at=generated_at,
                )
            )

    # A tranche the tracker never names reaches nothing at all: no holding, no
    # lot, no mark. The reconciler reports the tracker side of this join
    # (`cost_basis_never_compared`); the master-breakdown side has no analogue,
    # and here it is the difference between a position existing and not.
    for (orphan_fund, orphan), rows_for in by_position.items():
        if (orphan_fund, orphan) in claimed:
            continue
        out.refusals.append(
            Refusal(
                f"{orphan_fund} · {orphan}",
                "Holding",
                f"{len(rows_for)} master-breakdown row(s) totalling "
                f"{sum((t.investment for t in rows_for), Decimal(0)):,} belong to a company "
                "no valuation-tracker sheet names under this fund, so they reach no holding, "
                "no lot and no mark",
            )
        )
    return out
