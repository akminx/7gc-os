"""Dream — Series B pro forma capitalisation table, 14 November 2025.

The first extractor, and the reference the four document families are built
against. It is deliberately one document: the spine has to prove the whole path
— parse, hash, page-split, claim, cited fact, database refusal — before anything
fans out onto a contract that has not been exercised.

## Why this document

Dream is the case the audit letter asks about most directly. Harwell & Kent ask
to *"identify any positions marked on a pro forma basis pending receipt of
executed documentation"*, and this is one: the round is described as closed and
the artifact in the Fund's possession is a pro forma table, not a closing set.
§6.2.2 settles which of those `execution_status` records — the file, not the
world — so this claim is `pro_forma` even though note (d) references an executed
Stock Purchase Agreement.

It also carries the corpus's clearest INV-17 case. 7GC holds **Series A-1**;
the price this document establishes is the **Series B** price of $8.00. Marking
the A-1 position at $8.00 is pricing one class off another's evidence, which is
a policy act that must be cited rather than an arithmetic convenience — so
`priced_class` is `series_b`, which is what makes the database demand a cited
cross-class policy decision before any valuation approval over this evidence.
Recording it as `series_a1` would be the cheapest possible collapse of INV-17:
one word, no error, and the gate goes quiet.

## Why patterns and not offsets

`-layout` renders a cap-table row as a label, thirty spaces and a figure. The
regexes below are the reviewable artifact; the quote is whatever they matched,
verbatim from the document, and the span is computed from that match. No offset
is written down anywhere in this file, which is what makes a wrong one
unexpressible rather than merely unlikely.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from ingest.documents.claims import ClaimDraft, FactDraft, cited_fact
from ingest.documents.parse import ParsedDocument
from packages.contracts.enums import ExecutionStatus, SourceClass

#: 14 November 2025 — the closing date the table states, and the date from which
#: it is the round of record. INV-3 keeps this separate from the measurement
#: date it is relied on at; INV-16 keeps it separate from how long it applies.
CLOSING_DATE = date(2025, 11, 14)

#: The class 7GC holds, and the class this document prices. They differ, and
#: that difference is the whole INV-17 story above.
HELD_CLASS = "series_a1"
PRICED_CLASS = "series_b"

#: Each pattern must match exactly once and must capture `value` inside its own
#: match, so the figure is provably part of the passage cited for it (INV-8).
#:
#: `7GC Fund II, L.P.` is matched with its share count, price and percentage in
#: one quote rather than by searching for `625,000` alone: `$3.20` occurs five
#: times in this document and `$8.00` four, so a figure lifted out of its row
#: cites a number that is genuinely present and says nothing about whose it is.
_PATTERNS: dict[str, re.Pattern[str]] = {
    "fund_shares": re.compile(r"7GC Fund II, L\.P\.\s+(?P<value>[\d,]+)\s+\$[\d.]+\s+[\d.]+%"),
    "fund_entry_price_per_share": re.compile(
        r"7GC Fund II, L\.P\.\s+[\d,]+\s+(?P<value>\$[\d.]+)\s+[\d.]+%"
    ),
    # The section heading under which the 7GC row sits. This is what makes the
    # held class a CITED FACT rather than a constant in this file: the document
    # states "Series A-1 Preferred — Holders of Record", and 7GC Fund II, L.P.
    # appears in that table. A cross-family review found the class asserted in
    # `HELD_CLASS` above while nothing in the ledger recorded it, so the lot
    # reached the policy layer as `unstated` and the document naming it was
    # never consulted.
    #
    # Distinct from `series_b_price_per_share` below, and the distinction is the
    # whole INV-17 story: a cap table's PRICED class is the round being raised,
    # its HOLDERS-OF-RECORD section is what the fund owns. Reading the first as
    # the held class collapses the invariant; reading the second is what it
    # needs.
    "fund_held_security_class": re.compile(r"(?P<value>Series A-1 Preferred) — Holders of Record"),
    "series_b_price_per_share": re.compile(
        r"Series B Preferred Stock issued at (?P<value>\$[\d.]+) per share"
    ),
    "post_money_valuation": re.compile(
        r"Post-money valuation: (?P<value>\$[\d,]+) on [\d,]+ fully diluted shares"
    ),
    "fully_diluted_shares": re.compile(
        r"Post-money valuation: \$[\d,]+ on (?P<value>[\d,]+) fully diluted shares"
    ),
    # The date wraps a line in the source — "Closing Date: November\n14, 2025" —
    # so the quote contains that newline. Nothing repairs it: the canonical text
    # is the extractor's output with no post-processing, and a value stitched
    # back together would no longer be a substring of the document (SPEC §8).
    # `cited_numeral` reads no number from it, so it is stored as text with a
    # NULL `value_numeric` rather than as the nonsense figure a digit-stripping
    # parser would produce.
    "closing_date": re.compile(r"Closing Date: (?P<value>November\s+\d+, \d{4})"),
}


def dream_facts(document_version_id: str, parsed: ParsedDocument) -> tuple[FactDraft, ...]:
    """Every figure this document states that the packet relies on."""
    return tuple(
        cited_fact(
            document_version_id=document_version_id,
            canonical_text=parsed.canonical_text,
            field_name=field_name,
            pattern=pattern,
        )
        for field_name, pattern in _PATTERNS.items()
    )


def dream_claim(*, document_version_id: str, parsed: ParsedDocument, holding_id: str) -> ClaimDraft:
    """The one assertion this document makes, at one authority. INV-15.

    A pro forma cap table prepared by company counsel is a single authority, so
    it is a single claim. A document carrying several — an administrator
    statement forwarded under a covering email, say — produces several, and
    classifying by envelope would mis-tier the strongest evidence in the set.

    `applicable_to` is left open because the table states no expiry. INV-16 is
    about what the *source* says: inventing a window here would be the same
    error as ignoring Capsule's, in the opposite direction.
    """
    return ClaimDraft(
        claim_key="series_b_pro_forma",
        holding_id=holding_id,
        source_class=SourceClass.COMPANY_CAP_TABLE,
        execution_status=ExecutionStatus.PRO_FORMA,
        issued_date=CLOSING_DATE,
        as_of_date=CLOSING_DATE,
        applicable_from=CLOSING_DATE,
        applicable_to=None,
        priced_class=PRICED_CLASS,
        price_per_share=Decimal("8.00"),
        facts=dream_facts(document_version_id, parsed),
    )
