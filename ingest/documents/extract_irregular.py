"""Family D — the irregulars: six documents where the classification is the work.

Every document here is weak evidence wearing a strong envelope, or strong
evidence wearing a weak one. The figures are easy; `source_class` and
`execution_status` are the whole difficulty, and each one is decided by a
sentence in the document rather than by what the transaction turned out to be.

Each classification below is followed by the sentence in the document that
decides it, and each of those sentences is extracted as a cited fact, so the
decision is reviewable against the page rather than merely asserted here.

* The Signal → `press` · `not_applicable`
  *"The Signal has not independently reviewed the transaction documents."*
* Banzai quotes → `public_market_quote` · `not_applicable`
  *"quoted closing price on the last trading day of each fiscal year"*
* Jackpocket notice → `executed_transaction_doc` · `executed`
  *"the merger was consummated on May 20, 2024"*
* Lucra term sheet → `company_communication` · `non_binding`
  *"Non-binding except as noted"*
* Lucra CEO email → `company_communication` · `unexecuted_referenced`
  *"Counsel is still finalizing the closing set"*
* Dream notice → `company_communication` · `unexecuted_referenced`
  *"executed documents will follow from counsel this week"*

Three temptations, each of which would make a position look supported:

* **The press article is not a cap table.** INV-2 · authority is a lattice, not
  a score: `press` can trigger research and can never support a fair-value mark,
  at any rank. SPEC §14 records the consequence — Anthropic's 25Q4 $8,000,000
  carries reason `NO_PRIMARY_PPS_SUPPORT`, gets a transcription approval and no
  valuation approval, and never enters an approved total. The job here is to
  extract what the article states and classify it honestly, not to make it
  sufficient. So this claim carries **no `price_per_share` at all**: the article
  states a headline valuation in words and no per-share figure exists to lift.
* **An email saying "we closed" is not a closing set.** §6.2.2 · execution
  status describes the artifact in the Fund's possession, not the state of the
  world. Lucra's CEO email is the position where the letter's request for
  executed documentation is unmet, and it says so itself.
* **An executed term sheet is still a term sheet.** Lucra's excerpt opens with
  *"Non-binding except as noted"* and closes by saying the executed SPA is with
  counsel. `executed` here would be one word, no error, and Lucra would read as
  documented.

## Why Banzai is three claims and not one

One `.txt` file, three dated observations. `evals/oracle/primitives.yaml` models
them as three documents for a reason recorded there: collapsing them into one
document dated 2025-12-31 made the FY2023 quote read as subsequent evidence and
resolve to the wrong price. The FY2023 close is dated **12/29/2023** — the last
trading day — against a 12/31/2023 measurement date, which is INV-3's own
example. Each row therefore gets its own claim, its own `issued_date`, and its
own applicability window, and each row's price is quoted inside that row so
three prices in one file cannot be confused for one another.

## Two of these documents recite an acquisition they did not effect

Jackpocket's paying-agent notice states, from the company's stock ledger, that
the holder bought in on 30 December 2021 at $4.00 a share for $2,000,000.00.
Banzai's saved quote screen states, in a parenthesis about periods before the
audit window, that the position is held at a March 2021 purchase price of
$10.00/share, $500,000. Neither figure is stated anywhere else in the corpus,
and there is no purchase agreement for either position.

Reading them changes what the packet can SAY and not what it may CONCLUDE. A
paying agent's recital and a saved brokerage screen are not executed acquisition
documents, so the classifications above are untouched, the R1 gaps recording
that those agreements are not located stay open, and neither claim gains a
reliance link on the letter's first request. What ends is the silence: ¶1 for
these two holdings is now answered with a cited figure AND a stated gap, rather
than with nothing. A later change that lifts either gap on the strength of these
figures would report that a brokerage screen satisfies the letter.

## Prices are read from the citation, never typed beside it

`_cited_price` takes the claim's `price_per_share` out of the fact that cites
it, so the structured price and the quoted passage cannot disagree. A hand-typed
`Decimal("1.10")` beside a row stating $0.62 is exactly the plausible wrong
number this project is built against, and here there are three prices in one
file for it to be plausible against.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from ingest.documents.claims import ClaimDraft, FactDraft, cited_fact
from ingest.documents.extract_dream import HELD_CLASS as DREAM_HELD_CLASS
from ingest.documents.extract_dream import PRICED_CLASS as DREAM_PRICED_CLASS
from ingest.documents.extract_spa import WIRE_REF
from ingest.documents.parse import ParsedDocument
from packages.contracts.citations import CitationError
from packages.contracts.enums import ExecutionStatus, SourceClass

#: 7GC holds Series A-1 in Lucra. The CEO email prices **Series A-2**, so the
#: October 2025 mark of $2,250,000 is 750,000 A-1 shares carried at the A-2
#: price — a cross-class act (INV-17) that the database must be able to see.
#: Recording `series_a1` here would be the cheapest collapse: one word, no
#: error, and the cross-class trigger never fires.
LUCRA_HELD_CLASS = "series_a1"
LUCRA_A1_PRICED_CLASS = "series_a1"
LUCRA_A2_PRICED_CLASS = "series_a2"

#: Dream's closing notice prices the same Series B the cap table prices, against
#: the same Series A-1 holding. Imported rather than restated so the two
#: extractors cannot drift into different ideas of which class is which.
DREAM_EMAIL_PRICED_CLASS = DREAM_PRICED_CLASS
DREAM_EMAIL_HELD_CLASS = DREAM_HELD_CLASS


def _facts(
    document_version_id: str,
    parsed: ParsedDocument,
    patterns: dict[str, re.Pattern[str]],
) -> tuple[FactDraft, ...]:
    """Every figure a pattern set states, each cited to the passage stating it.

    Almost every pattern here stops where its `value` group stops, with the
    anchor in front of it. That is not style. `supports_value` reads the
    character *after* the value inside the quote, and a comma or full stop there
    means the value is a fragment of a longer figure: `"December 9, 2025"`
    followed by `", 6:04 AM PT"` is refused for the same reason `625` inside
    `625,000` is. Where a pattern does carry trailing context — Banzai's rows,
    which need the columns after the price to prove which row was matched — the
    character following the value is a space, and the same check passes.
    """
    return tuple(
        cited_fact(
            document_version_id=document_version_id,
            canonical_text=parsed.canonical_text,
            field_name=field_name,
            pattern=pattern,
        )
        for field_name, pattern in patterns.items()
    )


#: Month and weekday names, spelled out rather than read from `strftime`.
#: `%B` and `%A` are locale-dependent — under `LC_TIME=fr_FR` they render
#: `décembre` and every date pattern below would match nothing — and `%d`
#: zero-pads a day that no document in this corpus writes as `09`.
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _date_pattern(when: date, *, weekday: bool = False) -> str:
    """The date a claim carries, written the way the document writes it.

    Every claim date in this module is hand-read from the page, and a hand-read
    date beside a document is two places for it to live. So the *pattern* is
    built from the constant: change `LUCRA_EMAIL_DATE` to a date the email does
    not state and the pattern matches nothing, which is a loud failure rather
    than a claim dated one day and cited to another.

    Spaces become `\\s+` because `-layout` wraps a line wherever the column ends
    — Dream's `Closing Date: November\\n14, 2025` is that shape — and a date
    broken across two lines is still the date the document states.
    """
    prefix = f"{_WEEKDAYS[when.weekday()]}, " if weekday else ""
    stated = f"{prefix}{_MONTHS[when.month - 1]} {when.day}, {when.year}"
    return r"\s+".join(re.escape(part) for part in stated.split(" "))


def _cited_price(facts: tuple[FactDraft, ...], field_name: str) -> Decimal:
    """The claim's price, taken from the fact that cites it.

    Refuses text that states no figure rather than defaulting to zero. Lucra's
    email says `$95M post` and Dream's says `$800M` — figure-shaped to a human,
    no figure at all to `cited_numeral`, and a claim priced at `None` coerced to
    zero would be a mark of nothing with a resolving citation beside it.
    """
    for fact in facts:
        if fact.field_name == field_name:
            if fact.value_numeric is None:
                raise CitationError(
                    f"{field_name} cites {fact.value_text!r}, which states no single "
                    "figure, so it cannot be a claim's price per share"
                )
            return fact.value_numeric
    raise CitationError(f"no fact named {field_name} was extracted to price this claim")


# ── Anthropic · The Signal, 9 December 2025 ──────────────────────────────
#: The article states a valuation in words (`$120 Billion`), an attribution to
#: unnamed sources, and two explicit disclaimers. `cited_numeral` reads no
#: number from any of them, which is the honest outcome: there is no per-share
#: price in this document to lift, and a `$120` stripped out of `$120 Billion`
#: would be a figure the article does not state.
PRESS_DATE = date(2025, 12, 9)

_ANTHROPIC: dict[str, re.Pattern[str]] = {
    "publication_date": re.compile(rf"Published (?P<value>{_date_pattern(PRESS_DATE)})"),
    "headline_valuation": re.compile(r"Funding Round at (?P<value>\$[\d,]+ Billion)"),
    "valuation_attribution": re.compile(
        r"billion, (?P<value>according to three people familiar with the matter)"
    ),
    "terms_disclosure": re.compile(
        r"coming weeks\. (?P<value>Terms have not been publicly disclosed)"
    ),
    "independent_review": re.compile(
        r"The Signal (?P<value>has not independently reviewed the transaction documents)"
    ),
}


def anthropic_facts(document_version_id: str, parsed: ParsedDocument) -> tuple[FactDraft, ...]:
    """What the article states, including the two sentences that unmake it."""
    return _facts(document_version_id, parsed, _ANTHROPIC)


def anthropic_claim(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str
) -> ClaimDraft:
    """A rumoured round, classified as press. INV-2.

    `priced_class` and `price_per_share` are both `None`, and that is the whole
    finding rather than an omission: the article discloses no terms, so there is
    no class it prices and no figure it prices it at. A press article that
    arrived carrying a per-share price would still be press — the lattice is
    about kind, not about how much the document happens to say.
    """
    return ClaimDraft(
        claim_key="round_rumour",
        holding_id=holding_id,
        source_class=SourceClass.PRESS,
        execution_status=ExecutionStatus.NOT_APPLICABLE,
        issued_date=PRESS_DATE,
        as_of_date=PRESS_DATE,
        applicable_from=PRESS_DATE,
        applicable_to=None,
        priced_class=None,
        price_per_share=None,
        facts=anthropic_facts(document_version_id, parsed),
    )


# ── Banzai · saved year-end quote record ─────────────────────────────────
#: `(observation date the row states, the fiscal year end it is the close for)`.
#:
#: The second date is read from the document's own basis line — *"quoted closing
#: price on the last trading day of each fiscal year"* — and not computed from
#: the first. They coincide for FY2024 and FY2025 and differ for FY2023, which
#: is the only reason this file has three claims instead of one.
BANZAI_QUOTES: tuple[tuple[date, date], ...] = (
    (date(2023, 12, 29), date(2023, 12, 31)),
    (date(2024, 12, 31), date(2024, 12, 31)),
    (date(2025, 12, 31), date(2025, 12, 31)),
)

#: 7GC Fund I holds common stock and the quotes price common stock, so Banzai is
#: the corpus's clearest non-cross-class case.
BANZAI_PRICED_CLASS = "common"


def _banzai_patterns(observed: date) -> dict[str, re.Pattern[str]]:
    """One row's three figures, each quoted inside that row, and the two the
    whole file states once.

    Three prices live in this file — $2.40, $1.10 and $0.62 — and each appears
    once. Quoting a price on its own would still resolve; anchoring it to its
    own measurement date is what makes the citation say *which year's close* it
    is, which is the distinction the FY2023 row exists to break.

    The row label is built from the date the claim carries, so a claim dated
    12/31/2024 cannot cite the 12/29/2023 row: there is no second place for the
    date to be typed and therefore nothing for the two to disagree about.

    The share count and the entry cost carry no row, because the document states
    each of them once for the position as a whole. They are cited onto all three
    claims for that reason, exactly as `position_shares` already was.

    `March 2021` is a literal and not a `_date_pattern`: the basis note states a
    month and a year and no day, so there is no date constant for a pattern to
    be built from. `/share` sits OUTSIDE the price group deliberately —
    `cited_numeral("$10.00/share")` reads no figure at all, and a price stored
    with no number is a claim's worth of evidence that reconciles against
    nothing.
    """
    row = f"{observed.month:02d}/{observed.day:02d}/{observed.year}"
    return {
        "position_shares": re.compile(r"7GC Fund I, L\.P\. — (?P<value>[\d,]+) common shares"),
        "quote_date": re.compile(rf"(?P<value>{row})\s+\$[\d.]+\s+\$[\d,]+"),
        "closing_price": re.compile(rf"{row}\s+(?P<value>\$[\d.]+)\s+\$[\d,]+"),
        "position_value": re.compile(rf"{row}\s+\$[\d.]+\s+(?P<value>\$[\d,]+)"),
        "original_purchase_pps": re.compile(
            r"held at March 2021 purchase price \((?P<value>\$[\d.]+)/share; \$[\d,]+\)"
        ),
        "original_purchase_aggregate": re.compile(
            r"held at March 2021 purchase price \(\$[\d.]+/share; (?P<value>\$[\d,]+)\)"
        ),
    }


def banzai_facts(
    document_version_id: str, parsed: ParsedDocument, observed: date
) -> tuple[FactDraft, ...]:
    """The share count, the entry cost, and one row's date, close and value."""
    return _facts(document_version_id, parsed, _banzai_patterns(observed))


def banzai_claims(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str
) -> tuple[ClaimDraft, ...]:
    """Three observations, three claims. INV-3, INV-15, INV-16.

    One saved quote record is one *artifact* and three *assertions*, and INV-15
    puts authority — and here, date — on the assertion. The window closes at the
    fiscal year end each row is the close for, so the 12/29/2023 quote is
    available at the 12/31/2023 measurement date and at no later one. A single
    claim dated 2025-12-31 would resolve every measurement date to $0.62 with
    every citation still resolving.
    """
    claims: list[ClaimDraft] = []
    for observed, fiscal_year_end in BANZAI_QUOTES:
        facts = banzai_facts(document_version_id, parsed, observed)
        claims.append(
            ClaimDraft(
                claim_key=f"fy{fiscal_year_end.year}_close",
                holding_id=holding_id,
                source_class=SourceClass.PUBLIC_MARKET_QUOTE,
                execution_status=ExecutionStatus.NOT_APPLICABLE,
                issued_date=observed,
                as_of_date=observed,
                applicable_from=observed,
                applicable_to=fiscal_year_end,
                priced_class=BANZAI_PRICED_CLASS,
                price_per_share=_cited_price(facts, "closing_price"),
                facts=facts,
            )
        )
    return tuple(claims)


# ── Jackpocket · notice of merger consideration, 20 May 2024 ─────────────
#: Request 4 of the audit letter — *"merger consideration statements … including
#: per-share consideration and share counts"* — and the only realisation in the
#: corpus. The paying agent's holder statement is an executed transaction
#: document: the merger was consummated, and this is the instrument that states
#: what was paid.
MERGER_EFFECTIVE_DATE = date(2024, 5, 20)
JACKPOCKET_PRICED_CLASS = "series_b"

#: The date the paying agent recites for the holder's ORIGINAL purchase, which
#: is not a date this notice effects anything on. It is compiled into its own
#: pattern for the same reason every other date here is: a notice that stated
#: another day would match nothing rather than be cited for this one.
JACKPOCKET_ENTRY_DATE = date(2021, 12, 30)

#: Escrow and withholding are extracted even though both are zero. V9 reconciles
#: `gross == shares × per-share` and reconciles fees, escrow and withholding
#: *separately*, never comparing net to the gross formula — and a zero that was
#: never read is indistinguishable from a zero that was assumed.
_JACKPOCKET: dict[str, re.Pattern[str]] = {
    "merger_agreement_date": re.compile(
        r"Agreement and Plan of Merger dated (?P<value>February \d+, \d{4})"
    ),
    "effective_date": re.compile(
        rf"merger was consummated on\s+(?P<value>{_date_pattern(MERGER_EFFECTIVE_DATE)})"
    ),
    "consideration_per_share_stated": re.compile(
        r"converted into the right to receive (?P<value>\$[\d.]+) in cash"
    ),
    "security": re.compile(r"Security\s+(?P<value>Series B Preferred Stock)"),
    "shares_of_record": re.compile(r"Shares of record at Effective Time\s+(?P<value>[\d,]+)"),
    "consideration_per_share": re.compile(r"Per-share merger consideration\s+(?P<value>\$[\d.]+)"),
    "gross_consideration": re.compile(r"Gross merger consideration\s+(?P<value>\$[\d,.]+)"),
    "escrow_allocation": re.compile(r"Escrow / holdback allocation\s+(?P<value>\$[\d,.]+)"),
    "tax_withholding": re.compile(r"Tax withholding\s+(?P<value>\$[\d,.]+)"),
    "net_payment": re.compile(r"Net payment\s+(?P<value>\$[\d,.]+)"),
    "payment_date": re.compile(r"initiated by wire on (?P<value>May \d+, \d{4})"),
    # `letter of transmittal` occurs three times in the notice and only this one
    # carries a reference, so the `, ref\.` is what names the passage rather
    # than the phrase. `-layout` wraps the line between the two words, which is
    # why the space is `\s+`; a literal space matches nothing here.
    "payment_reference": re.compile(rf"letter of\s+transmittal, ref\. (?P<value>{WIRE_REF})"),
    # ¶1, inside a ¶4 document. The paying agent recites the company's stock
    # ledger, and that recital is the corpus's only statement of what the fund
    # paid for Jackpocket — there is no 2021 purchase agreement. Extracting it
    # answers the letter's first request with a figure and its provenance; it
    # does not turn a merger notice into an acquisition document, and the
    # `document_gap` recording that the SPA is not located stays as it is.
    "acquisition_date": re.compile(
        r"Original acquisition of the shares by the holder:\s+"
        rf"(?P<value>{_date_pattern(JACKPOCKET_ENTRY_DATE)})"
    ),
    "original_purchase_pps": re.compile(
        r"Original acquisition of the shares by the holder:\s+"
        rf"{_date_pattern(JACKPOCKET_ENTRY_DATE)} at (?P<value>\$[\d.]+) per share"
    ),
    # The wrap falls between `per share` and `($2,000,000.00`, so the space in
    # front of the bracket is `\s+` for the same reason as above.
    "original_purchase_aggregate": re.compile(
        r"at \$[\d.]+ per share\s+\((?P<value>\$[\d,.]+) aggregate\)"
    ),
}


def jackpocket_facts(document_version_id: str, parsed: ParsedDocument) -> tuple[FactDraft, ...]:
    """The holder-facing amounts, each cited to its own row of the statement.

    `$3,100,000.00` appears twice — as gross and as net — and `$0.00` twice, as
    escrow and as withholding. Each is cited to its labelled row, so a citation
    an auditor follows lands on the line that states the figure rather than on
    whichever of the two came first.
    """
    return _facts(document_version_id, parsed, _JACKPOCKET)


def jackpocket_claim(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str
) -> ClaimDraft:
    """The realisation, at the authority a paying agent's notice actually has.

    `applicable_to` is open because the notice states no expiry: the merger
    consideration is what it is, permanently. INV-16 is about what the source
    says, and inventing a window here would be the same error as ignoring
    Capsule's, in the other direction.
    """
    facts = jackpocket_facts(document_version_id, parsed)
    return ClaimDraft(
        claim_key="merger_consideration",
        holding_id=holding_id,
        source_class=SourceClass.EXECUTED_TRANSACTION_DOC,
        execution_status=ExecutionStatus.EXECUTED,
        issued_date=MERGER_EFFECTIVE_DATE,
        as_of_date=MERGER_EFFECTIVE_DATE,
        applicable_from=MERGER_EFFECTIVE_DATE,
        applicable_to=None,
        priced_class=JACKPOCKET_PRICED_CLASS,
        price_per_share=_cited_price(facts, "consideration_per_share"),
        facts=facts,
    )


# ── Lucra · Series A-1 term sheet excerpt, 20 May 2024 ───────────────────
LUCRA_TERM_SHEET_DATE = date(2024, 5, 20)

#: `term_sheet_provenance` is extracted precisely because it is the sentence
#: that argues for the wrong answer. The excerpt calls itself *"this excerpt
#: from the executed term sheet"*, and a reader who classifies on that word
#: alone records `executed` for a document whose second line says
#: *"Non-binding except as noted"*. Both sentences are in the packet, so the
#: classification is reviewable rather than merely asserted.
_LUCRA_TERM_SHEET: dict[str, re.Pattern[str]] = {
    "term_sheet_date": re.compile(
        rf"Summary of Terms — (?P<value>{_date_pattern(LUCRA_TERM_SHEET_DATE)})"
    ),
    "binding_status": re.compile(
        rf"{_date_pattern(LUCRA_TERM_SHEET_DATE)} — (?P<value>Non-binding except as noted)"
    ),
    "securities": re.compile(r"Securities\s+(?P<value>Series A-1 Preferred Stock)"),
    "amount_of_financing": re.compile(r"Amount of financing\s+Up to (?P<value>\$[\d,]+)"),
    "price_per_share": re.compile(r"Price per share\s+(?P<value>\$[\d.]+)"),
    "pre_money_valuation": re.compile(r"Valuation\s+(?P<value>\$[\d,]+) pre-money"),
    "post_money_valuation": re.compile(r"pre-money; (?P<value>\$[\d,]+) post-money"),
    "fund_commitment": re.compile(r"7GC Fund II, L\.P\. \((?P<value>\$[\d,]+)\)"),
    "anticipated_closing": re.compile(
        r"Anticipated closing\s+On or about (?P<value>June \d+, \d{4})"
    ),
    "term_sheet_provenance": re.compile(
        r"(?P<value>This excerpt from the executed term sheet is retained for audit "
        r"support purposes)"
    ),
    "executed_docs_location": re.compile(
        r"capitalization table are (?P<value>on file with company counsel and have not "
        r"been located in the Fund's document repository)"
    ),
}


def lucra_term_sheet_facts(
    document_version_id: str, parsed: ParsedDocument
) -> tuple[FactDraft, ...]:
    """The terms, and the sentence recording where the executed SPA is."""
    return _facts(document_version_id, parsed, _LUCRA_TERM_SHEET)


def lucra_term_sheet_claim(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str
) -> ClaimDraft:
    """A proposal, not a transaction. INV-4 · `non_binding` is its own status.

    It is neither `executed` nor `pro_forma`, and INV-4 is explicit that
    `non_binding` carries its own label and reason code and does **not** imply
    pro forma. The whole R1 story for Lucra is in `executed_docs_location`: the
    executed Series A-1 SPA is with company counsel and has not been located, so
    the letter's first request is unmet at this position and the packet has to
    say so rather than count a term sheet as the acquisition document.
    """
    facts = lucra_term_sheet_facts(document_version_id, parsed)
    return ClaimDraft(
        claim_key="series_a1_price",
        holding_id=holding_id,
        source_class=SourceClass.COMPANY_COMMUNICATION,
        execution_status=ExecutionStatus.NON_BINDING,
        issued_date=LUCRA_TERM_SHEET_DATE,
        as_of_date=LUCRA_TERM_SHEET_DATE,
        applicable_from=LUCRA_TERM_SHEET_DATE,
        applicable_to=None,
        priced_class=LUCRA_A1_PRICED_CLASS,
        price_per_share=_cited_price(facts, "price_per_share"),
        facts=facts,
    )


# ── Lucra · email from the CEO, 17 October 2025 ──────────────────────────
LUCRA_EMAIL_DATE = date(2025, 10, 17)

_LUCRA_EMAIL: dict[str, re.Pattern[str]] = {
    "email_date": re.compile(rf"Date: (?P<value>{_date_pattern(LUCRA_EMAIL_DATE, weekday=True)})"),
    "close_statement": re.compile(
        r"circulates: (?P<value>we signed and closed the Series A-2 on Wednesday)"
    ),
    "price_per_share": re.compile(r"on Wednesday\. (?P<value>\$[\d.]+) per share"),
    "post_money_valuation": re.compile(r"per share, (?P<value>\$\d+M) post"),
    "closing_set_status": re.compile(
        r"(?P<value>Counsel is still finalizing the closing set); I'll have them send "
        r"over the executed docs and updated cap table once the final signature pages are in"
    ),
}


def lucra_email_facts(document_version_id: str, parsed: ParsedDocument) -> tuple[FactDraft, ...]:
    """The A-2 price the CEO states, and his own account of what is missing."""
    return _facts(document_version_id, parsed, _LUCRA_EMAIL)


def lucra_email_claim(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str
) -> ClaimDraft:
    """ "We signed and closed" is not a closing set. §6.2.2, INV-4, INV-17.

    The transaction is done and the artifact is an email. `execution_status`
    describes the file, so this is `unexecuted_referenced`: it *references*
    executed documents that the Fund does not have — *"Counsel is still
    finalizing the closing set."* Recording `executed` would answer a question
    the auditor did not ask and hide the one she did.

    `as_of_date` is left null on purpose. The email dates the close as
    "Wednesday" and states no calendar date for it; the Friday in the header is
    the date of the *email*. Subtracting two days would be a date this system
    computed, and INV-3 exists because a figure right for the wrong moment is
    the failure that survives review.

    `priced_class` is `series_a2` against a Series A-1 holding, which is what
    makes the $2,250,000 October mark a cross-class act requiring a cited
    policy decision (INV-17) rather than an arithmetic convenience.
    """
    facts = lucra_email_facts(document_version_id, parsed)
    return ClaimDraft(
        claim_key="series_a2_price",
        holding_id=holding_id,
        source_class=SourceClass.COMPANY_COMMUNICATION,
        execution_status=ExecutionStatus.UNEXECUTED_REFERENCED,
        issued_date=LUCRA_EMAIL_DATE,
        as_of_date=None,
        applicable_from=LUCRA_EMAIL_DATE,
        applicable_to=None,
        priced_class=LUCRA_A2_PRICED_CLASS,
        price_per_share=_cited_price(facts, "price_per_share"),
        facts=facts,
    )


# ── Dream · Series B closing notice, 17 November 2025 ────────────────────
DREAM_EMAIL_DATE = date(2025, 11, 17)

_DREAM_EMAIL: dict[str, re.Pattern[str]] = {
    "email_date": re.compile(rf"Date: (?P<value>{_date_pattern(DREAM_EMAIL_DATE, weekday=True)})"),
    "closing_date_stated": re.compile(r"financing closed on (?P<value>Friday, November \d+)"),
    "price_per_share": re.compile(r"Key terms: (?P<value>\$[\d.]+) per share"),
    "amount_raised": re.compile(r"per share, (?P<value>\$\d+M) raised"),
    "post_money_valuation": re.compile(r"raised, (?P<value>\$\d+M) post-money"),
    "fully_diluted_shares": re.compile(r"post-money on (?P<value>\d+M) fully diluted shares"),
    "attachment_status": re.compile(
        r"(?P<value>The pro forma capitalization table and closing set are attached); "
        r"executed documents will follow from counsel this week"
    ),
    "executed_docs_pending": re.compile(
        r"closing set are attached; (?P<value>executed documents will follow from counsel "
        r"this week)"
    ),
}


def dream_email_facts(document_version_id: str, parsed: ParsedDocument) -> tuple[FactDraft, ...]:
    """The CFO's terms, and the sentence that keeps the cap table pro forma."""
    return _facts(document_version_id, parsed, _DREAM_EMAIL)


def dream_email_claim(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str
) -> ClaimDraft:
    """A second claim about the same round, at its own authority. INV-15.

    The cap table `extract_dream.py` reads is `company_cap_table` / `pro_forma`;
    this email is `company_communication` / `unexecuted_referenced`. It states
    the round closed and it does **not** upgrade the cap table: §6.2.2 settles
    that `execution_status` records the artifact, and the artifact remains a pro
    forma table whose executed documents *"will follow from counsel this week"*.
    A pipeline that let the email promote the table would answer the letter's
    pro-forma question with "no positions", which is the one answer the corpus
    contradicts.

    `$80M`, `$800M` and `100M` are stored as text with no number, because that
    is what they are. The cap table states `$800,000,000` on `100,000,000`
    shares and is the document those figures are read from; a `800` lifted out
    of `$800M` here would reconcile against nothing and look cited.

    `as_of_date` is null for the same reason as Lucra's: the email says the
    round closed "Friday, November 14" and states no year in that sentence. The
    cap table states the closing date in full, and it is the document that
    should carry it.
    """
    facts = dream_email_facts(document_version_id, parsed)
    return ClaimDraft(
        claim_key="series_b_closing_notice",
        holding_id=holding_id,
        source_class=SourceClass.COMPANY_COMMUNICATION,
        execution_status=ExecutionStatus.UNEXECUTED_REFERENCED,
        issued_date=DREAM_EMAIL_DATE,
        as_of_date=None,
        applicable_from=DREAM_EMAIL_DATE,
        applicable_to=None,
        priced_class=DREAM_EMAIL_PRICED_CLASS,
        price_per_share=_cited_price(facts, "price_per_share"),
        facts=facts,
    )
