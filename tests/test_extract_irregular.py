"""Family D — the irregulars, and the four classifications that are the point.

Two halves, for the reason `test_document_parse.py` states: *a guard that only
runs where the private material lives has not been proved.*

* **Synthetic text, always runs.** Every guard is exercised on documents this
  file writes into `tmp_path`, with figures nothing like the corpus's — so a
  pattern reading a constant would fail here rather than agree with itself.
* **The real documents, skipped without them.** Every figure asserted below was
  transcribed by hand from the PDF or the `.txt`, and written as a literal.
  Asserting what the extractor returned would prove only that it is consistent.

The four assertions this family exists for: the press article is `press`; the
term sheet is `non_binding` though it calls itself executed; the CEO email is
`unexecuted_referenced` though it says the round closed; and one saved quote
record is three claims with three dates.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ingest.documents.claims import ClaimDraft, store_claim, store_document
from ingest.documents.extract_irregular import (
    BANZAI_PRICED_CLASS,
    DREAM_EMAIL_HELD_CLASS,
    DREAM_EMAIL_PRICED_CLASS,
    LUCRA_A2_PRICED_CLASS,
    LUCRA_HELD_CLASS,
    _cited_price,
    anthropic_claim,
    banzai_claims,
    dream_email_claim,
    jackpocket_claim,
    lucra_email_claim,
    lucra_term_sheet_claim,
)
from ingest.documents.parse import ParsedDocument, parse
from packages.contracts.citations import CitationError
from packages.contracts.enums import ExecutionStatus, SourceClass
from tests.schema_helpers import DSN, Conn

CORPUS = Path("7GC Audit Case Study/02_Portfolio Documentation")
ANTHROPIC_PDF = CORPUS / (
    "Anthropic/The Signal - Anthropic Said to Close Round at 120B Valuation (December 9, 2025).pdf"
)
BANZAI_TXT = CORPUS / "Banzai/Banzai (BNZA) - Saved Quote Record - Year-End Closing Prices.txt"
JACKPOCKET_PDF = CORPUS / (
    "Jackpocket/Jackpocket - Notice of Merger Consideration to Stockholders (May 20, 2024).pdf"
)
LUCRA_TERM_SHEET_PDF = CORPUS / "Lucra/Lucra - Series A-1 - Term Sheet Excerpt (May 2024).pdf"
LUCRA_EMAIL_TXT = CORPUS / "Lucra/Lucra - Email from CEO re Series A-2 Close (October 17, 2025).txt"
DREAM_EMAIL_TXT = CORPUS / "Dream/Dream - Series B Closing Notice Email (November 17, 2025).txt"

_ABSENT = "case-study documents are not in the repository"


def _needs(document: Path) -> pytest.MarkDecorator:
    return pytest.mark.skipif(not document.exists(), reason=_ABSENT)


# ── Synthetic documents ──────────────────────────────────────────────────
# Structure copied from the corpus, figures deliberately unlike it. Zenith Labs
# is not a portfolio company and $999 Billion is not a mark, so a test that
# passed by carrying a corpus constant would go red here.
#
# The *dates* do match the corpus, and must: every claim date is compiled into
# the pattern that reads it, so a synthetic document stating another date is a
# document this extractor correctly refuses. That is its own test below.
PRESS = """THE SIGNAL
Technology & Markets — Published December 9, 2025, 7:15 AM PT

Zenith Labs Said to Close New Funding Round at $999 Billion Valuation
Zenith Labs has finalized a new round of funding valuing the company at approximately $999
billion, according to three people familiar with the matter, roughly doubling its valuation.

The financing is expected to be formally announced in the
coming weeks. Terms have not been publicly disclosed, and the company declined to comment.

Reporting by staff. The Signal has not independently reviewed the transaction documents.
"""

QUOTES = """Zenith (NASDAQ: ZNTH) — Year-End Closing Price Record

Position: 7GC Fund I, L.P. — 40,000 common shares

Measurement Date    Closing Price    Position Value
12/29/2023          $9.90            $396,000
12/31/2024          $8.80            $352,000
12/31/2025          $7.70            $308,000

Basis: quoted closing price on the last trading day of each fiscal year (Level 1 input).
Pre-listing periods (FY2021, FY2022): held at March 2021 purchase price ($14.25/share; $570,000).
"""

MERGER = """ZENITH TRUST & TRANSFER COMPANY

Pursuant to the Agreement and Plan of Merger dated February 4, 2024, the merger was consummated on
May 20, 2024 (the "Effective Time"). At the Effective Time, each share of Series B Preferred Stock
was cancelled and converted into the right to receive $9.50 in cash, without interest.

    Security                              Series B Preferred Stock
    Shares of record at Effective Time    200,000
    Per-share merger consideration        $9.50
    Gross merger consideration            $1,900,000.00
    Escrow / holdback allocation          $0.00 (fully released at closing)
    Tax withholding                       $0.00 (valid Form W-9 on file)
    Net payment                           $1,900,000.00

Payment of the net amount was initiated by wire on May 24, 2024 to the account specified in the
holder's letter of transmittal, ref. ZN-M-4402. Original acquisition of the shares by the holder:
December 30, 2021 at $7.75 per share ($1,550,000.00 aggregate), per the Company's stock ledger.
"""

TERM_SHEET = """ZENITH, INC.
Series A-1 Preferred Stock Financing — Summary of Terms — May 20, 2024 — Non-binding except as noted

    Securities                        Series A-1 Preferred Stock ("Series A-1")
    Amount of financing               Up to $20,000,000
    Price per share                   $7.50 (the "Original Purchase Price")
    Valuation                         $70,000,000 pre-money; $90,000,000 post-money, fully diluted
    Investors                         Zenith Growth Partners (Lead); 7GC Fund II, L.P. ($4,000,000)
    Anticipated closing               On or about June 3, 2024

This excerpt from the executed term sheet is retained for audit support purposes. The executed
Series A-1 Stock Purchase Agreement and final closing
capitalization table are on file with company counsel and have not been located in the Fund's \
document repository.
"""

CEO_EMAIL = """From: A Founder <founder@zenith.example>
Date: Friday, October 17, 2025, 9:00 AM ET
Subject: Re: quick update

Wanted you to hear it from me before it \
circulates: we signed and closed the Series A-2 on Wednesday. $7.25 per share, $40M post.

Counsel is still finalizing the closing set; I'll have them send over the executed docs and \
updated cap table once the final signature pages are in.
"""

CLOSING_NOTICE = """From: A CFO <cfo@zenith.example>
Date: Monday, November 17, 2025, 8:05 AM ET
Subject: Zenith — Series B Closed

We're pleased to share that our Series B Preferred \
financing closed on Friday, November 1. Key terms: $12.50 per share, $40M raised, $500M \
post-money on 40M fully diluted shares. The pro forma capitalization table and closing set \
are attached; executed documents will follow from counsel this week.
"""


def _doc(tmp_path: Path, body: str, name: str) -> ParsedDocument:
    source = tmp_path / name
    source.write_bytes(body.encode("utf-8"))
    return parse(source)


def _stated(claim: ClaimDraft) -> dict[str, tuple[str, Decimal | None]]:
    """Each fact as `field -> (value_text, value_numeric)`."""
    return {fact.field_name: (fact.value_text, fact.value_numeric) for fact in claim.facts}


def _quote(claim: ClaimDraft, field_name: str) -> str:
    return next(f.citation.quote for f in claim.facts if f.field_name == field_name)


# ── Press: the classification that decides the system's honesty ──────────
def test_a_press_article_is_press_and_prices_nothing(tmp_path: Path) -> None:
    """INV-2 · authority is a lattice, not a score.

    A round reported by a newspaper is still a newspaper. The claim carries no
    `priced_class` and no `price_per_share`, so there is no figure for a policy
    layer to be tempted by — SPEC §14 keeps Anthropic's $8,000,000 out of every
    approved total, and that only holds if this document never supplies a price.

    `$999 Billion` is a magnitude in words, not a figure. Stripping `$999` out
    of it would store nine hundred and ninety-nine dollars against a valuation
    of nine hundred and ninety-nine billion — cited, resolving, and wrong by
    nine orders of magnitude. So every fact here is text carrying no number.
    """
    claim = anthropic_claim(
        document_version_id="dv", parsed=_doc(tmp_path, PRESS, "signal.txt"), holding_id="h"
    )
    assert claim.source_class is SourceClass.PRESS
    assert claim.execution_status is ExecutionStatus.NOT_APPLICABLE
    assert claim.priced_class is None
    assert claim.price_per_share is None
    assert all(fact.value_numeric is None for fact in claim.facts)
    assert _stated(claim)["headline_valuation"][0] == "$999 Billion"
    assert _stated(claim)["terms_disclosure"][0] == "Terms have not been publicly disclosed"


# ── Banzai: one file, three observations ─────────────────────────────────
def test_one_saved_quote_record_produces_three_dated_claims(tmp_path: Path) -> None:
    """INV-3 · measurement date ≠ document date ≠ observation date.

    Collapsing the rows into one claim dated 2025-12-31 is the failure
    `primitives.yaml` records: every measurement date then resolved to the last
    price, with every citation still resolving.
    """
    claims = banzai_claims(
        document_version_id="dv", parsed=_doc(tmp_path, QUOTES, "quotes.txt"), holding_id="h"
    )
    assert [c.claim_key for c in claims] == ["fy2023_close", "fy2024_close", "fy2025_close"]
    assert [c.issued_date for c in claims] == [
        date(2023, 12, 29),
        date(2024, 12, 31),
        date(2025, 12, 31),
    ]
    assert [c.price_per_share for c in claims] == [
        Decimal("9.90"),
        Decimal("8.80"),
        Decimal("7.70"),
    ]
    assert {c.priced_class for c in claims} == {BANZAI_PRICED_CLASS}


def test_the_fy2023_window_opens_at_the_quote_date_and_closes_at_the_year_end(
    tmp_path: Path,
) -> None:
    """INV-16 · the window is what the source states, and only FY2023 differs.

    12/29 is the last trading day of 2023, so the quote is observed two days
    before the measurement date it supports. Setting `applicable_from` to the
    year end would make the price look observed on a day the market was shut;
    setting `applicable_to` to the quote date would put it out of scope at the
    only measurement date it exists to support.
    """
    claims = banzai_claims(
        document_version_id="dv", parsed=_doc(tmp_path, QUOTES, "quotes.txt"), holding_id="h"
    )
    windows = [(c.applicable_from, c.applicable_to) for c in claims]
    assert windows[0] == (date(2023, 12, 29), date(2023, 12, 31))
    assert windows[0][0] != windows[0][1]
    assert windows[1] == (date(2024, 12, 31), date(2024, 12, 31))
    assert windows[2] == (date(2025, 12, 31), date(2025, 12, 31))


def test_each_price_is_quoted_inside_its_own_row(tmp_path: Path) -> None:
    """Three prices in one file, so a price quoted on its own says nothing.

    The citation an auditor follows has to land on the row that states the year
    as well as the price. A pattern anchored only on `\\$[\\d.]+` would resolve
    to a real passage and point at whichever row came first.
    """
    claims = banzai_claims(
        document_version_id="dv", parsed=_doc(tmp_path, QUOTES, "quotes.txt"), holding_id="h"
    )
    rows = ["12/29/2023", "12/31/2024", "12/31/2025"]
    for claim, own_row in zip(claims, rows, strict=True):
        quote = _quote(claim, "closing_price")
        assert own_row in quote
        assert [other for other in rows if other != own_row and other in quote] == []


def test_a_repeated_quote_row_is_refused_rather_than_resolved_to_the_first(
    tmp_path: Path,
) -> None:
    """A saved screen pasted twice is a real way for a `.txt` to arrive, and
    taking the first match would attach a resolving span to one of two identical
    rows with nothing downstream able to tell which was meant."""
    doubled = QUOTES.replace(
        "12/31/2024          $8.80            $352,000\n",
        "12/31/2024          $8.80            $352,000\n12/31/2024          $8.80"
        "            $352,000\n",
    )
    with pytest.raises(CitationError, match="matched 2 passages"):
        banzai_claims(
            document_version_id="dv",
            parsed=_doc(tmp_path, doubled, "quotes.txt"),
            holding_id="h",
        )


# ── Lucra: the two classifications the letter turns on ───────────────────
def test_the_term_sheet_is_non_binding_although_it_calls_itself_executed(
    tmp_path: Path,
) -> None:
    """INV-4 · `non_binding` is its own status and does not imply pro forma.

    The document says both *"this excerpt from the executed term sheet"* and
    *"Non-binding except as noted"*. Classifying on the first word would record
    `executed`, and Lucra — the position where the letter's request for executed
    documentation is unmet — would read as documented.

    The last assertion is the R1 gap in the document's own words. §7.3 makes
    `with_counsel` `partial` with `REQUEST_FROM_COUNSEL`, and it can only be
    classified that way because the sentence saying so was extracted rather
    than summarised.
    """
    claim = lucra_term_sheet_claim(
        document_version_id="dv", parsed=_doc(tmp_path, TERM_SHEET, "ts.txt"), holding_id="h"
    )
    assert claim.execution_status is ExecutionStatus.NON_BINDING
    assert claim.source_class is SourceClass.COMPANY_COMMUNICATION
    stated = _stated(claim)
    assert stated["binding_status"][0] == "Non-binding except as noted"
    assert "executed term sheet" in stated["term_sheet_provenance"][0]
    assert claim.price_per_share == Decimal("7.50")
    assert stated["executed_docs_location"][0] == (
        "on file with company counsel and have not been located in the Fund's document repository"
    )


def test_the_ceo_email_is_unexecuted_referenced_although_it_says_closed(
    tmp_path: Path,
) -> None:
    """§6.2.2 · execution status describes the artifact, not the world.

    *"We signed and closed"* is a statement about the transaction; *"Counsel is
    still finalizing the closing set"* is the statement about the file, and the
    file is what the auditor asked for.
    """
    claim = lucra_email_claim(
        document_version_id="dv", parsed=_doc(tmp_path, CEO_EMAIL, "ceo.txt"), holding_id="h"
    )
    assert claim.execution_status is ExecutionStatus.UNEXECUTED_REFERENCED
    assert claim.source_class is SourceClass.COMPANY_COMMUNICATION
    stated = _stated(claim)
    assert stated["close_statement"][0] == "we signed and closed the Series A-2 on Wednesday"
    assert stated["closing_set_status"][0] == "Counsel is still finalizing the closing set"


def test_the_ceo_email_dates_the_close_only_as_a_weekday(tmp_path: Path) -> None:
    """INV-3 · a date this system computed is not a date the source stated.

    The email says "Wednesday" and never a calendar date, so `as_of_date` is
    null. Subtracting two days from the Friday in the header would produce a
    plausible date with nothing behind it.

    INV-17 rides along: 7GC holds Series A-1 and this email prices Series A-2.
    Recording `series_a1` would be one word and no error, and the cross-class
    trigger that demands a cited policy decision would never fire.
    """
    claim = lucra_email_claim(
        document_version_id="dv", parsed=_doc(tmp_path, CEO_EMAIL, "ceo.txt"), holding_id="h"
    )
    assert claim.as_of_date is None
    assert claim.issued_date == date(2025, 10, 17)
    assert "Wednesday" in _stated(claim)["close_statement"][0]
    assert claim.priced_class == LUCRA_A2_PRICED_CLASS != LUCRA_HELD_CLASS


# ── Dream: a second claim about a round the spine already read ───────────
def test_the_closing_notice_does_not_upgrade_the_cap_table(tmp_path: Path) -> None:
    """INV-15 · one round, two artifacts, two authorities.

    `extract_dream.py` reads the pro forma table as `company_cap_table` /
    `pro_forma`. This email says the round closed and remains a company
    communication whose executed documents are still to follow. If it upgraded
    the table, the letter's pro-forma question would be answered "no positions".
    """
    claim = dream_email_claim(
        document_version_id="dv", parsed=_doc(tmp_path, CLOSING_NOTICE, "cfo.txt"), holding_id="h"
    )
    assert claim.source_class is SourceClass.COMPANY_COMMUNICATION
    assert claim.execution_status is ExecutionStatus.UNEXECUTED_REFERENCED
    assert claim.execution_status is not ExecutionStatus.PRO_FORMA
    stated = _stated(claim)
    assert stated["executed_docs_pending"][0] == (
        "executed documents will follow from counsel this week"
    )
    assert claim.priced_class == DREAM_EMAIL_PRICED_CLASS != DREAM_EMAIL_HELD_CLASS


def test_shorthand_magnitudes_are_stored_as_text_with_no_number(tmp_path: Path) -> None:
    """`$40M` states a figure to a reader and none to `cited_numeral`. A `40`
    lifted out of it would reconcile against nothing while looking cited; the
    cap table states this round's post-money in full and owns those figures."""
    claim = dream_email_claim(
        document_version_id="dv", parsed=_doc(tmp_path, CLOSING_NOTICE, "cfo.txt"), holding_id="h"
    )
    stated = _stated(claim)
    assert stated["amount_raised"] == ("$40M", None)
    assert stated["post_money_valuation"] == ("$500M", None)
    assert stated["fully_diluted_shares"] == ("40M", None)
    assert stated["price_per_share"] == ("$12.50", Decimal("12.50"))


# ── Jackpocket: the realisation, request 4 ───────────────────────────────
def test_the_merger_notice_is_an_executed_transaction_document(tmp_path: Path) -> None:
    """The merger was consummated and the paying agent states what was paid.

    This is the one document in the family whose strong envelope is honest, and
    it is worth asserting for the same reason as the others: `executed` has to
    be a decision the document supports, not a default.
    """
    claim = jackpocket_claim(
        document_version_id="dv", parsed=_doc(tmp_path, MERGER, "merger.txt"), holding_id="h"
    )
    assert claim.source_class is SourceClass.EXECUTED_TRANSACTION_DOC
    assert claim.execution_status is ExecutionStatus.EXECUTED
    assert claim.priced_class == "series_b"
    assert claim.price_per_share == Decimal("9.50")


def test_the_holder_amounts_reconcile_without_comparing_net_to_gross(
    tmp_path: Path,
) -> None:
    """V9 · `gross == shares × per-share`, with escrow and withholding separate.

    Net is read, never derived, and both zeroes are extracted: a zero that was
    assumed is indistinguishable from one the document states."""
    claim = jackpocket_claim(
        document_version_id="dv", parsed=_doc(tmp_path, MERGER, "merger.txt"), holding_id="h"
    )
    stated = _stated(claim)
    shares, per_share = stated["shares_of_record"][1], stated["consideration_per_share"][1]
    assert shares is not None and per_share is not None
    assert shares * per_share == stated["gross_consideration"][1]
    assert stated["escrow_allocation"] == ("$0.00", Decimal("0.00"))
    assert stated["tax_withholding"] == ("$0.00", Decimal("0.00"))
    assert stated["net_payment"][1] == Decimal("1900000.00")
    assert stated["effective_date"] == ("May 20, 2024", None)


# ── The price a claim carries is the price its citation states ───────────
def test_a_price_the_document_states_as_no_single_figure_is_refused(tmp_path: Path) -> None:
    """A claim priced at nothing would be a mark of zero with a resolving
    citation beside it. The refusal is loud instead."""
    malformed = CEO_EMAIL.replace("$7.25 per share", "$7.2.5 per share")
    with pytest.raises(CitationError, match="states no single figure"):
        lucra_email_claim(
            document_version_id="dv",
            parsed=_doc(tmp_path, malformed, "ceo.txt"),
            holding_id="h",
        )


def test_a_document_stating_another_date_than_the_claim_is_refused(tmp_path: Path) -> None:
    """A hand-read claim date and a document date are two places for one fact.

    The pattern is compiled from the constant, so they cannot disagree quietly:
    an email dated a week later matches nothing and the extraction fails, rather
    than producing a claim dated 17 October cited to a passage saying the 24th.
    """
    misdated = CEO_EMAIL.replace("Friday, October 17, 2025", "Friday, October 24, 2025")
    with pytest.raises(CitationError, match="pattern matched nothing"):
        lucra_email_claim(
            document_version_id="dv",
            parsed=_doc(tmp_path, misdated, "ceo.txt"),
            holding_id="h",
        )


def test_a_claim_cannot_be_priced_by_a_fact_that_was_never_extracted() -> None:
    """The other half of the same rule: naming a field that does not exist is a
    typo away, and returning `None` for it would price the claim at nothing."""
    with pytest.raises(CitationError, match="no fact named"):
        _cited_price((), "price_per_share")


# ── The real documents ───────────────────────────────────────────────────
# Every figure below was read off the page by hand. Reading them out of the
# extractor would make these tests agree with it by construction.
@_needs(ANTHROPIC_PDF)
def test_the_real_article_reports_a_valuation_and_discloses_no_terms() -> None:
    claim = anthropic_claim(document_version_id="dv", parsed=parse(ANTHROPIC_PDF), holding_id="h")
    assert _stated(claim) == {
        "publication_date": ("December 9, 2025", None),
        "headline_valuation": ("$120 Billion", None),
        "valuation_attribution": ("according to three people familiar with the matter", None),
        "terms_disclosure": ("Terms have not been publicly disclosed", None),
        "independent_review": ("has not independently reviewed the transaction documents", None),
    }
    assert claim.source_class is SourceClass.PRESS
    assert claim.price_per_share is None
    assert claim.issued_date == date(2025, 12, 9)


@_needs(BANZAI_TXT)
def test_the_real_quote_record_carries_three_year_end_closes() -> None:
    claims = banzai_claims(document_version_id="dv", parsed=parse(BANZAI_TXT), holding_id="h")
    assert [(c.issued_date, c.applicable_to, c.price_per_share) for c in claims] == [
        (date(2023, 12, 29), date(2023, 12, 31), Decimal("2.40")),
        (date(2024, 12, 31), date(2024, 12, 31), Decimal("1.10")),
        (date(2025, 12, 31), date(2025, 12, 31), Decimal("0.62")),
    ]
    assert [_stated(c)["position_value"][0] for c in claims] == [
        "$120,000",
        "$55,000",
        "$31,000",
    ]
    assert {_stated(c)["position_shares"] for c in claims} == {("50,000", Decimal("50000"))}
    assert _stated(claims[0])["quote_date"][0] == "12/29/2023"


@_needs(JACKPOCKET_PDF)
def test_the_real_merger_notice_states_the_holder_facing_amounts() -> None:
    claim = jackpocket_claim(document_version_id="dv", parsed=parse(JACKPOCKET_PDF), holding_id="h")
    stated = _stated(claim)
    assert stated["effective_date"][0] == "May 20, 2024"
    assert stated["shares_of_record"] == ("500,000", Decimal("500000"))
    assert stated["consideration_per_share"] == ("$6.20", Decimal("6.20"))
    assert stated["consideration_per_share_stated"] == ("$6.20", Decimal("6.20"))
    assert stated["gross_consideration"] == ("$3,100,000.00", Decimal("3100000.00"))
    assert stated["escrow_allocation"] == ("$0.00", Decimal("0.00"))
    assert stated["tax_withholding"] == ("$0.00", Decimal("0.00"))
    assert stated["net_payment"] == ("$3,100,000.00", Decimal("3100000.00"))
    assert stated["payment_date"][0] == "May 24, 2024"
    assert claim.execution_status is ExecutionStatus.EXECUTED


@_needs(LUCRA_TERM_SHEET_PDF)
def test_the_real_term_sheet_is_non_binding() -> None:
    claim = lucra_term_sheet_claim(
        document_version_id="dv", parsed=parse(LUCRA_TERM_SHEET_PDF), holding_id="h"
    )
    stated = _stated(claim)
    assert stated["binding_status"][0] == "Non-binding except as noted"
    assert stated["price_per_share"] == ("$2.00", Decimal("2.00"))
    assert stated["pre_money_valuation"] == ("$48,000,000", Decimal("48000000"))
    assert stated["post_money_valuation"] == ("$60,000,000", Decimal("60000000"))
    assert stated["fund_commitment"] == ("$1,500,000", Decimal("1500000"))
    assert stated["anticipated_closing"][0] == "June 28, 2024"
    assert stated["executed_docs_location"][0] == (
        "on file with company counsel and have not been located in the Fund's document repository"
    )
    assert claim.execution_status is ExecutionStatus.NON_BINDING
    assert claim.issued_date == date(2024, 5, 20)


@_needs(LUCRA_EMAIL_TXT)
def test_the_real_ceo_email_is_unexecuted_referenced() -> None:
    claim = lucra_email_claim(
        document_version_id="dv", parsed=parse(LUCRA_EMAIL_TXT), holding_id="h"
    )
    stated = _stated(claim)
    assert stated["price_per_share"] == ("$3.00", Decimal("3.00"))
    assert stated["post_money_valuation"] == ("$95M", None)
    assert stated["closing_set_status"][0] == "Counsel is still finalizing the closing set"
    assert claim.execution_status is ExecutionStatus.UNEXECUTED_REFERENCED
    assert claim.priced_class == LUCRA_A2_PRICED_CLASS
    assert claim.issued_date == date(2025, 10, 17)
    assert claim.as_of_date is None


@_needs(DREAM_EMAIL_TXT)
def test_the_real_closing_notice_leaves_the_cap_table_pro_forma() -> None:
    claim = dream_email_claim(
        document_version_id="dv", parsed=parse(DREAM_EMAIL_TXT), holding_id="h"
    )
    stated = _stated(claim)
    assert stated["price_per_share"] == ("$8.00", Decimal("8.00"))
    assert stated["amount_raised"] == ("$80M", None)
    assert stated["post_money_valuation"] == ("$800M", None)
    assert stated["fully_diluted_shares"] == ("100M", None)
    assert stated["closing_date_stated"][0] == "Friday, November 14"
    assert stated["attachment_status"][0] == (
        "The pro forma capitalization table and closing set are attached"
    )
    assert claim.execution_status is ExecutionStatus.UNEXECUTED_REFERENCED
    assert claim.issued_date == date(2025, 11, 17)


# ── One document, three claims, all the way to Postgres ──────────────────
@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
@_needs(BANZAI_TXT)
def test_three_banzai_claims_store_against_one_document_version(
    conn: Conn, seed: dict[str, str]
) -> None:
    """One `document_version`, three `claim` rows, each with its own window.

    The round trip is what proves the three-claim shape survives the schema:
    `claim.id` is `holding:claim_key`, so a family that reused one key would
    collide here rather than quietly overwrite. Each citation is re-resolved by
    `store_claim` and again by the trigger against the text Postgres holds.
    """
    parsed = parse(BANZAI_TXT)
    version_id = store_document(conn, parsed)
    for claim in banzai_claims(document_version_id=version_id, parsed=parsed, holding_id=seed["h"]):
        store_claim(conn, version_id, claim, parsed.canonical_text)

    rows = conn.execute(
        "select claim_key, source_class, execution_status, issued_date, applicable_from,"
        " applicable_to, priced_class, price_per_share from claim"
        " where document_version_id = %s order by issued_date",
        (version_id,),
    ).fetchall()
    assert [r[0] for r in rows] == ["fy2023_close", "fy2024_close", "fy2025_close"]
    assert {r[1] for r in rows} == {SourceClass.PUBLIC_MARKET_QUOTE.value}
    assert {r[2] for r in rows} == {ExecutionStatus.NOT_APPLICABLE.value}
    assert [(r[3], r[4], r[5]) for r in rows] == [
        (date(2023, 12, 29), date(2023, 12, 29), date(2023, 12, 31)),
        (date(2024, 12, 31), date(2024, 12, 31), date(2024, 12, 31)),
        (date(2025, 12, 31), date(2025, 12, 31), date(2025, 12, 31)),
    ]
    assert [r[7] for r in rows] == [Decimal("2.40"), Decimal("1.10"), Decimal("0.62")]

    stored = conn.execute(
        "select value_text from extracted_fact f join claim c on c.id = f.claim_id"
        " where c.document_version_id = %s and f.field_name = 'closing_price'"
        " order by c.issued_date",
        (version_id,),
    ).fetchall()
    assert [r[0] for r in stored] == ["$2.40", "$1.10", "$0.62"]
    conn.rollback()
