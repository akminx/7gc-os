"""The pro forma cap-table extractors: what the patterns do, and what they read.

Three layers, separated by what each can prove:

* **Patterns on synthetic text**, which runs in CI where the corpus is absent.
  The bodies below are the `-layout` shape of the real documents carrying
  *different figures*, so a pattern that returned a constant rather than reading
  the page fails here. Every guard is proved on this layer, because a guard that
  only runs where the private material lives has not been proved.
* **The real documents**, corpus-gated. Every figure is hand-transcribed from
  the PDF and written here as a literal — the rule `evals/oracle/primitives.yaml`
  follows. Asserting what the extractor returned would agree with itself.
* **A database round trip**, database- and corpus-gated.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ingest.documents.claims import FactDraft, cited_fact, store_claim, store_document
from ingest.documents.extract_cap_table import (
    _FLUIDSTACK_SERIES_B_PATTERNS,
    FLUIDSTACK_CLOSING_DATE,
    FLUIDSTACK_HELD_CLASSES,
    FLUIDSTACK_PRICED_CLASS,
    FLUIDSTACK_SERIES_A2_CLOSING_DATE,
    SWAY_EFFECTIVE_DATE,
    SWAY_HELD_CLASS,
    SWAY_HOLDER_APPROVAL_DATE,
    SWAY_PRICED_CLASS,
    SWAY_PRIOR_HELD_CLASS,
    _price_the_document_states,
    fluidstack_claims,
    fluidstack_series_a2_facts,
    fluidstack_series_b_facts,
    sway_claim,
    sway_facts,
)
from ingest.documents.parse import ParsedDocument, parse
from packages.contracts.citations import CitationError, locate, resolves_in
from packages.contracts.enums import ExecutionStatus, SourceClass
from packages.contracts.models import Citation
from tests.schema_helpers import DSN, Conn

FLUIDSTACK_PDF = Path(
    "7GC Audit Case Study/02_Portfolio Documentation/Fluidstack/"
    "Fluidstack - Series B - Pro Forma Capitalization Table Excerpt (December 18, 2025).pdf"
)
SWAY_PDF = Path(
    "7GC Audit Case Study/02_Portfolio Documentation/Sway/"
    "Sway - Series A-3 Recapitalization - Pro Forma Capitalization Table "
    "(September 30, 2025).pdf"
)
needs_corpus = pytest.mark.skipif(
    not (FLUIDSTACK_PDF.exists() and SWAY_PDF.exists()),
    reason="case-study documents are not in the repository",
)

# ── Synthetic documents ──────────────────────────────────────────────────
#: Fluidstack's shape, every figure changed except the two prices the claim
#: constructors state by hand. The Series A row carries `1,100,000` on purpose:
#: a pattern matching three digits, a comma and three digits reads `100,000` out
#: of it and is wrong by a million shares while citing a passage that really does
#: contain those characters.
FLUIDSTACK_BODY = (
    "FLUIDSTACK LTD\n"
    "Series B Preferred Financing — Pro Forma Capitalization Table (Fully Diluted) — "
    "Closing Date: February 3, 2026\n"
    "— Prepared by company counsel\n"
    "\n"
    "1. Transaction Summary\n"
    "Series B Preferred issued at $30.00 per share. "
    "Aggregate gross proceeds: $25,000,000 (2,000,000 shares).\n"
    "Post-money valuation: $250,000,000 on 20,000,000 fully diluted shares. "
    "Pre-money valuation: $225,000,000.\n"
    "\n"
    "4. Selected Holders of Record — Series A and A-2 (Post-Closing)\n"
    "    Holder                        Security          Shares          Orig. PPS\n"
    "\n"
    "    7GC Fund II, L.P.             Series A          1,100,000          $4.00\n"
    "\n"
    "    7GC Fund II, L.P.             Series A-2          250,000          $7.00\n"
    "\n"
    "5. Notes\n"
    "(a) The Series A-2 tranche closed June 1, 2025 at $15.00 per share "
    "($90,000,000 post-money); executed documents on file with\n"
    "company counsel. (c) Figures reflect the register of members as of the closing "
    "date and the executed Series B Subscription Agreement dated February 3, 2026.\n"
)

#: Sway's shape, likewise. The Series Seed row states `400,000` twice — prior
#: shares and shares issued, because a 1.0000 : 1 ratio makes them equal — which
#: is the real document's shape and the reason one citation there quotes the tail
#: of the row rather than the row.
SWAY_BODY = (
    "SWAY TECHNOLOGIES, INC.\n"
    "Series A-3 Recapitalization — Pro Forma Capitalization Table (Fully Diluted) — "
    "Effective March 31, 2026 —\n"
    "Prepared by company counsel\n"
    "\n"
    "1. Transaction Summary\n"
    "Inside-led recapitalization approved by the requisite holders on March 20, 2026 "
    "and closed March 31, 2026. New\n"
    "Series A-3 Preferred issued at $0.40 per share for aggregate new capital of "
    "$2,000,000 (5,000,000 shares). Post-money\n"
    "valuation: $5,000,000 on 12,500,000 fully diluted shares. All previously "
    "outstanding preferred stock converted into Series\n"
    "A-3 Preferred pursuant to the Recapitalization Agreement at the exchange ratios "
    "set out in Section 3.\n"
    "\n"
    "3. Conversion of Prior Preferred — Exchange Ratios\n"
    "  Prior Security                    Prior Shares      Exchange Ratio      A-3 Shares Issued\n"
    "\n"
    "  Series Seed Preferred ($0.50, 2021)      400,000         1.0000 : 1         400,000\n"
    "\n"
    "  Series A Preferred ($1.00, Nov 2022)   2,000,000        1.25000 : 1       2,500,000\n"
    "\n"
    "  Total conversion shares                2,400,000                          2,900,000\n"
    "\n"
    "4. Selected Holders of Record (Post-Recapitalization)\n"
    "  Holder                        A-3 Shares      Basis\n"
    "\n"
    "  7GC Fund II, L.P.                500,000      Conversion of 400,000 Series A "
    "at 1.25000 : 1\n"
    "\n"
    "5. Notes\n"
    "(b) Holders electing not to participate in the new-money tranche retained\n"
    "conversion shares only; 7GC Fund II, L.P. did not participate in the new-money "
    "tranche. (c) Liquidation preference of the Series A-3 is 1x.\n"
)

# ── What each field must read, on the real page and on the synthetic one ──
#: `field name → (real value_text, its number or None, synthetic value_text)`.
#:
#: The first two columns are hand-transcribed from the PDF. `None` means the
#: passage states no single figure, so `value_numeric` is NULL rather than a
#: number invented from a date or a sentence. The third is what the same pattern
#: must read out of a page carrying different figures, which is what
#: distinguishes a pattern that reads from one that remembers.
Table = dict[str, tuple[str, str | None, str]]

FLUIDSTACK_SERIES_B: Table = {
    "fund_series_a_security_class": ("Series A", None, "Series A"),
    "fund_series_a_shares": ("100,000", "100000", "1,100,000"),
    "fund_series_a_original_pps": ("$10.00", "10.00", "$4.00"),
    "fund_series_a2_security_class": ("Series A-2", None, "Series A-2"),
    "fund_series_a2_shares": ("100,000", "100000", "250,000"),
    "fund_series_a2_original_pps": ("$15.00", "15.00", "$7.00"),
    "series_b_price_per_share": ("$30.00", "30.00", "$30.00"),
    "series_b_gross_proceeds": ("$150,000,000", "150000000", "$25,000,000"),
    "series_b_shares_issued": ("5,000,000", "5000000", "2,000,000"),
    "post_money_valuation": ("$1,500,000,000", "1500000000", "$250,000,000"),
    "fully_diluted_shares": ("50,000,000", "50000000", "20,000,000"),
    "pre_money_valuation": ("$1,350,000,000", "1350000000", "$225,000,000"),
    "closing_date": ("December 18, 2025", None, "February 3, 2026"),
    "series_b_subscription_agreement": (
        "executed Series B Subscription Agreement dated December 18, 2025",
        None,
        "executed Series B Subscription Agreement dated February 3, 2026",
    ),
}

FLUIDSTACK_SERIES_A2: Table = {
    "series_a2_closing_date": ("May 30, 2025", None, "June 1, 2025"),
    "series_a2_price_per_share": ("$15.00", "15.00", "$15.00"),
    "series_a2_post_money_valuation": ("$750,000,000", "750000000", "$90,000,000"),
    # The line wraps between `with` and `company` in both sources, so the quoted
    # form carries that newline. Nothing repairs it: the canonical text is the
    # extractor's output with no post-processing (SPEC §8).
    "series_a2_executed_documents": (
        "executed documents on file with\ncompany counsel",
        None,
        "executed documents on file with\ncompany counsel",
    ),
}

SWAY: Table = {
    "effective_date": ("September 30, 2025", None, "March 31, 2026"),
    "holder_approval_date": ("September 26, 2025", None, "March 20, 2026"),
    "closing_date": ("September 30, 2025", None, "March 31, 2026"),
    "series_a3_price_per_share": ("$0.40", "0.40", "$0.40"),
    "new_money_aggregate_capital": ("$4,000,000", "4000000", "$2,000,000"),
    "new_money_shares": ("10,000,000", "10000000", "5,000,000"),
    "post_money_valuation": ("$10,000,000", "10000000", "$5,000,000"),
    "fully_diluted_shares": ("25,000,000", "25000000", "12,500,000"),
    "converted_into_class": ("Series\nA-3 Preferred", None, "Series\nA-3 Preferred"),
    "prior_series_seed_shares": ("1,250,000", "1250000", "400,000"),
    "prior_series_seed_exchange_ratio": ("1.0000", "1.0000", "1.0000"),
    "series_seed_a3_shares_issued": ("1,250,000", "1250000", "400,000"),
    "prior_series_a_shares": ("8,000,000", "8000000", "2,000,000"),
    "prior_series_a_exchange_ratio": ("1.09375", "1.09375", "1.25000"),
    "series_a_a3_shares_issued": ("8,750,000", "8750000", "2,500,000"),
    "total_prior_conversion_shares": ("9,250,000", "9250000", "2,400,000"),
    "total_a3_conversion_shares_issued": ("10,000,000", "10000000", "2,900,000"),
    "fund_a3_shares": ("875,000", "875000", "500,000"),
    "fund_prior_security_class": ("Series A", None, "Series A"),
    "fund_prior_shares": ("800,000", "800000", "400,000"),
    "fund_exchange_ratio": ("1.09375", "1.09375", "1.25000"),
    "fund_new_money_participation": (
        "7GC Fund II, L.P. did not participate in the new-money tranche",
        None,
        "7GC Fund II, L.P. did not participate in the new-money tranche",
    ),
}


def _doc(tmp_path: Path, body: str, name: str = "captable.txt") -> ParsedDocument:
    source = tmp_path / name
    source.write_bytes(body.encode("utf-8"))
    return parse(source)


def _values(facts: tuple[FactDraft, ...]) -> dict[str, str]:
    return {fact.field_name: fact.value_text for fact in facts}


def _synthetic(table: Table) -> dict[str, str]:
    return {field_name: row[2] for field_name, row in table.items()}


def _assert_transcribed(facts: tuple[FactDraft, ...], table: Table, parsed: ParsedDocument) -> None:
    by_name = {fact.field_name: fact for fact in facts}
    assert set(by_name) == set(table)
    for field_name, (want_text, want_number, _) in table.items():
        fact = by_name[field_name]
        assert fact.value_text == want_text, field_name
        assert fact.value_numeric == (None if want_number is None else Decimal(want_number)), (
            field_name
        )
        assert resolves_in(fact.citation, parsed.canonical_text), field_name
        # The span lies inside a page of the document it cites, so the packet can
        # tell an auditor where to look. `page_of` raises rather than clamping.
        assert parsed.page_of(fact.citation.span_start) == 1, field_name


# ── Patterns, on synthetic text ──────────────────────────────────────────
def test_the_patterns_read_the_page_and_not_a_constant(tmp_path: Path) -> None:
    fluidstack = _doc(tmp_path, FLUIDSTACK_BODY, "fluidstack.txt")
    sway = _doc(tmp_path, SWAY_BODY, "sway.txt")
    assert _values(fluidstack_series_b_facts("dv_f", fluidstack)) == _synthetic(FLUIDSTACK_SERIES_B)
    assert _values(fluidstack_series_a2_facts("dv_f", fluidstack)) == _synthetic(
        FLUIDSTACK_SERIES_A2
    )
    assert _values(sway_facts("dv_s", sway)) == _synthetic(SWAY)


def test_every_cited_figure_resolves_and_is_stated_once_in_its_own_quote(tmp_path: Path) -> None:
    """The two bindings INV-8 needs, over every pattern in the module at once.

    `cited_fact` enforces both on the way in, so this cannot fail while the
    module is intact — which is the point. It goes red when somebody adds a
    pattern whose value group reaches outside its match, without anyone having
    to remember to write a test for that pattern.
    """
    fluidstack = _doc(tmp_path, FLUIDSTACK_BODY, "fluidstack.txt")
    sway = _doc(tmp_path, SWAY_BODY, "sway.txt")
    checks = (
        (fluidstack, fluidstack_series_b_facts("dv_f", fluidstack)),
        (fluidstack, fluidstack_series_a2_facts("dv_f", fluidstack)),
        (sway, sway_facts("dv_s", sway)),
    )
    for parsed, facts in checks:
        assert facts
        for fact in facts:
            assert resolves_in(fact.citation, parsed.canonical_text), fact.field_name
            assert fact.citation.quote.count(fact.value_text) == 1, fact.field_name


def test_a_share_count_is_captured_whole_or_not_at_all(tmp_path: Path) -> None:
    """`1,100,000` cited as `100,000` is the cap-table shape of the defect that
    put `625` against a row stating `625,000`: every digit is present, the
    citation resolves, and the ledger is wrong by a million shares."""
    facts = _values(fluidstack_series_b_facts("dv_synthetic", _doc(tmp_path, FLUIDSTACK_BODY)))
    assert facts["fund_series_a_shares"] == "1,100,000"


def test_the_series_a_row_patterns_do_not_also_match_the_series_a2_row(tmp_path: Path) -> None:
    """`Series A` is a prefix of `Series A-2`, and 7GC holds both. A pattern
    matching either row would attach a resolving span to whichever came first
    and report the A-2 lot's shares as the A lot's, with the holder name, the
    class column and the price all reading plausibly.

    Each of the three is asserted by name rather than through the fact set as a
    whole: one `pattern matched nothing` from anywhere in the dict would let the
    other two quietly start matching the wrong row.
    """
    without_series_a = FLUIDSTACK_BODY.replace(
        "    7GC Fund II, L.P.             Series A          1,100,000          $4.00\n", ""
    )
    text = _doc(tmp_path, without_series_a).canonical_text
    for field_name in (
        "fund_series_a_security_class",
        "fund_series_a_shares",
        "fund_series_a_original_pps",
    ):
        assert _FLUIDSTACK_SERIES_B_PATTERNS[field_name].search(text) is None, field_name

    # And the A-2 row is still found exactly once, so the two rows are
    # distinguished rather than merely both missed.
    full_text = _doc(tmp_path, FLUIDSTACK_BODY).canonical_text
    for field_name in (
        "fund_series_a2_security_class",
        "fund_series_a2_shares",
        "fund_series_a2_original_pps",
    ):
        assert len(_FLUIDSTACK_SERIES_B_PATTERNS[field_name].findall(full_text)) == 1, field_name


def test_two_rows_for_the_same_holder_and_class_are_refused(tmp_path: Path) -> None:
    """A cap table stating the fund's Series A twice is not a document to extract
    from silently: the two rows may disagree, and taking the first is a choice
    the citation cannot express."""
    row = "    7GC Fund II, L.P.             Series A          1,100,000          $4.00\n"
    with pytest.raises(CitationError, match="matched 2 passages"):
        fluidstack_series_b_facts("dv_synthetic", _doc(tmp_path, FLUIDSTACK_BODY + row))


def test_a_row_stating_the_same_figure_twice_cannot_be_quoted_whole(tmp_path: Path) -> None:
    """Why `series_seed_a3_shares_issued` quotes the tail of its row: a 1.0000 : 1
    ratio makes prior shares and shares issued the same number, so the row states
    `400,000` twice and a whole-row quote does not say which it means. That is
    refused rather than resolved by taking the second."""
    whole_row = re.compile(
        r"Series Seed Preferred \(\$[\d.]+, \d{4}\)\s+[\d,]+\s+[\d.]+ : 1\s+(?P<value>[\d,]+)"
    )
    with pytest.raises(CitationError, match="is not inside the passage cited for it"):
        cited_fact(
            document_version_id="dv_synthetic",
            canonical_text=_doc(tmp_path, SWAY_BODY).canonical_text,
            field_name="series_seed_a3_shares_issued",
            pattern=whole_row,
        )


def test_the_exchange_ratio_is_bound_to_a_number_the_validator_can_multiply(
    tmp_path: Path,
) -> None:
    """V13 multiplies by this ratio. Captured as `1.25000 : 1` it is prose,
    `cited_numeral` reads no figure from it, and the validator is handed a NULL
    where its multiplicand belongs."""
    facts = {f.field_name: f for f in sway_facts("dv_synthetic", _doc(tmp_path, SWAY_BODY))}
    assert facts["fund_exchange_ratio"].value_numeric == Decimal("1.25000")
    assert facts["prior_series_seed_exchange_ratio"].value_numeric == Decimal("1.0000")
    assert " : 1" in facts["fund_exchange_ratio"].citation.quote


# ── The claim's own price is cited, not asserted ─────────────────────────
def test_a_claim_price_the_document_does_not_state_is_refused(tmp_path: Path) -> None:
    """`price_per_share` is the one figure on a claim typed by hand, and the one
    the mark is computed from. Nothing bound it to any fact, so a transposed
    digit stored, resolved, and reconciled to itself."""
    misquoted = SWAY_BODY.replace("issued at $0.40 per share", "issued at $0.41 per share")
    with pytest.raises(CitationError, match="the claim is priced at 0.40 but the document"):
        sway_claim(
            document_version_id="dv_synthetic", parsed=_doc(tmp_path, misquoted), holding_id="h"
        )


def test_a_claim_price_with_no_fact_of_that_name_is_refused() -> None:
    """The other half of the same guard: a price whose field never appears among
    the facts is cited to nothing at all — the failure a renamed pattern
    produces."""
    text = "Series B Preferred issued at $30.00 per share."
    citation = locate(
        document_version_id="dv", canonical_text=text, quote="issued at $30.00 per share"
    )
    facts = (
        FactDraft(
            field_name="a_different_name",
            value_text="$30.00",
            citation=citation,
            value_numeric=Decimal("30.00"),
        ),
    )
    with pytest.raises(CitationError, match="carries no fact of that name"):
        _price_the_document_states(facts, "series_b_price_per_share", Decimal("30.00"))


# ── INV-15 and INV-17, on the claims themselves ──────────────────────────
def test_fluidstack_makes_two_claims_that_no_single_claim_could_carry(tmp_path: Path) -> None:
    """INV-15 · authority lives on the claim, not on the file.

    The Series B table and note (a)'s Series A-2 tranche differ in the three
    fields that decide how evidence is used: when the price is a price *at*
    (INV-3), which class it prices (INV-17), and what the Fund holds for it
    (INV-4). One `ClaimDraft` has one of each, so folding them together would
    date a May price to December and label an A-2 price Series B-priced.
    """
    parsed = _doc(tmp_path, FLUIDSTACK_BODY)
    series_b, series_a2 = fluidstack_claims(
        document_version_id="dv_synthetic", parsed=parsed, holding_id="h"
    )

    assert series_b.execution_status is ExecutionStatus.PRO_FORMA
    assert series_a2.execution_status is ExecutionStatus.UNEXECUTED_REFERENCED
    assert series_b.priced_class == "series_b"
    assert series_a2.priced_class == "series_a2"
    assert series_b.as_of_date == FLUIDSTACK_CLOSING_DATE
    assert series_a2.as_of_date == FLUIDSTACK_SERIES_A2_CLOSING_DATE
    assert series_a2.issued_date == FLUIDSTACK_CLOSING_DATE != series_a2.as_of_date
    assert series_b.claim_key != series_a2.claim_key
    # Both are the same authority *class* — one counsel-prepared document — so
    # source_class does not distinguish them. Execution status does, and that is
    # the field the audit letter's question is about.
    assert series_b.source_class is series_a2.source_class is SourceClass.COMPANY_CAP_TABLE


def test_priced_class_is_the_class_the_document_prices_on_both_sides(tmp_path: Path) -> None:
    """INV-17, and the reason these two documents belong in one module.

    Fluidstack prices a class 7GC does not hold: recording a held class there
    would be the cheapest possible collapse — one word, no error — and would let
    the mark be approved at $30.00 with no cited cross-class policy decision.

    Sway prices the class 7GC *does* hold, and only because the recapitalisation
    converted the position on 30 September 2025. Writing `series_a` there would
    fabricate a cross-class decision the document itself resolves; forgetting the
    prior class would misprice any mark dated before the conversion.
    """
    fluidstack, _ = fluidstack_claims(
        document_version_id="dv_synthetic", parsed=_doc(tmp_path, FLUIDSTACK_BODY), holding_id="h"
    )
    assert fluidstack.priced_class == FLUIDSTACK_PRICED_CLASS
    assert FLUIDSTACK_PRICED_CLASS not in FLUIDSTACK_HELD_CLASSES
    assert FLUIDSTACK_HELD_CLASSES == ("series_a", "series_a2")

    sway = sway_claim(
        document_version_id="dv_synthetic", parsed=_doc(tmp_path, SWAY_BODY), holding_id="h"
    )
    assert sway.priced_class == SWAY_PRICED_CLASS == SWAY_HELD_CLASS == "series_a3"
    assert SWAY_PRIOR_HELD_CLASS == "series_a" != SWAY_HELD_CLASS
    assert sway.execution_status is ExecutionStatus.PRO_FORMA
    assert sway.applicable_to is None


# ── The real documents ───────────────────────────────────────────────────
@needs_corpus
def test_the_real_fluidstack_table_states_these_figures() -> None:
    parsed = parse(FLUIDSTACK_PDF)
    _assert_transcribed(fluidstack_series_b_facts("dv_f", parsed), FLUIDSTACK_SERIES_B, parsed)
    _assert_transcribed(fluidstack_series_a2_facts("dv_f", parsed), FLUIDSTACK_SERIES_A2, parsed)


@needs_corpus
def test_the_real_fluidstack_claims_carry_the_dates_and_classes_the_page_states() -> None:
    parsed = parse(FLUIDSTACK_PDF)
    series_b, series_a2 = fluidstack_claims(
        document_version_id="dv_f", parsed=parsed, holding_id="h"
    )

    assert series_b.issued_date == date(2025, 12, 18)
    assert series_b.as_of_date == date(2025, 12, 18)
    assert series_b.applicable_from == date(2025, 12, 18)
    assert series_b.applicable_to is None
    assert series_b.price_per_share == Decimal("30.00")
    assert series_b.priced_class == "series_b"
    # §6.2.2 · the artifact in the Fund's possession, not the state of the
    # transaction. Note (c) references an executed Subscription Agreement and the
    # table is still pro forma — that gap is the audit letter's actual question.
    assert series_b.execution_status is ExecutionStatus.PRO_FORMA

    assert series_a2.issued_date == date(2025, 12, 18)
    assert series_a2.as_of_date == date(2025, 5, 30)
    assert series_a2.applicable_from == date(2025, 5, 30)
    assert series_a2.price_per_share == Decimal("15.00")
    assert series_a2.priced_class == "series_a2"
    assert series_a2.execution_status is ExecutionStatus.UNEXECUTED_REFERENCED


@needs_corpus
def test_the_real_sway_table_states_these_figures() -> None:
    parsed = parse(SWAY_PDF)
    _assert_transcribed(sway_facts("dv_s", parsed), SWAY, parsed)


@needs_corpus
def test_the_real_sway_recapitalisation_states_v13s_three_figures_separately() -> None:
    """SPEC V13 asserts `800,000 × 1.09375 = 875,000` exactly, and it can only
    assert it because the document states all three and each is cited on its own.

    The multiplication belongs to the validator; what this proves is the
    transcription it will be handed. The equality below checks the three literals
    *this file* transcribed against each other, which is cheaper than finding the
    typo as a red V13 with no way to tell which figure moved.
    """
    parsed = parse(SWAY_PDF)
    facts = {fact.field_name: fact for fact in sway_facts("dv_s", parsed)}

    assert facts["fund_prior_shares"].value_text == "800,000"
    assert facts["fund_exchange_ratio"].value_text == "1.09375"
    assert facts["fund_a3_shares"].value_text == "875,000"
    assert Decimal("800000") * Decimal("1.09375") == Decimal("875000")

    # One quote carries all three, which is what makes the ratio checkable: the
    # auditor reads the fund's own row and sees the arithmetic it claims.
    row = facts["fund_a3_shares"].citation.quote
    assert facts["fund_exchange_ratio"].citation.quote == row
    assert facts["fund_prior_shares"].citation.quote == row
    assert "Conversion of 800,000 Series A at 1.09375 : 1" in row


@needs_corpus
def test_the_real_sway_claim_is_dated_at_the_recapitalisation() -> None:
    parsed = parse(SWAY_PDF)
    claim = sway_claim(document_version_id="dv_s", parsed=parsed, holding_id="h")
    assert claim.issued_date == SWAY_EFFECTIVE_DATE == date(2025, 9, 30)
    assert claim.applicable_from == date(2025, 9, 30)
    assert claim.applicable_to is None
    assert claim.price_per_share == Decimal("0.40")
    assert claim.source_class is SourceClass.COMPANY_CAP_TABLE
    # INV-3 · the holders approved on 26 September and the recapitalisation
    # closed on 30 September. Two instants the document states separately, and
    # the claim is dated at the one the conversion took effect on.
    assert SWAY_HOLDER_APPROVAL_DATE == date(2025, 9, 26) != SWAY_EFFECTIVE_DATE


# ── The database round trip ──────────────────────────────────────────────
@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
@needs_corpus
def test_fluidstack_goes_from_pdf_to_stored_facts_that_still_resolve(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Both claims, all the way through, then re-resolved from what Postgres
    holds. Each layer can be right on its own and the chain still broken: a span
    computed on Python's code points, stored in a column that normalises newlines
    and re-read through a driver that decodes differently gives three plausible
    answers and no error anywhere."""
    parsed = parse(FLUIDSTACK_PDF)
    version_id = store_document(conn, parsed)
    claims = fluidstack_claims(document_version_id=version_id, parsed=parsed, holding_id=seed["h"])

    row = conn.execute(
        "select canonical_text from document_version where id = %s", (version_id,)
    ).fetchone()
    assert row is not None
    stored_text = row[0]
    assert isinstance(stored_text, str)
    assert stored_text == parsed.canonical_text

    for draft, table in zip(claims, (FLUIDSTACK_SERIES_B, FLUIDSTACK_SERIES_A2), strict=True):
        claim_id = store_claim(conn, version_id, draft, parsed.canonical_text)
        rows = conn.execute(
            "select field_name, value_text, value_numeric, citation_quote, span_start, span_end"
            " from extracted_fact where claim_id = %s",
            (claim_id,),
        ).fetchall()
        assert len(rows) == len(table)
        for field_name, value_text, value_numeric, quote, start, end in rows:
            assert isinstance(field_name, str)
            assert isinstance(quote, str)
            assert isinstance(start, int)
            assert isinstance(end, int)
            want_text, want_number, _ = table[field_name]
            assert value_text == want_text, field_name
            assert value_numeric == (None if want_number is None else Decimal(want_number)), (
                field_name
            )
            citation = Citation(
                document_version_id=version_id, quote=quote, span_start=start, span_end=end
            )
            assert resolves_in(citation, stored_text), field_name

    stored = conn.execute(
        "select claim_key, execution_status, priced_class, price_per_share, as_of_date"
        " from claim where holding_id = %s order by claim_key",
        (seed["h"],),
    ).fetchall()
    # The seed fixture's own claim is the first row; the two this extractor wrote
    # are the ones under test, and they differ in exactly the fields that made
    # them separate claims.
    assert [r[0] for r in stored] == ["k", "series_a2_referenced_execution", "series_b_pro_forma"]
    assert [r[1] for r in stored[1:]] == ["unexecuted_referenced", "pro_forma"]
    assert [r[2] for r in stored[1:]] == ["series_a2", "series_b"]
    assert [r[3] for r in stored[1:]] == [Decimal("15.00"), Decimal("30.00")]
    assert [r[4] for r in stored[1:]] == [date(2025, 5, 30), date(2025, 12, 18)]

    conn.rollback()
