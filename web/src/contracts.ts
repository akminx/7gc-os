/**
 * The wire contract for one MODEL, transcribed by hand from
 * `packages/contracts/models.py` and `packages/contracts/enums.py`. The shapes
 * the ROUTES wrap around these — `source`, the embedded totals, the evidence
 * list — live in `responses.ts`, so that this file stays a mirror of the Python
 * models and can be checked against them field for field.
 *
 * Two properties of this file are deliberate:
 *
 * 1. **It is types only — no runtime values.** The closed vocabularies are
 *    string-literal unions rather than TypeScript enums, so nothing here can be
 *    compared with `>` or fed to `max()`. INV-1 and INV-2 say authority and
 *    verdicts are sets, not scales, and a union type cannot be ordered.
 * 2. **It declares the computed fields, because the API now sends them.**
 *    `supported`, `unsupported_reasons`, `approved`, `applicable` and
 *    `contains_unsupported_inputs` are Python `@property`, which Pydantic does
 *    not serialise; `api/serialize.py` attaches each one to the model dump by
 *    hand. Every one of them was previously rendered as "not supplied by API".
 *    They are marked below with the property they come from, because the browser
 *    must render them and must not recompute them — SPEC §5.3 assigns support
 *    status and reason codes to the API, and the derivation is subtle in exactly
 *    the way that invites a wrong reimplementation.
 *
 * `Money.amount` is a `Decimal` on the Python side and arrives as a decimal
 * STRING. It is typed `string` here so that no arithmetic operator will accept
 * it without an explicit, visible conversion.
 */

export type AuditScope = "packet" | "lineage_only";

export type PositionType =
  | "direct_equity"
  | "indirect_feeder"
  | "public_listed"
  | "fx_denominated_interest";

export type SourceClass =
  | "executed_transaction_doc"
  | "fund_internal_record"
  | "company_cap_table"
  | "company_communication"
  | "administrator_statement"
  | "public_market_quote"
  | "third_party_valuation_memo"
  | "press"
  | "rumor";

export type ExecutionStatus =
  | "executed"
  | "pro_forma"
  | "non_binding"
  | "unexecuted_referenced"
  | "not_applicable";

export type RequirementCode = "R1" | "R2" | "R3" | "R4" | "R5";

export type RequirementVerdict =
  | "not_assessed"
  | "not_applicable"
  | "missing"
  | "insufficient"
  | "partial"
  | "conflicting"
  | "sufficient";

export type DerivationStatus = "derivable" | "not_derivable";

export type ValuationBasis =
  | "cost"
  | "last_round"
  | "third_party_memo"
  | "quoted_price"
  | "administrator_nav"
  | "realization";

export type GapKind = "with_counsel" | "referenced_location_unspecified" | "not_located";

export type GapRemediation = "open" | "requested" | "received" | "unobtainable";

export type DecisionType = "transcription" | "valuation" | "management_assessment" | "packet";

export type DecisionStatus = "draft" | "approved" | "rejected" | "superseded";

export type FactState = "candidate" | "canonical" | "approved";

export type TotalKind = "tracker_reported" | "held_at_date_reported" | "approved_fair_value";

/** INV-11 · an amount that knows its currency. `amount` is a decimal string. */
export interface Money {
  amount: string;
  currency: string;
}

export interface Citation {
  document_version_id: string;
  quote: string;
  span_start: number;
  span_end: number;
}

export interface SourceFact {
  id: number;
  claim_id: string;
  field_name: string;
  value_text: string;
  value_numeric: string | null;
  state: FactState;
  citation: Citation;
}

export interface DerivedFigureInput {
  ordinal: number;
  fact: SourceFact | null;
  child: DerivedFigure | null;
}

export interface DerivedFigure {
  id: number;
  label: string;
  operator: string;
  value: Money;
  inputs: DerivedFigureInput[];
}

export interface Claim {
  id: string;
  document_version_id: string;
  holding_id: string;
  claim_key: string;
  source_class: SourceClass;
  execution_status: ExecutionStatus;
  issued_date: string;
  as_of_date: string | null;
  received_date: string | null;
  applicable_from: string;
  applicable_to: string | null;
  priced_class: string | null;
  price_per_share: string | null;
  stated: Money | null;
  supersedes_claim_id: string | null;
}

export interface EvidenceCitation {
  claim: Claim;
  is_subsequent: boolean;
}

export interface RequirementAssessment {
  requirement: RequirementCode;
  verdict: RequirementVerdict;
  reason_codes: string[];
  next_actions: string[];
  evidence: EvidenceCitation[];
  pro_forma: boolean;
  tracker_label: string | null;
  policy_version: string;
  /**
   * `RequirementAssessment.applicable`, computed by the API.
   *
   * False exactly when the verdict is `not_applicable`. It is rendered anyway,
   * beside the verdict, because "the requirement does not arise here" and "the
   * requirement arises and nothing satisfies it" are the pair INV-2 exists to
   * keep apart, and a reader should not have to know that one field is the other
   * one negated.
   */
  applicable: boolean;
}

export interface GapObservation {
  id: number;
  holding_id: string;
  requirement: RequirementCode;
  security_class: string | null;
  missing_document: string;
  kind: GapKind;
  source_quote: string;
  remediation: GapRemediation;
}

export interface Approval {
  id: number;
  decision_type: DecisionType;
  status: DecisionStatus;
  mark_id: number | null;
  packet_id: string | null;
  policy_version: string | null;
  evidence_assessment_ids: number[];
  actor_id: string;
  decided_at: string;
}

export interface Mark {
  id: number;
  holding_id: string;
  period_id: string;
  revision: number;
  reported: Money;
  validated: Money | null;
  derivation_status: DerivationStatus;
  derivation_reason: string;
  basis: ValuationBasis | null;
  lineage: DerivedFigure[];
}

export interface PacketTotals {
  kind: TotalKind;
  label: string;
  amount: Money;
  unsupported_amount: Money;
  unsupported_positions: number;
  /**
   * INV-7 / INV-19 · every unsupported row, held at the measurement date or
   * not. A SUPERSET of `unsupported_positions`. The unheld gaps are the
   * difference of the two; adding them double counts — and subtracting them is
   * arithmetic on a canonical figure, which §5.3 puts on the API's side of the
   * line, so this surface renders all three numbers and derives none of them.
   */
  packet_gap_positions: number;
  /**
   * `PacketTotals.contains_unsupported_inputs`, computed by the API.
   *
   * INV-19 · whether this figure has anything unsupported inside it. Not a
   * restatement of the subtotal being non-zero: it is true if EITHER the
   * unsupported amount or the unsupported position count is non-zero, and a
   * position can be unsupported at a zero mark.
   */
  contains_unsupported_inputs: boolean;
  /**
   * The difference `packet_gap_positions − unsupported_positions`, computed by
   * the API so that the browser never has to subtract two canonical counts.
   * That subtraction is what §5.3 forbids, and it is the exact expression a
   * probe once got past both gates with.
   */
  unheld_gap_positions: number;
}

export interface HoldingRow {
  holding_id: string;
  company_name: string;
  position_type: PositionType;
  held_at_date: boolean;
  /**
   * Absent when the ledger holds no mark for this holding at this date.
   *
   * A position realised during the period is still in the packet — the audit
   * letter asks for realised investments by name — and has no mark at the
   * measurement date because it was not held then. `evals/oracle/derived.json`
   * states Jackpocket at 2024-12-31 as `held_at_date: false`,
   * `reported_amount: null`.
   *
   * `Mark | null`, not an optional field: the API always sends the key. The
   * browser must render the ABSENCE — carrying the last known mark forward
   * would put a stale figure where the oracle says there is none, and a blank
   * cell reads as zero on a screen full of amounts.
   */
  mark: Mark | null;
  assessments: RequirementAssessment[];
  gaps: GapObservation[];
  approval: Approval | null;
  /**
   * `HoldingRow.supported`, computed by the API. SPEC §7.1–7.2 · every
   * applicable requirement is sufficient AND the always-applicable ones were
   * actually assessed. Two earlier Python versions got this wrong in opposite
   * directions, which is the reason it is not recomputed here.
   */
  supported: boolean;
  /**
   * `HoldingRow.unsupported_reasons`, computed by the API: why the row is not
   * supported, keyed by requirement code. Empty exactly when `supported`.
   *
   * `Partial` because the API sends only the codes that have a reason — an
   * absent key is "this requirement is fine", which is not the same as a key
   * whose reason is empty, and `noUncheckedIndexedAccess` makes the difference
   * something a caller has to handle rather than assume.
   */
  unsupported_reasons: Partial<Record<RequirementCode, string>>;
  /**
   * `HoldingRow.approved`, computed by the API. INV-10 · true only for a
   * RECORDED valuation approval that cites the assessments it rests on. Nothing
   * about this row being unsupported or supported creates it, and it is not the
   * same question as `approval !== null` — a transcription approval is an
   * approval and leaves this false.
   */
  approved: boolean;
}

export interface Period {
  id: string;
  fund_id: string;
  period_date: string;
  audit_scope: AuditScope;
  label: string;
}

export interface Packet {
  fund_id: string;
  period: Period;
  rows: HoldingRow[];
  schema_version: string;
  policy_version: string;
  generated_at: string;
}
