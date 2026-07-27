import type {
  Claim,
  DecisionStatus,
  DecisionType,
  Money,
  Packet,
  PacketTotals,
  RequirementCode,
  SourceFact,
} from "./contracts";

/**
 * What the ROUTES return, as opposed to what the models contain.
 *
 * `contracts.ts` mirrors `packages/contracts/models.py`. This file mirrors
 * `api/routes.py` and `api/serialize.py` — the envelope each route wraps around
 * a model, which is a different thing and drifts for different reasons. Keeping
 * them in one file made "is this field on the model or added by the route?" a
 * question you had to read Python to answer, and `tests/test_web_contracts.py`
 * checks the two halves against two different Python artefacts.
 */

/**
 * Which store answered.
 *
 * `fixture` means the API found no DSN and served the one-row Dream stub. That
 * is a legitimate state — the app must render something honest on a machine with
 * no database — but it is NOT the fund, and the difference between a 25,648,515
 * eight-holding ledger and a 5,000,000 one-holding stub is invisible on screen
 * unless the screen says so. Every surface displays this.
 */
export type Source = "ledger" | "fixture";

/** One fund-period the API can produce a packet for. */
export interface FundPeriod {
  fund_id: string;
  period_id: string;
  label: string;
}

/**
 * `GET /funds`. The dashboard used to hard-code `fund_ii` / `f2_25q4` because no
 * route listed the alternatives, which made a dual-fund screen single-fund in
 * practice. The list is whatever the API returns and is never assumed to have
 * one entry, six, or any other length.
 */
export interface FundsResponse {
  source: Source;
  periods: FundPeriod[];
}

/**
 * `GET /funds/{fund}/periods/{period}/packet`.
 *
 * The totals arrive INSIDE the packet. They used to be a second request, and
 * nothing tied the two responses together — a packet from one period could be
 * rendered under a total from another and no field on either said so.
 */
export interface PacketResponse extends Packet {
  source: Source;
  totals: PacketTotals;
  /**
   * SPEC §8's V2 over the same ledger, keyed by holding — what the cited
   * evidence independently derives for each mark.
   *
   * BESIDE the rows, not inside them, because it is a second opinion about a
   * row rather than a property of one. Folding it into `HoldingRow` would put a
   * derived figure where the reported ones live, and that collapse is exactly
   * what the label exists to prevent: "validated: 2,500,000" is a claim this
   * system has not earned, while "derived 2,500,000 against a reported
   * 6,000,000" is a finding.
   *
   * `null` when no derivation ran at all — the fixture branch has no ledger to
   * derive from. That is not the same as an empty object, which would mean the
   * derivation ran and found nothing to say about any row.
   */
  recomputations: Record<string, Recomputation> | null;
}

/**
 * One class of shares, priced by its OWN class (INV-17).
 *
 * Per class rather than one total because that is the granularity at which the
 * finding is legible: Fluidstack is 100,000 Series A at $10.00 plus 100,000
 * Series A-2 at $15.00, and the reported 6,000,000 is 200,000 shares at the
 * $30.00 Series B price applied to every class. One number hides which half is
 * wrong.
 */
export interface RecomputedClass {
  lot_id: string;
  security_class: string;
  shares: number;
  price_per_share: string;
  amount: Money;
  /** The price came from a class the fund does not hold at this date. */
  cross_class: boolean;
}

/**
 * What the cited evidence derives for one mark, against what was reported.
 *
 * Computed on read and stored nowhere. `mark.validated_amount` is a stored
 * column, and SPEC §6.3 binds an approval to `(mark_revision,
 * evidence_set_hash, policy_version)` precisely so an approved total cannot
 * follow a moving figure — so a read-time derivation written into that column
 * would reopen the question the binding exists to close.
 *
 * `difference` arrives computed, because §5.3 forbids the browser subtracting
 * two canonical figures. It is `null` and never zero when either side is
 * absent: the distance between a figure that exists and one that does not is
 * not nothing.
 */
export interface Recomputation {
  holding_id: string;
  /** SPEC §8's six-value vocabulary, unordered. Glossed by `outcomeGloss`. */
  outcome: string;
  /** HOW the figure was reached, or the named reason there is none. */
  reason: string;
  derived: Money | null;
  reported: Money | null;
  difference: Money | null;
  evidence_claim_ids: string[];
  per_class: RecomputedClass[];
  policy_version: string;
}

/** `GET /funds/{fund}/periods/{period}/totals` — the same totals, alone. */
export interface TotalsResponse extends PacketTotals {
  source: Source;
}

/**
 * A claim with the labelled figures extracted from it. `facts` is added by the
 * route around `Claim`; it is not a field of the model.
 *
 * Facts, not a detached list of quotes. SPEC §6 models the chain as
 * `claim → source_fact → citation`, and sending only its two ends leaves an
 * auditor with passages and no way to say which figure each one supports. Every
 * fact names the field it fills, the value as the document states it, and the
 * one passage that states it.
 */
export interface EvidenceClaim extends Claim {
  facts: EvidenceFact[];
}

/**
 * One extracted figure, with the client's requests it answers.
 *
 * `answers_requirements` is added by `api/serialize.py`; it is not a field of
 * `SourceFact`. The ledger binds a CLAIM to a requirement, never a FIGURE, so
 * Fluidstack's Series A purchase agreement — legitimately relied upon for both
 * existence and fair value — rendered all twelve of its figures under both, and
 * clicking R1 then R2 showed the same window twice.
 *
 * The judgement is the API's and stays the API's. `scripts/check-web-arch.mjs`
 * refuses a browser that derives what the API owns, and it is right to: a
 * component deciding `fund_shares` is about existence would be writing evidence
 * policy in TypeScript. This array is read, grouped and labelled here, never
 * computed here.
 *
 * An empty array is a declaration, not a lookup that failed. The API raises on
 * a field name nobody has ruled on rather than returning one, so the empty case
 * always means "reviewed, and it answers none of the four requests" — which is
 * why the trail shows those figures under the document rather than dropping
 * them.
 */
export interface EvidenceFact extends SourceFact {
  answers_requirements: RequirementCode[];
  /**
   * How directly this figure answers each request it answers. Lower leads.
   *
   * The second half of the same judgement `answers_requirements` carries, and it
   * is the API's for the same reason: which of ten relevant figures an auditor
   * should be shown FIRST is a statement about evidence, not a display
   * preference. Fluidstack's Series A agreement answers existence and cost with
   * ten figures, and only one of them answers "what did the fund pay".
   *
   * The browser orders by this and never computes it — ordering a display is the
   * permitted half of §5.3. Keyed only by the requests the figure answers, so a
   * rank cannot be read for a request it has nothing to do with.
   */
  answer_rank: Partial<Record<RequirementCode, number>>;
}

/**
 * `GET /holdings/{holding_id}` — the evidence surface's whole input.
 *
 * `evidence` is frequently EMPTY, and that is an answer rather than a missing
 * one: for most of this fund the corpus contains no document that states the
 * mark. A screen that renders an empty list as a blank panel reports the true
 * answer as an absence of information, which are opposite claims.
 */
export interface HoldingResponse {
  source: Source;
  holding_id: string;
  company_name: string;
  evidence: EvidenceClaim[];
}

/**
 * `GET /documents/{document_version_id}` — the text a citation points into.
 *
 * The whole canonical text, not a window around the span. A citation is a quote
 * plus `[span_start, span_end)`, and `0008_citations_resolve.sql` enforces that
 * `substring(canonical_text, span)` equals the quote — a constraint nobody can
 * check from a screen that shows only the quote. With the text here the reader
 * sees the passage in its surroundings and the offsets stop being debug output.
 *
 * `extractor` travels because offsets are only meaningful against a named
 * extraction: the same PDF through two extractors gives two canonical texts and
 * therefore two different spans (SPEC §8).
 *
 * `text_length` is supplied rather than measured, so a screen can say a span
 * falls outside the document without taking `.length` of the text and treating
 * the result as a figure.
 */
export interface DocumentResponse {
  source: Source;
  document_version_id: string;
  filename: string;
  extractor: string;
  text_hash: string;
  page_count: number;
  text_length: number;
  text: string;
}

/**
 * `GET /funds/{fund}/periods/{period}/export` — what the exporter wrote.
 *
 * A GET that writes, which is stated rather than hidden. It writes no LEDGER
 * row: `recorded_in_ledger` is on the wire and is false, because "a packet was
 * generated" and "a packet version was registered" are different facts and a
 * screen that reported one as the other would be claiming a record exists.
 *
 * `file_count` is the API's count. `files.length` would agree with it today and
 * is an aggregate over rows either way (SPEC §5.3).
 */
export interface ExportResponse {
  source: Source;
  fund_id: string;
  period_id: string;
  packet_id: string;
  root: string;
  manifest_hash: string;
  schema_version: string;
  policy_version: string;
  file_count: number;
  files: string[];
  recorded_in_ledger: boolean;
}

/**
 * `GET .../export.zip` — an archive, and what the response says about it.
 *
 * Not a JSON envelope. The body is the zip itself, so everything a screen can
 * report about a download it has just handed to the operating system arrives in
 * headers, and this is the browser's declaration of them. A download that
 * reports nothing is a file the reader has to take on trust: they cannot see
 * inside it from the page, and "a packet arrived" is not the same fact as
 * "packet pkx_… arrived, carrying 30 of the manifest's 30 files".
 *
 * `file_count` and `withheld_file_count` stay STRINGS. They are counts the API
 * performed, and parsing them into numbers here would be the browser turning a
 * supplied figure into one it owns — which is the line `Number()` is banned
 * across this directory to keep. They add up to the manifest's entry count, so
 * a reader can check the archive against the manifest inside it.
 *
 * `recorded_in_ledger` is the sentence the JSON export route carries in its
 * body, on every download: generating a packet is not registering one.
 *
 * `filename` and `blob` are the two fields with no header behind them —
 * the first is read out of `Content-Disposition`, the second is the body. The
 * rest are checked against the headers the route actually sets, in
 * `tests/test_web_contracts.py`.
 */
export interface PacketDownload {
  filename: string;
  blob: Blob;
  packet_id: string;
  manifest_hash: string;
  file_count: string;
  withheld_file_count: string;
  recorded_in_ledger: boolean;
}

/**
 * `POST /decisions` — the one write the application accepts.
 *
 * SPEC §6.3 · four typed decisions, none implying another, so `decision_type`
 * is required and has no default: a UI action names what it is deciding. The
 * subject is ONE field whose meaning that type fixes (a mark id for a valuation
 * or a management assessment, a source fact for a transcription, a packet
 * version for a packet approval), so a caller cannot name two subjects and
 * leave the API to guess which machine it meant.
 *
 * `reason` is required by the API when `status` is `rejected` — a rejection
 * with no stated reason records that a human said no and nothing about what
 * would change the answer. The response is an `Approval`, the same shape a
 * packet row already carries.
 */
export interface DecisionRequest {
  decision_type: DecisionType;
  status: DecisionStatus;
  subject_id: string;
  policy_version: string | null;
  reason: string | null;
}

/**
 * `GET /evals` — what this system has been measured to do, measured on request.
 *
 * Every number arrives computed. None is transcribed: the figures in the
 * handoff's table came from agent reports and triage files, and typing one into
 * the page would make it a claim about a run nobody can reproduce — the same
 * defect as a hand-maintained derived value, which this project has already
 * failed at twice.
 *
 * Rates arrive as a numerator and a denominator, never as a percentage. A count
 * is auditable; a percentage is a conclusion, and §5.3 refuses a browser that
 * divides one count by another. Where a mean is the readable form — candidates
 * per case — the API sends it WITH its two counts.
 */
export interface EvalsResponse {
  source: Source;
  measured_at: string;
  corpus: CorpusCounts;
  retrieval: RetrievalMeasurement;
  citations: CitationCensus;
  extraction: ExtractionMeasurement;
  validators: ValidatorCensus;
  by_holding: HoldingMeasurement[];
  /** What this page does NOT measure, and where each gap IS measured. */
  not_measured: BlindSpot[];
}

export interface CorpusCounts {
  holdings: number;
  companies: number;
  documents: number;
  claims: number;
  facts: number;
  packet_periods: number;
}

/**
 * One cutoff, as counts.
 *
 * `found_some_relied_on` and `found_every_relied_on` are different questions and
 * neither is "recall" on its own: one document out of two relied upon is a hit
 * for the first and a miss for the second, and an auditor asking "did you find
 * the support" means the second.
 */
export interface RecallAtK {
  k: number;
  cases: number;
  found_some_relied_on: number;
  found_every_relied_on: number;
  candidate_documents: number;
  mean_candidates_per_case: number;
}

export interface RetrievalMiss {
  scope: string;
  k: number;
  holding_id: string;
  company_name: string;
  requirement: RequirementCode;
  measurement_date: string;
  relied_on: string[];
  retrieved: string[];
}

export interface RetrievalMeasurement {
  gold_cases: number;
  retrievals_run: number;
  k_reported: number[];
  /** Keyed `k1` / `k3` / `k5`; absent keys are handled, never assumed. */
  scoped: Record<string, RecallAtK | undefined>;
  blind: Record<string, RecallAtK | undefined>;
  misses: RetrievalMiss[];
}

export interface CitationCensus {
  total: number;
  resolving: number;
  failures: {
    fact_id: number;
    claim_id: string;
    field_name: string;
    document_version_id: string;
    /** `[start, end)` — the auditor's own unit, and the one the passage pane shows. */
    chars: [number, number];
  }[];
}

/**
 * The recorded model call, replayed. Never a live one — CI has no key and must
 * not need one, and a page that called a model would report a different number
 * every time it was opened.
 *
 * `measured` is false when the recording cannot be re-bound, and `why` says so.
 * That is not the same as a model that proposed nothing.
 */
export interface ExtractionMeasurement {
  measured: boolean;
  why?: string;
  document?: string;
  model?: string;
  provider?: string;
  replayed_from_recording?: boolean;
  proposed?: number;
  accepted?: number;
  accepted_fields?: string[];
  refused?: { field_name: string; value_text: string; reason: string }[];
}

export interface ValidatorCensus {
  holding_dates: number;
  /** SPEC §8's six outcomes, counted. Never reduced to a pass rate. */
  outcomes: Record<string, number | undefined>;
  disagreements: {
    holding_id: string;
    company_name: string;
    measurement_date: string;
    reported: Money;
    derived: Money;
    difference: Money;
    reason: string;
  }[];
}

export interface HoldingMeasurement {
  holding_id: string;
  company_name: string;
  documents: number;
  claims: number;
  facts: number;
  facts_with_a_failing_citation: number;
  packet_appearances: number;
  requirements_applicable: number;
  requirements_sufficient: number;
  recomputation_outcomes: Record<string, number | undefined>;
}

export interface BlindSpot {
  what: string;
  why: string;
  measured_by: string;
}
