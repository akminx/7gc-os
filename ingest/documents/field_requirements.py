"""Which of the client's requests each extracted figure answers. A reviewed judgement.

`reliance.py` binds a CLAIM to a requirement, and that is the right granularity
for "what did we rely on". It is the wrong granularity for "show me the
support": Fluidstack's Series A purchase agreement legitimately answers ¶1 and
¶2, so under a claim-level binding every one of its twelve cited figures
rendered under both — the same window and the same figures whichever request
the auditor clicked. The document was right; the pane was answering a question
nobody asked.

A figure answers a request or it does not, and that is decidable per figure:

* **R1 · existence and cost** is about the FUND'S OWN ACQUISITION — what it
  bought, of which class, at what price, for how much, when, signed by whom,
  and (¶1's third limb) that the money actually moved.
* **R2 · fair-value support** is about THE VALUE at the measurement date — what
  a share is worth, what the round priced the company at, what a third party
  concluded, what the administrator struck, what the market closed at.
* **R3** is management's assessment that an unchanged last-round price is still
  representative, so the figures that answer it are the ones about the AGE and
  SCOPE of the support: a memo saying it may not be relied on at a later date,
  a records note saying no subsequent round is documented.
* **R4 · realisation** is what the exit paid.
* **R5 · pro-forma identification** is the labelling request, so the figures
  that answer it are the ones stating that executed documents are pending.

Two rules make this fail closed rather than fail quiet:

1. **Every `field_name` written to `extracted_fact` must appear below.**
   `store_claim` raises on one that does not, so a new extractor cannot ship a
   figure whose relevance nobody decided. There is no "all" default and no
   "none" default — both would be a judgement made by absence.
2. **A figure relevant to no request is a declared `frozenset()`**, exactly as
   seven claims already are in `reliance.py`. Fourteen of them are below and
   each says why. They are still shown: the trail lists them under the document
   they came from, marked as answering a different request. Declaring nothing
   decides where a figure is filed, never whether an auditor may see it.

**Keyed by field name, and where that is lossy it is lossy in the safe
direction.** `closing_date` is the fund's purchase closing on a stock purchase
agreement and the round's closing on a capitalisation table; `effective_date` is
a recapitalisation's on one document and a merger's on another. The declared set
is the UNION, so such a figure appears under both requests rather than
disappearing from one. Keying on `(claim_key, field_name)` would sharpen those
six entries and would also let a figure be forgotten for one document while
declared for another, which is the failure this file exists to prevent. The
union is the cheaper mistake and it is the one that shows too much.
"""

from __future__ import annotations

from packages.contracts.enums import RequirementCode

R1 = RequirementCode.R1
R2 = RequirementCode.R2
R3 = RequirementCode.R3
R4 = RequirementCode.R4
R5 = RequirementCode.R5

#: The one figure that answers nothing, said once so the reason is not retyped
#: fourteen times below.
_NOTHING: frozenset[RequirementCode] = frozenset()

#: `field_name` -> the requirements that figure answers.
FIELD_REQUIREMENT: dict[str, frozenset[RequirementCode]] = {
    # ── ¶1 · the fund's acquisition, on an executed purchase agreement ─────
    "agreement_date": frozenset({R1}),
    "company_signature": frozenset({R1}),
    "purchaser_signature": frozenset({R1}),
    "priced_security_class": frozenset({R1}),
    "fund_shares": frozenset({R1}),
    "fund_price_per_share": frozenset({R1}),
    "fund_aggregate_purchase_price": frozenset({R1}),
    "schedule_a_total_shares": frozenset({R1}),
    "schedule_a_total_purchase_price": frozenset({R1}),
    # The purchase closed on a stock purchase agreement; the ROUND closed on a
    # capitalisation table. Both, because one name carries both facts.
    "closing_date": frozenset({R1, R2}),
    # ── ¶1's third limb · settlement of funds ─────────────────────────────
    # "including share counts, price per share, and settlement of funds". Two
    # reviewers found independently that nothing visible answered the third
    # limb; these are what answers it.
    "settlement_amount_received": frozenset({R1}),
    "settlement_date": frozenset({R1}),
    "settlement_reference": frozenset({R1}),
    # ── ¶1 · the position as a term sheet or capitalisation table states it ─
    "securities": frozenset({R1}),
    "fund_commitment": frozenset({R1}),
    "fund_held_security_class": frozenset({R1}),
    "fund_entry_price_per_share": frozenset({R1}),
    "fund_series_a_security_class": frozenset({R1}),
    "fund_series_a_shares": frozenset({R1}),
    "fund_series_a_original_pps": frozenset({R1}),
    "fund_series_a2_security_class": frozenset({R1}),
    "fund_series_a2_shares": frozenset({R1}),
    "fund_series_a2_original_pps": frozenset({R1}),
    "security_class_held": frozenset({R1}),
    "shares_held": frozenset({R1}),
    "position_shares": frozenset({R1}),
    "original_purchase_pps": frozenset({R1}),
    "original_purchase_aggregate": frozenset({R1}),
    "acquisition_consideration_usd": frozenset({R1}),
    "eur_interest_at_acquisition": frozenset({R1}),
    # The document's own date. On a term sheet it is both the date the fund
    # committed and the date the price it states is as of.
    "term_sheet_date": frozenset({R1, R2}),
    # ── ¶1 · the recapitalised position, as the fund now holds it ──────────
    # What the fund holds AFTER the recap is existence; how the recap was
    # priced is fair value, and those are the entries below.
    "converted_into_class": frozenset({R1}),
    "fund_prior_security_class": frozenset({R1}),
    "fund_prior_shares": frozenset({R1}),
    "fund_a3_shares": frozenset({R1}),
    "fund_exchange_ratio": frozenset({R1}),
    "fund_new_money_participation": frozenset({R1}),
    # ── ¶1 · an indirect feeder interest, per the administrator ────────────
    # Jio has no stock purchase agreement to ask for. The capital account
    # statement is its existence evidence AND its settlement evidence:
    # contributed capital is money the partnership confirms it received.
    "investor_of_record": frozenset({R1}),
    "partnership": frozenset({R1}),
    "underlying_position": frozenset({R1}),
    "capital_commitment": frozenset({R1}),
    "contributed_capital": frozenset({R1}),
    "unfunded_commitment": frozenset({R1}),
    "distributions": frozenset({R1}),
    # The date the account is struck. It dates the position and it dates the
    # net asset value, so it answers both requests.
    "as_of_date": frozenset({R1, R2}),
    # ── ¶2 · what a share is worth, and what the round priced ─────────────
    "round_price_per_share": frozenset({R2}),
    "price_per_share": frozenset({R2}),
    "post_money_valuation": frozenset({R2}),
    "pre_money_valuation": frozenset({R2}),
    "fully_diluted_shares": frozenset({R2}),
    "amount_of_financing": frozenset({R2}),
    "amount_raised": frozenset({R2}),
    "close_statement": frozenset({R2}),
    "closing_date_stated": frozenset({R2}),
    "series_b_price_per_share": frozenset({R2}),
    "series_b_shares_issued": frozenset({R2}),
    "series_b_gross_proceeds": frozenset({R2}),
    "series_a2_price_per_share": frozenset({R2}),
    "series_a2_post_money_valuation": frozenset({R2}),
    "series_a2_closing_date": frozenset({R2}),
    "series_a3_price_per_share": frozenset({R2}),
    # ── ¶2 · the recapitalisation's own arithmetic ────────────────────────
    "prior_series_a_shares": frozenset({R2}),
    "prior_series_a_exchange_ratio": frozenset({R2}),
    "prior_series_seed_shares": frozenset({R2}),
    "prior_series_seed_exchange_ratio": frozenset({R2}),
    "series_a_a3_shares_issued": frozenset({R2}),
    "series_seed_a3_shares_issued": frozenset({R2}),
    "total_prior_conversion_shares": frozenset({R2}),
    "total_a3_conversion_shares_issued": frozenset({R2}),
    "new_money_shares": frozenset({R2}),
    "new_money_aggregate_capital": frozenset({R2}),
    "holder_approval_date": frozenset({R2}),
    # ── ¶2 · a third party's conclusion ───────────────────────────────────
    "concluded_fair_value_per_share": frozenset({R2}),
    "concluded_fair_value_usd": frozenset({R2}),
    "fund_holding_value": frozenset({R2}),
    "implied_change_vs_purchase": frozenset({R2}),
    "bridge_financing_amount": frozenset({R2}),
    "measurement_date": frozenset({R2}),
    "post_money_valuation_eur": frozenset({R2}),
    "eur_interest_last_round_basis": frozenset({R2}),
    # ── ¶2 · the administrator's and the market's figures ─────────────────
    "net_asset_value": frozenset({R2}),
    "valuation_basis": frozenset({R2}),
    "audit_status": frozenset({R2}),
    "closing_price": frozenset({R2}),
    "quote_date": frozenset({R2}),
    "position_value": frozenset({R2}),
    # ── ¶2 · currency remeasurement of a EUR-denominated interest ─────────
    "currency_pair": frozenset({R2}),
    "fx_rate": frozenset({R2}),
    "fx_rate_effective_date": frozenset({R2}),
    "fx_remeasurement_adjustment": frozenset({R2}),
    "prior_usd_carrying_value": frozenset({R2}),
    "usd_carrying_value": frozenset({R2}),
    "eur_interest_unchanged": frozenset({R2}),
    "remeasurement_scope": frozenset({R2}),
    # ── ¶2 · what the press does and does not stand behind ────────────────
    # These three are the reason Anthropic's R2 is `insufficient`, so they are
    # fair-value evidence in the only sense that matters here: they are what an
    # auditor reads to see that the figure is a rumour.
    "headline_valuation": frozenset({R2}),
    "valuation_attribution": frozenset({R2}),
    "independent_review": frozenset({R2}),
    "terms_disclosure": frozenset({R2}),
    "publication_date": frozenset({R2}),
    "email_date": frozenset({R2}),
    # ── ¶3 · is the support still representative at this date ─────────────
    # A memo that disclaims later dates, and a records note saying no round has
    # happened since, are what ¶3(b) asks management to assess. They also
    # qualify the fair-value support itself, which is why two carry R2 as well.
    "no_reliance_scope": frozenset({R2, R3}),
    "reliance_scope": frozenset({R2, R3}),
    "update_status": frozenset({R2, R3}),
    "basis_reference": frozenset({R2, R3}),
    "no_subsequent_round_of_record": frozenset({R3}),
    # ── ¶4 · what the exit paid ──────────────────────────────────────────
    "consideration_per_share": frozenset({R4}),
    "consideration_per_share_stated": frozenset({R4}),
    "gross_consideration": frozenset({R4}),
    "net_payment": frozenset({R4}),
    "shares_of_record": frozenset({R4}),
    "escrow_allocation": frozenset({R4}),
    "tax_withholding": frozenset({R4}),
    "payment_date": frozenset({R4}),
    "merger_agreement_date": frozenset({R4}),
    "security": frozenset({R4}),
    # A recapitalisation's effective date and a merger's. Both, for the reason
    # `closing_date` carries both.
    "effective_date": frozenset({R2, R4}),
    # ── closing paragraph · positions marked pending executed documentation ─
    "executed_docs_pending": frozenset({R5}),
    "executed_docs_location": frozenset({R5}),
    "attachment_status": frozenset({R5}),
    "closing_set_status": frozenset({R5}),
    "anticipated_closing": frozenset({R5}),
    # These three state the pending status AND qualify the price beside them,
    # which is what caps a pro-forma table at `partial` rather than excluding
    # it. Both requests, because both are answered by the same sentence.
    "series_a2_executed_documents": frozenset({R2, R5}),
    "series_b_subscription_agreement": frozenset({R2, R5}),
    "binding_status": frozenset({R2, R5}),
    # ── Answers no request, deliberately ─────────────────────────────────
    # Authority is a property of the CLAIM (INV-15) and the trail already shows
    # it there. Repeating "Meridian Fund Services" as a figure under existence
    # would count one piece of evidence twice — the same reason `reliance.py`
    # relies on the capital account statement and not on the email carrying it.
    "administrator": _NOTHING,
    "preparer": _NOTHING,
    "engagement_reference": _NOTHING,
    "term_sheet_provenance": _NOTHING,
    # How often a document is issued or delivered is a fact about the filing
    # cadence, not about the position or its value.
    "issuance_cadence": _NOTHING,
    "delivery_cadence": _NOTHING,
    # The delivery email is an attribute of the statement it transmits, and
    # `reliance.py` relies on it for nothing for exactly that reason. Its own
    # figures describe the transmission.
    "attachment": _NOTHING,
    "delivery_date": _NOTHING,
    "prior_period_availability": _NOTHING,
    "statement_as_of_date": _NOTHING,
}


#: Which figure most directly ANSWERS each request, most direct first.
#:
#: `FIELD_REQUIREMENT` says whether a figure is relevant; this says which of the
#: relevant ones an auditor should be shown first. They are different
#: judgements: Fluidstack's Series A agreement answers existence and cost with
#: ten figures, and only one of them is the answer to "what did the fund pay" —
#: the other nine qualify it. Opening on whichever the extractor happened to
#: emit first is not a judgement at all, and it is what made the pane land on
#: `agreement_date` when the question was about money.
#:
#: A field absent from its requirement's tuple ranks after every field present
#: in it, in the order the documents state them. So this is a declared FRONT of
#: the list rather than a total ordering of 134 fields — the tail is arrival
#: order, which is the document's own order and is the right default for figures
#: nobody has ranked.
#:
#: Ordered by what the request asks, not by what is easiest to read:
#:
#: * **R1** asks what the fund bought and whether the money moved, so the
#:   aggregate purchase price leads and the signatures come last.
#: * **R2** asks what the position is worth. A CONCLUDED value answers that
#:   outright, so third-party and administrator figures precede per-share
#:   prices; among prices, the later round precedes the original purchase,
#:   because ¶2 asks for support AS OF the measurement date.
#: * **R3** asks whether an unchanged mark is still representative, so the
#:   figures about the AGE and SCOPE of the support lead.
#: * **R4** asks what the exit paid. **R5** asks which marks are pro forma
#:   pending executed documentation.
LEAD_FIELDS: dict[RequirementCode, tuple[str, ...]] = {
    R1: (
        "fund_aggregate_purchase_price",
        "fund_shares",
        "fund_price_per_share",
        "contributed_capital",
        "settlement_amount_received",
        "fund_commitment",
        "original_purchase_aggregate",
        "shares_held",
        "position_shares",
        "fund_a3_shares",
        "fund_series_a_shares",
        "fund_series_a2_shares",
        "priced_security_class",
        "securities",
        "fund_held_security_class",
        "investor_of_record",
        "agreement_date",
    ),
    R2: (
        "concluded_fair_value_usd",
        "fund_holding_value",
        "concluded_fair_value_per_share",
        "net_asset_value",
        "usd_carrying_value",
        "position_value",
        "closing_price",
        "series_b_price_per_share",
        "series_a3_price_per_share",
        "series_a2_price_per_share",
        "round_price_per_share",
        "price_per_share",
        "headline_valuation",
        "post_money_valuation",
    ),
    R3: (
        "no_subsequent_round_of_record",
        "update_status",
        "no_reliance_scope",
        "reliance_scope",
        "basis_reference",
    ),
    R4: (
        "gross_consideration",
        "net_payment",
        "consideration_per_share",
        "shares_of_record",
        "escrow_allocation",
        "tax_withholding",
        "payment_date",
    ),
    R5: (
        "executed_docs_pending",
        "closing_set_status",
        "executed_docs_location",
        "series_a2_executed_documents",
        "attachment_status",
        "binding_status",
        "anticipated_closing",
    ),
}


class UndeclaredField(Exception):
    """A figure was extracted whose relevance to the client's requests is undecided."""


class UnrankableField(Exception):
    """A lead ordering names a figure that does not answer the request it leads."""


def answer_rank(field_name: str, requirement: RequirementCode) -> int:
    """How directly this figure answers this request. Lower leads.

    Every unranked field gets the SAME rank — one past the declared front —
    rather than an ordering invented from its name or its position in the file.
    Ties are then broken by the order the documents state the figures in, which
    is a fact about the source rather than a preference of this table.
    """
    lead = LEAD_FIELDS[requirement]
    return lead.index(field_name) if field_name in lead else len(lead)


def check_lead_fields() -> None:
    """A lead ordering may only name figures that answer the request it leads.

    Fail closed, and in the direction that actually bites: a typo, or a field
    whose requirement set is later narrowed, leaves a name here that can never
    match — and the pane would go on opening on whatever came first, silently,
    which is the state this table exists to end.
    """
    for requirement, fields in LEAD_FIELDS.items():
        for field_name in fields:
            declared = FIELD_REQUIREMENT.get(field_name)
            if declared is None:
                raise UnrankableField(
                    f"LEAD_FIELDS[{requirement.value}] names {field_name!r}, which "
                    f"FIELD_REQUIREMENT does not declare at all."
                )
            if requirement not in declared:
                raise UnrankableField(
                    f"LEAD_FIELDS[{requirement.value}] leads with {field_name!r}, which is "
                    f"declared as answering {sorted(c.value for c in declared) or 'nothing'}. "
                    f"A figure cannot lead a request it does not answer."
                )
        if len(set(fields)) != len(fields):
            raise UnrankableField(f"LEAD_FIELDS[{requirement.value}] names a field twice.")


check_lead_fields()


def requirements_for(field_name: str) -> frozenset[RequirementCode]:
    """Which requests this figure answers, or a refusal naming the undecided field.

    No default. An unknown field name is a judgement nobody made, and both
    available defaults are wrong in a way nothing would report: "all" files a
    settlement confirmation under fair value, and "none" deletes a figure from
    every request that asks for it.
    """
    declared = FIELD_REQUIREMENT.get(field_name)
    if declared is None:
        raise UndeclaredField(
            f"{field_name!r} is extracted but ingest/documents/field_requirements.py "
            f"does not say which of the client's requests it answers. Decide it there — "
            f"a figure relevant to none of them is a declared frozenset()."
        )
    return declared
