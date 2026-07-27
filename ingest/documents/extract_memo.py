"""Family C — valuation memoranda and periodic administrator statements.

Seven documents across three holdings, carrying three of the distinctions this
project exists to keep apart.

## Capsule states how long it may be relied on (INV-16)

Every date on Capsule's FY2022 memo can be right and a link to FY2023 still
invalid, because the memo itself says so:

    "This memorandum was prepared solely for the FY2022 financial statement
    audit of the Fund and may not be relied upon for any other purpose or for
    any subsequent measurement date without a written update from CVA. No
    update has been commissioned as of the date of this excerpt."

So `applicable_to` closes on the measurement date, and the sentence that closes
it is a cited fact rather than a decision taken in this file. Moonfare's FY2023
memo says the same thing in weaker words — *"should not be relied upon for
subsequent measurement dates without update"* — and closes for the same reason.
The Jio statements close on the narrower ground that they say statements are
*"issued annually as of the Partnership's fiscal year end"*, so each fiscal year
end has its own. Dream's cap table states no expiry and is therefore left open;
inventing a window is the same error as ignoring one, in the other direction.

## The Meridian email is an envelope (INV-15)

INVARIANTS.md is explicit: *"Email is an envelope. Meridian's email carries an
administrator statement."* Classifying it `company_communication` because it
arrived as email would take Jio's strongest evidence and file it with a CEO's
opinion. Authority is read off who is speaking in what capacity, never off the
container, and every assertion in that email is Meridian's as Administrator to
the Partnership — so it is one claim, not several. The shape that would need
two is a *company* forwarding an administrator statement: then the covering
note is a company communication and the attachment is not.

## It arrived after the date it reports on (INV-3)

The FY2025 statement is as of 31 December 2025 and reached the Fund on
30 January 2026. Three instants, three fields: `as_of_date` and `issued_date`
are what the statement is, `received_date` is when it arrived, and
`0004_subsequent_evidence_delivery_date.sql` reads the third to label the
evidence subsequent. Collapsing them produces the record that migration was
written to stop — evidence that did not exist in the Fund's hands at the
measurement date, presented as contemporaneous.

The statement PDF does not date its own delivery; the covering email does, and
cites it. `_DELIVERED_ON` is therefore an explicit map of the statements whose
delivery the corpus actually dates, so FY2023 and FY2024 stay NULL rather than
being given an invented receipt date.

## Moonfare states a re-measurement; nothing here computes one

SPEC §8 V8 never asserts equality — it recomputes and classifies a variance, and
that is a validator's job, not an extractor's. These patterns record what the
memos state: the directed pair, the rate, its effective date, and both amounts.
SPEC §15 cut the FX rate entity outright, so there is no rate store to write to
and no arithmetic to do here.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from ingest.documents.claims import ClaimDraft, FactDraft, cited_fact
from ingest.documents.parse import ParsedDocument
from packages.contracts.enums import ExecutionStatus, SourceClass

#: Measurement dates, hand-transcribed from each document's own header. None of
#: these documents states an issue date distinct from the date it measures — the
#: FY2023 Moonfare memo carries a 2024-series engagement reference and still
#: dates itself only to the measurement date — so `issued_date` records the one
#: date the source states rather than a date nobody wrote down.
MOONFARE_FY2023 = date(2023, 12, 31)
MOONFARE_FY2024 = date(2024, 12, 31)
CAPSULE_FY2022 = date(2022, 12, 31)

#: The three Jio capital account statements, one per fiscal year end.
JIO_STATEMENT_DATES = (date(2023, 12, 31), date(2024, 12, 31), date(2025, 12, 31))

#: The `Date:` header of Meridian's covering email, and the only delivery date
#: the corpus states for any statement in this family.
MERIDIAN_DELIVERY_DATE = date(2026, 1, 30)

#: Which statements have a dated delivery. INV-3 · `received_date` stays NULL
#: where no document dates the delivery: 0004 falls back to the issue date there,
#: and inventing a receipt date to fill the column is the collapse it names. The
#: FY2025 entry is not read from the statement — it is read from the covering
#: email, which carries it as a cited fact on its own claim.
_DELIVERED_ON: dict[date, date] = {date(2025, 12, 31): MERIDIAN_DELIVERY_DATE}

#: Capsule prices the class it holds, so nothing here is cross-class (INV-17).
#: Recorded anyway, because `priced_class` is what lets the database's
#: cross-class trigger fire at all — a NULL beside a stated price is refused by
#: `require_cross_class_policy` precisely so this cannot be left out.
CAPSULE_HELD_CLASS = "series_b"
CAPSULE_PRICED_CLASS = "series_b"

#: Clearwater's FY2023 memo on the Moonfare interest.
#:
#: Every figure is anchored to the row or clause that names it. `$1,000,000`
#: appears twice — as the March 2023 consideration and as the concluded value —
#: and `EUR 950,000` twice, at acquisition and on a last-round basis at the
#: measurement date. Those are four different assertions that happen to share two
#: numbers, and a pattern that took the first match would cite the wrong one with
#: every downstream check still green.
_MOONFARE_MEMO: dict[str, re.Pattern[str]] = {
    # "Measurement" ends one line and "Date:" opens the next, so the quote
    # carries that break. Nothing repairs it — the canonical text is the
    # extractor's output with no post-processing (SPEC §8).
    "measurement_date": re.compile(
        r"Measurement\s+Date: (?P<value>December 31, 2023) — Engagement ref\."
    ),
    "engagement_reference": re.compile(r"Engagement ref\. (?P<value>CVA-\d{4}-\d{4})"),
    "acquisition_consideration_usd": re.compile(r"for consideration of (?P<value>\$[\d,]*\d)"),
    # `EUR ` stays in the quote and out of the value: `cited_numeral` reads no
    # figure from "EUR 950,000" and would store NULL for a row that plainly
    # states one.
    "eur_interest_at_acquisition": re.compile(
        r"EUR-denominated interest of EUR (?P<value>[\d,]+) at the"
    ),
    "post_money_valuation_eur": re.compile(r"valuation of €(?P<value>[\d,]*\d)"),
    "eur_interest_last_round_basis": re.compile(
        r"EUR-denominated interest \(last-round basis\)\s+EUR (?P<value>[\d,]+)"
    ),
    # The pair is directed and stated as such. SPEC V7 wants a directed pair, an
    # effective date and a cited source; the memo states the first two.
    "currency_pair": re.compile(r"(?P<value>EUR/USD) closing rate, 12/31/2023"),
    "fx_rate_effective_date": re.compile(r"EUR/USD closing rate, (?P<value>12/31/2023)"),
    "fx_rate": re.compile(r"EUR/USD closing rate, 12/31/2023\s+(?P<value>[\d.]+)"),
    "concluded_fair_value_usd": re.compile(
        r"Concluded fair value \(USD, rounded\)\s+(?P<value>\$[\d,]+)"
    ),
    # INV-16 · the window below is this sentence, not a policy applied to it.
    "reliance_scope": re.compile(
        r"prepared for the FY2023 financial statement audit of the Fund and "
        r"(?P<value>should not be relied upon for subsequent\s+"
        r"measurement dates without update\.)"
    ),
}

#: 7GC Fund Operations' FY2024 re-measurement of the same interest.
#:
#: ORACLE.md F1 turns on the last sentence quoted here: the memo says the
#: interest will be re-measured at each future measurement date, and no
#: 12/31/2025 rate exists in the corpus, so FY2025 is not derivable rather than
#: carried forward (INV-6).
_MOONFARE_FX: dict[str, re.Pattern[str]] = {
    "measurement_date": re.compile(r"Measurement Date: (?P<value>December\s+31, 2024)"),
    # Who wrote it, in the document's own words. This is the fact the
    # `source_class` below rests on.
    "preparer": re.compile(r"(?P<value>Prepared by Fund Operations; reviewed by the CFO\.)"),
    "eur_interest_unchanged": re.compile(
        r"EUR-denominated interest \(unchanged, last-round basis\)\s+EUR (?P<value>[\d,]+)"
    ),
    "currency_pair": re.compile(r"(?P<value>EUR/USD) closing rate, 12/31/2024"),
    "fx_rate_effective_date": re.compile(r"EUR/USD closing rate, (?P<value>12/31/2024)"),
    "fx_rate": re.compile(r"EUR/USD closing rate, 12/31/2024\s+(?P<value>[\d.]+)"),
    "usd_carrying_value": re.compile(r"USD carrying value, 12/31/2024\s+(?P<value>\$[\d,]+)"),
    # The prior amount is cited to the parenthetical that names it rather than to
    # the row, because the row states `$1,000,000` twice — once inside the label
    # and once in the Value column — and a quote stating its figure twice does
    # not say which occurrence it means. `supports_value` refuses it, which is
    # how this was found rather than shipped.
    "prior_usd_carrying_value": re.compile(
        r"Prior USD carrying value \(entry, March 2023: (?P<value>\$[\d,]+)\)"
    ),
    # The `+` stays in the quote: `cited_numeral` reads no figure from "+$48,515"
    # and the direction is legible in the passage an auditor opens.
    "fx_remeasurement_adjustment": re.compile(
        r"FX re-measurement adjustment\s+\+(?P<value>\$[\d,]+)"
    ),
    # Where the EUR value came from — a third-party memo that, by its own terms
    # above, closed at 12/31/2023.
    "basis_reference": re.compile(
        r"financing \(March 2023\), "
        r"(?P<value>consistent with the FY2023 third-party valuation memorandum\.)"
    ),
    "remeasurement_scope": re.compile(
        r"(?P<value>The interest\s+"
        r"will be re-measured at the closing rate at each future measurement date\.)"
    ),
}

#: Clearwater's FY2022 memo on Capsule, and the sharpest INV-16 case in the
#: corpus: a memo that forbids its own later reuse in a sentence you have to
#: read to find.
_CAPSULE_MEMO: dict[str, re.Pattern[str]] = {
    "measurement_date": re.compile(
        r"Measurement Date:\s+(?P<value>December 31, 2022) — Engagement ref\."
    ),
    "engagement_reference": re.compile(r"Engagement ref\. (?P<value>CVA-\d{4}-\d{4})"),
    "shares_held": re.compile(r"holding of (?P<value>[\d,]+) shares of Series B Preferred Stock"),
    "security_class_held": re.compile(r"(?P<value>Series B Preferred Stock) of Capsule"),
    "original_purchase_pps": re.compile(r"completed in June 2019 at (?P<value>\$[\d.]+) per share"),
    "original_purchase_aggregate": re.compile(r"per share \((?P<value>\$[\d,]+) aggregate\)"),
    "bridge_financing_amount": re.compile(
        r"the Company closed a (?P<value>\$[\d,]+) bridge financing"
    ),
    "concluded_fair_value_per_share": re.compile(
        r"Concluded fair value per Series B Preferred share\s+(?P<value>\$[\d.]+)"
    ),
    "fund_holding_value": re.compile(r"Fund holding \(500,000 shares\)\s+(?P<value>\$[\d,]+)"),
    # Parenthesised, which `cited_numeral` reads as negative — a 70% decline, not
    # a 70% gain. The accounting convention survives into the stored number.
    "implied_change_vs_purchase": re.compile(
        r"Implied change vs\. original purchase price \(\$4\.00\)\s+(?P<value>\(\d+\.\d+%\))"
    ),
    # INV-16 · the sentence `applicable_to` is derived from.
    "no_reliance_scope": re.compile(
        r"prepared solely for the FY2022 financial statement audit of the Fund and "
        r"(?P<value>may not be relied upon for any other\s+purpose or for any subsequent "
        r"measurement date without a written update from CVA\.)"
    ),
    # And the sentence that says the escape hatch was never used.
    "update_status": re.compile(
        r"(?P<value>No update has been commissioned as of the date\s+of this excerpt\.)"
    ),
}


def _statement_patterns(as_of: date) -> dict[str, re.Pattern[str]]:
    """The Jio capital account statement for one fiscal year end.

    The three statements are near-identical: the same eight labels, the same
    five amounts, and only the year differs. Each is parsed on its own, so a
    label anchor is enough to be unique *within* a document — `$1,000,000.00`
    appears in three rows and `$0.00` in two, and the label is what tells them
    apart.

    The as-of pattern carries the year, which makes it the guard: building the
    FY2024 patterns and running them at the FY2023 statement matches nothing and
    raises, instead of quietly reporting the wrong year's account under the right
    year's claim. Every row here states the same amounts in all three years, so
    nothing downstream could have noticed.
    """
    return {
        "as_of_date": re.compile(
            rf"Capital Account Statement — As of (?P<value>December 31,\s+{as_of.year}) — Delivered"
        ),
        "administrator": re.compile(
            r"(?P<value>MERIDIAN FUND SERVICES \(CAYMAN\) LTD\.)\s+Administrator to"
        ),
        "partnership": re.compile(
            r"Administrator to (?P<value>Horizon Access Fund IV \(Jio Feeder\), L\.P\.) —"
        ),
        "investor_of_record": re.compile(r"Investor of Record: (?P<value>7GC Fund I, L\.P\.)"),
        "capital_commitment": re.compile(r"Capital commitment\s+(?P<value>\$[\d,]+\.\d{2})"),
        "contributed_capital": re.compile(
            r"Contributed capital \(inception to date\)\s+(?P<value>\$[\d,]+\.\d{2})"
        ),
        "distributions": re.compile(
            r"Distributions \(inception to date\)\s+(?P<value>\$[\d,]+\.\d{2})"
        ),
        "net_asset_value": re.compile(
            r"Net asset value of capital account\s+(?P<value>\$[\d,]+\.\d{2})"
        ),
        "unfunded_commitment": re.compile(r"Unfunded commitment\s+(?P<value>\$[\d,]+\.\d{2})"),
        "underlying_position": re.compile(
            r"a single underlying position: (?P<value>an indirect interest in Jio Platforms "
            r"Limited, acquired July 2020\.)"
        ),
        "valuation_basis": re.compile(
            r"(?P<value>based on the price of the most recent observable financing round of "
            r"the underlying company)"
        ),
        "audit_status": re.compile(r"(?P<value>Figures are unaudited\.)"),
        # INV-16 · the ground on which the window below closes at the year end.
        "issuance_cadence": re.compile(
            r"(?P<value>Statements are issued annually as of the Partnership's fiscal year end)"
        ),
    }


#: Meridian's covering email. A `.txt` parsed by the same `parse()` under
#: `utf8-verbatim@1`; nothing about the write path treats it differently from a
#: PDF, which is the point — the transport is not a property the ledger records.
_MERIDIAN_EMAIL: dict[str, re.Pattern[str]] = {
    "delivery_date": re.compile(r"\nDate: (?P<value>Friday, January 30, 2026, 6:02 AM ET)\n"),
    "administrator": re.compile(
        r"Kind regards,\s+Investor Services\s+(?P<value>Meridian Fund Services \(Cayman\) Ltd\.)"
    ),
    # The subject line states the same date in title case, so this anchors on the
    # body sentence and matches once.
    "statement_as_of_date": re.compile(
        r"capital account statement for Horizon Access Fund IV \(Jio Feeder\), L\.P\. "
        r"as of (?P<value>December 31, 2025)"
    ),
    # What binds the envelope to the statement it carries.
    "attachment": re.compile(
        r"Attachment: (?P<value>Horizon Access Fund IV \(Jio Feeder\) - Capital Account "
        r"Statement - 12\.31\.2025\.pdf)"
    ),
    "delivery_cadence": re.compile(
        r"(?P<value>Statements as of each fiscal year end are delivered annually via this "
        r"email address of record\.)"
    ),
    # The remedy for the two statements whose delivery nothing in the corpus
    # dates: they can be requested.
    "prior_period_availability": re.compile(
        r"(?P<value>Prior-period statements are available upon request from Investor Services\.)"
    ),
}


def _facts(
    document_version_id: str, canonical_text: str, patterns: dict[str, re.Pattern[str]]
) -> tuple[FactDraft, ...]:
    """Every named pattern, read through the one sanctioned constructor.

    `cited_fact` is the only way a fact is built anywhere in this module, so no
    offset is written down and a wrong span is unexpressible rather than
    unlikely (INV-8).
    """
    return tuple(
        cited_fact(
            document_version_id=document_version_id,
            canonical_text=canonical_text,
            field_name=field_name,
            pattern=pattern,
        )
        for field_name, pattern in patterns.items()
    )


def moonfare_memo_facts(document_version_id: str, parsed: ParsedDocument) -> tuple[FactDraft, ...]:
    """Moonfare FY2023 — the figures Clearwater's memo states."""
    return _facts(document_version_id, parsed.canonical_text, _MOONFARE_MEMO)


def moonfare_fx_facts(document_version_id: str, parsed: ParsedDocument) -> tuple[FactDraft, ...]:
    """Moonfare FY2024 — the figures the FX re-measurement memo states."""
    return _facts(document_version_id, parsed.canonical_text, _MOONFARE_FX)


def capsule_memo_facts(document_version_id: str, parsed: ParsedDocument) -> tuple[FactDraft, ...]:
    """Capsule FY2022 — the figures Clearwater's memo states."""
    return _facts(document_version_id, parsed.canonical_text, _CAPSULE_MEMO)


def jio_statement_facts(
    document_version_id: str, parsed: ParsedDocument, as_of: date
) -> tuple[FactDraft, ...]:
    """One Jio capital account statement, read against its own year."""
    return _facts(document_version_id, parsed.canonical_text, _statement_patterns(as_of))


def meridian_email_facts(document_version_id: str, parsed: ParsedDocument) -> tuple[FactDraft, ...]:
    """The covering email — what it transmits, and when it arrived."""
    return _facts(document_version_id, parsed.canonical_text, _MERIDIAN_EMAIL)


def moonfare_memo_claim(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str
) -> ClaimDraft:
    """An independent valuation memorandum, scoped to one measurement date.

    One authority: Clearwater, engaged by the Fund, speaking as valuer. Not a
    transaction instrument, so `execution_status` is `not_applicable` rather than
    `pro_forma` — INV-4's r1 guard labelled every non-executed document pro forma
    and thereby mislabelled exactly this kind of memo.

    `applicable_to` closes on the measurement date because §5 says the memo
    "should not be relied upon for subsequent measurement dates without update".
    The window is the document's, not a policy applied over it (INV-16).
    """
    return ClaimDraft(
        claim_key="fy2023_third_party_valuation",
        holding_id=holding_id,
        source_class=SourceClass.THIRD_PARTY_VALUATION_MEMO,
        execution_status=ExecutionStatus.NOT_APPLICABLE,
        issued_date=MOONFARE_FY2023,
        as_of_date=MOONFARE_FY2023,
        applicable_from=MOONFARE_FY2023,
        applicable_to=MOONFARE_FY2023,
        facts=moonfare_memo_facts(document_version_id, parsed),
    )


def moonfare_fx_claim(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str
) -> ClaimDraft:
    """The Fund's own re-measurement of the same interest — INV-15, inverted.

    This document says what it is on its first line: "7GC — FUND OPERATIONS ·
    Internal Memorandum", "Prepared by Fund Operations; reviewed by the CFO". It
    is management's arithmetic on management's position, and the EUR value it
    starts from is not its own — it is carried from the Clearwater memo above,
    whose reliance window had already closed.

    `SourceClass` has no member for a fund-internal memorandum, so the honest
    choice is between two wrong ones. `company_communication` names an interested
    party's assertion, which is what this is; `third_party_valuation_memo` would
    assert independence the document denies, and would let the FY2024 USD mark
    read as supported by an outside valuer. INVARIANTS.md counts the corpus's
    third-party memos as two — Moonfare FY2023 and Capsule FY2022 — and this is
    not one of them. Erring toward the weaker class leaves a gap an auditor can
    see; erring toward the stronger one hides that the mark rests on the Fund's
    own memo. It is now `fund_internal_record`, a `SourceClass` member added for
    exactly this: management's paperwork about management's own position. Before
    it existed the choice was between `third_party_valuation_memo`, which would
    make the FY2024 mark read as though an outside valuer had checked it, and
    `company_communication`, which is merely wrong in the safe direction. The
    oracle carried the first of those and has been corrected.

    One claim, not two. It restates the third-party memo's EUR value and adds a
    rate and a translation, but every sentence is Fund Operations speaking, and
    the reference to Clearwater is a citation rather than a second voice.
    """
    return ClaimDraft(
        claim_key="fy2024_fx_remeasurement",
        holding_id=holding_id,
        source_class=SourceClass.FUND_INTERNAL_RECORD,
        execution_status=ExecutionStatus.NOT_APPLICABLE,
        issued_date=MOONFARE_FY2024,
        as_of_date=MOONFARE_FY2024,
        applicable_from=MOONFARE_FY2024,
        # CLOSED, on the sentence's grammatical subject.
        #
        # This window was opened, then reopened wrongly, and the deciding
        # question is what "The interest will be re-measured at the closing rate
        # at each future measurement date" is a statement ABOUT. The subject is
        # *the interest*; the closing rate is the instrument of re-measurement,
        # not the thing being scoped. So it is not INV-6 speaking about a rate
        # while leaving reliance open — it is a whole-document INV-16 clause in
        # the same family as Capsule's memo and Moonfare's own FY2023 one, and
        # it says this memo does not speak to any future measurement date.
        #
        # Reading it as rate-scoped moved R2 at FY2025 from `missing` /
        # `SUPPORT_OUTSIDE_ITS_OWN_RELIANCE_WINDOW` /
        # `REQUEST_UPDATED_VALUATION` to `insufficient` /
        # `MANAGEMENT_ASSERTION_WITHOUT_PRIMARY_SOURCE` /
        # `REQUEST_PRIMARY_EVIDENCE`: a weaker gap statement on the letter's ¶2,
        # supplied by the very document whose stale figure the gap exists to
        # flag. "Go and get an updated valuation" became "go and get primary
        # evidence for the thing we already have".
        #
        # This is NOT a return to the bandage a cross-family review named. That
        # bandage was this window standing in for two defects one layer down,
        # and both are now fixed where they live: `derive_mark` returns
        # `MANAGEMENT_CARRYING_VALUE` for a `fund_internal_record`, so no
        # carry-forward can happen, and V7 decides from the rate's own cited
        # effective date rather than from whatever this window happens to say.
        # Neither depends on this field any more, which is what makes it free to
        # state what the source states.
        #
        # The memo does carry two assertions with different natural lifetimes —
        # the EUR basis and the rate — and one `applicable_to` cannot express
        # both. Splitting it is a real improvement and belongs in its own step:
        # here both expire on the same date, so the split would record something
        # true and change no verdict.
        applicable_to=MOONFARE_FY2024,
        facts=moonfare_fx_facts(document_version_id, parsed),
    )


def capsule_memo_claim(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str
) -> ClaimDraft:
    """The memo that forbids its own reuse — INV-16's failing real-data case.

    F3 is that this memo is carried at $600,000 through FY2023, FY2024 and
    FY2025. Each of those links can be made deliberately, with every date field
    correct, and each is invalid on the source's own terms. `applicable_to` is
    what makes the policy able to refuse them, and it is set from §6 rather than
    from the measurement date's calendar year — a window derived from anything
    other than the document would be an assumption wearing the document's
    clothes.

    It prices Series B and the Fund holds Series B, so nothing is cross-class
    here. `priced_class` is recorded anyway: `require_cross_class_policy` refuses
    a stated price beside a NULL class, so leaving it out would be refused rather
    than merely unhelpful.
    """
    return ClaimDraft(
        claim_key="fy2022_third_party_valuation",
        holding_id=holding_id,
        source_class=SourceClass.THIRD_PARTY_VALUATION_MEMO,
        execution_status=ExecutionStatus.NOT_APPLICABLE,
        issued_date=CAPSULE_FY2022,
        as_of_date=CAPSULE_FY2022,
        applicable_from=CAPSULE_FY2022,
        applicable_to=CAPSULE_FY2022,
        priced_class=CAPSULE_PRICED_CLASS,
        price_per_share=Decimal("1.20"),
        facts=capsule_memo_facts(document_version_id, parsed),
    )


def jio_statement_claim(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str, as_of: date
) -> ClaimDraft:
    """One fiscal year end's capital account, as the administrator states it.

    `source_class` is `administrator_statement` on all three, which is what makes
    Jio's evidence the strongest in the fund rather than the weakest. Nothing
    about the PDF container earns that; the Administrator speaking on behalf of
    the General Partner does.

    `received_date` comes from `_DELIVERED_ON` and is NULL for two of the three.
    That asymmetry is real: only FY2025 has a covering email in the corpus, so
    only FY2025 has a delivery this repository can date. 0004 falls back to the
    issue date where it is absent, which is honest; filling it in would not be.
    """
    return ClaimDraft(
        claim_key=f"fy{as_of.year}_capital_account",
        holding_id=holding_id,
        source_class=SourceClass.ADMINISTRATOR_STATEMENT,
        execution_status=ExecutionStatus.NOT_APPLICABLE,
        issued_date=as_of,
        as_of_date=as_of,
        received_date=_DELIVERED_ON.get(as_of),
        applicable_from=as_of,
        # "Statements are issued annually as of the Partnership's fiscal year
        # end" — so this one is the statement for this year end, and the next
        # year end has its own.
        applicable_to=as_of,
        facts=jio_statement_facts(document_version_id, parsed, as_of),
    )


def meridian_email_claim(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str
) -> ClaimDraft:
    """The transmittal, classified by its authority and dated by its delivery.

    INV-15 · *"Email is an envelope. Meridian's email carries an administrator
    statement."* The mis-tiering this guards against is mechanical and
    invisible — a classifier that maps every `.txt` from an inbox to
    `company_communication` passes the whole sufficiency matrix while filing
    Jio's strongest evidence with a founder's opinion. So the class is read off
    the speaker: Meridian Fund Services (Cayman) Ltd., Administrator to the
    Partnership, in the same capacity in which it issued the statement.

    One claim. Every sentence in the email is Meridian's, in that one capacity;
    the covering text describes the delivery of the same statement rather than
    asserting anything on different authority. A *company* forwarding an
    administrator statement is the case that needs two claims — the cover note
    would be a company communication and the attachment would not — and this is
    not that.

    INV-3 · three instants, three fields. The statement is issued and as of
    31 December 2025; it reached the Fund on 30 January 2026. `received_date` is
    what 0004 reads to set `is_subsequent`, and this is the corpus case that
    migration was written for: with the delivery date collapsed into the issue
    date, the truthful record was rejected and the false one was the only one
    that would commit.
    """
    return ClaimDraft(
        claim_key="fy2025_statement_delivery",
        holding_id=holding_id,
        source_class=SourceClass.ADMINISTRATOR_STATEMENT,
        execution_status=ExecutionStatus.NOT_APPLICABLE,
        # This claim is the DELIVERY, so it is dated by the delivery. The email
        # bears `Date: Friday, January 30, 2026` on its own header, and dating it
        # 31 December collapsed `issued` into `as_of` — the email stopped
        # carrying the date printed on it, which is the distinction INV-3 exists
        # to keep.
        #
        # The statement itself is the other claim, dated the fiscal year end and
        # received on the 30th. `evals/oracle/primitives.yaml` models exactly
        # this split — `jio_stmt_25` dated 2025-12-31, `jio_delivery_email`
        # dated 2026-01-30 — and the oracle is the authority on it.
        #
        # `as_of_date` stays at the year end: it is what the delivery is *about*.
        issued_date=MERIDIAN_DELIVERY_DATE,
        as_of_date=date(2025, 12, 31),
        received_date=MERIDIAN_DELIVERY_DATE,
        applicable_from=MERIDIAN_DELIVERY_DATE,
        # The email states no expiry — only that statements arrive annually and
        # prior periods are available on request. Inventing a close would be the
        # same error as ignoring Capsule's, in the other direction.
        applicable_to=None,
        facts=meridian_email_facts(document_version_id, parsed),
    )
