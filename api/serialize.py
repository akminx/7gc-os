"""What the browser receives, including the fields the models compute.

`HoldingRow.supported`, `unsupported_reasons`, `approved`,
`RequirementAssessment.applicable` and `PacketTotals.contains_unsupported_inputs`
are Python `@property`, and Pydantic does not serialise properties. So the wire
carried the assessments and not the conclusion drawn from them — and the
dashboard's support column, the one column an audit-support tool exists to show,
rendered "not supplied by API".

The browser must not recompute them. SPEC §5.3 assigns every support status and
reason code to the API, and the derivation is subtle in exactly the way that
invites a wrong reimplementation: an always-applicable requirement marked
`not_applicable` still counts as unsupported, which two earlier Python versions
got wrong. So the API sends the conclusion.

Done here rather than with Pydantic's `computed_field`, which needs a
type-suppression comment on every property — mypy does not support decorators
above `@property` — and the suppression ceiling for this repo is zero. This also
leaves the frozen contract untouched.

(That sentence originally spelled the suppression out, and the gate counted its
own explanation as a suppression. The check reads prose and code alike, which is
the right trade: a comment that mentions the pattern is cheap to reword, and a
scanner that tried to tell code from prose would be the thing to distrust.)
"""

from __future__ import annotations

from typing import Any

from ingest.documents.field_requirements import answer_rank, requirements_for
from packages.contracts.models import HoldingRow, Packet, PacketTotals, SourceFact
from packet.recompute import Recomputation

#: What `fact_json` adds to a `SourceFact` dump: which requests the figure
#: answers, and how directly it answers each of them.
FACT_REQUIREMENT_KEY = "answers_requirements"
FACT_RANK_KEY = "answer_rank"


def fact_json(fact: SourceFact) -> dict[str, Any]:
    """One extracted figure, with the requests it answers attached.

    The ledger binds a CLAIM to a requirement, never a FIGURE, so a stock
    purchase agreement relied upon for both existence and fair value rendered
    all twelve of its cited figures under both — the same window whichever
    request an auditor clicked. `field_requirements.py` is the reviewed
    judgement that separates them.

    Sent from here rather than derived in the browser because relevance is a
    judgement about evidence and `scripts/check-web-arch.mjs` is right to refuse
    a component that decides `fund_shares` is about existence. The browser
    groups by what this field says; it does not decide what it should say.

    A figure that answers nothing arrives as an empty list, which is a
    declaration and not a lookup failure — `requirements_for` raises on a field
    nobody has ruled on rather than returning one.

    `answer_rank` is the second half of the same judgement, and it is here for
    the same reason: WHICH of ten relevant figures an auditor should be shown
    first is a statement about evidence. The browser orders by it — display
    ordering is the permitted half of §5.3 — and never decides it. Only the
    requests a figure answers appear, so a rank cannot be read for a request the
    figure has nothing to do with.
    """
    answers = requirements_for(fact.field_name)
    return {
        **fact.model_dump(mode="json"),
        FACT_REQUIREMENT_KEY: sorted(c.value for c in answers),
        FACT_RANK_KEY: {c.value: answer_rank(fact.field_name, c) for c in sorted(answers)},
    }


#: The one key `packet_json` adds for SPEC §8's V2. Named here and read by the
#: contract tests, so the browser's shape is checked against the serialiser
#: rather than against a literal somebody typed twice.
PACKET_RECOMPUTATION_KEY = "recomputations"


def recomputation_json(recomputed: Recomputation) -> dict[str, Any]:
    """SPEC §8's V2 for one holding, as a finding rather than as a value.

    `outcome` is SPEC §8's own six-value vocabulary and not a boolean, and
    `reason` names the DERIVATION rather than the verdict — `PER_CLASS_SHARES_X_PPS`
    reads the same whether the figures matched or not, so pass/fail cannot be
    read out of it by accident.

    `difference` arrives computed. The browser may not subtract two canonical
    figures (SPEC §5.3), and it is `null` rather than zero whenever either side
    is absent, because the distance between a figure that exists and one that
    does not is not nothing.
    """
    return {
        "holding_id": recomputed.holding_id,
        "outcome": recomputed.outcome.value,
        "reason": recomputed.reason,
        "derived": None
        if recomputed.derived is None
        else recomputed.derived.model_dump(mode="json"),
        "reported": None
        if recomputed.reported is None
        else recomputed.reported.model_dump(mode="json"),
        "difference": None
        if recomputed.difference is None
        else recomputed.difference.model_dump(mode="json"),
        "evidence_claim_ids": list(recomputed.evidence_claim_ids),
        "per_class": [
            {
                "lot_id": part.lot_id,
                "security_class": part.security_class,
                "shares": part.shares,
                "price_per_share": str(part.price_per_share),
                "amount": part.amount.model_dump(mode="json"),
                "cross_class": part.cross_class,
            }
            for part in recomputed.per_class
        ],
        "policy_version": recomputed.policy_version,
    }


def totals_json(totals: PacketTotals) -> dict[str, Any]:
    return {
        **totals.model_dump(mode="json"),
        "contains_unsupported_inputs": totals.contains_unsupported_inputs,
        #: INV-19 · `packet_gap_positions` is a SUPERSET of
        #: `unsupported_positions` — it counts unheld rows too. The difference is
        #: the unheld gaps; adding the two double counts. Sent as its own field
        #: so the browser never has to subtract, which §5.3 forbids.
        "unheld_gap_positions": totals.packet_gap_positions - totals.unsupported_positions,
    }


def row_json(row: HoldingRow) -> dict[str, Any]:
    data = row.model_dump(mode="json")
    for sent, source in zip(data["assessments"], row.assessments, strict=True):
        sent["applicable"] = source.applicable
    return {
        **data,
        "supported": row.supported,
        # Keys are `RequirementCode`; JSON object keys must be strings, and the
        # enum's own value is the auditor-facing label (R1..R5).
        "unsupported_reasons": {
            code.value: reason for code, reason in row.unsupported_reasons.items()
        },
        "approved": row.approved,
    }


def packet_json(
    packet: Packet, recomputed: dict[str, Recomputation] | None = None
) -> dict[str, Any]:
    """The packet, and beside it what the same evidence independently derives.

    Beside, not inside. A recomputation is not a property of the packet row —
    it is a second opinion about the row, produced by a different layer over the
    same ledger, and folding it into `HoldingRow` would put a derived figure
    where the reported ones live. That is the collapse the label exists to
    prevent: "validated: 2,500,000" is a claim this system has not earned, while
    "derived 2,500,000 against a reported 6,000,000" is a finding.

    Keyed by holding rather than positional, so a caller cannot pair the
    recomputation of one row with the mark of another by mis-indexing.

    `null` where no derivation ran at all — the fixture branch, which has no
    ledger to derive from. On the ledger path every row has an entry, INCLUDING
    the rows the check could not run for: `unconfirmable · Because Market has no
    document of any kind` is an answer to "what did you check", and omitting it
    would report the system's successes as its coverage.
    """
    return {
        **packet.model_dump(mode="json"),
        "rows": [row_json(r) for r in packet.rows],
        "totals": totals_json(packet.totals()),
        PACKET_RECOMPUTATION_KEY: None
        if recomputed is None
        else {holding_id: recomputation_json(r) for holding_id, r in recomputed.items()},
    }
