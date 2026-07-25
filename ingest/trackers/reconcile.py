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
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from ingest.trackers.read import TrackerSheet, Tranche

#: A gap smaller than this fraction of the implied value is not worth an
#: auditor's attention. Named rather than inlined so it is reviewable, and set
#: deliberately tight — this layer reports, it does not decide.
_MATERIALITY = Decimal("0.001")


class FindingKind(StrEnum):
    STATED_TOTAL_DISAGREES_WITH_CELLS = "stated_total_disagrees_with_cells"
    COST_TOTAL_DISAGREES_WITH_CELLS = "cost_total_disagrees_with_cells"
    TRANCHE_ARITHMETIC_DISAGREES = "tranche_arithmetic_disagrees"
    COST_BASIS_DISAGREES_ACROSS_WORKBOOKS = "cost_basis_disagrees_across_workbooks"
    UNRECOGNISED_TRANCHE_KIND = "unrecognised_tranche_kind"
    COST_BASIS_NEVER_COMPARED = "cost_basis_never_compared"
    NO_STATED_TOTAL_TO_CHECK = "no_stated_total_to_check"
    MARK_DIVERGES_FROM_LATER_ROUND = "mark_diverges_from_later_round"
    LATEST_ROUND_IS_AMBIGUOUS = "latest_round_is_ambiguous"
    MARK_BASIS_NOT_IN_WORKBOOKS = "mark_basis_not_in_workbooks"
    UNRECOGNISED_PERIOD_LABEL = "unrecognised_period_label"
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
        key = (_fund_of(t.fund), t.company)
        by_company[key] = by_company.get(key, Decimal(0)) + t.investment

    out: list[Finding] = []
    for sheet in sheets:
        fund = _fund_of(sheet.fund_label)
        for company, stated in sheet.cost_basis.items():
            computed = by_company.get((fund, company))
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

    tracked = {(_fund_of(s.fund_label), c) for s in sheets for c in s.cost_basis}
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


def _fund_of(label: str | None) -> str | None:
    """Normalise `Fund II Holdings by Quarter` and `Fund II` to one key."""
    if not label:
        return None
    text = label.strip()
    for name in ("Fund II", "Fund I"):
        if text.startswith(name):
            return name
    return text


def _period_end(label: str) -> date | None:
    """The last day of a tracker period label — `25Q4`, `FY2024`.

    Returned rather than assumed so a label this reader does not understand
    disables the anachronism guard loudly (None) instead of quietly comparing
    against the wrong date.
    """
    text = label.strip().upper()
    if text.startswith("FY") and text[2:].isdigit():
        return date(int(text[2:]), 12, 31)
    if len(text) == 4 and text[2] == "Q" and text[:2].isdigit() and text[3].isdigit():
        year = 2000 + int(text[:2])
        month = int(text[3]) * 3
        return date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return None


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
        if len(priced) < 2:
            continue

        # Order by the LATEST day each tranche could have occurred. Keying on an
        # exact date alone dropped any month-only tranche out of the running, so
        # a later imprecise round lost to an earlier precise one and the whole
        # check went silent — the range parsing existed but nothing used it.
        def upper(t: Tranche) -> date | None:
            return t.acquired_range[1] if t.acquired_range else None

        ranked = [t for t in priced if upper(t) is not None]
        if not ranked:
            continue
        latest = max(ranked, key=lambda t: upper(t) or date.min)
        assert latest.share_price is not None

        # If another tranche's range overlaps the winner's, "most recent" is not
        # decidable from the source and must not be guessed.
        low = latest.acquired_range[0] if latest.acquired_range else date.min
        contested = [t for t in ranked if t is not latest and (upper(t) or date.min) >= low]
        if contested:
            out.append(
                Finding(
                    kind=FindingKind.LATEST_ROUND_IS_AMBIGUOUS,
                    subject=company,
                    detail=(
                        "which tranche is most recent cannot be determined: "
                        + "; ".join(
                            f"{t.acquired_text} at {t.share_price}" for t in [latest, *contested]
                        )
                    ),
                )
            )
            continue

        shares = sum((t.share_count or Decimal(0)) for t in priced)
        at_latest_round = shares * latest.share_price
        cost = sum(t.investment for t in priced)
        if at_latest_round == cost:
            continue

        unreadable: set[str] = set()
        for sheet in sheets:
            for period in sheet.period_labels:
                amount = sheet.amount(company, period)
                if amount is None:
                    continue
                # A round cannot inform a mark struck before it happened.
                # Without this, Fluidstack's Dec-2024 mark was compared against a
                # May-2025 tranche and reported as diverging from a price that
                # did not yet exist.
                measured = _period_end(period)
                if measured is None:
                    # Failing open here silently re-enabled the anachronism this
                    # guard exists to prevent: an unreadable label meant "no date
                    # constraint" rather than "cannot check".
                    unreadable.add(period)
                    continue
                # 3 · use the three-state answer the range was built for. `low >
                # measured` treated a tranche whose range merely STARTS before
                # the measurement date as definitely acquired by then.
                if latest.held_by(measured) is not True:
                    continue
                # Exact equality with cost was a brittle proxy. A mark one dollar
                # off, or stale, escaped entirely — so the check silently stopped
                # firing on precisely the sloppy data it exists to catch. What
                # matters is a material gap between the carried figure and what
                # the fund's own latest round implies.
                gap = at_latest_round - amount
                if gap == 0 or abs(gap) < at_latest_round * _MATERIALITY:
                    continue
                # A PURCHASE price is not a ROUND price. The Mom Project is
                # marked at 2,750,000 on a Series C basis named only in a
                # documentation line this reader does not parse; comparing
                # against the last purchase ($5.00) produced three confident
                # false discrepancies. So a mark that matches neither cost nor
                # the last purchase is reported as a basis we cannot verify —
                # which is true — rather than as a disagreement, which is not.
                at_cost = amount == cost
                out.append(
                    Finding(
                        kind=(
                            FindingKind.MARK_HELD_AT_COST_WHILE_LATER_ROUND_EXISTS
                            if at_cost
                            else FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS
                        ),
                        subject=f"{company} · {period}",
                        detail=(
                            f"carried at {amount:,}"
                            + (
                                ", which equals total cost, while the fund's own "
                                if at_cost
                                else ", which matches neither cost nor the fund's own "
                            )
                            + f"{latest.acquired_text} purchase at {latest.share_price} "
                            f"({at_latest_round:,} across {shares:,} shares); "
                            + (
                                "the later purchase implies a higher value"
                                if at_cost
                                else "the basis is not stated in these workbooks"
                            )
                        ),
                        stated=amount,
                        computed=at_latest_round,
                    )
                )
        if unreadable:
            out.append(
                Finding(
                    kind=FindingKind.UNRECOGNISED_PERIOD_LABEL,
                    subject=company,
                    detail=(
                        f"period label(s) {', '.join(sorted(unreadable))} could not be dated, "
                        "so no mark for them was checked against later rounds"
                    ),
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
