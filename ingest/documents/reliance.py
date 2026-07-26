"""Which requirement each claim is relied upon for. A reviewed judgement.

Not derivable from `source_class`, and the corpus contains all three
counterexamples:

* Jackpocket's merger notice and Poolside's stock purchase agreement are both
  `executed_transaction_doc`. The SPA evidences existence, cost AND fair value;
  the merger notice evidences the EXIT and neither of the other two, because by
  the measurement date the position is gone.
* Fluidstack's Series A-2 reference is a real claim, correctly classified,
  relied upon for nothing. The cap table mentions the tranche closed at $15.00
  and says the executed documents are with counsel — so it is the *gap* that
  carries weight, not the reference.
* Roofstock's and Poolside's records notes ("no subsequent financing rounds
  have been documented for this company as of the Fund's most recent records")
  are `fund_internal_record` and answer no PBC requirement directly. They bind
  through `valuation_component_support` instead, where they do the work the
  audit letter's ¶3 actually asks for: establishing that the last round is
  still the most recent one.

Absence from this table is therefore meaningful and is not an omission. Every
claim in the ledger is listed below, including the seven relied upon for
nothing, so a claim that is simply forgotten shows up as a claim this file does
not mention — which `seed_claim_requirements` refuses.
"""

from __future__ import annotations

from packages.contracts.enums import RequirementCode

R1 = RequirementCode.R1
R2 = RequirementCode.R2
R4 = RequirementCode.R4

#: claim id -> the requirements that claim is relied upon for.
RELIANCE: dict[str, frozenset[RequirementCode]] = {
    # Executed transaction documents for positions still held: existence and
    # cost, and — because the mark is the last round — fair value too.
    "fund_ii_poolside:series_b_price": frozenset({R1, R2}),
    "fund_i_roofstock:series_e_price": frozenset({R1, R2}),
    "fund_ii_fluidstack:series_a_price": frozenset({R1, R2}),
    # The realisation. Not R1: at 12/31/2024 the position is not held, and
    # existence-and-cost of something no longer held is not what ¶4 asks.
    "fund_ii_jackpocket:merger_consideration": frozenset({R4}),
    # Administrator statements. The owner determination recorded in the matrix
    # is that these stand in for existence and cost on a feeder interest, where
    # no stock purchase agreement exists to ask for.
    "fund_i_jio_indirect:fy2023_capital_account": frozenset({R1, R2}),
    "fund_i_jio_indirect:fy2024_capital_account": frozenset({R1, R2}),
    "fund_i_jio_indirect:fy2025_capital_account": frozenset({R1, R2}),
    # Term sheets. Non-binding, so `insufficient` for both — but relied upon,
    # because the mark is carried at the price they state and the packet must
    # show what the figure rests on.
    "fund_ii_lucra:series_a1_price": frozenset({R1, R2}),
    "fund_i_the_mom_project:series_c_term_sheet": frozenset({R1, R2}),
    # Fair value only.
    "fund_ii_fluidstack:series_b_pro_forma": frozenset({R2}),
    "fund_ii_dream:series_b_pro_forma": frozenset({R2}),
    "fund_ii_dream:series_b_closing_notice": frozenset({R2}),
    "fund_ii_sway:series_a3_recap_pro_forma": frozenset({R2}),
    "fund_ii_lucra:series_a2_price": frozenset({R2}),
    "fund_ii_anthropic:round_rumour": frozenset({R2}),
    "fund_ii_moonfare:fy2023_third_party_valuation": frozenset({R2}),
    "fund_ii_moonfare:fy2024_fx_remeasurement": frozenset({R2}),
    "fund_i_capsule:fy2022_third_party_valuation": frozenset({R2}),
    "fund_i_banzai:fy2023_close": frozenset({R2}),
    "fund_i_banzai:fy2024_close": frozenset({R2}),
    "fund_i_banzai:fy2025_close": frozenset({R2}),
    # ── Relied upon for nothing, deliberately ────────────────────────────
    # The closing set is with counsel; the reference is not the evidence, the
    # gap is. Linking it to R2 would put a $15.00 price into fair-value support
    # on the strength of a sentence saying the documents are elsewhere.
    "fund_ii_fluidstack:series_a2_referenced_execution": frozenset(),
    # Settlement confirmations. They evidence that funds moved, which the SPA
    # they accompany already covers, and they price nothing.
    "fund_ii_poolside:series_b_settlement": frozenset(),
    "fund_i_roofstock:series_e_settlement": frozenset(),
    "fund_ii_fluidstack:series_a_settlement": frozenset(),
    # The records notes. They bind through `valuation_component_support`.
    "fund_ii_poolside:series_b_fund_records": frozenset(),
    "fund_i_roofstock:series_e_fund_records": frozenset(),
    # The delivery email is an attribute of the statement it transmits, and the
    # statement carries its own `received_date`. Relying on both would count one
    # piece of evidence twice.
    "fund_i_jio_indirect:fy2025_statement_delivery": frozenset(),
}
