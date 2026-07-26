import { FIXTURE_FUNDS, FIXTURE_HOLDING, FIXTURE_PACKET } from "./fixture";
import type { FundsResponse, HoldingResponse, PacketResponse } from "./responses";

/**
 * The one seam between "where the data came from" and "what the screen does
 * with it". Everything downstream sees a response object and cannot tell whether
 * it was fetched or bundled — except by reading `source`, which every surface
 * displays, because a demo that has silently fallen back to the one-row fixture
 * is showing numbers nobody can trace.
 *
 * The packet and its totals now arrive in ONE response. They used to be two
 * requests with nothing tying them together, so a total from one period could be
 * rendered above rows from another and no field on either would contradict it.
 */

const API = import.meta.env.VITE_API_BASE_URL ?? "";

export function fixtureFunds(): FundsResponse {
  return FIXTURE_FUNDS;
}

export function fixturePacket(): PacketResponse {
  return FIXTURE_PACKET;
}

/**
 * The bundled fixture holds exactly one holding, so any other id is a 404 here
 * for the same reason it is a 404 at the API: answering with an empty evidence
 * list under a name the fixture does not have would report "no evidence for
 * Anthropic" when the truth is "no Anthropic".
 */
export function fixtureHolding(holdingId: string): HoldingResponse {
  if (holdingId !== FIXTURE_HOLDING.holding_id)
    throw new Error(`holding request failed: no ${holdingId} in the bundled fixture`);
  return FIXTURE_HOLDING;
}

/**
 * A cast is not a check. The API declares `extra="forbid"` on its side, but a
 * renamed or dropped field arrives here as `undefined` and renders as a blank
 * cell that reads like "nothing to report" — the exact failure mode this whole
 * project is arranged against. So the top-level keys are asserted present, and
 * a response that has drifted fails loudly instead of rendering emptily.
 */
function assertKeys(value: unknown, keys: string[], what: string): void {
  const record =
    typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
  const absent = keys.filter((k) => !(k in record));
  if (absent.length > 0) throw new Error(`${what} is missing: ${absent.join(", ")}`);
}

async function fetchJson(url: string, keys: string[], what: string): Promise<unknown> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${what} request failed: ${response.status}`);
  const body: unknown = await response.json();
  assertKeys(body, keys, what);
  return body;
}

const FUNDS_KEYS = ["source", "periods"];
const PACKET_KEYS = [
  "source",
  "fund_id",
  "period",
  "rows",
  "schema_version",
  "policy_version",
  "generated_at",
  "totals",
];
const HOLDING_KEYS = ["source", "holding_id", "company_name", "evidence"];

/** Every fund-period the API can packet. Never assumed to have any one length. */
export async function loadFunds(): Promise<FundsResponse> {
  if (API === "") return fixtureFunds();
  return (await fetchJson(`${API}/funds`, FUNDS_KEYS, "funds")) as FundsResponse;
}

export async function loadPacket(fundId: string, periodId: string): Promise<PacketResponse> {
  if (API === "") return fixturePacket();
  const url = `${API}/funds/${fundId}/periods/${periodId}/packet`;
  return (await fetchJson(url, PACKET_KEYS, "packet")) as PacketResponse;
}

/** One holding's claims, each with the passages it cites. */
export async function loadHolding(holdingId: string): Promise<HoldingResponse> {
  if (API === "") return fixtureHolding(holdingId);
  const url = `${API}/holdings/${holdingId}`;
  return (await fetchJson(url, HOLDING_KEYS, "holding")) as HoldingResponse;
}

/** What a surface has: nothing yet, the thing, or a stated reason it has neither. */
export type Async<T> =
  | { kind: "loading" }
  | { kind: "ready"; data: T }
  | { kind: "error"; detail: string };

/**
 * A rejection rendered as text. A thrown non-`Error` — an upstream that rejects
 * with a bare string — must still reach the screen as words, not as the empty
 * string a `.message` access would produce.
 */
export function failureDetail(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
