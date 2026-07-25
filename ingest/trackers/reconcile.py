"""Reconcile the workbooks against themselves and against each other.

Every finding here is a disagreement between two things the fund already
asserts. That matters for tone: the output is not "your numbers are wrong", it
is "these two statements cannot both be true, and here is the arithmetic." An
auditor can act on the second and will argue with the first.

Findings carry a `kind` from a closed vocabulary rather than free text, so the
packet can group them without parsing prose (INV-2 — a finding is a member of a
set, not a severity number). The vocabulary itself lives in `findings.py`, and
the checks that compare marks against purchases live in `marks.py`.

This module holds the checks a sheet or a tranche can answer on its own, plus
the one pass that runs everything.
"""

from __future__ import annotations

from decimal import Decimal

from ingest.trackers.findings import Finding, FindingKind, _fund_of, _period_scope
from ingest.trackers.marks import MARK_CHECKS
from ingest.trackers.read import TrackerSheet, Tranche, company_key


def check_stated_totals(sheet: TrackerSheet) -> list[Finding]:
    """Does each column add up to the total printed beneath it?

    Fund II's 23Q4 column does not, and the reason is in the label: the row is
    `TOTAL (active)`, and a position realised in May 2024 has been removed from a
    December 2023 total. That is INV-7 — held-at-date is not active-today —
    appearing unprompted in the source data rather than as a hypothetical.
    """
    out: list[Finding] = []
    missing = [p for p in sheet.period_labels if p not in sheet.stated_totals]
    if missing and sheet.companies:
        # A renamed footer ("Sum (active)") or an absent one leaves nothing to
        # compare against, and every period is skipped in silence. The whole
        # point of this check is the stated total, so its absence is a finding.
        out.append(
            Finding(
                kind=FindingKind.NO_STATED_TOTAL_TO_CHECK,
                subject=f"{sheet.fund_label} · {', '.join(missing)}",
                detail=(
                    f"{len(sheet.companies)} positions were read but no stated total was "
                    f"found for {len(missing)} period(s), so nothing was checked against them"
                ),
            )
        )
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
                    scope=_period_scope(_fund_of(sheet.fund_label), period),
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
        # An exit's "Investment ($)" column holds PROCEEDS, and its price and
        # count describe the shares sold. Checking price x count against it asks
        # a question with no meaning and reports the answer as a discrepancy.
        if not t.is_investment:
            continue
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
    # Keyed by (fund, company): the same company can appear in both funds, and
    # merging them reports two correct fund-level costs as a disagreement.
    by_company: dict[tuple[str | None, str], Decimal] = {}
    for t in tranches:
        # Exits carry proceeds in the same column as purchases carry cost.
        if not t.is_investment:
            continue
        key = (_fund_of(t.fund), company_key(t.company))
        by_company[key] = by_company.get(key, Decimal(0)) + t.investment

    out: list[Finding] = []
    for sheet in sheets:
        fund = _fund_of(sheet.fund_label)
        for company, stated in sheet.cost_basis.items():
            computed = by_company.get((fund, company_key(company)))
            if computed is None:
                # Silence is not agreement. A tab named "Fluid Stack" while the
                # tracker says "Fluidstack" makes the join produce nothing, and
                # the report then reads clean because the two statements were
                # never compared at all.
                out.append(
                    Finding(
                        kind=FindingKind.COST_BASIS_NEVER_COMPARED,
                        subject=company,
                        detail=(
                            f"the valuation tracker states {stated:,} but no master-breakdown "
                            "sheet matched this company, so the two were never compared"
                        ),
                        stated=stated,
                    )
                )
                continue
            if computed == stated:
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

    tracked = {(_fund_of(s.fund_label), company_key(c)) for s in sheets for c in s.cost_basis}
    for (fund, company), computed in sorted(by_company.items(), key=lambda kv: str(kv[0])):
        if (fund, company) not in tracked:
            out.append(
                Finding(
                    kind=FindingKind.COST_BASIS_NEVER_COMPARED,
                    subject=f"{fund} · {company}" if fund else company,
                    detail=(
                        f"the master breakdown states {computed:,} of investment but this "
                        "company has no cost-basis row in the valuation tracker"
                    ),
                    computed=computed,
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
    for check in MARK_CHECKS:
        findings += check(sheets, tranches)
    return findings
