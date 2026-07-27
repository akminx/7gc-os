"""Where each artefact sits inside the packet.

The audit letter asks for the support "organized by portfolio company", so the
company folder is the packet's primary structure rather than a convenience. It
is planned once, here, and both the writer and the evidence index read the same
plan — a second, independently computed path is how an index comes to point at a
file that is not there.

Every document is exported twice: the bytes the fund holds, and the canonical
text those bytes produced. `span_start`/`span_end` on a cited fact are code-point
offsets into the second, so exporting only the first would leave every citation
in the index pointing into a string the auditor does not have.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from packages.contracts.models import Packet
from packet.evidence import Evidence

COMPANIES = "companies"

#: The characters a filesystem, a zip archive or a spreadsheet hyperlink will
#: each object to somewhere — plus the two path separators and anything that
#: would let a stored filename escape its company folder.
#:
#: A denylist, not an allowlist. The corpus filenames carry commas, apostrophes
#: and ampersands, and an allowlist mangled every one of them: an auditor
#: matching the exported file against the fund's own document register should be
#: comparing the same string, not a sanitised one.
_UNSAFE = re.compile(r'[/\\:*?"<>|\x00-\x1f]+')


def safe_name(raw: str) -> str:
    """A filesystem-safe rendering of a company or document name.

    `..` and a leading separator are the two ways a name taken from data becomes
    a path that leaves the directory it was meant for. Both are neutralised here
    rather than trusted to the caller.
    """
    cleaned = _UNSAFE.sub("_", raw).replace("..", "__").strip(" .")
    return cleaned or "unnamed"


@dataclass(frozen=True)
class Layout:
    """Packet-relative paths, with POSIX separators on every platform."""

    company_dir: dict[str, str] = field(default_factory=dict)
    source_path: dict[str, str] = field(default_factory=dict)
    text_path: dict[str, str] = field(default_factory=dict)


def plan(packet: Packet, evidence: Evidence) -> Layout:
    """Assign a folder to every position and a pair of paths to every document.

    Collisions are resolved by appending the holding id rather than by silently
    reusing the folder: two companies sharing a sanitised name would otherwise
    have their evidence merged, which is the one thing "organized by portfolio
    company" must not do.
    """
    layout = Layout()
    taken: set[str] = set()
    for row in sorted(packet.rows, key=lambda r: (r.company_name, r.holding_id)):
        name = safe_name(row.company_name)
        if name.casefold() in taken:
            name = f"{name} ({safe_name(row.holding_id)})"
        taken.add(name.casefold())
        directory = f"{COMPANIES}/{name}"
        layout.company_dir[row.holding_id] = directory

        used: set[str] = set()
        holding = evidence.by_holding.get(row.holding_id)
        for document in holding.documents if holding else ():
            filename = safe_name(document.filename)
            if filename.casefold() in used:
                filename = f"{safe_name(document.document_version_id)}_{filename}"
            used.add(filename.casefold())
            layout.source_path[document.document_version_id] = f"{directory}/{filename}"
            layout.text_path[document.document_version_id] = f"{directory}/{filename}.canonical.txt"
    return layout
