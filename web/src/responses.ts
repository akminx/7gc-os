import type { Citation, Claim, Packet, PacketTotals } from "./contracts";

/**
 * What the four read ROUTES return, as opposed to what the models contain.
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
 * A claim with the passages it cites. `citations` is added by the route around
 * `Claim`; it is not a field of the model.
 */
export interface EvidenceClaim extends Claim {
  citations: Citation[];
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
