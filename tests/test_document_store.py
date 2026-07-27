"""The write path: what reaches the database, and what is refused on the way.

Database-gated but **not** corpus-gated. The documents are private and CI does
not have them; the database is real in CI, so every guard on the write path is
exercised there on synthetic documents this file creates. `mutate.py --ci` hides
the corpus and runs exactly this configuration, which is what makes these guards
provable rather than merely present.

`test_document_end_to_end.py` covers the same path with the real Dream cap
table and skips without it. That test proves the wiring; these prove the rules.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from ingest.documents.claims import (
    ClaimDraft,
    FactDraft,
    cited_fact,
    store_claim,
    store_document,
)
from ingest.documents.parse import ParsedDocument, parse
from packages.contracts.citations import CitationError, locate
from packages.contracts.enums import ExecutionStatus, SourceClass
from tests.schema_helpers import DSN, Conn

pytestmark = pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")

BODY = (
    "ACME, INC.\n"
    "Series B Preferred Stock issued at $8.00 per share.\n"
    "    7GC Fund II, L.P.        625,000     $3.20      3.29%\n"
)


#: The holder row, exactly as it appears in the canonical text.
ROW = BODY.splitlines()[2].strip()


def _doc(tmp_path: Path, body: str = BODY, name: str = "acme.txt") -> ParsedDocument:
    source = tmp_path / name
    source.write_bytes(body.encode("utf-8"))
    return parse(source)


def _draft(holding_id: str, facts: tuple[FactDraft, ...] = ()) -> ClaimDraft:
    return ClaimDraft(
        claim_key="series_b",
        holding_id=holding_id,
        source_class=SourceClass.COMPANY_CAP_TABLE,
        execution_status=ExecutionStatus.PRO_FORMA,
        issued_date=date(2025, 11, 14),
        applicable_from=date(2025, 11, 14),
        priced_class="series_b",
        # 0009 refuses a claim whose price no fact on it states, so the price is
        # set only when a fact states it. These drafts mostly carry a share
        # count, so most of them state no price at all.
        #
        # The two field names here are `fund_shares` and `round_price_per_share`
        # rather than anything convenient because `store_claim` now refuses a
        # figure whose relevance to the client's requests is undeclared, and a
        # synthetic document inventing a field name is exactly the case that
        # guard exists to catch.
        price_per_share=next(
            (f.value_numeric for f in facts if f.field_name == "round_price_per_share"), None
        ),
        facts=facts,
    )


# ── Storing a document ───────────────────────────────────────────────────
def test_the_same_bytes_store_once(conn: Conn, tmp_path: Path) -> None:
    """SPEC §10 · content-addressed versions; duplicate upload is idempotent."""
    doc = _doc(tmp_path)
    assert store_document(conn, doc) == store_document(conn, doc)
    row = conn.execute(
        "select count(*) from document_version where text_hash = %s", (doc.text_hash,)
    ).fetchone()
    assert row is not None
    assert row[0] == 1
    conn.rollback()


def test_the_stored_text_is_the_text_the_spans_were_computed_against(
    conn: Conn, tmp_path: Path
) -> None:
    """A round trip through Postgres, because a column that normalised newlines
    or a driver that decoded differently would shift every offset with no error
    anywhere. The text is the only thing a citation means anything relative to."""
    doc = _doc(tmp_path, "line one\r\nline two\r\n\f")
    version_id = store_document(conn, doc)
    row = conn.execute(
        "select canonical_text, page_count from document_version where id = %s", (version_id,)
    ).fetchone()
    assert row is not None
    assert row[0] == doc.canonical_text
    assert "\r\n" in row[0]
    assert row[1] == doc.page_count == 1
    conn.rollback()


def test_a_version_id_already_holding_different_content_is_refused(
    conn: Conn, tmp_path: Path
) -> None:
    """A bare `on conflict do nothing` makes a collision, a truncated column or a
    half-applied migration look like a successful re-ingest — and every span
    already recorded against that version then points into text nobody checked.
    Idempotent means *checked*, not skipped.

    The colliding row is planted by insert rather than by updating a stored one:
    `document_version` is append-only, so an UPDATE is refused before this guard
    could ever be reached. That refusal is a different rule, and a test that
    tripped over it would prove that rule twice and this one not at all.
    """
    doc = _doc(tmp_path)
    conn.execute(
        "insert into source_file (id, filename, content_hash, byte_size, bytes)"
        " values (%s, %s, %s, %s, %s) on conflict (content_hash) do nothing",
        (f"sf_{doc.content_hash[:24]}", doc.filename, doc.content_hash, doc.byte_size, b""),
    )
    conn.execute(
        "insert into document_version"
        " (id, source_file_id, canonical_text, extractor, text_hash, page_count)"
        " values (%s, %s, 'something else entirely', %s, %s, 1)",
        (
            f"dv_{doc.text_hash[:24]}",
            f"sf_{doc.content_hash[:24]}",
            doc.extractor,
            doc.text_hash,
        ),
    )
    with pytest.raises(CitationError, match="collision, not a re-ingest"):
        store_document(conn, doc)
    conn.rollback()


# ── Producing a fact ─────────────────────────────────────────────────────
def test_a_fact_is_produced_from_a_pattern_with_its_value_inside_its_quote(
    conn: Conn, tmp_path: Path
) -> None:
    doc = _doc(tmp_path)
    fact = cited_fact(
        document_version_id="dv",
        canonical_text=doc.canonical_text,
        field_name="fund_shares",
        pattern=re.compile(r"7GC Fund II, L\.P\.\s+(?P<value>[\d,]+)"),
    )
    assert fact.value_text == "625,000"
    assert fact.value_numeric == Decimal("625000")
    assert fact.value_text in fact.citation.quote
    assert doc.canonical_text[fact.citation.span_start : fact.citation.span_end] == (
        fact.citation.quote
    )


def test_a_value_captured_outside_its_own_match_is_refused(tmp_path: Path) -> None:
    """A lookahead group captures text the match does not cover, so the value is
    not part of the passage cited for it. Narrow, and the only shape in which a
    named group can escape its own quote — which is why the check exists rather
    than being assumed unreachable."""
    doc = _doc(tmp_path)
    with pytest.raises(CitationError, match="not inside the passage cited"):
        cited_fact(
            document_version_id="dv",
            canonical_text=doc.canonical_text,
            field_name="fund_shares",
            pattern=re.compile(r"7GC Fund II, L\.P\.(?=\s+(?P<value>[\d,]+))"),
        )


def test_text_that_states_no_figure_carries_no_number(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "Closing Date: November\n14, 2025\n")
    fact = cited_fact(
        document_version_id="dv",
        canonical_text=doc.canonical_text,
        field_name="closing_date",
        pattern=re.compile(r"Closing Date: (?P<value>November\s+\d+, \d{4})"),
    )
    assert fact.value_text == "November\n14, 2025"
    assert fact.value_numeric is None


# ── Storing a claim ──────────────────────────────────────────────────────
def test_a_claim_and_its_facts_store_together(
    conn: Conn, seed: dict[str, str], tmp_path: Path
) -> None:
    doc = _doc(tmp_path)
    version_id = store_document(conn, doc)
    fact = cited_fact(
        document_version_id=version_id,
        canonical_text=doc.canonical_text,
        field_name="fund_shares",
        pattern=re.compile(r"7GC Fund II, L\.P\.\s+(?P<value>[\d,]+)"),
    )
    claim_id = store_claim(conn, version_id, _draft(seed["h"], (fact,)), doc.canonical_text)
    row = conn.execute(
        "select value_text, value_numeric from extracted_fact where claim_id = %s",
        (claim_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "625,000"
    assert row[1] == Decimal("625000")
    conn.rollback()


def test_a_fact_cited_into_a_different_document_is_refused(
    conn: Conn, seed: dict[str, str], tmp_path: Path
) -> None:
    """The span would be checked by the trigger against text the extractor never
    read — and could resolve there by coincidence."""
    doc = _doc(tmp_path)
    version_id = store_document(conn, doc)
    fact = cited_fact(
        document_version_id="dv_elsewhere",
        canonical_text=doc.canonical_text,
        field_name="fund_shares",
        pattern=re.compile(r"7GC Fund II, L\.P\.\s+(?P<value>[\d,]+)"),
    )
    with pytest.raises(CitationError, match="but is being stored against"):
        store_claim(conn, version_id, _draft(seed["h"], (fact,)), doc.canonical_text)
    conn.rollback()


def test_the_writer_refuses_a_citation_that_does_not_resolve(
    conn: Conn, seed: dict[str, str], tmp_path: Path
) -> None:
    """The writer checks before inserting so the diagnostic can name the field;
    the trigger checks regardless because the writer can be bypassed. Both
    sides, because every recurring defect here was a rule enforced on one."""
    doc = _doc(tmp_path)
    version_id = store_document(conn, doc)
    fact = cited_fact(
        document_version_id=version_id,
        canonical_text=doc.canonical_text,
        field_name="fund_shares",
        pattern=re.compile(r"7GC Fund II, L\.P\.\s+(?P<value>[\d,]+)"),
    )
    with pytest.raises(CitationError, match="does not resolve"):
        store_claim(conn, version_id, _draft(seed["h"], (fact,)), "a completely different text")
    conn.rollback()


def test_nothing_is_stored_when_one_fact_of_several_fails(
    conn: Conn, seed: dict[str, str], tmp_path: Path
) -> None:
    """Every citation is checked before the first insert, so a claim is written
    whole or not at all. Checking as it goes would leave a claim carrying the
    facts that happened to come first."""
    doc = _doc(tmp_path)
    version_id = store_document(conn, doc)
    good = cited_fact(
        document_version_id=version_id,
        canonical_text=doc.canonical_text,
        field_name="fund_shares",
        pattern=re.compile(r"7GC Fund II, L\.P\.\s+(?P<value>[\d,]+)"),
    )
    bad = cited_fact(
        document_version_id="dv_elsewhere",
        canonical_text=doc.canonical_text,
        field_name="round_price_per_share",
        pattern=re.compile(r"issued at (?P<value>\$[\d.]+)"),
    )
    with pytest.raises(CitationError):
        store_claim(conn, version_id, _draft(seed["h"], (good, bad)), doc.canonical_text)
    row = conn.execute(
        "select count(*) from claim where holding_id = %s and claim_key = 'series_b'",
        (seed["h"],),
    ).fetchone()
    assert row is not None
    assert row[0] == 0
    conn.rollback()


def test_a_claim_records_the_class_it_prices_not_the_class_held(
    conn: Conn, seed: dict[str, str], tmp_path: Path
) -> None:
    """INV-17 · pricing one class off another's evidence is a policy act that
    must be cited. The database's cross-class trigger can only fire if this
    field says which class the price belongs to."""
    doc = _doc(tmp_path)
    version_id = store_document(conn, doc)
    # The price has to be a figure the document states, so the claim brings the
    # fact that states it — 0009 refuses a price no citation supports.
    price = cited_fact(
        document_version_id=version_id,
        canonical_text=doc.canonical_text,
        field_name="round_price_per_share",
        pattern=re.compile(r"issued at (?P<value>\$[\d.]+) per share"),
    )
    claim_id = store_claim(conn, version_id, _draft(seed["h"], (price,)), doc.canonical_text)
    row = conn.execute(
        "select priced_class, price_per_share from claim where id = %s", (claim_id,)
    ).fetchone()
    assert row is not None
    assert row[0] == "series_b"
    assert row[1] == Decimal("8.00")
    conn.rollback()


def test_the_trigger_still_refuses_a_fact_written_around_the_writer(
    conn: Conn, seed: dict[str, str], tmp_path: Path
) -> None:
    doc = _doc(tmp_path)
    version_id = store_document(conn, doc)
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


def test_the_writer_refuses_a_value_that_is_a_fragment_of_a_longer_figure(
    conn: Conn, seed: dict[str, str], tmp_path: Path
) -> None:
    """`cited_fact` cannot produce this, but a hand-built `FactDraft` can — and
    that is the path a cross-family review took to store `value_text="625"`
    against a row stating 625,000, with all three bindings satisfied.

    The writer has to refuse it too, not only the trigger. The trigger is the
    side that cannot be bypassed; the writer is the side that can name the field.
    """
    doc = _doc(tmp_path)
    version_id = store_document(conn, doc)
    citation = locate(document_version_id=version_id, canonical_text=doc.canonical_text, quote=ROW)
    fragment = FactDraft(
        field_name="fund_shares",
        value_text="625",
        citation=citation,
        value_numeric=Decimal("625"),
    )
    with pytest.raises(CitationError, match="in its own right"):
        store_claim(conn, version_id, _draft(seed["h"], (fragment,)), doc.canonical_text)
    conn.rollback()


def test_the_writer_refuses_a_number_the_cited_text_does_not_state(
    conn: Conn, seed: dict[str, str], tmp_path: Path
) -> None:
    """The text says 625,000 and the number beside it says 625. Every citation
    resolves; the ledger is wrong by three orders of magnitude."""
    doc = _doc(tmp_path)
    version_id = store_document(conn, doc)
    citation = locate(document_version_id=version_id, canonical_text=doc.canonical_text, quote=ROW)
    mismatched = FactDraft(
        field_name="fund_shares",
        value_text="625,000",
        citation=citation,
        value_numeric=Decimal("625"),
    )
    with pytest.raises(CitationError, match="is not the figure"):
        store_claim(conn, version_id, _draft(seed["h"], (mismatched,)), doc.canonical_text)
    conn.rollback()


def test_the_writer_refuses_figure_shaped_text_carrying_no_number(
    conn: Conn, seed: dict[str, str], tmp_path: Path
) -> None:
    """The equality has two sides. NULL short-circuiting it let a cited `$8.00`
    be stored as a fact that states no figure at all."""
    doc = _doc(tmp_path)
    version_id = store_document(conn, doc)
    citation = locate(document_version_id=version_id, canonical_text=doc.canonical_text, quote=ROW)
    numberless = FactDraft(
        field_name="fund_shares", value_text="625,000", citation=citation, value_numeric=None
    )
    with pytest.raises(CitationError, match="is not the figure"):
        store_claim(conn, version_id, _draft(seed["h"], (numberless,)), doc.canonical_text)
    conn.rollback()


def test_the_writer_refuses_a_claim_price_no_fact_states(
    conn: Conn, seed: dict[str, str], tmp_path: Path
) -> None:
    """The shape two independent cross-family reviews found on the same day,
    from opposite ends — one reading the extractors, one reading the write path.

    Every citation resolves and every fact is bound; the claim beside them says
    eight hundred, and the API renders 800 next to a passage reading $8.00. The
    claim's own figures are numbers stored beside the citations rather than
    through them, and until this check nothing compared the two. The deferred
    trigger in 0009 refuses it at commit; this refuses it at the field, where the
    error can say which one.
    """
    doc = _doc(tmp_path)
    version_id = store_document(conn, doc)
    price = cited_fact(
        document_version_id=version_id,
        canonical_text=doc.canonical_text,
        field_name="round_price_per_share",
        pattern=re.compile(r"issued at (?P<value>\$[\d.]+) per share"),
    )
    assert price.value_numeric == Decimal("8.00")
    mispriced = ClaimDraft(
        claim_key="series_b",
        holding_id=seed["h"],
        source_class=SourceClass.COMPANY_CAP_TABLE,
        execution_status=ExecutionStatus.PRO_FORMA,
        issued_date=date(2025, 11, 14),
        applicable_from=date(2025, 11, 14),
        priced_class="series_b",
        price_per_share=Decimal("800"),
        facts=(price,),
    )
    with pytest.raises(CitationError, match="which no fact cited on it states"):
        store_claim(conn, version_id, mispriced, doc.canonical_text)
    conn.rollback()
