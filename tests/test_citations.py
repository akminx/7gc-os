"""Citations resolve, or nothing is stored. INV-8.

Audit finding #3 was that `Citation` was a structural shell: span (0, 1) beside
a forty-character quote satisfied every check in the system, and the figure read
as cited while resolving to nothing.

Everything here runs on synthetic text, so the guard is proved in CI where the
corpus is absent. The two-sided agreement tests need a database and skip without
one — and that skip is itself the reason the Python-only cases below cover the
same rule independently.
"""

from __future__ import annotations

import re
from decimal import Decimal

import psycopg
import pytest

from packages.contracts.citations import (
    CitationError,
    cited_numeral,
    locate,
    locate_pattern,
    resolves_in,
    supports_value,
    value_token_occurrences,
    verify,
)
from packages.contracts.models import Citation
from tests.schema_helpers import DSN, Conn

TEXT = (
    "DREAM, INC.\n"
    "Series B Preferred Stock issued at $8.00 per share.\n"
    "    7GC Fund II, L.P.        625,000     $3.20      3.29%\n"
    "    Northgate Ventures III   2,812,500   $3.20     14.80%\n"
    "    Series B Preferred (this financing)   10,000,000   $8.00\n"
)
DV = "dv_test"


# ── The span is computed, never asserted ─────────────────────────────────
def test_locate_computes_the_span_from_the_text() -> None:
    citation = locate(document_version_id=DV, canonical_text=TEXT, quote="625,000")
    assert TEXT[citation.span_start : citation.span_end] == "625,000"
    assert resolves_in(citation, TEXT)


def test_an_ambiguous_quote_is_refused_rather_than_resolved_to_the_first_match() -> None:
    """`$3.20` is on two holder rows here and five in the real document. Taking
    the first attaches a resolving span to the wrong row, every downstream check
    passes, and the auditor following the citation lands on someone else's
    holding with no way to tell that was not what the system meant."""
    with pytest.raises(CitationError, match="occurs 2 times"):
        locate(document_version_id=DV, canonical_text=TEXT, quote="$3.20")


def test_an_ambiguous_quote_may_be_disambiguated_deliberately() -> None:
    citation = locate(document_version_id=DV, canonical_text=TEXT, quote="$3.20", occurrence=1)
    assert resolves_in(citation, TEXT)
    assert citation.span_start > TEXT.index("Northgate")


def test_a_quote_that_is_not_in_the_text_is_refused() -> None:
    with pytest.raises(CitationError, match="not present"):
        locate(document_version_id=DV, canonical_text=TEXT, quote="Series C")


def test_an_empty_quote_cites_nothing() -> None:
    with pytest.raises(CitationError, match="empty quote"):
        locate(document_version_id=DV, canonical_text=TEXT, quote="")


@pytest.mark.parametrize("quote", ["7GC Fund II, L.P.", "(this financing)", "3.29%"])
def test_a_quote_with_regex_metacharacters_is_matched_literally(quote: str) -> None:
    """A quote is a literal, not a pattern. Searching for it unescaped is not a
    hypothetical slip: `(this financing)` appears verbatim in Dream's cap table,
    and as a regex the parentheses are a group — the match starts one character
    late, so the span is shifted and covers the wrong text while the quote
    beside it still looks right. `L.P.` is the quieter version of the same bug,
    where `.` matches anything.
    """
    citation = locate(document_version_id=DV, canonical_text=TEXT, quote=quote)
    assert TEXT[citation.span_start : citation.span_end] == quote
    assert resolves_in(citation, TEXT)


# ── Verification refuses the shell ───────────────────────────────────────
def test_the_shape_the_audit_found_does_not_verify() -> None:
    """The exact defect: a real quote, a legal span, and no relationship
    between them. `span_end > span_start` was the only thing standing here."""
    shell = Citation(
        document_version_id=DV, quote="issued at $8.00 per share", span_start=0, span_end=1
    )
    assert not resolves_in(shell, TEXT)
    with pytest.raises(CitationError, match="does not resolve"):
        verify(shell, TEXT)


def test_a_span_running_past_the_end_does_not_verify() -> None:
    """Python slicing past the end is silent — `"ab"[0:99]` is `"ab"` — so a
    short quote could match a truncated slice if the length went unchecked."""
    over = Citation(document_version_id=DV, quote=TEXT, span_start=0, span_end=len(TEXT) + 50)
    assert not resolves_in(over, TEXT)
    with pytest.raises(CitationError, match="past the end"):
        verify(over, TEXT)


def test_a_span_off_by_one_does_not_verify() -> None:
    """The failure a `+1` in the Postgres translation would produce."""
    good = locate(document_version_id=DV, canonical_text=TEXT, quote="625,000")
    shifted = Citation(
        document_version_id=DV,
        quote=good.quote,
        span_start=good.span_start + 1,
        span_end=good.span_end + 1,
    )
    assert not resolves_in(shifted, TEXT)


# ── The value must be inside its own citation ────────────────────────────
def test_a_real_but_irrelevant_quote_does_not_support_a_figure() -> None:
    """INV-8's second hole: r1 proved a quote existed, not that it supported the
    figure. Without this an extractor cites the document's title for a share
    count and every structural check still passes."""
    assert not supports_value("DREAM, INC.", "625,000")
    assert supports_value("7GC Fund II, L.P.        625,000", "625,000")


ROW = "7GC Fund II, L.P.        625,000     $3.20      3.29%"


@pytest.mark.parametrize("fragment", ["625", "000", "25,0", "62", "3.2", "20"])
def test_a_fragment_of_a_longer_figure_does_not_support_a_value(fragment: str) -> None:
    """The defect a cross-family review found by executing it, not by reading.

    With a citation resolving to this row, `value_text="625"` with
    `value_numeric=625` satisfied all three bindings and the database accepted
    it — the ledger holding six hundred and twenty-five shares, cited to a row
    stating six hundred and twenty-five thousand, every check green. `"000"`
    with `0` went through the same way.

    Containment was the wrong test. A digit, comma or full stop on either side
    means the match is part of a longer figure, not the figure itself.
    """
    assert fragment in ROW
    assert not supports_value(ROW, fragment)


@pytest.mark.parametrize("figure", ["625,000", "$3.20", "3.29", "7GC Fund II, L.P."])
def test_a_whole_figure_in_the_row_is_still_supported(figure: str) -> None:
    """The tightening must not refuse the values the extractor actually reads.
    `$` and `%` are dressing, not digits: `3.29` inside `3.29%` is the number
    the page states."""
    assert supports_value(ROW, figure)


@pytest.mark.parametrize(
    ("quote", "value"),
    [
        # A sign the value would be dropping. Cited as `8.00` with
        # `value_numeric=8`, this stored POSITIVE eight against a passage
        # stating negative eight — the ledger reading the opposite of the page.
        ("loss was -8.00", "8.00"),
        ("adjustment of -1,000 this year", "1,000"),
        # An exponent. `8e3` is eight thousand; matching `8` inside it is out by
        # three orders of magnitude, and every check downstream still passed.
        ("scaled 8e3", "8"),
        ("rate 8.00e-2 applied", "8.00"),
        ("count 5e+6 units", "5"),
    ],
)
def test_a_sign_or_exponent_means_the_match_is_not_the_whole_figure(quote: str, value: str) -> None:
    """Both found by a cross-family review, and both accepted before it.

    A digit, comma or full stop either side was the whole boundary rule, so a
    minus sign and an exponent read as ordinary punctuation. `$` and `%` still
    do not count — they dress a figure without changing it — and a leading `+`
    does not either, because Moonfare's `+$48,515` is a real corpus figure that
    means exactly what it says.
    """
    assert value in quote
    assert not supports_value(quote, value)


@pytest.mark.parametrize(
    ("quote", "value"),
    [
        ("at $8.00 per share", "$8.00"),
        ("3.29% of the class", "3.29"),
        ("adjustment +$48,515 this year", "$48,515"),
        # Parentheses are grouping here, and this corpus uses them for both
        # things — Lucra's `($1,500,000)` is a commitment, Capsule's `(70.0%)`
        # is a negative. Position cannot separate them, so the convention is
        # decided per figure by the extractor's pattern.
        ("7GC Fund II, L.P. ($1,500,000); existing", "$1,500,000"),
    ],
)
def test_dressing_around_a_figure_does_not_make_it_a_fragment(quote: str, value: str) -> None:
    """The other half. An over-strict boundary rule refused four real corpus
    figures, and a constraint that rejects true evidence is as damaging as a
    missing one and harder to notice."""
    assert supports_value(quote, value)


def test_a_passage_stating_the_figure_twice_does_not_say_which_one() -> None:
    """Citing a whole page for `$8.00` when four rows carry that price points an
    auditor at all four. Same objection `locate` makes to an ambiguous quote,
    one level down."""
    assert not supports_value("row a $8.00 and row b $8.00", "$8.00")
    assert supports_value("row a $8.00 and row b $3.20", "$8.00")


def test_a_pattern_must_match_exactly_one_passage() -> None:
    with pytest.raises(CitationError, match="matched 2 passages"):
        locate_pattern(document_version_id=DV, canonical_text=TEXT, pattern=re.compile(r"\$3\.20"))
    with pytest.raises(CitationError, match="matched nothing"):
        locate_pattern(document_version_id=DV, canonical_text=TEXT, pattern=re.compile(r"Series C"))


def test_a_pattern_cites_the_span_it_matched() -> None:
    citation, match = locate_pattern(
        document_version_id=DV,
        canonical_text=TEXT,
        pattern=re.compile(r"7GC Fund II, L\.P\.\s+(?P<value>[\d,]+)"),
    )
    assert TEXT[citation.span_start : citation.span_end] == citation.quote
    assert match.group("value") == "625,000"
    assert supports_value(citation.quote, match.group("value"))


# ── Reading a number out of quoted text ──────────────────────────────────
#: One table, run through the Python parser here and through the SQL parser
#: below. Two implementations believed to agree is how a figure passes the
#: contract and is refused by the database — or worse, passes both while they
#: mean different numbers.
NUMERALS: list[tuple[str, str | None]] = [
    ("$8.00", "8.00"),
    ("8.00", "8.00"),
    ("625,000", "625000"),
    ("$800,000,000", "800000000"),
    ("$50,000,000.00", "50000000.00"),
    ("3.29%", "3.29"),
    ("100.00%", "100.00"),
    ("(1,000)", "-1000"),
    ("-42", "-42"),
    ("  8.00  ", "8.00"),
    ("8.00\n", "8.00"),
    # Text that states no single figure gets no number at all.
    ("November\n14, 2025", None),
    ("November 14, 2025", None),
    ("$8.00 and $3.20", None),
    ("Series A-1 Preferred", None),
    ("", None),
    ("abc", None),
    (".75", None),
    # A European decimal is not an American thousands group. Both parsers read
    # `8,00` as eight hundred and agreed with each other about it, which is the
    # one failure a mirror test cannot catch: two implementations wrong in the
    # same direction. A comma separates thousands only when it groups exactly
    # three digits.
    ("8,00", None),
    ("12,34", None),
    ("1,2345", None),
    ("1,00,000", None),
    # A leading zero is refused rather than normalised away.
    ("008", None),
    ("0", "0"),
    ("0.75", "0.75"),
    ("1,875,000", "1875000"),
    ("100,000,000", "100000000"),
    # A non-breaking space is Unicode whitespace to Python's `\s` and not to
    # Postgres ARE. Both sides name the six ASCII whitespace characters, so
    # both refuse this rather than one silently accepting it.
    ("8.00\xa0", None),
]


@pytest.mark.parametrize(("text", "expected"), NUMERALS)
def test_cited_numeral_reads_only_text_that_states_one_figure(
    text: str, expected: str | None
) -> None:
    """The first version stripped every non-numeric character and read what was
    left, which turned a cited date into the figure 142025 and stored it as a
    value. A rule that answers a question it was not asked is worse than one
    that refuses, because the answer is plausible."""
    got = cited_numeral(text)
    assert got == (None if expected is None else Decimal(expected))


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_database_reads_every_figure_the_same_way(conn: Conn) -> None:
    """The mirror check. `0008_citations_resolve.sql` reimplements this rule in
    plpgsql because the database is the side that cannot be bypassed, and a
    mirror nobody compares is not a mirror."""
    for text, expected in NUMERALS:
        row = conn.execute("select cited_numeral(%s)", (text,)).fetchone()
        assert row is not None
        want = None if expected is None else Decimal(expected)
        assert row[0] == want, f"{text!r}: python {cited_numeral(text)}, postgres {row[0]}"


# ── The database refuses what the contract refuses ───────────────────────
@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_postgres_and_python_agree_on_what_a_span_selects(conn: Conn) -> None:
    """`substring(from ... for ...)` is 1-based and counts characters; Python
    slicing is 0-based and counts code points. The `+1` in the trigger is the
    only adjustment between them, and getting it wrong shifts every citation in
    the system by one character — which still resolves often enough to look
    correct."""
    body = TEXT + "an astral char: \U0001f600 and text after it"
    for quote in ("625,000", "7GC Fund II, L.P.", "text after it", "\U0001f600"):
        citation = locate(document_version_id=DV, canonical_text=body, quote=quote)
        row = conn.execute(
            "select substring(%s from %s for %s)",
            (body, citation.span_start + 1, citation.span_end - citation.span_start),
        ).fetchone()
        assert row is not None
        assert row[0] == quote


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_trigger_refuses_a_citation_that_does_not_resolve(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The one that closes audit finding #3 in the database. This exact row —
    a plausible quote at span (0, 1) — inserted cleanly before 0008."""
    with pytest.raises(psycopg.Error, match="does not resolve"):
        conn.execute(
            "insert into extracted_fact (claim_id, field_name, value_text, citation_quote,"
            " span_start, span_end) values (%s, 'pps', '8.00', 'issued at $8.00', 0, 1)",
            (seed["cl"],),
        )
    conn.rollback()


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_trigger_refuses_a_negative_span(conn: Conn, seed: dict[str, str]) -> None:
    """0001 constrained only `span_end > span_start`, so (-9, -1) was legal and
    Postgres `substring` reaches before the string rather than failing."""
    with pytest.raises(psycopg.Error, match="negative"):
        conn.execute(
            "insert into extracted_fact (claim_id, field_name, value_text, citation_quote,"
            " span_start, span_end) values (%s, 'pps', '8.00', 'q', -9, -1)",
            (seed["cl"],),
        )
    conn.rollback()


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_trigger_refuses_a_span_past_the_end(conn: Conn, seed: dict[str, str]) -> None:
    with pytest.raises(psycopg.Error, match="past the end"):
        conn.execute(
            "insert into extracted_fact (claim_id, field_name, value_text, citation_quote,"
            " span_start, span_end) values (%s, 'pps', '8.00', 'x', 0, 9999)",
            (seed["cl"],),
        )
    conn.rollback()


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_trigger_refuses_a_figure_absent_from_its_own_citation(
    conn: Conn, seed: dict[str, str]
) -> None:
    """A resolving span is necessary and not sufficient: this quote is really in
    the document and says nothing about the value stored beside it."""
    from tests.schema_helpers import CITED_END, CITED_QUOTE, CITED_START

    with pytest.raises(psycopg.Error, match="as a figure in its own right 0 time"):
        conn.execute(
            "insert into extracted_fact (claim_id, field_name, value_text, citation_quote,"
            " span_start, span_end) values (%s, 'shares', '625,000', %s, %s, %s)",
            (seed["cl"], CITED_QUOTE, CITED_START, CITED_END),
        )
    conn.rollback()


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_trigger_refuses_a_number_the_cited_text_does_not_state(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The last link: the stored number must be the figure the text states.
    Without it `value_text = '8.00'` can carry `value_numeric = 800`, and every
    total built from the fact is wrong while every citation checks out."""
    from tests.schema_helpers import CITED_END, CITED_QUOTE, CITED_START, CITED_VALUE

    with pytest.raises(psycopg.Error, match="is not the figure"):
        conn.execute(
            "insert into extracted_fact (claim_id, field_name, value_text, value_numeric,"
            " citation_quote, span_start, span_end) values (%s, 'pps', %s, 800, %s, %s, %s)",
            (seed["cl"], CITED_VALUE, CITED_QUOTE, CITED_START, CITED_END),
        )
    conn.rollback()


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_trigger_refuses_figure_shaped_text_carrying_no_number(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The binding is an equality, and an equality has two sides.

    Checking it only when `value_numeric` was non-NULL let NULL short-circuit
    it, so a cited `$8.00` could be stored with no number beside it — and every
    downstream reader of `value_numeric` sees a fact that states no figure.
    """
    from tests.schema_helpers import CITED_END, CITED_QUOTE, CITED_START, CITED_VALUE

    with pytest.raises(psycopg.Error, match="is not the figure"):
        conn.execute(
            "insert into extracted_fact (claim_id, field_name, value_text, value_numeric,"
            " citation_quote, span_start, span_end) values (%s, 'pps', %s, null, %s, %s, %s)",
            (seed["cl"], CITED_VALUE, CITED_QUOTE, CITED_START, CITED_END),
        )
    conn.rollback()


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_trigger_refuses_a_fragment_of_a_longer_figure(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Executed against the live trigger before the fix, and accepted."""
    from tests.schema_helpers import CITED_END, CITED_QUOTE, CITED_START

    with pytest.raises(psycopg.Error, match="in its own right"):
        conn.execute(
            "insert into extracted_fact (claim_id, field_name, value_text, value_numeric,"
            " citation_quote, span_start, span_end) values (%s, 'pps', '8.0', 8.0, %s, %s, %s)",
            (seed["cl"], CITED_QUOTE, CITED_START, CITED_END),
        )
    conn.rollback()


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_database_counts_figure_tokens_the_same_way(conn: Conn) -> None:
    """The second mirrored rule, and the second place two implementations could
    quietly disagree. Includes a value carrying regex metacharacters, which the
    plpgsql side must handle by scanning rather than by building a pattern out
    of data it cannot escape."""
    cases = [
        (ROW, "625", 0),
        (ROW, "000", 0),
        (ROW, "625,000", 1),
        (ROW, "$3.20", 1),
        (ROW, "3.29", 1),
        ("row a $8.00 and row b $8.00", "$8.00", 2),
        ("Series B Preferred (this financing)", "(this financing)", 1),
        (ROW, "", 0),
        # The sign and exponent rules, mirrored. Both implementations were wrong
        # together before — the one failure a mirror test cannot catch unless the
        # cases are in it.
        ("loss was -8.00", "8.00", 0),
        ("scaled 8e3", "8", 0),
        ("rate 8.00e-2 applied", "8.00", 0),
        ("adjustment +$48,515 this year", "$48,515", 1),
        ("7GC Fund II, L.P. ($1,500,000); existing", "$1,500,000", 1),
    ]
    for quote, value, want in cases:
        row = conn.execute("select value_token_occurrences(%s, %s)", (quote, value)).fetchone()
        assert row is not None
        assert row[0] == want == value_token_occurrences(quote, value), (quote, value)


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_a_citation_that_resolves_is_accepted(conn: Conn, seed: dict[str, str]) -> None:
    """The positive path, without which every refusal above would still pass
    with the constraint written so tightly that nothing can be stored."""
    from tests.schema_helpers import CITED_END, CITED_QUOTE, CITED_START, CITED_VALUE

    conn.execute(
        "insert into extracted_fact (claim_id, field_name, value_text, value_numeric,"
        " citation_quote, span_start, span_end) values (%s, 'pps', %s, 8.00, %s, %s, %s)",
        (seed["cl"], CITED_VALUE, CITED_QUOTE, CITED_START, CITED_END),
    )
    conn.rollback()
