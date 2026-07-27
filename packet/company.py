"""One portfolio company's slice of a packet that has already been published.

The audit letter closes by asking for the support "organized by portfolio
company", and `layout.py` makes the company folder the packet's primary
structure. What was missing was the ability to take ONE of those folders away
without taking the other seven with it.

This is a filter over a finished export, not a second exporter. `export_packet`
validates before it publishes — every citation resolved against the exported
text, every manifest entry re-hashed off disk, an approved-but-unsupported
position refused outright — and a per-company build that skipped those checks
would be a deliverable produced by a path nothing guards. So the whole packet is
generated, and this decides which of its files travel.

**What travels, and why it is not only the company folder.**

Everything except the OTHER companies' source documents. The seven CSVs, the
workbook, the README and `MANIFEST.json` are carried whole and unmodified, and
each still hashes to the value the manifest records for it.

The tempting alternative — trim each CSV to the chosen company's rows — was
rejected twice over. First, it is the defect this project keeps finding: the gap
report, the evidence index and the recomputation table are where the system
states what it does NOT know, and a copy of them cut to one company reports a
smaller set of findings than the packet found. Second, a trimmed table is a file
no manifest attests to: `holdings.csv` carries a footer stating the fund's total
and the unsupported portion of it, so a version holding one company's rows under
the fund's total is a wrong number that renders, reconciles to itself and passes
every type check. Recomputing that footer per company would invent a "company
total" the ledger has no concept of and `PacketTotals` never blessed.

Omitting the tables instead — a folder and nothing else — was rejected for the
first of those reasons alone. An archive that drops `gap_report.csv` is an
archive that cannot state its own gaps.

So the difference between this archive and the packet is exactly one thing:
other companies' documents. It is not left to be inferred. `COMPANY_SCOPE.txt`
names every withheld path, in the manifest's own words, so the reader can
reconcile the member list against `MANIFEST.json` rather than discovering a
shortfall and guessing at its cause.
"""

from __future__ import annotations

from dataclasses import dataclass

from packet.export import EMPTY_FOLDER_NOTE, MANIFEST_NAME, Written
from packet.layout import COMPANIES

#: The archive's account of its own difference from the packet it was cut from.
#: Named in capitals beside `MANIFEST.json` and `README.md` so a reader opening
#: the archive meets it before they go looking for a folder that is not there.
COMPANY_SCOPE_NOTE = "COMPANY_SCOPE.txt"


@dataclass(frozen=True)
class CompanySlice:
    """Which of a published packet's files belong in one company's archive.

    `present` and `withheld` together are every entry the manifest holds. That
    is the property the whole slice turns on and it is asserted rather than
    assumed — a path filed under neither would leave the archive short by a file
    nobody could account for, which is the shape of a silent omission.
    """

    holding_id: str
    directory: str
    present: tuple[str, ...]
    withheld: tuple[str, ...]

    @property
    def label(self) -> str:
        """The company folder's name, as the writer chose it.

        Read off the plan rather than sanitised again from the company name. Two
        companies whose names sanitise to the same folder are told apart by
        `plan()` appending the holding id, and re-deriving the name here would
        produce a label that disagrees with the folder it describes.
        """
        return self.directory.removeprefix(f"{COMPANIES}/")

    @property
    def documents(self) -> tuple[str, ...]:
        """What is inside this company's folder, as opposed to beside it.

        `present` is the whole archive, tables and all. This is the half the
        letter's "organized by portfolio company" refers to, and separating them
        is what lets the check below ask its question — over the folder, never
        over the archive, which is never empty.
        """
        return tuple(path for path in self.present if path.startswith(f"{self.directory}/"))

    @property
    def holds_no_source_document(self) -> bool:
        """Is this a position the fund holds no document for?

        A real state, and one of the packet's findings rather than an error:
        `_companies()` writes a note into the folder saying so, and the gap
        report carries the same finding as `no_source_documents`. The archive is
        therefore never empty, and never a 404 — an absence that produced no
        file would be an absence the deliverable does not state.
        """
        return self.documents == (f"{self.directory}/{EMPTY_FOLDER_NOTE}",)


def holdings_in(written: Written) -> tuple[str, ...]:
    """Every position the packet was built for, as the ids a caller must name."""
    return tuple(sorted(written.layout.company_dir))


def slice_for(written: Written, holding_id: str) -> CompanySlice | None:
    """The files one company's archive carries, or `None` for a position the
    packet does not hold.

    `None` rather than an empty slice. A position that is not in this packet and
    a position with no documents are different answers — the second is a finding
    the packet states in three places — and returning an empty archive for both
    would render the finding and the mistake identically.
    """
    directory = written.layout.company_dir.get(holding_id)
    if directory is None:
        return None
    inside = f"{directory}/"
    #: Prefix-matched with the separator attached. `companies/Ada` is not a
    #: prefix of `companies/Adafruit/x.pdf` once the slash is part of the test,
    #: and without it one company's archive would quietly acquire another's
    #: documents — the one thing "organized by portfolio company" must not do.
    mine = [
        path.startswith(inside) or not path.startswith(f"{COMPANIES}/") for path in written.paths
    ]
    present = tuple(path for path, keep in zip(written.paths, mine, strict=True) if keep)
    withheld = tuple(path for path, keep in zip(written.paths, mine, strict=True) if not keep)
    assert len(present) + len(withheld) == len(written.paths)
    return CompanySlice(
        holding_id=holding_id, directory=directory, present=present, withheld=withheld
    )


def scope_note(written: Written, chosen: CompanySlice) -> bytes:
    """The sentence the archive owes its reader, as a file inside the archive.

    Written from the manifest and the slice, so it cannot describe an archive
    other than the one it ships in: the counts are the lengths of the two lists
    the writer used, and every withheld path is named rather than summarised.
    """
    absent = (
        [
            "",
            "This position has NO SOURCE DOCUMENT. Its folder holds a note saying so,",
            "and `gap_report.csv` carries the same finding. An empty folder would have",
            "read as an oversight; the note and the gap row are the fund stating that",
            "it has not located the paperwork.",
        ]
        if chosen.holds_no_source_document
        else []
    )
    lines = [
        f"This archive is one portfolio company's slice of packet {written.packet_id}.",
        "",
        f"Portfolio company folder : {chosen.directory}",
        f"Holding id               : {chosen.holding_id}",
        f"Fund and period          : {written.fund_id} · {written.period_id}",
        f"Manifest hash            : {written.manifest_hash}",
        *absent,
        "",
        "WHAT IS HERE",
        "",
        f"Every packet-level file, unmodified: {MANIFEST_NAME}, README.md, the workbook",
        "and all seven CSVs are byte-for-byte the files the full packet carries, and each",
        f"still hashes to the value {MANIFEST_NAME} records for it. They describe the whole",
        "fund-period rather than this company alone, and that is deliberate. The gap",
        "report, the evidence index and the recomputation table are where this packet",
        "states what it does not know; a copy of them trimmed to one company would report",
        "fewer findings than the packet found, and the holdings table's total is a total",
        "of the fund, which one company's rows do not add up to.",
        "",
        "WHAT IS NOT HERE",
        "",
        f"The source documents filed under the other company folders — "
        f"{len(chosen.withheld)} file(s),",
        "listed below by the path the manifest gives them. Nothing else was removed:",
    ]
    lines.extend(f"  {path}" for path in chosen.withheld)
    lines.extend(
        [
            "",
            f"{len(chosen.present)} file(s) present and {len(chosen.withheld)} withheld, "
            f"against {len(written.paths)} entries in {MANIFEST_NAME}.",
            f"This file and {MANIFEST_NAME} are the two members that are not manifest entries.",
            "",
            "This archive was generated from the ledger on request and registered nowhere.",
            "No packet version row was written, so nothing here is an approved packet.",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")
