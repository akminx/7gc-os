"""Family C — valuation memoranda and administrator statements.

Split as `test_document_parse.py` splits: *a guard that skips because the
corpus is private has not failed*, so the rules run everywhere on synthetic text
and only the figures are gated on the real PDFs.

Every figure asserted against a real document is hand-transcribed from the PDF
and written here as a literal. Reading them back out of the extractor would
produce a test that agrees with the code by construction.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ingest.documents.claims import FactDraft, cited_fact, store_claim, store_document
from ingest.documents.extract_memo import (
    _CAPSULE_MEMO,
    _MERIDIAN_EMAIL,
    _MOONFARE_FX,
    _MOONFARE_MEMO,
    JIO_STATEMENT_DATES,
    MERIDIAN_DELIVERY_DATE,
    _statement_patterns,
    capsule_memo_claim,
    capsule_memo_facts,
    jio_statement_claim,
    jio_statement_facts,
    meridian_email_claim,
    meridian_email_facts,
    moonfare_fx_claim,
    moonfare_fx_facts,
    moonfare_memo_claim,
    moonfare_memo_facts,
)
from ingest.documents.parse import ParsedDocument, parse
from packages.contracts.citations import CitationError, cited_numeral, resolves_in
from packages.contracts.enums import ExecutionStatus, SourceClass
from packages.contracts.models import Citation
from tests.schema_helpers import DSN, Conn

PORTFOLIO = Path("7GC Audit Case Study/02_Portfolio Documentation")
MOONFARE_MEMO_PDF = PORTFOLIO / (
    "Moonfare/Moonfare - Third-Party Valuation Memorandum - FY2023 (December 31, 2023).pdf"
)
MOONFARE_FX_PDF = PORTFOLIO / (
    "Moonfare/Moonfare - FX Re-measurement Memo - FY2024 (December 31, 2024).pdf"
)
CAPSULE_MEMO_PDF = PORTFOLIO / (
    "Capsule/Capsule - Third-Party Valuation Memorandum - FY2022 (December 31, 2022).pdf"
)
MERIDIAN_EMAIL_TXT = PORTFOLIO / (
    "Jio/Email - Meridian Fund Services - Annual Capital Account Statement (January 30, 2026).txt"
)


def statement_pdf(as_of: date) -> Path:
    stem = "Jio/Horizon Access Fund IV (Jio Feeder) - Capital Account Statement"
    return PORTFOLIO / f"{stem} - 12.31.{as_of.year}.pdf"


needs_corpus = pytest.mark.skipif(
    not MOONFARE_MEMO_PDF.exists(), reason="case-study documents are not in the repository"
)
needs_db = pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")


def _doc(tmp_path: Path, body: str, name: str = "synthetic.txt") -> ParsedDocument:
    source = tmp_path / name
    source.write_bytes(body.encode("utf-8"))
    return parse(source)


#: The Meridian email's shape — the labels, dates and sentences the patterns key
#: on, and nothing else. Not the corpus document: it exists so the INV-15
#: classification is proved where the corpus is absent, which is the only place
#: a classification guard can be shown to fail on its own.
SYNTHETIC_EMAIL = (
    "From: Investor Services\n"
    "Date: Friday, January 30, 2026, 6:02 AM ET\n"
    "\n"
    "Please find attached your capital account statement for Horizon Access Fund IV "
    "(Jio Feeder), L.P. as of December 31, 2025.\n"
    "\n"
    "Statements as of each fiscal year end are delivered annually via this email address "
    "of record. Prior-period statements are available upon request from Investor Services.\n"
    "\n"
    "Kind regards,\n"
    "Investor Services\n"
    "Meridian Fund Services (Cayman) Ltd.\n"
    "\n"
    "Attachment: Horizon Access Fund IV (Jio Feeder) - Capital Account Statement - "
    "12.31.2025.pdf\n"
)


def synthetic_statement(as_of: date) -> str:
    """One capital account statement's shape, for any year end. The three real
    statements differ only in the year, which is what makes a mis-anchored
    pattern invisible: every amount is identical across all three."""
    return (
        "MERIDIAN FUND SERVICES (CAYMAN) LTD.\n"
        "Administrator to Horizon Access Fund IV (Jio Feeder), L.P. — Capital Account "
        f"Statement — As of December 31,\n{as_of.year} — Delivered via email to investor "
        "of record\n"
        "\n"
        "Investor of Record: 7GC Fund I, L.P.\n"
        "     Capital commitment                             $1,000,000.00\n"
        "     Contributed capital (inception to date)        $1,000,000.00\n"
        "     Distributions (inception to date)                      $0.00\n"
        "     Net asset value of capital account             $1,000,000.00\n"
        "     Unfunded commitment                                    $0.00\n"
        "\n"
        "The Partnership holds a single underlying position: an indirect interest in Jio "
        "Platforms Limited, acquired July 2020. The\nPartnership's valuation of the "
        "underlying position is determined in accordance with the Partnership's valuation "
        "policy,\nbased on the price of the most recent observable financing round of the "
        "underlying company, adjusted for the\nPartnership's fees and expenses where "
        "applicable.\n"
        "Figures are unaudited. Statements are issued annually as of the Partnership's "
        "fiscal year end and delivered to the investor's email of record in PDF format.\n"
    )


#: Clearwater's FY2023 Moonfare memo, in shape. Added when the basis patterns
#: went in: both Moonfare documents were reached only through `@needs_corpus`,
#: so every guard over them SKIPPED in a checkout without the case study — and a
#: guard that skips because the corpus is private has not failed.
SYNTHETIC_MOONFARE_MEMO = (
    "Independent Valuation Memorandum — Subject: 7GC Fund II, L.P. holding in Moonfare "
    "GmbH — Measurement\nDate: December 31, 2023 — Engagement ref. CVA-2024-0031\n"
    "\n"
    "CVA was engaged to estimate the fair value of the Fund's EUR-denominated interest. "
    "The Fund acquired the interest in\nMarch 2023 for consideration of $1,000,000, "
    "corresponding to a EUR-denominated interest of EUR 950,000 at the\nexchange rate "
    "prevailing at acquisition.\n"
    "\n"
    "2. Valuation Approach\n"
    "Calibration to most recent financing. The Company completed an equity financing in "
    "March 2023 at a post-money\nvaluation of €555,000,000, in which the Fund "
    "participated. We identified no subsequent financing rounds, secondary\ntransactions "
    "or other observable market inputs before the Measurement Date. Accordingly, we\n"
    "concluded the March 2023 round price remains the best indication of fair value for "
    "the EUR-denominated interest at the\nMeasurement Date.\n"
    "\n"
    "      EUR-denominated interest (last-round basis)          EUR 950,000\n"
    "      EUR/USD closing rate, 12/31/2023                          1.0526\n"
    "      Concluded fair value (USD, rounded)                   $1,000,000\n"
    "\n"
    "This memorandum was prepared for the FY2023 financial statement audit of the Fund "
    "and should not be relied upon for subsequent\nmeasurement dates without update.\n"
)

#: 7GC Fund Operations' FY2024 re-measurement of the same interest, in shape.
SYNTHETIC_MOONFARE_FX = (
    "7GC — FUND OPERATIONS\n"
    "Internal Memorandum — FX Re-measurement of EUR-Denominated Holding — Measurement "
    "Date: December\n31, 2024\n"
    "\n"
    "     EUR-denominated interest (unchanged, last-round basis)      EUR 950,000\n"
    "     EUR/USD closing rate, 12/31/2024                                 1.1037\n"
    "     USD carrying value, 12/31/2024                               $1,048,515\n"
    "     Prior USD carrying value (entry, March 2023: $1,000,000)     $1,000,000\n"
    "     FX re-measurement adjustment                                   +$48,515\n"
    "\n"
    "Basis\n"
    "The underlying EUR value of the interest is unchanged and remains based on the "
    "company's most recent equity\nfinancing (March 2023), consistent with the FY2023 "
    "third-party valuation memorandum. The USD movement is\nattributable solely to the "
    "change in the EUR/USD exchange rate between the measurement dates. The interest\n"
    "will be re-measured at the closing rate at each future measurement date.\n"
    "\n"
    "Prepared by Fund Operations; reviewed by the CFO.\n"
)

#: Capsule's shape, including the sentence INV-16 turns on.
SYNTHETIC_CAPSULE = (
    "Independent Valuation Memorandum — Subject: 7GC Fund I, L.P. holding in Capsule — "
    "Measurement Date:\nDecember 31, 2022 — Engagement ref. CVA-2023-0187\n"
    "\n"
    "CVA was engaged to estimate the fair value of the Fund's holding of 500,000 shares "
    "of Series B Preferred Stock of Capsule as of the Measurement Date. The Fund's "
    "original purchase was\ncompleted in June 2019 at $4.00 per share ($2,000,000 "
    "aggregate).\n"
    "\n"
    "In Q3 2022 the Company closed a $9,000,000 bridge financing in the form of "
    "convertible notes.\n"
    "\n"
    # §3 and §4 are both here because the memo names approaches it REJECTED
    # beside the one it used, and a basis read out of the wrong section reports
    # a ground the valuer declined to stand on. The heading is the only thing
    # that tells them apart, which is why it is inside the citation.
    "3. Valuation Approaches Considered\n"
    "Market approach — backsolve. We considered a backsolve to the Q3 2022 bridge "
    "financing. Because the bridge was\nissued as convertible debt to insiders under "
    "distressed conditions, we applied it as a calibration input rather than a primary\n"
    "indication. Income approach. Not relied upon given the limited reliability of "
    "long-range forecasts at the Measurement Date.\n"
    "\n"
    "4. Selected Approach and Allocation\n"
    "We estimated total equity value using a hybrid of the calibrated backsolve and the "
    "guideline multiple contraction applied to\nthe Company's revised revenue plan, and "
    "allocated value across the capital structure using an option pricing model\n(OPM).\n"
    "\n"
    "      Concluded fair value per Series B Preferred share             $1.20\n"
    "      Fund holding (500,000 shares)                             $600,000\n"
    "      Implied change vs. original purchase price ($4.00)         (70.0%)\n"
    "\n"
    "This memorandum was prepared solely for the FY2022 financial statement audit of the "
    "Fund and may not be relied upon for any other\npurpose or for any subsequent "
    "measurement date without a written update from CVA. No update has been commissioned "
    "as of the date\nof this excerpt.\n"
)


# ── The patterns, as artifacts ───────────────────────────────────────────
def test_every_pattern_captures_a_group_named_value() -> None:
    """`cited_fact` reads `value` out of the same match it cited. Cheap, and it
    covers every pattern including the ones only the real documents reach."""
    dicts = {
        "moonfare_memo": _MOONFARE_MEMO,
        "moonfare_fx": _MOONFARE_FX,
        "capsule_memo": _CAPSULE_MEMO,
        "meridian_email": _MERIDIAN_EMAIL,
        "jio_statement": _statement_patterns(date(2025, 12, 31)),
    }
    for family, patterns in dicts.items():
        assert patterns, family
        for field_name, pattern in patterns.items():
            assert "value" in pattern.groupindex, f"{family}.{field_name}"


def test_a_row_pattern_that_quotes_the_label_and_the_column_is_refused(tmp_path: Path) -> None:
    """Why `prior_usd_carrying_value` cites the parenthetical, not the row.

    That row states `$1,000,000` twice — in the label and in the Value column —
    so a whole-row citation does not say which occurrence it means. The number
    is right, the span resolves, and the auditor is shown two figures as one.
    """
    doc = _doc(
        tmp_path,
        "     Prior USD carrying value (entry, March 2023: $1,000,000)      $1,000,000\n",
    )
    with pytest.raises(CitationError, match="not inside the passage cited"):
        cited_fact(
            document_version_id="dv",
            canonical_text=doc.canonical_text,
            field_name="prior_usd_carrying_value",
            pattern=re.compile(r"Prior USD carrying value .*?\s+(?P<value>\$[\d,]+)\n"),
        )


def test_a_statement_pattern_built_for_one_year_matches_no_other(tmp_path: Path) -> None:
    """The guard that keeps three near-identical statements apart. Every amount
    is the same in all three years, so a pattern matching any of them reads the
    right figures under the wrong claim and nothing downstream can notice — not
    the value check, not the citation, not the trigger."""
    doc = _doc(tmp_path, synthetic_statement(date(2023, 12, 31)))
    assert jio_statement_facts("dv", doc, date(2023, 12, 31))
    for wrong in (date(2024, 12, 31), date(2025, 12, 31)):
        with pytest.raises(CitationError, match="pattern matched nothing"):
            jio_statement_facts("dv", doc, wrong)


def test_the_row_label_is_what_tells_three_identical_amounts_apart(tmp_path: Path) -> None:
    """`$1,000,000.00` appears in three rows and `$0.00` in two. Each fact must
    cite the row that names it, not the first row that carries the figure."""
    as_of = date(2024, 12, 31)
    doc = _doc(tmp_path, synthetic_statement(as_of))
    quoted = {f.field_name: f.citation.quote for f in jio_statement_facts("dv", doc, as_of)}
    assert quoted["capital_commitment"].startswith("Capital commitment")
    assert quoted["contributed_capital"].startswith("Contributed capital")
    assert quoted["net_asset_value"].startswith("Net asset value of capital account")
    assert quoted["distributions"].startswith("Distributions")
    assert quoted["unfunded_commitment"].startswith("Unfunded commitment")


# ── INV-15 · authority is read off the speaker, not the envelope ─────────
def test_the_meridian_email_is_an_administrator_statement_not_a_communication(
    tmp_path: Path,
) -> None:
    """The point of this family, and a collapse that costs one word.

    INV-15: *"Email is an envelope. Meridian's email carries an administrator
    statement."* Mapping anything arriving as email to `company_communication`
    passes the whole matrix while filing Jio's strongest evidence weakest.
    """
    doc = _doc(tmp_path, SYNTHETIC_EMAIL, "email.txt")
    claim = meridian_email_claim(document_version_id="dv", parsed=doc, holding_id="h")
    assert claim.source_class is SourceClass.ADMINISTRATOR_STATEMENT
    # Through `.value`: `is not` between two enum members is settled statically
    # by mypy, and the collapse guarded against is a column value, not a type.
    assert claim.source_class.value != SourceClass.COMPANY_COMMUNICATION.value
    assert claim.execution_status is ExecutionStatus.NOT_APPLICABLE


def test_a_txt_envelope_is_parsed_by_the_same_path_as_a_pdf(tmp_path: Path) -> None:
    """SPEC §8 pins one extractor per suffix and the write path knows nothing
    about either. The container is recorded and never consulted."""
    doc = _doc(tmp_path, SYNTHETIC_EMAIL, "email.txt")
    assert doc.extractor == "utf8-verbatim@1"
    assert doc.page_count == 1
    assert len(meridian_email_facts("dv", doc)) == len(_MERIDIAN_EMAIL)


# ── INV-3 · three instants, three fields ─────────────────────────────────
def test_the_delivery_date_is_recorded_without_moving_the_as_of_date(tmp_path: Path) -> None:
    """0004 reads `received_date` to set `is_subsequent`; with the two dates
    collapsed the truthful record was rejected and the false one committed.

    Issued the day the email was sent; dating it 31 December made `issued` and
    `as_of` identical and left the email not bearing its own date.
    """
    doc = _doc(tmp_path, SYNTHETIC_EMAIL, "email.txt")
    claim = meridian_email_claim(document_version_id="dv", parsed=doc, holding_id="h")
    assert claim.as_of_date == date(2025, 12, 31)
    assert claim.issued_date == MERIDIAN_DELIVERY_DATE == date(2026, 1, 30)
    assert claim.received_date == MERIDIAN_DELIVERY_DATE
    assert claim.issued_date > claim.as_of_date
    assert claim.applicable_from == MERIDIAN_DELIVERY_DATE
    assert claim.applicable_to is None


def test_only_the_statement_whose_delivery_the_corpus_dates_carries_one(tmp_path: Path) -> None:
    """Nothing in the corpus dates FY2023's or FY2024's delivery, and inventing
    a receipt date to fill the column is the collapse 0004 names."""
    received = {}
    for as_of in JIO_STATEMENT_DATES:
        doc = _doc(tmp_path, synthetic_statement(as_of), f"stmt{as_of.year}.txt")
        claim = jio_statement_claim(
            document_version_id="dv", parsed=doc, holding_id="h", as_of=as_of
        )
        received[as_of] = claim.received_date
        assert claim.as_of_date == claim.issued_date == as_of
        assert claim.source_class is SourceClass.ADMINISTRATOR_STATEMENT
    assert received == {
        date(2023, 12, 31): None,
        date(2024, 12, 31): None,
        date(2025, 12, 31): date(2026, 1, 30),
    }


# ── INV-16 · the window is the source's, not the calendar's ─────────────
def test_capsules_stated_no_reliance_scope_closes_its_window(tmp_path: Path) -> None:
    """F3: the memo is carried at $600,000 through FY2023, FY2024 and FY2025.
    Each link can be made deliberately with every date field correct, and each
    is invalid because the memo says so. Leaving `applicable_to` open is the
    cheapest collapse of INV-16 — one deletion, no error anywhere."""
    doc = _doc(tmp_path, SYNTHETIC_CAPSULE, "capsule.txt")
    claim = capsule_memo_claim(document_version_id="dv", parsed=doc, holding_id="h")
    assert claim.applicable_from == claim.applicable_to == date(2022, 12, 31)

    scope = {f.field_name: f.value_text for f in claim.facts}
    assert "may not be relied upon" in scope["no_reliance_scope"]
    assert "any subsequent measurement date" in scope["no_reliance_scope"]
    assert scope["update_status"].startswith("No update has been commissioned")


def test_the_capsule_memo_prices_the_class_it_states(tmp_path: Path) -> None:
    """Nothing here is cross-class, but `priced_class` is recorded regardless:
    a stated price beside a NULL class is what the trigger refuses. `(70.0%)`
    is a 70% fall, and that convention has to survive into `value_numeric` or
    the packet reports the opposite of the memo."""
    doc = _doc(tmp_path, SYNTHETIC_CAPSULE, "capsule.txt")
    claim = capsule_memo_claim(document_version_id="dv", parsed=doc, holding_id="h")
    assert claim.priced_class == "series_b"
    assert claim.price_per_share == Decimal("1.20")
    assert claim.source_class is SourceClass.THIRD_PARTY_VALUATION_MEMO
    facts = {f.field_name: f for f in capsule_memo_facts("dv", doc)}
    assert facts["implied_change_vs_purchase"].value_text == "(70.0%)"
    assert facts["implied_change_vs_purchase"].value_numeric == cited_numeral("(70.0%)")
    assert facts["implied_change_vs_purchase"].value_numeric == Decimal("-70.0")


# ── ¶2 · the ground a value rests on, where a document states one ───────
# ¶2 has two limbs and which one governs a row depends on what the mark is
# BASED ON, so `mark.basis` decides how every ¶2 figure is scored. It is NULL
# for all 72 marks, and the temptation is to fill it from the evidence on file:
# there is a cap table, so the mark is round-based. That reasoning cannot come
# out wrong — the answer justifies itself — and it renders as a determined fact
# an auditor cannot tell from a real one.
#
# So the basis is READ, never inferred, and the guards below are about the two
# ways reading it goes wrong: citing a sentence that states something adjacent
# (an approach considered and declined, an absence of rounds, a cost basis for
# periods this document raises no claim for), and inventing one where the
# document is silent. Four of this family's seven documents state a basis. The
# other three do not, and `test_a_document_that_states_no_basis_produces_none`
# is what keeps that a finding rather than a gap someone later fills in.
def test_the_jio_basis_says_whose_it_is_and_what_was_done_to_it(tmp_path: Path) -> None:
    """The Partnership's ground for the underlying position, not 7GC's for the
    feeder mark — and a round price ADJUSTED, not a round price.

    Cited bare, "based on the price of the most recent observable financing
    round" reads as the fund's own basis and as an unadjusted round price.
    Neither is what the statement says, and both are the reading that makes the
    account look like cleaner evidence than it is.
    """
    as_of = date(2024, 12, 31)
    doc = _doc(tmp_path, synthetic_statement(as_of), "stmt.txt")
    fact = {f.field_name: f for f in jio_statement_facts("dv", doc, as_of)}[
        "valuation_basis_stated"
    ]
    assert "Partnership's valuation of the underlying position" in fact.citation.quote
    assert "in accordance with the Partnership's valuation policy" in fact.citation.quote
    assert fact.value_text.startswith("based on the price of the most recent observable")
    assert fact.value_text.endswith("Partnership's fees and expenses where applicable.")
    assert "adjusted for the" in fact.value_text


def test_the_moonfare_basis_is_the_conclusion_and_not_the_search_before_it(
    tmp_path: Path,
) -> None:
    """§2 says two things and only one of them is a basis.

    *"We identified no subsequent financing rounds, secondary transactions or
    other observable market inputs"* is an ABSENCE — ¶3's subject, the age and
    scope of the support, which this corpus already answers with
    `no_subsequent_round_of_record`. The basis is the sentence that says what
    the concluded value rests ON, and citing the absence for it would file a
    ¶3 fact under ¶2 while reporting that the memo based its value on having
    found nothing.
    """
    doc = _doc(tmp_path, SYNTHETIC_MOONFARE_MEMO, "memo.txt")
    fact = {f.field_name: f for f in moonfare_memo_facts("dv", doc)}["valuation_basis_stated"]
    assert fact.value_text.startswith("concluded the March 2023 round price")
    assert "best indication of fair value" in fact.value_text
    assert "identified no subsequent" not in fact.citation.quote
    assert fact.value_numeric is None


def test_the_fx_memo_basis_carries_the_word_that_dates_it(tmp_path: Path) -> None:
    """A 2023 ground under a 2024 measurement date, and the memo says so.

    The quote reaches back to *"is unchanged and"* deliberately. Capturing only
    "remains based on the company's most recent equity financing (March 2023)"
    would still resolve and would still be true, and an auditor reading it
    beside a 12/31/2024 measurement date would have to work out for himself
    that twenty-one months passed and nothing was re-priced. The memo does not
    make him: it states it in the same sentence.
    """
    doc = _doc(tmp_path, SYNTHETIC_MOONFARE_FX, "fx.txt")
    stated = {f.field_name: f for f in moonfare_fx_facts("dv", doc)}
    fact = stated["valuation_basis_stated"]
    assert "is unchanged and" in fact.citation.quote
    assert "(March 2023)" in fact.value_text
    # The measurement date is 2024's and the ground is 2023's. Two different
    # years in one claim is the whole content of this document.
    assert "2024" in stated["measurement_date"].value_text
    assert "2024" not in fact.value_text


def test_the_capsule_basis_is_the_selected_approach_and_not_a_rejected_one(
    tmp_path: Path,
) -> None:
    """The corpus's only model-based mark, and its sharpest mis-citation.

    §3 "Valuation Approaches Considered" lists a backsolve demoted to *"a
    calibration input rather than a primary indication"* and an income approach
    *"Not relied upon"*. Both are grammatical basis sentences about this
    valuation; neither is the basis. The section heading is inside the citation
    because it is the only thing in the passage that tells them apart, and a
    basis read out of §3 would report Capsule's $600,000 as resting on ground
    Clearwater explicitly refused.
    """
    doc = _doc(tmp_path, SYNTHETIC_CAPSULE, "capsule.txt")
    fact = {f.field_name: f for f in capsule_memo_facts("dv", doc)}["valuation_basis_stated"]
    assert fact.citation.quote.startswith("4. Selected Approach and Allocation")
    assert "a hybrid of the calibrated backsolve" in fact.value_text
    for rejected in ("Not relied upon", "rather than a primary", "Approaches Considered"):
        assert rejected not in fact.value_text
    # Rejected approaches are in the document and must stay unread by this
    # field, so the guard checks the section it did NOT come from is present.
    assert "3. Valuation Approaches Considered" in doc.canonical_text


def test_a_document_that_states_no_basis_produces_none(tmp_path: Path) -> None:
    """The silence, which is as much the deliverable as the four extractions.

    Meridian's covering email transmits a statement that states a basis and
    states none itself, and that is the ordinary case in this corpus rather
    than the exception. Sixty-odd marks have no basis sentence anywhere behind
    them; leaving them NULL is a finding about what the fund holds, and the way
    that finding dies is a later pattern that reads a basis out of a document
    that never gave one.
    """
    doc = _doc(tmp_path, SYNTHETIC_EMAIL, "email.txt")
    assert "valuation_basis_stated" not in {f.field_name for f in meridian_email_facts("dv", doc)}
    # And no basis-shaped words are in it to read one out of.
    assert "Basis" not in doc.canonical_text
    assert "based on" not in doc.canonical_text


# ── The real documents ───────────────────────────────────────────────────
#: Hand-transcribed from each PDF. `None` where the passage states no single
#: figure — a wrapped date, a pair, a sentence — because a silent zero is worse.
MOONFARE_MEMO_EXPECTED: dict[str, tuple[str, str | None]] = {
    "measurement_date": ("December 31, 2023", None),
    "engagement_reference": ("CVA-2024-0031", None),
    "acquisition_consideration_usd": ("$1,000,000", "1000000"),
    "eur_interest_at_acquisition": ("950,000", "950000"),
    "post_money_valuation_eur": ("555,000,000", "555000000"),
    "eur_interest_last_round_basis": ("950,000", "950000"),
    "currency_pair": ("EUR/USD", None),
    "fx_rate_effective_date": ("12/31/2023", None),
    "fx_rate": ("1.0526", "1.0526"),
    "concluded_fair_value_usd": ("$1,000,000", "1000000"),
    "reliance_scope": (
        "should not be relied upon for subsequent\nmeasurement dates without update.",
        None,
    ),
    "valuation_basis_stated": (
        "concluded the March 2023 round price remains the best indication of fair value "
        "for the EUR-denominated interest at the\nMeasurement Date.",
        None,
    ),
}

MOONFARE_FX_EXPECTED: dict[str, tuple[str, str | None]] = {
    # The header wraps mid-date, so the quoted form carries the newline.
    "measurement_date": ("December\n31, 2024", None),
    "preparer": ("Prepared by Fund Operations; reviewed by the CFO.", None),
    "eur_interest_unchanged": ("950,000", "950000"),
    "currency_pair": ("EUR/USD", None),
    "fx_rate_effective_date": ("12/31/2024", None),
    "fx_rate": ("1.1037", "1.1037"),
    "usd_carrying_value": ("$1,048,515", "1048515"),
    "prior_usd_carrying_value": ("$1,000,000", "1000000"),
    # The `+` stays in the quote; the figure is the magnitude.
    "fx_remeasurement_adjustment": ("$48,515", "48515"),
    "valuation_basis_stated": (
        "remains based on the company's most recent equity\nfinancing (March 2023)",
        None,
    ),
    "basis_reference": ("consistent with the FY2023 third-party valuation memorandum.", None),
    "remeasurement_scope": (
        "The interest\nwill be re-measured at the closing rate at each future measurement date.",
        None,
    ),
}

CAPSULE_EXPECTED: dict[str, tuple[str, str | None]] = {
    "measurement_date": ("December 31, 2022", None),
    "engagement_reference": ("CVA-2023-0187", None),
    "shares_held": ("500,000", "500000"),
    "security_class_held": ("Series B Preferred Stock", None),
    "original_purchase_pps": ("$4.00", "4.00"),
    "original_purchase_aggregate": ("$2,000,000", "2000000"),
    "bridge_financing_amount": ("$9,000,000", "9000000"),
    "valuation_basis_stated": (
        "We estimated total equity value using a hybrid of the calibrated backsolve and "
        "the guideline multiple contraction applied to\nthe Company's revised revenue plan",
        None,
    ),
    "concluded_fair_value_per_share": ("$1.20", "1.20"),
    "fund_holding_value": ("$600,000", "600000"),
    "implied_change_vs_purchase": ("(70.0%)", "-70.0"),
    "no_reliance_scope": (
        "may not be relied upon for any other\npurpose or for any subsequent measurement "
        "date without a written update from CVA.",
        None,
    ),
    "update_status": ("No update has been commissioned as of the date\nof this excerpt.", None),
}

MERIDIAN_EXPECTED: dict[str, tuple[str, str | None]] = {
    "delivery_date": ("Friday, January 30, 2026, 6:02 AM ET", None),
    "administrator": ("Meridian Fund Services (Cayman) Ltd.", None),
    "statement_as_of_date": ("December 31, 2025", None),
    "attachment": (
        "Horizon Access Fund IV (Jio Feeder) - Capital Account Statement - 12.31.2025.pdf",
        None,
    ),
    "delivery_cadence": (
        "Statements as of each fiscal year end are delivered annually via this email "
        "address of record.",
        None,
    ),
    "prior_period_availability": (
        "Prior-period statements are available upon request from Investor Services.",
        None,
    ),
}


def statement_expected(as_of: date) -> dict[str, tuple[str, str | None]]:
    """The same five amounts in all three years — the hazard, not an oversight."""
    return {
        "as_of_date": (f"December 31,\n{as_of.year}", None),
        "administrator": ("MERIDIAN FUND SERVICES (CAYMAN) LTD.", None),
        "partnership": ("Horizon Access Fund IV (Jio Feeder), L.P.", None),
        "investor_of_record": ("7GC Fund I, L.P.", None),
        "capital_commitment": ("$1,000,000.00", "1000000.00"),
        "contributed_capital": ("$1,000,000.00", "1000000.00"),
        "distributions": ("$0.00", "0.00"),
        "net_asset_value": ("$1,000,000.00", "1000000.00"),
        "unfunded_commitment": ("$0.00", "0.00"),
        "underlying_position": (
            "an indirect interest in Jio Platforms Limited, acquired July 2020.",
            None,
        ),
        # The fee-and-expense adjustment is part of the value, not decoration in
        # the quote: the Partnership does not state the account AS the round
        # price, it states it as the round price adjusted.
        "valuation_basis_stated": (
            "based on the price of the most recent observable financing round of the "
            "underlying company, adjusted for the\nPartnership's fees and expenses "
            "where applicable.",
            None,
        ),
        "audit_status": ("Figures are unaudited.", None),
        "issuance_cadence": (
            "Statements are issued annually as of the Partnership's fiscal year end",
            None,
        ),
    }


def _check(facts: tuple[FactDraft, ...], expected: dict[str, tuple[str, str | None]]) -> None:
    read = {f.field_name: f for f in facts}
    assert set(read) == set(expected)
    for field_name, (want_text, want_number) in expected.items():
        fact = read[field_name]
        assert fact.value_text == want_text, field_name
        want = None if want_number is None else Decimal(want_number)
        assert fact.value_numeric == want, field_name
        assert fact.value_text in fact.citation.quote, field_name


@needs_corpus
def test_the_moonfare_memo_states_these_figures() -> None:
    parsed = parse(MOONFARE_MEMO_PDF)
    _check(moonfare_memo_facts("dv", parsed), MOONFARE_MEMO_EXPECTED)
    claim = moonfare_memo_claim(document_version_id="dv", parsed=parsed, holding_id="h")
    assert claim.source_class is SourceClass.THIRD_PARTY_VALUATION_MEMO
    # §5 · "should not be relied upon for subsequent measurement dates".
    assert claim.applicable_from == claim.applicable_to == date(2023, 12, 31)


@needs_corpus
def test_the_moonfare_fx_memo_states_a_rate_a_pair_and_two_amounts() -> None:
    """SPEC §8 V8 recomputes and classifies a variance rather than asserting
    equality, and it is a validator. Nothing here multiplies anything: the memo
    states EUR 950,000, EUR/USD 1.1037 at 12/31/2024, $1,048,515 and a prior
    $1,000,000, and those are what is recorded."""
    parsed = parse(MOONFARE_FX_PDF)
    _check(moonfare_fx_facts("dv", parsed), MOONFARE_FX_EXPECTED)
    claim = moonfare_fx_claim(document_version_id="dv", parsed=parsed, holding_id="h")
    # "Prepared by Fund Operations" is not third-party evidence, and
    # INVARIANTS.md counts the corpus's third-party memos as two.
    assert claim.source_class is SourceClass.FUND_INTERNAL_RECORD
    assert claim.applicable_to == date(2024, 12, 31)


@needs_corpus
def test_the_capsule_memo_states_these_figures() -> None:
    parsed = parse(CAPSULE_MEMO_PDF)
    _check(capsule_memo_facts("dv", parsed), CAPSULE_EXPECTED)


@needs_corpus
@pytest.mark.parametrize("as_of", JIO_STATEMENT_DATES)
def test_each_jio_statement_states_its_own_years_capital_account(as_of: date) -> None:
    parsed = parse(statement_pdf(as_of))
    _check(jio_statement_facts("dv", parsed, as_of), statement_expected(as_of))


@needs_corpus
def test_the_meridian_email_states_these_figures() -> None:
    parsed = parse(MERIDIAN_EMAIL_TXT)
    _check(meridian_email_facts("dv", parsed), MERIDIAN_EXPECTED)


@needs_corpus
def test_the_real_capsule_memo_carries_the_sentence_the_window_rests_on() -> None:
    """The synthetic case proves the window closes; this proves it closes for
    the reason the source gives, in its own words."""
    parsed = parse(CAPSULE_MEMO_PDF)
    claim = capsule_memo_claim(document_version_id="dv", parsed=parsed, holding_id="h")
    assert claim.applicable_to == date(2022, 12, 31)
    scope = next(f for f in claim.facts if f.field_name == "no_reliance_scope")
    assert scope.value_text == (
        "may not be relied upon for any other\npurpose or for any subsequent measurement "
        "date without a written update from CVA."
    )
    assert resolves_in(scope.citation, parsed.canonical_text)


@needs_corpus
def test_the_real_meridian_email_is_classified_by_its_authority() -> None:
    parsed = parse(MERIDIAN_EMAIL_TXT)
    claim = meridian_email_claim(document_version_id="dv", parsed=parsed, holding_id="h")
    assert claim.source_class is SourceClass.ADMINISTRATOR_STATEMENT
    assert claim.received_date == date(2026, 1, 30)
    assert claim.as_of_date == date(2025, 12, 31)
    delivered = next(f for f in claim.facts if f.field_name == "delivery_date")
    assert delivered.value_text == "Friday, January 30, 2026, 6:02 AM ET"


@needs_corpus
def test_a_statement_read_against_the_wrong_year_raises_on_the_real_pdfs() -> None:
    """The synthetic case proves the anchor; this proves the real statements
    are as interchangeable as it assumes."""
    parsed = parse(statement_pdf(date(2024, 12, 31)))
    with pytest.raises(CitationError, match="pattern matched nothing"):
        jio_statement_facts("dv", parsed, date(2025, 12, 31))


# ── The write path ───────────────────────────────────────────────────────
@needs_db
def test_the_meridian_claim_stores_its_authority_and_its_delivery_date(
    conn: Conn, seed: dict[str, str], tmp_path: Path
) -> None:
    """A round trip on synthetic text, so it runs where the corpus does not."""
    doc = _doc(tmp_path, SYNTHETIC_EMAIL, "email.txt")
    version_id = store_document(conn, doc)
    draft = meridian_email_claim(document_version_id=version_id, parsed=doc, holding_id=seed["h"])
    claim_id = store_claim(conn, version_id, draft, doc.canonical_text)
    row = conn.execute(
        "select source_class, execution_status, issued_date, as_of_date, received_date,"
        " applicable_from, applicable_to from claim where id = %s",
        (claim_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == SourceClass.ADMINISTRATOR_STATEMENT.value
    assert row[1] == ExecutionStatus.NOT_APPLICABLE.value
    # issued, as_of, received.
    assert (row[2], row[3], row[4]) == (
        date(2026, 1, 30),
        date(2025, 12, 31),
        date(2026, 1, 30),
    )
    assert (row[5], row[6]) == (date(2026, 1, 30), None)
    conn.rollback()


@needs_db
def test_capsules_window_reaches_the_database_closed(
    conn: Conn, seed: dict[str, str], tmp_path: Path
) -> None:
    doc = _doc(tmp_path, SYNTHETIC_CAPSULE, "capsule.txt")
    version_id = store_document(conn, doc)
    draft = capsule_memo_claim(document_version_id=version_id, parsed=doc, holding_id=seed["h"])
    claim_id = store_claim(conn, version_id, draft, doc.canonical_text)
    row = conn.execute(
        "select applicable_from, applicable_to, priced_class, price_per_share"
        " from claim where id = %s",
        (claim_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == row[1] == date(2022, 12, 31)
    assert row[2] == "series_b"
    assert row[3] == Decimal("1.20")
    conn.rollback()


@needs_db
@needs_corpus
def test_the_fy2025_statement_goes_from_pdf_to_cited_facts_that_resolve(
    conn: Conn, seed: dict[str, str]
) -> None:
    """One real document all the way through, with every citation re-resolved
    against the text Postgres stored. Each layer can be right alone and the
    chain still broken."""
    as_of = date(2025, 12, 31)
    parsed = parse(statement_pdf(as_of))
    version_id = store_document(conn, parsed)
    draft = jio_statement_claim(
        document_version_id=version_id, parsed=parsed, holding_id=seed["h"], as_of=as_of
    )
    claim_id = store_claim(conn, version_id, draft, parsed.canonical_text)

    stored = conn.execute(
        "select canonical_text from document_version where id = %s", (version_id,)
    ).fetchone()
    assert stored is not None
    stored_text = stored[0]
    assert stored_text == parsed.canonical_text

    rows = conn.execute(
        "select field_name, value_text, value_numeric, citation_quote, span_start, span_end"
        " from extracted_fact where claim_id = %s order by field_name",
        (claim_id,),
    ).fetchall()
    expected = statement_expected(as_of)
    assert len(rows) == len(expected)
    for field_name, value_text, value_numeric, quote, start, end in rows:
        want_text, want_number = expected[str(field_name)]
        assert value_text == want_text, field_name
        assert value_numeric == (None if want_number is None else Decimal(want_number)), field_name
        citation = Citation(
            document_version_id=version_id,
            quote=str(quote),
            span_start=int(str(start)),
            span_end=int(str(end)),
        )
        assert resolves_in(citation, str(stored_text)), field_name

    row = conn.execute(
        "select source_class, received_date from claim where id = %s", (claim_id,)
    ).fetchone()
    assert row is not None
    assert row[0] == SourceClass.ADMINISTRATOR_STATEMENT.value
    # The statement does not date its own delivery; the covering email does.
    assert row[1] == date(2026, 1, 30)
    conn.rollback()
