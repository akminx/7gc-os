import type {
  Claim,
  DecisionStatus,
  DecisionType,
  Packet,
  PacketTotals,
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
  facts: SourceFact[];
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
