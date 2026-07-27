"""Family A — executed Stock Purchase Agreements: Fluidstack, Poolside, Roofstock.

Harwell & Kent's request 1 asks for *"executed transaction documents supporting
the Fund's acquisition of each position ... including share counts, price per
share, and settlement of funds."* These three files are the only documents in
the corpus that answer it head-on, which makes them the strongest evidence in
the set — and makes every judgement below a judgement about not quietly
weakening them.

## Two claims per document, not one — INV-15

Each file carries assertions of two genuinely different authorities, and request
1 asks for both, so they are separated rather than filed under the envelope:

* **The Agreement** — Sections 1 and 2, Schedule A, and a signature block signed
  by the Company and by the Fund. `executed_transaction_doc` / `executed`. It
  states what the Fund agreed to buy and at what price.
* **The Wire Settlement Confirmation**, headed *"(Attached to Closing Set)"* and
  sourced *"per the settlement statement of company counsel."* Nobody signs a
  wire confirmation; it is an observation that cash moved, not a term anyone
  agreed to. `company_communication` / `not_applicable` — and INV-4 is explicit
  that `not_applicable` does not imply pro forma.

Filing the second under the first's authority would label the weakest assertion
in the file `executed_transaction_doc`, so an auditor testing settlement would
follow the citation to a contract *promising* payment rather than to evidence of
it. That is INV-15's failure mode with the sign reversed: classifying by
envelope here would *upgrade* rather than downgrade.

Poolside's and Roofstock's closing "Fund records note" — *"no subsequent
financing rounds have been documented"* — is a third authority again: the Fund's
own records, not the company's and not counsel's. `SourceClass` has no member
for a fund-internal record, so it is left to the gap inventory rather than filed
under a class that would misdescribe it. Minting a class to hold it would be the
same collapse in the other direction.

Section 2's conditions reference agreements this file does not contain — an
Investors' Rights Agreement, a Voting Agreement, a legal opinion. No claim is
made about them here: they carry no figure the packet relies on, and a claim
asserting them would be `unexecuted_referenced`, never `executed` (SPEC §6.2.2).
They belong to the gap inventory as referenced documents of unspecified
location.

## Which class the document prices — INV-17

`priced_class` is the class the agreement prices, which is not the same
statement as "the class the Fund holds". Fluidstack is the case: that holding
carries a Series A lot **and** a Series A-2 lot, and this agreement prices
Series A alone. Reading `priced_class` off the holding would silently extend
$10.00 to the A-2 lot, and the database's cross-class trigger — which exists to
demand a cited policy decision before that happens — would never fire.

## What the three do not share

They look alike and are not the same document:

* Fluidstack states a post-money valuation and **no fully diluted share count**,
  so it carries no `fully_diluted_shares` fact and V4 has nothing to compare.
  Poolside and Roofstock state both.
* Roofstock has **no closing clause at all**. Its `as_of_date` is therefore NULL
  rather than a date borrowed from the agreement date, and `applicable_from`
  falls back to the date the instrument bears.
* Fluidstack spells the Fund's settlement date `10/10/2024`; the other two write
  it out. Both spellings are matched and neither is rewritten — a repaired date
  would no longer be a substring of the document (SPEC §8).

## Why patterns and not offsets

The same reason as `extract_dream.py`: `-layout` renders a Schedule A row as a
name, sixty spaces and three figures. The regex is the reviewable artifact, the
quote is whatever it matched verbatim, and the span is computed from that match.
No offset is written down in this file, so a wrong one is unexpressible rather
than merely unlikely.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ingest.documents.claims import ClaimDraft, FactDraft, cited_fact
from ingest.documents.parse import ParsedDocument
from packages.contracts.citations import CitationError
from packages.contracts.enums import ExecutionStatus, SourceClass

_CORPUS = Path("7GC Audit Case Study/02_Portfolio Documentation")

#: Fragments every pattern below is built from, named once so that how this
#: corpus spells a figure is stated in one place rather than in nine patterns.
#: `_PPS` carries no thousands separator and `_MONEY` insists on cents, which is
#: what keeps a per-share price and an aggregate from matching each other's
#: column when a row's whitespace shifts.
_SHARES = r"[\d,]+"
_PPS = r"\$[\d.]+"
_MONEY = r"\$[\d,]+\.\d\d"
_WHOLE_MONEY = r"\$[\d,]+"
_DATE_SPELLED = r"[A-Z][a-z]+ \d{1,2}, \d{4}"
_DATE_SLASHED = r"\d{2}/\d{2}/\d{4}"

#: How this corpus spells a payment reference, public because the same shape is
#: read on Jackpocket's realisation notice — `JP-M-1187` on a letter of
#: transmittal. Imported there rather than restated, so the format is stated
#: once and two extractors cannot drift into two ideas of what one looks like.
WIRE_REF = r"[A-Z]{2}-[A-Z]-\d{4}"

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

#: Poolside and Roofstock state a fully diluted share count beside the
#: valuation; Fluidstack does not. One pattern, held by the two documents that
#: state it, so the third's silence is a missing fact rather than a fact that
#: quietly reads zero.
_FULLY_DILUTED_SHARES = re.compile(
    r"on a fully diluted basis \((?P<value>" + _SHARES + r")\s+fully diluted shares\)"
)


def _agreement_patterns(purchaser: str) -> dict[str, re.Pattern[str]]:
    """What all three agreements state, in the words all three use.

    Every pattern must match exactly once and must capture `value` inside its
    own match, so the figure is provably part of the passage cited for it.
    """
    return {
        # The class the agreement prices, taken from the line that names the
        # instrument. `Series A Preferred Shares` also appears in the section
        # heading and again in §1.1 across a line break, so the title line is
        # the one place it identifies itself unambiguously.
        "priced_security_class": re.compile(
            r"(?P<value>Series [A-Z0-9-]+ Preferred (?:Share|Stock))"
            r" Purchase Agreement \(Excerpt\)"
        ),
        "agreement_date": re.compile(r"is made as of (?P<value>" + _DATE_SPELLED + r")"),
        # `\s+` rather than a space: Poolside and Roofstock wrap the line
        # between the figure and "per share", and Fluidstack does not.
        "round_price_per_share": re.compile(
            r"at a purchase price of (?P<value>" + _PPS + r")\s+per share"
        ),
        # Fluidstack writes "valuation of the Company of"; the other two write
        # "valuation of".
        "post_money_valuation": re.compile(
            r"post-money valuation of (?:the Company of )?"
            r"(?P<value>" + _WHOLE_MONEY + r") on a fully diluted"
        ),
        # Three reads of one Schedule A row, each quoting the whole row.
        # $10.00 occurs six times in Fluidstack, so a figure lifted out of its
        # row cites a number that is genuinely present and says nothing about
        # whose it is. The purchaser's name alone is not enough either: it also
        # heads the wire confirmation and the signature block, so each pattern
        # carries the shape of the row rather than just the name.
        "fund_shares": re.compile(
            purchaser + r"\s+(?P<value>" + _SHARES + r")\s+" + _PPS + r"\s+" + _MONEY
        ),
        "fund_price_per_share": re.compile(
            purchaser + r"\s+" + _SHARES + r"\s+(?P<value>" + _PPS + r")\s+" + _MONEY
        ),
        "fund_aggregate_purchase_price": re.compile(
            purchaser + r"\s+" + _SHARES + r"\s+" + _PPS + r"\s+(?P<value>" + _MONEY + r")"
        ),
        # V6 compares the stated total against the sum of Schedule A's rows, so
        # the stated total has to be read rather than assumed. It is the total
        # of this schedule — not the Fund's cost, and not the round size as any
        # other document reports it — which is what the field name has to say.
        "schedule_a_total_shares": re.compile(r"Total\s+(?P<value>" + _SHARES + r")\s+" + _MONEY),
        "schedule_a_total_purchase_price": re.compile(
            r"Total\s+" + _SHARES + r"\s+(?P<value>" + _MONEY + r")"
        ),
        # The evidence that `execution_status` is `executed` at all. Citing both
        # signatures makes that classification something an auditor can check
        # rather than something this module asserts about the file.
        "company_signature": re.compile(r"COMPANY: [^\n]+ — (?P<value>/s/ [^\n]+)"),
        "purchaser_signature": re.compile(
            r"PURCHASER: " + purchaser + r"[^\n]* — (?P<value>/s/ [^\n]+)"
        ),
    }


def _settlement_patterns(purchaser: str) -> dict[str, re.Pattern[str]]:
    """The wire confirmation's own figures — request 1's third element.

    The reference is what an auditor carries to a bank record, so it is cited
    from the same passage as the amount rather than on its own: `ref.` wraps a
    line in all three files, and a quote of the reference alone would point at
    a code with no payer, amount or date beside it.
    """
    line = purchaser + r": "
    settled = r" received (" + _DATE_SLASHED + r"|" + _DATE_SPELLED + r")"
    return {
        # Quoted through the date, not just to "received": an amount cited
        # without the day it moved is not settlement evidence, it is a number.
        "settlement_amount_received": re.compile(line + r"(?P<value>" + _MONEY + r")" + settled),
        "settlement_date": re.compile(
            line + _MONEY + r" received (?P<value>" + _DATE_SLASHED + r"|" + _DATE_SPELLED + r")"
        ),
        "settlement_reference": re.compile(
            line + _MONEY + r" received [^\n]*ref\.\s+(?P<value>" + WIRE_REF + r")"
        ),
    }


@dataclass(frozen=True)
class SpaDocument:
    """One executed agreement, and the things about it that are not figures."""

    key: str
    path: Path
    #: The Fund entity as Schedule A spells it, written as regex source so the
    #: full stops in `L.P.` cannot stand for any character.
    purchaser: str
    #: INV-17 · the class this agreement PRICES. Checked against the class the
    #: document names itself, so a one-word substitution cannot pass silently.
    priced_class: str
    #: Every class the Fund holds in this company, from the lot records rather
    #: than from this document. Recorded so the INV-17 question — does the
    #: agreement price every class held? — can be asked by a test instead of
    #: re-derived there. No claim field is built from it.
    held_classes: tuple[str, ...]
    #: Hand-transcribed. `_dated` refuses any of these that the document does
    #: not state in its own words, so a literal cannot drift from its source.
    agreement_date: date
    #: None where the document states no closing date at all. INV-3.
    closing_date: date | None
    settlement_date: date
    #: Patterns for what only this document states.
    extra_patterns: Mapping[str, re.Pattern[str]]
    #: The Fund's own record-keeping note, where the document carries one.
    #:
    #: Poolside and Roofstock each close with a sentence saying no later
    #: financing round is in the Fund's records. That sentence is the whole basis
    #: on which those marks stay unchanged across measurement dates — the audit
    #: letter's request 3 — and nothing read it, so the evidence for the letter's
    #: third question was dropped while the file looked fully extracted.
    #: Fluidstack's agreement carries no such note and gets no such claim.
    fund_records_note: re.Pattern[str] | None = None


FLUIDSTACK = SpaDocument(
    key="fluidstack",
    path=_CORPUS
    / "Fluidstack"
    / "Fluidstack - Series A - Stock Purchase Agreement Excerpt (October 10, 2024).pdf",
    purchaser=r"7GC Fund II, L\.P\.",
    priced_class="series_a",
    # The A-2 lot is held and is NOT priced by this agreement. That gap is the
    # whole of INV-17 for this document.
    held_classes=("series_a", "series_a2"),
    agreement_date=date(2024, 10, 10),
    closing_date=date(2024, 10, 10),
    settlement_date=date(2024, 10, 10),
    # No fully diluted share count anywhere in the file: §1.3 states the
    # post-money valuation "on a fully diluted basis" and stops there.
    extra_patterns={
        "closing_date": re.compile(
            r"of documents and signatures on (?P<value>" + _DATE_SPELLED + r")"
        ),
    },
)

POOLSIDE = SpaDocument(
    key="poolside",
    path=_CORPUS
    / "Poolside"
    / "Poolside - Series B - Stock Purchase Agreement Excerpt (August 1, 2024).pdf",
    purchaser=r"7GC Fund II, L\.P\.",
    priced_class="series_b",
    held_classes=("series_b",),
    agreement_date=date(2024, 8, 1),
    closing_date=date(2024, 8, 1),
    settlement_date=date(2024, 8, 1),
    extra_patterns={
        "closing_date": re.compile(
            r"The Closing shall occur remotely on (?P<value>" + _DATE_SPELLED + r")"
        ),
        "fully_diluted_shares": _FULLY_DILUTED_SHARES,
    },
    fund_records_note=re.compile(
        r"Fund records note: (?P<value>no subsequent financing rounds have been "
        r"documented for this company as of the Fund's most recent records\.)"
    ),
)

ROOFSTOCK = SpaDocument(
    key="roofstock",
    path=_CORPUS
    / "Roofstock"
    / "Roofstock - Series E - Stock Purchase Agreement Excerpt (November 8, 2021).pdf",
    # Fund I, not Fund II. The letter is a Fund II audit; the same categories are
    # applied to Fund I deliberately (SPEC §2), and reading the Fund II row out
    # of a Fund I closing set would cite a row that does not exist.
    purchaser=r"7GC Fund I, L\.P\.",
    priced_class="series_e",
    held_classes=("series_e",),
    agreement_date=date(2021, 11, 8),
    # The only one of the three with no closing clause. Not an omission here:
    # the document does not state one, so nothing may.
    closing_date=None,
    settlement_date=date(2021, 11, 8),
    extra_patterns={"fully_diluted_shares": _FULLY_DILUTED_SHARES},
    fund_records_note=re.compile(
        r"Fund records note: (?P<value>no subsequent financing rounds documented "
        r"in the Fund's records after this closing\.)"
    ),
)

#: The family, keyed the way the oracle keys its holdings.
DOCUMENTS: dict[str, SpaDocument] = {doc.key: doc for doc in (FLUIDSTACK, POOLSIDE, ROOFSTOCK)}


def spa_facts(
    document_version_id: str, parsed: ParsedDocument, spec: SpaDocument
) -> tuple[FactDraft, ...]:
    """Every figure the agreement itself states."""
    return _facts(
        document_version_id,
        parsed,
        {**_agreement_patterns(spec.purchaser), **spec.extra_patterns},
    )


def spa_settlement_facts(
    document_version_id: str, parsed: ParsedDocument, spec: SpaDocument
) -> tuple[FactDraft, ...]:
    """Every figure the attached wire confirmation states."""
    return _facts(document_version_id, parsed, _settlement_patterns(spec.purchaser))


def spa_claim(
    *,
    document_version_id: str,
    parsed: ParsedDocument,
    spec: SpaDocument,
    holding_id: str,
) -> ClaimDraft:
    """The executed agreement's assertion — the first of the file's two.

    §6.2.2 · `execution_status` describes the artifact in the Fund's
    possession. Here the artifact is a signed agreement, and both signature
    lines are cited facts on this claim, so `executed` is checkable rather than
    asserted. Dream's cap table is the opposite case and lands on `pro_forma`
    despite describing a closed round.

    `price_per_share` is read out of the cited fact rather than written as a
    literal beside it. The document is the only thing that can say what the
    round priced at, and a literal is a second copy of that figure with nothing
    holding the two together.

    `as_of_date` is the closing date the document states, and is NULL for
    Roofstock, which states none (INV-3). `applicable_to` is NULL for all three:
    none of them states an expiry, and INV-16 is about what the source says —
    inventing a window here would be Capsule's error in the opposite direction.
    """
    facts = spa_facts(document_version_id, parsed, spec)

    named = _fact(facts, "priced_security_class").value_text
    if _class_slug(named) != spec.priced_class:
        raise CitationError(
            f"priced_class {spec.priced_class!r} is not the class this document "
            f"names ({named!r}). INV-17 · pricing one class off another's "
            "evidence is a policy act, not a spelling."
        )

    price = _fact(facts, "round_price_per_share")
    if price.value_numeric is None:
        raise CitationError(
            f"round_price_per_share cites {price.value_text!r}, which states no "
            "single figure, so the claim would carry a price the document does not"
        )

    issued = _dated(facts, "agreement_date", spec.agreement_date)
    closed = None if spec.closing_date is None else _dated(facts, "closing_date", spec.closing_date)
    return ClaimDraft(
        claim_key=f"{spec.priced_class}_price",
        holding_id=holding_id,
        source_class=SourceClass.EXECUTED_TRANSACTION_DOC,
        execution_status=ExecutionStatus.EXECUTED,
        issued_date=issued,
        as_of_date=closed,
        # Nothing in any of the three states when the Fund received the file.
        received_date=None,
        applicable_from=issued if closed is None else closed,
        applicable_to=None,
        priced_class=spec.priced_class,
        price_per_share=price.value_numeric,
        facts=facts,
    )


def spa_settlement_claim(
    *,
    document_version_id: str,
    parsed: ParsedDocument,
    spec: SpaDocument,
    holding_id: str,
) -> ClaimDraft:
    """The wire confirmation's assertion — the second, and why there are two.

    It prices nothing, so `priced_class` and `price_per_share` are NULL. A
    settlement confirmation states that an amount moved, not what a share is
    worth, and copying the agreement's price onto it would put a price on a
    claim no auditor could trace to a passage stating one.

    The block states exactly one date — when the funds were received — so
    `as_of_date` is that instant and `issued_date` carries the same date rather
    than a different one invented for it. `received_date` stays NULL: when the
    *Fund* took delivery of this artifact is nowhere in the file, and INV-3
    exists precisely so those three are not quietly made one.
    """
    facts = spa_settlement_facts(document_version_id, parsed, spec)
    settled = _dated(facts, "settlement_date", spec.settlement_date)
    return ClaimDraft(
        claim_key=f"{spec.priced_class}_settlement",
        holding_id=holding_id,
        source_class=SourceClass.COMPANY_COMMUNICATION,
        execution_status=ExecutionStatus.NOT_APPLICABLE,
        issued_date=settled,
        as_of_date=settled,
        received_date=None,
        applicable_from=settled,
        applicable_to=None,
        priced_class=None,
        price_per_share=None,
        facts=facts,
    )


def spa_records_claim(
    *,
    document_version_id: str,
    parsed: ParsedDocument,
    spec: SpaDocument,
    holding_id: str,
) -> ClaimDraft:
    """The Fund's own note about its own records. Request 3's evidence.

    `fund_internal_record` exists for exactly this: management's paperwork about
    management's position. It is not the company speaking and not counsel — it
    is the Fund saying what its own files do and do not contain, which is
    precisely what the auditor asked management to assert.

    No price, no class: the note states no figure. It carries one fact, the
    sentence itself, cited to the passage that says it. `applicable_from` is the
    agreement date because the note speaks from the closing forward, and
    `applicable_to` is open because the note states no expiry — it says what the
    records held *as of the Fund's most recent records*, which is a claim about
    the present each time it is read, and the policy layer decides how long that
    stands.
    """
    if spec.fund_records_note is None:
        raise CitationError(f"{spec.key} states no fund-records note")
    return ClaimDraft(
        claim_key=f"{spec.priced_class}_fund_records",
        holding_id=holding_id,
        source_class=SourceClass.FUND_INTERNAL_RECORD,
        execution_status=ExecutionStatus.NOT_APPLICABLE,
        issued_date=spec.agreement_date,
        applicable_from=spec.agreement_date,
        applicable_to=None,
        facts=(
            cited_fact(
                document_version_id=document_version_id,
                canonical_text=parsed.canonical_text,
                field_name="no_subsequent_round_of_record",
                pattern=spec.fund_records_note,
            ),
        ),
    )


def spa_claims(
    *,
    document_version_id: str,
    parsed: ParsedDocument,
    spec: SpaDocument,
    holding_id: str,
) -> tuple[ClaimDraft, ...]:
    """Every assertion the file makes, in the order the file makes them."""
    claims = [
        spa_claim(
            document_version_id=document_version_id,
            parsed=parsed,
            spec=spec,
            holding_id=holding_id,
        ),
        spa_settlement_claim(
            document_version_id=document_version_id,
            parsed=parsed,
            spec=spec,
            holding_id=holding_id,
        ),
    ]
    # Checked against the text, not just the spec: a synthetic or excerpted
    # document that does not carry the sentence does not get a claim asserting
    # it. The per-document expectation tables in `tests/test_extract_spa.py` are
    # what catch a pattern that has stopped matching a document that does.
    if spec.fund_records_note is not None and spec.fund_records_note.search(parsed.canonical_text):
        claims.append(
            spa_records_claim(
                document_version_id=document_version_id,
                parsed=parsed,
                spec=spec,
                holding_id=holding_id,
            )
        )
    return tuple(claims)


def _facts(
    document_version_id: str,
    parsed: ParsedDocument,
    patterns: Mapping[str, re.Pattern[str]],
) -> tuple[FactDraft, ...]:
    return tuple(
        cited_fact(
            document_version_id=document_version_id,
            canonical_text=parsed.canonical_text,
            field_name=field_name,
            pattern=pattern,
        )
        for field_name, pattern in patterns.items()
    )


def _fact(facts: tuple[FactDraft, ...], field_name: str) -> FactDraft:
    for fact in facts:
        if fact.field_name == field_name:
            return fact
    raise CitationError(
        f"no fact named {field_name!r} was extracted, so the claim would be "
        "built from a figure nothing cited"
    )


def _dated(facts: tuple[FactDraft, ...], field_name: str, day: date) -> date:
    """`day`, but only once the document has been shown to state it.

    The date columns are the one part of a claim not read out of the text:
    `ClaimDraft` takes `date` objects and nothing here parses a month name into
    one. So each literal is checked against the passage cited for it, in both
    spellings this corpus uses. A literal that has drifted from its document —
    `date(2024, 10, 1)` against a page reading October 10 — is otherwise a
    figure that no citation, constraint or database trigger can contradict,
    because none of them ever sees it.
    """
    stated = _fact(facts, field_name).value_text
    spellings = (f"{_MONTHS[day.month - 1]} {day.day}, {day.year}", f"{day:%m/%d/%Y}")
    if stated not in spellings:
        raise CitationError(
            f"{field_name}: the document states {stated!r}, which is not "
            f"{day.isoformat()} in either spelling this corpus uses"
        )
    return day


def _class_slug(stated: str) -> str:
    """`Series A-2 Preferred Stock` → `series_a2`, the lot records' spelling.

    Narrow on purpose. It exists to compare the class a claim declares against
    the class its document names, not to parse security classes in general — a
    lenient reading would answer for text it was never shown, which is how a
    Series A agreement comes to price Series B with nothing going red.
    """
    designation = stated.removeprefix("Series ").split(" ")[0]
    return f"series_{designation.replace('-', '').lower()}"
