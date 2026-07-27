import type { Approval } from "./contracts";
import { FIXTURE_FUNDS, FIXTURE_HOLDING, FIXTURE_PACKET } from "./fixture";
import type {
  DecisionRequest,
  DocumentResponse,
  ExportResponse,
  FundsResponse,
  HoldingResponse,
  PacketResponse,
} from "./responses";

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

const DOCUMENT_KEYS = [
  "source",
  "document_version_id",
  "filename",
  "extractor",
  "text_hash",
  "page_count",
  "text_length",
  "text",
];
const EXPORT_KEYS = [
  "source",
  "fund_id",
  "period_id",
  "packet_id",
  "root",
  "manifest_hash",
  "file_count",
  "files",
  "recorded_in_ledger",
];

/**
 * The text one citation points into.
 *
 * There is no fixture branch. `data.ts` falls back to the bundled Dream stub for
 * the packet routes because a hand-written packet is checked by the oracle; no
 * document text is bundled, and inventing one would put a passage on screen that
 * an auditor could not find in any stored document — which is the single thing
 * this surface exists not to do. With no API configured the request states that
 * rather than answering with prose nobody can trace.
 */
export async function loadDocument(documentVersionId: string): Promise<DocumentResponse> {
  if (API === "")
    throw new Error(
      "No API is configured, so this browser is showing the bundled fixture, which carries no document text. The passage below is the stored quote alone.",
    );
  const url = `${API}/documents/${documentVersionId}`;
  return (await fetchJson(url, DOCUMENT_KEYS, "document")) as DocumentResponse;
}

/**
 * Generate the auditor packet for one fund-period.
 *
 * A GET, because SPEC §3.1 keeps the public surface read-only and what it is
 * read-only about is the LEDGER: the exporter records nothing and supersedes
 * nothing. What it writes is a build artefact on the API host, which is why the
 * response says where it landed and says that no ledger row was created.
 *
 * The API's refusal is rendered verbatim for the same reason a decision refusal
 * is: `export_packet` refuses a packet whose citation does not resolve or whose
 * approved position is unsupported, and names which one. "Export failed" throws
 * away the finding and keeps the failure.
 */
export async function exportPacket(fundId: string, periodId: string): Promise<ExportResponse> {
  if (API === "")
    throw new Error(
      "No API is configured, so this browser is showing the bundled fixture. There is no ledger to export a packet from.",
    );
  const response = await fetch(`${API}/funds/${fundId}/periods/${periodId}/export`);
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(refusalDetail(body, response.status));
  assertKeys(body, EXPORT_KEYS, "export");
  return body as ExportResponse;
}

/**
 * SPEC §3.1 · who may record a decision here, and therefore whether this build
 * offers the control at all.
 *
 * Empty is the public deployment, and empty is the default — the read-only
 * surface renders exactly what it rendered before, with no approve or reject
 * anywhere in the tree. A non-empty list is the private demo, where §3.1 says
 * decisions are made by named actors.
 *
 * Empty too when no API is configured, whatever the build declares: the read
 * surfaces may honestly fall back to the bundled Dream fixture, but a decision
 * has nothing to fall back to, and a button that cannot record anything is
 * worse than no button. The API refuses the same request for the same reason —
 * this is the browser declining to ask, not the browser deciding.
 */
export function namedActors(): string[] {
  if (API === "") return [];
  const declared: string = import.meta.env.VITE_DECISION_ACTORS ?? "";
  return declared
    .split(",")
    .map((name) => name.trim())
    .filter((name) => name !== "");
}

/**
 * The API's own sentence about why it refused, or a statement that it sent none.
 *
 * This is the load-bearing half of the whole write path. When the ledger blocks
 * a valuation approval — Anthropic's $8,000,000 resting on a press article — the
 * refusal text names the invariant, the trigger and the requirement that is
 * short. Discarding it and showing a status code would turn the one moment this
 * product exists for into "something went wrong".
 */
function refusalDetail(body: unknown, status: number): string {
  const detail =
    typeof body === "object" && body !== null ? (body as { detail?: unknown }).detail : undefined;
  if (typeof detail === "string") return detail;
  if (detail !== undefined) return JSON.stringify(detail);
  return `the ledger refused this decision with status ${status} and stated no reason`;
}

/**
 * Record one typed decision. SPEC §6.3 · the caller names the decision type.
 *
 * Never optimistic: nothing is reported as recorded until the API says the row
 * committed, because the prerequisites are enforced by the database and a
 * browser that assumed success would show an approval that does not exist.
 */
export async function recordDecision(request: DecisionRequest, actorId: string): Promise<Approval> {
  if (API === "")
    throw new Error(
      "No API is configured, so this browser is showing the bundled fixture. A decision recorded against a fixture exists nowhere.",
    );
  const response = await fetch(`${API}/decisions`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-actor-id": actorId },
    body: JSON.stringify(request),
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(refusalDetail(body, response.status));
  return body as Approval;
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
