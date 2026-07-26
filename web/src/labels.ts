import type {
  AuditScope,
  DecisionStatus,
  DecisionType,
  DerivationStatus,
  ExecutionStatus,
  GapKind,
  GapRemediation,
  PositionType,
  RequirementCode,
  RequirementVerdict,
  SourceClass,
  TotalKind,
  ValuationBasis,
} from "./contracts";
import type { Source } from "./responses";

/**
 * Display vocabulary. Every map here is total over its union — a new member of
 * a closed vocabulary is a type error, not a blank cell, which is the point of
 * `Record<Union, …>` rather than a lookup with a fallback. A fallback is how an
 * unrecognised verdict renders as an empty box that reads like "fine".
 *
 * Nothing in this file decides anything. It attaches a human label to a value
 * the API already decided.
 */

export interface Term {
  label: string;
  meaning: string;
}

/**
 * Which store answered the request.
 *
 * The two labels are deliberately not symmetrical. `ledger` is unremarkable and
 * says so quietly; `fixture` interrupts, because a viewer who does not notice it
 * is reading a 5,000,000 one-holding stub as a 25,648,515 eight-holding fund.
 */
export const SOURCE: Record<Source, Term> = {
  ledger: {
    label: "ledger",
    meaning: "Read from the fund's database. Every figure below traces to a stored record.",
  },
  fixture: {
    label: "fixture — not the fund",
    meaning:
      "No database was configured, so the API served its one-holding demo stub. Nothing on this screen is the fund's data.",
  },
};

/**
 * INV-2 · seven distinct findings, deliberately unordered.
 *
 * Each gets its own hue AND its own glyph, because `missing` and
 * `not_applicable` mean opposite things to an auditor — one is evidence that
 * should exist and does not, the other is a question that was never asked of
 * this position. A shared "not ok" treatment is the cheapest way to make a
 * packet look complete, so the two are as far apart here as any two entries.
 */
export const VERDICT: Record<RequirementVerdict, Term & { glyph: string }> = {
  not_assessed: {
    label: "not assessed",
    glyph: "?",
    meaning: "Nobody has looked. This is not a finding of any kind.",
  },
  not_applicable: {
    label: "not applicable",
    glyph: "∅",
    meaning: "The requirement does not arise for this position at this date.",
  },
  missing: {
    label: "missing",
    glyph: "✕",
    meaning: "Evidence that should exist was not located.",
  },
  insufficient: {
    label: "insufficient",
    glyph: "▲",
    meaning: "Evidence exists but cannot support the requirement.",
  },
  partial: {
    label: "partial",
    glyph: "◐",
    meaning: "Evidence supports part of the requirement. Two partials never compose to sufficient.",
  },
  conflicting: {
    label: "conflicting",
    glyph: "⇄",
    meaning:
      "Claims contradict. Dominates every other verdict until a human resolution supersedes.",
  },
  sufficient: {
    label: "sufficient",
    glyph: "✓",
    meaning: "The requirement is met by the cited evidence.",
  },
};

/** SPEC §7.1. */
export const REQUIREMENT: Record<RequirementCode, Term> = {
  R1: { label: "R1 · existence and cost", meaning: "Applies to every holding at every date." },
  R2: { label: "R2 · fair-value support", meaning: "Applies to every holding at every date." },
  R3: {
    label: "R3 · unchanged-mark calibration",
    meaning: "Applies when the mark did not move and material support is stale.",
  },
  R4: { label: "R4 · realization support", meaning: "Applies to realised lots only." },
  R5: {
    label: "R5 · pro-forma identification",
    meaning: "A labelling requirement for pro-forma marks. Labelling correctly is not support.",
  },
};

/** INV-12 · why a document is absent decides what the auditor does next. */
export const GAP_KIND: Record<GapKind, Term & { next: string }> = {
  with_counsel: {
    label: "with counsel",
    meaning: "The document exists and is held by counsel.",
    next: "Request from counsel. R1 is partial, not missing.",
  },
  referenced_location_unspecified: {
    label: "referenced, location unspecified",
    meaning: "A document is referred to, with no statement of where it is.",
    next: "Establish custody before requesting. Insufficient on its own.",
  },
  not_located: {
    label: "not located",
    meaning: "The document was searched for and not found.",
    next: "Request from the company.",
  },
};

/** Rendering order for the gap inventory. Fixed, so a kind never disappears. */
export const GAP_KIND_ORDER: GapKind[] = [
  "with_counsel",
  "referenced_location_unspecified",
  "not_located",
];

export const GAP_REMEDIATION: Record<GapRemediation, string> = {
  open: "open",
  requested: "requested",
  received: "received",
  unobtainable: "unobtainable",
};

/** SPEC §6.3 · four independent decisions. None implies another. */
export const DECISION_TYPE: Record<DecisionType, Term> = {
  transcription: {
    label: "transcription approval",
    meaning:
      "The figure was transcribed faithfully from its source. It may appear in reconciliation and gap sections and NEVER as fair value.",
  },
  valuation: {
    label: "valuation approval",
    meaning: "The mark may appear as an approved fair value and enter the approved total.",
  },
  management_assessment: {
    label: "management-assessment approval",
    meaning: "A human-edited management assessment closes R3.",
  },
  packet: {
    label: "packet approval",
    meaning: "Export is permitted. Requires the lower decisions but never creates them.",
  },
};

export const DECISION_STATUS: Record<DecisionStatus, string> = {
  draft: "draft",
  approved: "approved",
  rejected: "rejected",
  superseded: "superseded",
};

/** INV-19 · a total must say what it is a total OF. */
export const TOTAL_KIND: Record<TotalKind, Term> = {
  tracker_reported: {
    label: "tracker reported",
    meaning: "The tracker's own stated total, including positions not held at the date.",
  },
  held_at_date_reported: {
    label: "held at date · reported",
    meaning:
      "Tracker-reported amounts for the positions held at this measurement date. Unaudited, and not the tracker's own total.",
  },
  approved_fair_value: {
    label: "approved fair value",
    meaning: "Only marks carrying a valuation approval. Cannot contain an unsupported position.",
  },
};

export const POSITION_TYPE: Record<PositionType, string> = {
  direct_equity: "direct equity",
  indirect_feeder: "indirect feeder",
  public_listed: "public listed",
  fx_denominated_interest: "FX-denominated interest",
};

export const SOURCE_CLASS: Record<SourceClass, string> = {
  executed_transaction_doc: "executed transaction doc",
  // The fund's own paperwork about its own position. Distinct from a
  // third-party memo on purpose: management's arithmetic on management's
  // holding is not an outside valuer having checked it.
  fund_internal_record: "fund internal record",
  company_cap_table: "company cap table",
  company_communication: "company communication",
  administrator_statement: "administrator statement",
  public_market_quote: "public market quote",
  third_party_valuation_memo: "third-party valuation memo",
  press: "press",
  rumor: "rumor",
};

/** INV-4 · a signed document and a proposed one are different evidence. */
export const EXECUTION_STATUS: Record<ExecutionStatus, string> = {
  executed: "executed",
  pro_forma: "pro forma",
  non_binding: "non-binding",
  unexecuted_referenced: "unexecuted, referenced",
  not_applicable: "not applicable",
};

/** INV-13 · derivable is about arithmetic; supported is about evidence. */
export const DERIVATION_STATUS: Record<DerivationStatus, Term> = {
  derivable: {
    label: "derivable",
    meaning: "The evidence independently reproduces an amount. It says nothing about support.",
  },
  not_derivable: {
    label: "not derivable",
    meaning: "No validated amount could be derived from the evidence.",
  },
};

export const VALUATION_BASIS: Record<ValuationBasis, string> = {
  cost: "cost",
  last_round: "last round",
  third_party_memo: "third-party memo",
  quoted_price: "quoted price",
  administrator_nav: "administrator NAV",
  realization: "realization",
};

export const AUDIT_SCOPE: Record<AuditScope, Term> = {
  packet: { label: "packet", meaning: "An audit measurement date. Enters packet completeness." },
  lineage_only: {
    label: "lineage only",
    meaning: "A tracker period. Never generates an assessment and never enters completeness.",
  },
};
