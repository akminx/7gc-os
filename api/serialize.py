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

from packages.contracts.models import HoldingRow, Packet, PacketTotals


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


def packet_json(packet: Packet) -> dict[str, Any]:
    return {
        **packet.model_dump(mode="json"),
        "rows": [row_json(r) for r in packet.rows],
        "totals": totals_json(packet.totals()),
    }
