"""What the fund owns, out of the Master Investment Breakdown.

Split from `to_contracts.py` at the gate's file-size limit, and split by
responsibility rather than by line count: this module answers *what was bought,
when, and of what class*, while `to_contracts.py` answers *what it was reported
to be worth*. They failed independently and for different reasons — a lot that
never reached the ledger cost Fund I its Jio position, while a mark that could
not be dated cost a period its whole column.

Every value here is either read from the workbook or refused. The two records
that come back beside the lots — `Substitution` and `Refusal` — are the point:
a lot the contract could not hold must be counted, not skipped.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ingest.trackers import classify
from ingest.trackers.read import SheetNote, Tranche
from ingest.trackers.records import Holding, Mapped, Refusal, Substitution
from packages.contracts.models import Lot, LotConversion, Money

#: The workbooks name no currency in any cell, header or footer. `Money` cannot
#: be built without one (INV-11), so every figure is denominated here rather
#: than by the source.
ASSUMED_CURRENCY = "USD"

#: The fallback when nothing in either workbook names a class. Still a sentinel
#: rather than a plausible guess — inventing `series_a` would make INV-17's
#: cross-class rule read as satisfied, which is the one failure it exists to
#: catch. It is now the exception rather than the rule: `classify.security_class`
#: reads the class off the documentation line that names it, and only Anthropic
#: and Dream reach this.
ASSUMED_SECURITY_CLASS = classify.UNSTATED

#: Classes a DOCUMENT names and the workbooks do not.
#:
#: * Jackpocket's merger notice states "Security: Series B Preferred Stock" —
#:   the class being cashed out is the class the fund held.
#: * Dream's cap table has a section headed "Series A-1 Preferred — Holders of
#:   Record" listing `7GC Fund II, L.P.` at 625,000 shares.
#:
#: Dream was excluded on the rule "never read a class off a cap table", and that
#: rule was too coarse — a cross-family review caught it. A cap table's PRICED
#: class is the round being raised (Series B, $8.00) and its HOLDERS-OF-RECORD
#: section is what the fund owns (Series A-1). Reading the first as the held
#: class would collapse INV-17 in the one position that exists to demonstrate
#: it. Reading the second is exactly what INV-17 needs, and the document says
#: so in as many words.
CLASS_FROM_DOCUMENT = {"Jackpocket": "series_b", "Dream": "series_a1"}


def _usd(amount: Decimal) -> Money:
    return Money(amount=amount, currency=ASSUMED_CURRENCY)


def realised_date(
    company: str, purchases: list[Tranche], exits: list[Tranche], out: Mapped
) -> date | None:
    """The date these lots stopped being held, when the source forces one.

    `check_realisations_are_allocatable` already reports that the workbooks name
    no allocation method. The same silence lands harder here: `Lot.realized_date`
    is what `Lot.held_at` reads, so an unallocatable exit leaves every lot
    reading as still held — the position is sold and the ledger says otherwise.
    """
    if not exits:
        return None
    sold = sum((e.share_count or Decimal(0) for e in exits), Decimal(0))
    held = sum((p.share_count or Decimal(0) for p in purchases), Decimal(0))
    when = exits[0].acquired
    # One sale of the WHOLE position leaves nothing to allocate, however many
    # lots it consumed: every lot is realised, so no choice between FIFO,
    # specific identification and pro-rata is being made. Requiring a single
    # purchase lot as well made this refuse the ordinary shape — one exit
    # against two tranches — and every lot then reached the ledger with
    # `realized_date` null, reading as still held. `Packet.totals()` then
    # carried the position at every later measurement date, and
    # `check_realisations_are_allocatable` stays silent on a full exit because
    # the allocation genuinely is invariant. A sold position, reported as held,
    # with nothing anywhere saying so.
    if len(exits) == 1 and sold >= held and held > 0 and when is not None:
        out.substitutions.append(
            Substitution(
                company,
                "Lot.realized_date",
                when.isoformat(),
                "the workbooks name no lot-allocation method for a realisation; here one "
                "exit sells the position's entire share count, so every lot is realised and "
                "the allocation is forced rather than chosen",
            )
        )
        return when
    out.refusals.append(
        Refusal(
            company,
            "Lot.realized_date",
            f"{sold:,} share(s) realised across {len(exits)} exit row(s) against "
            f"{len(purchases)} purchase lot(s), and the workbooks name no allocation "
            "method, so no lot can be marked realised and every lot reads as still held",
        )
    )
    return None


def add_lots(
    holding: Holding,
    company: str,
    own: list[Tranche],
    out: Mapped,
    notes: list[SheetNote],
    measured: list[date],
) -> list[Lot]:
    mine: list[Lot] = []
    purchases = [t for t in own if t.is_investment]
    exits = [t for t in own if t.is_exit]
    for t in own:
        if t.is_recognised:
            continue
        out.refusals.append(
            Refusal(
                f"{company} · {t.kind}",
                "Lot",
                f"row kind {t.kind!r} is neither an investment nor an exit, so it becomes "
                f"no lot at all and {t.investment:,} of stated investment leaves no trace "
                "in the contract layer",
            )
        )
    realized = realised_date(company, purchases, exits, out)
    for n, t in enumerate(purchases, 1):
        subject = f"{company} lot {n}"
        acquired = t.acquired
        if acquired is None:
            acquired = acquired_from_range(subject, t, measured, out)
        if acquired is None:
            continue
        read = classify.security_class(t, notes, holding.position_type, CLASS_FROM_DOCUMENT)
        if read.value == ASSUMED_SECURITY_CLASS:
            out.substitutions.append(
                Substitution(
                    subject,
                    "Lot.security_class",
                    ASSUMED_SECURITY_CLASS,
                    f"{read.source_text}, and `Lot.security_class` is required",
                )
            )
        mine.append(
            Lot(
                id=f"{holding.id}_{n}",
                holding_id=holding.id,
                security_class=read.value,
                shares=t.share_count,
                entry_pps=t.share_price,
                cost=_usd(t.investment),
                acquired_date=acquired,
                realized_date=realized,
            )
        )
    out.lots.extend(mine)
    add_conversion(company, mine, notes, out)
    return mine


def add_conversion(company: str, mine: list[Lot], notes: list[SheetNote], out: Mapped) -> None:
    """Sway's recapitalisation, as an event rather than an edit to the lot.

    The exchange ratio is DERIVED from the two share counts the workbook states
    rather than read from a cell, because no cell states it: 800,000 into
    875,000 is 1.09375 exactly. V13 asserts that product, and a ratio producing
    a fractional share count fails rather than rounding into a plausible number.
    """
    recap = classify.recapitalisation(notes)
    if recap is None:
        return
    holders = [lot for lot in mine if lot.shares]
    if len(holders) != 1:
        out.refusals.append(
            Refusal(
                company,
                "LotConversion.lot_id",
                f"a recapitalisation is recorded but {len(holders)} share-bearing lot(s) "
                "exist, and the workbooks name no allocation, so no lot can be converted "
                "without choosing which",
            )
        )
        return
    lot = holders[0]
    assert lot.shares is not None
    out.conversions.append(
        LotConversion(
            lot_id=lot.id,
            effective_date=recap.effective_date,
            to_security_class=recap.security_class,
            to_shares=Decimal(recap.shares),
            exchange_ratio=Decimal(recap.shares) / lot.shares,
        )
    )


def acquired_from_range(subject: str, t: Tranche, measured: list[date], out: Mapped) -> date | None:
    """The earliest day an imprecise Date cell could mean — when it cannot matter.

    Jio's cell reads `7/2020`, a month. `Lot.acquired_date` is a required `date`
    and the reader deliberately preserves the range rather than inventing the
    day, so this lot was dropped entirely — which is worse than it sounds: with
    no lot, held-at-date had nothing to ask, and `api/ledger.py` fell back to
    "a mark exists at this date". A $1,000,000 position's membership rested on a
    fallback, and an earlier version of that fallback dropped it from every
    Fund I total.

    The precision only matters if a measurement date falls INSIDE the range —
    that is the case where the invented day would decide held-at-date. Every
    measurement date in this corpus is a year end and the range is July 2020, so
    no date can be affected and the earliest day is safe to use, recorded as a
    substitution naming the range. Where a date does fall inside, the lot is
    still refused, because there the guess would decide the answer.
    """
    span = t.acquired_range
    if span is None:
        out.refusals.append(
            Refusal(
                f"{subject} ({t.acquired_text})",
                "Lot.acquired_date",
                "the Date cell names no date at all, and `Lot.acquired_date` is required",
            )
        )
        return None
    start, end = span
    straddled = sorted(d for d in measured if start <= d < end)
    if straddled:
        out.refusals.append(
            Refusal(
                f"{subject} ({t.acquired_text})",
                "Lot.acquired_date",
                f"the Date cell names {start}..{end}, and the measurement date(s) "
                f"{', '.join(str(d) for d in straddled)} fall inside it, so the day chosen "
                "would decide whether the position was held at that date (INV-7)",
            )
        )
        return None
    out.substitutions.append(
        Substitution(
            subject,
            "Lot.acquired_date",
            start.isoformat(),
            f"the Date cell states {t.acquired_text!r}, a range of {start}..{end}; no "
            "measurement date falls inside it, so the day cannot change held-at-date",
        )
    )
    return start
