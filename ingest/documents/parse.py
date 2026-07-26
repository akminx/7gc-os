"""Turn a source file into the exact text every citation resolves against.

SPEC §8 · citations resolve against "the persisted UTF-8 output of one pinned
`pdftotext -layout` version, with zero-based half-open Unicode code-point
offsets, no post-extraction normalisation, and a hash over both the canonical
text and the extractor version."

Every clause of that sentence is load-bearing, and three of them are load-bearing
against Python's own defaults:

* **No post-extraction normalisation.** `Path.read_text()` and
  `subprocess.run(text=True)` both apply universal-newline translation, which
  rewrites `\\r\\n` to `\\n` *after* the extractor produced the bytes. That is a
  normalisation, and it silently shifts every offset after the first CRLF. Both
  paths here decode from `bytes` for exactly that reason.
* **Code points, not bytes or UTF-16 units.** Python `str` indices and Postgres
  `substring()` on `text` both count code points, including astral-plane
  characters as one. That agreement is what lets the same span mean the same
  thing in `citations.py` and in the database trigger; it would not hold for a
  JavaScript producer, so spans are never computed in `web/**`.
* **A hash over both.** The extractor identity is hashed *with* the text, so a
  different poppler produces a different `text_hash` and therefore a different
  `document_version` row. Citations bind to a version id, so a re-extraction can
  never silently invalidate spans that already resolved — it creates a new
  version beside the old one instead of corrupting it.

The corpus is 16 born-digital PDFs plus five `.txt` files. No OCR, no hosted
parser; the trigger for either is a scanned document entering the corpus.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: The version this corpus's spans were computed against. `parse()` records
#: whatever it actually ran rather than asserting this, because recording
#: reality is what makes a mismatch visible; `tests/test_document_parse.py`
#: asserts the pin and goes red on a poppler upgrade. Asserting it here would
#: make the library unusable on any other machine while proving nothing extra —
#: the text hash already separates the outputs.
PINNED_PDFTOTEXT = "26.03.0"

#: Flags are part of the extractor's identity, not incidental invocation detail.
#: `-layout` preserves column structure, which is what makes a cap-table row
#: quotable; `-enc UTF-8` and `-eol unix` pin the two things that would
#: otherwise vary by platform and shift every offset downstream.
_PDFTOTEXT_FLAGS = ("-layout", "-enc", "UTF-8", "-eol", "unix")

#: pdftotext emits this after every page, including the last.
_PAGE_BREAK = "\f"

_VERSION_LINE = re.compile(r"pdftotext version ([0-9][0-9.]*)")


class ExtractionFailed(RuntimeError):
    """The parser did not produce usable text. SPEC §9 · fail closed.

    A parser non-zero exit and an empty extraction are separate typed failures
    there, and neither may create a canonical fact (INV-14). Returning `""` for
    either would do exactly that: an empty canonical text accepts any citation
    span of zero length and reports a document with no evidence in it as
    successfully parsed.
    """


@dataclass(frozen=True)
class Page:
    """One page's half-open extent within the canonical text.

    Pages are a *view* over the canonical text, never a separate copy of it.
    Storing page text independently would give a citation two texts it could
    resolve against, and nothing would keep them equal.
    """

    number: int
    span_start: int
    span_end: int

    def contains(self, offset: int) -> bool:
        return self.span_start <= offset < self.span_end


@dataclass(frozen=True)
class ParsedDocument:
    """A source file and the single text its citations resolve against."""

    filename: str
    #: The source bytes as delivered. `source_file.bytes` is what lets an
    #: auditor packet reproduce the document a citation points into, so the
    #: bytes travel with the text they produced rather than being re-read from
    #: a path later — a path can change underneath a stored hash, and then
    #: `byte_size` and `content_hash` describe a file nobody still has.
    source_bytes: bytes
    content_hash: str
    byte_size: int
    canonical_text: str
    extractor: str
    text_hash: str
    pages: tuple[Page, ...]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def page_of(self, offset: int) -> int:
        """The 1-based page containing this offset.

        Raises rather than clamping. A span that runs past the end of the text
        is a defect in whatever produced it, and attributing it to the last page
        would hand an auditor a page number that does not contain the quote —
        which is worse than no page number, because it looks checkable.
        """
        for page in self.pages:
            if page.contains(offset):
                return page.number
        raise ValueError(
            f"offset {offset} lies outside every page of {self.filename} "
            f"(text is {len(self.canonical_text)} code points, {self.page_count} pages)"
        )


def content_hash(data: bytes) -> str:
    """The identity of the bytes as delivered. SPEC §10 · content-addressed."""
    return hashlib.sha256(data).hexdigest()


def text_hash(extractor: str, canonical_text: str) -> str:
    """A hash over the extractor identity *and* the text it produced.

    The NUL separator is not decoration. Concatenating the two directly makes
    `("pdftotext-layout@1", "0text")` and `("pdftotext-layout@10", "text")` hash
    identically, so two different extractions could collide on the
    `(source_file_id, text_hash)` unique key and the second would be rejected as
    a duplicate of a text it does not match. NUL cannot appear in either input —
    Postgres refuses it in `text` — so it is an unambiguous boundary.
    """
    digest = hashlib.sha256()
    digest.update(extractor.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(canonical_text.encode("utf-8"))
    return digest.hexdigest()


def split_pages(canonical_text: str) -> tuple[Page, ...]:
    """Page extents, derived from the form feeds the extractor emitted.

    pdftotext writes a form feed *after* every page, so a well-formed extraction
    ends with one. The naive `text.split("\\f")` therefore reports one page too
    many for every document in the corpus — a trailing empty segment that is not
    a page. Counting the breaks and keeping any tail after the last one gets
    both shapes right: a `.txt` file with no break at all is one page, and a
    genuinely blank final page (two adjacent breaks) is still counted, because
    the extractor saw a page there.
    """
    pages: list[Page] = []
    start = 0
    for index, char in enumerate(canonical_text):
        if char == _PAGE_BREAK:
            pages.append(Page(len(pages) + 1, start, index))
            start = index + 1
    if start < len(canonical_text):
        pages.append(Page(len(pages) + 1, start, len(canonical_text)))
    return tuple(pages)


def pdftotext_version() -> str:
    """The version of the extractor actually on this machine.

    poppler prints its banner on stderr, so reading stdout alone returns the
    empty string and the version silently becomes "unknown" — an extractor
    identity that no longer distinguishes anything.
    """
    result = subprocess.run(
        ["pdftotext", "-v"],
        capture_output=True,
        check=False,
    )
    banner = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    match = _VERSION_LINE.search(banner)
    if match is None:
        raise ExtractionFailed(
            "could not read a version out of `pdftotext -v`; the extractor "
            f"identity would be unpinned. Banner was: {banner.strip()!r}"
        )
    return match.group(1)


def _pdf_text(path: Path) -> tuple[str, str]:
    version = pdftotext_version()
    result = subprocess.run(
        ["pdftotext", *_PDFTOTEXT_FLAGS, str(path), "-"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ExtractionFailed(
            f"pdftotext exited {result.returncode} on {path.name}: "
            f"{result.stderr.decode('utf-8', errors='replace').strip()}"
        )
    # Decoded here, not by `text=True`, so no universal-newline translation runs
    # between the extractor and the offsets computed from its output.
    return result.stdout.decode("utf-8"), f"pdftotext {' '.join(_PDFTOTEXT_FLAGS)}@{version}"


def _plain_text(raw: bytes) -> tuple[str, str]:
    return raw.decode("utf-8"), "utf8-verbatim@1"


def parse(path: Path) -> ParsedDocument:
    """Read one source file into the text its citations will resolve against."""
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        canonical_text, extractor = _pdf_text(path)
    elif suffix == ".txt":
        canonical_text, extractor = _plain_text(raw)
    else:
        raise ExtractionFailed(
            f"{path.name}: no pinned extractor for {suffix!r}. Adding one is a "
            "deliberate act — it changes what a citation resolves against."
        )

    if not canonical_text.strip():
        raise ExtractionFailed(
            f"{path.name} extracted to whitespace only. An empty canonical text "
            "accepts citations that resolve to nothing, so this fails closed."
        )

    return ParsedDocument(
        filename=path.name,
        source_bytes=raw,
        content_hash=content_hash(raw),
        byte_size=len(raw),
        canonical_text=canonical_text,
        extractor=extractor,
        text_hash=text_hash(extractor, canonical_text),
        pages=split_pages(canonical_text),
    )
