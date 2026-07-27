"""The cover sheet and the README, which are where the packet states its own gaps.

Both are built from the same counts, so the sentence at the top of the README and
the figures on the cover cannot disagree — the failure this exists to prevent is a
narrative that reads clean over a table that does not.

Every figure here is qualified. INV-19 · a total must say what it is a total of,
so the fund amount never appears without the kind and label that travel with it,
and the unsupported subtotal is stated beside it rather than behind a link.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.contracts.models import Packet, PacketTotals
from packet.evidence import Evidence
from packet.manifest import PACKET_FORMAT_VERSION, Provenance
from packet.tables import Cell, Table, money_text


@dataclass(frozen=True)
class Counts:
    positions: int
    held: int
    unheld: int
    marked: int
    supported: int
    approved: int
    cited_facts: int
    documents: int
    gap_observations: int
    gap_findings: int


def counts(packet: Packet, evidence: Evidence, gap_rows: int) -> Counts:
    return Counts(
        positions=len(packet.rows),
        held=sum(1 for r in packet.rows if r.held_at_date),
        unheld=sum(1 for r in packet.rows if not r.held_at_date),
        marked=sum(1 for r in packet.rows if r.mark is not None),
        supported=sum(1 for r in packet.rows if r.supported),
        approved=sum(1 for r in packet.rows if r.approved),
        cited_facts=sum(
            len(facts)
            for holding in evidence.by_holding.values()
            for facts in holding.facts.values()
        ),
        documents=len(evidence.documents()),
        gap_observations=sum(len(r.gaps) for r in packet.rows),
        gap_findings=gap_rows,
    )


def statement(packet: Packet, held: PacketTotals, tally: Counts) -> str:
    """The one paragraph a reader who reads nothing else will read.

    Written from the counts rather than chosen from a set of phrasings, so a
    packet cannot describe itself as something the tables underneath it deny.
    """
    on = packet.period.period_date.isoformat()
    if tally.approved == 0:
        opening = (
            f"No position in this packet carries a recorded valuation approval "
            f"(0 of {tally.positions})."
        )
    else:
        opening = (
            f"{tally.approved} of {tally.positions} positions carry a recorded valuation approval."
        )
    if held.contains_unsupported_inputs:
        support = (
            f"{money_text(held.unsupported_amount)} of the "
            f"{money_text(held.amount)} {held.kind.value} figure — across "
            f"{held.unsupported_positions} of {tally.held} positions held at {on} — "
            f"is not supported by sufficient evidence in the Fund's records."
        )
    else:
        support = (
            f"Every position held at {on} has sufficient evidence for each applicable requirement."
        )
    unheld = ""
    if held.packet_gap_positions > held.unsupported_positions:
        unheld = (
            f" A further {held.packet_gap_positions - held.unsupported_positions} "
            f"position(s) not held at {on} also carry open findings; they are "
            f"reported here because the period under audit includes their "
            f"realisation, and they are excluded from the total above."
        )
    return f"{opening} {support}{unheld}"


def _packet_approval(evidence: Evidence) -> str:
    approved = any(
        d.decision_type == "packet" and d.status == "approved" for d in evidence.decisions
    )
    return "approved" if approved else "not approved — no packet decision is recorded"


def cover(
    packet: Packet,
    evidence: Evidence,
    provenance: Provenance,
    held: PacketTotals,
    approved: PacketTotals,
    tally: Counts,
) -> Table:
    on = packet.period.period_date.isoformat()
    rows: list[tuple[Cell, ...]] = [
        ("Fund", packet.fund_id),
        ("Reporting period", packet.period.label),
        ("Measurement date", on),
        ("Audit scope", packet.period.audit_scope.value),
        ("Packet id", provenance.packet_id),
        ("Packet format version", PACKET_FORMAT_VERSION),
        ("Ledger schema version", packet.schema_version),
        ("Policy version", packet.policy_version),
        ("Generated at (UTC)", provenance.generated_at.isoformat()),
        ("Generator", provenance.generator_ref),
        ("Generator commit", provenance.generator_commit or "unresolved"),
        ("", None),
        ("Positions in this packet", tally.positions),
        (f"Positions held at {on}", tally.held),
        (f"Positions not held at {on} (realised in the period)", tally.unheld),
        ("Positions carrying a mark at this date", tally.marked),
        # Named for what the ledger computes, not for what the label would read
        # best as. `HoldingRow.supported` demands R1 and R2 be sufficient on a
        # position that was not held at the date, where the requirements do not
        # arise — so "every applicable requirement is sufficient" would be a
        # claim this number does not make. See
        # `packet.tables.not_applicable_because_unheld`.
        (
            "Positions the ledger reports as fully supported",
            f"{tally.supported} of {tally.positions}",
        ),
        (
            "Positions with a recorded valuation approval",
            f"{tally.approved} of {tally.positions}",
        ),
        ("", None),
        # INV-19 · every one of these labels carries the kind, so a figure lifted
        # out of this file arrives with the answer to "a total of what?" already
        # attached. The first version headed both blocks "Amount", which meant a
        # reader loading the cover into a dictionary kept the second and printed
        # the approved figure under the fund's name.
        (f"{held.kind.value} — what this total is", held.label),
        (f"{held.kind.value} — amount", money_text(held.amount)),
        (f"{held.kind.value} — of which unsupported", money_text(held.unsupported_amount)),
        (
            f"{held.kind.value} — unsupported positions held at this date",
            f"{held.unsupported_positions} of {tally.held}",
        ),
        (
            f"{held.kind.value} — further unsupported positions not held at this date",
            held.packet_gap_positions - held.unsupported_positions,
        ),
        (
            f"{held.kind.value} — contains unsupported inputs",
            "yes" if held.contains_unsupported_inputs else "no",
        ),
        ("", None),
        (f"{approved.kind.value} — what this total is", approved.label),
        (f"{approved.kind.value} — amount", money_text(approved.amount)),
        (f"{approved.kind.value} — positions in this total", tally.approved),
        ("", None),
        ("Source documents exported", tally.documents),
        ("Cited source facts in the evidence index", tally.cited_facts),
        ("Recorded gap observations", tally.gap_observations),
        ("Gap report findings", tally.gap_findings),
        ("Packet approval", _packet_approval(evidence)),
        ("", None),
        ("Statement", statement(packet, held, tally)),
    ]
    return Table(
        key="cover",
        title="Cover",
        note=(
            f"Valuation support for {packet.fund_id}, {packet.period.label}, "
            f"measurement date {on}. Prepared in response to the Harwell & Kent LLP "
            f"valuation support request. Amounts are tracker-reported and unaudited."
        ),
        headers=("Item", "Value"),
        rows=tuple(rows),
    )


#: What each file in the packet holds. A table rather than prose because a reader
#: who wants one artefact should not have to read a paragraph to find it.
_CONTENTS: tuple[tuple[str, str], ...] = (
    ("`Valuation_Support.xlsx`", "Every table below, one per sheet."),
    ("`cover.csv`", "The figures on this page, as data."),
    (
        "`holdings.csv`",
        "One row per portfolio investment: mark, support status, per-requirement verdicts.",
    ),
    (
        "`requirements.csv`",
        "The five PBC requirements per position, each with its verdict and reason codes.",
    ),
    (
        "`evidence_index.csv`",
        "One row per cited source fact, with the passage it resolves to.",
    ),
    (
        "`approval_log.csv`",
        'What has been approved, and by whom. A position with no decision reads "none recorded".',
    ),
    (
        "`gap_report.csv`",
        "Everything this packet does not evidence, and the next action for each.",
    ),
    (
        "`companies/<company>/`",
        "The source documents for that position, and the canonical text each was parsed into.",
    ),
    (
        "`MANIFEST.json`",
        "Content hashes for every file above, the mark revisions, the document "
        "versions and the generator commit.",
    ),
)


def readme(packet: Packet, provenance: Provenance, held: PacketTotals, tally: Counts) -> str:
    on = packet.period.period_date.isoformat()
    contents = "\n".join(f"| {path} | {what} |" for path, what in _CONTENTS)
    approvals = (
        "It records no approval of any position."
        if tally.approved == 0
        else f"It records approvals for {tally.approved} of {tally.positions} positions "
        "and no others."
    )
    return f"""# Valuation support — {packet.fund_id}, {packet.period.label} ({on})

Prepared in response to the Harwell & Kent LLP valuation support request for
7GC Fund II, L.P., FY2023–FY2025. The support is organised by portfolio company,
as requested.

**{statement(packet, held, tally)}**

## What is in this packet

| Path | What it holds |
|---|---|
{contents}

## Tracing a figure to its source

1. Find the figure in `holdings.csv` or on the `Holdings` sheet.
2. Open `evidence_index.csv` and filter to that portfolio company.
3. Each row names the exported source document, the exported canonical text, and
   two offsets. Read `text[start:end]` of the canonical text file and you have the
   quoted passage, verbatim — it is reproduced in the `Cited passage` column so the
   two can be checked against each other.
4. `MANIFEST.json` carries the SHA-256 of both files, so the document you opened
   can be proved to be the document that was cited.

## What this packet does not assert

- It does not assert fair value. Every amount is what the Fund's tracker reports,
  unaudited, and the `{held.kind.value}` total states exactly that.
- It does not assert that unsupported positions are correctly valued. It states
  which ones are unsupported and why.
- {approvals}

Generated {provenance.generated_at.isoformat()} by `{provenance.generator_ref}`
at commit `{provenance.generator_commit or "unresolved"}`.
"""
