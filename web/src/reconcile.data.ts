import type { ReconciliationResponse, ScorecardResponse } from "./reconcile.contracts";

/**
 * The fetch seam for the reconciliation report and the completeness scorecard.
 *
 * Deliberately no bundled fixture. `data.ts` carries one because the packet
 * routes have a hand-written Dream stub that the oracle checks; these two
 * screens do not, and inventing one would mean either hand-writing a scorecard
 * — six lines of derived counts nothing verifies, which is the failure this
 * project has already paid for twice — or copying `real_findings.json` into the
 * bundle, a second copy of the committed snapshot that can drift from it in
 * silence. So with no API to answer, these screens state the failure instead of
 * rendering numbers nobody can trace.
 */

const API = import.meta.env.VITE_API_BASE_URL ?? "";

/**
 * A cast is not a check. The API declares its shape on its side, but a renamed
 * or dropped field arrives here as `undefined` and renders as a blank cell that
 * reads like "nothing to report" — which on a reconciliation report means "the
 * books agree". So the top-level keys are asserted present and a drifted
 * response fails loudly.
 */
async function read<T>(path: string, required: string[], what: string): Promise<T> {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) throw new Error(`${what} request failed: ${response.status}`);
  const body: unknown = await response.json();
  const fields: Record<string, unknown> =
    typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
  const missing = required.filter((name) => !(name in fields));
  if (missing.length > 0) throw new Error(`${what} response is missing: ${missing.join(", ")}`);
  return body as T;
}

const RECONCILIATION_KEYS = [
  "source",
  "snapshot",
  "positions",
  "tranches",
  "fund_periods",
  "finding_count",
  "scopes",
];

const SCORECARD_KEYS = ["source", "periods"];

/** Where the fund's two workbooks disagree, already partitioned by audit scope. */
export async function loadReconciliation(): Promise<ReconciliationResponse> {
  return await read<ReconciliationResponse>(
    "/reconciliation",
    RECONCILIATION_KEYS,
    "reconciliation",
  );
}

/** One completeness line per packet-scope fund-period. */
export async function loadScorecard(): Promise<ScorecardResponse> {
  return await read<ScorecardResponse>("/scorecard", SCORECARD_KEYS, "scorecard");
}
