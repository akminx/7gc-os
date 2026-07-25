"""Do the two independent paths to the same numbers agree?

The oracle derives from `evals/oracle/primitives.yaml`, hand-transcribed from
the source by a human. The reader parses the actual `.xlsx`. Until this file
existed the two had **never been compared**, which meant a transcription error
would have anchored every oracle assertion to a fiction, and a reader error
would have anchored every reconciler finding to one — with nothing able to tell
the difference.

They agree, 6 of 6, everywhere they overlap. That is worth keeping true.

Skipped when the workbooks are absent, like every other real-data test here.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from ingest.trackers.read import read_master_breakdown, read_valuation_tracker
from ingest.trackers.snapshot import MASTER, VALUATION, workbooks_present

needs_workbooks = pytest.mark.skipif(
    not workbooks_present(), reason="case-study workbooks are not in the repository"
)

ORACLE = Path(__file__).resolve().parent.parent / "evals/oracle/derived.json"

#: The oracle names funds and dates its own way; the tracker uses column labels.
#: Stated explicitly rather than inferred, so a new period cannot silently map
#: onto the wrong column.
SHEET_OF = {"fund_ii": "Fund II Holdings by Quarter", "fund_i": "Fund I Holdings by Year"}
LABEL_OF = {
    ("fund_ii", "2023-12-31"): "23Q4",
    ("fund_ii", "2024-12-31"): "24Q4",
    ("fund_ii", "2025-12-31"): "25Q4",
    ("fund_i", "2023-12-31"): "FY2023",
    ("fund_i", "2024-12-31"): "FY2024",
    ("fund_i", "2025-12-31"): "FY2025",
}


@needs_workbooks
def test_the_oracle_and_the_reader_agree_on_every_stated_total() -> None:
    """The load-bearing cross-check. A hand-transcribed figure and a parsed one,
    compared for the first time."""
    oracle = json.loads(ORACLE.read_text())
    sheets = {s.fund_label: s for s in read_valuation_tracker(VALUATION)}

    compared = 0
    for total in oracle["totals"]:
        key = (total["fund"], total["date"])
        assert key in LABEL_OF, f"oracle covers {key} but this test has no tracker label for it"
        sheet = sheets[SHEET_OF[total["fund"]]]
        stated = sheet.stated_totals[LABEL_OF[key]]
        assert stated == Decimal(str(total["tracker_stated_total"])), (
            f"{total['fund']} {total['date']}: the oracle transcribed "
            f"{total['tracker_stated_total']} where the workbook states {stated}"
        )
        compared += 1
    assert compared == 6, "the oracle's coverage changed — update LABEL_OF deliberately"


@needs_workbooks
def test_the_oracle_and_the_reader_agree_lot_by_lot() -> None:
    """Per lot, not in aggregate.

    The first version of this test summed both sides and compared the totals,
    while its name promised lot-level agreement. Raising one oracle lot by a
    dollar and lowering another by a dollar left the assertion input unchanged —
    a compensating pair of transcription errors would have passed, which is
    exactly the failure a cross-check exists to catch.
    """
    oracle = json.loads(ORACLE.read_text())
    # Entry costs cover only lots stating both a price and a share count,
    # because the table exists to check `shares x pps = stated cost`. Match on
    # that arithmetic rather than on lot ids, which the two sides name
    # differently (`fluid_1` against a company and a date).
    transcribed = sorted(
        (Decimal(str(e["shares"])), Decimal(str(e["entry_pps"])), Decimal(str(e["stated"])))
        for e in oracle["entry_costs"]
        if e.get("stated")
    )
    parsed = sorted(
        (t.share_count, t.share_price, t.investment)
        for t in read_master_breakdown(MASTER)
        if t.is_investment and t.share_count is not None and t.share_price is not None
    )
    # 14 priced lots on each side; the oracle's other 3 entry-cost rows carry no
    # stated cost because their instruments state no share price.
    assert len(transcribed) == len(parsed) == 14
    for (o_sh, o_px, o_cost), (r_sh, r_px, r_cost) in zip(transcribed, parsed, strict=True):
        assert (o_sh, o_px, o_cost) == (r_sh, r_px, r_cost), (
            f"the oracle transcribed {o_sh} x {o_px} = {o_cost}; "
            f"the reader parses {r_sh} x {r_px} = {r_cost}"
        )


@needs_workbooks
def test_the_unpriced_instruments_are_the_only_difference() -> None:
    """The two sides cover different row sets by design, and the gap must be
    exactly the instruments with no share price: Moonfare's 1,000,000 and The
    Mom Project's 250,000 note.

    Jio's 1,000,000 is in neither. Its row kind is `Indirect Fund`, which the
    reader does not recognise as an investment and reports rather than bucketing
    — writing 2,250,000 here, counting Jio, is the mistake this test caught on
    its first run, in the test rather than the code.
    """
    oracle = json.loads(ORACLE.read_text())
    parsed = sum(
        (t.investment for t in read_master_breakdown(MASTER) if t.is_investment), Decimal(0)
    )
    transcribed = sum(
        (Decimal(str(e["stated"])) for e in oracle["entry_costs"] if e.get("stated")), Decimal(0)
    )
    assert parsed - transcribed == Decimal("1250000")


@needs_workbooks
def test_the_oracle_covers_half_the_periods_the_reconciler_reports_on() -> None:
    """Not a defect — a scope boundary that must stay visible.

    The oracle validates year ends only: 6 of the 12 fund-periods the tracker
    carries. Findings at 25Q2, 25Q3, 26Q1, FY2021 and FY2022 therefore have no
    independent check. That is acceptable while it is *stated*; it stops being
    acceptable the moment someone reads a green suite as full coverage.
    """
    oracle = json.loads(ORACLE.read_text())
    sheets = read_valuation_tracker(VALUATION)
    tracker_periods = sum(len(s.period_labels) for s in sheets)
    assert tracker_periods == 12
    assert len(oracle["totals"]) == 6, (
        "the oracle's period coverage changed. If it grew, that is good — update this "
        "test and docs/ORACLE.md. If it shrank, findings lost their only cross-check."
    )
