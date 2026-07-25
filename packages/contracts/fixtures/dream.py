"""The Dream vertical slice — hand-written, and checked against the oracle.

This fixture is three things at once: the interface contract every later module
builds against, the specification of the Step 4 end-to-end slice, and the first
real test of whether `packages/contracts` can represent an actual holding rather
than merely type-check.

It is written **by hand**. Generating it from the pipeline would make it agree
with whatever the pipeline does, which is the one thing a fixture must not do.
`tests/test_dream_fixture.py` then checks every figure against
`evals/oracle/derived.json`, which is derived independently of production code —
so the fixture cannot drift quietly, and cannot be "fixed" by changing the thing
it is supposed to be testing.

Why Dream is the right slice
----------------------------
At 2025-12-31 the tracker reports **$5,000,000**. That number is reachable:
625,000 shares × $8.00 from the Series B cap table is exactly $5,000,000. It
reconciles, it renders, and it is **wrong to rely on**, for three independent
reasons that the packet has to state separately:

1. The lot is **Series A-1**. The only price in the corpus is for **Series B**.
   Applying it across classes is a valuation *policy* act requiring a cited
   decision — which does not exist here — so the mark is `not_derivable` with
   reason `NO_PRICE_FOR_CLASS:series_a1`, not "derivable and equal to $5m".
2. Both supporting documents are **unexecuted**: a `pro_forma` cap table and a
   closing email that references a set which has not closed.
3. The Series A-1 acquisition documents are **not located**, so existence and
   cost (R1) is `missing` — the position's own basis is unevidenced.

So this single holding exercises INV-13 (reported ≠ validated ≠ supported),
INV-17 (cross-class pricing), INV-4 (executed ≠ pro forma), INV-12 (why a
document is absent) and INV-19 (a total that must not launder this figure) —
and it is a real position from the corpus, not a constructed edge case.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from packages.contracts.enums import (
    AuditScope,
    DecisionType,
    DerivationStatus,
    ExecutionStatus,
    GapKind,
    PositionType,
    RequirementCode,
    RequirementVerdict,
    SourceClass,
)
from packages.contracts.models import (
    Claim,
    EvidenceCitation,
    GapObservation,
    HoldingRow,
    Lot,
    Mark,
    Money,
    Packet,
    Period,
    RequirementAssessment,
)

MEASUREMENT_DATE = date(2025, 12, 31)


def usd(v: str) -> Money:
    return Money(amount=Decimal(v), currency="USD")


#: The position. 625,000 Series A-1 shares at $3.20, acquired 2025-08-01.
DREAM_LOT = Lot(
    id="dream_1",
    holding_id="dream",
    security_class="series_a1",
    shares=Decimal(625000),
    entry_pps=Decimal("3.20"),
    cost=usd("2000000"),
    acquired_date=date(2025, 8, 1),
)

#: INV-4 · a pro-forma cap table is not an executed transaction document.
DREAM_B_CAP = Claim(
    id="dream_b_cap",
    document_version_id="dv_dream_b_captable",
    holding_id="dream",
    claim_key="dream/series_b_price",
    source_class=SourceClass.COMPANY_CAP_TABLE,
    execution_status=ExecutionStatus.PRO_FORMA,
    issued_date=date(2025, 11, 14),
    applicable_from=date(2025, 11, 14),
    priced_class="series_b",
    price_per_share=Decimal("8.00"),
)

#: INV-15 · authority lives on the claim. This one *references* a closing that
#: has not happened, which is weaker than the cap table beside it, not stronger
#: for arriving later.
DREAM_CLOSE_EMAIL = Claim(
    id="dream_close_email",
    document_version_id="dv_dream_closing_email",
    holding_id="dream",
    claim_key="dream/series_b_price",
    source_class=SourceClass.COMPANY_COMMUNICATION,
    execution_status=ExecutionStatus.UNEXECUTED_REFERENCED,
    issued_date=date(2025, 11, 17),
    applicable_from=date(2025, 11, 17),
    priced_class="series_b",
    price_per_share=Decimal("8.00"),
)

#: INV-12 · *why* it is absent decides what the auditor does next. `not_located`
#: is a request to the company; `with_counsel` would not be.
DREAM_R1_GAP = GapObservation(
    id=1,
    holding_id="dream",
    requirement=RequirementCode.R1,
    security_class="series_a1",
    missing_document="Series A-1 acquisition docs",
    kind=GapKind.NOT_LOCATED,
    source_quote="no executed acquisition document in corpus",
)

#: INV-13 · the tracker figure is retained as *reported*. No validated amount
#: exists, because the only available price belongs to a class this lot is not.
#: The temptation this refuses: 625,000 × $8.00 = $5,000,000 exactly.
DREAM_MARK = Mark(
    id=1,
    holding_id="dream",
    period_id="f2_25q4",
    revision=1,
    reported=usd("5000000"),
    validated=None,
    derivation_status=DerivationStatus.NOT_DERIVABLE,
    derivation_reason="NO_PRICE_FOR_CLASS:series_a1",
)

DREAM_ASSESSMENTS = [
    RequirementAssessment(
        requirement=RequirementCode.R1,
        applicable=True,
        verdict=RequirementVerdict.MISSING,
        reason_codes=["ACQUISITION_DOCS_NOT_LOCATED"],
        next_actions=["REQUEST_FROM_COMPANY"],
        policy_version="v1",
    ),
    RequirementAssessment(
        requirement=RequirementCode.R2,
        applicable=True,
        verdict=RequirementVerdict.PARTIAL,
        reason_codes=[
            "CLOSING_SET_PENDING",
            "CROSS_CLASS_POLICY_DECISION_REQUIRED",
            "PRO_FORMA_PENDING_EXECUTION",
        ],
        next_actions=["RECORD_VALUATION_POLICY_DECISION"],
        evidence=[
            EvidenceCitation(claim=DREAM_B_CAP, is_subsequent=False),
            EvidenceCitation(claim=DREAM_CLOSE_EMAIL, is_subsequent=False),
        ],
        pro_forma=True,
        policy_version="v1",
    ),
    # R3 is inapplicable because the value CHANGED since 2025-09-30 — calibration
    # of an unchanged mark is a different question that does not arise here.
    RequirementAssessment(
        requirement=RequirementCode.R3,
        applicable=False,
        verdict=RequirementVerdict.NOT_APPLICABLE,
        reason_codes=["VALUE_CHANGED_SINCE_2025-09-30"],
        policy_version="v1",
    ),
    # R4 is realisation support; nothing was realised.
    RequirementAssessment(
        requirement=RequirementCode.R4,
        applicable=False,
        verdict=RequirementVerdict.NOT_APPLICABLE,
        reason_codes=["NO_REALISATION_IN_PERIOD"],
        policy_version="v1",
    ),
    # R5 is a LABELLING requirement, and it is satisfied: the pro-forma nature of
    # the evidence is disclosed. INV-4 — labelling something correctly is not the
    # same as it being sufficient support, which is why R5 can be `sufficient`
    # on a row whose overall verdict is `missing`.
    RequirementAssessment(
        requirement=RequirementCode.R5,
        applicable=True,
        verdict=RequirementVerdict.SUFFICIENT,
        reason_codes=[],
        policy_version="v1",
    ),
]

DREAM_ROW = HoldingRow(
    holding_id="dream",
    company_name="Dream",
    position_type=PositionType.DIRECT_EQUITY,
    mark=DREAM_MARK,
    assessments=DREAM_ASSESSMENTS,
    gaps=[DREAM_R1_GAP],
    # INV-10 · no approval. Nothing here is approvable: R1 is missing and R2 is
    # partial. A row can be complete, rendered and exported and still carry no
    # approval — that is the packet telling the truth, not a missing feature.
    approval=None,
)

FY2025_Q4 = Period(
    id="f2_25q4",
    fund_id="fund_ii",
    period_date=MEASUREMENT_DATE,
    audit_scope=AuditScope.PACKET,
    label="FY2025 Q4",
)


def dream_packet() -> Packet:
    """A one-row packet. Its total is $5,000,000 and *all* of it is unsupported."""
    return Packet(
        fund_id="fund_ii",
        period=FY2025_Q4,
        rows=[DREAM_ROW],
        schema_version="1",
        policy_version="v1",
        generated_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
    )


#: What a reviewer must have decided before this row could ever be approved.
#: Recorded here as prose because the decision does not exist: no cross-class
#: policy decision has been cited, so INV-17 blocks approval at the database.
BLOCKED_ON = (
    "A cited valuation policy decision permitting series_b pricing to be applied "
    "to a series_a1 lot, plus executed Series B closing documents, plus located "
    "Series A-1 acquisition documents."
)

__all__ = [
    "BLOCKED_ON",
    "DREAM_ASSESSMENTS",
    "DREAM_B_CAP",
    "DREAM_CLOSE_EMAIL",
    "DREAM_LOT",
    "DREAM_MARK",
    "DREAM_R1_GAP",
    "DREAM_ROW",
    "FY2025_Q4",
    "MEASUREMENT_DATE",
    "DecisionType",
    "dream_packet",
]
