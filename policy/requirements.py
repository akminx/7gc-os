"""The five PBC requirements — SPEC §7.1, §7.2, §7.3.

Each is a pure function of `policy.inputs.Ledger` and a measurement date.
`assess_row` runs all five and reduces them to the row verdict (§6.2.1).

**Applicability is the verdict.** There is no `applicable` boolean beside it.
An earlier contract carried both, which made fourteen combinations representable
of which six are nonsense, and the validators guarding them were written wrong
twice — the worst of which let R1 be marked inapplicable and made a holding with
no existence evidence read as fully supported. `verdict is not_applicable` is the
one place that question is answered.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from packages.contracts.enums import ExecutionStatus, RequirementCode, RequirementVerdict
from policy.inputs import EvidenceClaim, Ledger, Lot, MaterialComponent
from policy.reducer import best, reduce_links, reduce_row, worst
from policy.valid_tuples import gap_reason, gap_result, lookup

#: Only R2 expires. An executed purchase agreement proves the fund bought the
#: shares in 2021 and goes on proving it in 2025 — INV-5 is that a mark at a new
#: date is a new assertion, not that the acquisition un-happens. R2 asks what the
#: position is worth *now*, so its evidence is read inside the window the source
#: itself states (INV-16).
WINDOWED = frozenset({RequirementCode.R2})

_NA = RequirementVerdict.NOT_APPLICABLE
_MISSING = RequirementVerdict.MISSING
_SUFFICIENT = RequirementVerdict.SUFFICIENT
_PARTIAL = RequirementVerdict.PARTIAL
_INSUFFICIENT = RequirementVerdict.INSUFFICIENT


@dataclass(frozen=True)
class StaleComponent:
    """A material component whose newest qualifying support is too old.

    `latest` is `None` when the component has no dated support at all. That is
    not "unknown" — SPEC §7.2 says absent dated support counts as stale, and
    Because Market, which has no evidence of any kind, is the case.
    """

    component: str
    latest: date | None


@dataclass(frozen=True)
class Outcome:
    """One requirement's finding at one measurement date."""

    requirement: RequirementCode
    verdict: RequirementVerdict
    reasons: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    relied_on: tuple[str, ...] = ()
    per_lot: dict[str, RequirementVerdict] = field(default_factory=dict)
    cross_class: bool = False
    pro_forma: bool = False
    subsequent_evidence: bool = False
    stale_components: tuple[StaleComponent, ...] = ()
    unchanged_since: date | None = None
    realized_lots: tuple[str, ...] = ()
    note: str | None = None


def applicable_claims(
    ledger: Ledger, holding_id: str, requirement: RequirementCode, on: date
) -> list[EvidenceClaim]:
    """Claims relied on for this requirement that speak to this date.

    For R2 the source's own reliance window decides (INV-16): a memo that says
    it must not be relied on after its measurement date is out of scope
    afterwards, whatever the matrix would otherwise say about its class. That
    ordering is deliberate — INV-16 outranks the matrix, so the window is
    applied here, before any cell is consulted.
    """
    out = []
    for claim in ledger.claims:
        if claim.holding_id != holding_id or requirement not in claim.requirements:
            continue
        if requirement in WINDOWED:
            if claim.applicable_from > on:
                continue
            if claim.applicable_to is not None and claim.applicable_to < on:
                continue
        elif claim.issued_date > on:
            continue
        out.append(claim)
    # Chronological, then by id. `relied_on` reaches the packet as an ordered
    # list an auditor reads, and evidence reads in the order it arose. Sorting
    # here rather than in the SQL keeps the order a property of the policy layer:
    # it was inherited from whatever `order by` the adapter happened to use, so
    # changing that query silently changed what the packet printed.
    return sorted(out, key=lambda c: (c.issued_date, c.id))


def supersede(claims: list[EvidenceClaim]) -> list[EvidenceClaim]:
    """Drop claims a later one explicitly replaces. SPEC §7.4 rule 2.

    Supersession is **recorded, never inferred from dates**. The tempting rule —
    within a priced class, keep only the latest claim — is wrong on this corpus
    and would be invisible: Dream's Series B is asserted by a pro forma cap
    table (11/14) and corroborated by the CFO's closing notice (11/17), and
    inferring supersession would drop the cap table, taking the `pro_forma`
    label with it. Two claims about the same round are usually corroboration,
    not replacement, and only the fund knows which.
    """
    replaced = {c.supersedes_claim_id for c in claims if c.supersedes_claim_id}
    return [c for c in claims if c.id not in replaced]


#: Fields that state the fund's money actually moved, in whichever vocabulary
#: the position's own document class uses. Alternatives, not a conjunction: a
#: stock purchase agreement says "received … per the settlement statement", a
#: capital account statement says "contributed capital" against an unfunded
#: commitment of zero, and demanding the first of a fund interest reports a gap
#: the document already closes.
#:
#: `acquisition_consideration_usd` is Moonfare's, whose memo records the USD
#: consideration paid for the EUR interest at entry.
_SETTLEMENT_EVIDENCE = frozenset(
    {"settlement_amount_received", "contributed_capital", "acquisition_consideration_usd"}
)

#: ¶1's THREE named figures, and the fields that can state each.
#:
#: "Executed transaction documents supporting the Fund's acquisition of each
#: position …, INCLUDING share counts, price per share, and settlement of
#: funds." Settlement was required first and the other two were left to the
#: document class, which is the same shortcut one clause apart — the owner's
#: ruling is that the letter names three things and means three.
#:
#: Alternatives WITHIN a group, all three groups REQUIRED. A fund interest
#: states its size in units of commitment rather than shares, so
#: `capital_commitment` answers the share-count limb for one: the letter asks
#: how much of the thing the fund owns, and every document class says that in
#: its own words.
_ACQUISITION_FIGURES: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "NO_SHARE_COUNT_STATED",
        frozenset(
            {
                "fund_shares",
                "shares_held",
                "position_shares",
                "schedule_a_total_shares",
                "fund_series_a_shares",
                "fund_series_a2_shares",
                "fund_a3_shares",
                "capital_commitment",
            }
        ),
    ),
    (
        "NO_ACQUISITION_PRICE_STATED",
        frozenset(
            {
                "fund_price_per_share",
                "round_price_per_share",
                "original_purchase_pps",
                "fund_entry_price_per_share",
                "fund_series_a2_original_pps",
            }
        ),
    ),
    ("SETTLEMENT_OF_FUNDS_NOT_EVIDENCED", _SETTLEMENT_EVIDENCE),
)


def _acquisition_gaps(claims: Sequence[EvidenceClaim], lot: Lot) -> list[str]:
    """Which of ¶1's three figures these claims do not state, for THIS lot.

    POSITIVE, not merely present. The first version of the settlement half asked
    only whether a field NAME appeared, and a cross-family review passed it
    `contributed_capital = 0` — an investor who has committed and funded
    nothing — which read as settled. A commitment drawn to zero is the clearest
    evidence available that the money has NOT moved, and it satisfied the check
    written to prove that it had. The same rule applies to all three: a share
    count of zero is not a share count.

    A LOT WITH NO SHARES IS NOT SHORT OF A SHARE COUNT. Jio's LP interest, The
    Mom Project's convertible note and Moonfare's fund interest are bought as
    commitments and principal, not as shares, and `v1_entry_cost` already says
    so — it answers `not_applicable, NO_SHARE_COUNT` rather than failing them,
    because "each one's cost is a real number that reconciles to nothing
    per-share".

    Demanding a price per share of them reports a gap the fund can never close
    with a document that does not exist. That is the same error as naming only
    the stock-purchase vocabulary for settlement, made twice in one file, and
    the fix is the same: ask each position for cost in the terms its own
    instrument has. What ¶1 wants of these three is what the fund paid, and the
    settlement limb is where that lives.
    """
    stated = {
        name
        for claim in claims
        for name, value in claim.facts.items()
        if value is not None and value > 0
    }
    applicable = _ACQUISITION_FIGURES if lot.shares is not None else _ACQUISITION_FIGURES[-1:]
    return [reason for reason, fields in applicable if not (fields & stated)]


def r1(ledger: Ledger, holding_id: str, on: date) -> Outcome:
    """Existence and cost — evaluated per held lot, worst wins (INV-7).

    Per lot rather than per holding because a holding with one documented lot
    and one undocumented lot is `partial`, and a holding-level roll-up would
    round that to whichever lot was looked at first. Fluidstack is the case:
    Series A has its executed SPA, Series A-2's closing set is with counsel.
    """
    position = ledger.holdings[holding_id].position_type
    claims = applicable_claims(ledger, holding_id, RequirementCode.R1, on)
    per_lot: dict[str, RequirementVerdict] = {}
    actions: set[str] = set()
    reasons: set[str] = set()
    relied: list[str] = []

    for lot in ledger.held_lots(holding_id, on):
        held_class = lot.class_at(on)
        candidates: list[RequirementVerdict] = []
        covering: list[EvidenceClaim] = []
        for claim in claims:
            if claim.priced_class not in (None, held_class):
                continue
            covering.append(claim)
            cell = lookup(RequirementCode.R1, claim.source_class, claim.execution_status, position)
            candidates.append(cell.verdict)
            relied.append(claim.id)
            if cell.reason_code:
                reasons.add(cell.reason_code)
            actions.update(cell.next_actions)
        for gap in ledger.gaps_for(holding_id, RequirementCode.R1, lot.security_class):
            cell = gap_result(gap.kind)
            candidates.append(cell.verdict)
            actions.update(cell.next_actions)
            reasons.add(gap_reason(gap.kind))
        if not candidates:
            cell = gap_result(None)
            candidates.append(cell.verdict)
            actions.update(cell.next_actions)
            reasons.add(gap_reason(None))
        outcome = best(candidates)

        # ¶1's THREE FIGURES, PER LOT, from the claims covering THAT lot.
        #
        # Written first as a holding-wide union over every R1 claim, which a
        # cross-family review broke twice in one pass. A claim priced for a
        # class this lot is not — excluded from the lot's own assessment, and
        # absent from `relied_on` — still cleared settlement for it; and one
        # settlement cleared every acquisition the holding had. The scope of the
        # question is the lot, because that is the scope of the acquisition.
        if outcome is _SUFFICIENT and (gaps := _acquisition_gaps(covering, lot)):
            outcome = _PARTIAL
            reasons.update(gaps)
            actions.add("REQUEST_ACQUISITION_FIGURES")
        per_lot[lot.id] = outcome

    if not per_lot:
        # No lot held at this date. A realised position still appears in the
        # packet — its realisation is what R4 evidences — but existence and cost
        # of something no longer held is not a question the auditor asked.
        return Outcome(requirement=RequirementCode.R1, verdict=_NA)

    return Outcome(
        requirement=RequirementCode.R1,
        verdict=worst(list(per_lot.values())),
        reasons=tuple(sorted(reasons)),
        next_actions=tuple(sorted(actions)),
        relied_on=tuple(dict.fromkeys(relied)),
        per_lot=per_lot,
    )


def _contradictions(claims: list[EvidenceClaim]) -> list[str]:
    """Priced classes for which two relied-upon claims state different prices.

    A material contradiction is two claims pricing **the same security class**
    differently. Not two different prices anywhere in the evidence: Lucra's
    A-1 at $2.00 and A-2 at $3.00 are two facts about two classes, and calling
    that a contradiction would make every multi-class holding conflicting.
    """
    by_class: dict[str, set[Decimal]] = {}
    for claim in claims:
        if claim.priced_class is None or claim.price_per_share is None:
            continue
        by_class.setdefault(claim.priced_class, set()).add(claim.price_per_share)
    return sorted(k for k, prices in by_class.items() if len(prices) > 1)


def _pro_forma(relied: list[EvidenceClaim]) -> bool:
    """INV-4 · derived from what the fund actually holds, never from a label.

    True when a relied-upon claim is pro forma and no *executed* claim at least
    as recent has replaced it. Anthropic is why this is derived: management
    labels the 25Q4 mark PRO FORMA and there is no pro forma document — there is
    no document at all, only press. The label and the derivation disagree, and
    that disagreement is a reconciliation finding rather than something one side
    silently wins.
    """
    pro_forma = [c for c in relied if c.execution_status is ExecutionStatus.PRO_FORMA]
    if not pro_forma:
        return False
    latest = max(c.issued_date for c in pro_forma)
    return not any(
        c.execution_status is ExecutionStatus.EXECUTED and c.issued_date >= latest for c in relied
    )


def r2(ledger: Ledger, holding_id: str, on: date) -> Outcome:
    """Fair value support at this measurement date — the audit letter's ¶2.

    **¶2 is two branches, not one rule**, and which one applies depends on what
    the mark is based on:

        "For marks based on a financing round: the round's executed documents
         **or** pro forma capitalization table evidencing price per share. For
         marks based on other information: the underlying source **and**
         management's memo describing the basis of the mark."

    Using the "and" on a round-based mark, or the "or" on an other-information
    mark, is wrong in a different direction each time. Both branches are carried
    by the matrix cell for the source class, since the source class is what says
    which branch a document belongs to; `policy/valid_tuples.py` quotes the
    letter at each of them.

    The one thing the matrix key cannot express is ¶2's qualifier on the
    pro-forma disjunct — "evidencing price per share" is a property of the claim,
    not of the tuple — so the cell carries a `without_price_per_share` fallback
    and it is applied here.

    Off-class evidence is excluded from the reduction rather than capped after
    it. That is INV-17 and **not** ¶2: the letter says nothing about whether
    evidence for a class you do not hold may support one you do.
    """
    if not ledger.held_lots(holding_id, on):
        return Outcome(requirement=RequirementCode.R2, verdict=_NA)

    position = ledger.holdings[holding_id].position_type
    relied = supersede(applicable_claims(ledger, holding_id, RequirementCode.R2, on))
    held = ledger.held_lots(holding_id, on)
    held_classes = {lot.class_at(on) for lot in held}
    # INV-17 · a recorded valuation-policy decision is what licenses pricing one
    # class off another class's evidence. Read once, here, because two readers of
    # the same gate is how a decision recorded for one position starts clearing
    # another. Used by the off-class exclusion below and the cross-class cap.
    authorized = bool(ledger.decisions_for(holding_id, on))
    verdicts: list[RequirementVerdict] = []
    reasons: set[str] = set()
    actions: set[str] = set()
    off_class: list[str] = []

    for claim in relied:
        cell = lookup(RequirementCode.R2, claim.source_class, claim.execution_status, position)
        # ¶2's qualifier on the pro-forma disjunct: "pro forma capitalization
        # table **evidencing price per share**". A table that states no price is
        # not the document the letter accepts, so the cell's fallback applies.
        if cell.without_price_per_share is not None and claim.price_per_share is None:
            cell = cell.without_price_per_share
        # Owner ruling, 2026-07-26 · evidence about a class the fund does NOT
        # hold may not RAISE this requirement's verdict until a valuation-policy
        # decision is recorded.
        #
        # The letter is SILENT on this and the decision rests on INV-17, not on
        # ¶2. There is no sentence about whether evidence concerning a class you
        # do not hold may support one you do; the nearest thing is the framing of
        # the request itself — "for each portfolio investment **held** during the
        # periods under audit" — which leans against it, but that is inference.
        # A future reader who disagrees is disagreeing with an inference, so say
        # so rather than citing ¶2 at them.
        #
        # Lucra is the case: the fund holds Series A-1, and the CEO's email about
        # the Series A-2 close was lifting R2 from `insufficient` to `partial`
        # through `best()`. The cross-class cap below could not stop it — it only
        # lowers `sufficient` to `partial`, so it never saw the raise happen.
        # Pricing one class off another's evidence is a policy act (INV-17), and
        # it was arriving through the reducer instead of through pricing.
        if (
            claim.priced_class is not None
            and claim.priced_class not in held_classes
            and not authorized
        ):
            off_class.append(claim.priced_class)
            continue
        verdicts.append(cell.verdict)
        if cell.reason_code:
            reasons.add(cell.reason_code)
        actions.update(cell.next_actions)

    if off_class:
        # Named, not silently dropped. The claim stays in `relied_on` — it is in
        # scope, it is what makes the holding cross-class, and a packet that
        # hides the evidence it declined to count says less than the system
        # knows.
        reasons.add("OFF_CLASS_EVIDENCE_NOT_RELIED")

    if relied and not verdicts:
        # Everything in scope prices a class the fund does not hold. There is
        # evidence and it says something, so `insufficient` rather than
        # `missing` — the same reading as the `fund_internal_record` cell.
        #
        # Dream is the case, and it is worth stating because it looks like an
        # edge and is not: the fund holds Series A-1, and both relied-upon
        # documents price Series B. `validated_amount` has ALWAYS refused this
        # one — `not_derivable, NO_PRICE_FOR_CLASS:series_a1` — while the verdict
        # read `partial`. Two layers of the same system disagreeing about whether
        # the held class had support. They now agree.
        #
        # "Price Series B" is true of the CLAIMS, and a cross-family review was
        # right to point out that it is not true of the DOCUMENTS: Dream's pro
        # forma table lists 7GC under Series A-1 at $3.20, and the claim even
        # stores `fund_held_security_class`. That $3.20 is an ORIGINAL ISSUE
        # price restated in a later table, so the extractor is right not to key
        # it as a price for A-1 — 625,000 x $3.20 = $2,000,000 against a
        # $5,000,000 mark, and what shares first sold for does not support what
        # they are worth now. What was wrong was the reason's WORDING, which
        # said no document prices the held class while an auditor could open the
        # PDF and see one. Fixed in the gloss, not here: the code is an
        # identifier and the sentence is what a reader is owed.
        verdicts.append(_INSUFFICIENT)
        reasons.add("NO_SUPPORT_FOR_A_HELD_CLASS")

    if not relied:
        # Nothing in scope. WHY nothing is in scope is the finding: a document
        # with counsel and a document nobody can find call for different action,
        # and reducing both to "unsupported" is what makes a gap inventory
        # useless to the person who has to close it.
        #
        # The first distinction is between never-had and had-and-expired, and it
        # was missing. Because Market has no portfolio document of any kind;
        # Moonfare has TWO, and its FY2023 memo closes its own window in its own
        # words — "should not be relied upon for subsequent measurement dates
        # without update". Both rendered as `missing` with `REQUEST_FROM_COMPANY`
        # beside them, which reads as "go and find something" for a fund that
        # already holds the thing and needs it REFRESHED. Those are different
        # letters to different people.
        #
        # The verdict is `missing` either way and that is right — there is no
        # support at this date, and an expired memo is not weaker support, it is
        # no support. What changes is the reason and the action.
        expired = [
            c
            for c in ledger.claims
            if c.holding_id == holding_id
            and RequirementCode.R2 in c.requirements
            and c.applicable_to is not None
            and c.applicable_to < on
        ]
        if expired:
            verdicts.append(_MISSING)
            reasons.add("SUPPORT_OUTSIDE_ITS_OWN_RELIANCE_WINDOW")
            actions.add("REQUEST_UPDATED_VALUATION")
        else:
            gaps = ledger.gaps_for(holding_id, RequirementCode.R2)
            kind = gaps[0].kind if gaps else None
            cell = gap_result(kind)
            verdicts.append(cell.verdict)
            actions.update(cell.next_actions)
            reasons.add(gap_reason(kind, prefix="NO_APPLICABLE_SUPPORT"))

    contradicted = _contradictions(relied)
    if contradicted:
        resolved = {r.priced_class for r in ledger.resolutions if r.holding_id == holding_id}
        if not set(contradicted) <= resolved:
            return Outcome(
                requirement=RequirementCode.R2,
                verdict=reduce_links(verdicts, contradicted=True),
                reasons=("CONTRADICTORY_CLAIMS",),
                next_actions=("RESOLVE_CONTRADICTION",),
                relied_on=tuple(c.id for c in relied),
            )

    verdict = reduce_links(verdicts)

    covered = {c.priced_class for c in relied}
    # A document covering ONE class must not mark a multi-lot holding
    # sufficient. `None in covered` means some relied-upon claim is not
    # class-specific — an administrator statement values the whole interest —
    # and then no class is left uncovered by it.
    if None not in covered and held_classes - covered and verdict is _SUFFICIENT:
        verdict = _PARTIAL
        reasons.add("UNCOVERED_SECURITY_CLASS")
        actions.add("REQUEST_SUPPORT_FOR_CLASS")

    # INV-17 · cross-class pricing, derived from held class versus priced class
    # and independent of any label, so omitting a label cannot bypass it. The
    # test is set EQUALITY, and both one-way versions were wrong on this corpus:
    #
    #   priced − held   Lucra holds Series A-1 and the mark uses the A-2 price
    #                   from a CEO email. "Is every held class covered?" says
    #                   yes — A-1 has its own term sheet — while the figure that
    #                   reaches the packet comes from a class the fund does not
    #                   hold.
    #   held − priced   With B and C held and one claim pricing C, "is the priced
    #                   class held?" says yes, while the B shares are marked at
    #                   the C price. This is what INV-17 was written for.
    priced_classes = {c.priced_class for c in relied if c.priced_class is not None}
    cross_class = bool(priced_classes) and held_classes != priced_classes
    if cross_class and not authorized:
        if verdict is _SUFFICIENT:
            verdict = _PARTIAL
        reasons.add("CROSS_CLASS_POLICY_DECISION_REQUIRED")
        actions.add("RECORD_VALUATION_POLICY_DECISION")

    return Outcome(
        requirement=RequirementCode.R2,
        verdict=verdict,
        reasons=tuple(sorted(reasons)),
        next_actions=tuple(sorted(actions)),
        relied_on=tuple(c.id for c in relied),
        cross_class=cross_class,
        pro_forma=_pro_forma(relied),
        subsequent_evidence=any(c.effective_date > on for c in relied),
    )


def minus_months(anchor: date, months: int) -> date:
    """`anchor` shifted back N calendar months, clamping the day if it overflows."""
    year, month = anchor.year, anchor.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = anchor.day
    while day > 0:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    raise ValueError(f"no date {months} months before {anchor}")


def _stale(components: tuple[MaterialComponent, ...], on: date) -> list[StaleComponent]:
    """Components whose newest qualifying support predates the 12-month window.

    **The boundary is strict: exactly 12 months is not stale.** Capsule FY2023
    is the case — a memo dated 12/31/2022 read at 12/31/2023 is exactly twelve
    months old and R3 does not fire. `<` rather than `<=`, and that one
    character has its own guard because it has been wrong before.
    """
    threshold = minus_months(on, 12)
    out = []
    for component in components:
        latest = component.latest_on_or_before(on)
        if latest is None or latest < threshold:
            out.append(StaleComponent(component=component.name, latest=latest))
    return out


def r3(ledger: Ledger, holding_id: str, on: date) -> Outcome:
    """Unchanged-mark calibration — SPEC §7.2, the audit letter's ¶3.

    Two limbs, and this definition has been got wrong four times:

    **(a)** the reported amount equals the amount at the **immediately preceding
    mark observation** for this fund — which may fall in a lineage-only period.
    It said "audit measurement date" through r4, which made R3 structurally
    unable to fire at the *first* packet date, so Roofstock — flat at the same
    mark since November 2021 — escaped calibration at FY2023, which is exactly
    the position ¶3 addresses. Two questions had been conflated: whether a date
    is in packet scope, and whether a prior dated observation can prove the mark
    did not move.

    **(b)** **at least one** material component lacks qualifying support dated
    within the 12 calendar months preceding `on`. The quantifier was `every` in
    r2 and was wrong: Moonfare's fresh FX component rescued its 33-month-stale
    underlying valuation and R3 did not fire. `at least one` is also the correct
    audit logic — if any material part of a number rests on stale evidence, the
    number needs an assessment.

    A lineage-only period may serve **only** as the predecessor in (a). It never
    generates its own assessment, never counts as qualifying support in (b),
    never resets support age, and never enters packet completeness (INV-20).
    """
    fund_id = ledger.holdings[holding_id].fund_id
    period = ledger.period_at(fund_id, on)
    current = None if period is None else ledger.mark_at(holding_id, period.id)
    if current is None:
        return Outcome(requirement=RequirementCode.R3, verdict=_NA, note="no mark at this date")

    prior = [(d, amount) for d, amount in ledger.mark_observations(holding_id, fund_id) if d < on]
    if not prior:
        return Outcome(
            requirement=RequirementCode.R3, verdict=_NA, note="no preceding mark observation"
        )
    previous_date, previous_amount = prior[-1]
    if previous_amount != current:
        return Outcome(
            requirement=RequirementCode.R3,
            verdict=_NA,
            note=f"value changed since {previous_date.isoformat()}",
        )

    stale = _stale(ledger.components_for(holding_id), on)
    if not stale:
        return Outcome(
            requirement=RequirementCode.R3,
            verdict=_NA,
            note="all components have support within 12 months",
        )

    # V12 · the gap closes only on an APPROVED management assessment. A draft
    # leaves it open, which is the whole distinction PBC ¶3 turns on: the
    # auditor is asking for management's conclusion, not for management's
    # intention to reach one.
    approved = [a for a in ledger.assessments_for(holding_id, on) if a.status == "approved"]
    return Outcome(
        requirement=RequirementCode.R3,
        verdict=_SUFFICIENT if approved else _MISSING,
        reasons=() if approved else ("MARK_UNCHANGED_WITH_STALE_SUPPORT",),
        next_actions=() if approved else ("DRAFT_MANAGEMENT_ASSESSMENT",),
        stale_components=tuple(stale),
        unchanged_since=previous_date,
    )


def _realized_in_window(ledger: Ledger, holding_id: str, on: date) -> list[Lot]:
    """Lots realised in (previous packet date, `on`].

    Bounded below so a realisation is evidenced once, in the period it happened,
    rather than following the packet around forever.
    """
    fund_id = ledger.holdings[holding_id].fund_id
    previous = ledger.previous_packet_date(fund_id, on)
    return [
        lot
        for lot in ledger.lots_for(holding_id)
        if lot.realized_date is not None
        and lot.realized_date <= on
        and (previous is None or lot.realized_date > previous)
    ]


#: ¶4's three named figures, and the fields that can state each. Alternatives
#: WITHIN a group, all three groups REQUIRED — the letter says "support for
#: proceeds received, INCLUDING per-share consideration and share counts".
#:
#: `gross_consideration` or `net_payment` for proceeds, because a notice may
#: state either and the difference between them is a separate finding that
#: `packet/` already reports; the question here is only whether the document
#: says what was received at all.
_REALIZATION_FIGURES: tuple[tuple[str, frozenset[str]], ...] = (
    ("NO_PROCEEDS_STATED", frozenset({"gross_consideration", "net_payment"})),
    (
        "NO_PER_SHARE_CONSIDERATION_STATED",
        frozenset({"consideration_per_share", "consideration_per_share_stated"}),
    ),
    ("NO_REALIZED_SHARE_COUNT_STATED", frozenset({"shares_of_record"})),
)


def r4(ledger: Ledger, holding_id: str, on: date) -> Outcome:
    """Realisation support, for EVERY lot realised in this window.

    An earlier version took the first realisation event, so a holding with two
    realised lots could be judged from the wrong one, and an event outside the
    window suppressed a second event inside it.
    """
    events = _realized_in_window(ledger, holding_id, on)
    if not events:
        return Outcome(requirement=RequirementCode.R4, verdict=_NA)

    position = ledger.holdings[holding_id].position_type
    claims = applicable_claims(ledger, holding_id, RequirementCode.R4, on)
    per_lot: dict[str, RequirementVerdict] = {}
    reasons: list[str] = []
    actions: list[str] = []
    for lot in events:
        covering = [c for c in claims if c.priced_class in (None, lot.security_class)]
        outcome = (
            best(
                [
                    lookup(RequirementCode.R4, c.source_class, c.execution_status, position).verdict
                    for c in covering
                ]
            )
            if covering
            else _MISSING
        )

        # ¶4 NAMES THREE THINGS, and the document class was answering for all of
        # them. "Merger consideration statements, distribution notices, or other
        # support for PROCEEDS RECEIVED, including per-share consideration and
        # share counts" — proceeds is the head noun, the other two are named
        # after "including", so a notice that states none of them does not
        # answer the request even though it is exactly the class asked for.
        #
        # PER LOT, from the claims covering THAT lot, for the reason R1's
        # settlement limb is: a holding-wide union let figures from an off-class
        # claim — one excluded from this lot's own assessment — complete it, and
        # let one realisation's figures answer for another's.
        if outcome is _SUFFICIENT:
            stated = {name for c in covering for name in c.facts}
            absent = [missing for missing, needed in _REALIZATION_FIGURES if not (needed & stated)]
            if absent:
                # SOME evidenced is partial; NONE is insufficient. A notice of
                # exactly the right class stating not one of proceeds, per-share
                # consideration or share count supports no part of what ¶4 asks
                # for, and `partial` would report that it supports some of it.
                outcome = _INSUFFICIENT if len(absent) == len(_REALIZATION_FIGURES) else _PARTIAL
                reasons.extend(absent)
                actions.append("REQUEST_REALIZATION_FIGURES")
        per_lot[lot.id] = outcome

    if not all(v is _SUFFICIENT for v in per_lot.values()):
        reasons.insert(0, "NO_REALIZATION_SUPPORT_FOR_LOT")
        actions.insert(0, "REQUEST_REALIZATION_SUPPORT")

    return Outcome(
        requirement=RequirementCode.R4,
        verdict=worst(list(per_lot.values())),
        reasons=tuple(dict.fromkeys(reasons)),
        next_actions=tuple(dict.fromkeys(actions)),
        relied_on=tuple(c.id for c in claims),
        per_lot=per_lot,
        realized_lots=tuple(lot.id for lot in events),
    )


def r5(r2_outcome: Outcome) -> Outcome:
    """Pro forma identification — a **labelling** requirement, not a support one.

    It asks whether a mark carried on a pro forma basis says so. Derived from
    R2's relied-upon execution statuses rather than from a tracker label, so a
    position management forgot to label is still identified, and one management
    labelled without a pro forma document in the file is a reconciliation
    finding rather than a silent pass.
    """
    if not r2_outcome.pro_forma:
        return Outcome(requirement=RequirementCode.R5, verdict=_NA)
    return Outcome(
        requirement=RequirementCode.R5,
        verdict=_SUFFICIENT,
        note="label present and derived from relied-upon inputs",
    )


@dataclass(frozen=True)
class RowAssessment:
    """All five requirements for one holding at one date, and the row verdict."""

    holding_id: str
    measurement_date: date
    outcomes: dict[RequirementCode, Outcome]
    verdict: RequirementVerdict

    @property
    def applicable(self) -> list[Outcome]:
        return [o for o in self.outcomes.values() if o.verdict is not _NA]

    @property
    def fully_supported(self) -> bool:
        """Every applicable requirement is sufficient — §7.1.

        `sufficient / applicable`, never a count against a fixed denominator of
        five. A row where R3, R4 and R5 do not arise is not two-fifths supported.
        """
        applicable = self.applicable
        return bool(applicable) and all(o.verdict is _SUFFICIENT for o in applicable)


def assess_row(ledger: Ledger, holding_id: str, on: date) -> RowAssessment:
    """Every requirement for one holding at one measurement date."""
    one = r1(ledger, holding_id, on)
    two = r2(ledger, holding_id, on)
    outcomes = {
        RequirementCode.R1: one,
        RequirementCode.R2: two,
        RequirementCode.R3: r3(ledger, holding_id, on),
        RequirementCode.R4: r4(ledger, holding_id, on),
        RequirementCode.R5: r5(two),
    }
    return RowAssessment(
        holding_id=holding_id,
        measurement_date=on,
        outcomes=outcomes,
        verdict=reduce_row(o.verdict for o in outcomes.values()),
    )


__all__ = [
    "Outcome",
    "RowAssessment",
    "StaleComponent",
    "applicable_claims",
    "assess_row",
    "minus_months",
    "r1",
    "r2",
    "r3",
    "r4",
    "r5",
    "supersede",
]
