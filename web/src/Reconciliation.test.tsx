import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Reconciliation } from "./Reconciliation";
import type { Finding, ReconciliationResponse } from "./reconcile.contracts";

/**
 * The report's job is to keep two pairs of things apart: packet-scope findings
 * from lineage-only ones, and what a workbook states from what its own cells
 * compute. Every case here is about one of those two separations, or about the
 * screen refusing to derive a figure it was not given.
 */

afterEach(cleanup);

/**
 * The sharpest finding in the real set, verbatim from
 * `ingest/trackers/real_findings.json`: one column of the fund's own workbook
 * whose four cells sum to 6,000,000 under a total row that states 4,000,000.
 */
const SHARPEST: Finding = {
  kind: "stated_total_disagrees_with_cells",
  subject: "Fund II Holdings by Quarter · 23Q4",
  scope: "packet",
  stated: "4000000",
  computed: "6000000",
  delta_computed_minus_stated: "2000000",
  detail:
    "the column sums to 6,000,000 across 4 positions (Because Market, Moonfare, Sway, Jackpocket) but the sheet states 4,000,000",
};

const LINEAGE: Finding = {
  kind: "mark_at_cost_disagrees_with_purchase_prices",
  subject: "Fluidstack · 25Q2",
  scope: "lineage_only",
  stated: "2500000",
  computed: "3000000",
  delta_computed_minus_stated: "500000",
  detail: "carried at 2,500,000, which equals the cost of the lots held at this date",
};

/** A finding that states no figures at all — a gap in the books, not a delta. */
const NO_FIGURES: Finding = {
  kind: "no_stated_total_to_check",
  subject: "Fund I · FY2023",
  scope: "lineage_only",
  stated: null,
  computed: null,
  delta_computed_minus_stated: null,
  detail: "5 positions were read but no stated total was found to check them against",
};

const UNSCOPED: Finding = {
  kind: "cost_total_disagrees_with_cells",
  subject: "Fund II Holdings by Quarter · cost basis",
  scope: "unscoped",
  stated: "14000000",
  computed: "16000000",
  delta_computed_minus_stated: "2000000",
  detail: "the column sums to 16,000,000 but the sheet states 14,000,000",
};

const REPORT: ReconciliationResponse = {
  source: "tracker_snapshot",
  snapshot: "ingest/trackers/real_findings.json",
  positions: 14,
  tranches: 18,
  fund_periods: 12,
  finding_count: 4,
  scopes: [
    {
      scope: "packet",
      finding_count: 1,
      by_kind: [{ kind: "stated_total_disagrees_with_cells", count: 1 }],
      findings: [SHARPEST],
    },
    {
      scope: "lineage_only",
      finding_count: 2,
      by_kind: [
        { kind: "mark_at_cost_disagrees_with_purchase_prices", count: 1 },
        { kind: "no_stated_total_to_check", count: 1 },
      ],
      findings: [LINEAGE, NO_FIGURES],
    },
    {
      scope: "unscoped",
      finding_count: 1,
      by_kind: [{ kind: "cost_total_disagrees_with_cells", count: 1 }],
      findings: [UNSCOPED],
    },
  ],
};

function show(report: ReconciliationResponse = REPORT) {
  return render(<Reconciliation report={report} />);
}

/** Every `.section`, keyed by its heading, so a finding can be pinned to one. */
function sections(container: HTMLElement): Record<string, HTMLElement> {
  const found: Record<string, HTMLElement> = {};
  for (const section of container.querySelectorAll<HTMLElement>(".section")) {
    found[section.querySelector("h2")?.textContent ?? ""] = section;
  }
  return found;
}

describe("audit scope", () => {
  it("counts each scope in its own box and never adds them into one headline", () => {
    const { container } = show();
    const headline = [...container.querySelectorAll(".triptych")][0];
    const boxes = [...(headline?.querySelectorAll(".figure") ?? [])].map((box) => ({
      caption: box.querySelector(".figure__caption")?.textContent,
      count: box.querySelector(".figure__amount")?.textContent,
    }));
    expect(boxes).toEqual([
      { caption: "packet scope", count: "1" },
      { caption: "lineage only", count: "2" },
      { caption: "no measurement date", count: "1" },
    ]);
    expect(screen.getByText(/interchangeable and are never added into one headline/)).toBeDefined();
  });

  /**
   * The overall count is 4 here while the packet count is 1. It is rendered
   * only in the metadata, under a label that says what it counts, because a
   * partner reading a headline "4" would be reading three different audit
   * questions as one number.
   */
  it("keeps the overall finding count out of the headline and labels what it counts", () => {
    const { container } = show();
    const meta = [...container.querySelectorAll(".section .meta > div")].map((item) => ({
      label: item.querySelector("dt")?.textContent,
      value: item.querySelector("dd")?.textContent,
    }));
    expect(meta).toContainEqual({ label: "findings in total", value: "4" });
    expect(meta).toContainEqual({ label: "positions read", value: "14" });
    expect(meta).toContainEqual({ label: "fund-periods read", value: "12" });
  });

  it("renders a lineage-only finding in its own section and never in the packet one", () => {
    const { container } = show();
    const byHeading = sections(container);
    const packet = byHeading["Findings · packet scope"];
    const lineage = byHeading["Findings · lineage only"];
    expect(packet?.textContent).toContain(SHARPEST.subject);
    expect(packet?.textContent).not.toContain(LINEAGE.subject);
    expect(lineage?.textContent).toContain(LINEAGE.subject);
    expect(lineage?.textContent).not.toContain(SHARPEST.subject);
  });

  it("gives the unscoped finding its own section rather than filing it under a date", () => {
    const { container } = show();
    const unscoped = sections(container)["Findings · no measurement date"];
    expect(unscoped?.textContent).toContain(UNSCOPED.subject);
    expect(unscoped?.querySelector(".note")?.textContent).toContain(
      "Filing it under a date would assert something the workbook does not say",
    );
  });

  /**
   * A section that disappears when it holds nothing is indistinguishable from a
   * section nobody built — and on a reconciliation report, a missing heading
   * reads as agreement.
   */
  it("renders a scope that found nothing, with its zero stated", () => {
    const empty: ReconciliationResponse = {
      ...REPORT,
      scopes: [{ scope: "packet", finding_count: 0, by_kind: [], findings: [] }],
    };
    const { container } = show(empty);
    expect(sections(container)["Findings · packet scope"]).toBeDefined();
    expect(screen.getByText(/found nothing in this scope. That is a result/)).toBeDefined();
  });
});

describe("stated against computed", () => {
  it("shows both figures and the delta side by side, each under its own caption", () => {
    const { container } = show();
    const card = container.querySelector(".gap");
    const figures = [...(card?.querySelectorAll(".figure") ?? [])].map((figure) => ({
      caption: figure.querySelector(".figure__caption")?.textContent,
      amount: figure.querySelector(".figure__amount")?.textContent,
    }));
    expect(figures).toEqual([
      { caption: "stated in the workbook", amount: "4,000,000" },
      { caption: "computed from the workbook's own figures", amount: "6,000,000" },
      { caption: "delta · computed − stated", amount: "2,000,000" },
    ]);
  });

  it("renders the reconciler's own sentence beside the figures", () => {
    show();
    expect(screen.getByText(SHARPEST.detail)).toBeDefined();
  });

  it("renders the finding kind verbatim as the code it is", () => {
    const { container } = show();
    const kinds = [...container.querySelectorAll(".gap-kind")].map((code) => code.textContent);
    expect(kinds).toEqual([
      "stated_total_disagrees_with_cells",
      "mark_at_cost_disagrees_with_purchase_prices",
      "no_stated_total_to_check",
      "cost_total_disagrees_with_cells",
    ]);
  });

  it("says a figure is absent instead of leaving the box blank", () => {
    const { container } = show();
    const cards = [...container.querySelectorAll(".gap")];
    const withoutFigures = cards.find((card) => card.textContent?.includes(NO_FIGURES.subject));
    const amounts = [...(withoutFigures?.querySelectorAll(".figure__amount") ?? [])].map(
      (amount) => amount.textContent,
    );
    expect(amounts).toEqual(["none stated", "none stated", "none stated"]);
  });

  it("breaks each scope down by kind, with the API's counts", () => {
    const { container } = show();
    const lineage = sections(container)["Findings · lineage only"];
    const codes = [...(lineage?.querySelectorAll(".codes code") ?? [])].map(
      (code) => code.textContent,
    );
    expect(codes).toEqual([
      "mark_at_cost_disagrees_with_purchase_prices · 1",
      "no_stated_total_to_check · 1",
    ]);
  });

  it("names the committed snapshot it read, rather than implying a live workbook", () => {
    show();
    expect(screen.getByText("source · committed tracker snapshot")).toBeDefined();
    expect(screen.getByText("ingest/trackers/real_findings.json")).toBeDefined();
  });
});

/**
 * The fetch seam. `VITE_API_BASE_URL` is read at module scope, so each case
 * re-imports the module after stubbing the environment.
 */
async function seam(apiBase: string) {
  vi.stubEnv("VITE_API_BASE_URL", apiBase);
  vi.resetModules();
  return await import("./reconcile.data");
}

function answer(body: unknown, ok = true): string[] {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urls.push(url);
      return { ok, status: ok ? 200 : 503, json: async () => body };
    }),
  );
  return urls;
}

beforeEach(() => {
  vi.unstubAllEnvs();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("the fetch seam", () => {
  it("asks the configured API for each report, and returns what it answered", async () => {
    const urls = answer({ ...REPORT, periods: [] });
    const { loadReconciliation, loadScorecard } = await seam("https://api.example");
    await expect(loadReconciliation()).resolves.toMatchObject({ finding_count: 4 });
    await loadScorecard();
    expect(urls).toEqual(["https://api.example/reconciliation", "https://api.example/scorecard"]);
  });

  /**
   * A cast is not a check. A dropped field arrives as `undefined` and renders as
   * a blank, and a blank on a reconciliation report reads as "the books agree" —
   * so a drifted response fails loudly instead.
   */
  it("refuses a response that has lost a field rather than rendering it empty", async () => {
    answer({ source: "tracker_snapshot", scopes: [] });
    const { loadReconciliation } = await seam("https://api.example");
    await expect(loadReconciliation()).rejects.toThrow(
      /reconciliation response is missing: snapshot, positions, tranches, fund_periods, finding_count/,
    );
  });

  it("reports a failed request as its status rather than as an empty report", async () => {
    answer(null, false);
    const { loadScorecard } = await seam("https://api.example");
    await expect(loadScorecard()).rejects.toThrow(/scorecard request failed: 503/);
  });
});
