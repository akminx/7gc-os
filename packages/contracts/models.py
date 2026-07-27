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
from enum import StrEnum

from pydantic import Field, model_validator

from packages.contracts.base import (
    PPS_SCALE as PPS_SCALE,
)
from packages.contracts.base import (
    Contract as Contract,
)
from packages.contracts.base import (
    Money as Money,
)
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

    @model_validator(mode="after")
    def _price_fits_its_declared_scale(self) -> Claim:
        if self.price_per_share is not None:
            exponent = self.price_per_share.as_tuple().exponent
            if isinstance(exponent, int) and -exponent > PPS_SCALE:
                raise ValueError(
                    f"price per share carries more than {PPS_SCALE} decimal places "
                    f"({self.price_per_share})"
                )
        return self

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

    @model_validator(mode="after")
    def _shares_are_whole(self) -> Lot:
        """INV-11 · mirrors the DB `lot_shares_whole` CHECK.

        Without this the database refuses 100.5 and the wire model happily
        carries it, so the browser and any API DTO can hold a share count the
        ledger considers impossible.
        """
        if self.shares is not None and self.shares != self.shares.to_integral_value():
            raise ValueError(f"share counts are whole numbers; got {self.shares}")
        return self

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

    **Applicability is the verdict, not a field beside it.** The first version
    carried `applicable: bool` *and* `verdict`, which is fourteen combinations of
    which six are nonsense, guarded by validators I twice wrote incorrectly — the
    worst let R1 be marked inapplicable, which made a holding with no
    existence-and-cost evidence read as fully supported.

    Removing the field removes the contradiction rather than forbidding it: there
    is now exactly one place applicability is expressed, so nothing can disagree
    with it.

    `reason_codes` is not decoration: a `partial` with no reason is an assertion
    the auditor cannot act on.
    """

    requirement: RequirementCode
    verdict: RequirementVerdict
    reason_codes: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    evidence: list[EvidenceCitation] = Field(default_factory=list)
    pro_forma: bool = False
    tracker_label: str | None = None
    policy_version: str

    @property
    def applicable(self) -> bool:
        return self.verdict is not RequirementVerdict.NOT_APPLICABLE

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


#: SPEC §7.1 · R1 (existence and cost) and R2 (fair-value support) are
#: applicable to every holding at every measurement date. R3–R5 are conditional.
#: A row missing either of these has not been assessed, which is not the same
#: fact as having been assessed and found clean.
ALWAYS_APPLICABLE: frozenset[RequirementCode] = frozenset({RequirementCode.R1, RequirementCode.R2})


class TotalKind(StrEnum):
    """INV-19 · a total must say what it is a total OF.

    An unqualified fund number is how unsupported value gets laundered into a
    headline figure: the caller prints "$25,648,515" and the caveat stays behind
    in a field nobody rendered.
    """

    TRACKER_REPORTED = "tracker_reported"
    HELD_AT_DATE_REPORTED = "held_at_date_reported"
    APPROVED_FAIR_VALUE = "approved_fair_value"


class PacketTotals(Contract):
    """A sum that carries its own qualification.

    `contains_unsupported_inputs` is derived rather than stored so it cannot
    disagree with the subtotal beside it.
    """

    kind: TotalKind
    label: str
    amount: Money
    unsupported_amount: Money
    unsupported_positions: int
    #: INV-7 / INV-19 · EVERY unsupported row, held at the measurement date or
    #: not. A superset of `unsupported_positions`, which counts only the held
    #: ones because only those are inputs to the total beside it. The unheld
    #: gaps are the DIFFERENCE of the two; adding them double counts.
    packet_gap_positions: int = 0

    @property
    def contains_unsupported_inputs(self) -> bool:
        return self.unsupported_amount.amount != 0 or self.unsupported_positions > 0

    @model_validator(mode="after")
    def _approved_totals_carry_nothing_unsupported(self) -> PacketTotals:
        """An approved fair-value total containing unsupported inputs is a
        contradiction — that is the number the packet exists to refuse."""
        if self.kind is TotalKind.APPROVED_FAIR_VALUE and self.contains_unsupported_inputs:
            raise ValueError(
                "an approved_fair_value total cannot include unsupported positions; "
                f"{self.unsupported_positions} position(s) are unsupported"
            )
        return self


class HoldingRow(Contract):
    """One row of the auditor packet: the mark, its evidence, and its gaps.

    `supported` is deliberately derived from the assessments rather than stored,
    so it cannot disagree with them.
    """

    holding_id: str
    company_name: str
    position_type: PositionType
    #: INV-7 · held-at-date ≠ active-today, computed upstream from immutable lots
    #: (`Lot.held_at`) and never a mutable flag on the holding. The oracle has
    #: carried this since it was written; the contract did not, so `totals()`
    #: summed realisation-only rows into a held-at-date figure. An invariant
    #: enforced on one side only is not enforced.
    held_at_date: bool = True
    #: Absent when the ledger holds no mark for this holding at this date.
    #:
    #: A position realised during the period under audit still belongs in the
    #: packet — the audit letter's request 4 asks for realised investments — but
    #: it has no mark at the measurement date, because it was not held then.
    #: `evals/oracle/derived.json` states exactly this: Jackpocket at 2024-12-31
    #: is `held_at_date: false` with `reported_amount: null`.
    #:
    #: Required until now, which is why `api/ledger.py` anchored the packet on
    #: marks and dropped every realised position — the one class of row the
    #: letter asks for by name. Carrying the last known mark forward instead
    #: would put a stale figure where the oracle says there is none.
    mark: Mark | None = None
    assessments: list[RequirementAssessment] = Field(default_factory=list)
    gaps: list[GapObservation] = Field(default_factory=list)
    approval: Approval | None = None

    @model_validator(mode="after")
    def _always_applicable_codes_apply_while_the_position_is_held(self) -> HoldingRow:
        """SPEC §7.1 · R1 and R2 apply to every holding **held at this date**.

        This lived on `RequirementAssessment`, which cannot see whether the
        position was held — so it read §7.1's "always" literally and refused the
        one case the audit letter distinguishes. The letter asks for existence
        and cost "for each portfolio investment held during the periods under
        audit" (¶1) and for realisation support separately (¶4). Jackpocket at
        12/31/2024 is the second, not the first: it was sold in May, so there is
        no position whose existence and cost can be evidenced at the measurement
        date, and `evals/oracle/derived.json` states both as `not_applicable`.

        Moving the check here also closes the hole the old placement left: an
        assessment could read `sufficient` on a row that was not held at all,
        and nothing compared the two, because the validator that cared about
        applicability could not see `held_at_date`.
        """
        if not self.held_at_date:
            return self
        wrong = sorted(
            a.requirement
            for a in self.assessments
            if a.requirement in ALWAYS_APPLICABLE and not a.applicable
        )
        if wrong:
            raise ValueError(
                f"{self.holding_id} is held at this date, so "
                f"{', '.join(c.value for c in wrong)} cannot be not_applicable"
            )
        return self

    @property
    def unsupported_reasons(self) -> dict[RequirementCode, str]:
        """Why this row is not supported, keyed by requirement. Empty means it is.

        `supported` is defined FROM this, so the flag and the explanation cannot
        drift apart — a previous version computed them separately and they
        disagreed about a requirement that was present but inapplicable.
        """
        by_code = {a.requirement: a for a in self.assessments}
        reasons: dict[RequirementCode, str] = {}
        # R1 and R2 must each be present, applicable, and sufficient — WHILE THE
        # POSITION IS HELD. Checking presence-applicability-sufficiency together
        # is what the two earlier versions got wrong: one tested presence alone,
        # the next skipped anything marked inapplicable.
        #
        # The `held_at_date` gate is the same rule the validator above states,
        # expressed a second time here because this is a second place that
        # decides applicability — and an applicability rule written where
        # `held_at_date` is not visible is exactly the defect that was already
        # fixed once, on `RequirementAssessment`. Moving that validator did not
        # move this: the contract went on demanding existence-and-cost evidence
        # for Jackpocket at 2024-12-31, a position sold in May, where
        # `derived.json` says `fully_supported: true` and both codes are
        # `not_applicable`. The audit letter asks for existence and cost "for
        # each portfolio investment held during the periods under audit" (¶1)
        # and for realisation support separately (¶4); reporting an unheld row
        # as an open gap collapses that split and sends the auditor after
        # paperwork that cannot exist.
        if self.held_at_date:
            for code in sorted(ALWAYS_APPLICABLE):
                got = by_code.get(code)
                if got is None:
                    reasons[code] = "not assessed"
                elif got.verdict is not RequirementVerdict.SUFFICIENT:
                    # Covers not_applicable too: an always-applicable
                    # requirement marked N/A on a HELD row is not sufficient, so
                    # it lands here. A separate branch for it was redundant —
                    # mutation testing showed removing it changed nothing, which
                    # is the signal to delete rather than to write a test for it.
                    reasons[code] = got.verdict.value
        # An unheld row is still judged, on what it is actually answerable for:
        # the loop below covers R4 and R5. `supported` does not become vacuously
        # true here — a realised position whose realisation evidence is short
        # still reports a gap, which `test_contracts.py` pins so this gate
        # cannot be over-applied into "unheld means clean".
        elif not any(a.applicable for a in self.assessments):
            # And an unheld row with NOTHING applicable is not "clean", it is
            # unexamined. Without this branch, skipping the always-applicable
            # loop makes an empty assessment set read as fully supported — the
            # fix for the ¶1/¶4 collapse turning into a second, larger hole in
            # the other direction. R4 is the key because an unheld position is
            # in the packet on the letter's ¶4 (realised investments), so R4 is
            # the question it exists to answer and the one nobody answered.
            reasons[RequirementCode.R4] = "not assessed"
        for a in self.assessments:
            if a.applicable and a.verdict is not RequirementVerdict.SUFFICIENT:
                reasons.setdefault(a.requirement, a.verdict.value)
        return reasons

    @property
    def supported(self) -> bool:
        """SPEC 7.1-7.2 · every applicable requirement is sufficient, and the
        always-applicable ones were actually assessed."""
        return not self.unsupported_reasons

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

    def totals(self) -> PacketTotals:
        """A total that states what kind of total it is. INV-19.

        Returning a bare `reported_total` invites a caller to print it as "the
        fund's value". It is not: it is the sum of tracker-reported amounts, part
        of which nothing supports. The kind and the unsupported subtotal travel
        with the number so that stripping the qualification takes deliberate
        effort rather than being the default.

        INV-7 · only rows held at the measurement date are inputs. A position
        realised before the date belongs in the packet — it is a gap if its
        evidence is incomplete — but adding it to the total answers a question
        nobody asked, and the oracle has always excluded it. This summed every
        row, so the two sides disagreed about the same fund on the same facts.

        Which is why the kind is `held_at_date_reported`, not `tracker_reported`.
        The filter above is applied unconditionally, so the number this returns
        is *never* the tracker's total: at a date where anything was realised the
        two differ, and calling a held-at-date subtotal "Tracker-reported total"
        states something false about what the figure IS — the exact laundering
        INV-19 exists to stop. The oracle has always called the same quantity
        `held_at_date_reported_total` and carries the tracker's own figure
        separately as `tracker_stated_total`; this contract used one name for
        both and left `HELD_AT_DATE_REPORTED` unreachable.
        """
        if not self.rows:
            raise ValueError("a packet with no rows has no meaningful total")
        # The currency comes from the first row that is actually an INPUT, not
        # from `rows[0]`. An unheld EUR row before a held USD row set the zero
        # to EUR and then refused to add USD to it — a cross-currency error
        # raised by a row the total excludes.
        # A packet where nothing is held at the date has a total of zero, not an
        # error — a fund that exited every position still files a packet, and
        # `test_a_single_exit_selling_the_whole_position_realises_every_lot` is
        # that case. So the currency comes from the held inputs when there are
        # any, and from the first marked row otherwise: with no inputs the sum is
        # zero either way, and taking it from an EXCLUDED row while real inputs
        # exist is what made an unheld EUR row refuse to add a held USD one.
        marked = [r for r in self.rows if r.mark is not None]
        if not marked:
            raise ValueError("a packet whose rows carry no mark has no meaningful total")
        inputs = [r for r in marked if r.held_at_date]
        source = (inputs or marked)[0].mark
        assert source is not None  # every row in `marked` has one
        currency = source.reported.currency
        total = Money(amount=Decimal(0), currency=currency)
        unsupported = Money(amount=Decimal(0), currency=currency)
        for row in self.rows:
            if not row.held_at_date:
                continue
            if row.mark is None:
                continue
            total = total + row.mark.reported  # raises on a currency mismatch
            if not row.supported:
                unsupported = unsupported + row.mark.reported
        return PacketTotals(
            kind=TotalKind.HELD_AT_DATE_REPORTED,
            label="Tracker-reported amounts for positions held at this date, unaudited",
            amount=total,
            unsupported_amount=unsupported,
            unsupported_positions=sum(1 for r in self.rows if r.held_at_date and not r.supported),
            packet_gap_positions=sum(1 for r in self.rows if not r.supported),
        )


DerivedFigureInput.model_rebuild()
