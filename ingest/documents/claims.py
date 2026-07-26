"""The path from a parsed document to a stored claim and its cited facts.

`claim` in `0001_init.sql` is the contract extractors write to. INV-15 puts
authority on the claim rather than on the file: one PDF can carry several claims
of differing authority, and classifying by envelope mis-tiers the strongest
evidence in the set. So an extractor's job is not "read this PDF" — it is "name
the assertions this document makes, say what kind of evidence each is, and cite
the exact passage for every figure."

Two rules are structural here rather than conventional:

* **A fact is produced from a pattern, never from a hand-written offset.**
  `cited_fact()` is the only constructor, and there is no parameter through
  which a caller can supply a span. `scripts/arch_checks.py` refuses
  `span_start=` outside `packages/contracts/citations.py`.
* **Nothing reaches the database unverified.** `store_claim()` re-resolves every
  citation against the canonical text it is about to be stored beside, and
  refuses the whole claim if one fails. The trigger in
  `0008_citations_resolve.sql` checks the same thing from the other side, so a
  writer that skips this module is refused too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import psycopg

from ingest.documents.parse import ParsedDocument
from packages.contracts.citations import (
    CitationError,
    cited_numeral,
    locate_pattern,
    supports_value,
    verify,
)
from packages.contracts.enums import ExecutionStatus, SourceClass
from packages.contracts.models import Citation

Conn = psycopg.Connection[tuple[object, ...]]


@dataclass(frozen=True)
class FactDraft:
    """One figure a document states, with the passage that states it."""

    field_name: str
    value_text: str
    citation: Citation
    value_numeric: Decimal | None


@dataclass(frozen=True)
class ClaimDraft:
    """One assertion a document makes, at one authority. INV-15, INV-3, INV-16."""

    claim_key: str
    holding_id: str
    source_class: SourceClass
    execution_status: ExecutionStatus
    issued_date: date
    applicable_from: date
    applicable_to: date | None = None
    as_of_date: date | None = None
    received_date: date | None = None
    priced_class: str | None = None
    price_per_share: Decimal | None = None
    facts: tuple[FactDraft, ...] = ()


def cited_fact(
    *,
    document_version_id: str,
    canonical_text: str,
    field_name: str,
    pattern: re.Pattern[str],
    value_group: str = "value",
) -> FactDraft:
    """Read one figure out of the document, cited to the passage stating it.

    The pattern must match exactly once and must capture a group named
    `value` — the figure itself — inside the wider passage it quotes. That
    nesting is the point: INV-8's second hole is that r1 "proved a quote
    existed, not that it *supported* the figure", so the value is required to be
    a substring of its own citation rather than merely accompanied by it.

    `value_numeric` is whatever `cited_numeral` reads, which is `None` for text
    that names no single figure. `None` is stored as NULL rather than as zero;
    the database refuses a `value_numeric` that disagrees with its text either
    way.
    """
    citation, match = locate_pattern(
        document_version_id=document_version_id,
        canonical_text=canonical_text,
        pattern=pattern,
    )
    value_text = match.group(value_group)
    if not supports_value(citation.quote, value_text):
        raise CitationError(
            f"{field_name}: captured value {value_text!r} is not inside the passage "
            f"cited for it. A group that reaches outside its own match cites nothing."
        )
    return FactDraft(
        field_name=field_name,
        value_text=value_text,
        citation=citation,
        value_numeric=cited_numeral(value_text),
    )


def store_document(conn: Conn, parsed: ParsedDocument) -> str:
    """Persist the source bytes and the canonical text. Idempotent by content.

    SPEC §10 · "content-addressed immutable versions; duplicate upload is
    idempotent". Idempotent here means *checked*, not skipped: re-ingesting
    returns the existing version only after confirming the stored text is the
    text we just extracted. A bare `on conflict do nothing` would make a hash
    collision, a truncated column or a half-applied migration look like a
    successful re-ingest, and every span already recorded against that version
    would then point into text nobody verified.
    """
    version_id = f"dv_{parsed.text_hash[:24]}"

    conn.execute(
        "insert into source_file (id, filename, content_hash, byte_size, bytes)"
        " values (%s, %s, %s, %s, %s) on conflict (content_hash) do nothing",
        (
            f"sf_{parsed.content_hash[:24]}",
            parsed.filename,
            parsed.content_hash,
            parsed.byte_size,
            parsed.source_bytes,
        ),
    )
    # Read the id back rather than reusing the one just offered. `do nothing`
    # keeps whatever row was already there, and if that row carries a different
    # id the foreign key below would fail against a source file that does exist.
    existing = conn.execute(
        "select id from source_file where content_hash = %s", (parsed.content_hash,)
    ).fetchone()
    if existing is None:
        raise CitationError(f"source file for {parsed.filename} did not store")
    source_id = existing[0]

    conn.execute(
        "insert into document_version"
        " (id, source_file_id, canonical_text, extractor, text_hash, page_count)"
        " values (%s, %s, %s, %s, %s, %s) on conflict (id) do nothing",
        (
            version_id,
            source_id,
            parsed.canonical_text,
            parsed.extractor,
            parsed.text_hash,
            parsed.page_count,
        ),
    )

    row = conn.execute(
        "select canonical_text, extractor, page_count from document_version where id = %s",
        (version_id,),
    ).fetchone()
    if row is None:
        raise CitationError(f"document version {version_id} did not store")
    stored_text, stored_extractor, stored_pages = row
    if (stored_text, stored_extractor, stored_pages) != (
        parsed.canonical_text,
        parsed.extractor,
        parsed.page_count,
    ):
        raise CitationError(
            f"{version_id} already holds different content than {parsed.filename} "
            "just extracted. Citations already recorded against it resolve into "
            "the stored text, so this is a collision, not a re-ingest."
        )
    return version_id


def store_claim(conn: Conn, version_id: str, draft: ClaimDraft, canonical_text: str) -> str:
    """Write one claim and its cited facts, or none of them.

    Every citation is re-resolved against the canonical text first. Checking
    before the insert rather than relying on the trigger is not redundancy for
    its own sake: it produces the diagnostic naming the field and the passage,
    where the trigger can only say the span did not resolve. The trigger remains
    the side that cannot be bypassed.
    """
    for fact in draft.facts:
        verify(fact.citation, canonical_text)
        if fact.citation.document_version_id != version_id:
            raise CitationError(
                f"{fact.field_name} cites {fact.citation.document_version_id} "
                f"but is being stored against {version_id}"
            )
        # The same two bindings the trigger checks. `cited_fact` produces facts
        # that satisfy them by construction, so this only bites on a hand-built
        # `FactDraft` — which is exactly the path that reached the database
        # carrying `value_text="625"` against a row stating 625,000.
        if not supports_value(fact.citation.quote, fact.value_text):
            raise CitationError(
                f"{fact.field_name}: the cited passage does not state "
                f"{fact.value_text!r} as a figure in its own right, exactly once"
            )
        if cited_numeral(fact.value_text) != fact.value_numeric:
            raise CitationError(
                f"{fact.field_name}: stored number {fact.value_numeric} is not the "
                f"figure {fact.value_text!r} states ({cited_numeral(fact.value_text)})"
            )

    # The claim's own figures must be figures the document states, and the only
    # evidence that it does is a fact cited on this claim. Two cross-family
    # reviews found this from opposite ends on the same day: a claim reading
    # `price_per_share=800` beside a fact citing `$8.00` was accepted, and the
    # API then rendered 800 next to a passage stating $8.00.
    #
    # Half the extractors bound the price by hand; the other half typed the
    # literal. A rule half the callers follow is not a rule.
    # `ClaimDraft` carries no `stated_amount`, though the `claim` table has one —
    # so this writer cannot set it and cannot check it. The trigger in 0009
    # covers that column for anything that reaches the table another way.
    cited = {f.value_numeric for f in draft.facts if f.value_numeric is not None}
    if draft.price_per_share is not None and draft.price_per_share not in cited:
        raise CitationError(
            f"claim {draft.claim_key!r} states price_per_share {draft.price_per_share}, "
            f"which no fact cited on it states. Cited figures: {sorted(cited) or 'none'}"
        )

    claim_id = f"{draft.holding_id}:{draft.claim_key}"
    conn.execute(
        "insert into claim (id, document_version_id, holding_id, claim_key, source_class,"
        " execution_status, issued_date, as_of_date, received_date, applicable_from,"
        " applicable_to, priced_class, price_per_share)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            claim_id,
            version_id,
            draft.holding_id,
            draft.claim_key,
            draft.source_class.value,
            draft.execution_status.value,
            draft.issued_date,
            draft.as_of_date,
            draft.received_date,
            draft.applicable_from,
            draft.applicable_to,
            draft.priced_class,
            draft.price_per_share,
        ),
    )
    for fact in draft.facts:
        conn.execute(
            "insert into extracted_fact (claim_id, field_name, value_text, value_numeric,"
            " citation_quote, span_start, span_end) values (%s, %s, %s, %s, %s, %s, %s)",
            (
                claim_id,
                fact.field_name,
                fact.value_text,
                fact.value_numeric,
                fact.citation.quote,
                fact.citation.span_start,
                fact.citation.span_end,
            ),
        )
    return claim_id
