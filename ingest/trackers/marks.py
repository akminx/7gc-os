"""The seven questions the marks and the master breakdown ask of each other.

One question per check. Every check does its own `(fund, company)` lookup
through the fact layer in `mark_facts.py`. That is deliberate duplication: the
recurring defect in this project is a rule applied on one side of a join and
not the other, and a check that cannot see another check's lookup cannot
inherit its mistake.
"""

from __future__ import annotations

from decimal import Decimal

from ingest.trackers.findings import (
    Finding,
    FindingKind,
    _fund_of,
    _is_material,
    _period_end,
    _period_scope,
)
from ingest.trackers.mark_facts import (
    _allocation_is_invariant,
    _composition,
    _dated_marks,
    _facts_at,
    _has_comparable_purchases,
    _held_at,
    _is_priced,
    _labels_for,
    _latest_candidates,
    _positions,
    _purchases,
    _sheets_for,
)
from ingest.trackers.read import TrackerSheet, Tranche, company_key


# ── one check, one question ──────────────────────────────────────────────
def check_latest_purchase_is_decidable(
    sheets: list[TrackerSheet], tranches: list[Tranche]
) -> list[Finding]:
    """Can the workbooks say which purchase came last?

    Only reports. It used to `continue` out of the enclosing loop, which meant
    an undecidable ordering suppressed every other question about that company —
    so an ordinary month-only follow-on hid a mark sitting exactly on cost.

    Ambiguity is reported only when it changes an answer. Two lots on the same
    day at the same price are not ambiguous in any way that matters, and
    reporting them buried real findings under noise.
    """
    out: list[Finding] = []
    for (_fund, company), lots in _positions(tranches).items():
        if not _has_comparable_purchases(lots):
            continue
        # `_purchases`, not `lots`: `_positions` carries exits now, and an exit
        # has a price and a share count too. Without this filter an exit was
        # announced as a "priced purchase" and entered the latest-purchase
        # ordering — a sale reported as an acquisition.
        priced = [t for t in _purchases(lots) if _is_priced(t)]
        undated = [t for t in priced if t.acquired_range is None]
        if undated:
            out.append(
                Finding(
                    kind=FindingKind.PURCHASE_DATE_UNREADABLE,
                    subject=company,
                    detail=(
                        f"{len(undated)} priced purchase(s) carry a date this reader cannot "
                        f"read ({', '.join(sorted(str(t.acquired_text) for t in undated))}), "
                        "so no mark was compared against them"
                    ),
                )
            )
        candidates = _latest_candidates(priced)
        if len(candidates) < 2 or len({t.share_price for t in candidates}) < 2:
            continue
        out.append(
            Finding(
                kind=FindingKind.LATEST_PURCHASE_IS_AMBIGUOUS,
                subject=company,
                detail=(
                    "which purchase is most recent cannot be determined, and they are "
                    "priced differently: "
                    + "; ".join(f"{t.acquired_text} at {t.share_price}" for t in candidates)
                ),
            )
        )
    return out


def check_holding_dates_are_decidable(
    sheets: list[TrackerSheet], tranches: list[Tranche]
) -> list[Finding]:
    """Can we say whether a lot was held at the measurement date?

    A date cell spanning the measurement date answers neither yes nor no. The
    old code had no third answer available to it: it summed every priced lot
    once, outside the period loop, so an undated lot's shares were valued at a
    price nothing showed it preceded.
    """
    out: list[Finding] = []
    for (fund, company), lots in _positions(tranches).items():
        # Not gated: whether a lot was held is a question about one lot.
        blocked = sorted(
            {
                period
                for period, measured, _a, _c in _dated_marks(sheets, fund, company)
                # Purchases only: `lots` carries exits now, and an undecidable
                # EXIT date was reported as "a purchase date spans the
                # measurement date" — wrong row, wrong noun.
                if _held_at(_purchases(lots), measured)[1]
            }
        )
        if blocked:
            out.append(
                Finding(
                    kind=FindingKind.HOLDING_AT_DATE_UNDECIDABLE,
                    subject=company,
                    detail=(
                        f"at {', '.join(blocked)} a purchase date spans the measurement date, "
                        "so whether the lot was held then cannot be determined and the mark "
                        "was not compared"
                    ),
                )
            )
    return out


def check_marks_reach_a_position(
    sheets: list[TrackerSheet], tranches: list[Tranche]
) -> list[Finding]:
    """Every mark must reach some master-breakdown position, or say it did not.

    The cost path has said this since the beginning — `cost_basis_never_compared`
    exists precisely so a failed join cannot read as agreement. The mark path had
    no such statement: a sheet whose fund label did not normalise onto a tranche
    fund, or a company the master spells differently, was simply excluded by
    `_sheets_for` and every mark on it went unexamined in silence.

    That is this project's recurring defect — a rule enforced on one side of a
    join and not the other — appearing for the sixth time.
    """
    reachable = set(_positions(tranches))
    # Rows the master breakdown carries for a company but which are not
    # recognised investments — Jio's only row is `Indirect Fund`. Saying "no
    # position matched this company" of those reads as "we hold nothing for
    # them", which is false and points the auditor at the wrong question: the
    # row exists, this reader does not understand its type.
    unrecognised = {
        (_fund_of(t.fund), company_key(t.company)) for t in tranches if not t.is_recognised
    }
    out: list[Finding] = []
    for sheet in sheets:
        fund = _fund_of(sheet.fund_label)
        for company in sheet.companies:
            if (fund, company_key(company)) in reachable:
                continue
            # One finding per period, not one per company. A single finding
            # spanning FY2021-FY2025 mixes packet and lineage-only dates, so it
            # can carry only one scope and whichever is chosen is wrong for the
            # others — and packet filtering then drops or admits all five.
            for period in sorted(sheet.period_labels):
                if sheet.amount(company, period) is None or _period_end(period) is None:
                    continue
                out.append(
                    Finding(
                        kind=FindingKind.MARK_NEVER_COMPARED,
                        subject=f"{company} · {period}",
                        scope=_period_scope(fund, period),
                        detail=(
                            "the valuation tracker states a figure but "
                            + (
                                "every master-breakdown row for this company is of a type "
                                "this reader does not recognise as an investment"
                                if (fund, company_key(company)) in unrecognised
                                else "no master-breakdown position matched this company "
                                "in this fund"
                            )
                            + ", so the mark was never compared against any purchase"
                        ),
                    )
                )
    return out


def check_realisations_are_allocatable(
    sheets: list[TrackerSheet], tranches: list[Tranche]
) -> list[Finding]:
    """Once shares have been sold, which lots did the sale consume?

    FIFO, specific identification and pro-rata give different answers and these
    workbooks name none of them. So after a realisation this reader cannot say
    how many shares remain, and every claim that depends on a share count stops.

    Exits used to be dropped before the marks were examined at all, so a
    position sold in full still reported "the N shares then held" — a statement
    the workbooks flatly contradict, about a company whose exit row they carry.
    """
    out: list[Finding] = []
    for (fund, company), lots in _positions(tranches).items():
        # Per period, and counting only the exits that actually precede it. A
        # single total across every exit reported a 2026 sale as "preceding"
        # 25Q4 — a share count the source contradicts.
        for period, measured, _a, _c in _dated_marks(sheets, fund, company):
            done = [t for t in lots if t.is_exit and t.held_by(measured) is True]
            # An exit this reader cannot place is blocked by the fact layer too,
            # and blocking without reporting is the silence this whole layer
            # exists to prevent.
            undated = [t for t in lots if t.is_exit and t.held_by(measured) is None]
            if not done and not undated:
                continue
            if done and not undated and _allocation_is_invariant(lots, measured):
                continue
            sold = sum((t.share_count or Decimal(0) for t in done + undated), Decimal(0))
            when = (
                "precedes this date"
                if not undated
                else "carries a date this reader cannot place against this measurement date"
            )
            out.append(
                Finding(
                    kind=FindingKind.REALISATION_NOT_ALLOCATED_TO_LOTS,
                    subject=f"{company} · {period}",
                    scope=_period_scope(fund, period),
                    detail=(
                        f"a realisation of {sold:,} shares {when}, and these workbooks do not "
                        "say which lots it consumed, so the mark was not compared against any "
                        "share count"
                    ),
                )
            )
    return out


def check_period_labels_are_readable(
    sheets: list[TrackerSheet], tranches: list[Tranche]
) -> list[Finding]:
    """A period label this reader cannot date disables the date guard.

    Failing open here silently re-enabled the anachronism the guard exists to
    prevent: an unreadable label meant "no date constraint" rather than
    "cannot check".
    """
    out: list[Finding] = []
    for (fund, company), _lots in _positions(tranches).items():
        # Not gated: an undateable period label defeats the date guard for any
        # position, however many lots it has.
        unreadable = sorted(
            {
                period
                for sheet in _sheets_for(sheets, fund)
                for label in _labels_for(sheet, company)
                for period in sheet.period_labels
                if sheet.amount(label, period) is not None and _period_end(period) is None
            }
        )
        if unreadable:
            out.append(
                Finding(
                    kind=FindingKind.UNRECOGNISED_PERIOD_LABEL,
                    subject=company,
                    detail=(
                        f"period label(s) {', '.join(unreadable)} could not be dated, so no "
                        "mark for them was checked against later purchases"
                    ),
                )
            )
    return out


def check_marks_held_at_cost(sheets: list[TrackerSheet], tranches: list[Tranche]) -> list[Finding]:
    """A position carried at cost while the fund's own later purchase was dearer.

    Fluidstack is the case: 100,000 shares at $10 in October 2024 and 100,000 at
    $15 in May 2025. From 25Q2 the tracker still carries $2,500,000 — exactly
    cost — while the fund's own second purchase prices the same security at $15,
    which across 200,000 shares is $3,000,000.

    This is **not** an assertion that the mark is wrong. Holding at cost can be
    the correct treatment, and a purchase price is not a round price. The finding
    states two figures and the arithmetic between them, and stops there — the
    earlier wording claimed the later purchase "implies a higher value", which
    asserts a valuation conclusion this layer has no standing to draw and which
    was flatly false whenever the implied figure came out lower.
    """
    out: list[Finding] = []
    for (fund, company), lots in _positions(tranches).items():
        if not _has_comparable_purchases(lots):
            continue
        for period, measured, amount, _tracker_cost in _dated_marks(sheets, fund, company):
            facts = _facts_at(lots, measured)
            if facts is None or facts.undecidable or facts.realised:
                continue
            # "At cost" within rounding, not to the cent. Exact equality made
            # this check and the basis check disagree about a mark a fraction
            # off cost: neither would claim it.
            if _is_material(amount - facts.cost, facts.cost):
                continue
            gaps = [(t, value, value - amount) for t, value in facts.implied]
            # No priced purchase held at this date, so there is no later
            # purchase to be carried at cost *against*. `all([])` is vacuously
            # true and `max([])` raises, which aborted the entire reconciliation
            # rather than reporting anything at all.
            if not gaps:
                continue
            # True under every ordering the source still permits, or not
            # reported at all. This is what lets an undecidable ordering stop
            # being a gag: it only silences the finding when it actually
            # changes the answer.
            if not all(_is_material(gap, value) for _t, value, gap in gaps):
                continue
            lot, value, _gap = max(gaps, key=lambda g: abs(g[2]))
            out.append(
                Finding(
                    kind=FindingKind.MARK_AT_COST_DISAGREES_WITH_PURCHASE_PRICES,
                    subject=f"{company} · {period}",
                    scope=_period_scope(fund, period),
                    detail=(
                        f"carried at {amount:,}, which equals the cost of the lots held at "
                        f"this date, while {_composition(facts, lot, value)}"
                    ),
                    stated=amount,
                    computed=value,
                )
            )
    return out


def check_mark_basis_is_in_the_workbooks(
    sheets: list[TrackerSheet], tranches: list[Tranche]
) -> list[Finding]:
    """A mark matching neither cost nor any purchase price these books record.

    The Mom Project is marked at 2,750,000 on a Series C basis named only in a
    documentation line this reader does not parse. Comparing it against the last
    purchase ($5.00) produced three confident false discrepancies. So a mark
    matching neither cost nor a purchase price is reported as a basis we cannot
    verify — which is true — rather than as a disagreement, which is not.
    """
    out: list[Finding] = []
    for (fund, company), lots in _positions(tranches).items():
        # Deliberately NOT gated on `_has_comparable_purchases`. This question
        # does not need a later purchase to compare against an earlier one: a
        # single-lot position marked above its own cost and its own price is
        # exactly as unexplained, and gating it here hid that silently.
        for period, measured, amount, tracker_cost in _dated_marks(sheets, fund, company):
            facts = _facts_at(lots, measured)
            if facts is None or facts.undecidable or facts.realised:
                continue
            # A mark sitting on cost within rounding is the at-cost check's
            # question, not this one. Without this the `repriced` bypass below
            # reported a mark one cent off total cost as an unexplained basis.
            if not _is_material(amount - facts.cost, facts.cost):
                continue
            # The valuation tracker states a cost basis of its own, and a mark
            # sitting on it IS supported by a row in these workbooks — any
            # disagreement with the master breakdown is already reported by
            # `check_cost_basis_across_workbooks`, which is where it belongs.
            #
            # But that column is a LIFETIME figure with no as-of date. At a date
            # where some lots are not yet held it describes a different position
            # from the one being marked, and letting it through suppressed a
            # real discrepancy: 1,000 of cost held at 24Q4, a 2,000 purchase
            # still a year away, and a 3,000 mark reading as supported because
            # the lifetime total happens to be 3,000.
            # A mark sitting on the tracker's own cost column rests on a figure
            # these workbooks state — but that column is a lifetime total with
            # no as-of date, and where it disagrees with the master breakdown it
            # is a figure the workbooks CONTRADICT. Suppressing the finding on
            # that basis told an auditor to reconcile two spreadsheets when what
            # the mark needs is valuation support. So it is reported, and the
            # detail says what the figure actually is.
            lifetime = sum((t.investment for t in _purchases(lots)), Decimal(0))
            on_tracker_cost = (
                tracker_cost is not None
                and facts.cost == lifetime
                and not _is_material(amount - tracker_cost, tracker_cost)
            )
            gaps = [(t, value, value - amount) for t, value in facts.implied]
            # A mark the workbooks reproduce is not an unverifiable basis — but
            # only the workbooks get to reproduce it. When the held lots were
            # bought at one price, the implied figure is arithmetic on stated
            # rows and matching it is genuine reconciliation. When they were
            # bought at several, the figure reprices shares nothing repriced,
            # and letting THAT buy silence is how a synthesised number becomes
            # an audit conclusion. The Mom Project is the live case: its mark
            # equals 500,000 shares at the 5.00 price of a lot covering 100,000
            # of them, plus a note assumed to be worth cost. That coincidence is
            # a lead worth reporting, not a verification.
            gap_under_every_ordering = all(_is_material(gap, value) for _t, value, gap in gaps)
            # The repricing rule overrides materiality, never the ordering rule.
            # With two still-possible latest purchases, one of which implies the
            # carried mark exactly, "matches no purchase price" is false under a
            # reading the source still permits — and this check would have said
            # it while the at-cost check, given identical facts, refused to.
            # A synthesised match may not buy silence; an UNDECIDED one may not
            # buy a claim either.
            if gaps and len(gaps) == 1 and facts.repriced:
                pass
            elif gaps and not gap_under_every_ordering:
                continue
            if not gaps:
                # No priced purchase at all, so nothing in these workbooks can
                # imply a value. The mark differs from cost and stands alone.
                out.append(
                    Finding(
                        kind=FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS,
                        subject=f"{company} · {period}",
                        scope=_period_scope(fund, period),
                        detail=(
                            f"carried at {amount:,} against {facts.cost:,} of cost for the "
                            "lots held at this date; no lot states both a share price and a "
                            "share count, so no row this reader can parse implies this value"
                        ),
                        stated=amount,
                        computed=facts.cost,
                    )
                )
                continue
            lot, value, _gap = max(gaps, key=lambda g: abs(g[2]))
            # Does the arithmetic actually land on the carried figure? If it
            # does, the mark is explained — but only by the repricing this
            # reader had to invent to get there, so it is a question about a
            # treatment rather than a figure with no support at all. The Mom
            # Project is the live case, and an auditor asks something different
            # about it than about a mark four times its cost with nothing
            # behind it.
            reproduced = any(g == 0 for _t, _v, g in gaps)
            out.append(
                Finding(
                    kind=(
                        FindingKind.MARK_BASIS_ASSUMES_AN_UNSTATED_TREATMENT
                        if reproduced
                        else FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS
                    ),
                    subject=f"{company} · {period}",
                    scope=_period_scope(fund, period),
                    detail=(
                        f"carried at {amount:,}, which the {facts.cost:,} cost of the lots held "
                        "at this date does not explain. "
                        + (
                            "It equals the cost basis the valuation tracker states for this "
                            "company, which disagrees with the master breakdown. "
                            if on_tracker_cost
                            else ""
                        )
                        + (
                            f"It is reproduced exactly by {_composition(facts, lot, value)}"
                            if reproduced
                            else f"Nor do their purchase prices — {_composition(facts, lot, value)}"
                            "; no row in these trackers states that basis, so the "
                            "supporting document is the evidence to obtain"
                        )
                    ),
                    stated=amount,
                    computed=value if len(gaps) == 1 else None,
                )
            )
    return out


#: Every mark check, in the order the packet reads them. Named so `reconcile`
#: cannot silently omit one: adding a check here is what wires it in.
MARK_CHECKS = (
    check_marks_reach_a_position,
    check_latest_purchase_is_decidable,
    check_realisations_are_allocatable,
    check_holding_dates_are_decidable,
    check_period_labels_are_readable,
    check_marks_held_at_cost,
    check_mark_basis_is_in_the_workbooks,
)
