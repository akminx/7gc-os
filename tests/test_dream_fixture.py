"""The hand-written fixture must agree with the independently-derived oracle.

The fixture is written by hand so it can disagree. The oracle derives the same
figures from `evals/oracle/primitives.yaml` and imports nothing from the
application. Where they agree, two independent routes reached the same answer.
Where they disagree, one of them is wrong and the diff says which fields.

This is the closing of the loop: the contracts can be checked against something
that was not built from them.
"""

from __future__ import annotations

import json
import pathlib
from decimal import Decimal

from packages.contracts.enums import RequirementCode, RequirementVerdict
from packages.contracts.fixtures.dream import DREAM_LOT, DREAM_ROW, dream_packet
from packages.contracts.models import TotalKind

ORACLE = json.loads((pathlib.Path("evals/oracle/derived.json")).read_text())
ROWS = ORACLE.get("rows", ORACLE)
DREAM = next(
    r
    for r in ROWS
    if isinstance(r, dict) and r.get("holding") == "dream" and r.get("date") == "2025-12-31"
)


def test_reported_amount_matches_the_oracle() -> None:
    assert DREAM_ROW.mark.reported.amount == Decimal(DREAM["reported_amount"])


def test_the_mark_is_not_derivable_for_the_reason_the_oracle_gives() -> None:
    """625,000 x $8.00 is exactly $5,000,000 — and the price belongs to Series B
    while the lot is Series A-1, so the arithmetic that works is the arithmetic
    nobody is entitled to do."""
    assert DREAM_ROW.mark.validated is None
    assert DREAM["validated_amount"] is None
    assert DREAM_ROW.mark.derivation_status.value == DREAM["derivation_status"]
    assert DREAM_ROW.mark.derivation_reason == DREAM["derivation_reason"]
    assert DREAM_LOT.shares is not None
    assert DREAM_LOT.shares * Decimal("8.00") == DREAM_ROW.mark.reported.amount


def test_every_requirement_verdict_matches_the_oracle() -> None:
    got = {a.requirement.value: a.verdict.value for a in DREAM_ROW.assessments}
    want = {k: v["verdict"] for k, v in DREAM["requirements"].items()}
    assert got == want


def test_applicability_matches_the_oracle_count() -> None:
    assert sum(1 for a in DREAM_ROW.assessments if a.applicable) == DREAM["applicable_count"]
    assert (
        sum(
            1
            for a in DREAM_ROW.assessments
            if a.applicable and a.verdict is RequirementVerdict.SUFFICIENT
        )
        == DREAM["sufficient_count"]
    )


def test_r2_reason_codes_match_the_oracle() -> None:
    r2 = next(a for a in DREAM_ROW.assessments if a.requirement is RequirementCode.R2)
    assert sorted(r2.reason_codes) == sorted(DREAM["requirements"]["R2"]["reasons"])
    assert [e.claim.id for e in r2.evidence] == DREAM["requirements"]["R2"]["relied_on"]


def test_the_row_is_unsupported_and_the_oracle_agrees() -> None:
    assert DREAM_ROW.supported is False
    assert DREAM["fully_supported"] is False


def test_r5_is_sufficient_on_a_row_whose_overall_verdict_is_missing() -> None:
    """A labelling requirement can be met on a position with no support at all.
    Collapsing those would force the packet to either hide the label or imply
    the mark is evidenced."""
    r5 = next(a for a in DREAM_ROW.assessments if a.requirement is RequirementCode.R5)
    assert r5.verdict is RequirementVerdict.SUFFICIENT
    assert DREAM["row_verdict"] == "missing"


def test_the_packet_total_is_entirely_unsupported() -> None:
    """INV-19 · $5,000,000 reported, $5,000,000 of it unsupported. A total that
    printed only the first number would be the laundering this forbids."""
    totals = dream_packet().totals()
    assert totals.kind is TotalKind.HELD_AT_DATE_REPORTED
    assert totals.amount.amount == Decimal("5000000")
    assert totals.unsupported_amount.amount == Decimal("5000000")
    assert totals.unsupported_positions == 1
    assert totals.contains_unsupported_inputs is True


def test_the_row_carries_no_approval() -> None:
    """Nothing here is approvable, and the fixture must not invent one."""
    assert DREAM_ROW.approval is None
    assert DREAM_ROW.approved is False
