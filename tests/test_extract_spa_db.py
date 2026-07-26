"""The SPA family through a live database.

Split from `tests/test_extract_spa.py` at the file-size budget. That file
reads the documents; this one stores what it read and re-resolves every
citation against the text Postgres actually holds.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ingest.documents.claims import store_claim, store_document
from ingest.documents.extract_spa import (
    FLUIDSTACK,
    POOLSIDE,
    ROOFSTOCK,
    SpaDocument,
    spa_claims,
    spa_records_claim,
)
from ingest.documents.parse import parse
from packages.contracts.citations import CitationError, resolves_in
from packages.contracts.models import Citation
from tests.schema_helpers import DSN, Conn
from tests.test_extract_spa import REAL, Transcribed

# ── The synthetic corpus ─────────────────────────────────────────────────
_FUND_II = "7GC Fund II, L.P."
_FUND_I = "7GC Fund I, L.P."

_VALUATION_WITH_SHARE_COUNT = (
    "1.2 Valuation. The purchase price reflects a post-money valuation of "
    "$625,000,000 on a fully diluted basis (25,000,000\n"
    "fully diluted shares).\n\n"
)
#: Fluidstack's shape: a valuation "on a fully diluted basis" and no count of
#: those shares anywhere in the file.
_VALUATION_WITHOUT_SHARE_COUNT = (
    "1.3 Valuation. The Purchase Price reflects a post-money valuation of the "
    "Company of $625,000,000 on a fully diluted\n"
    "basis.\n\n"
)
_CLOSING_REMOTELY = "1.3 Closing. The Closing shall occur remotely on March 4, 2030.\n\n"
_CLOSING_BY_EXCHANGE = (
    "1.2 Closing. The initial closing of the purchase and sale (the “Closing”) "
    "shall take place remotely via electronic exchange\n"
    "of documents and signatures on March 4, 2030, or at such other time as the "
    "Company and the Purchasers agree.\n\n"
)
#: Roofstock's shape: the agreement states no closing date at all.
_NO_CLOSING_CLAUSE = ""


needs_corpus = pytest.mark.skipif(
    not all(spec.path.exists() for spec in (FLUIDSTACK, POOLSIDE, ROOFSTOCK)),
    reason="case-study documents are not in the repository",
)


# ── Through the database ─────────────────────────────────────────────────
@needs_corpus
@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
@pytest.mark.parametrize(("spec", "agreement", "settlement", "records"), REAL)
def test_a_spa_goes_from_pdf_to_stored_claims_whose_citations_resolve(
    conn: Conn,
    seed: dict[str, str],
    spec: SpaDocument,
    agreement: Transcribed,
    settlement: Transcribed,
    records: Transcribed,
) -> None:
    """The round trip. Each layer can be right alone and the chain still broken:
    a span computed on Python code points, stored in a column that normalises
    newlines and read back through a driver that decodes differently gives three
    plausible answers and no error."""
    parsed = parse(spec.path)
    version_id = store_document(conn, parsed)
    for draft in spa_claims(
        document_version_id=version_id, parsed=parsed, spec=spec, holding_id=seed["h"]
    ):
        store_claim(conn, version_id, draft, parsed.canonical_text)
    expected = {**agreement, **settlement, **records}

    stored_text = _stored_text(conn, version_id)
    assert stored_text == parsed.canonical_text

    rows = conn.execute(
        "select f.field_name, f.value_text, f.value_numeric, f.citation_quote,"
        " f.span_start, f.span_end from extracted_fact f"
        " join claim c on c.id = f.claim_id where c.document_version_id = %s",
        (version_id,),
    ).fetchall()
    assert len(rows) == len(expected)

    for row in rows:
        field_name, value_text, value_numeric, quote, start, end = _row(row)
        want_text, want_number = expected[field_name]
        assert value_text == want_text, field_name
        assert value_numeric == (None if want_number is None else Decimal(want_number)), field_name
        # Re-resolved against what Postgres holds, not what Python built.
        citation = Citation(
            document_version_id=version_id, quote=quote, span_start=start, span_end=end
        )
        assert resolves_in(citation, stored_text), field_name

    stored = conn.execute(
        "select claim_key, source_class, execution_status, priced_class, price_per_share"
        " from claim where document_version_id = %s order by claim_key",
        (version_id,),
    ).fetchall()
    # Ordered by claim_key: `fund_records` sorts first. The claim exists only
    # where the document states the sentence, which Fluidstack's does not.
    expected_claims = [f"{spec.priced_class}_price", f"{spec.priced_class}_settlement"]
    expected_classes = ["executed_transaction_doc", "company_communication"]
    expected_status = ["executed", "not_applicable"]
    expected_priced = [spec.priced_class, None]
    # The wire confirmation prices nothing. INV-15 in the stored row.
    expected_prices = [Decimal(agreement["round_price_per_share"][0].lstrip("$")), None]
    if records:
        expected_claims.insert(0, f"{spec.priced_class}_fund_records")
        expected_classes.insert(0, "fund_internal_record")
        expected_status.insert(0, "not_applicable")
        expected_priced.insert(0, None)
        expected_prices.insert(0, None)

    assert [r[0] for r in stored] == expected_claims
    assert [r[1] for r in stored] == expected_classes
    assert [r[2] for r in stored] == expected_status
    assert [r[3] for r in stored] == expected_priced
    assert [r[4] for r in stored] == expected_prices
    conn.rollback()


def _row(row: tuple[object, ...]) -> tuple[str, str, Decimal | None, str, int, int]:
    """psycopg hands back `object`; the alternative to narrowing here is a
    suppression comment, which the gate's ratchet holds at zero."""
    field_name, value_text, value_numeric, quote, start, end = row
    assert isinstance(field_name, str)
    assert isinstance(value_text, str)
    assert value_numeric is None or isinstance(value_numeric, Decimal)
    assert isinstance(quote, str)
    assert isinstance(start, int) and isinstance(end, int)
    return field_name, value_text, value_numeric, quote, start, end


def _stored_text(conn: Conn, version_id: str) -> str:
    row = conn.execute(
        "select canonical_text from document_version where id = %s", (version_id,)
    ).fetchone()
    assert row is not None
    text = row[0]
    assert isinstance(text, str)
    return text


@needs_corpus
def test_a_document_that_states_no_records_note_gets_no_such_claim() -> None:
    """Fluidstack's agreement carries no Fund-records sentence, so it makes no
    claim asserting one. Emitting an empty claim would put "we have no record of
    a later round" in the packet for a document that never said it — which is
    the difference between evidence and its absence, and the one distinction the
    letter's third request turns on."""
    assert FLUIDSTACK.fund_records_note is None
    with pytest.raises(CitationError, match="states no fund-records note"):
        spa_records_claim(
            document_version_id="dv",
            parsed=parse(FLUIDSTACK.path),
            spec=FLUIDSTACK,
            holding_id="h",
        )
