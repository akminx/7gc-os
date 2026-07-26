"""Family A — the executed Stock Purchase Agreements, and what makes them executed.

Split three ways, because *a guard that skips where the case-study material is
private has not failed*: every pattern the module ships is proved on synthetic
text that runs in CI; the figures are then hand-transcribed from the PDFs into
the tables below and asserted against the real files; and one round trip through
Postgres shows the span, the column and the driver agree, which no layer can
show on its own.

The Fund's synthetic row is 500,000 shares against $12,500,000.00 deliberately:
`500,000` is a substring of `12,500,000.00`, so a rule that merely asked whether
the quote contained the figure finds it twice, and one without boundaries
refuses the row outright.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ingest.documents.claims import ClaimDraft, FactDraft
from ingest.documents.extract_spa import (
    FLUIDSTACK,
    POOLSIDE,
    ROOFSTOCK,
    SpaDocument,
    spa_claim,
    spa_claims,
    spa_facts,
    spa_settlement_claim,
    spa_settlement_facts,
)
from ingest.documents.parse import ParsedDocument, parse
from packages.contracts.citations import CitationError
from packages.contracts.enums import ExecutionStatus, SourceClass

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


def _body(*, valuation: str, closing: str, settled: str, purchaser: str) -> str:
    return (
        "ACME, INC.\n"
        "Series C Preferred Stock Purchase Agreement (Excerpt) — Dated March 4, 2030\n"
        "\n\n"
        "THIS SERIES C PREFERRED STOCK PURCHASE AGREEMENT (this “Agreement”) "
        "is made as of March 4, 2030, by\n"
        "and among Acme, Inc. and the purchasers listed on Schedule A.\n\n"
        "1.1 Sale and Issuance. Each Purchaser agrees to purchase at the Closing "
        "that number of\n"
        "shares of Series C Preferred Stock set forth opposite such Purchaser's "
        "name on Schedule A at a purchase price of $25.00\n"
        "per share.\n\n"
        f"{valuation}"
        f"{closing}"
        "Schedule A — Schedule of Purchasers\n\n"
        "    Northwind Partners, L.P.         200,000       $25.00               $5,000,000.00\n"
        "\n"
        f"    {purchaser}{' ' * (33 - len(purchaser))}500,000       $25.00"
        "              $12,500,000.00\n"
        "\n"
        "    Total                            700,000                            $17,500,000.00\n"
        "\n\n"
        "Wire Settlement Confirmation (Attached to Closing Set)\n"
        f"{purchaser}: $12,500,000.00 received {settled}, per the settlement "
        "statement of company counsel, ref.\n"
        "AC-C-0001.\n\n"
        "Signatures (Excerpt)\n"
        "COMPANY: Acme, Inc. — /s/ R. Roe, Chief Executive Officer\n"
        f"PURCHASER: {purchaser}, by its general partner — /s/ Authorized Signatory\n"
    )


#: Each real document's shape, carrying figures that are not the corpus's.
#: `dataclasses.replace` keeps every pattern the module ships, including the two
#: that differ per document, so this file proves them where the PDFs are not.
FLUIDSTACK_SHAPED = _body(
    valuation=_VALUATION_WITHOUT_SHARE_COUNT,
    closing=_CLOSING_BY_EXCHANGE,
    settled="03/04/2030",
    purchaser=_FUND_II,
)
POOLSIDE_SHAPED = _body(
    valuation=_VALUATION_WITH_SHARE_COUNT,
    closing=_CLOSING_REMOTELY,
    settled="March 4, 2030",
    purchaser=_FUND_II,
)
ROOFSTOCK_SHAPED = _body(
    valuation=_VALUATION_WITH_SHARE_COUNT,
    closing=_NO_CLOSING_CLAUSE,
    settled="March 4, 2030",
    purchaser=_FUND_I,
)

_MARCH_4 = date(2030, 3, 4)


def _synthetic(spec: SpaDocument, closing: date | None) -> SpaDocument:
    return replace(
        spec,
        priced_class="series_c",
        held_classes=("series_c",),
        agreement_date=_MARCH_4,
        closing_date=closing,
        settlement_date=_MARCH_4,
    )


FLUID_SYN = _synthetic(FLUIDSTACK, _MARCH_4)
POOL_SYN = _synthetic(POOLSIDE, _MARCH_4)
ROOF_SYN = _synthetic(ROOFSTOCK, None)


def _doc(tmp_path: Path, body: str) -> ParsedDocument:
    source = tmp_path / "acme.txt"
    source.write_bytes(body.encode("utf-8"))
    return parse(source)


def _by_name(facts: tuple[FactDraft, ...]) -> dict[str, FactDraft]:
    return {fact.field_name: fact for fact in facts}


def _claim(doc: ParsedDocument, spec: SpaDocument) -> ClaimDraft:
    return spa_claim(document_version_id="dv", parsed=doc, spec=spec, holding_id="h")


# ── Reading the Fund's row out of Schedule A ─────────────────────────────
def test_the_row_is_read_from_schedule_a_not_the_wire_or_signature(tmp_path: Path) -> None:
    """The Fund's name heads three passages in each of these files: its Schedule
    A row, the wire confirmation and the signature block. Anchored on the name
    alone a pattern lands on whichever comes first, every check downstream still
    passes, and the auditor arrives at the wrong line."""
    doc = _doc(tmp_path, FLUIDSTACK_SHAPED)
    assert doc.canonical_text.count(_FUND_II) == 3

    shares = _by_name(spa_facts("dv", doc, FLUID_SYN))["fund_shares"]
    assert shares.value_text == "500,000"
    assert shares.value_numeric == Decimal("500000")
    assert "$25.00" in shares.citation.quote
    assert "$12,500,000.00" in shares.citation.quote and "received" not in shares.citation.quote


def test_one_row_states_three_figures_and_a_count_is_not_its_aggregate(tmp_path: Path) -> None:
    """`500,000` occurs twice in this row — once as the share count and once
    inside `$12,500,000.00`. It is the share count exactly once, which is the
    difference between a ledger holding half a million shares and one holding
    twelve and a half million dollars' worth of digits."""
    facts = _by_name(spa_facts("dv", _doc(tmp_path, POOLSIDE_SHAPED), POOL_SYN))
    row = facts["fund_shares"].citation.quote
    assert row.count("500,000") == 2
    assert facts["fund_price_per_share"].citation.quote == row
    assert facts["fund_aggregate_purchase_price"].citation.quote == row

    assert facts["fund_shares"].value_numeric == Decimal("500000")
    assert facts["fund_price_per_share"].value_text == "$25.00"
    assert facts["fund_price_per_share"].value_numeric == Decimal("25.00")
    assert facts["fund_aggregate_purchase_price"].value_text == "$12,500,000.00"
    assert facts["fund_aggregate_purchase_price"].value_numeric == Decimal("12500000.00")
    assert facts["schedule_a_total_shares"].value_numeric == Decimal("700000")
    assert facts["schedule_a_total_purchase_price"].value_numeric == Decimal("17500000.00")


def test_a_schedule_carrying_two_rows_for_the_fund_is_refused(tmp_path: Path) -> None:
    """V6 · "zero or multiple matches fail with distinct reason codes." Taking
    the first of two attaches a resolving span to an arbitrary one of them."""
    doubled = POOLSIDE_SHAPED.replace(
        "    Northwind Partners, L.P.         200,000       $25.00               $5,000,000.00",
        "    7GC Fund II, L.P.                200,000       $25.00               $5,000,000.00",
    )
    with pytest.raises(CitationError, match="matched 2 passages"):
        spa_facts("dv", _doc(tmp_path, doubled), POOL_SYN)


def test_a_schedule_with_no_row_for_the_fund_is_refused(tmp_path: Path) -> None:
    """The wire line and the signature line still name the Fund, so a looser
    pattern reads `$12,500,000.00` out of the wire confirmation as a share
    count. A missing row is a finding, not a figure."""
    without = "\n".join(
        line
        for line in POOLSIDE_SHAPED.splitlines(keepends=True)
        if "500,000       $25.00" not in line
    )
    doc = _doc(tmp_path, without)
    assert _FUND_II in doc.canonical_text
    with pytest.raises(CitationError, match="pattern matched nothing"):
        spa_facts("dv", doc, POOL_SYN)


# ── What each document states and the others do not ──────────────────────
def test_only_a_document_stating_a_fully_diluted_count_carries_one(tmp_path: Path) -> None:
    """Fluidstack's shape states a valuation "on a fully diluted basis" and
    never says how many shares that is, so V4 has nothing to compare. A zero, or
    a count divided out of the valuation, turns a gap into a figure."""
    fluid = _by_name(spa_facts("dv", _doc(tmp_path, FLUIDSTACK_SHAPED), FLUID_SYN))
    assert "fully_diluted_shares" not in fluid
    assert fluid["post_money_valuation"].value_text == "$625,000,000"

    pool = _by_name(spa_facts("dv", _doc(tmp_path, POOLSIDE_SHAPED), POOL_SYN))
    assert pool["fully_diluted_shares"].value_text == "25,000,000"
    assert pool["fully_diluted_shares"].value_numeric == Decimal("25000000")


def test_the_as_of_date_is_the_stated_closing_date_or_nothing(tmp_path: Path) -> None:
    """INV-3 · three distinct instants. Where a closing date is stated it is the
    as-of date and the window start; where none is — Roofstock's shape — it stays
    NULL, because filling it makes "signed on" and "closed on" one fact."""
    stated = _claim(_doc(tmp_path, POOLSIDE_SHAPED), POOL_SYN)
    assert stated.issued_date == stated.as_of_date == stated.applicable_from == _MARCH_4
    assert stated.applicable_to is None
    assert stated.received_date is None

    silent_doc = _doc(tmp_path, ROOFSTOCK_SHAPED)
    assert "closing_date" not in _by_name(spa_facts("dv", silent_doc, ROOF_SYN))
    silent = _claim(silent_doc, ROOF_SYN)
    assert silent.as_of_date is None
    assert silent.issued_date == silent.applicable_from == _MARCH_4


def test_the_wire_confirmation_states_a_payer_an_amount_a_date_and_a_reference(
    tmp_path: Path,
) -> None:
    """Two spellings of a date in one corpus: Fluidstack writes `10/10/2024`,
    the other two write the month out. Neither is rewritten into the other — a
    repaired date is no longer a substring of the document (SPEC §8) — and
    neither reads as a number. `ref.` wraps a line in all three files, so the
    reference is quoted beside the payer and the amount rather than alone."""
    slashed = _by_name(spa_settlement_facts("dv", _doc(tmp_path, FLUIDSTACK_SHAPED), FLUID_SYN))
    assert slashed["settlement_date"].value_text == "03/04/2030"
    assert slashed["settlement_date"].value_numeric is None

    spelled = _by_name(spa_settlement_facts("dv", _doc(tmp_path, POOLSIDE_SHAPED), POOL_SYN))
    assert spelled["settlement_date"].value_text == "March 4, 2030"
    assert spelled["settlement_date"].value_numeric is None
    assert spelled["settlement_amount_received"].value_numeric == Decimal("12500000.00")
    assert "March 4, 2030" in spelled["settlement_amount_received"].citation.quote

    reference = spelled["settlement_reference"]
    assert (reference.value_text, reference.value_numeric) == ("AC-C-0001", None)
    assert _FUND_II in reference.citation.quote
    assert "$12,500,000.00" in reference.citation.quote


def test_the_signatures_are_cited_because_they_are_why_this_is_executed(tmp_path: Path) -> None:
    """§6.2.2 · `execution_status` describes the artifact in the Fund's
    possession. `executed` is the strongest label in the enum, so the passage
    earning it is cited rather than inferred from the file's name."""
    facts = _by_name(spa_facts("dv", _doc(tmp_path, ROOFSTOCK_SHAPED), ROOF_SYN))
    assert facts["company_signature"].value_text == "/s/ R. Roe, Chief Executive Officer"
    assert facts["purchaser_signature"].value_text == "/s/ Authorized Signatory"
    assert _FUND_I in facts["purchaser_signature"].citation.quote


# ── The guards on what a claim may assert ────────────────────────────────
def test_a_date_literal_the_document_does_not_state_is_refused(tmp_path: Path) -> None:
    """The date columns are the one part of a claim not read out of the text, so
    nothing downstream can contradict them: no citation covers them and the
    trigger never receives them."""
    doc = _doc(tmp_path, POOLSIDE_SHAPED)
    wrong_day = replace(POOL_SYN, agreement_date=date(2030, 3, 5))
    with pytest.raises(CitationError, match="which is not 2030-03-05"):
        spa_claim(document_version_id="dv", parsed=doc, spec=wrong_day, holding_id="h")

    wrong_settlement = replace(POOL_SYN, settlement_date=date(2030, 4, 4))
    with pytest.raises(CitationError, match="which is not 2030-04-04"):
        spa_settlement_claim(
            document_version_id="dv", parsed=doc, spec=wrong_settlement, holding_id="h"
        )


def test_a_claim_date_whose_fact_was_never_extracted_is_refused(tmp_path: Path) -> None:
    """A spec naming a closing date the patterns do not read would otherwise
    write that date to the database with nothing cited for it."""
    unread = replace(POOL_SYN, extra_patterns={})
    with pytest.raises(CitationError, match="no fact named 'closing_date'"):
        _claim(_doc(tmp_path, POOLSIDE_SHAPED), unread)


def test_a_priced_class_the_document_does_not_name_is_refused(tmp_path: Path) -> None:
    """INV-17 · the one-word silent collapse. `series_c` → `series_b` is not an
    error, fails no type check and reads perfectly; it prices one class off
    another's evidence, and the database's cross-class trigger never fires
    because that trigger can only see the word this field carries."""
    with pytest.raises(CitationError, match="not the class this document names"):
        _claim(_doc(tmp_path, POOLSIDE_SHAPED), replace(POOL_SYN, priced_class="series_b"))


def test_the_claim_price_is_the_documents_and_a_refused_numeral_is_no_price(
    tmp_path: Path,
) -> None:
    """`$025.00` is figure-shaped and states no figure: a leading zero on an
    integer is refused by both `cited_numeral` implementations rather than
    normalised. Without the guard the claim carries `price_per_share = NULL`
    beside a cited passage that plainly quotes a price."""
    claim = _claim(_doc(tmp_path, POOLSIDE_SHAPED), POOL_SYN)
    assert claim.price_per_share == Decimal("25.00")
    assert claim.priced_class == "series_c"

    zeroed = _doc(tmp_path, POOLSIDE_SHAPED.replace("price of $25.00", "price of $025.00"))
    with pytest.raises(CitationError, match="states no.single figure"):
        _claim(zeroed, POOL_SYN)


def test_the_agreement_and_the_wire_confirmation_are_separate_claims(tmp_path: Path) -> None:
    """INV-15 · authority lives on the claim, not the file. One PDF, two
    authorities: an agreement both parties signed, and an attached confirmation
    that cash moved, sourced from counsel and signed by nobody. Filing the second
    under the first lets an auditor testing settlement follow the citation to a
    contract *promising* payment."""
    agreement, settlement = spa_claims(
        document_version_id="dv",
        parsed=_doc(tmp_path, POOLSIDE_SHAPED),
        spec=POOL_SYN,
        holding_id="h",
    )
    assert agreement.claim_key == "series_c_price"
    assert agreement.source_class == SourceClass.EXECUTED_TRANSACTION_DOC
    assert agreement.execution_status == ExecutionStatus.EXECUTED

    assert settlement.claim_key == "series_c_settlement"
    assert settlement.source_class == SourceClass.COMPANY_COMMUNICATION
    # INV-4 · `not_applicable` keeps its own label and does not imply pro forma.
    assert settlement.execution_status == ExecutionStatus.NOT_APPLICABLE
    assert settlement.priced_class is None
    assert settlement.price_per_share is None

    shared = {f.field_name for f in agreement.facts} & {f.field_name for f in settlement.facts}
    assert shared == set()


# ── The real documents ───────────────────────────────────────────────────
#: Hand-transcribed from the PDFs, field by field. Read out of the extractor
#: these would agree with it by construction and prove nothing — the rule
#: `evals/oracle/primitives.yaml` follows.
Transcribed = dict[str, tuple[str, str | None]]

FLUIDSTACK_AGREEMENT: Transcribed = {
    "priced_security_class": ("Series A Preferred Share", None),
    "agreement_date": ("October 10, 2024", None),
    "round_price_per_share": ("$10.00", "10.00"),
    "post_money_valuation": ("$500,000,000", "500000000"),
    "fund_shares": ("100,000", "100000"),
    "fund_price_per_share": ("$10.00", "10.00"),
    "fund_aggregate_purchase_price": ("$1,000,000.00", "1000000.00"),
    "schedule_a_total_shares": ("2,000,000", "2000000"),
    "schedule_a_total_purchase_price": ("$20,000,000.00", "20000000.00"),
    "company_signature": ("/s/ E. Varga, Chief Executive Officer", None),
    "purchaser_signature": ("/s/ Authorized Signatory", None),
    "closing_date": ("October 10, 2024", None),
}
FLUIDSTACK_SETTLEMENT: Transcribed = {
    "settlement_amount_received": ("$1,000,000.00", "1000000.00"),
    "settlement_date": ("10/10/2024", None),
    "settlement_reference": ("FS-A-0117", None),
}
POOLSIDE_AGREEMENT: Transcribed = {
    "priced_security_class": ("Series B Preferred Stock", None),
    "agreement_date": ("August 1, 2024", None),
    "round_price_per_share": ("$40.00", "40.00"),
    "post_money_valuation": ("$2,000,000,000", "2000000000"),
    "fund_shares": ("50,000", "50000"),
    "fund_price_per_share": ("$40.00", "40.00"),
    "fund_aggregate_purchase_price": ("$2,000,000.00", "2000000.00"),
    "schedule_a_total_shares": ("2,500,000", "2500000"),
    "schedule_a_total_purchase_price": ("$100,000,000.00", "100000000.00"),
    "company_signature": ("/s/ J. Whitfield, Chief Executive Officer", None),
    "purchaser_signature": ("/s/ Authorized Signatory", None),
    "closing_date": ("August 1, 2024", None),
    "fully_diluted_shares": ("50,000,000", "50000000"),
}
POOLSIDE_SETTLEMENT: Transcribed = {
    "settlement_amount_received": ("$2,000,000.00", "2000000.00"),
    "settlement_date": ("August 1, 2024", None),
    "settlement_reference": ("PS-B-0244", None),
}
ROOFSTOCK_AGREEMENT: Transcribed = {
    "priced_security_class": ("Series E Preferred Stock", None),
    "agreement_date": ("November 8, 2021", None),
    "round_price_per_share": ("$25.00", "25.00"),
    "post_money_valuation": ("$1,900,000,000", "1900000000"),
    "fund_shares": ("60,000", "60000"),
    "fund_price_per_share": ("$25.00", "25.00"),
    "fund_aggregate_purchase_price": ("$1,500,000.00", "1500000.00"),
    "schedule_a_total_shares": ("3,040,000", "3040000"),
    "schedule_a_total_purchase_price": ("$76,000,000.00", "76000000.00"),
    "company_signature": ("/s/ M. Deverell, Chief Executive Officer", None),
    "purchaser_signature": ("/s/ Authorized Signatory", None),
    "fully_diluted_shares": ("76,000,000", "76000000"),
}
ROOFSTOCK_SETTLEMENT: Transcribed = {
    "settlement_amount_received": ("$1,500,000.00", "1500000.00"),
    "settlement_date": ("November 8, 2021", None),
    "settlement_reference": ("RS-E-0592", None),
}

#: The Fund's own record-keeping note. Request 3's evidence — the basis on which
#: a mark stays unchanged — and for a while nothing read it at all.
FLUIDSTACK_RECORDS: Transcribed = {}
POOLSIDE_RECORDS: Transcribed = {
    "no_subsequent_round_of_record": (
        "no subsequent financing rounds have been documented for this company "
        "as of the Fund's most recent records.",
        None,
    )
}
ROOFSTOCK_RECORDS: Transcribed = {
    "no_subsequent_round_of_record": (
        "no subsequent financing rounds documented in the Fund's records after this closing.",
        None,
    )
}

REAL = [
    pytest.param(
        FLUIDSTACK, FLUIDSTACK_AGREEMENT, FLUIDSTACK_SETTLEMENT, FLUIDSTACK_RECORDS, id="fluidstack"
    ),
    pytest.param(
        POOLSIDE, POOLSIDE_AGREEMENT, POOLSIDE_SETTLEMENT, POOLSIDE_RECORDS, id="poolside"
    ),
    pytest.param(
        ROOFSTOCK, ROOFSTOCK_AGREEMENT, ROOFSTOCK_SETTLEMENT, ROOFSTOCK_RECORDS, id="roofstock"
    ),
]

needs_corpus = pytest.mark.skipif(
    not all(spec.path.exists() for spec in (FLUIDSTACK, POOLSIDE, ROOFSTOCK)),
    reason="case-study documents are not in the repository",
)


@needs_corpus
@pytest.mark.parametrize(("spec", "agreement", "settlement", "records"), REAL)
def test_the_documents_state_these_figures_and_no_others(
    spec: SpaDocument, agreement: Transcribed, settlement: Transcribed, records: Transcribed
) -> None:
    assert records is not None
    parsed = parse(spec.path)
    for facts, expected in (
        (spa_facts("dv", parsed, spec), agreement),
        (spa_settlement_facts("dv", parsed, spec), settlement),
    ):
        read = _by_name(facts)
        assert set(read) == set(expected)
        for field_name, (text, number) in expected.items():
            fact = read[field_name]
            assert fact.value_text == text, field_name
            assert fact.value_numeric == (None if number is None else Decimal(number)), field_name
            assert fact.value_text in fact.citation.quote, field_name
            span = parsed.canonical_text[fact.citation.span_start : fact.citation.span_end]
            assert span == fact.citation.quote, field_name


@needs_corpus
@pytest.mark.parametrize(
    ("spec", "priced_class", "price", "issued", "closed"),
    [
        pytest.param(FLUIDSTACK, "series_a", "10.00", date(2024, 10, 10), date(2024, 10, 10)),
        pytest.param(POOLSIDE, "series_b", "40.00", date(2024, 8, 1), date(2024, 8, 1)),
        # Roofstock states no closing date, so its as_of_date is NULL.
        pytest.param(ROOFSTOCK, "series_e", "25.00", date(2021, 11, 8), None),
    ],
)
def test_the_agreement_claims_record_what_the_documents_say(
    spec: SpaDocument, priced_class: str, price: str, issued: date, closed: date | None
) -> None:
    claim = spa_claim(document_version_id="dv", parsed=parse(spec.path), spec=spec, holding_id="h")
    assert claim.source_class == SourceClass.EXECUTED_TRANSACTION_DOC
    assert claim.execution_status == ExecutionStatus.EXECUTED
    assert claim.priced_class == priced_class
    assert claim.price_per_share == Decimal(price)
    assert claim.issued_date == issued
    assert claim.as_of_date == closed
    assert claim.applicable_from == (issued if closed is None else closed)
    # None of the three states an expiry or a date of receipt.
    assert claim.applicable_to is None
    assert claim.received_date is None


@needs_corpus
def test_the_three_documents_are_not_the_same_document() -> None:
    """The family's two per-document differences, on the real files. Fluidstack
    states a valuation "on a fully diluted basis" and no count of those shares,
    so V4 is `not_comparable` there; Roofstock has no closing clause, so its
    as-of date is NULL. Absences to report, not to fill in from the other two."""
    fluid = _by_name(spa_facts("dv", parse(FLUIDSTACK.path), FLUIDSTACK))
    assert "fully_diluted_shares" not in fluid
    assert "fully diluted" in fluid["post_money_valuation"].citation.quote

    roofstock = parse(ROOFSTOCK.path)
    assert "Closing shall" not in roofstock.canonical_text
    claim = spa_claim(document_version_id="dv", parsed=roofstock, spec=ROOFSTOCK, holding_id="h")
    assert claim.as_of_date is None
    assert claim.applicable_from == date(2021, 11, 8)


@needs_corpus
def test_fluidstack_prices_one_of_the_two_classes_the_fund_holds() -> None:
    """INV-17 for this family. The holding carries a Series A lot and a Series
    A-2 lot; this agreement prices Series A. Reading `priced_class` off the
    holding would extend $10.00 to the A-2 lot with no cited policy decision
    anywhere, and nothing would go red."""
    claim = spa_claim(
        document_version_id="dv", parsed=parse(FLUIDSTACK.path), spec=FLUIDSTACK, holding_id="h"
    )
    assert claim.priced_class == "series_a"
    assert set(FLUIDSTACK.held_classes) - {claim.priced_class} == {"series_a2"}
