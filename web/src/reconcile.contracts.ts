import type { AuditScope, PacketTotals } from "./contracts";
import type { Source } from "./responses";

/**
 * What the reconciliation and scorecard routes return.
 *
 * `contracts.ts` mirrors the Python models and `responses.ts` mirrors the four
 * packet routes. These two routes wrap different things — a committed tracker
 * snapshot and a per-fund-period roll-up — and drift for their own reasons, so
 * they get their own file rather than widening either of those.
 */

/**
 * Where the reconciliation report's figures came from.
 *
 * Not `Source`. The packet routes answer from the ledger or from a demo stub;
 * this one answers from `ingest/trackers/real_findings.json`, the committed
 * output of the reconciler run against the fund's two workbooks. That is a third
 * provenance and says so, because "the database says" and "the spreadsheets said
 * when we last read them" are different claims about a number.
 */
export type ReconciliationSource = "tracker_snapshot";

/**
 * SPEC §2 · which audit question a finding belongs to.
 *
 * `packet` is one of the six measurement dates the auditor's packet closes at.
 * `lineage_only` is one of the other six tracker periods, ingested for history
 * and never entering packet completeness (INV-20). `unscoped` is neither: the
 * fund-wide cost-basis column is stated once for the whole workbook and belongs
 * to no date at all.
 *
 * Three, not two, and a closed union rather than a nullable string — filing the
 * unscoped finding under either date would assert something the workbook does
 * not say, and dropping it would lose a real disagreement.
 */
export type FindingScope = "packet" | "lineage_only" | "unscoped";

/**
 * One place the two workbooks disagree.
 *
 * `kind` is a plain string on purpose. It is a machine-readable code from
 * `ingest/trackers/findings.py`, a seventeen-member vocabulary that layer owns,
 * and mirroring it here would create a second copy nothing binds to the first.
 * The reconciler already writes one English sentence per finding — `detail` —
 * so the code is rendered verbatim beside its own explanation rather than
 * glossed by a translation table that could quietly disagree with it.
 *
 * `stated` and `computed` are two different facts about the same column and are
 * never merged: the sheet's own total row said one thing and its cells sum to
 * another. Both are canonical decimal strings, as money is everywhere in this
 * project (INV-11); neither carries a currency, because the workbook cells do
 * not state one and inventing USD here would be inventing a fact.
 */
export interface Finding {
  kind: string;
  subject: string;
  scope: FindingScope;
  stated: string | null;
  computed: string | null;
  /**
   * `computed − stated`, subtracted by the API. SPEC §5.3 forbids this surface
   * subtracting two canonical figures, and the field is named for the direction
   * it runs in because a delta whose sign nobody wrote down can be read
   * backwards.
   */
  delta_computed_minus_stated: string | null;
  detail: string;
}

export interface FindingKindCount {
  kind: string;
  count: number;
}

/**
 * The findings for one audit scope, already separated by the API.
 *
 * The response has no flat `findings` list to render by accident: a single list
 * with a scope column on each row is one careless map away from a screen that
 * reports a 6/30/2025 disagreement as a finding about the packet.
 */
export interface ScopeBucket {
  scope: FindingScope;
  finding_count: number;
  by_kind: FindingKindCount[];
  findings: Finding[];
}

/**
 * `GET /reconciliation`.
 *
 * `finding_count` is every finding the reconciler produced across all twelve
 * tracker fund-periods. It is not a packet figure and is never the headline —
 * the three bucket counts are, reported separately, because adding them answers
 * a question the audit letter does not ask.
 */
export interface ReconciliationResponse {
  source: ReconciliationSource;
  snapshot: string;
  positions: number;
  tranches: number;
  fund_periods: number;
  finding_count: number;
  scopes: ScopeBucket[];
}

/**
 * Every count on the scorecard, supplied by the API.
 *
 * `fully_supported` and `positions` are two integers rather than a ratio so
 * that "0 of 8" is a sentence assembled from two supplied numbers. SPEC §5.3:
 * the division that would produce a percentage is not this surface's to make.
 *
 * `open_gap_positions` counts rows that are not fully supported — the same
 * quantity `PacketTotals.packet_gap_positions` reports, sent separately because
 * a fund-period whose rows carry no mark has counts and no totals.
 *
 * `held_at_date` and `not_held_at_date` are INV-7, not decoration: a position
 * realised during the period is one of the packet's positions and is not an
 * input to the total beside it.
 */
export interface ScorecardCounts {
  positions: number;
  fully_supported: number;
  open_gap_positions: number;
  pro_forma_positions: number;
  held_at_date: number;
  not_held_at_date: number;
}

/**
 * One fund-period.
 *
 * `counts` is `null` — not a row of zeros — when the ledger lists the period but
 * can assemble no packet for it. "Zero of zero positions supported" reads as a
 * finding about the fund; "no packet could be assembled" is a finding about the
 * ledger, and the two must not render the same way. `totals` is `null` on the
 * same line, and also when a packet's rows carry no mark at all, which is a
 * legitimate state with no figure to report.
 */
export interface ScorecardLine {
  fund_id: string;
  period_id: string;
  label: string;
  period_date: string | null;
  audit_scope: AuditScope | null;
  counts: ScorecardCounts | null;
  totals: PacketTotals | null;
  absent_reason: string | null;
}

/** `GET /scorecard` — every packet-scope fund-period, in the order the API lists them. */
export interface ScorecardResponse {
  source: Source;
  periods: ScorecardLine[];
}
