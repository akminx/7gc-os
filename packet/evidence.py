"""What the packet needs from the ledger that the `Packet` contract does not carry.

`api.ledger.packet` assembles the marks, the verdicts and the gaps. It does not
carry the documents themselves, the text a citation resolves into, or the review
decisions recorded against the period — and an auditor packet is those three
things standing beside the figures. Without the document there is nothing to put
in a per-company folder; without the canonical text a span is an offset into
something the auditor does not have; without the decisions the packet cannot
state that nothing has been approved.

Reads only. Nothing here judges anything: the verdicts were computed by
`policy/` and the gaps were recorded when the rows were written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg

from api.ledger import claims_for
from packages.contracts.models import Claim, Packet, SourceFact

Conn = psycopg.Connection[tuple[object, ...]]


def _as[T](kind: type[T], value: object) -> T:
    """Narrow one column. psycopg hands every value back as `object`.

    One function rather than a family of `_str`/`_int`/`_bytes` helpers: the
    suppression ceiling for this repo is zero, so the alternative to narrowing is
    not a cast, and five near-identical two-line functions is a clone waiting to
    drift from the five in `api/ledger.py` that already exist.
    """
    assert isinstance(value, kind), f"expected {kind.__name__}, got {type(value).__name__}"
    return value


@dataclass(frozen=True)
class SourceDocument:
    """One immutable document version, with the bytes and the text it produced.

    Both travel, because they answer different questions. The bytes are what the
    fund actually holds and what an auditor will want to open; the canonical text
    is the string every `span_start`/`span_end` pair indexes into, and exporting
    the first without the second leaves the offsets pointing at nothing.
    """

    document_version_id: str
    source_file_id: str
    filename: str
    content_hash: str
    byte_size: int
    extractor: str
    text_hash: str
    page_count: int
    payload: bytes
    canonical_text: str


@dataclass(frozen=True)
class DecisionRecord:
    """A row of `review_decision`, as recorded.

    INV-18 · four independent state machines. `decision_type` is carried rather
    than collapsed, because a transcription approval is not a valuation approval
    and a packet that treats them as one blesses a figure nobody blessed.
    """

    id: int
    decision_type: str
    status: str
    subject_kind: str
    subject_id: str
    mark_id: int | None
    packet_id: str | None
    policy_version: str | None
    actor_id: str
    decided_at: datetime
    notes: str | None
    holding_id: str | None
    mark_revision: int | None
    bound_assessments: int


@dataclass(frozen=True)
class HoldingEvidence:
    """Everything cited, and everything citable, for one position."""

    holding_id: str
    claims: tuple[Claim, ...]
    facts: dict[str, tuple[SourceFact, ...]]
    documents: tuple[SourceDocument, ...]


@dataclass(frozen=True)
class Evidence:
    """The packet's evidence, keyed by holding, plus the period's decisions."""

    by_holding: dict[str, HoldingEvidence]
    decisions: tuple[DecisionRecord, ...]

    def documents(self) -> tuple[SourceDocument, ...]:
        """Every document version in the packet, once, in a stable order."""
        seen: dict[str, SourceDocument] = {}
        for holding in self.by_holding.values():
            for document in holding.documents:
                seen.setdefault(document.document_version_id, document)
        return tuple(sorted(seen.values(), key=lambda d: d.document_version_id))


_DOCUMENTS_SQL = (
    "select dv.id, dv.source_file_id, sf.filename, sf.content_hash, sf.byte_size,"
    " dv.extractor, dv.text_hash, dv.page_count, sf.bytes, dv.canonical_text"
    " from document_version dv"
    " join source_file sf on sf.id = dv.source_file_id"
    " where dv.id = any(%s) order by dv.id"
)

#: Every decision touching this fund-period, whichever machine it belongs to.
#: Reached through the mark for the three that bind one, and through `packet_id`
#: for the packet decision, which binds no mark at all.
_DECISIONS_SQL = (
    "select d.id, d.decision_type, d.status, d.subject_kind, d.subject_id, d.mark_id,"
    " d.packet_id, d.policy_version, d.actor_id, d.decided_at, d.notes,"
    " m.holding_id, m.revision,"
    " (select count(*) from decision_evidence de where de.decision_id = d.id)"
    " from review_decision d"
    " left join mark m on m.id = d.mark_id"
    " where m.period_id = %s"
    "    or d.packet_id in (select pv.id from packet_version pv"
    "                        where pv.fund_id = %s and pv.period_id = %s)"
    " order by d.decided_at, d.id"
)


def _documents(conn: Conn, version_ids: list[str]) -> tuple[SourceDocument, ...]:
    if not version_ids:
        return ()
    rows = conn.execute(_DOCUMENTS_SQL, (version_ids,)).fetchall()
    return tuple(
        SourceDocument(
            document_version_id=_as(str, r[0]),
            source_file_id=_as(str, r[1]),
            filename=_as(str, r[2]),
            content_hash=_as(str, r[3]),
            byte_size=_as(int, r[4]),
            extractor=_as(str, r[5]),
            text_hash=_as(str, r[6]),
            page_count=_as(int, r[7]),
            # psycopg hands `bytea` back as `bytes`; a server-side cursor or a
            # different adapter hands back a memoryview of the same octets.
            payload=bytes(_as(memoryview, r[8]))
            if isinstance(r[8], memoryview)
            else _as(bytes, r[8]),
            canonical_text=_as(str, r[9]),
        )
        for r in rows
    )


def _decisions(conn: Conn, fund_id: str, period_id: str) -> tuple[DecisionRecord, ...]:
    rows = conn.execute(_DECISIONS_SQL, (period_id, fund_id, period_id)).fetchall()
    return tuple(
        DecisionRecord(
            id=_as(int, r[0]),
            decision_type=_as(str, r[1]),
            status=_as(str, r[2]),
            subject_kind=_as(str, r[3]),
            subject_id=_as(str, r[4]),
            mark_id=None if r[5] is None else _as(int, r[5]),
            packet_id=None if r[6] is None else _as(str, r[6]),
            policy_version=None if r[7] is None else _as(str, r[7]),
            actor_id=_as(str, r[8]),
            decided_at=_as(datetime, r[9]),
            notes=None if r[10] is None else _as(str, r[10]),
            holding_id=None if r[11] is None else _as(str, r[11]),
            mark_revision=None if r[12] is None else _as(int, r[12]),
            bound_assessments=_as(int, r[13]),
        )
        for r in rows
    )


def gather(conn: Conn, packet: Packet) -> Evidence:
    """Every claim, cited fact and document behind the rows of this packet.

    Claims come through `api.ledger.claims_for` rather than a second query of the
    same tables: one reader means one answer, and the citation rebuild it
    performs is the step that would be silently skipped by a copy.
    """
    by_holding: dict[str, HoldingEvidence] = {}
    for row in packet.rows:
        pairs = claims_for(conn, row.holding_id)
        claims = tuple(claim for claim, _ in pairs)
        facts = {claim.id: tuple(found) for claim, found in pairs}
        version_ids = sorted({claim.document_version_id for claim in claims})
        by_holding[row.holding_id] = HoldingEvidence(
            holding_id=row.holding_id,
            claims=claims,
            facts=facts,
            documents=_documents(conn, version_ids),
        )
    return Evidence(
        by_holding=by_holding,
        decisions=_decisions(conn, packet.fund_id, packet.period.id),
    )
