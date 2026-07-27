"""The corpus manifest's names against the extractors' names.

The manifest calls a figure `fluidstack.series_a.fund_price_per_share` and reads
it out of a document it calls `fluidstack_series_a_spa`; the extractors call the
same figure `round_price_per_share` on a claim called `series_a_price`. Neither
vocabulary is wrong and neither was written from the other — the manifest was
transcribed from the PDFs by someone who deliberately did not read
`ingest/documents/`, which is the entire reason it is worth comparing against.

The mapping lives HERE, in the tests, for the reason `tests/oracle_map.py` gives
about the oracle: it is a fact about comparing two independent readings of one
corpus, not a fact about the product. Putting it in `ingest/` or `policy/` would
give the implementation a table keyed by the answer key's vocabulary, and the
step after that is importing the answer key.

Three things this file records, each of which is a judgement a person made:

* `FIELD` — which extracted figure each manifest fact is about. Keyed on the
  manifest's `id` because no natural key is unique: `(holding_id, source, field,
  security_class, as_of)` still collides on Fluidstack's two
  `post_money_valuation` facts, one for the Series A-2 tranche and one for the
  Series B round, both read out of the same pro forma table.
* `UNMATCHED` — the three manifest facts that bind to nothing today, with the
  reason for each. `join.mapping_is_not_renaming` in the manifest asks for
  exactly this: "a manifest field with NO counterpart is a FINDING, not a
  chore." All three are now of one kind: the system cites the right document and
  a weaker passage inside it. The six that were figures no extractor read at all
  — four of them the corpus's only evidence of what the fund paid for Jackpocket
  and Banzai — are bound below, which is what closed that finding.
* `DOCUMENT_GAP_ABSENCES` — the absence entries that name a missing DOCUMENT
  rather than a missing figure, and so cannot be checked against
  `extracted_fact` at all.

A `claim_key` of `None` in `FIELD` means "every claim this document produces",
not "any one of them". Banzai's saved quote record states the position size once
and the extractor cites it onto all three year-end claims, so the obligation is
that every one of them agrees with the manifest — not that one of them does.
"""

from __future__ import annotations

#: The manifest composes `{fund}_{holding}` from the display name; the ledger
#: slugs three holdings differently. `join.holding_id` predicted exactly this
#: and named the three to watch — The Mom Project, Jio (Indirect) and Banzai
#: (Public). Two of the three needed an entry; `fund_i_banzai` matched already.
HOLDING: dict[str, str] = {
    "fund_i_mom_project": "fund_i_the_mom_project",
    "fund_i_jio": "fund_i_jio_indirect",
}

#: manifest fact id -> (claim_key, extracted field_name). `None` for the claim
#: key means every claim the document produces.
FIELD: dict[str, tuple[str | None, str]] = {
    # ── Fluidstack ────────────────────────────────────────────────────
    # The manifest cites Section 1.1 for what the fund paid, and in an executed
    # purchase agreement the fund pays the round's stated price — so the
    # counterpart of `fund_price_per_share` is the figure the extractor reads
    # out of that same sentence. The Schedule A row states it a second time and
    # is left unbound rather than mapped onto the same manifest fact twice.
    "fluidstack.series_a.fund_price_per_share": ("series_a_price", "round_price_per_share"),
    "fluidstack.series_a.fund_shares": ("series_a_price", "fund_shares"),
    "fluidstack.series_a.fund_aggregate_purchase_price": (
        "series_a_price",
        "fund_aggregate_purchase_price",
    ),
    "fluidstack.series_a.agreement_date": ("series_a_price", "agreement_date"),
    "fluidstack.series_a.settlement_amount": ("series_a_settlement", "settlement_amount_received"),
    "fluidstack.series_a.settlement_date": ("series_a_settlement", "settlement_date"),
    "fluidstack.series_a.settlement_reference": ("series_a_settlement", "settlement_reference"),
    "fluidstack.series_a.post_money_valuation": ("series_a_price", "post_money_valuation"),
    "fluidstack.series_a2.fund_shares": ("series_b_pro_forma", "fund_series_a2_shares"),
    # Note (a) of the Series B table, which the manifest calls "the better
    # citation than the Section 4 row: it says what the $15.00 IS". The
    # extractor agrees, and files all three of note (a)'s figures onto their own
    # claim because the tranche it describes was executed elsewhere — INV-15.
    "fluidstack.series_a2.original_issue_price": (
        "series_a2_referenced_execution",
        "series_a2_price_per_share",
    ),
    "fluidstack.series_a2.round_close_date": (
        "series_a2_referenced_execution",
        "series_a2_closing_date",
    ),
    "fluidstack.series_a2.post_money_valuation": (
        "series_a2_referenced_execution",
        "series_a2_post_money_valuation",
    ),
    "fluidstack.series_b.round_price_per_share": ("series_b_pro_forma", "series_b_price_per_share"),
    "fluidstack.series_b.post_money_valuation": ("series_b_pro_forma", "post_money_valuation"),
    "fluidstack.series_b.fully_diluted_shares": ("series_b_pro_forma", "fully_diluted_shares"),
    # ── Poolside ──────────────────────────────────────────────────────
    "poolside.series_b.fund_price_per_share": ("series_b_price", "round_price_per_share"),
    "poolside.series_b.fund_shares": ("series_b_price", "fund_shares"),
    "poolside.series_b.fund_aggregate_purchase_price": (
        "series_b_price",
        "fund_aggregate_purchase_price",
    ),
    "poolside.series_b.post_money_valuation": ("series_b_price", "post_money_valuation"),
    "poolside.series_b.fully_diluted_shares": ("series_b_price", "fully_diluted_shares"),
    "poolside.series_b.agreement_date": ("series_b_price", "agreement_date"),
    "poolside.series_b.settlement_amount": ("series_b_settlement", "settlement_amount_received"),
    "poolside.series_b.settlement_date": ("series_b_settlement", "settlement_date"),
    "poolside.series_b.settlement_reference": ("series_b_settlement", "settlement_reference"),
    # ── Roofstock ─────────────────────────────────────────────────────
    "roofstock.series_e.fund_price_per_share": ("series_e_price", "round_price_per_share"),
    "roofstock.series_e.fund_shares": ("series_e_price", "fund_shares"),
    "roofstock.series_e.fund_aggregate_purchase_price": (
        "series_e_price",
        "fund_aggregate_purchase_price",
    ),
    "roofstock.series_e.post_money_valuation": ("series_e_price", "post_money_valuation"),
    "roofstock.series_e.fully_diluted_shares": ("series_e_price", "fully_diluted_shares"),
    "roofstock.series_e.agreement_date": ("series_e_price", "agreement_date"),
    "roofstock.series_e.settlement_amount": ("series_e_settlement", "settlement_amount_received"),
    "roofstock.series_e.settlement_date": ("series_e_settlement", "settlement_date"),
    "roofstock.series_e.settlement_reference": ("series_e_settlement", "settlement_reference"),
    # ── Dream ─────────────────────────────────────────────────────────
    "dream.series_a1.fund_shares": ("series_b_pro_forma", "fund_shares"),
    "dream.series_a1.original_issue_price": ("series_b_pro_forma", "fund_entry_price_per_share"),
    "dream.series_b.round_price_per_share": ("series_b_pro_forma", "series_b_price_per_share"),
    "dream.series_b.post_money_valuation": ("series_b_pro_forma", "post_money_valuation"),
    "dream.series_b.fully_diluted_shares": ("series_b_pro_forma", "fully_diluted_shares"),
    # ── Lucra ─────────────────────────────────────────────────────────
    "lucra.series_a1.fund_price_per_share": ("series_a1_price", "price_per_share"),
    "lucra.series_a1.fund_aggregate_purchase_price": ("series_a1_price", "fund_commitment"),
    "lucra.series_a1.post_money_valuation": ("series_a1_price", "post_money_valuation"),
    "lucra.series_a1.pre_money_valuation": ("series_a1_price", "pre_money_valuation"),
    "lucra.series_a1.term_sheet_date": ("series_a1_price", "term_sheet_date"),
    "lucra.series_a2.round_price_per_share": ("series_a2_price", "price_per_share"),
    "lucra.series_a2.post_money_valuation": ("series_a2_price", "post_money_valuation"),
    # ── Sway ──────────────────────────────────────────────────────────
    "sway.series_a3.fund_shares": ("series_a3_recap_pro_forma", "fund_a3_shares"),
    "sway.series_a3.prior_shares": ("series_a3_recap_pro_forma", "fund_prior_shares"),
    # Section 3's ratio row, which is where the manifest's `passage_locator`
    # points. The fund's own row in Section 4 restates it and the manifest
    # records that under `also_stated_in`.
    "sway.series_a3.exchange_ratio": (
        "series_a3_recap_pro_forma",
        "prior_series_a_exchange_ratio",
    ),
    "sway.series_a3.round_price_per_share": (
        "series_a3_recap_pro_forma",
        "series_a3_price_per_share",
    ),
    "sway.series_a3.post_money_valuation": ("series_a3_recap_pro_forma", "post_money_valuation"),
    "sway.series_a3.fully_diluted_shares": ("series_a3_recap_pro_forma", "fully_diluted_shares"),
    # The recapitalisation closed on the 30th and was approved on the 26th, in
    # one sentence. `effective_date` reads the header; the manifest's window is
    # the sentence, so the counterpart is the figure read out of it.
    "sway.series_a3.recapitalization_date": ("series_a3_recap_pro_forma", "closing_date"),
    "sway.series_a3.non_participation": (
        "series_a3_recap_pro_forma",
        "fund_new_money_participation",
    ),
    # ── Jackpocket ────────────────────────────────────────────────────
    "jackpocket.merger.consideration_per_share": (
        "merger_consideration",
        "consideration_per_share",
    ),
    "jackpocket.merger.shares_of_record": ("merger_consideration", "shares_of_record"),
    "jackpocket.merger.gross_consideration": ("merger_consideration", "gross_consideration"),
    "jackpocket.merger.escrow_holdback": ("merger_consideration", "escrow_allocation"),
    "jackpocket.merger.tax_withholding": ("merger_consideration", "tax_withholding"),
    "jackpocket.merger.net_payment": ("merger_consideration", "net_payment"),
    "jackpocket.merger.effective_date": ("merger_consideration", "effective_date"),
    "jackpocket.merger.payment_date": ("merger_consideration", "payment_date"),
    # The manifest files the transmittal reference under `settlement_reference`,
    # which on the three purchase agreements means money IN — ¶1's third limb.
    # Here it is the reference the exit proceeds were paid against, so the
    # extractor gives it its own name and the map records the correspondence.
    "jackpocket.merger.payment_reference": ("merger_consideration", "payment_reference"),
    # ¶1 evidence inside a ¶4 document: the paying agent's recital of the
    # company's stock ledger, and the only statement in the corpus of what 7GC
    # paid for Jackpocket. Binding it does not make the notice an acquisition
    # document — `document_gap` still records that the 2021 SPA is not located.
    "jackpocket.entry.acquisition_date": ("merger_consideration", "acquisition_date"),
    "jackpocket.entry.fund_price_per_share": ("merger_consideration", "original_purchase_pps"),
    "jackpocket.entry.fund_aggregate_purchase_price": (
        "merger_consideration",
        "original_purchase_aggregate",
    ),
    # ── Moonfare ──────────────────────────────────────────────────────
    "moonfare.fy2023.concluded_fair_value_usd": (
        "fy2023_third_party_valuation",
        "concluded_fair_value_usd",
    ),
    "moonfare.fy2023.foreign_currency_interest": (
        "fy2023_third_party_valuation",
        "eur_interest_last_round_basis",
    ),
    "moonfare.fy2023.fx_rate": ("fy2023_third_party_valuation", "fx_rate"),
    "moonfare.round.post_money_valuation": (
        "fy2023_third_party_valuation",
        "post_money_valuation_eur",
    ),
    "moonfare.entry.fund_aggregate_purchase_price": (
        "fy2023_third_party_valuation",
        "acquisition_consideration_usd",
    ),
    "moonfare.fy2024.carried_amount": ("fy2024_fx_remeasurement", "usd_carrying_value"),
    "moonfare.fy2024.fx_rate": ("fy2024_fx_remeasurement", "fx_rate"),
    "moonfare.fy2024.foreign_currency_interest": (
        "fy2024_fx_remeasurement",
        "eur_interest_unchanged",
    ),
    "moonfare.fy2024.fx_adjustment": ("fy2024_fx_remeasurement", "fx_remeasurement_adjustment"),
    # ── Capsule ───────────────────────────────────────────────────────
    "capsule.fy2022.concluded_fair_value_per_share": (
        "fy2022_third_party_valuation",
        "concluded_fair_value_per_share",
    ),
    "capsule.fy2022.concluded_fair_value_usd": (
        "fy2022_third_party_valuation",
        "fund_holding_value",
    ),
    "capsule.fund_shares": ("fy2022_third_party_valuation", "shares_held"),
    "capsule.entry.fund_price_per_share": ("fy2022_third_party_valuation", "original_purchase_pps"),
    "capsule.entry.fund_aggregate_purchase_price": (
        "fy2022_third_party_valuation",
        "original_purchase_aggregate",
    ),
    # ── The Mom Project ───────────────────────────────────────────────
    "mom_project.series_c.fund_price_per_share": ("series_c_term_sheet", "price_per_share"),
    "mom_project.series_c.fund_shares": ("series_c_term_sheet", "fund_shares"),
    "mom_project.series_c.fund_aggregate_purchase_price": (
        "series_c_term_sheet",
        "fund_commitment",
    ),
    "mom_project.series_c.post_money_valuation": ("series_c_term_sheet", "post_money_valuation"),
    "mom_project.series_c.pre_money_valuation": ("series_c_term_sheet", "pre_money_valuation"),
    "mom_project.series_c.term_sheet_date": ("series_c_term_sheet", "term_sheet_date"),
    # ── Jio ───────────────────────────────────────────────────────────
    "jio.fy2023.net_asset_value": ("fy2023_capital_account", "net_asset_value"),
    "jio.fy2024.net_asset_value": ("fy2024_capital_account", "net_asset_value"),
    "jio.fy2025.net_asset_value": ("fy2025_capital_account", "net_asset_value"),
    "jio.fy2025.capital_commitment": ("fy2025_capital_account", "capital_commitment"),
    "jio.fy2025.distributions_to_date": ("fy2025_capital_account", "distributions"),
    "jio.delivery_date": ("fy2025_statement_delivery", "delivery_date"),
    "jio.attachment_relation": ("fy2025_statement_delivery", "attachment"),
    # ── Banzai ────────────────────────────────────────────────────────
    # One statement of the position, cited onto all three year-end claims.
    "banzai.fund_shares": (None, "position_shares"),
    "banzai.fy2023.quoted_closing_price": ("fy2023_close", "closing_price"),
    "banzai.fy2023.position_value": ("fy2023_close", "position_value"),
    "banzai.fy2024.quoted_closing_price": ("fy2024_close", "closing_price"),
    "banzai.fy2024.position_value": ("fy2024_close", "position_value"),
    "banzai.fy2025.quoted_closing_price": ("fy2025_close", "closing_price"),
    "banzai.fy2025.position_value": ("fy2025_close", "position_value"),
    # The basis note states the March 2021 entry once, for the position rather
    # than for a year, so it is cited onto all three claims — the same shape as
    # `banzai.fund_shares` above, and the same `None` for the claim key.
    "banzai.entry.fund_price_per_share": (None, "original_purchase_pps"),
    "banzai.entry.fund_aggregate_purchase_price": (None, "original_purchase_aggregate"),
}

#: The manifest facts nothing in `FIELD` accounts for, and why. Every entry here
#: is a question for a person, not a chore, and all three are now one question:
#: the system cites the right document and a weaker passage inside it. None of
#: them is a figure nothing reads — that category was emptied when Jackpocket's
#: and Banzai's entry cost was extracted, and an entry rejoining it would be a
#: figure the packet has stopped being able to state.
UNMATCHED: dict[str, str] = {
    "anthropic.press.reported_valuation": (
        "The extractor cites the headline; the manifest's window is the lead paragraph. "
        "Both state $120 billion and only the paragraph carries the hedges — "
        "'approximately', 'according to three people familiar with the matter', 'Terms "
        "have not been publicly disclosed' — that are the whole reason this figure may "
        "not support a mark. The headline is a correct citation to a passage stripped "
        "of the caveats an auditor following it needs to see."
    ),
    "fluidstack.series_a.priced_security_class": (
        "The extractor cites the document's title line; the manifest's window is the "
        "Section 1 heading, 'Purchase and Sale of Series A Preferred Shares'. Both name "
        "the class and both are in the same agreement. The title is the weaker of the "
        "two because a title states what a document is about, and the heading states "
        "what the operative section sells."
    ),
    "dream.series_b.closing_date": (
        "The extractor cites the table's own 'Closing Date' header; the manifest's "
        "window is note (d), which says the table is prepared in connection with an "
        "EXECUTED purchase agreement dated 14 November 2025. That agreement is not in "
        "the corpus. The header states a date; the note states whose date it is, and "
        "only the note tells a reader that the executed instrument is missing."
    ),
}

#: Absence entries whose `field` names a missing DOCUMENT rather than a missing
#: figure. `extracted_fact` has no row shaped like "the executed Series A-1
#: purchase agreement", so asserting its absence there proves nothing: the query
#: returns empty whether the document is missing or the check is broken. These
#: belong against `document_gap`, which is populated from the trackers, and are
#: deliberately silent here rather than counted as coverage.
DOCUMENT_GAP_ABSENCES: frozenset[str] = frozenset(
    {"executed_entry_documents", "executed_a2_documents"}
)
