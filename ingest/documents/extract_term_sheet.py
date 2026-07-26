"""The Mom Project — Series C summary of terms, 15 September 2021.

The corpus's twentieth document, and for most of a day the one nothing read.
The four-way split of the extractor families simply omitted it, so
`fund_i_the_mom_project` carried no claims at all — indistinguishable, in the
data, from Because Market, which carries none because the fund genuinely holds
nothing for it. Those are opposite facts and a packet that renders them the same
way is the exact failure this system exists to prevent.

`tests/test_document_load.py` now asserts every file in the corpus has a reader,
so the next omission is a red test rather than a quiet blank.

## Why it is `non_binding`

The header says so — *"Summary of Terms — September 15, 2021 — Non-binding
except as noted"* — and the trailing note says the executed agreement is
somewhere else: *"The executed Series C Stock Purchase Agreement is on file with
company counsel."* §6.2.2 governs: `execution_status` describes the artifact in
the Fund's possession, and what the Fund possesses is a summary of terms.

The excerpt calls itself *"this excerpt from the executed term sheet"*, which is
the same trap Lucra's term sheet sets. An *executed term sheet* is still a term
sheet: what was signed is an agreement to negotiate, and the document says in
its own header that it is non-binding. Reading "executed" off that sentence
would promote the weakest evidence in the file to the strongest.

Lucra's term sheet is read by `extract_irregular.py`, where it landed with the
other one-off shapes. These two are the same shape and should share a module the
moment a third term sheet appears; two is not yet a pattern.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from ingest.documents.claims import ClaimDraft, FactDraft, cited_fact
from ingest.documents.parse import ParsedDocument
from packages.contracts.enums import ExecutionStatus, SourceClass

TERM_SHEET_DATE = date(2021, 9, 15)

#: The class this document prices, and the class the Fund holds through it.
#: They coincide here, unlike Dream — recorded anyway, because
#: `require_cross_class_policy` refuses a price beside a NULL class rather than
#: assuming the convenient answer.
PRICED_CLASS = "series_c"

_PATTERNS: dict[str, re.Pattern[str]] = {
    "term_sheet_date": re.compile(r"Summary of Terms — (?P<value>September \d+, \d{4})"),
    "binding_status": re.compile(r"— (?P<value>Non-binding except as noted)"),
    "securities": re.compile(r"Securities\s+(?P<value>Series C Preferred Stock)"),
    "amount_of_financing": re.compile(r"Amount of financing\s+Up to (?P<value>\$[\d,]+)"),
    "price_per_share": re.compile(r"Price per share\s+(?P<value>\$[\d.]+)"),
    "pre_money_valuation": re.compile(r"Valuation\s+(?P<value>\$[\d,]+) pre-money"),
    "post_money_valuation": re.compile(r"pre-money; (?P<value>\$[\d,]+) post-money"),
    # The Fund's own line, quoted whole. `$500,000` also appears in the pro rata
    # rights row ("Major Investors (≥ $500,000)"), so a figure lifted out of its
    # own row would cite a threshold and call it a purchase.
    "fund_commitment": re.compile(r"7GC Fund I, L\.P\. \((?P<value>\$[\d,]+) / [\d,]+ shares\)"),
    "fund_shares": re.compile(r"7GC Fund I, L\.P\. \(\$[\d,]+ / (?P<value>[\d,]+) shares\)"),
    "anticipated_closing": re.compile(
        r"Anticipated closing\s+On or about (?P<value>September \d+, \d{4})"
    ),
    # The R1 gap, in the document's own words. The executed agreement exists and
    # is elsewhere — `with_counsel`, not `not_located`, and the difference
    # changes what the auditor is asked to do about it (INV-12).
    "executed_docs_location": re.compile(
        r"Series C Stock Purchase Agreement is\s+(?P<value>on file with company counsel)"
    ),
}


def term_sheet_facts(document_version_id: str, parsed: ParsedDocument) -> tuple[FactDraft, ...]:
    return tuple(
        cited_fact(
            document_version_id=document_version_id,
            canonical_text=parsed.canonical_text,
            field_name=name,
            pattern=pattern,
        )
        for name, pattern in _PATTERNS.items()
    )


def mom_project_claim(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str
) -> ClaimDraft:
    """One claim: a non-binding summary of terms, at the Fund's own record.

    `applicable_to` is left open because the document states no expiry. The
    no-shop clause is 45 days *from execution* and binds the company's conduct,
    not the reliance window of the figures — reading it as an expiry would
    invent a date the source does not state (INV-16).
    """
    return ClaimDraft(
        claim_key="series_c_term_sheet",
        holding_id=holding_id,
        source_class=SourceClass.COMPANY_COMMUNICATION,
        execution_status=ExecutionStatus.NON_BINDING,
        issued_date=TERM_SHEET_DATE,
        as_of_date=TERM_SHEET_DATE,
        applicable_from=TERM_SHEET_DATE,
        applicable_to=None,
        priced_class=PRICED_CLASS,
        price_per_share=Decimal("5.00"),
        facts=term_sheet_facts(document_version_id, parsed),
    )
