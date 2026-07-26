"""The oracle's short names against the ledger's qualified ids.

The oracle calls a holding `dream` and a document `dream_b_cap`; the ledger
calls them `fund_ii_dream` and `fund_ii_dream:series_b_pro_forma`, because a
company can be held by both funds and a document can carry several claims.

The mapping lives HERE, in the tests, and nowhere in `policy/` or `api/`. It is
a fact about comparing two independent representations of one corpus, not a fact
about the product — and putting it in the product would give the implementation
a table keyed by the answer key's own vocabulary, which is one short step from
importing the answer key.
"""

from __future__ import annotations

HOLDING: dict[str, str] = {
    "because_market": "fund_ii_because_market",
    "moonfare": "fund_ii_moonfare",
    "sway": "fund_ii_sway",
    "anthropic": "fund_ii_anthropic",
    "lucra": "fund_ii_lucra",
    "poolside": "fund_ii_poolside",
    "fluidstack": "fund_ii_fluidstack",
    "dream": "fund_ii_dream",
    "jackpocket": "fund_ii_jackpocket",
    "capsule": "fund_i_capsule",
    "mom_project": "fund_i_the_mom_project",
    "roofstock": "fund_i_roofstock",
    "jio": "fund_i_jio_indirect",
    "banzai": "fund_i_banzai",
}

CLAIM: dict[str, str] = {
    "poolside_spa": "fund_ii_poolside:series_b_price",
    "roofstock_spa": "fund_i_roofstock:series_e_price",
    "fluidstack_a_spa": "fund_ii_fluidstack:series_a_price",
    "fluidstack_b_cap": "fund_ii_fluidstack:series_b_pro_forma",
    "fluidstack_a2_ref": "fund_ii_fluidstack:series_a2_referenced_execution",
    "dream_b_cap": "fund_ii_dream:series_b_pro_forma",
    "dream_close_email": "fund_ii_dream:series_b_closing_notice",
    "sway_recap_cap": "fund_ii_sway:series_a3_recap_pro_forma",
    "lucra_term_sheet": "fund_ii_lucra:series_a1_price",
    "lucra_ceo_email": "fund_ii_lucra:series_a2_price",
    "anthropic_press": "fund_ii_anthropic:round_rumour",
    "moonfare_memo_23": "fund_ii_moonfare:fy2023_third_party_valuation",
    "moonfare_fx_24": "fund_ii_moonfare:fy2024_fx_remeasurement",
    "capsule_memo_22": "fund_i_capsule:fy2022_third_party_valuation",
    "mom_c_term_sheet": "fund_i_the_mom_project:series_c_term_sheet",
    "jackpocket_merger": "fund_ii_jackpocket:merger_consideration",
    "jio_stmt_23": "fund_i_jio_indirect:fy2023_capital_account",
    "jio_stmt_24": "fund_i_jio_indirect:fy2024_capital_account",
    "jio_stmt_25": "fund_i_jio_indirect:fy2025_capital_account",
    "jio_delivery_email": "fund_i_jio_indirect:fy2025_statement_delivery",
    "banzai_quote_23": "fund_i_banzai:fy2023_close",
    "banzai_quote_24": "fund_i_banzai:fy2024_close",
    "banzai_quote_25": "fund_i_banzai:fy2025_close",
}

LOT: dict[str, str] = {
    "bm_1": "fund_ii_because_market_1",
    "mf_1": "fund_ii_moonfare_1",
    "sway_1": "fund_ii_sway_1",
    "anth_1": "fund_ii_anthropic_1",
    "lucra_1": "fund_ii_lucra_1",
    "pool_1": "fund_ii_poolside_1",
    "fluid_1": "fund_ii_fluidstack_1",
    "fluid_2": "fund_ii_fluidstack_2",
    "dream_1": "fund_ii_dream_1",
    "jack_1": "fund_ii_jackpocket_1",
    "caps_1": "fund_i_capsule_1",
    "mom_1": "fund_i_the_mom_project_1",
    "mom_2": "fund_i_the_mom_project_2",
    "mom_3": "fund_i_the_mom_project_3",
    "roof_1": "fund_i_roofstock_1",
    "jio_1": "fund_i_jio_indirect_1",
    "banz_1": "fund_i_banzai_1",
}
