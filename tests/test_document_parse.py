"""The parse layer: what a citation resolves against, and how it is identified.

Almost everything here runs without the corpus, on synthetic text written into
`tmp_path`. That is deliberate. The last thing this project learned was that "a
guard that skips because the workbooks are private has not failed" — so the
rules that must hold are proved on text this file creates, and only the two
tests that genuinely need a real PDF are gated on the corpus being present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.documents.parse import (
    PINNED_PDFTOTEXT,
    ExtractionFailed,
    ParsedDocument,
    content_hash,
    parse,
    pdftotext_version,
    split_pages,
    text_hash,
)

DREAM_PDF = Path(
    "7GC Audit Case Study/02_Portfolio Documentation/Dream/"
    "Dream - Series B - Pro Forma Capitalization Table (November 14, 2025).pdf"
)
needs_corpus = pytest.mark.skipif(
    not DREAM_PDF.exists(), reason="case-study documents are not in the repository"
)


# ── Page splitting ───────────────────────────────────────────────────────
def test_a_trailing_form_feed_is_not_an_extra_page() -> None:
    """pdftotext writes a form feed AFTER every page, so every well-formed
    extraction ends with one and `text.split("\\f")` reports one page too many
    for every document in the corpus. A page count that is always wrong by one
    is the kind of defect that survives review, because it is never absurd."""
    assert len(split_pages("only page\f")) == 1
    assert len(split_pages("one\ftwo\f")) == 2


def test_a_file_with_no_form_feed_is_one_page() -> None:
    """The five `.txt` sources in the corpus contain no form feeds at all."""
    pages = split_pages("an email with no page breaks")
    assert len(pages) == 1
    assert (pages[0].span_start, pages[0].span_end) == (0, 28)


def test_a_blank_final_page_still_counts() -> None:
    """Two adjacent form feeds mean the extractor saw a page and found nothing
    on it. Dropping it would renumber every page after it."""
    pages = split_pages("one\f\fthree\f")
    assert len(pages) == 3
    assert pages[1].span_start == pages[1].span_end


def test_a_page_without_a_closing_form_feed_is_still_a_page() -> None:
    """Truncated output must not lose its last page silently."""
    assert len(split_pages("one\ftwo")) == 2


def test_page_extents_do_not_include_the_break_and_do_not_overlap() -> None:
    pages = split_pages("abc\fde\f")
    assert [(p.number, p.span_start, p.span_end) for p in pages] == [(1, 0, 3), (2, 4, 6)]


# ── Offsets to pages ─────────────────────────────────────────────────────
def test_an_offset_past_the_end_is_refused_not_clamped(tmp_path: Path) -> None:
    """Attributing an out-of-range span to the last page hands an auditor a page
    number that does not contain the quote — worse than no page number, because
    it looks checkable."""
    doc = _txt(tmp_path, "page one\fpage two\f")
    assert doc.page_of(0) == 1
    assert doc.page_of(9) == 2
    with pytest.raises(ValueError, match="outside every page"):
        doc.page_of(99)


def test_the_break_itself_belongs_to_no_page(tmp_path: Path) -> None:
    doc = _txt(tmp_path, "page one\fpage two\f")
    with pytest.raises(ValueError, match="outside every page"):
        doc.page_of(8)


# ── Identity ─────────────────────────────────────────────────────────────
def test_the_extractor_is_hashed_with_the_text_not_beside_it() -> None:
    """Concatenating the two without a separator makes ("ab", "cd") and
    ("abc", "d") the same hash, so two different extractions collide on the
    `(source_file_id, text_hash)` unique key and the second is rejected as a
    duplicate of a text it does not match."""
    assert text_hash("ab", "cd") != text_hash("abc", "d")


def test_a_different_extractor_gives_the_same_text_a_different_identity() -> None:
    """Spans are extractor-bound. A re-extraction under a different poppler must
    create a new document_version beside the old one, never silently take its
    place — the citations already recorded resolve into the old text."""
    assert text_hash("pdftotext@25", "same") != text_hash("pdftotext@26", "same")


def test_content_hash_is_over_the_bytes_as_delivered() -> None:
    assert content_hash(b"") != content_hash(b"\n")


# ── No post-extraction normalisation ─────────────────────────────────────
def test_crlf_survives_into_the_canonical_text(tmp_path: Path) -> None:
    """`Path.read_text()` and `subprocess.run(text=True)` both apply
    universal-newline translation, which rewrites CRLF to LF *after* the
    extractor produced the bytes. That is a normalisation SPEC §8 forbids, and
    it shifts every offset after the first CRLF — so a span computed here would
    land one character early in a database that stored the untranslated text.

    This is the whole reason both paths in `parse.py` decode from `bytes`.
    """
    source = tmp_path / "email.txt"
    source.write_bytes(b"line one\r\nline two\r\n")
    doc = parse(source)

    assert "\r\n" in doc.canonical_text
    assert len(doc.canonical_text) == 20
    assert doc.canonical_text.index("line two") == 10


def test_astral_characters_count_as_one_code_point(tmp_path: Path) -> None:
    """Python str indices and Postgres `substring` on `text` both count code
    points, and agreeing on that is what lets one span mean the same thing on
    both sides. A UTF-16 producer would count the emoji as two."""
    doc = _txt(tmp_path, "a\U0001f600b")
    assert len(doc.canonical_text) == 3
    assert doc.canonical_text[2:3] == "b"


# ── Failing closed ───────────────────────────────────────────────────────
def test_whitespace_only_extraction_is_refused(tmp_path: Path) -> None:
    """An empty canonical text accepts citations that resolve to nothing, and
    reports a document with no evidence in it as successfully parsed. SPEC §9 ·
    empty extraction is a typed failure, and no failed result creates a
    canonical fact."""
    source = tmp_path / "blank.txt"
    source.write_bytes(b"   \n\n  ")
    with pytest.raises(ExtractionFailed, match="whitespace only"):
        parse(source)


def test_an_unpinned_file_type_is_refused(tmp_path: Path) -> None:
    """Adding an extractor changes what a citation resolves against, so it is a
    deliberate act rather than a fallback."""
    source = tmp_path / "sheet.xlsx"
    source.write_bytes(b"PK\x03\x04")
    with pytest.raises(ExtractionFailed, match="no pinned extractor"):
        parse(source)


# ── The real document ────────────────────────────────────────────────────
@needs_corpus
def test_the_pinned_extractor_is_the_one_installed() -> None:
    """Goes red on a poppler upgrade. Every span committed against this corpus
    was computed under this version, and a silent change would move them all."""
    assert pdftotext_version() == PINNED_PDFTOTEXT


@needs_corpus
def test_dream_parses_to_one_page_of_known_text() -> None:
    doc = parse(DREAM_PDF)
    assert doc.page_count == 1
    assert doc.extractor == f"pdftotext -layout -enc UTF-8 -eol unix@{PINNED_PDFTOTEXT}"
    assert doc.byte_size == len(doc.source_bytes)
    assert doc.content_hash == content_hash(doc.source_bytes)
    assert doc.text_hash == text_hash(doc.extractor, doc.canonical_text)
    assert "7GC Fund II, L.P." in doc.canonical_text
    assert doc.page_of(doc.canonical_text.index("7GC Fund II, L.P.")) == 1


def _txt(tmp_path: Path, body: str) -> ParsedDocument:
    source = tmp_path / "doc.txt"
    source.write_bytes(body.encode("utf-8"))
    return parse(source)
