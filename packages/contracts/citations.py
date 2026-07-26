"""Binding a citation to the text it claims to quote. INV-8.

The audit found `Citation` to be a structural shell: `span_end > span_start` was
the only constraint, and nothing tied `quote` to
`canonical_text[span_start:span_end]`. A span of `(0, 1)` beside a quote of
"Series B Preferred Stock issued at $8.00 per share" satisfied every check in
the system. The figure looked cited and resolved to nothing.

It was left open deliberately until something wrote a citation, so the
constraint and its producer could be designed together. They are, here, and the
design is one sentence: **the span is computed from the quote, never asserted
beside it.**

`locate()` is the only sanctioned producer. It takes a quote and a text and
returns the offsets it found; there is no parameter through which a caller can
supply an offset, so a wrong span is not something a careless extractor can
write — it is something it cannot express. `scripts/arch_checks.py` enforces
that by refusing `span_start=` anywhere outside this module and its tests, and
`supabase/migrations/0008_citations_resolve.sql` re-checks the same equality in
the database so a writer that bypasses this module is still refused.

Three layers, because the defect this project keeps rediscovering is a rule
enforced on one side only.

## The second hole

INV-8 names it: r1 "proved a quote *existed*, not that it *supported* the
figure — any valid quote attached to any figure passed." A resolving span is
necessary and not sufficient. So a cited value carries a third link:

    canonical_text[span] == quote        the quote is really in the document
    value_text in quote                  the figure is really in the quote
    cited_numeral(value_text) == value   the stored number is really that figure

Each link is checked here and again in the database. Break any one and the chain
reports a figure the document does not state.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from packages.contracts.models import Citation


class CitationError(ValueError):
    """A citation does not resolve. Never downgraded to a warning."""


def locate(
    *,
    document_version_id: str,
    canonical_text: str,
    quote: str,
    occurrence: int | None = None,
) -> Citation:
    """The citation for `quote` in `canonical_text`, with its span computed.

    A quote that appears more than once must say which one it means. This is not
    fastidiousness: `$8.00` occurs four times in Dream's cap table — as the
    Series B issue price, and in three separate purchaser rows — and `$3.20`
    occurs five. Taking the first match would attach a plausible span to the
    wrong row, and every downstream check would pass, because the quote really
    is in the document and the span really does resolve to it. The auditor
    following the citation lands on the wrong line and has no way to tell that
    the system meant a different one.

    So an ambiguous quote is an error, and the fix is normally to quote more
    context rather than to pass `occurrence`. A quote that identifies itself is
    what an auditor can check; an index into a list of matches is not.
    """
    if not quote:
        raise CitationError("an empty quote cites nothing")

    starts = [m.start() for m in re.finditer(re.escape(quote), canonical_text)]
    if not starts:
        raise CitationError(
            f"quote not present in {document_version_id}: {_excerpt(quote)}. "
            "The text is the extractor's output verbatim — check for the "
            "run-together spacing `-layout` produces in table rows."
        )
    if occurrence is None:
        if len(starts) > 1:
            raise CitationError(
                f"quote occurs {len(starts)} times in {document_version_id} at "
                f"{starts}: {_excerpt(quote)}. Quote more context so it names one "
                "passage, or pass occurrence= to say which deliberately."
            )
        start = starts[0]
    else:
        if not 0 <= occurrence < len(starts):
            raise CitationError(
                f"occurrence {occurrence} requested but the quote occurs "
                f"{len(starts)} time(s) in {document_version_id}: {_excerpt(quote)}"
            )
        start = starts[occurrence]

    return Citation(
        document_version_id=document_version_id,
        quote=quote,
        span_start=start,
        span_end=start + len(quote),
    )


def locate_pattern(
    *,
    document_version_id: str,
    canonical_text: str,
    pattern: re.Pattern[str],
) -> tuple[Citation, re.Match[str]]:
    """The single passage this pattern matches, cited at the span it matched.

    `-layout` renders a cap-table row as a label, a run of thirty-odd spaces and
    a figure. Writing that whitespace into a source file as a literal quote is
    unreadable and drifts the moment poppler changes a column width, so table
    rows are cited by pattern: the *regex* is the reviewable artifact and the
    quote is whatever it matched, which is still text verbatim from the document.

    Matching exactly once is required for the same reason `locate` demands a
    unique quote — a pattern that matches three purchaser rows and takes the
    first attaches a resolving span to the wrong one, and nothing downstream can
    tell. The match object comes back so the caller can read a named group out
    of the same match rather than searching again and possibly landing elsewhere.
    """
    matches = list(pattern.finditer(canonical_text))
    if not matches:
        raise CitationError(
            f"pattern matched nothing in {document_version_id}: {pattern.pattern!r}"
        )
    if len(matches) > 1:
        raise CitationError(
            f"pattern matched {len(matches)} passages in {document_version_id} at "
            f"{[m.span() for m in matches]}: {pattern.pattern!r}. Anchor it to one row."
        )
    match = matches[0]
    start, end = match.span()
    return (
        Citation(
            document_version_id=document_version_id,
            quote=match.group(0),
            span_start=start,
            span_end=end,
        ),
        match,
    )


def from_stored(
    *,
    document_version_id: str,
    quote: str,
    span: tuple[int, int],
    canonical_text: str | None = None,
) -> Citation:
    """Rebuild a citation that was already stored, and already checked.

    Reading a row back is not the act `locate()` exists to prevent. The offsets
    here were computed from the text when the fact was written, and
    `0008_citations_resolve.sql` refused the insert unless
    `substring(canonical_text, span) = citation_quote` — so by the time a span is
    in `extracted_fact` the database has already proved it resolves.

    It still goes through this module rather than constructing `Citation`
    directly, because the arch rule in `scripts/arch_checks.py` allows no
    exceptions: `span_start=` appears nowhere outside this file. A rule with one
    carve-out for "the reader, which is fine" is a rule whose next carve-out is
    an extractor that also looked fine. The reader named itself here instead.

    The span arrives as one pair rather than two keyword arguments, so a caller
    cannot name the ends independently — and so `span_start=` genuinely appears
    nowhere outside this file, which is what makes the arch rule checkable
    rather than aspirational.

    `canonical_text` is optional because the caller usually has not fetched the
    document — a claim list would pull every document's full text to display a
    quote it already has. When it is supplied, this verifies rather than trusts.
    """
    citation = Citation(
        document_version_id=document_version_id,
        quote=quote,
        span_start=span[0],
        span_end=span[1],
    )
    if canonical_text is not None:
        verify(citation, canonical_text)
    return citation


def resolves_in(citation: Citation, canonical_text: str) -> bool:
    """Does the span actually contain the quote?

    Slicing past the end of a Python string is silent — `"ab"[0:99]` is `"ab"`,
    not an error — so a span running off the end would compare a truncated slice
    and could still match a short quote. The length is therefore checked
    explicitly rather than left to the slice.
    """
    if citation.span_end > len(canonical_text):
        return False
    return canonical_text[citation.span_start : citation.span_end] == citation.quote


def verify(citation: Citation, canonical_text: str) -> None:
    """Raise unless the citation resolves. The write path calls this."""
    if resolves_in(citation, canonical_text):
        return
    if citation.span_end > len(canonical_text):
        found = f"<past the end; text is {len(canonical_text)} code points>"
    else:
        found = repr(canonical_text[citation.span_start : citation.span_end])
    raise CitationError(
        f"citation into {citation.document_version_id} does not resolve: "
        f"span [{citation.span_start}, {citation.span_end}) holds {found}, "
        f"not {_excerpt(citation.quote)}"
    )


#: Whitespace, spelled out rather than `\s`.
#:
#: Python's `\s` on a `str` pattern matches Unicode whitespace — a non-breaking
#: space among them — while Postgres ARE `\s` does not. A figure carrying a
#: NBSP, which is an entirely ordinary thing for a PDF table to contain, would
#: then parse on one side and refuse on the other: the contract would store a
#: number the database rejects, or two mirrored rules would silently stop being
#: mirrored. Both sides name the same six characters.
_WS = r"[ \t\n\r\f\v]"

#: The shape of text that states exactly one figure. Deliberately narrow, and
#: anchored at both ends: anything else is not a figure and gets no number.
#:
#: The first version stripped every non-numeric character and read what was
#: left, which turned `"November\n14, 2025"` into `142025` and stored it as the
#: value of a date. A rule that answers a question it was not asked is worse
#: than one that refuses, because the answer is plausible.
#:
#: The integer part is a *grammar*, not "digits and commas". The looser version
#: read `"8,00"` — a European decimal — as eight hundred, and both this parser
#: and the plpgsql one agreed on it, which is the failure mode a mirror test
#: cannot catch: two implementations wrong in the same direction. A comma is
#: therefore only a thousands separator when it groups exactly three digits,
#: and a leading zero on an integer (`"008"`) is refused rather than normalised.
#: `"0.75"` is still a figure; `"0"` still reads as zero.
_INT = r"(?:0|[1-9][0-9]{0,2}(?:,[0-9]{3})+|[1-9][0-9]*)"
_FIGURE = re.compile(
    rf"{_WS}*\(?{_WS}*-?{_WS}*\$?{_WS}*"
    rf"{_INT}(?:\.[0-9]+)?"
    rf"{_WS}*%?{_WS}*\)?{_WS}*"
)
_NOT_NUMERIC = re.compile(r"[^0-9.]")
_BARE_NUMBER = re.compile(r"^[0-9]+(\.[0-9]+)?$")
_NEGATIVE = re.compile(rf"^{_WS}*[(-]")

#: Characters that, sitting next to a figure, mean it is part of a longer one.
#: `625` inside `625,000` is not the figure that row states — it is three of its
#: digits. Start and end of the quote count as boundaries.
_NUMERAL_CHAR = re.compile(r"[0-9,.]")


def cited_numeral(value_text: str) -> Decimal | None:
    """The number a quoted figure states, or None if it does not state one.

    Mirrored exactly by `cited_numeral()` in
    `supabase/migrations/0008_citations_resolve.sql`, and
    `tests/test_citations.py` runs one table of cases through both to prove they
    agree. Two implementations of a parsing rule that are merely *believed* to
    agree is how a figure passes the contract and is rejected by the database,
    or worse, passes both while meaning different numbers.

    Returning `None` rather than raising is deliberate at the boundary: plenty
    of cited facts are text (`"Series A-1 Preferred"`, a date, a party name) and
    have no numeric form. What must never happen is a *silent zero*, so callers
    store `None` and the database refuses a `value_numeric` that disagrees.

    `"$8.00 and $3.20"` reads as nothing, not as `8.003.20` and not as the first
    of the two. A value_text naming two figures cannot be bound to one number,
    and neither can `"November 14, 2025"`.
    """
    if _FIGURE.fullmatch(value_text) is None:
        return None
    stripped = _NOT_NUMERIC.sub("", value_text)
    if not _BARE_NUMBER.match(stripped):
        return None
    try:
        magnitude = Decimal(stripped)
    except InvalidOperation:  # pragma: no cover - _BARE_NUMBER already excludes these
        return None
    return -magnitude if _NEGATIVE.match(value_text) else magnitude


def value_token_occurrences(quote: str, value_text: str) -> int:
    """How many times the quote states this value as a figure in its own right.

    Plain substring containment was not enough, and the gap was not theoretical:
    with a citation resolving to `7GC Fund II, L.P.   625,000   $3.20`, storing
    `value_text="625"` with `value_numeric=625` satisfied all three bindings and
    the database accepted it. So did `"000"` with `0`. The ledger would then hold
    six hundred and twenty-five shares, cited to a row stating six hundred and
    twenty-five thousand, with every check green.

    A digit, comma or full stop on either side means the match is a fragment of
    a longer figure rather than the figure itself. `$` and `%` do not count —
    `8.00` inside `$8.00` and `3.29` inside `3.29%` are the same number the page
    states, just without its dressing.

    Three more continuations, each of which changes the value rather than its
    dressing, and each of which was accepted before:

    * **A leading minus.** `loss was -8.00` matched `8.00` and stored positive
      eight against a passage stating negative eight.
    Accounting parentheses are deliberately **not** a boundary, and the reason
    is worth recording because two attempts got it wrong.

    This corpus uses parentheses for both things. Sway's `($1,750,000)`,
    Capsule's `($4.00)` and Lucra's `($1,500,000)` are grouping — a tranche, a
    purchase price, a commitment, all positive. Capsule's `(70.0%)` is an
    accounting negative and means minus seventy. Position cannot separate them.

    Treating the pair as a boundary refused the three positives. Refusing a
    parenthesised capture outright refused the one negative. Both were tried and
    both broke real extractions.

    So the convention is decided per figure, by the extractor, in its pattern —
    where it is visible and reviewable — and `cited_numeral` reads a leading `(`
    as a negative sign. Capsule's pattern captures `(70.0%)` deliberately; the
    others capture the figure without its brackets, equally deliberately.
    * **An exponent.** `scaled 8e3` matched `8` — three orders of magnitude —
      and `8.00e-2` matched `8.00`. `e` counts only when a digit or sign follows
      it, so a figure followed by a word is untouched.

    A leading `+` is deliberately not a boundary: it states the sign the value
    already has, and Moonfare's `+$48,515` is a real corpus case.

    Mirrored by `value_token_occurrences()` in
    `supabase/migrations/0008_citations_resolve.sql`.
    """
    if not value_text:
        return 0
    found = 0
    start = 0
    while True:
        at = quote.find(value_text, start)
        if at < 0:
            return found
        end = at + len(value_text)
        before = quote[at - 1] if at > 0 else ""
        after = quote[end : end + 1]
        beyond = quote[end + 1 : end + 2]
        continues = (
            bool(_NUMERAL_CHAR.match(before))
            or bool(_NUMERAL_CHAR.match(after))
            or before == "-"
            or (after in ("e", "E") and (beyond.isdigit() or beyond in ("+", "-")))
        )
        if not continues:
            found += 1
        start = at + 1


def supports_value(quote: str, value_text: str) -> bool:
    """Does the cited passage state this figure, once and unambiguously? INV-8.

    Three failures, each of which passed before:

    * **A real but irrelevant quote** — the document's title cited for a share
      count. The figure is not in the passage at all.
    * **A fragment of a larger figure** — `625` cited to a row stating
      `625,000`. The digits are present and the number is wrong.
    * **A passage stating the figure more than once** — then the citation does
      not say which occurrence it means, which is the same objection `locate`
      makes to an ambiguous quote. Citing an entire page for `$8.00` when four
      rows carry that price points an auditor at all four.
    """
    return value_token_occurrences(quote, value_text) == 1


def _excerpt(text: str, limit: int = 80) -> str:
    return repr(text if len(text) <= limit else text[:limit] + "…")
