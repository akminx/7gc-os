"""Generate the packet into an isolated version, validate it, then publish it.

SPEC §12 · a failed generation exposes no partial packet. So everything is
written into a staging directory beside the destination, every manifest entry is
re-read and re-hashed from disk, every citation in the index is resolved against
the canonical text that was actually exported, and only then is the staging
directory moved into place. A raise anywhere before that leaves the destination
as it was and removes the staging directory.

The validations are the point of the step, not a formality. Each one can fail:

* a citation whose span does not resolve in the exported text,
* an entry whose file is missing or whose hash does not match what was written,
* a manifest whose ordinals are not the permutation 1..n the schema requires,
* an approved position that is not supported — refused by `PacketTotals` itself,
  which is the one figure this whole system exists to be unable to print.
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from packages.contracts.citations import resolves_in
from packages.contracts.models import Packet
from packet import cover as cover_module
from packet import manifest as manifest_module
from packet import tables as tables_module
from packet import workbook as workbook_module
from packet.evidence import Evidence, gather
from packet.layout import Layout, plan

Conn = psycopg.Connection[tuple[object, ...]]

MANIFEST_NAME = "MANIFEST.json"
README_NAME = "README.md"
WORKBOOK_NAME = "Valuation_Support.xlsx"
EMPTY_FOLDER_NOTE = "NO_SOURCE_DOCUMENTS.txt"


class PacketExportError(RuntimeError):
    """Generation failed. Nothing was published."""


@dataclass(frozen=True)
class Written:
    """What a successful export produced.

    Carries the fund-period identity rather than a reference to the `Packet` it
    came from: `record()` needs four scalars, and handing it the whole packet
    would let it read a figure the manifest was not built from.
    """

    packet_id: str
    root: Path
    manifest: dict[str, Any]
    fund_id: str
    period_id: str
    schema_version: str
    policy_version: str
    tables: list[tables_module.Table] = field(default_factory=list)

    @property
    def paths(self) -> list[str]:
        return [str(e["path"]) for e in self.manifest["entries"]]

    @property
    def manifest_hash(self) -> str:
        return str(self.manifest["manifest_hash"])


def packet_id_for(packet: Packet, at: datetime) -> str:
    return f"pkx_{packet.period.id}_{at.strftime('%Y%m%dT%H%M%SZ')}"


def _companies(root: Path, packet: Packet, evidence: Evidence, layout: Layout) -> list[str]:
    """The per-company folders the audit letter asks for.

    A position with no document still gets a folder holding a note that says so.
    An absent folder reads as an oversight; a folder stating "no source document
    is held for this position" is a finding, and it is the same finding the gap
    report carries.
    """
    written: list[str] = []
    for row in packet.rows:
        directory = layout.company_dir[row.holding_id]
        (root / directory).mkdir(parents=True, exist_ok=True)
        holding = evidence.by_holding.get(row.holding_id)
        documents = holding.documents if holding is not None else ()
        for document in documents:
            source = layout.source_path[document.document_version_id]
            text = layout.text_path[document.document_version_id]
            (root / source).write_bytes(document.payload)
            (root / text).write_text(document.canonical_text, encoding="utf-8")
            written.extend((source, text))
        if not documents:
            note = f"{directory}/{EMPTY_FOLDER_NOTE}"
            (root / note).write_text(
                f"No source document is held for {row.company_name} "
                f"({row.holding_id}) as at {packet.period.period_date.isoformat()}.\n"
                f"This is reported as a gap, not an omission — see gap_report.csv.\n",
                encoding="utf-8",
            )
            written.append(note)
    return written


def _verify_citations(packet: Packet, evidence: Evidence, root: Path, layout: Layout) -> None:
    """Every cited span must resolve in the text this run actually wrote.

    The database proved this when the fact was inserted (`0008_citations_resolve`).
    It is proved again here against the exported bytes, because what an auditor
    reads is the file on disk and not the row — and an encoding or a truncation on
    the way out would break the trace with every upstream check still green.
    """
    for row in packet.rows:
        holding = evidence.by_holding.get(row.holding_id)
        if holding is None:
            continue
        for claim in holding.claims:
            path = layout.text_path.get(claim.document_version_id)
            if path is None:
                raise PacketExportError(
                    f"{claim.id} cites {claim.document_version_id}, which was not exported"
                )
            body = (root / path).read_text(encoding="utf-8")
            for fact in holding.facts.get(claim.id, ()):
                if not resolves_in(fact.citation, body):
                    raise PacketExportError(
                        f"citation for {row.holding_id} fact #{fact.id} does not resolve in "
                        f"the exported text {path}: span "
                        f"[{fact.citation.span_start}, {fact.citation.span_end}) does not hold "
                        f"{fact.citation.quote!r}"
                    )


def _verify_entries(root: Path, entries: Iterable[manifest_module.Entry]) -> None:
    ordinals = []
    for entry in entries:
        target = root / entry.path
        if not target.is_file():
            raise PacketExportError(f"manifest names {entry.path}, which was not written")
        actual = manifest_module.sha256_bytes(target.read_bytes())
        if actual != entry.content_hash:
            raise PacketExportError(
                f"{entry.path} hashes to {actual}, not the {entry.content_hash} recorded"
            )
        ordinals.append(entry.ordinal)
    if sorted(ordinals) != list(range(1, len(ordinals) + 1)):
        raise PacketExportError(
            f"manifest ordinals {sorted(ordinals)} are not the ordered list 1..{len(ordinals)}"
        )


def _build(root: Path, packet: Packet, evidence: Evidence, at: datetime, repo: Path) -> Written:
    layout = plan(packet, evidence)
    held = packet.totals()
    approved = tables_module.approved_fair_value(packet)

    gaps = tables_module.gap_report(packet, evidence)
    tally = cover_module.counts(packet, evidence, len(gaps.rows))
    provenance = manifest_module.Provenance(
        packet_id=packet_id_for(packet, at),
        generated_at=at,
        generator_ref=manifest_module.GENERATOR_REF,
        generator_commit=manifest_module.git_commit(repo),
    )
    built = [
        cover_module.cover(packet, evidence, provenance, held, approved, tally),
        tables_module.holdings(packet),
        tables_module.requirements(packet),
        tables_module.evidence_index(packet, evidence, layout),
        tables_module.approval_log(packet, evidence),
        gaps,
    ]

    paths = _companies(root, packet, evidence, layout)
    _verify_citations(packet, evidence, root, layout)

    workbook_module.write(root / WORKBOOK_NAME, workbook_module.workbook_bytes(built))
    paths.append(WORKBOOK_NAME)
    for table in built:
        name = f"{table.key}.csv"
        workbook_module.write(root / name, workbook_module.csv_bytes(table))
        paths.append(name)
    workbook_module.write(
        root / README_NAME,
        cover_module.readme(packet, provenance, held, tally).encode("utf-8"),
    )
    paths.append(README_NAME)

    entries = manifest_module.entries_for(root, paths)
    _verify_entries(root, entries)
    manifest = manifest_module.build(
        packet=packet,
        evidence=evidence,
        tables=built,
        provenance=provenance,
        entries=entries,
        held_totals=held,
        approved_totals=approved,
    )
    (root / MANIFEST_NAME).write_bytes(manifest_module.serialise(manifest))
    return Written(
        packet_id=provenance.packet_id,
        root=root,
        manifest=manifest,
        fund_id=packet.fund_id,
        period_id=packet.period.id,
        schema_version=packet.schema_version,
        policy_version=packet.policy_version,
        tables=built,
    )


def export(
    packet: Packet,
    evidence: Evidence,
    destination: Path,
    *,
    at: datetime | None = None,
    repo: Path | None = None,
) -> Written:
    """Write the packet to `destination`, atomically. Raises rather than half-publishing."""
    at = at or datetime.now(UTC)
    repo = repo or Path(__file__).resolve().parents[1]
    destination = destination.resolve()
    staging = destination.parent / f".staging-{destination.name}-{uuid.uuid4().hex[:8]}"
    superseded = destination.parent / f".superseded-{destination.name}-{uuid.uuid4().hex[:8]}"
    staging.mkdir(parents=True)
    try:
        written = _build(staging, packet, evidence, at, repo)
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if isinstance(exc, PacketExportError):
            raise
        raise PacketExportError(
            f"packet generation failed and nothing was published: {exc}"
        ) from exc

    had_previous = destination.exists()
    if had_previous:
        destination.rename(superseded)
    try:
        staging.rename(destination)
    except OSError as exc:
        if had_previous:
            superseded.rename(destination)
        shutil.rmtree(staging, ignore_errors=True)
        raise PacketExportError(f"could not publish the packet to {destination}: {exc}") from exc
    shutil.rmtree(superseded, ignore_errors=True)
    return replace(written, root=destination)


def record(conn: Conn, written: Written) -> None:
    """Register the published packet and its manifest in the ledger.

    Optional, and off by default. The filesystem packet is the deliverable; this
    is what makes it referenceable — `review_decision.packet_id` points at a
    `packet_version`, and the approval trigger in `0003` reads the manifest
    entries to refuse an approval over an empty or non-contiguous one.

    `packet_version` is append-only, so this inserts a NEW version per generation
    rather than updating one. The caller owns the transaction: psycopg's outermost
    `transaction()` block commits on exit, and a generator does not get to decide
    that on the caller's behalf.
    """
    conn.execute(
        "insert into packet_version (id, fund_id, period_id, audit_scope, state,"
        " schema_version, policy_version, generator_ref)"
        " values (%s, %s, %s, 'packet', 'generated', %s, %s, %s)",
        (
            written.packet_id,
            written.fund_id,
            written.period_id,
            written.schema_version,
            written.policy_version,
            f"{manifest_module.GENERATOR_REF}@{written.manifest_hash}",
        ),
    )
    for entry in written.manifest["entries"]:
        conn.execute(
            "insert into packet_manifest_entry (packet_id, path, content_hash, ordinal)"
            " values (%s, %s, %s, %s)",
            (written.packet_id, entry["path"], entry["content_hash"], entry["ordinal"]),
        )


def export_packet(
    conn: Conn,
    fund_id: str,
    period_id: str,
    destination: Path,
    *,
    at: datetime | None = None,
) -> Written:
    """Read one fund-period out of the ledger and publish its packet."""
    from api import ledger

    packet = ledger.packet(conn, fund_id, period_id)
    if packet is None:
        raise PacketExportError(f"no packet for {fund_id} at {period_id}")
    evidence = gather(conn, packet)
    return export(packet, evidence, destination, at=at)
