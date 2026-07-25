"""Fixtures shared by the tracker ingest and tracker mark tests.

Extracted rather than duplicated: two copies of a tranche builder is two places
for a fixture to drift, and a wrong fixture has already failed two regression
tests on this project while the code under them was right.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from ingest.trackers.findings import FindingKind
from ingest.trackers.read import TrackerMark, TrackerSheet, Tranche, _as_range
from ingest.trackers.reconcile import reconcile

TRACKERS = Path("7GC Audit Case Study/01_Internal Trackers")
VALUATION = TRACKERS / "Funds I & II - Valuation Tracker (Case Study).xlsx"
MASTER = TRACKERS / "Master Investment Breakdown - Funds I & II (Case Study).xlsx"
needs_workbooks = pytest.mark.skipif(
    not (VALUATION.exists() and MASTER.exists()),
    reason="case-study workbooks are not in the repository",
)


def _tranche(
    kind: str,
    investment: str = "1000",
    text: str | None = None,
    fund: str = "Fund II",
    price: str | None = None,
    count: str | None = None,
    sheet: str | None = None,
    company: str = "X",
) -> Tranche:
    rng = _as_range(text) if text else None
    return Tranche(
        company=company,
        fund=fund,
        kind=kind,
        investment=Decimal(investment),
        entry_valuation=None,
        share_price=Decimal(price) if price is not None else None,
        share_count=Decimal(count) if count is not None else None,
        # A cell naming one day is the only form `Lot.acquired_date` can take;
        # everything else stays None, which is what the reader itself does.
        acquired=rng[0] if rng is not None and rng[0] == rng[1] else None,
        acquired_text=text,
        acquired_range=rng,
        source_sheet=sheet,
    )


def _priced(
    company: str, inv: str, price: str, count: str, text: str, fund: str = "Fund II"
) -> Tranche:
    return Tranche(
        company=company,
        fund=fund,
        kind="Fund",
        investment=Decimal(inv),
        entry_valuation=None,
        share_price=Decimal(price),
        share_count=Decimal(count),
        acquired=None,
        acquired_text=text,
        acquired_range=_as_range(text),
    )


def _unpriced(company: str, inv: str, text: str, fund: str = "Fund II") -> Tranche:
    """A convertible note: real money, no share price and no share count."""
    return Tranche(
        company=company,
        fund=fund,
        kind="Fund (Conv. Note)",
        investment=Decimal(inv),
        entry_valuation=None,
        share_price=None,
        share_count=None,
        acquired=None,
        acquired_text=text,
        acquired_range=_as_range(text),
    )


def _sheet(
    fund_label: str, company: str, marks: dict[str, str], cost: str | None = None
) -> TrackerSheet:
    return TrackerSheet(
        fund_label=fund_label,
        period_labels=list(marks),
        companies=[company],
        cost_basis={company: Decimal(cost)} if cost is not None else {},
        marks=[TrackerMark(company, p, Decimal(v)) for p, v in marks.items()],
        stated_totals={p: Decimal(v) for p, v in marks.items()},
    )


def _kinds(sheets: list[TrackerSheet], tranches: list[Tranche]) -> list[FindingKind]:
    return [f.kind for f in reconcile(sheets, tranches)]


#: The kinds that assert something about a valuation. A check that reports only
#: "this could not be determined" has not made a claim about a mark.
_VALUATION_KINDS = {
    FindingKind.MARK_AT_COST_DISAGREES_WITH_PURCHASE_PRICES,
    FindingKind.MARK_BASIS_NOT_IN_WORKBOOKS,
    FindingKind.MARK_BASIS_ASSUMES_AN_UNSTATED_TREATMENT,
}
