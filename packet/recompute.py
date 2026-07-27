"""SPEC §8's V2, computed on read and carried to the surfaces that report a mark.

Nothing in `api/` imported `v2_mark`, `v1_all` or `Outcome`, and all 72 `mark`
rows carry `validated_amount = null` because `ingest/trackers/to_contracts.py`
writes it as a literal. So the validators ran in the test suite and in the
oracle, and none of their output reached the product. Two findings never
rendered anywhere:

    Lucra FY2025        reported 2,250,000    derived 1,500,000
    Fluidstack 25Q4     reported 6,000,000    derived 2,500,000

Those are the "a wrong number is plausible — it renders, it reconciles to itself
and it passes every type check" moments, and they were invisible.

**Computed here, never stored.** `mark.validated_amount` is a stored column and
populating it decides when the derivation runs and what happens when evidence
moves underneath an approved figure. SPEC §6.3 binds an approval to
`(mark_revision, evidence_set_hash, policy_version)` precisely so an approved
total cannot follow a moving number, so writing a read-time derivation into that
column would quietly reopen the question the binding exists to close. That is a
design decision and not a task. This module answers the narrower question the
auditor actually asked — *does the evidence support the figure you reported* —
and answers it out loud, without claiming the mark has been validated.

**The label is the deliverable, as much as the number.** "Derived 2,500,000
against a reported 6,000,000" is a finding. "Validated: 2,500,000" is a claim
this system is not entitled to make, because nothing here has approved anything.
So `Recomputation` carries SPEC §8's own `Outcome` — six values, unordered —
rather than a boolean or a status borrowed from somewhere else.

**Moonfare FY2024 needs no new vocabulary.** The oracle publishes 1,048,515 for
it as `carried_amount`: a real cited figure that validates nothing, because the
fund wrote the memo about its own position. `derivation_status` on `mark` has no
word for that — it is `derivable | not_derivable` in the Python enum, the
database enum and the TypeScript union, and the nearest available label reads
"not derivable · no validated amount could be derived from the evidence", which
is false. `Outcome.NOT_COMPARABLE` is exactly that word and already exists, so
this surface can say it today: the evidence spoke, in the voice under audit, and
comparing the fund's number against the mark the fund took from it is the
circularity rather than a check.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from packages.contracts.base import MONEY_SCALE, PPS_SCALE
from packages.contracts.models import HoldingRow, Money, Packet
from policy.inputs import Ledger
from policy.validators import Outcome, Result, v2_mark


@dataclass(frozen=True)
class ClassAmount:
    """One held class's contribution, priced by its OWN class (INV-17).

    Carried per class rather than as one number because that is the granularity
    at which Fluidstack's finding is legible: 100,000 Series A at $10.00 plus
    100,000 Series A-2 at $15.00 is 2,500,000, and the reported 6,000,000 is
    200,000 shares at the $30.00 Series B price applied to every class. One
    total hides which half is wrong.
    """

    lot_id: str
    security_class: str
    shares: int
    price_per_share: Decimal
    amount: Money
    #: The price came from a class the fund does not hold at this date. INV-17 —
    #: pricing one class off another's evidence is a valuation-policy act.
    cross_class: bool


@dataclass(frozen=True)
class Recomputation:
    """What the cited evidence derives for one holding, beside what was reported.

    `difference` is `reported - derived`, computed here because the browser may
    not subtract two canonical figures (SPEC §5.3) — and is `None` unless BOTH
    figures exist and share a currency, because a difference between a figure
    that exists and one that does not is not zero.
    """

    holding_id: str
    #: SPEC §8's vocabulary, unordered: `not_comparable` is not a soft fail and
    #: `unconfirmable` is not a weak pass.
    outcome: Outcome
    #: How the figure was reached, or the named reason there is none. The same
    #: string whether the comparison matched or not — reading pass/fail out of it
    #: is deliberately impossible.
    reason: str
    derived: Money | None
    reported: Money | None
    difference: Money | None
    evidence_claim_ids: tuple[str, ...]
    per_class: tuple[ClassAmount, ...]
    policy_version: str


def _at_scale(value: Decimal, scale: int) -> Decimal:
    """A figure at its canonical scale, or a refusal.

    Money columns are `numeric(26,12)` against a canonical scale of 4, and price
    per share the same column type against 6 — declared wider on purpose so an
    over-precise figure survives to be REJECTED by a CHECK rather than silently
    rounded before any constraint can see it (SPEC §15). So the ledger hands
    back `10.000000000000` for a $10.00 price, and a screen that printed it
    verbatim would show twelve decimal places on a price nobody stated that way.

    Trailing zeros carry no information and are dropped. Anything else is a
    figure the database CHECK should have refused, and it raises rather than
    rounding: rounding here is the silent re-quantisation the decimal policy
    exists to prevent, and it would happen on the read path where nobody is
    looking.
    """
    trimmed = value.quantize(Decimal(1).scaleb(-scale))
    if trimmed != value:
        raise ValueError(
            f"derived figure {value} carries more than {scale} significant decimal places"
        )
    return trimmed


def _money(amount: Decimal, currency: str) -> Money:
    """A derived figure at the canonical money scale.

    `shares × price_per_share` is exact and unrounded by design — nothing in
    `policy/validators.py` quantises, so equality is decided on figures no
    source states rounded. Quantisation happens once, here, on the way to a
    screen, exactly as the export serialiser does it.
    """
    return Money(amount=_at_scale(amount, MONEY_SCALE), currency=currency)


def _from_result(result: Result, row: HoldingRow, policy_version: str) -> Recomputation:
    # The currency is the REPORTED mark's, and there is no second guess. The
    # validators carry bare Decimals; every field they can read a value from is
    # USD-denominated in this corpus, and a figure labelled with a currency
    # nobody stated is INV-11 breached in transit — which has happened here once
    # already, on `validated_currency`. With no mark there is no currency to
    # name, so the figure is withheld rather than published under a guess, and
    # the reason still travels.
    currency = None if row.mark is None else row.mark.reported.currency
    derived = (
        None if result.computed is None or currency is None else _money(result.computed, currency)
    )
    reported = None if row.mark is None else row.mark.reported
    difference = (
        None
        if derived is None or reported is None
        else _money(reported.amount - derived.amount, reported.currency)
    )
    return Recomputation(
        holding_id=row.holding_id,
        outcome=result.outcome,
        reason=result.reason,
        derived=derived,
        reported=reported,
        difference=difference,
        evidence_claim_ids=result.evidence,
        per_class=()
        if currency is None
        else tuple(
            ClassAmount(
                lot_id=lot.lot_id,
                security_class=lot.security_class,
                shares=lot.shares,
                price_per_share=_at_scale(lot.price_per_share, PPS_SCALE),
                amount=_money(lot.amount, currency),
                cross_class=lot.cross_class,
            )
            for lot in result.lineage
        ),
        policy_version=policy_version,
    )


def for_holding(ledger: Ledger, row: HoldingRow, on: date, policy_version: str) -> Recomputation:
    """V2 for one row, at one measurement date."""
    return _from_result(v2_mark(ledger, row.holding_id, on), row, policy_version)


def for_packet(ledger: Ledger, packet: Packet) -> dict[str, Recomputation]:
    """V2 for every row in the packet, keyed by holding.

    Every row, including the ones the check cannot run for. A recomputation
    offered only where it succeeds is a page reporting its own successes: the
    auditor's question is "what did you check", and `unconfirmable · Because
    Market has no document of any kind" is an answer to it.
    """
    return {
        row.holding_id: for_holding(ledger, row, packet.period.period_date, packet.policy_version)
        for row in packet.rows
    }


def disagreeing(recomputations: dict[str, Recomputation]) -> list[Recomputation]:
    """The rows where the evidence derives a figure and it is not the one reported."""
    return [r for r in recomputations.values() if r.outcome is Outcome.FAIL]
