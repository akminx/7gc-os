"""Reconcile the workbooks against themselves and against each other.

Every finding here is a disagreement between two things the fund already
asserts. That matters for tone: the output is not "your numbers are wrong", it
is "these two statements cannot both be true, and here is the arithmetic." An
auditor can act on the second and will argue with the first.

Findings carry a `kind` from a closed vocabulary rather than free text, so the
packet can group them without parsing prose (INV-2 — a finding is a member of a
set, not a severity number).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from ingest.trackers.read import TrackerSheet, Tranche


class FindingKind(StrEnum):
    STATED_TOTAL_DISAGREES_WITH_CELLS = "stated_total_disagrees_with_cells"
    COST_TOTAL_DISAGREES_WITH_CELLS = "cost_total_disagrees_with_cells"
    TRANCHE_ARITHMETIC_DISAGREES = "tranche_arithmetic_disagrees"
    COST_BASIS_DISAGREES_ACROSS_WORKBOOKS = "cost_basis_disagrees_across_workbooks"
    UNRECOGNISED_TRANCHE_KIND = "unrecognised_tranche_kind"
    MARK_HELD_AT_COST_WHILE_LATER_ROUND_EXISTS = "mark_held_at_cost_while_later_round_exists"


@dataclass(frozen=True)
class Finding:
    kind: FindingKind
    subject: str
    detail: str
    stated: Decimal | None = None
    computed: Decimal | None = None

    @property
    def difference(self) -> Decimal | None:
        if self.stated is None or self.computed is None:
            return None
        return self.computed - self.stated


def check_stated_totals(sheet: TrackerSheet) -> list[Finding]:
    """Does each column add up to the total printed beneath it?

    Fund II's 23Q4 column does not, and the reason is in the label: the row is
    `TOTAL (active)`, and a position realised in May 2024 has been removed from a
    December 2023 total. That is INV-7 — held-at-date is not active-today —
    appearing unprompted in the source data rather than as a hypothetical.
    """
    out: list[Finding] = []
    for period in sheet.period_labels:
        stated = sheet.stated_totals.get(period)
        if stated is None:
            continue
        computed = sheet.cells_total(period)
        if computed != stated:
            contributors = [
                m.company for m in sheet.marks if m.period_label == period and m.amount is not None
            ]
            out.append(
                Finding(
                    kind=FindingKind.STATED_TOTAL_DISAGREES_WITH_CELLS,
                    subject=f"{sheet.fund_label} · {period}",
                    detail=(
                        f"the column sums to {computed:,} across {len(contributors)} "
                        f"positions ({', '.join(contributors)}) but the sheet states "
                        f"{stated:,}"
                    ),
                    stated=stated,
                    computed=computed,
                )
            )
    return out


def check_stated_cost_total(sheet: TrackerSheet) -> list[Finding]:
    stated = sheet.stated_cost_total
    if stated is None:
        return []
    computed = sum(sheet.cost_basis.values(), Decimal(0))
    if computed == stated:
        return []
    return [
        Finding(
            kind=FindingKind.COST_TOTAL_DISAGREES_WITH_CELLS,
            subject=f"{sheet.fund_label} · cost basis",
            detail=f"the column sums to {computed:,} but the sheet states {stated:,}",
            stated=stated,
            computed=computed,
        )
    ]


def check_tranche_arithmetic(tranches: list[Tranche]) -> list[Finding]:
    """Does each tranche's own price x count reproduce its stated investment?"""
    out: list[Finding] = []
    for t in tranches:
        implied = t.implied_cost
        if implied is None or implied == t.investment:
            continue
        out.append(
            Finding(
                kind=FindingKind.TRANCHE_ARITHMETIC_DISAGREES,
                subject=f"{t.company} · {t.acquired}",
                detail=(
                    f"{t.share_count:,} shares at {t.share_price} is {implied:,}, "
                    f"but the sheet states an investment of {t.investment:,}"
                ),
                stated=t.investment,
                computed=implied,
            )
        )
    return out


def check_recognised_kinds(tranches: list[Tranche]) -> list[Finding]:
    """Surface any row type this reader does not understand.

    Silence here is what produced both earlier false findings: an exit counted as
    cost, then a convertible note excluded from it. An unfamiliar kind must be
    reported, not resolved by whichever default happens to be in the code.
    """
    return [
        Finding(
            kind=FindingKind.UNRECOGNISED_TRANCHE_KIND,
            subject=f"{t.company} · {t.acquired_text or t.acquired}",
            detail=(
                f"row type {t.kind!r} is neither an investment nor an exit; "
                f"its {t.investment:,} has been left out of every total"
            ),
        )
        for t in tranches
        if not t.is_recognised
    ]


def check_cost_basis_across_workbooks(
    sheets: list[TrackerSheet], tranches: list[Tranche]
) -> list[Finding]:
    """The two workbooks state cost twice. They must agree.

    The valuation tracker carries one cost-basis figure per company; the master
    breakdown carries the tranches that make it up. Neither is authoritative over
    the other — a disagreement is a question for the fund, not something to
    resolve by preferring a file.
    """
    by_company: dict[str, Decimal] = {}
    for t in tranches:
        # Exits carry proceeds in the same column as purchases carry cost.
        if not t.is_investment:
            continue
        by_company[t.company] = by_company.get(t.company, Decimal(0)) + t.investment

    out: list[Finding] = []
    for sheet in sheets:
        for company, stated in sheet.cost_basis.items():
            computed = by_company.get(company)
            if computed is None or computed == stated:
                continue
            out.append(
                Finding(
                    kind=FindingKind.COST_BASIS_DISAGREES_ACROSS_WORKBOOKS,
                    subject=company,
                    detail=(
                        f"the valuation tracker states {stated:,}; the master breakdown "
                        f"tranches sum to {computed:,}"
                    ),
                    stated=stated,
                    computed=computed,
                )
            )
    return out


def check_marks_held_at_cost(sheets: list[TrackerSheet], tranches: list[Tranche]) -> list[Finding]:
    """A position marked at cost while its own later round says otherwise.

    Fluidstack is the case: 100,000 shares at $10 in October 2024 and 100,000 at
    $15 in May 2025. From 25Q2 the tracker still carries $2,500,000 — exactly
    cost — while the fund's own second tranche prices the same security at $15,
    which across 200,000 shares is $3,000,000.

    This is **not** an assertion that the mark is wrong. Holding at cost can be
    the correct treatment. It is a flag that the tracker figure and the fund's
    own most recent transaction imply different values, which is precisely what
    an auditor asks about — and which nothing in the workbook currently records.
    """
    out: list[Finding] = []
    by_company: dict[str, list[Tranche]] = {}
    for t in tranches:
        by_company.setdefault(t.company, []).append(t)

    for company, lots in by_company.items():
        priced = [
            t
            for t in lots
            if t.is_investment and t.share_price is not None and t.share_count is not None
        ]
        dated = [t for t in priced if t.acquired is not None]
        if len(priced) < 2 or not dated:
            continue
        latest = max(dated, key=lambda t: t.acquired or date.min)
        assert latest.share_price is not None
        shares = sum((t.share_count or Decimal(0)) for t in priced)
        at_latest_round = shares * latest.share_price
        cost = sum(t.investment for t in priced)
        if at_latest_round == cost:
            continue
        for sheet in sheets:
            for period in sheet.period_labels:
                amount = sheet.amount(company, period)
                if amount is None or amount != cost:
                    continue
                out.append(
                    Finding(
                        kind=FindingKind.MARK_HELD_AT_COST_WHILE_LATER_ROUND_EXISTS,
                        subject=f"{company} · {period}",
                        detail=(
                            f"carried at {amount:,}, which equals total cost; the fund's own "
                            f"{latest.acquired} tranche prices the security at "
                            f"{latest.share_price}, implying {at_latest_round:,} "
                            f"across {shares:,} shares"
                        ),
                        stated=amount,
                        computed=at_latest_round,
                    )
                )
    return out


def reconcile(sheets: list[TrackerSheet], tranches: list[Tranche]) -> list[Finding]:
    """Every check, in one pass."""
    findings: list[Finding] = []
    for sheet in sheets:
        findings += check_stated_totals(sheet)
        findings += check_stated_cost_total(sheet)
    findings += check_recognised_kinds(tranches)
    findings += check_tranche_arithmetic(tranches)
    findings += check_cost_basis_across_workbooks(sheets, tranches)
    findings += check_marks_held_at_cost(sheets, tranches)
    return findings
