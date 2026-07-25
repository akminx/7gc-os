"""Typed vocabularies, mirroring the Postgres enums exactly.

INV-2 · a verdict is a member of a set, not a number.
These are `str` enums rather than ints so that no ordering is implied and no
comparison with `>` is possible. `partial` is not "more than" `insufficient`;
they are different findings about different evidence.

Mirroring is verified, not assumed: `tests/test_contracts.py` reads the enum
labels back out of the live database and asserts membership matches in both
directions. A contract that has drifted from its schema is worse than no
contract, because it reads as agreement.
"""

from __future__ import annotations

from enum import StrEnum


class AuditScope(StrEnum):
    """INV-20 · an audit measurement date is not a lineage-only tracker period."""

    PACKET = "packet"
    LINEAGE_ONLY = "lineage_only"


class PositionType(StrEnum):
    DIRECT_EQUITY = "direct_equity"
    INDIRECT_FEEDER = "indirect_feeder"
    PUBLIC_LISTED = "public_listed"
    FX_DENOMINATED_INTEREST = "fx_denominated_interest"


class SourceClass(StrEnum):
    """INV-1 · authority is a lattice, not a score.

    Ordering these would invite `max()`. Press can trigger research and can never
    support a fair-value mark — not at any rank, which is a statement about kind
    rather than degree. The policy matrix decides sufficiency; this enum only
    names the kinds.
    """

    EXECUTED_TRANSACTION_DOC = "executed_transaction_doc"
    COMPANY_CAP_TABLE = "company_cap_table"
    COMPANY_COMMUNICATION = "company_communication"
    ADMINISTRATOR_STATEMENT = "administrator_statement"
    PUBLIC_MARKET_QUOTE = "public_market_quote"
    THIRD_PARTY_VALUATION_MEMO = "third_party_valuation_memo"
    PRESS = "press"
    RUMOR = "rumor"


class ExecutionStatus(StrEnum):
    """INV-4 · a signed document and a proposed one are different evidence."""

    EXECUTED = "executed"
    PRO_FORMA = "pro_forma"
    NON_BINDING = "non_binding"
    UNEXECUTED_REFERENCED = "unexecuted_referenced"
    NOT_APPLICABLE = "not_applicable"


class RequirementCode(StrEnum):
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"


class RequirementVerdict(StrEnum):
    """INV-2 · seven distinct findings, deliberately unordered.

    `missing` and `not_applicable` both mean "no evidence here" and mean opposite
    things to an auditor. Collapsing them to a boolean is the cheapest way to
    make a packet look complete.
    """

    NOT_ASSESSED = "not_assessed"
    NOT_APPLICABLE = "not_applicable"
    MISSING = "missing"
    INSUFFICIENT = "insufficient"
    PARTIAL = "partial"
    CONFLICTING = "conflicting"
    SUFFICIENT = "sufficient"


class DerivationStatus(StrEnum):
    """INV-13 · derivable is about arithmetic; supported is about evidence."""

    DERIVABLE = "derivable"
    NOT_DERIVABLE = "not_derivable"


class ValuationBasis(StrEnum):
    COST = "cost"
    LAST_ROUND = "last_round"
    THIRD_PARTY_MEMO = "third_party_memo"
    QUOTED_PRICE = "quoted_price"
    ADMINISTRATOR_NAV = "administrator_nav"
    REALIZATION = "realization"


class GapKind(StrEnum):
    """INV-12 · why a document is absent changes what the auditor must do."""

    WITH_COUNSEL = "with_counsel"
    REFERENCED_LOCATION_UNSPECIFIED = "referenced_location_unspecified"
    NOT_LOCATED = "not_located"


class GapRemediation(StrEnum):
    OPEN = "open"
    REQUESTED = "requested"
    RECEIVED = "received"
    UNOBTAINABLE = "unobtainable"


class DecisionType(StrEnum):
    """INV-18 · four independent state machines; none implies another.

    Approving a faithful transcription is not approving a fair value. Without
    this split the packet must either hide an unsupported figure or bless it.
    """

    TRANSCRIPTION = "transcription"
    VALUATION = "valuation"
    MANAGEMENT_ASSESSMENT = "management_assessment"
    PACKET = "packet"


class DecisionStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class FactState(StrEnum):
    """INV-14 · candidate extraction ≠ canonical fact ≠ approved assertion."""

    CANDIDATE = "candidate"
    CANONICAL = "canonical"
    APPROVED = "approved"


#: Every enum here, keyed by its Postgres type name. The parity test iterates
#: this, so adding a Python enum without its schema counterpart fails.
PG_ENUMS: dict[str, type[StrEnum]] = {
    "audit_scope": AuditScope,
    "position_type": PositionType,
    "source_class": SourceClass,
    "execution_status": ExecutionStatus,
    "requirement_code": RequirementCode,
    "requirement_verdict": RequirementVerdict,
    "derivation_status": DerivationStatus,
    "valuation_basis": ValuationBasis,
    "gap_kind": GapKind,
    "gap_remediation": GapRemediation,
    "decision_type": DecisionType,
    "decision_status": DecisionStatus,
    "fact_state": FactState,
}
