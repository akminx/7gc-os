"""SPEC §8 · the deterministic validators, as pure functions over the ledger.

Eight of the fourteen are here. V12 is calibration and is already
`requirements.r3` — one rule, written once. V14 is citation resolution, enforced
in `packages/contracts/citations.py` and again by the trigger in
`0008_citations_resolve.sql`. V3 waits on the approval endpoint. V5 and V6 wait
on figures the ledger does not carry (see "What the ledger does not carry").

**Six outcomes, and never a silent skip.** Every validator returns exactly one
of `Outcome`. A check that did not run has to say which kind of not-run it was,
because "this position has no shares, so a per-share identity does not arise"
and "nobody checked" are opposite findings that a boolean renders identically.

**Two shapes of cannot-run, and they are different findings:**

* `unconfirmable` — the *evidence* does not say. Because Market has no document
  of any kind; the mark is not confirmable from anything the fund holds. The
  auditor's action is to request evidence.
* `blocked_incomplete` — the evidence says it and *this system* does not carry
  it. The Mom Project's convertible note states a commitment with no share
  count, so the per-class identity has an input the ledger has no field for.
  The action is to load the figure, not to chase the client.

  This was five rows larger. Moonfare's memos and Jio's capital accounts stated
  their values in `extracted_fact` and reached nothing, because
  `claim.stated_amount` is never written and the facts were loaded by nobody.
  `EvidenceClaim.facts` carries them now and `stated_value` reads the one field
  DECLARED as a holding value, so those five derive instead of blocking.

Collapsing the second into the first is the cheapest way to make an ingestion
gap read as an evidence gap, which puts a request on the auditor's list that the
fund cannot answer because the document is already in the file.

**A reason names the derivation; the outcome names the verdict.** `V2` reports
`PER_CLASS_SHARES_X_PPS` whether the mark matched or not — Lucra FY2025 derives
1,500,000 against a reported 2,250,000, and *how* the 1,500,000 was reached is
the same fact in both directions. Reading pass/fail out of the reason string is
therefore impossible, which is deliberate.

**Decimal, never float** (SPEC §15). `shares × PPS` is a single multiply with no
intermediate rounding, and nothing here quantises: that happens once, in the
export serialiser. A validator that rounded on the way to a comparison would
decide equality on a figure no source states.

**What the ledger does not carry.** `EvidenceClaim.facts` now carries every
cited figure, keyed by `field_name` — which is what a validator asks by, and
what the citation is bound under. `stated_value` reads the one field declared in
`VALUE_FIELDS` as the holding's own value.

What is still missing is not the figures but the SHAPE: an FX rate is a pair of
currencies and a date, a realisation is terms, a round is a set of interlocking
totals. Reading those out of a flat name→number mapping would be guessing at
structure the mapping does not record. So the validators that need them still
take them as arguments — `FxRate`, `RealizationTerms`, `RoundStatement` — and
the ledger-driven entry points beside them return `blocked_incomplete` naming
the missing input rather than a verdict nothing supports. Those argument types
are the shape `policy/inputs.py` has to grow.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from packages.contracts.enums import PositionType, RequirementCode, SourceClass
from policy.inputs import EvidenceClaim, Ledger, Lot
from policy.requirements import applicable_claims, supersede
from policy.valid_tuples import InvalidPolicyInput

_ZERO = Decimal(0)

#: Source classes whose documents state a value rather than a price per share.
#: A relied-upon claim of one of these kinds that names no value figure is the
#: ingestion gap above, not an absence of evidence.
_AMOUNT_BEARING = frozenset(
    {
        SourceClass.THIRD_PARTY_VALUATION_MEMO,
        SourceClass.ADMINISTRATOR_STATEMENT,
        SourceClass.FUND_INTERNAL_RECORD,
    }
)

#: Which CITED figure is the holding's value at the claim's date. Reviewed
#: judgements, enumerated — never inferred from position, magnitude, or "the
#: first number that looks like money".
#:
#: The reason it must be declared is on one claim in this corpus. Moonfare's
#: FY2024 FX remeasurement cites `usd_carrying_value` 1,048,515 AND
#: `prior_usd_carrying_value` 1,000,000, both bound to real passages, both
#: correct as facts. A rule that took the first amount-bearing fact would mark
#: the position at last year's number and reconcile perfectly to itself — the
#: exact failure mode this project exists to make impossible.
#:
#: `field_name` is the only thing that separates them, which is why the claim
#: carries a mapping rather than one `stated_amount` column (see
#: `EvidenceClaim.facts`).
VALUE_FIELDS = frozenset(
    {
        "concluded_fair_value_usd",
        "usd_carrying_value",
        "net_asset_value",
        "fund_holding_value",
    }
)


def stated_value(claim: EvidenceClaim) -> Decimal | None:
    """The one figure this claim states as the holding's value, or None.

    Fails closed on ambiguity rather than choosing. Two declared value fields on
    one claim means the corpus grew a case this set does not describe, and the
    right response is to decide which figure is the value and say so here —
    not to let an ordering pick.

    `stated_amount` is checked first and is always None today: the `claim` table
    has the column, `ClaimDraft` has no such field, and `ingest/documents/
    claims.py` says so in its own comment. It is read anyway so that a future
    writer populating it is not silently ignored.
    """
    if claim.stated_amount is not None:
        return claim.stated_amount
    named = sorted(f for f in claim.facts if f in VALUE_FIELDS)
    if len(named) > 1:
        raise InvalidPolicyInput(
            f"claim {claim.id} cites {len(named)} figures declared as a holding value "
            f"({', '.join(named)}). Decide which one is the value at this date and "
            f"narrow `VALUE_FIELDS` in policy/validators.py deliberately."
        )
    return claim.facts[named[0]] if named else None


class Outcome(StrEnum):
    """SPEC §8's vocabulary. Unordered, because none of these is "more" than
    another: `not_applicable` is not a weak pass and `unconfirmable` is not a
    soft fail."""

    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    NOT_COMPARABLE = "not_comparable"
    UNCONFIRMABLE = "unconfirmable"
    BLOCKED_INCOMPLETE = "blocked_incomplete"


@dataclass(frozen=True)
class LotAmount:
    """One lot's contribution to a derived figure, priced by its OWN class.

    `cross_class` records that the price came from a class the fund does not
    hold at this date (INV-17). It is carried per lot rather than per holding
    because that is the granularity at which it is true.
    """

    lot_id: str
    security_class: str
    shares: int
    price_per_share: Decimal
    amount: Decimal
    cross_class: bool


@dataclass(frozen=True)
class Result:
    """One validator's finding about one subject.

    `delta` is derived rather than stored. Two numbers and a difference are
    three fields of which one can disagree with the other two, and the figure
    an auditor reads must not be able to drift from the pair it came from.
    """

    validator: str
    subject: str
    outcome: Outcome
    reason: str
    computed: Decimal | None = None
    stated: Decimal | None = None
    evidence: tuple[str, ...] = ()
    lineage: tuple[LotAmount, ...] = field(default_factory=tuple)

    @property
    def delta(self) -> Decimal | None:
        if self.computed is None or self.stated is None:
            return None
        return self.stated - self.computed


@dataclass(frozen=True)
class Derivation:
    """A derived value, or the named reason there is none."""

    value: Decimal | None
    reason: str
    evidence: tuple[str, ...] = ()
    lineage: tuple[LotAmount, ...] = ()


@dataclass(frozen=True)
class FxRate:
    """INV-6's shape: a directed pair, a cited source, and two dates.

    `observed_date` and `effective_for` are separate and are both required to
    match, because the collapse the invariant sweep found was copying a stale
    rate and relabelling only its effective date. Date equality alone does not
    prove observation.
    """

    base: str
    quote: str
    rate: Decimal
    observed_date: date
    effective_for: date
    source_claim_id: str
    source_document_version_id: str


@dataclass(frozen=True)
class RealizationTerms:
    """What a realisation paid, and the four things that are NOT netted into it.

    Fees, escrow, earnout and withholding each reconcile on their own line.
    Subtracting them before comparing against `realized_shares × cash_per_share`
    is how a gross-consideration check silently becomes a net-proceeds check,
    and then agrees with a wire that is short by the escrow.
    """

    lot_id: str
    realized_on: date
    realized_shares: int
    cash_per_share: Decimal
    stated_gross: Decimal | None = None
    stated_net: Decimal | None = None
    fees: Decimal = _ZERO
    escrow: Decimal = _ZERO
    earnout: Decimal = _ZERO
    withholding: Decimal = _ZERO


@dataclass(frozen=True)
class RoundStatement:
    """One figure a document states about one financing round, with its join key.

    SPEC §8's V4 joins by company, round, effective date, currency and
    capitalization scope. Two post-money valuations of the same company on a
    different capitalization basis are not two readings of one number.
    """

    claim_id: str
    company: str
    round_name: str
    effective_date: date
    currency: str
    capitalization_scope: str


#: Derivation reasons that produce a FIGURE which nonetheless cannot validate
#: anything. Kept beside `_refusal_outcome` because it answers the same
#: question one step later: that function decides what an absent value means,
#: this one decides what a present-but-non-confirming value means.
_CARRIED_BUT_NOT_CONFIRMING = frozenset({"MANAGEMENT_CARRYING_VALUE"})


def _refusal_outcome(reason: str) -> Outcome:
    """Which kind of not-run a refusal reason is. No default, deliberately.

    A new refusal reason that fell through to `unconfirmable` would report an
    ingestion gap as an evidence gap and nothing would say so.
    """
    if reason.startswith("NO_PRICE_FOR_CLASS:"):
        return Outcome.UNCONFIRMABLE
    known = {
        "NO_APPLICABLE_EVIDENCE": Outcome.UNCONFIRMABLE,
        "NO_PRICE_IN_EVIDENCE": Outcome.UNCONFIRMABLE,
        "COMPONENT_WITHOUT_SHARE_COUNT": Outcome.BLOCKED_INCOMPLETE,
        "NO_VALUE_FIELD_CITED": Outcome.BLOCKED_INCOMPLETE,
    }
    if reason not in known:
        raise InvalidPolicyInput(
            f"{reason!r} is not an enumerated refusal reason, so which of SPEC §8's "
            f"six outcomes it is has not been decided. Decide it here rather than "
            f"letting it default."
        )
    return known[reason]


def _per_class(
    ledger: Ledger,
    holding_id: str,
    on: date,
    priced: Sequence[EvidenceClaim],
    *,
    authorized: bool,
) -> Derivation:
    """Held lots × the price for each lot's OWN class at this date (INV-17).

    Taking one price and applying it to every held lot is the defect this
    exists to prevent: Lucra holds 750,000 Series A-1 at $2.00 while the mark
    uses the Series A-2 price of $3.00 from a CEO email, and a holding-level
    price would derive the reported figure and call it supported.

    A class no relied-upon claim prices is left uncovered rather than priced
    from the nearest thing to hand — unless a valuation policy decision scoped
    to this holding and date says otherwise (`authorized`), and then the
    borrowing is recorded per lot in `cross_class`.
    """
    held = ledger.held_lots(holding_id, on)
    if any(lot.shares_at(on) is None for lot in held):
        return Derivation(None, "COMPONENT_WITHOUT_SHARE_COUNT")

    ordered = sorted(priced, key=lambda c: (c.issued_date, c.id))
    if not ordered:
        return Derivation(None, "NO_PRICE_IN_EVIDENCE")
    by_class = {c.priced_class: c for c in ordered if c.priced_class is not None}
    latest = ordered[-1]

    total = _ZERO
    lineage: list[LotAmount] = []
    uncovered: set[str] = set()
    used: list[str] = []
    for lot in held:
        held_class = lot.class_at(on)
        claim = by_class.get(held_class)
        if claim is None:
            if not authorized:
                uncovered.add(held_class)
                continue
            claim = latest
        shares = lot.shares_at(on)
        price = claim.price_per_share
        if shares is None or price is None:
            return Derivation(None, "COMPONENT_WITHOUT_SHARE_COUNT")
        amount = Decimal(shares) * price
        total += amount
        used.append(claim.id)
        lineage.append(
            LotAmount(
                lot_id=lot.id,
                security_class=held_class,
                shares=shares,
                price_per_share=price,
                amount=amount,
                cross_class=claim.priced_class != held_class,
            )
        )
    if uncovered:
        return Derivation(None, f"NO_PRICE_FOR_CLASS:{','.join(sorted(uncovered))}")
    return Derivation(
        total,
        "PER_CLASS_SHARES_X_PPS",
        evidence=tuple(dict.fromkeys(used)),
        lineage=tuple(lineage),
    )


#: WHOSE WORD a stated amount is, keyed by the class of document stating it.
#: The value is the reason code; `None` means the figure is real but validates
#: nothing, because the fund is the one asserting it.
#:
#: This replaced `if source_class is not ADMINISTRATOR_STATEMENT` — a rule that
#: named one class and treated every other amount-bearing document as a third
#: party's conclusion by default. Moonfare's FY2024 FX memo is the fund's own
#: paperwork ("Prepared by Fund Operations; reviewed by the CFO") and it minted
#: `THIRD_PARTY_CONCLUSION`, so V2 reported `pass` on management's own memo
#: confirming management's own mark. `r2` had it right all along —
#: `insufficient` / `MANAGEMENT_ASSERTION_WITHOUT_PRIMARY_SOURCE` — so two
#: layers disagreed about one document and only one of them was right.
#:
#: A cross-family review found it. The oracle encodes the same preference, so
#: 175 comparisons agreed with the defect: `derived.json` could not have caught
#: this, and the fix is not confirmed by the suite going green.
#:
#: Enumerated with no default, like the sufficiency matrix. The defect existed
#: because this decision had an implicit else-branch.
_STATED_AMOUNT_AUTHORITY: dict[SourceClass, str | None] = {
    SourceClass.THIRD_PARTY_VALUATION_MEMO: "THIRD_PARTY_CONCLUSION",
    SourceClass.ADMINISTRATOR_STATEMENT: "ADMINISTRATOR_NAV",
    SourceClass.FUND_INTERNAL_RECORD: None,
}


def derive_mark(ledger: Ledger, holding_id: str, on: date) -> Derivation:
    """What the mark WOULD be from the evidence relied upon at this date.

    The priority is authority, not convenience: a third party's concluded value
    stands as concluded (INV-1 — the system may recompute as a cross-check and
    must never substitute its own arithmetic), then an administrator's NAV,
    then the fund's own shares × the price for each class.

    A figure the FUND states about itself is none of those. It is reported —
    the document really does say it — and it validates nothing.
    """
    relied = supersede(applicable_claims(ledger, holding_id, RequirementCode.R2, on))
    if not relied:
        return Derivation(None, "NO_APPLICABLE_EVIDENCE")

    with_amount = [(c, v) for c in relied if (v := stated_value(c)) is not None]
    for claim, _ in with_amount:
        if claim.source_class not in _STATED_AMOUNT_AUTHORITY:
            raise InvalidPolicyInput(
                f"claim {claim.id} states an amount and its source class "
                f"{claim.source_class.value!r} is not in _STATED_AMOUNT_AUTHORITY. "
                f"Decide whose word that figure is — independent, the "
                f"administrator's, or the fund's own — and add it deliberately."
            )
    for claim, amount in with_amount:
        reason = _STATED_AMOUNT_AUTHORITY[claim.source_class]
        if reason is None:
            # The fund's own carrying value. Carried, never treated as
            # confirmation: `unconfirmable` would say the evidence is silent,
            # and it is not — it is the fund speaking about itself, which is a
            # different finding and a different next action.
            return Derivation(amount, "MANAGEMENT_CARRYING_VALUE", (claim.id,))
        return Derivation(amount, reason, (claim.id,))

    priced = [c for c in relied if c.price_per_share is not None]
    if not priced:
        if any(c.source_class in _AMOUNT_BEARING for c in relied):
            return Derivation(
                None,
                "NO_VALUE_FIELD_CITED",
                tuple(c.id for c in relied if c.source_class in _AMOUNT_BEARING),
            )
        return Derivation(None, "NO_PRICE_IN_EVIDENCE")

    return _per_class(
        ledger, holding_id, on, priced, authorized=bool(ledger.decisions_for(holding_id, on))
    )


def _compare(
    validator: str,
    subject: str,
    derived: Derivation,
    stated: Decimal | None,
) -> Result:
    """One derived figure against one stated figure, with nothing implied.

    A derivation that produced no value cannot pass or fail, and a stated figure
    that is absent cannot be compared to one that is present. Both are said out
    loud rather than folded into a verdict.
    """
    if derived.value is None:
        return Result(
            validator=validator,
            subject=subject,
            outcome=_refusal_outcome(derived.reason),
            reason=derived.reason,
            stated=stated,
            evidence=derived.evidence,
        )
    if derived.reason in _CARRIED_BUT_NOT_CONFIRMING:
        # The figure is real and the document states it; what it cannot do is
        # confirm the mark, because the fund is the author of both. Comparing
        # them is circular, and `pass` is the answer that circularity produces
        # if nothing stops it — which is exactly what happened to Moonfare
        # FY2024 until a cross-family review caught it.
        #
        # `not_comparable` rather than `unconfirmable`: the evidence is not
        # silent. It speaks, and it is the same voice as the assertion under
        # audit. Both figures and the delta are carried so an auditor can see
        # the position without the system pretending it checked it.
        return Result(
            validator=validator,
            subject=subject,
            outcome=Outcome.NOT_COMPARABLE,
            reason=derived.reason,
            computed=derived.value,
            stated=stated,
            evidence=derived.evidence,
            lineage=derived.lineage,
        )
    if stated is None:
        return Result(
            validator=validator,
            subject=subject,
            outcome=Outcome.BLOCKED_INCOMPLETE,
            reason="NO_STATED_FIGURE_TO_COMPARE",
            computed=derived.value,
            evidence=derived.evidence,
            lineage=derived.lineage,
        )
    return Result(
        validator=validator,
        subject=subject,
        outcome=Outcome.PASS if derived.value == stated else Outcome.FAIL,
        reason=derived.reason,
        computed=derived.value,
        stated=stated,
        evidence=derived.evidence,
        lineage=derived.lineage,
    )


def _reported_mark(ledger: Ledger, holding_id: str, on: date) -> Decimal | None:
    period = ledger.period_at(ledger.holdings[holding_id].fund_id, on)
    return None if period is None else ledger.mark_at(holding_id, period.id)


def v1_entry_cost(lot: Lot) -> Result:
    """V1 · entry cost == shares × entry price per share, per lot.

    A lot with no share count is `not_applicable` and never `pass`. Moonfare's
    fund interest, The Mom Project's convertible note and Jio's LP interest are
    the three, and each one's cost is a real number that reconciles to nothing
    per-share — passing them would report three checks that never ran.
    """
    if lot.shares is None:
        return Result(
            "V1", lot.id, Outcome.NOT_APPLICABLE, "NO_SHARE_COUNT", stated=lot.cost_amount
        )
    if lot.entry_pps is None:
        return Result(
            "V1", lot.id, Outcome.NOT_APPLICABLE, "NO_ENTRY_PRICE", stated=lot.cost_amount
        )
    computed = Decimal(lot.shares) * lot.entry_pps
    return Result(
        validator="V1",
        subject=lot.id,
        outcome=Outcome.PASS if computed == lot.cost_amount else Outcome.FAIL,
        reason="SHARES_X_ENTRY_PPS",
        computed=computed,
        stated=lot.cost_amount,
    )


def v1_all(ledger: Ledger) -> list[Result]:
    return [v1_entry_cost(lot) for lot in ledger.lots]


def v2_mark(ledger: Ledger, holding_id: str, on: date) -> Result:
    """V2 · the reported mark against what the evidence derives, per held lot."""
    subject = f"{holding_id}@{on.isoformat()}"
    if not ledger.held_lots(holding_id, on):
        return Result("V2", subject, Outcome.NOT_APPLICABLE, "NOT_HELD_AT_MEASUREMENT_DATE")
    derived = derive_mark(ledger, holding_id, on)
    return _compare("V2", subject, derived, _reported_mark(ledger, holding_id, on))


def v4_fully_diluted_shares(
    *,
    post_money: Decimal,
    price_per_share: Decimal,
    stated_shares: Decimal,
    source: RoundStatement,
    price_source: RoundStatement | None = None,
    shares_source: RoundStatement | None = None,
) -> Result:
    """V4 · post-money ÷ price per share == the stated fully diluted count.

    Dream states all three on one claim — $800,000,000, $8.00 and 100,000,000 —
    and that is the join: same company, same round, same effective date, same
    currency, same capitalization scope. Where the figures come from statements
    that do not agree on those five, the answer is `not_comparable` with the
    delta recorded, never `fail`: SPEC §15 cut V4's tolerance to exact Decimal
    equality precisely so that a rounded post-money reports as incomparable
    instead of as a discrepancy nobody can act on.
    """
    sources = [s for s in (price_source, shares_source) if s is not None]
    key = (
        source.company,
        source.round_name,
        source.effective_date,
        source.currency,
        source.capitalization_scope,
    )
    if any(
        (s.company, s.round_name, s.effective_date, s.currency, s.capitalization_scope) != key
        for s in sources
    ):
        return Result(
            validator="V4",
            subject=source.claim_id,
            outcome=Outcome.NOT_COMPARABLE,
            reason="JOIN_KEYS_DIFFER",
            stated=stated_shares,
            evidence=tuple(dict.fromkeys([source.claim_id, *(s.claim_id for s in sources)])),
        )
    if price_per_share == _ZERO:
        return Result(
            validator="V4",
            subject=source.claim_id,
            outcome=Outcome.BLOCKED_INCOMPLETE,
            reason="ZERO_PRICE_PER_SHARE",
            stated=stated_shares,
            evidence=(source.claim_id,),
        )
    implied = post_money / price_per_share
    return Result(
        validator="V4",
        subject=source.claim_id,
        outcome=Outcome.PASS if implied == stated_shares else Outcome.NOT_COMPARABLE,
        reason="POST_MONEY_OVER_PRICE_PER_SHARE",
        computed=implied,
        stated=stated_shares,
        evidence=(source.claim_id,),
    )


def v7_fx_rate_present(
    ledger: Ledger, holding_id: str, on: date, observed: Sequence[FxRate] = ()
) -> Result:
    """V7 · a rate observed FOR this measurement date, directed and cited.

    Never a prior period's rate. Moonfare FY2025 has no 12/31/2025 rate in the
    corpus, so the correct behaviour is to report the gap (INV-6) — carrying
    1,048,515 forward is the failure this check exists to make visible, and it
    is a failure that reconciles to itself perfectly.

    `observed` is empty in every real run today: the FY2023 and FY2024 rates are
    cited facts on their memos and `policy.inputs.Ledger` does not carry them as
    `FxRate`s. A date where an in-scope claim CITES A RATE FOR THAT DATE is
    therefore `blocked_incomplete` — the rate exists and this system has not
    loaded it — while a date no cited rate names is the genuine `fail`.

    "Cites a rate for that date", not "is in scope at that date". A reliance
    window says how long a document may be relied upon; it does not say when a
    rate was observed, and reading the second off the first is the FX
    carry-forward INV-6 forbids.
    """
    subject = f"{holding_id}@{on.isoformat()}"
    if ledger.holdings[holding_id].position_type is not PositionType.FX_DENOMINATED_INTEREST:
        return Result("V7", subject, Outcome.NOT_APPLICABLE, "NOT_AN_FX_DENOMINATED_POSITION")

    for_date = [r for r in observed if r.effective_for == on]
    if not for_date:
        # A claim can only stand in for THIS date's rate if it cites a rate
        # whose own effective date IS this date. Being merely in scope is not
        # enough, and the difference is INV-6 exactly.
        #
        # This read `if not observed and in_scope` over every R2-applicable
        # claim. While Moonfare's FY2024 memo closed its window at its own
        # measurement date the two agreed by accident, and when that window was
        # briefly opened they came apart: at 12/31/2025 the FY2024 memo was in
        # scope, so V7 reported `blocked_incomplete` — "the rate exists and this
        # system has not loaded it" — about a rate observed a year earlier. The
        # corpus holds no 12/31/2025 rate at all. That is the carry-forward this
        # check exists to make visible, reported as a loading gap.
        #
        # The window is closed again on the source's own words, so this branch
        # is not what turns FY2025 red today. It is written this way so that it
        # would be: a guard that only works while a neighbouring field happens
        # to agree with it is not a guard.
        #
        # `not observed` STAYS, and a review said it could go. The argument was
        # that once `in_scope` filters on the cited effective date it answers
        # the question precisely, so the caller-facing guard is redundant.
        # Removing it turned `test_v7_never_reuses_a_prior_periods_rate` from
        # `fail` to `blocked_incomplete`: a caller who supplies the 12/31/2023
        # rate and asks about 12/31/2024 got told the rate was merely unloaded,
        # because the FY2024 memo does cite one for that date.
        #
        # `blocked_incomplete` is arguably the more descriptive answer there,
        # and it is still the wrong one to hand this caller. It means "load the
        # figure" — an instruction aimed at this system — when what happened is
        # that a prior period's rate was offered for a date it does not cover.
        # That is a finding about the SUBMISSION, and demoting it to a loading
        # note is exactly the softening this check exists to refuse.
        in_scope = [
            c
            for c in supersede(applicable_claims(ledger, holding_id, RequirementCode.R2, on))
            if "fx_rate" in c.facts and c.fact_dates.get("fx_rate_effective_date") == on
        ]
        if not observed and in_scope:
            return Result(
                validator="V7",
                subject=subject,
                outcome=Outcome.BLOCKED_INCOMPLETE,
                reason="FX_RATE_NOT_IN_LEDGER",
                evidence=tuple(c.id for c in in_scope),
            )
        return Result("V7", subject, Outcome.FAIL, "unsupported_missing_fx")
    if len(for_date) > 1:
        return Result(
            validator="V7",
            subject=subject,
            outcome=Outcome.BLOCKED_INCOMPLETE,
            reason="MULTIPLE_FX_RATES_FOR_DATE",
            evidence=tuple(r.source_claim_id for r in for_date),
        )

    rate = for_date[0]
    evidence = (rate.source_claim_id,)
    if not rate.source_claim_id or not rate.source_document_version_id:
        return Result("V7", subject, Outcome.FAIL, "FX_RATE_UNCITED", evidence=evidence)
    if rate.base == rate.quote or not rate.base or not rate.quote:
        return Result("V7", subject, Outcome.FAIL, "FX_RATE_PAIR_UNDIRECTED", evidence=evidence)
    if rate.observed_date != rate.effective_for:
        return Result(
            validator="V7",
            subject=subject,
            outcome=Outcome.FAIL,
            reason="FX_RATE_NOT_OBSERVED_FOR_DATE",
            computed=rate.rate,
            evidence=evidence,
        )
    return Result(
        validator="V7",
        subject=subject,
        outcome=Outcome.PASS,
        reason="FX_RATE_OBSERVED_FOR_MEASUREMENT_DATE",
        computed=rate.rate,
        evidence=evidence,
    )


def _rounds_to(recomputed: Decimal, stated: Decimal, unit: Decimal | None) -> bool:
    """Is `stated` what `recomputed` becomes at the unit the source says it used?

    No unit means no claim of rounding, and then nothing but exact agreement is
    a rounding variance. The unit is never guessed from the shape of the stated
    figure: a tolerance inferred from the number it is meant to be checking
    grows to fit whatever it finds.
    """
    if unit is None or unit == _ZERO:
        return False
    return stated == (recomputed / unit).to_integral_value(rounding=ROUND_HALF_EVEN) * unit


def v8_fx_recomputation(
    *,
    subject: str,
    concluded: Decimal,
    foreign_amount: Decimal,
    rate: FxRate,
    rounding_unit: Decimal | None = None,
) -> Result:
    """V8 · recompute the concluded value, and NEVER assert equality on it.

    Moonfare FY2023: EUR 950,000 × 1.0526 = 999,970 against a concluded
    1,000,000 the memo itself labels rounded. The delta is 30, the
    classification is `ROUNDING_VARIANCE`, and the outcome is **pass** — a
    validator that asserted equality would go red on a correct number, and the
    repair someone reaches for next is writing 999,970 back over an audited
    third party's conclusion (INV-1).

    `rounding_unit` is the unit the source says it rounded to. It is a
    parameter, not an inference: SPEC §15 cut V8 to explicit classification
    only, so an unrecognised variance routes to a person instead of being
    explained by a tolerance this module invented.
    """
    recomputed = foreign_amount * rate.rate
    delta = concluded - recomputed
    evidence = (rate.source_claim_id,)
    if delta == _ZERO:
        classification, outcome = "EXACT", Outcome.PASS
    elif _rounds_to(recomputed, concluded, rounding_unit):
        classification, outcome = "ROUNDING_VARIANCE", Outcome.PASS
    else:
        classification, outcome = "UNRECOGNISED_VARIANCE", Outcome.FAIL
    return Result(
        validator="V8",
        subject=subject,
        outcome=outcome,
        reason=classification,
        computed=recomputed,
        stated=concluded,
        evidence=evidence,
    )


def v9_realization(terms: RealizationTerms) -> Result:
    """V9 · gross cash == realized shares × cash per share. Gross only.

    Jackpocket: 500,000 × $6.20 = $3,100,000. Fees, escrow, earnout and
    withholding are reconciled by `v9_net_reconciliation` and are never
    subtracted here, in either direction.
    """
    computed = Decimal(terms.realized_shares) * terms.cash_per_share
    if terms.stated_gross is None:
        return Result(
            validator="V9",
            subject=terms.lot_id,
            outcome=Outcome.BLOCKED_INCOMPLETE,
            reason="NO_STATED_GROSS_IN_LEDGER",
            computed=computed,
        )
    return Result(
        validator="V9",
        subject=terms.lot_id,
        outcome=Outcome.PASS if computed == terms.stated_gross else Outcome.FAIL,
        reason="GROSS_IS_SHARES_X_CASH_PER_SHARE",
        computed=computed,
        stated=terms.stated_gross,
    )


def v9_net_reconciliation(terms: RealizationTerms) -> Result:
    """The other line: gross less fees, escrow, earnout and withholding.

    Separate from `v9_realization` on purpose. One function returning whichever
    comparison the data supported is how the gross identity quietly becomes a
    net identity when an escrow appears.
    """
    gross = Decimal(terms.realized_shares) * terms.cash_per_share
    computed = gross - terms.fees - terms.escrow - terms.earnout - terms.withholding
    if terms.stated_net is None:
        return Result(
            validator="V9",
            subject=terms.lot_id,
            outcome=Outcome.BLOCKED_INCOMPLETE,
            reason="NO_STATED_NET_IN_LEDGER",
            computed=computed,
        )
    return Result(
        validator="V9",
        subject=terms.lot_id,
        outcome=Outcome.PASS if computed == terms.stated_net else Outcome.FAIL,
        reason="NET_IS_GROSS_LESS_FEES_ESCROW_EARNOUT_WITHHOLDING",
        computed=computed,
        stated=terms.stated_net,
    )


def realization_from_ledger(ledger: Ledger, holding_id: str, on: date) -> list[Result]:
    """V9 over what the ledger holds: one result per lot realised on or before `on`.

    The cash per share is the price on the realisation claim relied upon for R4.
    The stated gross is not in the ledger at all, so every result here is
    `blocked_incomplete` carrying the computed figure — which is still the
    number an auditor checks the wire against, and is not the same as silence.
    """
    claims = applicable_claims(ledger, holding_id, RequirementCode.R4, on)
    out: list[Result] = []
    for lot in ledger.lots_for(holding_id):
        if lot.realized_date is None or lot.realized_date > on:
            continue
        covering = [
            c
            for c in claims
            if c.price_per_share is not None
            and c.priced_class in (None, lot.class_at(lot.realized_date))
        ]
        if not covering:
            out.append(
                Result("V9", lot.id, Outcome.UNCONFIRMABLE, "NO_REALIZATION_PRICE_IN_EVIDENCE")
            )
            continue
        shares = lot.shares_at(lot.realized_date)
        if shares is None:
            out.append(Result("V9", lot.id, Outcome.BLOCKED_INCOMPLETE, "NO_REALIZED_SHARE_COUNT"))
            continue
        claim = max(covering, key=lambda c: (c.issued_date, c.id))
        price = claim.price_per_share
        assert price is not None
        result = v9_realization(
            RealizationTerms(
                lot_id=lot.id,
                realized_on=lot.realized_date,
                realized_shares=shares,
                cash_per_share=price,
            )
        )
        out.append(
            Result(
                validator=result.validator,
                subject=result.subject,
                outcome=result.outcome,
                reason=result.reason,
                computed=result.computed,
                stated=result.stated,
                evidence=(claim.id,),
            )
        )
    return out


def v10_quoted_value(ledger: Ledger, holding_id: str, on: date) -> Result:
    """V10 · the close from the exchange's last completed session ON OR BEFORE D.

    Banzai's FY2023 quote is dated 12/29/2023, not 12/31 — the year ended on a
    Sunday. A check that demanded a quote dated exactly at the measurement date
    would report the correct figure as missing, and a check that took the most
    recent quote in the file would use the 12/31/2024 close for FY2023.

    The exchange's identity is not in the ledger: `source_class ==
    public_market_quote` is the recorded judgement that this is an official
    market close, and there is no field distinguishing a primary listing from a
    secondary one or an adjusted close from an unadjusted one. SPEC §15 cut the
    market calendar on the ground that the corpus quotes are already dated to
    trading days; the selection rule here is the surviving half of it.
    """
    subject = f"{holding_id}@{on.isoformat()}"
    if ledger.holdings[holding_id].position_type is not PositionType.PUBLIC_LISTED:
        return Result("V10", subject, Outcome.NOT_APPLICABLE, "NOT_A_LISTED_POSITION")
    quotes = [
        c
        for c in supersede(applicable_claims(ledger, holding_id, RequirementCode.R2, on))
        if c.source_class is SourceClass.PUBLIC_MARKET_QUOTE
    ]
    if not quotes:
        return Result("V10", subject, Outcome.UNCONFIRMABLE, "NO_QUOTE_IN_EVIDENCE")
    completed = [c for c in quotes if c.issued_date <= on]
    if not completed:
        return Result(
            validator="V10",
            subject=subject,
            outcome=Outcome.FAIL,
            reason="QUOTE_AFTER_MEASUREMENT_DATE",
            evidence=tuple(c.id for c in quotes),
        )
    chosen = max(completed, key=lambda c: (c.issued_date, c.id))
    derived = _per_class(ledger, holding_id, on, [chosen], authorized=False)
    result = _compare("V10", subject, derived, _reported_mark(ledger, holding_id, on))
    return Result(
        validator=result.validator,
        subject=result.subject,
        outcome=result.outcome,
        reason="QUOTED_CLOSE_X_SHARES" if derived.value is not None else result.reason,
        computed=result.computed,
        stated=result.stated,
        evidence=(chosen.id,),
        lineage=result.lineage,
    )


def v13_recap(lot: Lot) -> Result:
    """V13 · prior shares × exchange ratio == the post-recap share count.

    Sway: 800,000 × 1.09375 = 875,000, exactly. A ratio that produces a
    fractional share is `fail` with `FRACTIONAL_SHARE_UNSUPPORTED` — INV-11 puts
    cash-in-lieu and fractional interests out of scope, so this is a rejection
    and not an instruction to round. Rounding here would put a share count in
    the ledger that no document states.
    """
    conversion = lot.conversion
    if conversion is None:
        return Result("V13", lot.id, Outcome.NOT_APPLICABLE, "NO_RECORDED_CONVERSION")
    if lot.shares is None:
        return Result("V13", lot.id, Outcome.BLOCKED_INCOMPLETE, "NO_PRIOR_SHARE_COUNT")
    computed = Decimal(lot.shares) * conversion.exchange_ratio
    stated = Decimal(conversion.shares)
    if computed != computed.to_integral_value():
        return Result(
            validator="V13",
            subject=lot.id,
            outcome=Outcome.FAIL,
            reason="FRACTIONAL_SHARE_UNSUPPORTED",
            computed=computed,
            stated=stated,
        )
    return Result(
        validator="V13",
        subject=lot.id,
        outcome=Outcome.PASS if computed == stated else Outcome.FAIL,
        reason="PRIOR_SHARES_X_EXCHANGE_RATIO",
        computed=computed,
        stated=stated,
    )


def v13_all(ledger: Ledger) -> list[Result]:
    return [v13_recap(lot) for lot in ledger.lots if lot.conversion is not None]


__all__ = [
    "Derivation",
    "FxRate",
    "LotAmount",
    "Outcome",
    "RealizationTerms",
    "Result",
    "RoundStatement",
    "derive_mark",
    "realization_from_ledger",
    "v10_quoted_value",
    "v13_all",
    "v13_recap",
    "v1_all",
    "v1_entry_cost",
    "v2_mark",
    "v4_fully_diluted_shares",
    "v7_fx_rate_present",
    "v8_fx_recomputation",
    "v9_net_reconciliation",
    "v9_realization",
]
