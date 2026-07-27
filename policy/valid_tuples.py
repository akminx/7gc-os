"""The sufficiency matrix — SPEC §7.3. Enumerated, and fail-closed.

The policy key is `(requirement, source_class, execution_status, position_type)`.
`document_type` is deliberately **not** in it: `term_sheet` and
`paying_agent_notice` are document types, not source classes, and r1 mixed the
two columns.

Three properties are structural rather than conventional, and each exists
because its absence already produced a wrong answer:

1. **No runtime default.** There is no wildcard row, no fallback rank and no
   `.get(key, something)`. An unenumerated tuple raises `InvalidPolicyInput`.
   This is not defensive coding — it is the mechanism by which the corpus is
   allowed to grow. Adding `fund_internal_record` to `SourceClass` in Step 2
   made the oracle refuse until the cell was added deliberately, which is how
   Moonfare's FY2024 memo came to be classified as management's own arithmetic
   rather than as a third-party valuation. A default would have filed it
   silently under whatever the neighbouring cell said.

2. **Every valid tuple has exactly one explicit verdict.** `MATRIX` is the
   single enumeration; `VALID_TUPLES` is derived from it rather than declared
   beside it, so the two cannot disagree. A second hand-maintained list of
   "which tuples are valid" is precisely the ~200-cell drift that failed two
   fixer cycles.

3. **Verdicts are a set, not a scale (INV-1, INV-2).** Nothing here compares
   two source classes. `press` is not "below" a cap table at some rank; it is a
   different kind of thing, and the cell says so for each requirement
   separately.

`PolicyResult` carries no `labels` field, though SPEC §7.3's signature names
one. Nothing populates it: `pro_forma` is derived from the execution status of
the relied-upon claims (INV-4) and `cross_class_policy` from held class versus
priced class (INV-17). Both are already derived once, elsewhere, from evidence
rather than from a table — and a second source for the same label is how two
answers get produced for one question. An always-empty field reads as coverage
and provides none.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from packages.contracts.enums import (
    ExecutionStatus,
    GapKind,
    PositionType,
    RequirementCode,
    RequirementVerdict,
    SourceClass,
)


class InvalidPolicyInput(Exception):
    """An unenumerated policy tuple. Fail closed, never default.

    Carries the tuple in its message because the remedy is always the same and
    always deliberate: decide what that combination of evidence means, and add
    the cell.
    """


@dataclass(frozen=True)
class PolicyResult:
    """What one piece of evidence does for one requirement.

    `reason_code` is `None` where sufficiency needs no explanation — an executed
    SPA supporting existence is not a finding. It is populated wherever the
    verdict is short of sufficient, because a verdict without a reason is a
    number an auditor cannot act on.
    """

    verdict: RequirementVerdict
    reason_code: str | None = None
    next_actions: tuple[str, ...] = field(default_factory=tuple)
    #: The audit letter's ¶2 qualifier, and the only conditional cell in the
    #: matrix. Branch A accepts "the round's executed documents **or** pro forma
    #: capitalization table **evidencing price per share**" — the disjunct is
    #: conditioned on that phrase, so the code conditions on it too.
    #:
    #: Set only where the letter attaches the qualifier. `None` everywhere else
    #: means the cell's verdict is unconditional, which is the fail-closed
    #: default: a cell says what it says unless a rule was deliberately written.
    #:
    #: A nested `PolicyResult` rather than a second table keyed by the same
    #: tuple. Two hand-maintained lists of one set is the ~200-cell drift that
    #: failed two fixer cycles; the alternative keeps the qualifier and its
    #: consequence in the cell they belong to.
    without_price_per_share: PolicyResult | None = None


PolicyKey = tuple[RequirementCode, SourceClass, ExecutionStatus, PositionType]

_R1 = RequirementCode.R1
_R2 = RequirementCode.R2
_R4 = RequirementCode.R4

_SUFFICIENT = RequirementVerdict.SUFFICIENT
_PARTIAL = RequirementVerdict.PARTIAL
_INSUFFICIENT = RequirementVerdict.INSUFFICIENT
_MISSING = RequirementVerdict.MISSING


#: Scoped to the tuples this corpus exercises, plus deliberate negatives (SPEC
#: §15's cut list). The trigger to widen it is stated there: a document arrives
#: whose tuple is not enumerated. Widening it to make a position pass is the
#: failure — an unenumerated tuple is a finding about that position's data.
MATRIX: dict[PolicyKey, PolicyResult] = {
    # ── R1 · existence and cost ──────────────────────────────────────────
    (
        _R1,
        SourceClass.EXECUTED_TRANSACTION_DOC,
        ExecutionStatus.EXECUTED,
        PositionType.DIRECT_EQUITY,
    ): PolicyResult(verdict=_SUFFICIENT),
    # Owner determination, recorded as one: an administrator's capital account
    # statement is accepted as the existence-and-cost equivalent for a feeder
    # interest, where no stock purchase agreement exists to ask for.
    (
        _R1,
        SourceClass.ADMINISTRATOR_STATEMENT,
        ExecutionStatus.NOT_APPLICABLE,
        PositionType.INDIRECT_FEEDER,
    ): PolicyResult(verdict=_SUFFICIENT),
    (
        _R1,
        SourceClass.COMPANY_COMMUNICATION,
        ExecutionStatus.NON_BINDING,
        PositionType.DIRECT_EQUITY,
    ): PolicyResult(
        verdict=_INSUFFICIENT,
        reason_code="NON_BINDING_TERM_SHEET",
        next_actions=("REQUEST_EXECUTED_DOC",),
    ),
    # A settlement confirmation: money received by the company from the fund, on
    # a date, with a reference. The audit letter's paragraph 1 names this
    # explicitly — the acquisition documents "including share counts, price per
    # share, and settlement of funds".
    #
    # `partial`, because it evidences one limb of three. It proves the fund paid
    # and says nothing about what the fund received: no share count, no price.
    # On its own an auditor could not establish the position from it.
    #
    # R1 reduces per lot with `best()`, so where a stock purchase agreement is
    # already `sufficient` this corroborates without downgrading, which is the
    # correct behaviour and was verified before the cell was added.
    (
        _R1,
        SourceClass.COMPANY_COMMUNICATION,
        ExecutionStatus.NOT_APPLICABLE,
        PositionType.DIRECT_EQUITY,
    ): PolicyResult(verdict=_PARTIAL, reason_code="SETTLEMENT_WITHOUT_SHARE_TERMS"),
    # ── R2 · fair value support ──────────────────────────────────────────
    (
        _R2,
        SourceClass.EXECUTED_TRANSACTION_DOC,
        ExecutionStatus.EXECUTED,
        PositionType.DIRECT_EQUITY,
    ): PolicyResult(verdict=_SUFFICIENT),
    # Owner ruling, 2026-07-26 · the letter's ¶2 says "or", so this is SUFFICIENT.
    #
    #   "For marks based on a financing round: the round's executed documents
    #    **or** pro forma capitalization table evidencing price per share."
    #
    # A pro forma capitalization table is a financing-round document by
    # construction — it states the post-money structure of a named round — so
    # branch A governs it and the disjunct is available. This cell read `partial`
    # for four rounds of review, which is stricter than the client asked.
    #
    # The cap was also counting one concern twice. The letter's closing asks
    # separately to "identify any positions marked on a pro forma basis pending
    # receipt of executed documentation" — that is R5, R5 already reports it, and
    # R5 is derived from execution status rather than from this verdict, so
    # raising the cell does not silence the disclosure. Support and disclosure
    # are two obligations in the letter and are two mechanisms here.
    #
    # `without_price_per_share` is the qualifier kept load-bearing: a pro forma
    # table that does not state price per share is not what ¶2 accepts. No
    # document in this corpus fails it — Dream, Sway and Fluidstack all state a
    # price — so the branch is exercised by `cases_policy.py` rather than by the
    # corpus, deliberately: an unreachable branch is the failure mode this
    # project exists to avoid.
    (
        _R2,
        SourceClass.COMPANY_CAP_TABLE,
        ExecutionStatus.PRO_FORMA,
        PositionType.DIRECT_EQUITY,
    ): PolicyResult(
        verdict=_SUFFICIENT,
        without_price_per_share=PolicyResult(
            verdict=_PARTIAL,
            reason_code="PRO_FORMA_WITHOUT_PRICE_PER_SHARE",
            next_actions=("REQUEST_EXECUTED_DOC",),
        ),
    ),
    # A cap table asserting a round CLOSED at a stated price, with the closing
    # set stated to be elsewhere. Fluidstack's Series A-2: "The Series A-2
    # tranche closed May 30, 2025 at $15.00 per share ($750,000,000
    # post-money); executed documents on file with company counsel."
    #
    # Added because binding that claim to R2 made this tuple reachable for the
    # first time and the matrix refused it — which is the fail-closed rule doing
    # its job. The evidence was in the corpus, cited, and relied on for nothing,
    # so the tuple had never been decided.
    #
    # `partial`, on the same reasoning as its two neighbours above and below: a
    # third party asserts the round closed, and the documents that would prove
    # it are not in the file. A cap table is not weaker than the CEO email that
    # says the same thing, and it is not stronger — the missing closing set is
    # the same absence in both.
    (
        _R2,
        SourceClass.COMPANY_CAP_TABLE,
        ExecutionStatus.UNEXECUTED_REFERENCED,
        PositionType.DIRECT_EQUITY,
    ): PolicyResult(verdict=_PARTIAL, reason_code="CLOSING_SET_PENDING"),
    (
        _R2,
        SourceClass.COMPANY_COMMUNICATION,
        ExecutionStatus.UNEXECUTED_REFERENCED,
        PositionType.DIRECT_EQUITY,
    ): PolicyResult(verdict=_PARTIAL, reason_code="CLOSING_SET_PENDING"),
    (
        _R2,
        SourceClass.COMPANY_COMMUNICATION,
        ExecutionStatus.NON_BINDING,
        PositionType.DIRECT_EQUITY,
    ): PolicyResult(verdict=_INSUFFICIENT, reason_code="NON_BINDING_TERM_SHEET"),
    # NOT changed by the 2026-07-26 ruling, and that is a decision rather than an
    # omission. A strict reading of ¶2 puts an exchange closing price and an
    # administrator's capital account statement on the "other information" side
    # too, which would carry branch B's conjunction to Banzai and Jio and take
    # six more rows off `sufficient`. The owner's ruling names the third-party
    # valuation memorandum and only that, and the reading that fits both the
    # ruling and the letter is that these two are determinations of value made by
    # an independent party in its own right — an exchange, an administrator —
    # rather than information management selected and applied, which is what ¶2's
    # second branch asks management to describe the basis of.
    #
    # It is inference, and it is recorded as inference. Widening branch B to
    # these classes is the owner's call, not this file's.
    (
        _R2,
        SourceClass.PUBLIC_MARKET_QUOTE,
        ExecutionStatus.NOT_APPLICABLE,
        PositionType.PUBLIC_LISTED,
    ): PolicyResult(verdict=_SUFFICIENT),
    (
        _R2,
        SourceClass.ADMINISTRATOR_STATEMENT,
        ExecutionStatus.NOT_APPLICABLE,
        PositionType.INDIRECT_FEEDER,
    ): PolicyResult(verdict=_SUFFICIENT),
    # Owner ruling, 2026-07-26 · branch B is an AND, and only half of it exists.
    #
    #   "For marks based on **other information**: the underlying source **and**
    #    management's memo describing the basis of the mark."
    #
    # A third-party valuation memorandum is a mark based on other information,
    # not on a financing round, so branch B governs and the conjunction applies.
    # The memo is the underlying source. No management memo describing the basis
    # of the mark exists anywhere in this corpus — not for Moonfare, not for
    # anyone — so the row read `sufficient` on one half of an "and".
    #
    # This is the correction that mattered most of the four, because it is the
    # only one where the packet claimed MORE support than the letter allows. The
    # others risk under-reporting; this one over-reported.
    #
    # `partial`, not `insufficient`: the memo is a real and authoritative leg of
    # the conjunction, which is exactly what `partial` means everywhere else here
    # (the R1 settlement cell evidences one limb of three). It is NOT the
    # `fund_internal_record` case below, where neither leg stands on its own.
    #
    # `REQUEST_MANAGEMENT_BASIS_MEMO`, deliberately not `DRAFT_MANAGEMENT_
    # ASSESSMENT`. R3's assessment is ¶3(b) — that a last round price *remains
    # representative* at a later date. This is ¶2 — what the mark is *based on*.
    # Different paragraphs, different documents, different questions. Collapsing
    # them because both are "a memo from management" is the kind of distinction
    # INVARIANTS.md exists to keep apart.
    #
    # NOTE · scope. `best()` is a disjunction and cannot express an "and", so a
    # genuine management memo arriving alongside this one would still reduce to
    # `partial` (§7.4 rule 3 — two partials never compose). That is correct
    # today, since no such document exists; if one is ever added, branch B needs
    # a composition rule, and it needs to be decided rather than discovered.
    #
    # The reliance window still applies first and independently: INV-16 is
    # enforced in `applicable_claims()` before this table is consulted, so
    # Capsule's memo — which forbids later reliance in a sentence that is itself
    # a cited fact — is out of scope after its own date whatever this cell says.
    (
        _R2,
        SourceClass.THIRD_PARTY_VALUATION_MEMO,
        ExecutionStatus.NOT_APPLICABLE,
        PositionType.FX_DENOMINATED_INTEREST,
    ): PolicyResult(
        verdict=_PARTIAL,
        reason_code="NO_MANAGEMENT_BASIS_MEMO",
        next_actions=("REQUEST_MANAGEMENT_BASIS_MEMO",),
    ),
    (
        _R2,
        SourceClass.THIRD_PARTY_VALUATION_MEMO,
        ExecutionStatus.NOT_APPLICABLE,
        PositionType.DIRECT_EQUITY,
    ): PolicyResult(
        verdict=_PARTIAL,
        reason_code="NO_MANAGEMENT_BASIS_MEMO",
        next_actions=("REQUEST_MANAGEMENT_BASIS_MEMO",),
    ),
    (
        _R2,
        SourceClass.PRESS,
        ExecutionStatus.NOT_APPLICABLE,
        PositionType.DIRECT_EQUITY,
    ): PolicyResult(
        verdict=_INSUFFICIENT,
        reason_code="PRESS_CANNOT_SUPPORT_FAIR_VALUE",
        next_actions=("REQUEST_PRIMARY_EVIDENCE",),
    ),
    # Management's own paperwork about management's own position. The letter
    # asks for "the underlying source AND management's memo describing the basis
    # of the mark"; this is the second half without the first. Moonfare FY2024
    # is the case — the memo translates a EUR figure carried from the FY2023
    # third-party memo, whose own text forbids reliance at a later date without
    # an update nobody commissioned, at a rate the memo asserts and does not
    # source.
    #
    # `insufficient`, not `missing`: a document exists and says something.
    # `insufficient`, not `partial`: neither leg stands on its own, and two
    # partials never compose to sufficient (§7.4), so calling it partial would
    # invite exactly that composition.
    (
        _R2,
        SourceClass.FUND_INTERNAL_RECORD,
        ExecutionStatus.NOT_APPLICABLE,
        PositionType.FX_DENOMINATED_INTEREST,
    ): PolicyResult(
        verdict=_INSUFFICIENT,
        reason_code="MANAGEMENT_ASSERTION_WITHOUT_PRIMARY_SOURCE",
        next_actions=("REQUEST_PRIMARY_EVIDENCE",),
    ),
    # ── R4 · realisation support ─────────────────────────────────────────
    (
        _R4,
        SourceClass.EXECUTED_TRANSACTION_DOC,
        ExecutionStatus.EXECUTED,
        PositionType.DIRECT_EQUITY,
    ): PolicyResult(verdict=_SUFFICIENT),
}


#: Derived, never declared beside the matrix. Two hand-maintained lists of the
#: same set is the drift that failed two fixer cycles.
VALID_TUPLES: frozenset[PolicyKey] = frozenset(MATRIX)


#: What a requirement is worth when no applicable evidence exists at all, keyed
#: by WHY the document is absent (INV-12). "With counsel" and "nobody can find
#: it" call for different auditor action, so they cannot reduce to one verdict.
#: `None` is the key for "no gap has been observed either" — no evidence and no
#: explanation, which is the weakest state and not the same as an explained one.
#:
#: No `reason_code` here on purpose. The reason a requirement is short is
#: requirement-specific prose — R2 reports *what* support is absent, R1 reports
#: only the action, because for R1 the absent document is already named by the
#: gap observation itself. Putting one string in this table would have both
#: requirements report the other's finding.
GAP_VERDICTS: dict[GapKind | None, PolicyResult] = {
    GapKind.WITH_COUNSEL: PolicyResult(verdict=_PARTIAL, next_actions=("REQUEST_FROM_COUNSEL",)),
    GapKind.REFERENCED_LOCATION_UNSPECIFIED: PolicyResult(
        verdict=_INSUFFICIENT, next_actions=("REQUEST_WITH_LOCATION",)
    ),
    GapKind.NOT_LOCATED: PolicyResult(verdict=_MISSING, next_actions=("REQUEST_FROM_COMPANY",)),
    None: PolicyResult(verdict=_MISSING, next_actions=("REQUEST_FROM_COMPANY",)),
}


def lookup(
    requirement: RequirementCode,
    source_class: SourceClass,
    execution_status: ExecutionStatus,
    position_type: PositionType,
) -> PolicyResult:
    """What this evidence does for this requirement, or refuse to guess.

    Raises `InvalidPolicyInput` for any tuple not enumerated above. Callers must
    not catch it to substitute a default — the whole value of the enumeration is
    that a combination nobody has ruled on stops the run instead of producing a
    verdict nobody decided.
    """
    key = (requirement, source_class, execution_status, position_type)
    result = MATRIX.get(key)
    if result is None:
        raise InvalidPolicyInput(
            f"unenumerated policy tuple: ({requirement.value}, {source_class.value}, "
            f"{execution_status.value}, {position_type.value}). Fail closed — decide "
            f"what this evidence means for {requirement.value} and add the cell to "
            f"policy/valid_tuples.py deliberately."
        )
    return result


def gap_result(kind: GapKind | None) -> PolicyResult:
    """The verdict a requirement carries when only an explained absence exists."""
    return GAP_VERDICTS[kind]


#: Why a requirement is short when the only thing there is a recorded absence.
#: Requirement-specific on purpose: R1 reports which document is missing and how,
#: R2 reports that no support is in scope AND how. `RequirementAssessment`
#: refuses a verdict short of sufficient with no reason at all — a `partial` an
#: auditor cannot act on is worse than a gap, because it looks answered.
_GAP_REASON: dict[GapKind | None, str] = {
    GapKind.WITH_COUNSEL: "DOCUMENT_WITH_COUNSEL",
    GapKind.REFERENCED_LOCATION_UNSPECIFIED: "DOCUMENT_LOCATION_UNSPECIFIED",
    GapKind.NOT_LOCATED: "DOCUMENT_NOT_LOCATED",
    None: "NO_DOCUMENT_AND_NO_GAP_RECORDED",
}


def gap_reason(kind: GapKind | None, *, prefix: str = "") -> str:
    """The reason code for an absence of this kind."""
    if prefix:
        return f"{prefix}_{(kind.value if kind else 'none').upper()}"
    return _GAP_REASON[kind]
