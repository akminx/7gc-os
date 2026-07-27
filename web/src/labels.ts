import type {
  AuditScope,
  DecisionStatus,
  DecisionType,
  DerivationStatus,
  ExecutionStatus,
  FactState,
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

/**
 * SPEC §7.1, and the paragraph of the client's letter each requirement answers.
 *
 * `meaning` says when the requirement ARISES; `letter` says what the client
 * asked for. They are different questions and the second was missing from every
 * screen: the dashboard's columns read `R1`…`R5`, and an auditor asked "which of
 * Harwell & Kent's four requests does this packet answer" had to hover five
 * headers to find out — on a project whose stated rule is to measure against the
 * audit letter rather than against itself.
 *
 * `letter` is TRANSCRIBED from `packet/tables.py::REQUIREMENTS`, which is where
 * the exported packet states the same mapping, and
 * `tests/test_label_coverage.py` asserts the two are identical. Two independent
 * descriptions of what the client asked for is exactly the drift this project
 * refuses everywhere else; one source and a checked mirror is the shape it uses
 * instead.
 */
export const REQUIREMENT: Record<RequirementCode, Term & { paragraph: string; letter: string }> = {
  R1: {
    label: "R1 · existence and cost",
    paragraph: "¶1",
    letter:
      "Letter ¶1 — executed transaction documents supporting acquisition, share counts, price per share and settlement of funds",
    meaning: "Applies to every holding at every date.",
  },
  R2: {
    label: "R2 · fair-value support",
    paragraph: "¶2",
    letter: "Letter ¶2 — fair value support as of this measurement date",
    meaning: "Applies to every holding at every date.",
  },
  R3: {
    label: "R3 · unchanged-mark calibration",
    paragraph: "¶3",
    letter:
      "Letter ¶3 — management's assessment that the last round price remains representative at this date",
    meaning: "Applies when the mark did not move and material support is stale.",
  },
  R4: {
    label: "R4 · realization support",
    paragraph: "¶4",
    letter:
      "Letter ¶4 — merger consideration, distribution notices or other support for proceeds received",
    meaning: "Applies to realised lots only.",
  },
  R5: {
    label: "R5 · pro-forma identification",
    paragraph: "closing ¶",
    letter:
      "Letter, closing paragraph — identify any positions marked on a pro forma basis pending executed documentation",
    meaning: "A labelling requirement for pro-forma marks. Labelling correctly is not support.",
  },
};

/**
 * Why a requirement is short, in words, and WHICH KIND of shortfall it is.
 *
 * `reason_codes` is `string[]` on the wire, not a closed union, because the
 * policy owns the vocabulary and adds to it. So this map is deliberately
 * partial and `reasonGloss` never invents a label: an unglossed code renders as
 * the code, which is the API's own word for it, and says no gloss is recorded.
 * The failure being avoided is the opposite one — a lookup with a friendly
 * fallback turning an unrecognised finding into a reassuring blank.
 *
 * `origin` is the load-bearing field and the reason this map exists at all.
 * Two codes carry the same verdict, `missing`, and mean opposite things:
 *
 * * `SUPPORT_OUTSIDE_ITS_OWN_RELIANCE_WINDOW` is `expired`. Evidence EXISTED:
 *   the document is on file and the source's own stated window does not reach
 *   this measurement date. The letter goes to the valuer who wrote it, asking
 *   for a re-issue.
 * * `NO_APPLICABLE_SUPPORT_*` is not that, and it is not one thing either. A
 *   document searched for and not found is `never_located` and the letter goes
 *   to the company; a document sitting with counsel is `held_elsewhere` and the
 *   letter goes to counsel. Filing the second under "nothing ever existed" is
 *   wrong on the facts and sends the wrong letter, so the two are separate.
 *
 * Same word on the chip, different letters to different people. Rendering them
 * identically would put a request for an update in front of a company that was
 * never asked for the document in the first place, so `origin` gives them
 * separate treatments and the block that shows them states the distinction in
 * the copy rather than relying on the reader knowing the codes.
 */
export type ShortfallOrigin =
  | "expired"
  | "never_located"
  | "held_elsewhere"
  | "insufficient_authority"
  | "unresolved";

export interface ReasonTerm extends Term {
  origin: ShortfallOrigin;
}

export const SHORTFALL_ORIGIN: Record<ShortfallOrigin, Term> = {
  expired: {
    label: "support existed and expired",
    meaning:
      "A document on file once covered this. Its own stated reliance window does not reach this measurement date, so it is out of date rather than absent. The letter asks the valuer who wrote it to re-issue.",
  },
  never_located: {
    label: "no support has been located anywhere",
    meaning:
      "It was searched for and not found, and no record says who holds it. There is nothing to re-date and nobody named to ask, so the letter goes to the company.",
  },
  held_elsewhere: {
    label: "it exists, and the fund does not hold it",
    meaning:
      "A record names the document and it is outside the fund's repository. The letter goes to whoever holds it, which is a different letter from the one asking a company to produce a document nobody can find.",
  },
  insufficient_authority: {
    label: "the document exists and cannot carry this",
    meaning:
      "Evidence is on file, and either whose word it is or whether it is signed falls short of what the requirement asks.",
  },
  unresolved: {
    label: "a decision or a step is outstanding",
    meaning: "The evidence is on file and something a human owes has not been recorded yet.",
  },
};

export const REASON_CODE: Record<string, ReasonTerm> = {
  SUPPORT_OUTSIDE_ITS_OWN_RELIANCE_WINDOW: {
    label: "support is outside its own reliance window",
    origin: "expired",
    meaning:
      "The source states the period it may be relied on for, and this measurement date is not in it. The evidence is on file and out of date.",
  },
  NO_APPLICABLE_SUPPORT_NOT_LOCATED: {
    label: "no applicable support · the document was not located",
    origin: "never_located",
    meaning: "It was searched for in the fund's repository and not found.",
  },
  NO_APPLICABLE_SUPPORT_WITH_COUNSEL: {
    label: "no applicable support · the document is with counsel",
    origin: "held_elsewhere",
    meaning: "It exists, outside the fund's repository, in counsel's hands.",
  },
  NO_APPLICABLE_SUPPORT_REFERENCED_LOCATION_UNSPECIFIED: {
    label: "no applicable support · referenced, location unstated",
    origin: "held_elsewhere",
    meaning: "A record refers to the document and states nowhere it can be found.",
  },
  DOCUMENT_NOT_LOCATED: {
    label: "the document was not located",
    origin: "never_located",
    meaning: "Searched for in the fund's repository and not found.",
  },
  DOCUMENT_WITH_COUNSEL: {
    label: "the document is with counsel",
    origin: "held_elsewhere",
    meaning: "It exists and the fund does not hold it. Existence and cost is partial, not missing.",
  },
  DOCUMENT_LOCATION_UNSPECIFIED: {
    label: "the document is referenced with no location",
    origin: "held_elsewhere",
    meaning: "Custody has to be established before anyone can request it.",
  },
  PRESS_CANNOT_SUPPORT_FAIR_VALUE: {
    label: "press cannot support a fair value",
    origin: "insufficient_authority",
    meaning:
      "A published report of a round is not evidence of this fund's position in it. The article may be entirely accurate and still cannot carry the mark.",
  },
  MANAGEMENT_ASSERTION_WITHOUT_PRIMARY_SOURCE: {
    label: "a management assertion with no primary source",
    origin: "insufficient_authority",
    meaning: "The fund's own record of its own holding, with nothing outside it agreeing.",
  },
  NON_BINDING_TERM_SHEET: {
    label: "a non-binding term sheet",
    origin: "insufficient_authority",
    meaning:
      "Terms nobody is committed to. An unsigned document is different evidence from a signed one.",
  },
  PRO_FORMA_PENDING_EXECUTION: {
    label: "pro forma, pending execution",
    origin: "insufficient_authority",
    meaning: "The figures assume a closing that the corpus does not show as executed.",
  },
  UNCOVERED_SECURITY_CLASS: {
    label: "no evidence covers the class the fund holds",
    origin: "never_located",
    meaning:
      "Something on file prices a class, and it is not this one. Priced class and held class are different facts.",
  },
  CROSS_CLASS_POLICY_DECISION_REQUIRED: {
    label: "a cross-class inference needs a recorded policy decision",
    origin: "unresolved",
    meaning:
      "Carrying a price from one security class to another is a valuation judgement, and no human has recorded it.",
  },
  CLOSING_SET_PENDING: {
    label: "the closing set has not arrived",
    origin: "unresolved",
    meaning: "Executed documents are said to be coming and are not here yet.",
  },
  MARK_UNCHANGED_WITH_STALE_SUPPORT: {
    label: "the mark did not move and its support is stale",
    origin: "expired",
    meaning:
      "R3 · an unchanged carrying value needs a calibration statement once the evidence under it has aged.",
  },
  // ── Reachable since today's rulings on the audit letter ──────────────
  // Added here in the same pass that found them on screen. An unglossed code
  // renders as "no gloss is recorded for this code", and `OFF_CLASS_EVIDENCE_
  // NOT_RELIED` was doing exactly that on Fluidstack's fair-value pane — which
  // is a stop on the five-minute walkthrough.
  //
  // Every gloss below is written from the policy's own reasoning at the cell
  // that raises it, not from the code's name. A label invented from a constant
  // is a translation of a string rather than of a finding.
  NO_MANAGEMENT_BASIS_MEMO: {
    label: "the third party's memo, and no memo from management",
    origin: "insufficient_authority",
    meaning:
      "Letter ¶2 asks for two things where a mark is based on something other than a financing round: the underlying source AND management's memo describing the basis of the mark. The valuer's memo is a real and authoritative half of that conjunction. The other half does not exist anywhere in this fund's records.",
  },
  SETTLEMENT_WITHOUT_SHARE_TERMS: {
    label: "settlement confirmed, share terms not",
    origin: "insufficient_authority",
    meaning:
      "Letter ¶1 asks for share counts, price per share AND settlement of funds. This evidences the third limb only: it proves the fund paid and says nothing about what the fund received. On its own an auditor could not establish the position from it.",
  },
  OFF_CLASS_EVIDENCE_NOT_RELIED: {
    label: "evidence about a class the fund does not hold, not counted",
    origin: "unresolved",
    meaning:
      "A document on file prices a different security class from the one held. It is named rather than dropped — it is in scope, and it is what makes this holding cross-class — but pricing one class off another's evidence is a valuation-policy act (INV-17) and is not performed until that decision is recorded.",
  },
  NO_SUPPORT_FOR_A_HELD_CLASS: {
    label: "every document on file prices a class the fund does not hold",
    origin: "insufficient_authority",
    meaning:
      "Not an absence of evidence: there are documents and they state prices, for a class this position is not. `insufficient` rather than `missing` for that reason. The derivation has always refused this case — no price for the held class — and the verdict now agrees with it.",
  },
};

export function reasonGloss(code: string): ReasonTerm {
  return (
    REASON_CODE[code] ?? {
      // Not the code again. It is already on screen beside this, and a label
      // that repeats its own key reads as a translation that happened to be
      // identical rather than as one that is absent.
      label: "no gloss is recorded for this code",
      origin: "unresolved",
      meaning: "The policy states this code and this display carries no gloss for it.",
    }
  );
}

/**
 * What the auditor does next, and WHO receives the letter.
 *
 * The recipient is a separate field because it is the half a reader acts on and
 * the half two identically-worded verdicts disagree about: an expired valuation
 * goes back to the valuer, an absent one goes to the company.
 */
export interface ActionTerm extends Term {
  recipient: string;
}

export const NEXT_ACTION: Record<string, ActionTerm> = {
  REQUEST_UPDATED_VALUATION: {
    label: "request an updated valuation",
    recipient: "the valuer who issued the memo on file",
    meaning:
      "The memo exists and its reliance window has closed. Ask for a re-issue as of this measurement date.",
  },
  REQUEST_FROM_COMPANY: {
    label: "request from the company",
    recipient: "the portfolio company",
    meaning: "Nothing on file covers this. Ask the company for the underlying document.",
  },
  REQUEST_FROM_COUNSEL: {
    label: "request from counsel",
    recipient: "the company's outside counsel",
    meaning: "The document exists and counsel holds it.",
  },
  REQUEST_WITH_LOCATION: {
    label: "establish custody, then request",
    recipient: "the fund's own records, first",
    meaning: "A record refers to the document without saying where it is. Custody comes first.",
  },
  REQUEST_EXECUTED_DOC: {
    label: "request the executed document",
    recipient: "whoever holds the signed original",
    meaning: "What is on file is unsigned. Signed and proposed are different evidence.",
  },
  REQUEST_PRIMARY_EVIDENCE: {
    label: "request primary evidence",
    recipient: "the company or its administrator",
    meaning: "What is on file reports the event rather than being it.",
  },
  REQUEST_SUPPORT_FOR_CLASS: {
    label: "request support for the class held",
    recipient: "the portfolio company",
    meaning: "Evidence on file prices a different security class than the one the fund holds.",
  },
  RECORD_VALUATION_POLICY_DECISION: {
    label: "record a valuation policy decision",
    recipient: "the fund's valuation committee",
    meaning: "No letter goes out. A human owes a recorded judgement.",
  },
  DRAFT_MANAGEMENT_ASSESSMENT: {
    label: "draft a management assessment",
    recipient: "fund management",
    meaning: "R3 · the unchanged mark needs a written calibration before it can close.",
  },
  REQUEST_MANAGEMENT_BASIS_MEMO: {
    label: "request management's memo on the basis of the mark",
    recipient: "fund management",
    meaning:
      "Letter ¶2 · what the mark is BASED ON. Deliberately not the same request as R3's calibration assessment, which is ¶3(b) and asks whether a last round price remains representative at a later date. Different paragraphs, different documents, different questions.",
  },
};

export function actionGloss(code: string): ActionTerm {
  return (
    NEXT_ACTION[code] ?? {
      label: "no gloss is recorded for this action",
      recipient: "not stated by the policy",
      meaning: "The policy states this action and this display carries no gloss for it.",
    }
  );
}

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

/**
 * How far an extracted figure has got. A candidate is what an extractor
 * proposed, a canonical fact is the one the ledger relies on, and an approved
 * one carries a recorded human decision. Rendered because "a number appears in
 * a document" and "a number a person signed off" are different evidence, and a
 * bare state string on screen states neither.
 */
export const FACT_STATE: Record<FactState, Term> = {
  candidate: {
    label: "candidate",
    meaning: "Extracted and not yet adopted. Nothing relies on it.",
  },
  canonical: {
    label: "canonical",
    meaning: "The fact the ledger relies on for this field.",
  },
  approved: {
    label: "approved",
    meaning: "Canonical and carrying a recorded human decision.",
  },
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
