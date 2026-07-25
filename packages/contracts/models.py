"""The wire contract between the database, the API and the browser.

These models are the interface every later module builds against, so the
distinctions `INVARIANTS.md` names have to survive serialisation. Two in
particular are easy to lose on the way out of the database and are therefore
structural here rather than conventional:

* **Money is never a bare number.** `Money` carries its currency, so a
  cross-currency sum is a type error rather than a plausible total (INV-11).
* **Reported, validated and supported are three fields.** A tracker figure, an
  independently recomputed figure and an evidence verdict are different facts
  about a mark. One holding in the corpus reproduces its arithmetic perfectly
  and has no evidence at all; a shape that renders that as one number is
  incapable of saying so (INV-13).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.contracts.enums import (
    AuditScope,
    DecisionStatus,
    DecisionType,
    DerivationStatus,
    ExecutionStatus,
    FactState,
    GapKind,
    GapRemediation,
    PositionType,
    RequirementCode,
    RequirementVerdict,
    SourceClass,
    ValuationBasis,
)


class Contract(BaseModel):
    """Frozen and strict: unknown fields are an error, not a silent drop.

    A tolerant parser is how a renamed field becomes a null downstream and then
    a zero in a total.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class Money(Contract):
    """An amount that knows its currency. INV-11.

    `Decimal` throughout — a float amount is wrong before anyone reads it.
    """

    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)

    def __add__(self, other: Money) -> Money:
        if self.currency != other.currency:
            raise ValueError(
                f"refusing to add {self.currency} to {other.currency}: "
                "a cross-currency sum needs a rate observed at the measurement date"
            )
        return Money(amount=self.amount + other.amount, currency=self.currency)


class Citation(Contract):
    """INV-8 · a source fact resolves VERBATIM to an immutable document version.

    The span is required. "The document says so somewhere" is not a citation an
    auditor can check, and a quote without offsets cannot be re-verified against
    a re-extracted text.
    """

    document_version_id: str
    quote: str = Field(min_length=1)
    span_start: int = Field(ge=0)
    span_end: int

    @model_validator(mode="after")
    def _span_is_ordered(self) -> Citation:
        if self.span_end <= self.span_start:
            raise ValueError("span_end must be greater than span_start")
        return self


class SourceFact(Contract):
    """A figure that appears verbatim in a document."""

    id: int
    claim_id: str
    field_name: str
    value_text: str
    value_numeric: Decimal | None = None
    state: FactState
    citation: Citation


class DerivedFigureInput(Contract):
    """A leaf of a computation: a cited fact, or another figure. Never neither."""

    ordinal: int
    fact: SourceFact | None = None
    child: DerivedFigure | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> DerivedFigureInput:
        if (self.fact is None) == (self.child is None):
            raise ValueError("an input is exactly one of a cited fact or a child figure")
        return self


class DerivedFigure(Contract):
    """INV-8 · a computed total appears verbatim in no document.

    It resolves through a typed computation whose complete leaf set is cited
    source facts. Presenting it as a quotable fact is the failure this splits.
    """

    id: int
    label: str
    operator: str
    value: Money
    inputs: list[DerivedFigureInput] = Field(default_factory=list)


class Claim(Contract):
    """INV-15 · authority lives on the claim, not the file.

    One PDF can carry several claims of differing authority. An administrator
    statement forwarded by email is an administrator statement; classifying by
    envelope mis-tiers the strongest evidence in the set.

    INV-3 · three distinct instants, never one `date`.
    """

    id: str
    document_version_id: str
    holding_id: str
    claim_key: str
    source_class: SourceClass
    execution_status: ExecutionStatus
    issued_date: date
    as_of_date: date | None = None
    received_date: date | None = None
    applicable_from: date
    applicable_to: date | None = None
    priced_class: str | None = None
    price_per_share: Decimal | None = None
    stated: Money | None = None
    supersedes_claim_id: str | None = None

    def applies_at(self, on: date) -> bool:
        """INV-16 · the source states its own reliance window.

        Capsule's memo forbids later reliance. Every date field can be correct
        and the link still invalid.
        """
        return self.applicable_from <= on and (
            self.applicable_to is None or on <= self.applicable_to
        )


class Lot(Contract):
    """INV-7 · held-at-date is computed from lots, never a mutable flag.

    A holding-level `active` boolean cannot represent a second tranche acquired
    later, or a partial realisation — both of which occur in the corpus.
    """

    id: str
    holding_id: str
    security_class: str
    shares: Decimal | None = None
    entry_pps: Decimal | None = None
    cost: Money
    acquired_date: date
    realized_date: date | None = None

    def held_at(self, on: date) -> bool:
        return self.acquired_date <= on and (self.realized_date is None or self.realized_date > on)


class LotConversion(Contract):
    """Sway's recapitalisation, recorded as an event so class-at-date survives."""

    lot_id: str
    effective_date: date
    to_security_class: str
    to_shares: Decimal
    exchange_ratio: Decimal


class EvidenceCitation(Contract):
    """A claim cited in support of a requirement, with its honest label."""

    claim: Claim
    is_subsequent: bool = False


class RequirementAssessment(Contract):
    """INV-2 · a per-requirement verdict, from a closed vocabulary.

    `reason_codes` is not decoration: a `partial` with no reason is an assertion
    the auditor cannot act on.
    """

    requirement: RequirementCode
    applicable: bool
    verdict: RequirementVerdict
    reason_codes: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    evidence: list[EvidenceCitation] = Field(default_factory=list)
    pro_forma: bool = False
    tracker_label: str | None = None
    policy_version: str

    @model_validator(mode="after")
    def _adverse_verdicts_state_a_reason(self) -> RequirementAssessment:
        adverse = {
            RequirementVerdict.MISSING,
            RequirementVerdict.INSUFFICIENT,
            RequirementVerdict.PARTIAL,
            RequirementVerdict.CONFLICTING,
        }
        if self.verdict in adverse and not self.reason_codes:
            raise ValueError(f"verdict {self.verdict} must carry at least one reason code")
        return self


class GapObservation(Contract):
    """INV-12 · why a document is absent, and what has been done about it.

    The observation is immutable; remediation is a separate history. Overwriting
    `with_counsel` with `not_located` is the cheapest collapse of this
    distinction — the gap reads resolved and the original finding is gone.
    """

    id: int
    holding_id: str
    requirement: RequirementCode
    security_class: str | None = None
    missing_document: str
    kind: GapKind
    source_quote: str
    remediation: GapRemediation = GapRemediation.OPEN


class Approval(Contract):
    """INV-10 · an approval binds the exact rows it approved.

    `mark_id` is the immutable revision, not a version string. The first schema
    stored three free-text columns, so an approval bound nothing at all.
    """

    id: int
    decision_type: DecisionType
    status: DecisionStatus
    mark_id: int | None = None
    packet_id: str | None = None
    policy_version: str | None = None
    evidence_assessment_ids: list[int] = Field(default_factory=list)
    actor_id: str
    decided_at: datetime


class Mark(Contract):
    """INV-13 · reported ≠ validated ≠ supported.

    `reported` is what the tracker says. `validated` is what the evidence
    independently derives, absent when it cannot. `support` is a separate
    judgement entirely — a mark can be perfectly derivable and wholly
    unsupported, which is exactly the case the packet must be able to state.
    """

    id: int
    holding_id: str
    period_id: str
    revision: int = 1
    reported: Money
    validated: Money | None = None
    derivation_status: DerivationStatus
    derivation_reason: str
    basis: ValuationBasis | None = None
    lineage: list[DerivedFigure] = Field(default_factory=list)

    @model_validator(mode="after")
    def _derivable_carries_its_amount(self) -> Mark:
        if self.derivation_status is DerivationStatus.DERIVABLE and self.validated is None:
            raise ValueError("a derivable mark must carry the derived amount")
        return self


class HoldingRow(Contract):
    """One row of the auditor packet: the mark, its evidence, and its gaps.

    `supported` is deliberately derived from the assessments rather than stored,
    so it cannot disagree with them.
    """

    holding_id: str
    company_name: str
    position_type: PositionType
    mark: Mark
    assessments: list[RequirementAssessment] = Field(default_factory=list)
    gaps: list[GapObservation] = Field(default_factory=list)
    approval: Approval | None = None

    @property
    def supported(self) -> bool:
        """Every applicable requirement is sufficient — and there is at least one.

        A holding with no applicable requirements is not "supported"; it has not
        been assessed. Returning True there would let an empty packet read clean.
        """
        applicable = [a for a in self.assessments if a.applicable]
        return bool(applicable) and all(
            a.verdict is RequirementVerdict.SUFFICIENT for a in applicable
        )

    @property
    def approved(self) -> bool:
        """INV-10 · nothing-unsupported is not approval; an approval is a record."""
        return (
            self.approval is not None
            and self.approval.decision_type is DecisionType.VALUATION
            and self.approval.status is DecisionStatus.APPROVED
            and bool(self.approval.evidence_assessment_ids)
        )


class Period(Contract):
    id: str
    fund_id: str
    period_date: date
    audit_scope: AuditScope
    label: str


class Packet(Contract):
    """The auditor deliverable, with its gaps stated rather than hidden.

    `unsupported_total` is reported separately from the fund total because the
    honest answer to "what does this fund hold" is two numbers, not one.
    """

    fund_id: str
    period: Period
    rows: list[HoldingRow] = Field(default_factory=list)
    schema_version: str
    policy_version: str
    generated_at: datetime

    @model_validator(mode="after")
    def _packets_are_packet_scope(self) -> Packet:
        """INV-20 · a lineage-only period never enters packet completeness."""
        if self.period.audit_scope is not AuditScope.PACKET:
            raise ValueError(
                f"period {self.period.id} is {self.period.audit_scope}; "
                "it may serve as an R3 predecessor but cannot be packeted"
            )
        return self

    def totals(self) -> dict[str, Money | int]:
        """Reported total, plus the part of it nothing supports."""
        if not self.rows:
            raise ValueError("a packet with no rows has no meaningful total")
        currency = self.rows[0].mark.reported.currency
        total = Money(amount=Decimal(0), currency=currency)
        unsupported = Money(amount=Decimal(0), currency=currency)
        for row in self.rows:
            total = total + row.mark.reported  # raises on a currency mismatch
            if not row.supported:
                unsupported = unsupported + row.mark.reported
        return {
            "reported_total": total,
            "unsupported_total": unsupported,
            "unsupported_positions": sum(1 for r in self.rows if not r.supported),
        }


DerivedFigureInput.model_rebuild()
