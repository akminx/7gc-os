import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { HoldingRow } from "./contracts";
import { FIXTURE_ROW } from "./fixture";
import type { Recomputation } from "./responses";
import { DISAGREEING_RECOMPUTATION, HOLDING_WITH_EVIDENCE, SWAY_ROW } from "./testdata";

/**
 * `VITE_API_BASE_URL` is read at module scope in the data seam, so each case
 * re-imports the component after stubbing the environment.
 */
async function mount(
  apiBase: string,
  rows: HoldingRow[],
  selected: string | null = null,
  recomputations: Record<string, Recomputation> | null = null,
) {
  vi.stubEnv("VITE_API_BASE_URL", apiBase);
  vi.resetModules();
  const { Company } = await import("./Company");
  return render(
    <Company
      fundId="fund_ii"
      measurementDate="2025-12-31"
      periodId="fund_ii_25q4"
      rows={rows}
      recomputations={recomputations}
      selected={selected}
      onSelect={() => {}}
    />,
  );
}

function serve(body: unknown): string[] {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      return { ok: true, status: 200, json: async () => body };
    }),
  );
  return calls;
}

beforeEach(() => {
  vi.unstubAllEnvs();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("Company", () => {
  it("asks the API for the selected holding's evidence and renders the passages", async () => {
    const calls = serve(HOLDING_WITH_EVIDENCE);
    await mount("https://api.example.com", [FIXTURE_ROW]);
    await waitFor(() => {
      expect(screen.getByText(/the Purchase Price shall be \$2\.50 per share/)).toBeDefined();
    });
    expect(calls).toEqual(["https://api.example.com/holdings/dream"]);
    expect(screen.getByText("characters 4821–4891")).toBeDefined();
  });

  /**
   * The workspace's figure must be the SELECTED holding's.
   *
   * `recomputations` is a map keyed by holding, and the company screen looks up
   * one entry from it. A lookup keyed on anything else — the first entry, a row
   * index, the previously selected id — would show Fluidstack's 3,500,000
   * discrepancy under Lucra's name, which is worse than showing nothing: it is
   * a specific, checkable, wrong finding about a named company.
   *
   * Two rows and two different derived amounts, so returning either one
   * unconditionally fails. `Dashboard.test.tsx` guards the same property on the
   * table; this guards it on the screen the walkthrough actually stops at.
   */
  it("shows the selected holding's own recomputation, never another row's", async () => {
    serve(HOLDING_WITH_EVIDENCE);
    const forDream: Recomputation = {
      ...DISAGREEING_RECOMPUTATION,
      holding_id: FIXTURE_ROW.holding_id,
      derived: { amount: "222.0000", currency: "USD" },
    };
    const forSway: Recomputation = {
      ...DISAGREEING_RECOMPUTATION,
      holding_id: SWAY_ROW.holding_id,
      derived: { amount: "999.0000", currency: "USD" },
    };
    const { container } = await mount(
      "https://api.example.com",
      [FIXTURE_ROW, SWAY_ROW],
      SWAY_ROW.holding_id,
      { [FIXTURE_ROW.holding_id]: forDream, [SWAY_ROW.holding_id]: forSway },
    );
    await waitFor(() => {
      expect(container.querySelector(".figure--recheck")).not.toBeNull();
    });
    const shown = container.querySelector(".figure--recheck .figure__amount")?.textContent;
    expect(shown).toBe("999.0000 USD");
    expect(shown).not.toBe("222.0000 USD");
  });

  it("says so when the packet carried no recomputation for this holding", async () => {
    serve(HOLDING_WITH_EVIDENCE);
    const { container } = await mount("https://api.example.com", [FIXTURE_ROW], null, {});
    await waitFor(() => {
      expect(container.querySelector(".figure--recheck")).not.toBeNull();
    });
    // A missing response, stated as one — not a finding that the mark could not
    // be checked, which is a different thing entirely.
    expect(container.querySelector(".figure--recheck")?.textContent).toContain(
      "not supplied by API",
    );
  });

  it("re-asks when the holding changes, so the panel is never the previous company's", async () => {
    const calls = serve(HOLDING_WITH_EVIDENCE);
    await mount("https://api.example.com", [FIXTURE_ROW, SWAY_ROW], "sway");
    await waitFor(() => {
      expect(calls).toEqual(["https://api.example.com/holdings/sway"]);
    });
  });

  it("offers every holding in the packet in the picker", async () => {
    serve(HOLDING_WITH_EVIDENCE);
    await mount("https://api.example.com", [FIXTURE_ROW, SWAY_ROW]);
    const options = [...screen.getAllByRole("option")].map((option) => option.textContent);
    expect(options).toEqual(["Dream", "Sway"]);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "sway" } });
    // `selected` is owned by the caller, so the picker reports the change and
    // does not act on it: this surface never decides what it is showing.
    expect(screen.getByText("Dream · dream")).toBeDefined();
  });

  it("shows the mark's own facts beneath the evidence", async () => {
    serve(HOLDING_WITH_EVIDENCE);
    await mount("https://api.example.com", [FIXTURE_ROW]);
    await waitFor(() => {
      expect(screen.getByText("The mark", { selector: "h2" })).toBeDefined();
    });
  });

  it("says the evidence is loading rather than showing an empty panel", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
    await mount("https://api.example.com", [FIXTURE_ROW]);
    expect(screen.getByText(/Loading the evidence for this holding/)).toBeDefined();
  });

  /**
   * A failed request and a holding with no evidence are opposite findings — one
   * says nothing is known, the other says something is known and it is nothing.
   * They must never render the same way.
   */
  it("distinguishes a failed evidence request from a finding of no evidence", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) })),
    );
    await mount("https://api.example.com", [FIXTURE_ROW]);
    await waitFor(() => {
      expect(screen.getByText(/Evidence request failed/)).toBeDefined();
    });
    expect(screen.getByText(/not a finding of no evidence/)).toBeDefined();
    expect(screen.queryByText(/No evidence in the corpus/)).toBeNull();
  });

  it("says a packet with no holdings has none, instead of rendering a blank workspace", async () => {
    await mount("", []);
    expect(screen.getByText("This packet contains no holdings.")).toBeDefined();
  });
});
