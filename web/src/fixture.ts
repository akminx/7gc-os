import type { HoldingRow, Mark } from "./contracts";
import type { FundsResponse, HoldingResponse, PacketResponse, TotalsResponse } from "./responses";

/**
 * The Dream slice, captured from the running API — all four read routes against
 * `api.main:app` with no DSN configured — and then typed against `contracts.ts`
 * and `responses.ts` rather than retyped from the Python fixture.
 *
 * Captured rather than hand-written for one reason: a hand-written frontend
 * fixture agrees with whatever the frontend expects, which makes it useless as
 * evidence that the wire shape is what the browser thinks it is. Because this is
 * the serialiser's own output, what is in it is really on the wire —
 * `supported`, `unsupported_reasons`, `approved`, `applicable` and
 * `contains_unsupported_inputs` appear here because `api/serialize.py` now
 * attaches them, and every screen that used to say "not supplied by API" was
 * saying something that had stopped being true.
 *
 * `source` is `"fixture"` throughout, because that is what this is. Against a
 * configured database the same routes answer `"ledger"` with eight holdings and
 * 25,648,515, and the screens say which one they are showing.
 */

export const FIXTURE_FUNDS: FundsResponse = {
  source: "fixture",
  periods: [{ fund_id: "fund_ii", period_id: "f2_25q4", label: "FY2025 Q4" }],
};

/**
 * Dream's mark, named so it can be spread without first proving it is not null.
 *
 * `HoldingRow.mark` is `Mark | null` — a realised position has none — so reading
 * it back off the row gives a nullable value that a variant cannot extend. This
 * is the same captured object, referenced by `FIXTURE_ROW` below rather than
 * copied, so the snapshot comparison is unaffected.
 */
export const FIXTURE_MARK: Mark = {
  id: 1,
  holding_id: "dream",
  period_id: "f2_25q4",
  revision: 1,
  reported: { amount: "5000000", currency: "USD" },
  validated: null,
  derivation_status: "not_derivable",
  derivation_reason: "NO_PRICE_FOR_CLASS:series_a1",
  basis: null,
  lineage: [],
};

export const FIXTURE_ROW: HoldingRow = {
  holding_id: "dream",
  company_name: "Dream",
  position_type: "direct_equity",
  held_at_date: true,
  mark: FIXTURE_MARK,
  assessments: [
    {
      requirement: "R1",
      verdict: "missing",
      reason_codes: ["ACQUISITION_DOCS_NOT_LOCATED"],
      next_actions: ["REQUEST_FROM_COMPANY"],
      evidence: [],
      pro_forma: false,
      tracker_label: null,
      policy_version: "v1",
      applicable: true,
    },
    {
      requirement: "R2",
      verdict: "insufficient",
      reason_codes: [
        "CROSS_CLASS_POLICY_DECISION_REQUIRED",
        "NO_SUPPORT_FOR_A_HELD_CLASS",
        "OFF_CLASS_EVIDENCE_NOT_RELIED",
      ],
      next_actions: ["RECORD_VALUATION_POLICY_DECISION"],
      evidence: [
        {
          claim: {
            id: "dream_b_cap",
            document_version_id: "dv_dream_b_captable",
            holding_id: "dream",
            claim_key: "dream/series_b_price",
            source_class: "company_cap_table",
            execution_status: "pro_forma",
            issued_date: "2025-11-14",
            as_of_date: null,
            received_date: null,
            applicable_from: "2025-11-14",
            applicable_to: null,
            priced_class: "series_b",
            price_per_share: "8.00",
            stated: null,
            supersedes_claim_id: null,
          },
          is_subsequent: false,
        },
        {
          claim: {
            id: "dream_close_email",
            document_version_id: "dv_dream_closing_email",
            holding_id: "dream",
            claim_key: "dream/series_b_price",
            source_class: "company_communication",
            execution_status: "unexecuted_referenced",
            issued_date: "2025-11-17",
            as_of_date: null,
            received_date: null,
            applicable_from: "2025-11-17",
            applicable_to: null,
            priced_class: "series_b",
            price_per_share: "8.00",
            stated: null,
            supersedes_claim_id: null,
          },
          is_subsequent: false,
        },
      ],
      pro_forma: true,
      tracker_label: null,
      policy_version: "v1",
      applicable: true,
    },
    {
      requirement: "R3",
      verdict: "not_applicable",
      reason_codes: ["VALUE_CHANGED_SINCE_2025-09-30"],
      next_actions: [],
      evidence: [],
      pro_forma: false,
      tracker_label: null,
      policy_version: "v1",
      applicable: false,
    },
    {
      requirement: "R4",
      verdict: "not_applicable",
      reason_codes: ["NO_REALISATION_IN_PERIOD"],
      next_actions: [],
      evidence: [],
      pro_forma: false,
      tracker_label: null,
      policy_version: "v1",
      applicable: false,
    },
    {
      requirement: "R5",
      verdict: "sufficient",
      reason_codes: [],
      next_actions: [],
      evidence: [],
      pro_forma: false,
      tracker_label: null,
      policy_version: "v1",
      applicable: true,
    },
  ],
  gaps: [
    {
      id: 1,
      holding_id: "dream",
      requirement: "R1",
      security_class: "series_a1",
      missing_document: "Series A-1 acquisition docs",
      kind: "not_located",
      source_quote: "no executed acquisition document in corpus",
      remediation: "open",
    },
  ],
  approval: null,
  supported: false,
  unsupported_reasons: { R1: "missing", R2: "insufficient" },
  approved: false,
};

/**
 * `GET …/packet` verbatim, totals included. The totals are no longer a second
 * request: they arrive inside the response that carries the rows they are a
 * total of, which is the only arrangement in which the two cannot be from
 * different periods.
 */
export const FIXTURE_PACKET: PacketResponse = {
  source: "fixture",
  fund_id: "fund_ii",
  period: {
    id: "f2_25q4",
    fund_id: "fund_ii",
    period_date: "2025-12-31",
    audit_scope: "packet",
    label: "FY2025 Q4",
  },
  rows: [FIXTURE_ROW],
  schema_version: "1",
  policy_version: "v1",
  generated_at: "2026-01-15T12:00:00Z",
  // `null`, not `{}`. The fixture branch has no ledger to derive FROM, so no
  // recomputation was attempted — which is a different fact from a recomputation
  // that ran and had nothing to say about any row.
  recomputations: null,
  totals: {
    kind: "held_at_date_reported",
    label: "Tracker-reported amounts for positions held at this date, unaudited",
    amount: { amount: "5000000", currency: "USD" },
    unsupported_amount: { amount: "5000000", currency: "USD" },
    unsupported_positions: 1,
    packet_gap_positions: 1,
    contains_unsupported_inputs: true,
    unheld_gap_positions: 0,
  },
};

/** `GET …/totals` verbatim — the same figures, with their own `source`. */
export const FIXTURE_TOTALS: TotalsResponse = {
  source: "fixture",
  ...FIXTURE_PACKET.totals,
};

/**
 * `GET /holdings/dream` verbatim. The evidence list is EMPTY, and that is the
 * capture rather than an oversight: the fixture branch has no claim store behind
 * it, and for most of the real fund the answer is the same. The workspace has to
 * be able to say so.
 */
export const FIXTURE_HOLDING: HoldingResponse = {
  source: "fixture",
  holding_id: "dream",
  company_name: "Dream",
  evidence: [],
};
