import type {
  Approval,
  DerivedFigure,
  EvidenceCitation,
  GapObservation,
  HoldingRow,
  RequirementAssessment,
} from "./contracts";
import { FIXTURE_MARK, FIXTURE_PACKET, FIXTURE_ROW } from "./fixture";
import type { EvidenceClaim, HoldingResponse, PacketResponse } from "./responses";

/**
 * Variants of the captured fixture, for the states the Dream slice does not
 * happen to contain: an approved mark, a derived mark with computation lineage,
 * evidence dated after the measurement date, the two gap kinds that are not
 * `not_located`, and a holding whose claims resolve to quoted passages.
 *
 * They are built by spreading the captured row rather than typed out again, so
 * a change to the wire shape reaches them through the same file it reaches the
 * application through.
 *
 * Every computed field below — `supported`, `unsupported_reasons`, `approved`
 * and the totals' `contains_unsupported_inputs` / `unheld_gap_positions` — was
 * read out of `api/serialize.py` for the equivalent Python row rather than
 * decided here. A hand-picked value would agree with whatever the screen did
 * with it, which is the reason `fixture.ts` is captured too.
 */

/** Everything an assessment carries besides its requirement and verdict. */
const BASE_ASSESSMENT: RequirementAssessment = {
  requirement: "R1",
  verdict: "sufficient",
  reason_codes: [],
  next_actions: [],
  evidence: [],
  pro_forma: false,
  tracker_label: null,
  policy_version: "v1",
  applicable: true,
};

export const APPROVAL: Approval = {
  id: 9,
  decision_type: "valuation",
  status: "approved",
  mark_id: 1,
  packet_id: null,
  policy_version: "v1",
  evidence_assessment_ids: [4, 5],
  actor_id: "reviewer_a",
  decided_at: "2026-01-14T09:30:00Z",
};

export const TRANSCRIPTION_APPROVAL: Approval = {
  ...APPROVAL,
  id: 10,
  decision_type: "transcription",
  status: "draft",
};

export const SUBSEQUENT_EVIDENCE: EvidenceCitation = {
  claim: {
    id: "banzai_quote",
    document_version_id: "dv_banzai_quote",
    holding_id: "banzai",
    claim_key: "banzai/close",
    source_class: "public_market_quote",
    execution_status: "not_applicable",
    issued_date: "2026-01-04",
    as_of_date: "2025-12-29",
    received_date: "2026-01-05",
    applicable_from: "2025-12-29",
    applicable_to: "2026-03-31",
    priced_class: "common",
    price_per_share: "1.234500",
    stated: { amount: "1234567.8900", currency: "USD" },
    supersedes_claim_id: "banzai_quote_prior",
  },
  is_subsequent: true,
};

export const LINEAGE: DerivedFigure = {
  id: 1,
  label: "shares × PPS",
  operator: "multiply",
  value: { amount: "5000000", currency: "USD" },
  inputs: [
    {
      ordinal: 1,
      fact: {
        id: 11,
        claim_id: "dream_b_cap",
        field_name: "price_per_share",
        value_text: "$8.00",
        value_numeric: "8.000000",
        state: "canonical",
        citation: {
          document_version_id: "dv_dream_b_captable",
          quote: "Series B price per share: $8.00",
          span_start: 120,
          span_end: 152,
        },
      },
      child: null,
    },
    {
      ordinal: 2,
      fact: null,
      child: {
        id: 2,
        label: "share count",
        operator: "sum",
        value: { amount: "625000", currency: "USD" },
        inputs: [],
      },
    },
  ],
};

export const CALIBRATION: RequirementAssessment = {
  requirement: "R3",
  verdict: "insufficient",
  reason_codes: ["STALE_SUPPORT"],
  next_actions: ["DRAFT_MANAGEMENT_ASSESSMENT"],
  evidence: [SUBSEQUENT_EVIDENCE],
  pro_forma: false,
  tracker_label: "unchanged since FY2024",
  policy_version: "v1",
  applicable: true,
};

export const COUNSEL_GAP: GapObservation = {
  id: 2,
  holding_id: "sway",
  requirement: "R1",
  security_class: null,
  missing_document: "Series A purchase agreement",
  kind: "with_counsel",
  source_quote: "held by outside counsel pending closing",
  remediation: "requested",
};

export const UNSPECIFIED_GAP: GapObservation = {
  id: 3,
  holding_id: "sway",
  requirement: "R2",
  security_class: "series_a",
  missing_document: "board consent",
  kind: "referenced_location_unspecified",
  source_quote: "as approved by the board",
  remediation: "open",
};

/** A second holding: derivable, approved, realised before the date. */
export const SWAY_ROW: HoldingRow = {
  ...FIXTURE_ROW,
  holding_id: "sway",
  company_name: "Sway",
  position_type: "public_listed",
  held_at_date: false,
  mark: {
    ...FIXTURE_MARK,
    id: 2,
    holding_id: "sway",
    reported: { amount: "2500000", currency: "USD" },
    validated: { amount: "1234567.8900", currency: "USD" },
    derivation_status: "derivable",
    derivation_reason: "SHARES_TIMES_PPS",
    basis: "quoted_price",
    lineage: [LINEAGE],
  },
  assessments: [CALIBRATION],
  gaps: [COUNSEL_GAP, UNSPECIFIED_GAP],
  approval: APPROVAL,
  // R1 and R2 are always applicable and this row carries neither, so the API
  // reports both as never assessed — a stronger statement than "insufficient".
  supported: false,
  unsupported_reasons: { R1: "not assessed", R2: "not assessed", R3: "insufficient" },
  // A recorded valuation approval citing its assessments (INV-10). The row is
  // unsupported AND approved, which is a real and reviewable combination: the
  // two fields answer different questions.
  approved: true,
};

export const TWO_ROW_PACKET: PacketResponse = {
  ...FIXTURE_PACKET,
  rows: [FIXTURE_ROW, SWAY_ROW],
};

/**
 * A third holding: held at the measurement date AND supported — R1 and R2 both
 * present and sufficient, which is what `HoldingRow.supported` requires.
 *
 * It exists because without it the packet's four total figures cannot be told
 * apart. With only Dream (held, unsupported) and Sway (not held, unsupported),
 * `amount` equals `unsupported_amount` and `unsupported_positions` equals
 * `packet_gap_positions` — so a dashboard that rendered the subtotal where the
 * total belongs, or the gap count where the unsupported count belongs, passed
 * every assertion in this suite. Both mutations survived until this row existed.
 *
 * Poolside rather than an invented name: it is the position in the corpus whose
 * evidence is actually satisfied, by an executed SPA.
 */
export const POOLSIDE_ROW: HoldingRow = {
  ...FIXTURE_ROW,
  holding_id: "poolside",
  company_name: "Poolside",
  held_at_date: true,
  mark: {
    ...FIXTURE_MARK,
    id: 3,
    holding_id: "poolside",
    reported: { amount: "2500000", currency: "USD" },
    validated: { amount: "2500000", currency: "USD" },
    derivation_status: "derivable",
    derivation_reason: "SHARES_TIMES_PPS",
    basis: "last_round",
    lineage: [],
  },
  assessments: [
    { ...BASE_ASSESSMENT, requirement: "R1", verdict: "sufficient" },
    { ...BASE_ASSESSMENT, requirement: "R2", verdict: "sufficient" },
    {
      ...BASE_ASSESSMENT,
      requirement: "R3",
      verdict: "not_applicable",
      reason_codes: ["VALUE_CHANGED_SINCE_2025-09-30"],
    },
    {
      ...BASE_ASSESSMENT,
      requirement: "R4",
      verdict: "not_applicable",
      reason_codes: ["NO_REALISATION_IN_PERIOD"],
    },
    { ...BASE_ASSESSMENT, requirement: "R5", verdict: "sufficient" },
  ],
  gaps: [],
  approval: TRANSCRIPTION_APPROVAL,
  supported: true,
  unsupported_reasons: {},
  // A transcription approval in good standing is still not a fair-value
  // approval (SPEC §6.3), so a supported row can be unapproved — the mirror
  // image of Sway, and the pair that makes a generic "Approved" badge wrong.
  approved: false,
};

export const THREE_ROW_PACKET: PacketResponse = {
  ...FIXTURE_PACKET,
  rows: [FIXTURE_ROW, SWAY_ROW, POOLSIDE_ROW],
  totals: {
    kind: "held_at_date_reported",
    label: "Tracker-reported amounts for positions held at this date, unaudited",
    amount: { amount: "7500000", currency: "USD" },
    unsupported_amount: { amount: "5000000", currency: "USD" },
    unsupported_positions: 1,
    packet_gap_positions: 2,
    contains_unsupported_inputs: true,
    unheld_gap_positions: 1,
  },
};

/**
 * A realised position: in the packet, and carrying NO mark.
 *
 * `HoldingRow.mark` became `Mark | None` for exactly this row. A position
 * realised during the period is what the audit letter's fourth request asks for
 * by name, and it has no mark at the measurement date because it was not held
 * then — `evals/oracle/derived.json` states Jackpocket at 2024-12-31 as
 * `held_at_date: false` with `reported_amount: null`. Carrying the last known
 * mark forward would put a stale figure where the oracle says there is none, so
 * the surfaces have to render the absence itself.
 *
 * `supported`, `unsupported_reasons` and `approved` below are the values
 * `api/serialize.py` returns for the equivalent Python row — a row with no
 * assessments at all, which the API reports as R1 and R2 never assessed.
 */
export const REALISED_ROW: HoldingRow = {
  holding_id: "jackpocket",
  company_name: "Jackpocket",
  position_type: "direct_equity",
  held_at_date: false,
  mark: null,
  assessments: [],
  gaps: [],
  approval: null,
  supported: false,
  unsupported_reasons: { R1: "not assessed", R2: "not assessed" },
  approved: false,
};

/**
 * The three rows plus the realised one.
 *
 * The totals are the three-row totals with two counts moved, which is what
 * `Packet.totals()` returns for the added row: it is unsupported, so it is a
 * packet gap; it is not held at the date, so it is neither an input to `amount`
 * nor an `unsupported_position`. `packet_gap_positions` 2 → 3 and
 * `unheld_gap_positions` 1 → 2; the two money figures do not move at all, which
 * is the point — a row with no mark cannot change a sum of marks.
 */
export const FOUR_ROW_PACKET: PacketResponse = {
  ...THREE_ROW_PACKET,
  rows: [FIXTURE_ROW, SWAY_ROW, POOLSIDE_ROW, REALISED_ROW],
  totals: {
    ...THREE_ROW_PACKET.totals,
    packet_gap_positions: 3,
    unheld_gap_positions: 2,
  },
};

/**
 * Not hand-written. These are the figures `api/serialize.py` returns for the
 * three rows above, obtained by constructing the equivalent packet through the
 * Python contract models and reading the result — the same reason `fixture.ts`
 * is captured rather than typed. A hand-written total would agree with whatever
 * the dashboard did with it.
 *
 * All five differ, which is the whole point: 7,500,000 is both held rows,
 * 5,000,000 is the unsupported one of them, 1 position is held and unsupported,
 * 2 are unsupported whether held or not, and 1 is unsupported and not held. Five
 * distinct values means rendering any of them in another's place goes red.
 */
export const THREE_ROW_TOTALS = THREE_ROW_PACKET.totals;

/**
 * A claim whose facts resolve to passages — the state the evidence surface
 * exists to render, and the one no live holding is in yet, because the document
 * extractors are still being written.
 *
 * Two facts rather than two loose quotes: `field_name` is what says which
 * citation supports which number, and it is the whole reason `api/routes.py`
 * sends `facts` instead of the detached citation list it used to. The quote and
 * its offsets are what an auditor re-verifies —
 * `canonical_text[span_start:span_end]` in the stored document version must
 * equal `quote`, which `0008_citations_resolve.sql` enforces.
 *
 * One fact carries a `value_numeric` and one does not, because both are real:
 * a share count parses and a narrative phrase does not, and a surface that only
 * ever meets the first renders `null` as a blank the first time it meets it.
 */
export const CITED_CLAIM: EvidenceClaim = {
  ...SUBSEQUENT_EVIDENCE.claim,
  id: "poolside_spa_price",
  document_version_id: "dv_poolside_spa",
  holding_id: "poolside",
  claim_key: "poolside/series_b_price",
  source_class: "executed_transaction_doc",
  execution_status: "executed",
  facts: [
    {
      id: 21,
      claim_id: "poolside_spa_price",
      field_name: "price_per_share",
      value_text: "$2.50",
      value_numeric: "2.500000",
      state: "canonical",
      citation: {
        document_version_id: "dv_poolside_spa",
        quote: "the Purchase Price shall be $2.50 per share of Series B Preferred Stock",
        span_start: 4821,
        span_end: 4891,
      },
    },
    {
      id: 22,
      claim_id: "poolside_spa_price",
      field_name: "security_class",
      value_text: "Series B Preferred Stock",
      value_numeric: null,
      state: "candidate",
      citation: {
        document_version_id: "dv_poolside_spa",
        quote: "1,000,000 shares of Series B Preferred Stock",
        span_start: 5102,
        span_end: 5146,
      },
    },
  ],
};

/** A claim on file with no fact attached: recorded, not yet pinned to text. */
export const UNCITED_CLAIM: EvidenceClaim = {
  ...CITED_CLAIM,
  id: "poolside_board_deck",
  source_class: "company_communication",
  execution_status: "non_binding",
  facts: [],
};

export const HOLDING_WITH_EVIDENCE: HoldingResponse = {
  source: "ledger",
  holding_id: "poolside",
  company_name: "Poolside",
  evidence: [CITED_CLAIM, UNCITED_CLAIM],
};

/**
 * The answer for most of this fund: the holding exists, the corpus says nothing
 * about it. Rendered as a sentence rather than as a blank panel, because "we
 * looked and there is nothing" and "nothing loaded" are different claims.
 */
export const HOLDING_WITHOUT_EVIDENCE: HoldingResponse = {
  source: "ledger",
  holding_id: "fund_ii_anthropic",
  company_name: "Anthropic",
  evidence: [],
};
