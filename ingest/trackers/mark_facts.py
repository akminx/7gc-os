"""What the workbooks say about one company, in one fund, at one date.

Lookups and arithmetic only. Nothing here decides whether anything is a finding
— that is `marks.py`, which imports this and holds the seven checks.

Split out at the file-size budget, along a seam that already existed: these
five used to be one function that ordered tranches, resolved ambiguity, summed
cost, applied materiality and chose a finding kind, and every defect this layer
produced lived in the seam between two of those jobs rather than inside any one
of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ingest.trackers.findings import _fund_of, _period_end
from ingest.trackers.read import TrackerSheet, Tranche, company_key

# ── the fact layer the mark checks share ─────────────────────────────────
#
# Lookups and arithmetic only. Nothing here decides whether anything is a
# finding.

#: A position: every master-breakdown investment row for one company in one
#: fund. Keyed by fund because the same company appears in both funds, and
#: merging them values one fund's shares at the other fund's purchase price.
_Positions = dict[tuple[str | None, str], list[Tranche]]


def _positions(tranches: list[Tranche]) -> _Positions:
    """Every recognised row for one company in one fund — exits included.

    Exits used to be dropped here. That is right for cost (an exit's
    "Investment ($)" column holds proceeds) and wrong for everything about
    shares: a position fully sold still reported "the 200 shares then held",
    because nothing that removed shares was ever in the list.
    """
    out: _Positions = {}
    for t in tranches:
        if not t.is_recognised:
            continue
        out.setdefault((_fund_of(t.fund), company_key(t.company)), []).append(t)
    return out


def _purchases(lots: list[Tranche]) -> list[Tranche]:
    return [t for t in lots if t.is_investment]


def _is_priced(t: Tranche) -> bool:
    return t.share_price is not None and t.share_count is not None


def _has_comparable_purchases(lots: list[Tranche]) -> bool:
    """Scope boundary, not a correctness rule.

    These checks ask what a *later* purchase says about an *earlier* one, so a
    position with a single priced lot is out of scope: its own price times its
    own shares is its own cost, and the question answers itself. Stated as a
    named predicate so a reviewer sees a decision rather than a bare `< 2`.
    """
    return len([t for t in _purchases(lots) if _is_priced(t)]) >= 2


def _definitely_follows_another(lot: Tranche, others: list[Tranche]) -> bool:
    """Does the source place `lot` strictly after some other lot?

    Without this, two purchases made on the SAME DAY produced a finding whose
    kind and detail both announced a "later purchase". Neither was later.
    """
    r = lot.acquired_range
    if r is None:
        return False
    return any(
        o is not lot and o.acquired_range is not None and o.acquired_range[1] < r[0] for o in others
    )


def _held_at(lots: list[Tranche], on: date) -> tuple[list[Tranche], list[Tranche]]:
    """(definitely held on `on`, cannot be told from the date cell).

    The second list is why this returns a pair. A lot whose date cell cannot
    answer must not be quietly counted or quietly dropped — either choice states
    something the source does not.
    """
    held = [t for t in lots if t.held_by(on) is True]
    undecidable = [t for t in lots if t.held_by(on) is None]
    return held, undecidable


def _latest_candidates(priced: list[Tranche]) -> list[Tranche]:
    """The priced lots that no other priced lot definitely follows.

    One candidate means "most recent" is decidable. More than one means the
    source does not say which came last — including the case of a lot with no
    readable date at all, which nothing can be shown to follow.
    """

    def definitely_after(a: Tranche, b: Tranche) -> bool:
        ra, rb = a.acquired_range, b.acquired_range
        return ra is not None and rb is not None and ra[0] > rb[1]

    return [t for t in priced if not any(definitely_after(o, t) for o in priced if o is not t)]


@dataclass(frozen=True)
class _MarkFacts:
    """What the workbooks say about one company, in one fund, at one date."""

    #: Cost of every investment lot held at the date — priced or not. Summing
    #: only the priced ones understated cost, so a mark sitting exactly on total
    #: cost was reported as matching neither cost nor any purchase price, which
    #: is a false statement about a figure that reconciles perfectly.
    cost: Decimal
    #: Shares held at the date across the PRICED lots only.
    shares: Decimal
    #: What each still-possible latest purchase price implies for the WHOLE
    #: position: the priced shares at that price, plus any unpriced lot carried
    #: at its own cost. Valuing only the priced shares compared part of a
    #: position against a mark covering all of it — which is what made The Mom
    #: Project's mark look unexplained when it reconciles to the dollar.
    #: More than one entry means the ordering is not decidable.
    implied: list[tuple[Tranche, Decimal]]
    #: Cost of held lots with no share price. Non-zero means the implied figure
    #: above rests on carrying those lots at cost, which the detail must say.
    unpriced_cost: Decimal
    #: True when the held lots were bought at more than one price, so applying
    #: one lot's price across every share REPRICES the others. The workbooks do
    #: not state that figure; this reader synthesises it, and it also flattens
    #: share classes this reader cannot distinguish (INV-17). Fine for raising a
    #: question — never sufficient to answer one. See the basis check.
    repriced: bool
    undecidable: list[Tranche]
    #: Exits realised on or before the date. Non-zero means this reader cannot
    #: say which lots the sale consumed — FIFO, specific identification and
    #: pro-rata all give different answers and the workbooks name none of them —
    #: so no claim about shares still held is supportable.
    realised: list[Tranche]
    #: Held lots that no other held lot definitely precedes. Empty means the
    #: source establishes no purchase as later than any other.
    followers: list[Tranche]
    #: Shares on held lots that state a count but no price. They cannot be
    #: valued, so they are absent from `shares` — and any sentence quoting
    #: `shares` as "the shares then held" is wrong unless it says so.
    dropped_shares: Decimal

    @property
    def partial(self) -> bool:
        return self.unpriced_cost != 0


def _allocation_is_invariant(lots: list[Tranche], on: date) -> bool:
    """Does it matter which lot a sale consumed?

    Only when the held lots were bought at different prices. If every share cost
    the same, FIFO, specific identification and pro-rata all leave the same
    remainder, so nothing is assumed by proceeding. Named once and used by both
    the fact layer and the finding, so the two cannot disagree about when a
    realisation is genuinely unallocatable.
    """
    held, undecidable = _held_at(_purchases(lots), on)
    if undecidable or any(not _is_priced(t) for t in held):
        return False
    return len({t.share_price for t in held}) == 1


def _facts_at(lots: list[Tranche], on: date) -> _MarkFacts | None:
    purchases = _purchases(lots)
    held, undecidable = _held_at(purchases, on)
    # `is True` alone let an exit with an unreadable or straddling date through,
    # and the basis check then announced "the 150 shares then held" while a sale
    # of exactly 150 sat on the sheet. An exit this reader cannot place is the
    # same problem as one it can: the share count is not knowable.
    realised = [t for t in lots if t.is_exit and t.held_by(on) is not False]
    # A sale only defeats the arithmetic when WHICH lot it consumed changes the
    # answer. If every held lot was bought at the same price, each share cost
    # the same, so the remainder is identical under any allocation — FIFO,
    # specific identification and pro-rata all agree, and nothing is assumed.
    # Blocking that case reported an unallocatable realisation on a position
    # with a single lot and missed the real basis gap underneath it.
    if realised and _allocation_is_invariant(lots, on):
        price = next(iter({t.share_price for t in held})) or Decimal(0)
        sold = sum((t.share_count or Decimal(0) for t in realised), Decimal(0))
        remaining = sum((t.share_count or Decimal(0) for t in held), Decimal(0)) - sold
        if remaining > 0:
            return _MarkFacts(
                cost=remaining * price,
                shares=remaining,
                implied=[(t, remaining * price) for t in _latest_candidates(held)],
                unpriced_cost=Decimal(0),
                repriced=False,
                undecidable=[],
                realised=[],
                followers=[t for t in held if _definitely_follows_another(t, held)],
                dropped_shares=Decimal(0),
            )
    if undecidable or realised:
        return _MarkFacts(
            cost=Decimal(0),
            shares=Decimal(0),
            implied=[],
            unpriced_cost=Decimal(0),
            repriced=False,
            undecidable=undecidable,
            realised=realised,
            followers=[],
            dropped_shares=Decimal(0),
        )
    if not held:
        return None
    # A position whose every lot is unpriced still has a cost, and a mark can
    # still disagree with it. Returning None here skipped Moonfare entirely —
    # carried at 1,048,515 against 1,000,000 of cost, with no share price in the
    # workbooks to explain the difference and no finding either.
    priced_held = [t for t in held if _is_priced(t)]
    shares = sum((t.share_count or Decimal(0) for t in priced_held), Decimal(0))
    unpriced_cost = sum((t.investment for t in held if not _is_priced(t)), Decimal(0))
    candidates = _latest_candidates(priced_held)
    return _MarkFacts(
        cost=sum((t.investment for t in held), Decimal(0)),
        shares=shares,
        implied=[(t, shares * (t.share_price or Decimal(0)) + unpriced_cost) for t in candidates],
        unpriced_cost=unpriced_cost,
        repriced=len({t.share_price for t in priced_held}) > 1,
        undecidable=[],
        realised=[],
        followers=[t for t in priced_held if _definitely_follows_another(t, priced_held)],
        dropped_shares=sum(
            (t.share_count or Decimal(0) for t in held if not _is_priced(t)), Decimal(0)
        ),
    )


def _composition(facts: _MarkFacts, lot: Tranche, value: Decimal) -> str:
    """How an implied figure was built, and what had to be assumed to build it.

    Every assumption is named. A figure this reader synthesised must not read
    like a figure the workbooks printed — that is the difference between giving
    an auditor a lead and handing them a fabrication.
    """
    # "later" only when the source places this lot after another. Two purchases
    # on the same day are not a later purchase, and saying so was a false claim
    # about the fund's own transaction history.
    when = "later " if lot in facts.followers else ""
    parts = [
        f"the {facts.shares:,} shares then held at the {when}{lot.acquired_text} purchase "
        f"price of {lot.share_price}"
    ]
    if facts.partial:
        parts.append(
            f"plus {facts.unpriced_cost:,} of investment for which these workbooks state "
            "no share price, carried at its own cost"
        )
    tail = f" is {value:,}"
    caveats = []
    if facts.repriced:
        caveats.append(
            "it reprices shares bought at other prices and does not distinguish share classes"
        )
    if len(facts.implied) > 1:
        # Attributing the figure to one lot while others remain possible reads
        # as though the ordering were settled. It is not.
        caveats.append(
            f"{len(facts.implied)} purchases could each be the most recent and this is one of them"
        )
    if facts.dropped_shares:
        # A lot with a share count but no price contributes its cost and not its
        # shares, so the share count in this sentence is smaller than the
        # position's. Saying "the N shares then held" without this was false.
        caveats.append(
            f"{facts.dropped_shares:,} further shares are held on lots that state no price "
            "and are excluded from this count"
        )
    if caveats:
        tail += " — a figure no row states, since " + "; and ".join(caveats)
    return ", ".join(parts) + tail


def _sheets_for(sheets: list[TrackerSheet], fund: str | None) -> list[TrackerSheet]:
    return [s for s in sheets if _fund_of(s.fund_label) == fund]


def _labels_for(sheet: TrackerSheet, key: str) -> list[str]:
    """The sheet's own row labels for a normalised company key.

    Positions are keyed on `company_key` so `Jio (Indirect)` joins the master
    sheet named `Jio`, but the tracker's cells are addressed by the label it
    actually prints. Looking up the normalised key here returned nothing and
    silently emptied every mark for that position.
    """
    return [c for c in sheet.companies if company_key(c) == key]


def _dated_marks(
    sheets: list[TrackerSheet], fund: str | None, company: str
) -> list[tuple[str, date, Decimal, Decimal | None]]:
    """Every mark for this company in this fund whose period can be dated.

    The fourth element is the cost basis the TRACKER states for this company,
    which is a figure in these workbooks like any other. Ignoring it let a mark
    sitting exactly on the tracker's own stated basis be reported as a basis no
    row states — while the cross-workbook check, correctly, reported the
    disagreement between that figure and the master breakdown. Two findings
    about one fact, one of them false.
    """
    out: list[tuple[str, date, Decimal, Decimal | None]] = []
    for sheet in _sheets_for(sheets, fund):
        for label in _labels_for(sheet, company):
            for period in sheet.period_labels:
                amount = sheet.amount(label, period)
                measured = _period_end(period)
                if amount is not None and measured is not None:
                    out.append((period, measured, amount, sheet.cost_basis.get(label)))
    return out
