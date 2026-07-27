import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FIXTURE_FUNDS, FIXTURE_HOLDING, FIXTURE_PACKET } from "./fixture";
import type { FundsResponse } from "./responses";
import { TWO_ROW_PACKET } from "./testdata";

/**
 * `VITE_API_BASE_URL` is read at module scope in the data seam, so each case
 * re-imports the app after stubbing the environment. With no base configured
 * the app renders the bundled fixture, which is also how it behaves in a
 * preview deploy with no API attached.
 */
async function mount(apiBase: string) {
  vi.stubEnv("VITE_API_BASE_URL", apiBase);
  vi.resetModules();
  const { App } = await import("./App");
  return render(<App />);
}

interface Bodies {
  funds?: unknown;
  packet?: unknown;
}

/** Routes each request by URL, and records the order they arrived in. */
function serve(bodies: Bodies = {}): string[] {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      let body: unknown = bodies.packet ?? FIXTURE_PACKET;
      if (url.endsWith("/funds")) body = bodies.funds ?? FIXTURE_FUNDS;
      if (url.includes("/holdings/")) body = FIXTURE_HOLDING;
      return { ok: true, status: 200, json: async () => body };
    }),
  );
  return calls;
}

const THREE_PERIODS: FundsResponse = {
  source: "ledger",
  periods: [
    { fund_id: "fund_i", period_id: "fund_i_fy2024", label: "FY2024" },
    { fund_id: "fund_ii", period_id: "fund_ii_24q4", label: "24Q4" },
    { fund_id: "fund_ii", period_id: "fund_ii_25q4", label: "25Q4" },
  ],
};

beforeEach(() => {
  vi.unstubAllEnvs();
  // jsdom keeps ONE location per test file, so a case that navigated the app
  // leaves its trail in the hash and the next mount opens where the last one
  // finished. That is the right behaviour in a browser and the wrong starting
  // state for a test, so each case begins on a fresh address bar.
  window.location.hash = "";
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("App", () => {
  it("shows the cold-start note while the fund list is in flight", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
    await mount("https://api.example.com");
    expect(screen.getByText(/takes about 50 seconds to wake/)).toBeDefined();
  });

  it("surfaces a failed fund-list request instead of an empty screen", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("NetworkError");
      }),
    );
    await mount("https://api.example.com");
    await waitFor(() => {
      expect(screen.getByText(/Fund list failed: NetworkError/)).toBeDefined();
    });
  });

  it("surfaces a rejection that is not an Error too", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject("upstream said no")),
    );
    await mount("https://api.example.com");
    await waitFor(() => {
      expect(screen.getByText(/Fund list failed: upstream said no/)).toBeDefined();
    });
  });

  it("reports a packet failure separately from a fund-list failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/funds"))
          return { ok: true, status: 200, json: async () => FIXTURE_FUNDS };
        return { ok: false, status: 404, json: async () => ({}) };
      }),
    );
    await mount("https://api.example.com");
    await waitFor(() => {
      expect(screen.getByText(/Packet request failed: packet request failed: 404/)).toBeDefined();
    });
  });

  /**
   * The claim itself is unchanged; it is one hover away rather than three lines
   * under the masthead. What a partner reads first is the fund, not a note about
   * where the arithmetic happened.
   */
  it("states that the surface is read-only, and where the figures come from", async () => {
    const { container } = await mount("");
    await waitFor(() => {
      expect(screen.getByText(/Audit support, read-only/)).toBeDefined();
    });
    expect(container.querySelector(".masthead .why")?.getAttribute("title")).toMatch(
      /computes nothing/,
    );
  });

  /**
   * A demo that has silently fallen back to the one-holding fixture is showing
   * numbers nobody can trace. It has to be visible on screen, in the masthead,
   * before any figure is read.
   */
  it("says in the masthead which store answered", async () => {
    await mount("");
    await waitFor(() => {
      expect(screen.getAllByText(/source · fixture — not the fund/).length).toBeGreaterThan(0);
    });
  });

  it("lands on the dashboard", async () => {
    await mount("");
    // Matched on the heading, not on the text: the picker's own <option> reads
    // "fund_ii · FY2025 Q4" too, and waiting on that resolved before the packet
    // had arrived — a test that passed or failed on request timing.
    await waitFor(() => {
      expect(screen.getByText("fund_ii · FY2025 Q4", { selector: "h2" })).toBeDefined();
    });
    expect(screen.getByRole("button", { name: "Dashboard" }).className).toContain("tab--on");
  });

  it("moves between the three surfaces", async () => {
    await mount("");
    await waitFor(() => {
      expect(screen.getByText("Holdings")).toBeDefined();
    });
    screen.getByRole("button", { name: "Gap inventory" }).click();
    await waitFor(() => {
      expect(screen.getByText("Gap inventory", { selector: "h2" })).toBeDefined();
    });
    screen.getByRole("button", { name: "Company evidence" }).click();
    await waitFor(() => {
      expect(screen.getByText("The mark", { selector: "h2" })).toBeDefined();
    });
    screen.getByRole("button", { name: "Dashboard" }).click();
    await waitFor(() => {
      expect(screen.getByText("Holdings")).toBeDefined();
    });
  });

  it("opens the workspace on the company that was clicked", async () => {
    serve({ packet: TWO_ROW_PACKET });
    await mount("https://api.example.com");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Sway" })).toBeDefined();
    });
    screen.getByRole("button", { name: "Sway" }).click();
    await waitFor(() => {
      expect(screen.getByText("Sway · sway")).toBeDefined();
    });
  });
});

describe("the fund-period picker", () => {
  /**
   * The dashboard used to hard-code one fund and one period, so a screen built
   * to compare funds showed exactly one whatever the ledger held. The list now
   * comes from `GET /funds`, and its length is never assumed — the dev database
   * answers with about 140 entries today and six after it is reset.
   */
  it("lists every fund-period the API supplies, whatever the count", async () => {
    serve({ funds: THREE_PERIODS });
    await mount("https://api.example.com");
    await waitFor(() => {
      expect(screen.getByText("Fund · period")).toBeDefined();
    });
    const options = [...screen.getAllByRole("option")].map((option) => option.textContent);
    expect(options).toEqual(["fund_i · FY2024", "fund_ii · 24Q4", "fund_ii · 25Q4"]);
  });

  it("requests the packet for the period that was chosen", async () => {
    const calls = serve({ funds: THREE_PERIODS });
    await mount("https://api.example.com");
    await waitFor(() => {
      expect(calls).toEqual([
        "https://api.example.com/funds",
        "https://api.example.com/funds/fund_i/periods/fund_i_fy2024/packet",
      ]);
    });
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "fund_ii/fund_ii_25q4" },
    });
    await waitFor(() => {
      expect(calls).toContain("https://api.example.com/funds/fund_ii/periods/fund_ii_25q4/packet");
    });
  });

  it("says an empty fund list is an empty ledger, not an empty screen", async () => {
    serve({ funds: { source: "ledger", periods: [] } });
    await mount("https://api.example.com");
    await waitFor(() => {
      expect(screen.getByText(/lists no fund-period that a packet can be built for/)).toBeDefined();
    });
    expect(screen.queryByText("Fund · period")).toBeNull();
  });
});
