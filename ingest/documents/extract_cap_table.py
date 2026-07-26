"""Pro forma capitalisation tables — Fluidstack (18 Dec 2025) and Sway (30 Sep 2025).

The second and third documents of the family `extract_dream.py` opened, and the
two the audit letter is pointed at most directly: Harwell & Kent ask to
*"identify any positions marked on a pro forma basis pending receipt of executed
documentation"*, and these are those positions. Both are counsel-prepared pro
forma tables; neither is a closing set.

## Why patterns and not offsets

Same reason as Dream. `-layout` renders a cap-table row as a label, thirty-odd
spaces and a figure, so the regexes below are the reviewable artifact and the
quote is whatever they matched, verbatim. No offset is written down anywhere in
this file, which is what makes a wrong one unexpressible rather than unlikely.

Every pattern must match **exactly once** and capture `value` **inside its own
match**, so the figure is provably part of the passage cited for it (INV-8).
On a cap table that bites harder than anywhere else: `$30.00` occurs on five
rows of the Fluidstack document and `100,000` on two, so a figure lifted out of
its row cites a number that is genuinely present and says nothing about whose it
is.

## §6.2.2 — both tables are `pro_forma`

Fluidstack's note (c) references *"the executed Series B Subscription Agreement
dated December 18, 2025"* and Sway's summary says the recapitalisation *"closed
September 30, 2025"*. Neither makes the claim `executed`: `execution_status`
describes the evidence artifact in the Fund's possession, and what the Fund holds
is a pro forma table. The transaction's own state, if it is ever needed, gets its
own field — collapsing the two would make "the round closed" and "we have the
closing set" the same fact, which is precisely what the auditor is asking about.

## INV-17 — the two documents fall on opposite sides, and that is the point

* **Fluidstack is cross-class.** 7GC holds **Series A** (100,000) and **Series
  A-2** (100,000); the price this table establishes is the **Series B** price of
  $30.00. Marking either held lot at $30.00 prices one class off another's
  evidence, so `priced_class` is `series_b` and the database demands a cited
  cross-class policy decision before any valuation approval over this evidence.
* **Sway is not cross-class, and not by omission.** The recapitalisation
  converted 7GC's Series A into **Series A-3** on 30 September 2025, so at the
  effective date the class held *is* the class priced. `priced_class` is
  `series_a3` because that is what the document prices; that it also happens to
  equal the held class is a fact about the conversion, not a shortcut. Writing
  `series_a` — the class 7GC bought — would be the same one-word collapse in the
  opposite direction: it would fabricate a cross-class decision that the
  document itself resolves.

## INV-15 — Fluidstack carries two claims, Sway one

Fluidstack's note (a) is a second assertion at a different authority: *"The
Series A-2 tranche closed May 30, 2025 at $15.00 per share ($750,000,000
post-money); executed documents on file with company counsel."* Three fields of
`ClaimDraft` cannot hold it and the Series B assertion at once — `as_of_date`
(30 May 2025 against 18 December 2025, which is INV-3's own worked example),
`priced_class` (`series_a2` against `series_b`) and `execution_status`. Folding
it into the Series B claim would date a May price to December and label an A-2
price as Series B-priced. So it is its own claim.

Its `execution_status` is `unexecuted_referenced`, not `pro_forma`, and the
distinction is the audit letter's question rather than a nicety. The whole
evidentiary content of that sentence is *an execution exists and the Fund does
not hold it*: the executed A-2 documents are on file with company counsel. That
is what `unexecuted_referenced` names. §6.2.2 is not violated — it forbids
reading through to the transaction's state, and this reads the artifact: a
counsel note pointing at documents held elsewhere. The pro forma **table** is
still `pro_forma`; the pointer to an execution the Fund lacks is not.

Sway is one claim. The conversion schedule, the holders-of-record table and the
transaction summary are components of a single recapitalisation asserted by
company counsel at a single effective date — one authority, one as-of date, one
priced class. Splitting them would produce claims that differ in nothing a
reader could act on.

## What these documents do not state

`fluidstack_series_b_claim` and `sway_claim` record what is on the page and
nothing else. Two things an auditor would look for are absent from both, and the
absence is the finding rather than something to synthesise:

* **No percentage of fully diluted shares for the 7GC row.** Fluidstack's §4
  gives Holder / Security / Shares / Orig. PPS and Sway's §4 gives Holder / A-3
  Shares / Basis. Both documents carry a `% FD` column in their *class* tables
  and neither carries one per holder.
* **No expiry or no-reliance condition.** `applicable_to` is therefore `None` on
  every claim here (INV-16 is about what the *source* says; inventing a window
  would be the same error as ignoring Capsule's, in the opposite direction).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from ingest.documents.claims import ClaimDraft, FactDraft, cited_fact
from ingest.documents.parse import ParsedDocument
from packages.contracts.citations import CitationError
from packages.contracts.enums import ExecutionStatus, SourceClass

#: 18 December 2025 — the closing date Fluidstack's header states, and the date
#: from which its table is the round of record. INV-3 keeps this separate from
#: the measurement date it is relied on at.
FLUIDSTACK_CLOSING_DATE = date(2025, 12, 18)

#: 30 May 2025 — stated by note (a) for the Series A-2 tranche. A December
#: document evidencing a May price is INV-3's worked example, and the reason the
#: note is a claim of its own rather than a fact on the Series B claim.
FLUIDSTACK_SERIES_A2_CLOSING_DATE = date(2025, 5, 30)

#: The classes 7GC holds in Fluidstack, and the class the table prices. They
#: differ, which is what makes this the corpus's second cross-class case.
FLUIDSTACK_HELD_CLASSES = ("series_a", "series_a2")
FLUIDSTACK_PRICED_CLASS = "series_b"

#: 30 September 2025 — Sway's stated effective date, its stated closing date and
#: the date the conversion takes effect. 26 September is when the holders
#: approved it; the two are separate assertions and both are extracted.
SWAY_EFFECTIVE_DATE = date(2025, 9, 30)
SWAY_HOLDER_APPROVAL_DATE = date(2025, 9, 26)

#: Sway's conversion moves the held class onto the priced class at the effective
#: date. `SWAY_PRIOR_HELD_CLASS` is what 7GC held going in and is kept because a
#: mark before 30 September 2025 is a mark on Series A, not on Series A-3.
SWAY_PRIOR_HELD_CLASS = "series_a"
SWAY_HELD_CLASS = "series_a3"
SWAY_PRICED_CLASS = "series_a3"

#: Fluidstack, Series B pro forma. The 7GC rows are matched whole — holder,
#: security, shares and original price in one quote — because `100,000` is the
#: share count of both held lots and `$15.00` appears three times in the
#: document. A figure taken out of its row would cite a real number and name
#: nobody.
#:
#: `Series A\s` does not match `Series A-2`: the character after `Series A` in
#: the A-2 row is a hyphen, so the two rows cannot be confused for one another.
_FLUIDSTACK_SERIES_B_PATTERNS: dict[str, re.Pattern[str]] = {
    "fund_series_a_security_class": re.compile(
        r"7GC Fund II, L\.P\.\s+(?P<value>Series A)\s+[\d,]+\s+\$[\d.]+"
    ),
    "fund_series_a_shares": re.compile(
        r"7GC Fund II, L\.P\.\s+Series A\s+(?P<value>[\d,]+)\s+\$[\d.]+"
    ),
    "fund_series_a_original_pps": re.compile(
        r"7GC Fund II, L\.P\.\s+Series A\s+[\d,]+\s+(?P<value>\$[\d.]+)"
    ),
    "fund_series_a2_security_class": re.compile(
        r"7GC Fund II, L\.P\.\s+(?P<value>Series A-2)\s+[\d,]+\s+\$[\d.]+"
    ),
    "fund_series_a2_shares": re.compile(
        r"7GC Fund II, L\.P\.\s+Series A-2\s+(?P<value>[\d,]+)\s+\$[\d.]+"
    ),
    "fund_series_a2_original_pps": re.compile(
        r"7GC Fund II, L\.P\.\s+Series A-2\s+[\d,]+\s+(?P<value>\$[\d.]+)"
    ),
    "series_b_price_per_share": re.compile(
        r"Series B Preferred issued at (?P<value>\$[\d.]+) per share"
    ),
    "series_b_gross_proceeds": re.compile(
        r"Aggregate gross proceeds: (?P<value>\$[\d,]+) \([\d,]+ shares\)"
    ),
    "series_b_shares_issued": re.compile(
        r"Aggregate gross proceeds: \$[\d,]+ \((?P<value>[\d,]+) shares\)"
    ),
    "post_money_valuation": re.compile(
        r"Post-money valuation: (?P<value>\$[\d,]+) on [\d,]+ fully diluted shares"
    ),
    "fully_diluted_shares": re.compile(
        r"Post-money valuation: \$[\d,]+ on (?P<value>[\d,]+) fully diluted shares"
    ),
    # The sentence ends in a full stop, and the pattern stops before it. A quote
    # of `Pre-money valuation: $1,350,000,000.` states no figure `supports_value`
    # will accept: a full stop against a figure means it is part of a longer one,
    # which is the rule that refuses `625` cited to `625,000`. It cannot know
    # this one is a sentence ending, and it must not guess.
    "pre_money_valuation": re.compile(r"Pre-money valuation: (?P<value>\$[\d,]+)"),
    # 18 December 2025 appears twice — the header and note (c) — so the header
    # is named in the pattern rather than the date searched for on its own.
    "closing_date": re.compile(r"Closing Date: (?P<value>[A-Z][a-z]+ \d+, \d{4})"),
    # The executed document this pro forma table points at. Recording it is what
    # turns "the round closed" into a specific, checkable request an auditor can
    # make; §6.2.2 is why it does not make the claim `executed`.
    "series_b_subscription_agreement": re.compile(
        r"the (?P<value>executed Series B Subscription Agreement dated [A-Z][a-z]+ \d+, \d{4})"
    ),
}

#: Fluidstack, note (a) — the Series A-2 tranche. A separate claim (INV-15), so a
#: separate pattern set. The month is matched as a word rather than written into
#: the regex: `May 30, 2025` is a figure the document states, not a constant this
#: file is entitled to assert.
_FLUIDSTACK_SERIES_A2_PATTERNS: dict[str, re.Pattern[str]] = {
    "series_a2_closing_date": re.compile(
        r"The Series A-2 tranche closed (?P<value>[A-Z][a-z]+ \d+, \d{4}) at \$[\d.]+ per share"
    ),
    "series_a2_price_per_share": re.compile(
        r"tranche closed [A-Z][a-z]+ \d+, \d{4} at (?P<value>\$[\d.]+) per share"
    ),
    "series_a2_post_money_valuation": re.compile(
        r"at \$[\d.]+ per share \((?P<value>\$[\d,]+) post-money\)"
    ),
    # The gap itself, in the document's own words. The line wraps between `with`
    # and `company`, so the quote carries that newline: the canonical text is the
    # extractor's output with no post-processing, and a value stitched back
    # together would no longer be a substring of the document (SPEC §8).
    "series_a2_executed_documents": re.compile(
        r"\(\$[\d,]+ post-money\); (?P<value>executed documents on file with\s+company counsel)"
    ),
}

#: Sway, Series A-3 recapitalisation. The exchange ratio is captured as
#: `1.09375` rather than `1.09375 : 1` so that `cited_numeral` reads a figure
#: from it — V13 multiplies by this number, and a ratio stored as prose would
#: give the validator nothing to multiply.
#:
#: `series_seed_a3_shares_issued` is cited to the tail of its row rather than to
#: the whole row, and that is forced by the data: the Series Seed line states
#: `1,250,000` **twice** — prior shares and shares issued, because the ratio is
#: 1.0000 : 1 — so a whole-row quote would not say which of the two it means.
#: `supports_value` refuses it, correctly. The Series A row states three
#: distinct figures and is quoted whole.
_SWAY_PATTERNS: dict[str, re.Pattern[str]] = {
    "effective_date": re.compile(r"Effective (?P<value>[A-Z][a-z]+ \d+, \d{4})"),
    "holder_approval_date": re.compile(
        r"approved by the requisite holders on (?P<value>[A-Z][a-z]+ \d+, \d{4})"
    ),
    "closing_date": re.compile(r"and closed (?P<value>[A-Z][a-z]+ \d+, \d{4})"),
    "series_a3_price_per_share": re.compile(
        r"Series A-3 Preferred issued at (?P<value>\$[\d.]+) per share"
    ),
    "new_money_aggregate_capital": re.compile(
        r"aggregate new capital of (?P<value>\$[\d,]+) \([\d,]+ shares\)"
    ),
    "new_money_shares": re.compile(
        r"aggregate new capital of \$[\d,]+ \((?P<value>[\d,]+) shares\)"
    ),
    "post_money_valuation": re.compile(
        r"Post-money\s+valuation: (?P<value>\$[\d,]+) on [\d,]+ fully diluted shares"
    ),
    "fully_diluted_shares": re.compile(
        r"Post-money\s+valuation: \$[\d,]+ on (?P<value>[\d,]+) fully diluted shares"
    ),
    # The class every prior preferred becomes. This is the documentary support
    # for `priced_class == held class` at the effective date, which is the whole
    # reason Sway is not a cross-class case. The line wraps after `Series`.
    "converted_into_class": re.compile(
        r"converted into (?P<value>Series\s+A-3 Preferred) pursuant to the "
        r"Recapitalization Agreement"
    ),
    # The prior classes' original prices — `$0.90` for the Seed and `$2.50` for
    # the Series A — are NOT extracted, and the reason is a refusal rather than
    # an oversight. Both appear only inside a row label, `Series Seed Preferred
    # ($0.90, 2022)`, where the figure is immediately followed by a comma.
    # `supports_value` reads a comma against a figure as evidence that it is
    # three digits of a longer one, which is the rule that refuses `625` cited
    # to a row stating `625,000`. Widening that rule to let this through would
    # weaken the guard everywhere to gain a figure the audit letter does not
    # ask for, so the two prices stay uncited and are reported as an absence.
    "prior_series_seed_shares": re.compile(
        r"Series Seed Preferred \(\$[\d.]+, \d{4}\)\s+(?P<value>[\d,]+)\s+[\d.]+ : 1"
    ),
    "prior_series_seed_exchange_ratio": re.compile(
        r"Series Seed Preferred \(\$[\d.]+, \d{4}\)\s+[\d,]+\s+(?P<value>[\d.]+) : 1"
    ),
    "series_seed_a3_shares_issued": re.compile(r"1\.0000 : 1\s+(?P<value>[\d,]+)"),
    "prior_series_a_shares": re.compile(
        r"Series A Preferred \(\$[\d.]+, [A-Z][a-z]+ \d{4}\)\s+(?P<value>[\d,]+)\s+[\d.]+ : 1"
    ),
    "prior_series_a_exchange_ratio": re.compile(
        r"Series A Preferred \(\$[\d.]+, [A-Z][a-z]+ \d{4}\)\s+[\d,]+\s+(?P<value>[\d.]+) : 1"
    ),
    "series_a_a3_shares_issued": re.compile(
        r"Series A Preferred \(\$[\d.]+, [A-Z][a-z]+ \d{4}\)"
        r"\s+[\d,]+\s+[\d.]+ : 1\s+(?P<value>[\d,]+)"
    ),
    "total_prior_conversion_shares": re.compile(
        r"Total conversion shares\s+(?P<value>[\d,]+)\s+[\d,]+"
    ),
    "total_a3_conversion_shares_issued": re.compile(
        r"Total conversion shares\s+[\d,]+\s+(?P<value>[\d,]+)"
    ),
    "fund_a3_shares": re.compile(
        r"7GC Fund II, L\.P\.\s+(?P<value>[\d,]+)\s+Conversion of [\d,]+ Series A at [\d.]+ : 1"
    ),
    "fund_prior_security_class": re.compile(
        r"7GC Fund II, L\.P\.\s+[\d,]+\s+Conversion of [\d,]+ (?P<value>Series A) at [\d.]+ : 1"
    ),
    "fund_prior_shares": re.compile(
        r"7GC Fund II, L\.P\.\s+[\d,]+\s+Conversion of (?P<value>[\d,]+) Series A at [\d.]+ : 1"
    ),
    "fund_exchange_ratio": re.compile(
        r"7GC Fund II, L\.P\.\s+[\d,]+\s+Conversion of [\d,]+ Series A at (?P<value>[\d.]+) : 1"
    ),
    # Note (b). 7GC's A-3 shares are conversion shares only, so the $0.40 the
    # round prices is not a price 7GC paid — an auditor reading the holder row
    # without this would read 875,000 shares as bought at $0.40.
    "fund_new_money_participation": re.compile(
        r"conversion shares only; "
        r"(?P<value>7GC Fund II, L\.P\. did not participate in the new-money tranche)"
    ),
}


def _facts(
    document_version_id: str,
    canonical_text: str,
    patterns: dict[str, re.Pattern[str]],
) -> tuple[FactDraft, ...]:
    return tuple(
        cited_fact(
            document_version_id=document_version_id,
            canonical_text=canonical_text,
            field_name=field_name,
            pattern=pattern,
        )
        for field_name, pattern in patterns.items()
    )


def _price_the_document_states(
    facts: tuple[FactDraft, ...], field_name: str, expected: Decimal
) -> Decimal:
    """`expected`, but only once the document has been read saying it.

    `ClaimDraft.price_per_share` is the one figure on a claim that is typed by
    hand rather than matched out of the text, and it is the figure the whole
    mark is computed from. A transposed digit there is invisible: it is a
    plausible price, it stores, and every citation on the claim still resolves —
    because the citations are on the *facts*, and nothing bound the claim's
    price to any of them.

    So the constant is checked against the fact that states it. This is not a
    recomputation of the document; it is the assertion that the two agree, which
    is the assertion nobody was making.
    """
    for fact in facts:
        if fact.field_name != field_name:
            continue
        if fact.value_numeric != expected:
            raise CitationError(
                f"{field_name}: the claim is priced at {expected} but the document "
                f"states {fact.value_text!r} ({fact.value_numeric}) in the passage "
                f"cited for it. A hand-typed price that no fact supports prices "
                f"the mark off nothing."
            )
        return expected
    raise CitationError(
        f"{field_name}: a claim priced at {expected} carries no fact of that name, "
        f"so its price is cited to nothing"
    )


def fluidstack_series_b_facts(
    document_version_id: str, parsed: ParsedDocument
) -> tuple[FactDraft, ...]:
    """Every figure the Series B pro forma table states that the packet relies on."""
    return _facts(document_version_id, parsed.canonical_text, _FLUIDSTACK_SERIES_B_PATTERNS)


def fluidstack_series_a2_facts(
    document_version_id: str, parsed: ParsedDocument
) -> tuple[FactDraft, ...]:
    """Note (a) — the Series A-2 tranche, and where its executed documents are."""
    return _facts(document_version_id, parsed.canonical_text, _FLUIDSTACK_SERIES_A2_PATTERNS)


def sway_facts(document_version_id: str, parsed: ParsedDocument) -> tuple[FactDraft, ...]:
    """Every figure the recapitalisation table states, including both sides of
    the conversion. V13 needs the ratio, the prior share count and the resulting
    share count as three separately cited figures — a ratio checked against a
    share count this module had derived would be checking itself."""
    return _facts(document_version_id, parsed.canonical_text, _SWAY_PATTERNS)


def fluidstack_series_b_claim(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str
) -> ClaimDraft:
    """The pro forma Series B table: a company cap table, priced at $30.00."""
    facts = fluidstack_series_b_facts(document_version_id, parsed)
    return ClaimDraft(
        claim_key="series_b_pro_forma",
        holding_id=holding_id,
        source_class=SourceClass.COMPANY_CAP_TABLE,
        execution_status=ExecutionStatus.PRO_FORMA,
        issued_date=FLUIDSTACK_CLOSING_DATE,
        as_of_date=FLUIDSTACK_CLOSING_DATE,
        applicable_from=FLUIDSTACK_CLOSING_DATE,
        applicable_to=None,
        priced_class=FLUIDSTACK_PRICED_CLASS,
        price_per_share=_price_the_document_states(
            facts, "series_b_price_per_share", Decimal("30.00")
        ),
        facts=facts,
    )


def fluidstack_series_a2_claim(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str
) -> ClaimDraft:
    """Note (a): the May 2025 Series A-2 price, and an execution held elsewhere.

    `issued_date` is the cap table's date, because that is when this artifact was
    prepared; `as_of_date` and `applicable_from` are 30 May 2025, because that is
    the date the price it states is a price *at*. INV-3 is exactly this
    separation, and Fluidstack is the example INVARIANTS.md gives for it.
    """
    facts = fluidstack_series_a2_facts(document_version_id, parsed)
    return ClaimDraft(
        claim_key="series_a2_referenced_execution",
        holding_id=holding_id,
        source_class=SourceClass.COMPANY_CAP_TABLE,
        execution_status=ExecutionStatus.UNEXECUTED_REFERENCED,
        issued_date=FLUIDSTACK_CLOSING_DATE,
        as_of_date=FLUIDSTACK_SERIES_A2_CLOSING_DATE,
        applicable_from=FLUIDSTACK_SERIES_A2_CLOSING_DATE,
        applicable_to=None,
        priced_class="series_a2",
        price_per_share=_price_the_document_states(
            facts, "series_a2_price_per_share", Decimal("15.00")
        ),
        facts=facts,
    )


def fluidstack_claims(
    *, document_version_id: str, parsed: ParsedDocument, holding_id: str
) -> tuple[ClaimDraft, ...]:
    """Both assertions the Fluidstack document makes. INV-15.

    Plural because the authority differs, not because the document is long. A
    reader who wants only the mark's evidence takes the first; the second exists
    so that the A-2 price is not silently dated December and not silently
    labelled Series B-priced.
    """
    return (
        fluidstack_series_b_claim(
            document_version_id=document_version_id, parsed=parsed, holding_id=holding_id
        ),
        fluidstack_series_a2_claim(
            document_version_id=document_version_id, parsed=parsed, holding_id=holding_id
        ),
    )


def sway_claim(*, document_version_id: str, parsed: ParsedDocument, holding_id: str) -> ClaimDraft:
    """The one assertion the recapitalisation table makes, at one authority.

    Singular, deliberately. Sections 1 to 4 state a transaction summary, a post-
    recap capitalisation, a conversion schedule and a holders-of-record table —
    four sections, one recapitalisation, prepared by one company counsel and
    effective on one date, pricing one class. A second `ClaimDraft` here would
    differ from the first in nothing a policy could read.

    `price_per_share` is the $0.40 new-money price, which is the price this
    document establishes for Series A-3. 7GC did not pay it: its 875,000 shares
    are conversion shares, and note (b) says so in the document's own words —
    which is why that note is extracted as a fact rather than left as context.
    """
    facts = sway_facts(document_version_id, parsed)
    return ClaimDraft(
        claim_key="series_a3_recap_pro_forma",
        holding_id=holding_id,
        source_class=SourceClass.COMPANY_CAP_TABLE,
        execution_status=ExecutionStatus.PRO_FORMA,
        issued_date=SWAY_EFFECTIVE_DATE,
        as_of_date=SWAY_EFFECTIVE_DATE,
        applicable_from=SWAY_EFFECTIVE_DATE,
        applicable_to=None,
        priced_class=SWAY_PRICED_CLASS,
        price_per_share=_price_the_document_states(
            facts, "series_a3_price_per_share", Decimal("0.40")
        ),
        facts=facts,
    )
