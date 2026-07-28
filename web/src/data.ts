import type { Approval, RequirementCode } from "./contracts";
import { FIXTURE_FUNDS, FIXTURE_HOLDING, FIXTURE_PACKET } from "./fixture";
import type {
  DecisionRequest,
  DocumentResponse,
  EvalsResponse,
  ExplainResponse,
  ExportResponse,
  FundsResponse,
  HoldingResponse,
  PacketDownload,
  PacketResponse,
  PassagesResponse,
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

const EVALS_KEYS = [
  "source",
  "measured_at",
  "corpus",
  "retrieval",
  "citations",
  "extraction",
  "validators",
  "by_holding",
  "not_measured",
];

/**
 * What the system has been measured to do, measured on request.
 *
 * NO FIXTURE BRANCH, and that is the whole point of the route. Every figure on
 * the evaluation page is a measurement OF A LEDGER; the bundled one-holding stub
 * would produce real-looking numbers about a corpus that is not the fund, which
 * is the failure `source` exists to prevent arriving somewhere `source` cannot
 * help. With no API configured this says so rather than answering.
 */
export async function loadEvals(): Promise<EvalsResponse> {
  if (API === "")
    throw new Error(
      "No API is configured. Every number on this page is a measurement of a ledger, and the bundled fixture is a one-holding demo stub — reporting its figures here would be reporting a measurement of something that is not the fund.",
    );
  return (await fetchJson(`${API}/evals`, EVALS_KEYS, "evals")) as EvalsResponse;
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
  if (!response.ok) throw new Error(refusalDetail(body, response.status, "this export"));
  assertKeys(body, EXPORT_KEYS, "export");
  return body as ExportResponse;
}

/**
 * A header the archive was supposed to carry, or a stated failure.
 *
 * `assertKeys` for a response with no body to inspect. A missing header would
 * otherwise reach the screen as an empty string beside a label, and a blank
 * where a packet id belongs reads as "this packet has no id" rather than "this
 * build is talking to an API that no longer sends one".
 */
function archiveHeader(response: Response, name: string): string {
  const value = response.headers.get(name);
  if (value === null)
    throw new Error(
      `the archive arrived without its ${name} header, so this page cannot say what was downloaded`,
    );
  return value;
}

/**
 * The name the API chose for the file, or the caller's fallback.
 *
 * The API builds it from ids that came in over the wire and strips everything
 * outside a safe set on the way, so it is the name to prefer. When the header
 * is absent or malformed the browser supplies its own rather than letting the
 * file save as `export.zip` — a downloads folder with four files called
 * `export.zip` is four packets nobody can tell apart.
 */
function attachmentName(disposition: string | null, fallback: string): string {
  const found = disposition === null ? null : /filename="([^"]+)"/.exec(disposition);
  return found?.[1] ?? fallback;
}

/**
 * Fetch one archive and everything the response says about it.
 *
 * A refusal is read out of the JSON body the API sends INSTEAD of the zip, and
 * rendered in the API's own words for the same reason every other refusal is:
 * the exporter names which citation would not resolve or which approved
 * position is unsupported, and that sentence is the deliverable. A download
 * that silently does not arrive, or that says "export failed", keeps the
 * failure and throws the finding away.
 */
async function fetchArchive(url: string, fallbackName: string): Promise<PacketDownload> {
  const response = await fetch(url);
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new Error(refusalDetail(body, response.status, "this export"));
  }
  return {
    filename: attachmentName(response.headers.get("content-disposition"), fallbackName),
    blob: await response.blob(),
    packet_id: archiveHeader(response, "x-packet-id"),
    manifest_hash: archiveHeader(response, "x-manifest-hash"),
    file_count: archiveHeader(response, "x-file-count"),
    withheld_file_count: archiveHeader(response, "x-withheld-file-count"),
    recorded_in_ledger: archiveHeader(response, "x-recorded-in-ledger") === "true",
  };
}

/**
 * Download the whole auditor packet for one fund-period.
 *
 * The packet has been the deliverable since SPEC §1 and until this it was only
 * ever written to the API host's disk — which on a free Render instance is
 * ephemeral and unreachable, so the thing the project exists to produce could
 * not be obtained by the person it is for.
 *
 * A separate function from `exportPacket`, not a replacement for it. Building
 * the packet on the host and reporting where it landed is still a real answer,
 * and it is the one that reports a refusal in full without the reader having to
 * open anything.
 */
export async function downloadPacket(fundId: string, periodId: string): Promise<PacketDownload> {
  if (API === "")
    throw new Error(
      "No API is configured, so this browser is showing the bundled fixture. There is no ledger to export a packet from.",
    );
  return fetchArchive(
    `${API}/funds/${fundId}/periods/${periodId}/export.zip`,
    `${fundId}-${periodId}.zip`,
  );
}

/**
 * Download one portfolio company's evidence out of that packet.
 *
 * The engagement letter closes by asking for the support "organized by
 * portfolio company", and the export has been organised that way from the
 * start; this is the half that lets one of those folders be taken away without
 * the other seven.
 *
 * The archive is the whole packet minus the other companies' source documents.
 * The gap report, the evidence index and the tables travel unmodified, because
 * a copy of them trimmed to one company would state fewer findings than the
 * packet found. The archive carries its own note saying exactly which files
 * were withheld.
 */
export async function downloadCompanyEvidence(
  fundId: string,
  periodId: string,
  holdingId: string,
): Promise<PacketDownload> {
  if (API === "")
    throw new Error(
      "No API is configured, so this browser is showing the bundled fixture. There is no ledger to export this company's evidence from.",
    );
  return fetchArchive(
    `${API}/funds/${fundId}/periods/${periodId}/companies/${holdingId}/export.zip`,
    `${fundId}-${periodId}-${holdingId}.zip`,
  );
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
 *
 * `subject` names what was refused, and it is a parameter because the exports
 * now use this too. The fallback sentence is the only place it shows, and it is
 * the sentence a reader gets when there is nothing better to tell them — so
 * "the ledger refused this decision" arriving over a failed packet download
 * would be this function inventing the one detail it exists to preserve.
 */
function refusalDetail(body: unknown, status: number, subject: string): string {
  const detail =
    typeof body === "object" && body !== null ? (body as { detail?: unknown }).detail : undefined;
  if (typeof detail === "string") return detail;
  if (detail !== undefined) return JSON.stringify(detail);
  return `the API refused ${subject} with status ${status} and stated no reason`;
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
  if (!response.ok) throw new Error(refusalDetail(body, response.status, "this decision"));
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

/**
 * Ask the corpus a question and get its own words back.
 *
 * No fixture fallback, deliberately, and it is the only loader here without
 * one. Every other read surface may honestly serve the bundled Dream stub and
 * say `source: "fixture"` beside it. A passage cannot work that way: it is a
 * quotation attributed to a named document at a page and a span, and a stub
 * quotation is the precise failure the citation machinery exists to prevent.
 * So this throws, and the pane renders the refusal.
 */
export async function findPassages(
  holdingId: string,
  on: string,
  requirement: RequirementCode,
  question: string,
): Promise<PassagesResponse> {
  if (API === "")
    throw new Error(
      "No API is configured, so this browser is showing the bundled fixture. There are no documents to search.",
    );
  const url =
    `${API}/holdings/${encodeURIComponent(holdingId)}/passages` +
    `?on=${encodeURIComponent(on)}&requirement=${encodeURIComponent(requirement)}` +
    (question.trim() === "" ? "" : `&q=${encodeURIComponent(question)}`);
  return (await fetchJson(
    url,
    ["outcome", "passages", "query"],
    "passage search",
  )) as PassagesResponse;
}

/**
 * This row, restated in plain English — or the reason there is no paragraph.
 *
 * A refusal is a 200 and a normal answer, so it is not thrown. The caller
 * renders `text` when the guard accepted the model's words and `refusal` when
 * it did not, and the structured row underneath is complete either way.
 */
export async function explainRow(
  holdingId: string,
  on: string,
  requirement: RequirementCode,
): Promise<ExplainResponse> {
  if (API === "")
    throw new Error(
      "No API is configured, so this browser is showing the bundled fixture. There is no row to restate.",
    );
  const url =
    `${API}/holdings/${encodeURIComponent(holdingId)}/explain` +
    `?on=${encodeURIComponent(on)}&requirement=${encodeURIComponent(requirement)}`;
  return (await fetchJson(url, ["outcome", "row"], "row restatement")) as ExplainResponse;
}
