"""What the policy layer reads. Values, not a database.

Every requirement in `policy/requirements.py` is a pure function of these, so
the rules can be exercised without a Postgres connection and the adapter that
fills them (`policy/from_ledger.py`) is the only thing that has to know SQL.
That split is not tidiness: SPEC §8's validators and §7's requirements are the
part of this system a wrong answer is *plausible* in, and a rule that can only
be run against a live schema is a rule that gets tested once.

Nothing here is derived. `class_at` and `shares_at` resolve a recorded
conversion event rather than mutating a lot, because Sway's recapitalisation
changes the security class at a date and INV-17 turns on which class was held
*then* — post-recap the held class equals the priced class, so Sway is not
cross-class, and a lot flattened to one immutable class cannot say that.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from packages.contracts.enums import (
    AuditScope,
    ExecutionStatus,
    GapKind,
    PositionType,
    RequirementCode,
    SourceClass,
)


@dataclass(frozen=True)
class Conversion:
    """A recorded security-class conversion. Sway's recap is the corpus case."""

    effective_date: date
    security_class: str
    shares: int
    exchange_ratio: Decimal


@dataclass(frozen=True)
class Lot:
    """One acquisition. Immutable — a change is a new event, never an edit."""

    id: str
    holding_id: str
    security_class: str
    shares: int | None
    entry_pps: Decimal | None
    cost_amount: Decimal
    cost_currency: str
    acquired_date: date
    realized_date: date | None = None
    conversion: Conversion | None = None

    def class_at(self, on: date) -> str:
        if self.conversion is not None and on >= self.conversion.effective_date:
            return self.conversion.security_class
        return self.security_class

    def shares_at(self, on: date) -> int | None:
        if self.conversion is not None and on >= self.conversion.effective_date:
            return self.conversion.shares
        return self.shares

    def held_at(self, on: date) -> bool:
        if self.acquired_date > on:
            return False
        return self.realized_date is None or self.realized_date > on

    def held_during(self, year_ending: date) -> bool:
        """Held at ANY point in the fiscal year ending at this measurement date.

        The letter asks for its four requests "for each portfolio investment held
        DURING the periods under audit", and this system read that as held AT the
        year end. Jackpocket is the case: acquired 2021-12-30, sold 2024-05-20,
        so at 12/31/2024 it is not held and R1 answered `not_applicable`.

        But the FY2024 statements carry a realised GAIN on that sale, and a gain
        is proceeds minus cost. Reporting existence and cost as inapplicable
        hands the auditor one half of a figure they have to sign off and calls
        the other half none of their business. R4 evidences the proceeds; ¶1 is
        where the cost lives, and the position was held for five months of the
        year the gain is in.

        Only ¶1 reads this way. R2 asks what a position is worth AT a date and a
        position not held then is worth nothing to this fund; R3 asks about a
        mark that is still being carried. Existence and cost is the one request
        whose subject outlives the holding.
        """
        if self.acquired_date > year_ending:
            return False
        if self.realized_date is None:
            return True
        return self.realized_date > year_ending.replace(year=year_ending.year - 1)


@dataclass(frozen=True)
class EvidenceClaim:
    """One assertion a document makes, at one authority (INV-15).

    `requirements` is which PBC requirements this claim is relied upon for. It
    is a property of the claim rather than of the document, for the same reason
    authority is: one artifact can carry a settlement confirmation and a
    records note, and they answer different questions.

    `applicable_from` / `applicable_to` are the source-stated reliance window
    (INV-16), not a processing convenience. Capsule's memo forbids reliance at a
    later date in a sentence that is itself a cited fact, so the window closes
    because the document says so.
    """

    id: str
    holding_id: str
    source_class: SourceClass
    execution_status: ExecutionStatus
    issued_date: date
    applicable_from: date
    requirements: frozenset[RequirementCode]
    applicable_to: date | None = None
    received_date: date | None = None
    priced_class: str | None = None
    price_per_share: Decimal | None = None
    stated_amount: Decimal | None = None
    stated_currency: str | None = None
    supersedes_claim_id: str | None = None
    #: The claim's CITED figures, `field_name` → value. Every entry is bound to
    #: a passage of the document by `0008`/`0009` and by
    #: `packages/contracts/citations.py`, so a number here is a number some
    #: sentence states, not one a reader typed.
    #:
    #: The ledger held 237 of these and the policy layer could not see any of
    #: them: `claim.stated_amount` is never written — `ClaimDraft` carries no
    #: such field, and `ingest/documents/claims.py` says so in its own comment —
    #: while `extracted_fact` was loaded by nothing. So the validators reported
    #: `blocked_incomplete` for Moonfare's concluded fair value and Jio's net
    #: asset value, five of seventeen cases, where the oracle derives an answer
    #: from the same documents.
    #:
    #: Loading the facts rather than backfilling `stated_amount` is deliberate.
    #: `stated_amount` is one unnamed number per claim; an administrator
    #: statement carries a net asset value AND a capital-account balance, and
    #: collapsing them into one column is INV-19 one level down — a figure that
    #: does not say what it is a figure of. `field_name` is what keeps them
    #: apart, and it is the same key the citation is bound under.
    facts: Mapping[str, Decimal] = field(default_factory=dict)
    #: The claim's cited DATE-valued figures, `field_name` → value. Parallel to
    #: `facts` and keyed the same way, because a cited date is a cited fact —
    #: `facts` cannot hold one only because its values are `Decimal`.
    #:
    #: Separate rather than widened to `Decimal | date`: every existing reader
    #: of `facts` does arithmetic on what it finds, and a union would put a
    #: value they cannot compute with behind the same key they already trust.
    #:
    #: V7 is the reason this exists. "The rate was observed AT the measurement
    #: date" is a question only the rate's own cited effective date can answer,
    #: and answering it from the claim's reliance window instead is the INV-6
    #: carry-forward this system exists to refuse.
    fact_dates: Mapping[str, date] = field(default_factory=dict)

    #: The claim's cited TEXT-valued figures, same keying, separate for the same
    #: reason `fact_dates` is separate.
    #:
    #: V7 is the reason this one exists too. It promises a rate that is
    #: "directed and cited", and it could check neither the direction nor who it
    #: was cited to — a GBP/USD rate belonging to another position satisfied it.
    #: The pair is not unknowable: the Moonfare memos state EUR/USD three times,
    #: `ingest/documents/extract_memo.py` captures it, and it is stored as
    #: `extracted_fact.currency_pair`. It had no way to travel, which is a
    #: different problem from not existing, and the first wording of this gap
    #: said the second — which is how a closable gap stays open.
    #:
    #: `Lot.cost_currency` is NOT the answer to "what is this denominated in".
    #: It is what the fund paid, and for Moonfare that is USD.
    fact_text: Mapping[str, str] = field(default_factory=dict)

    @property
    def effective_date(self) -> date:
        """The date this claim reaches the fund — delivery if later than issue.

        INV-3 · an administrator statement dated 12/31 and delivered 1/30 is
        subsequent evidence. Legitimate, but it must be labelled rather than
        presented as contemporaneous, and the label is decided from the later
        of the two dates rather than from the one printed on the page.
        """
        if self.received_date is not None and self.received_date > self.issued_date:
            return self.received_date
        return self.issued_date


@dataclass(frozen=True)
class Gap:
    """A document that should exist and does not (INV-12).

    Immutable. `kind` is why it is absent, and the three kinds call for three
    different auditor actions — overwriting `with_counsel` to `not_located` is
    the cheapest collapse of this distinction, so progress is recorded as
    remediation rows elsewhere and never as an edit here.
    """

    holding_id: str
    requirement: RequirementCode
    kind: GapKind
    missing_document: str
    source_quote: str
    security_class: str | None = None


@dataclass(frozen=True)
class Period:
    id: str
    fund_id: str
    period_date: date
    audit_scope: AuditScope


@dataclass(frozen=True)
class MarkObservation:
    """What a fund reported for a holding at one period.

    Lineage-only periods are included. R3's equality limb may use one as the
    predecessor observation — it establishes that the value did not move — but
    it never generates its own assessment, never counts as qualifying support,
    never resets support age and never enters packet completeness (INV-20).
    """

    holding_id: str
    period_id: str
    amount: Decimal


@dataclass(frozen=True)
class SupportObservation:
    """One dated piece of qualifying support for one material component.

    Bound to the artifact that provides it — a claim the fund holds, or the
    priced acquisition of a lot. There is no constructor taking a bare date,
    because "the last valuation was March 2023" with nothing behind it is the
    assertion R3 exists to stop the fund from making about itself.
    """

    supported_on: date
    claim_id: str | None = None
    lot_id: str | None = None


@dataclass(frozen=True)
class MaterialComponent:
    """A material component of a mark, and every dated support it has.

    Which parts of a mark are *material* is a judgement, not a computation —
    Moonfare's mark is an underlying EUR valuation and an FX rate, The Mom
    Project's is an equity position and a convertible note. So the decomposition
    is recorded and reviewable, and only its consequence is derived.

    An empty `support` is meaningful and is not the same as an absent component:
    SPEC §7.2 says absent dated support counts as stale, so Because Market —
    which has no evidence of any kind — is stale rather than silently passing.
    A holding with no components recorded at all is a different failure, and
    `Ledger.components_for` refuses it rather than reading as "nothing stale".
    """

    holding_id: str
    name: str
    support: tuple[SupportObservation, ...] = ()

    def latest_on_or_before(self, on: date) -> date | None:
        dates = [s.supported_on for s in self.support if s.supported_on <= on]
        return max(dates) if dates else None


@dataclass(frozen=True)
class ManagementAssessment:
    """Management's own assessment of an unchanged mark (PBC ¶3).

    Only an `approved` one closes R3, and only while it still matches the mark
    and evidence it was approved against (V12). A draft leaves the gap open.
    """

    holding_id: str
    measurement_date: date
    status: str
    mark_revision: str | None = None
    evidence_set_hash: str | None = None


@dataclass(frozen=True)
class PolicyDecision:
    """A recorded valuation-policy decision, scoped to one holding and date.

    Scoped, because a decision recorded for one position must not clear another
    (INV-17). One definition, read by everything that asks.
    """

    holding_id: str
    measurement_date: date
    method: str
    citation: str


@dataclass(frozen=True)
class ClaimResolution:
    """A recorded human resolution of a material contradiction (SPEC §7.4).

    `conflicting` dominates and does not decay: it stays until a person says
    which claim supersedes which, for a named security class. Nothing in this
    corpus contradicts anything, so this is empty — and that is the point.
    The branch exists so that `conflicting` can be reached and cleared by a
    test rather than sitting in the code as an unexercised possibility.
    """

    holding_id: str
    priced_class: str
    superseding_claim_id: str


@dataclass(frozen=True)
class Holding:
    id: str
    fund_id: str
    position_type: PositionType


class LedgerError(Exception):
    """The ledger cannot answer a question the policy layer must ask.

    Distinct from `InvalidPolicyInput`, which is about an unenumerated *rule*.
    This is about absent *data* — and it raises rather than defaulting for the
    same reason: a holding with no recorded material components would otherwise
    read as "nothing is stale", which is the answer R3 exists to refuse.
    """


@dataclass(frozen=True)
class Ledger:
    """Everything the policy layer reads, indexed for the questions it asks."""

    holdings: dict[str, Holding]
    periods: dict[str, Period]
    lots: tuple[Lot, ...]
    claims: tuple[EvidenceClaim, ...]
    gaps: tuple[Gap, ...]
    marks: tuple[MarkObservation, ...]
    components: tuple[MaterialComponent, ...] = ()
    assessments: tuple[ManagementAssessment, ...] = ()
    decisions: tuple[PolicyDecision, ...] = ()
    resolutions: tuple[ClaimResolution, ...] = ()
    tracker_labels: dict[tuple[str, str], tuple[str, ...]] = field(default_factory=dict)

    def lots_for(self, holding_id: str) -> list[Lot]:
        return [x for x in self.lots if x.holding_id == holding_id]

    def held_lots(self, holding_id: str, on: date) -> list[Lot]:
        return [x for x in self.lots_for(holding_id) if x.held_at(on)]

    def lots_held_during(self, holding_id: str, year_ending: date) -> list[Lot]:
        """¶1's population — see `Lot.held_during` for why it differs."""
        return [x for x in self.lots_for(holding_id) if x.held_during(year_ending)]

    def components_for(self, holding_id: str) -> tuple[MaterialComponent, ...]:
        found = tuple(x for x in self.components if x.holding_id == holding_id)
        if not found:
            raise LedgerError(
                f"{holding_id} has no material components recorded, so R3 cannot ask "
                f"whether any of them is stale. Record an explicit component with no "
                f"support where the absence is the finding — omission would read as "
                f"'nothing is stale', which is the opposite."
            )
        return found

    def gaps_for(
        self, holding_id: str, requirement: RequirementCode, security_class: str | None = None
    ) -> list[Gap]:
        return [
            g
            for g in self.gaps
            if g.holding_id == holding_id
            and g.requirement == requirement
            and (security_class is None or g.security_class == security_class)
        ]

    def period_at(self, fund_id: str, on: date) -> Period | None:
        for p in self.periods.values():
            if p.fund_id == fund_id and p.period_date == on:
                return p
        return None

    def packet_dates(self, fund_id: str) -> list[date]:
        return sorted(
            p.period_date
            for p in self.periods.values()
            if p.fund_id == fund_id and p.audit_scope is AuditScope.PACKET
        )

    def previous_packet_date(self, fund_id: str, on: date) -> date | None:
        earlier = [x for x in self.packet_dates(fund_id) if x < on]
        return max(earlier) if earlier else None

    def mark_at(self, holding_id: str, period_id: str) -> Decimal | None:
        for m in self.marks:
            if m.holding_id == holding_id and m.period_id == period_id:
                return m.amount
        return None

    def mark_observations(self, holding_id: str, fund_id: str) -> list[tuple[date, Decimal]]:
        """Every dated observation for this holding in this fund, lineage included."""
        out = []
        for m in self.marks:
            if m.holding_id != holding_id:
                continue
            period = self.periods.get(m.period_id)
            if period is None or period.fund_id != fund_id:
                continue
            out.append((period.period_date, m.amount))
        return sorted(out)

    def decisions_for(self, holding_id: str, on: date) -> list[PolicyDecision]:
        return [
            x for x in self.decisions if x.holding_id == holding_id and x.measurement_date == on
        ]

    def assessments_for(self, holding_id: str, on: date) -> list[ManagementAssessment]:
        return [
            x for x in self.assessments if x.holding_id == holding_id and x.measurement_date == on
        ]
