import type { RequirementCode } from "./contracts";

/**
 * The evidence trail, in the address bar.
 *
 * A partner who has found the sentence supporting a mark can currently send an
 * auditor *directions* to it — open the app, pick 25Q4, click Fluidstack, click
 * fair-value support, click the price. Every step is one a recipient can take
 * wrongly, and the passage is three clicks from the URL they were sent.
 *
 * So the whole path is in the location hash:
 *
 *     #/fund_ii/fund_ii_25q4/company/fund_ii_fluidstack/R2/claim%3A17
 *
 * The HASH and not the path, deliberately. The frontend is a static bundle on a
 * host with no rewrite rules configured, and a real route would 404 on reload —
 * a link that works when clicked from the app and breaks when pasted into a mail
 * is worse than no link at all, because only the sender ever sees it work.
 *
 * **The URL is the state, and this module never holds a copy of it.** Every
 * update re-reads the address bar, merges, and writes back. Two components own
 * different segments of the same path — `App` the fund-period, `Trail` the
 * requirement and the figure — and a module-level cache is how one of them
 * overwrites the other's segment with a value it read before the other moved.
 *
 * `replaceState`, not `pushState`: clicking through requirements is reading one
 * document, not navigating five pages, and a back button that walks the reader
 * back through their own clicks one at a time is worse than one that leaves the
 * app.
 */

export type Surface = "dashboard" | "company" | "gaps" | "evals";

const SURFACES: Surface[] = ["dashboard", "company", "gaps", "evals"];
const REQUIREMENTS: RequirementCode[] = ["R1", "R2", "R3", "R4", "R5"];

export interface Trail {
  fundId?: string;
  periodId?: string;
  surface?: Surface;
  holdingId?: string;
  requirement?: RequirementCode;
  /** `claimId:factId` — the trail's own figure key, percent-encoded in the URL. */
  fact?: string;
}

/**
 * Only what the URL actually says.
 *
 * A segment that is absent stays absent rather than becoming a default: a link
 * to a holding with no requirement in it means "open this company", and filling
 * in R1 here would make that link and a link explicitly to R1 indistinguishable
 * — including to the reader, who would have no way to tell which one they were
 * sent.
 */
export function readTrail(hash: string = window.location.hash): Trail {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const [fundId, periodId, surface, holdingId, requirement, fact] = parts;
  const trail: Trail = {};
  if (fundId !== undefined) trail.fundId = fundId;
  if (periodId !== undefined) trail.periodId = periodId;
  // Validated against the closed vocabularies rather than cast into them. A
  // hand-edited or truncated link must land somewhere real; a `surface` of
  // "compnay" rendering nothing at all is a blank page with no explanation.
  if (surface !== undefined && SURFACES.includes(surface as Surface))
    trail.surface = surface as Surface;
  if (holdingId !== undefined) trail.holdingId = holdingId;
  if (requirement !== undefined && REQUIREMENTS.includes(requirement as RequirementCode))
    trail.requirement = requirement as RequirementCode;
  if (fact !== undefined) trail.fact = fact;
  return trail;
}

/**
 * The hash for a trail, stopping at the first segment it does not carry.
 *
 * Positional, so a gap cannot be skipped over: a figure with no requirement
 * above it would land in the requirement's position and be read as one.
 */
export function formatTrail(trail: Trail): string {
  const ordered = [
    trail.fundId,
    trail.periodId,
    trail.surface,
    trail.holdingId,
    trail.requirement,
    trail.fact,
  ];
  const taken: string[] = [];
  for (const part of ordered) {
    if (part === undefined) break;
    taken.push(encodeURIComponent(part));
  }
  return taken.length === 0 ? "#/" : `#/${taken.join("/")}`;
}

/**
 * Merge a patch into whatever the address bar currently says.
 *
 * Re-read rather than remembered, for the reason in the module note above. The
 * write is `replaceState` so the history stack stays as long as the reader's
 * actual navigation rather than as long as their clicking.
 */
export function updateTrail(patch: Trail): void {
  const next = formatTrail({ ...readTrail(), ...patch });
  window.history.replaceState(null, "", next);
}

/** The absolute link to send, for the control that offers to copy it. */
export function trailHref(trail: Trail): string {
  const { origin, pathname, search } = window.location;
  return `${origin}${pathname}${search}${formatTrail(trail)}`;
}
