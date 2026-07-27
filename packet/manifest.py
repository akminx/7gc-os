"""The manifest: what was written, in what order, and hashed.

SPEC §12 · reproducibility here is **logical**, not byte-identical — two runs a
minute apart differ in `generated_at` and that is not drift. So the manifest
records the inputs a reader would need to decide whether two packets say the same
thing: the schema and policy versions, every mark revision, every document
version with the hash of its bytes and of its text, the generator and its commit,
and the hash of every file this run produced.

The entry list is content-addressed and ordered. `manifest_hash` is taken over
the canonical form of that list, so a packet whose contents were touched after
generation no longer matches the number it carries.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from packages.contracts.models import Packet, PacketTotals
from packet.evidence import Evidence
from packet.tables import Table, money_text

#: Bumped when the shape of the exported packet changes, independently of the
#: ledger's own `schema_version`. A reader that understands one may not
#: understand the other.
PACKET_FORMAT_VERSION = "1.0.0"

GENERATOR_REF = "packet.export"


@dataclass(frozen=True)
class Provenance:
    packet_id: str
    generated_at: datetime
    generator_ref: str
    generator_commit: str | None


@dataclass(frozen=True)
class Entry:
    ordinal: int
    path: str
    content_hash: str
    byte_size: int


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_commit(root: Path) -> str | None:
    """The commit this generator ran from, read rather than shelled out for.

    A subprocess would need a shell allowance in the security gate to answer a
    question two files already contain. Returns None when the ref cannot be
    resolved, and the manifest then records the absence rather than a guess —
    what it must never do is state a commit it did not verify.
    """
    head = root / ".git" / "HEAD"
    if not head.is_file():
        return None
    text = head.read_text(encoding="utf-8", errors="replace").strip()
    if not text.startswith("ref: "):
        return text or None
    ref = text[len("ref: ") :].strip()
    direct = root / ".git" / ref
    if direct.is_file():
        return direct.read_text(encoding="utf-8", errors="replace").strip() or None
    packed = root / ".git" / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(("#", "^")):
                continue
            parts = line.split(maxsplit=1)
            if len(parts) == 2 and parts[1].strip() == ref:
                return parts[0]
    return None


def entries_for(root: Path, paths: list[str]) -> tuple[Entry, ...]:
    """Hash what was actually written, in a deterministic order.

    The hash comes from re-reading the file rather than from the buffer that
    produced it: a manifest that hashes its own intention certifies nothing about
    the bytes on disk.
    """
    out: list[Entry] = []
    for ordinal, path in enumerate(sorted(paths), start=1):
        payload = (root / path).read_bytes()
        out.append(
            Entry(
                ordinal=ordinal,
                path=path,
                content_hash=sha256_bytes(payload),
                byte_size=len(payload),
            )
        )
    return tuple(out)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _totals_json(totals: PacketTotals) -> dict[str, Any]:
    return {
        "kind": totals.kind.value,
        "label": totals.label,
        "amount": str(totals.amount.amount),
        "currency": totals.amount.currency,
        "unsupported_amount": str(totals.unsupported_amount.amount),
        "unsupported_positions": totals.unsupported_positions,
        "packet_gap_positions": totals.packet_gap_positions,
        "contains_unsupported_inputs": totals.contains_unsupported_inputs,
        "stated_as": money_text(totals.amount),
    }


def _table_digest(table: Table) -> str:
    """A hash over a table's content, so a verdict cannot change unremarked.

    Assessments and approvals have no revision number of their own — they are
    computed on read from the ledger's current state. Their digest is therefore
    what a later reader compares, and it is the only thing that can tell them the
    evidence moved under a packet that still names the same policy version.
    """
    body = [list(table.headers), *[[_cell(c) for c in row] for row in table.rows]]
    return sha256_bytes(_canonical(body).encode("utf-8"))


def _cell(value: object) -> str | int | None:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, str | int) or value is None:
        return value
    return str(value)


def build(
    *,
    packet: Packet,
    evidence: Evidence,
    tables: list[Table],
    provenance: Provenance,
    entries: tuple[Entry, ...],
    held_totals: PacketTotals,
    approved_totals: PacketTotals,
) -> dict[str, Any]:
    """The manifest document, ready to serialise."""
    marks = sorted(
        (
            {
                "holding_id": r.holding_id,
                "mark_id": r.mark.id,
                "revision": r.mark.revision,
                "reported_amount": str(r.mark.reported.amount),
                "currency": r.mark.reported.currency,
            }
            for r in packet.rows
            if r.mark is not None
        ),
        key=lambda m: str(m["holding_id"]),
    )
    documents = [
        {
            "document_version_id": d.document_version_id,
            "source_file_id": d.source_file_id,
            "filename": d.filename,
            "content_hash": d.content_hash,
            "byte_size": d.byte_size,
            "text_hash": d.text_hash,
            "extractor": d.extractor,
            "page_count": d.page_count,
        }
        for d in evidence.documents()
    ]
    manifest: dict[str, Any] = {
        "packet_id": provenance.packet_id,
        "packet_format_version": PACKET_FORMAT_VERSION,
        "fund_id": packet.fund_id,
        "period_id": packet.period.id,
        "period_label": packet.period.label,
        "measurement_date": packet.period.period_date.isoformat(),
        "audit_scope": packet.period.audit_scope.value,
        "ledger_schema_version": packet.schema_version,
        "policy_version": packet.policy_version,
        "generated_at": provenance.generated_at.isoformat(),
        "generator_ref": provenance.generator_ref,
        "generator_commit": provenance.generator_commit,
        # SPEC §12 asks for prompt and model versions. There are none: every
        # figure in this corpus was extracted by the deterministic pattern
        # extractors in `ingest/documents/`, and recording an empty field is how
        # a reader learns that rather than assuming a model was involved.
        "extraction": {
            "model": None,
            "prompt_version": None,
            "extractors": sorted({d.extractor for d in evidence.documents()}),
        },
        "mark_revisions": marks,
        "document_versions": documents,
        "assessment_digest": next(
            (_table_digest(t) for t in tables if t.key == "requirements"), None
        ),
        "approval_digest": next(
            (_table_digest(t) for t in tables if t.key == "approval_log"), None
        ),
        "approvals_recorded": sum(
            1
            for d in evidence.decisions
            if d.decision_type == "valuation" and d.status == "approved"
        ),
        "packet_approved": any(
            d.decision_type == "packet" and d.status == "approved" for d in evidence.decisions
        ),
        "totals": [_totals_json(held_totals), _totals_json(approved_totals)],
        "table_row_counts": {t.key: len(t.rows) for t in tables},
        "entries": [
            {
                "ordinal": e.ordinal,
                "path": e.path,
                "content_hash": e.content_hash,
                "byte_size": e.byte_size,
            }
            for e in entries
        ],
    }
    manifest["manifest_hash"] = sha256_bytes(_canonical(manifest["entries"]).encode("utf-8"))
    return manifest


def serialise(manifest: dict[str, Any]) -> bytes:
    body = json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True)
    return (body + "\n").encode("utf-8")
