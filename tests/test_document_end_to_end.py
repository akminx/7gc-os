"""One real document, all the way through. Step 2's spine.

Parse the Dream cap table, hash it, split its pages, write a claim and its cited
facts to the database, then read every fact back and re-resolve its citation
against the text Postgres actually stored.

The round trip is the point. Each layer can be right on its own and the chain
still broken: a span computed on Python's code points, stored in a column that
normalises newlines, and re-read through a driver that decodes differently gives
three plausible answers and no error. Re-resolving from the database is the only
check that spans all three.

Corpus- and database-gated, so it skips in CI. That is why the rules it depends
on — page splitting, offsets, the numeral parser, every refusal in
`0008_citations_resolve.sql` — are proved on synthetic text in
`test_document_parse.py` and `test_citations.py`, which do not skip. A guard
that only runs where the private material lives has not been proved.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import psycopg
import pytest

from ingest.documents.claims import store_claim, store_document
from ingest.documents.extract_dream import HELD_CLASS, PRICED_CLASS, dream_claim
from ingest.documents.parse import parse
from packages.contracts.citations import resolves_in
from packages.contracts.enums import ExecutionStatus, SourceClass
from packages.contracts.models import Citation
from tests.schema_helpers import DSN, Conn
from tests.test_document_parse import DREAM_PDF

pytestmark = [
    pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set"),
    pytest.mark.skipif(
        not DREAM_PDF.exists(), reason="case-study documents are not in the repository"
    ),
]

#: What the document states, transcribed by hand from the PDF. Hand-transcribed
#: source facts only — the same rule `evals/oracle/primitives.yaml` follows. If
#: these were read out of the extractor they would agree with it by
#: construction and prove nothing.
EXPECTED: dict[str, tuple[str, str | None]] = {
    "fund_shares": ("625,000", "625000"),
    "fund_entry_price_per_share": ("$3.20", "3.20"),
    "series_b_price_per_share": ("$8.00", "8.00"),
    "post_money_valuation": ("$800,000,000", "800000000"),
    "fully_diluted_shares": ("100,000,000", "100000000"),
    # The date wraps a line in the source, so its quoted form contains a
    # newline and `cited_numeral` reads no figure from it.
    "closing_date": ("November\n14, 2025", None),
}


def test_dream_goes_from_pdf_to_cited_facts_that_resolve(conn: Conn, seed: dict[str, str]) -> None:
    parsed = parse(DREAM_PDF)
    version_id = store_document(conn, parsed)
    draft = dream_claim(document_version_id=version_id, parsed=parsed, holding_id=seed["h"])
    claim_id = store_claim(conn, version_id, draft, parsed.canonical_text)

    stored_text = _stored_text(conn, version_id)
    assert stored_text == parsed.canonical_text, (
        "the text Postgres stored is not the text the spans were computed against"
    )

    rows = conn.execute(
        "select field_name, value_text, value_numeric, citation_quote, span_start, span_end"
        " from extracted_fact where claim_id = %s order by field_name",
        (claim_id,),
    ).fetchall()
    assert len(rows) == len(EXPECTED)

    for row in rows:
        field_name, value_text, value_numeric, quote, start, end = _fact(row)
        want_text, want_number = EXPECTED[field_name]
        assert value_text == want_text, field_name
        assert value_numeric == (None if want_number is None else Decimal(want_number)), field_name

        # Re-resolved from what the database holds, not from what Python built.
        citation = Citation(
            document_version_id=version_id, quote=quote, span_start=start, span_end=end
        )
        assert resolves_in(citation, stored_text), field_name
        assert value_text in quote, field_name

    conn.rollback()


def test_the_stored_claim_prices_a_class_the_holding_does_not_hold(
    conn: Conn, seed: dict[str, str]
) -> None:
    """INV-17, and the reason Dream is the document worth doing first.

    7GC holds Series A-1; this table establishes the Series B price. Recording
    `priced_class` as the class held would be the cheapest possible collapse —
    one word, no error — and it would let the mark be approved at $8.00 with no
    cited cross-class policy decision. The database's cross-class trigger only
    fires because this field says `series_b`.
    """
    parsed = parse(DREAM_PDF)
    version_id = store_document(conn, parsed)
    draft = dream_claim(document_version_id=version_id, parsed=parsed, holding_id=seed["h"])
    claim_id = store_claim(conn, version_id, draft, parsed.canonical_text)

    row = conn.execute(
        "select source_class, execution_status, priced_class, price_per_share, issued_date"
        " from claim where id = %s",
        (claim_id,),
    ).fetchone()
    assert row is not None
    source_class, execution_status, priced_class, price_per_share, issued = row

    assert priced_class == PRICED_CLASS != HELD_CLASS
    assert price_per_share == Decimal("8.00")
    # §6.2.2 · execution_status describes the artifact in the Fund's possession,
    # not the state of the transaction. The round closed; what the Fund holds is
    # a pro forma table, and that is the question the audit letter asks.
    assert execution_status == ExecutionStatus.PRO_FORMA.value
    assert source_class == SourceClass.COMPANY_CAP_TABLE.value
    assert issued == date(2025, 11, 14)

    conn.rollback()


def test_re_ingesting_the_same_document_is_idempotent(conn: Conn, seed: dict[str, str]) -> None:
    """SPEC §10 · content-addressed versions, duplicate upload is idempotent."""
    parsed = parse(DREAM_PDF)
    assert store_document(conn, parsed) == store_document(conn, parsed)
    row = conn.execute(
        "select count(*) from source_file where content_hash = %s", (parsed.content_hash,)
    ).fetchone()
    assert row is not None
    assert row[0] == 1
    conn.rollback()


def test_the_writer_refuses_a_fact_cited_into_a_different_document(
    conn: Conn, seed: dict[str, str]
) -> None:
    """A citation carries the version it resolves against. Storing it beside a
    different one would produce a row whose span means nothing — and the
    trigger, which reads the text through the claim, would check it against
    text the extractor never saw."""
    from packages.contracts.citations import CitationError

    parsed = parse(DREAM_PDF)
    version_id = store_document(conn, parsed)
    draft = dream_claim(
        document_version_id="dv_somewhere_else", parsed=parsed, holding_id=seed["h"]
    )
    with pytest.raises(CitationError, match="but is being stored against"):
        store_claim(conn, version_id, draft, parsed.canonical_text)
    conn.rollback()


def test_the_trigger_refuses_the_same_fact_written_around_the_writer(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The writer verifies before inserting; the database verifies regardless.
    Both, because every recurring defect in this project was a rule enforced on
    one side only — and the writer is the side that can be bypassed."""
    parsed = parse(DREAM_PDF)
    version_id = store_document(conn, parsed)
    conn.execute(
        "insert into claim (id, document_version_id, holding_id, claim_key, source_class,"
        " execution_status, issued_date, applicable_from)"
        " values (%s, %s, %s, 'k', 'company_cap_table', 'pro_forma', '2025-11-14',"
        " '2025-11-14')",
        (f"{seed['h']}:direct", version_id, seed["h"]),
    )
    with pytest.raises(psycopg.Error, match="does not resolve"):
        conn.execute(
            "insert into extracted_fact (claim_id, field_name, value_text, citation_quote,"
            " span_start, span_end) values (%s, 'fund_shares', '625,000', '625,000', 0, 7)",
            (f"{seed['h']}:direct",),
        )
    conn.rollback()


def _fact(row: tuple[object, ...]) -> tuple[str, str, Decimal | None, str, int, int]:
    """A stored fact row, narrowed to the types the columns declare.

    psycopg hands back `object`, and the alternative to narrowing here is a
    suppression comment — which the gate counts and the ratchet holds at zero,
    because suppressions are how a type check stops checking.
    """
    field_name, value_text, value_numeric, quote, start, end = row
    assert isinstance(field_name, str)
    assert isinstance(value_text, str)
    assert value_numeric is None or isinstance(value_numeric, Decimal)
    assert isinstance(quote, str)
    assert isinstance(start, int)
    assert isinstance(end, int)
    return field_name, value_text, value_numeric, quote, start, end


def _stored_text(conn: Conn, version_id: str) -> str:
    row = conn.execute(
        "select canonical_text from document_version where id = %s", (version_id,)
    ).fetchone()
    assert row is not None
    text = row[0]
    assert isinstance(text, str)
    return text
