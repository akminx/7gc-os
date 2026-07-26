import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { failureDetail } from "./data";
import { FIXTURE_FUNDS, FIXTURE_HOLDING, FIXTURE_PACKET } from "./fixture";
import { HOLDING_WITH_EVIDENCE } from "./testdata";

/**
 * `VITE_API_BASE_URL` is read at module scope, so each case re-imports the
 * module after stubbing the environment.
 */
async function seam(apiBase: string) {
  vi.stubEnv("VITE_API_BASE_URL", apiBase);
  vi.resetModules();
  return await import("./data");
}

/** Answers every request with `body`, and records the URLs it was asked for. */
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
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("the bundled-fixture branch", () => {
  it("serves the fund list without a request when no API base is configured", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const { loadFunds } = await seam("");
    await expect(loadFunds()).resolves.toEqual(FIXTURE_FUNDS);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("serves the packet with its totals inside it, not as a second request", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const { loadPacket } = await seam("");
    const packet = await loadPacket("fund_ii", "f2_25q4");
    expect(packet).toEqual(FIXTURE_PACKET);
    expect(packet.totals.amount.amount).toBe("5000000");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("serves the one holding it has", async () => {
    const { loadHolding } = await seam("");
    await expect(loadHolding("dream")).resolves.toEqual(FIXTURE_HOLDING);
  });

  /**
   * Answering with an empty evidence list under a name the fixture does not
   * hold would report "no evidence for Anthropic" when the truth is "no
   * Anthropic" — and those render identically once the panel is on screen.
   */
  it("refuses a holding it does not have rather than inventing an empty one", async () => {
    const { loadHolding } = await seam("");
    await expect(loadHolding("fund_ii_anthropic")).rejects.toThrow(
      /no fund_ii_anthropic in the bundled fixture/,
    );
  });
});

describe("the fetched branch", () => {
  it("asks /funds for the fund-periods rather than assuming one", async () => {
    const calls = serve(FIXTURE_FUNDS);
    const { loadFunds } = await seam("https://api.example.com");
    const funds = await loadFunds();
    expect(calls).toEqual(["https://api.example.com/funds"]);
    expect(funds.periods).toHaveLength(1);
    expect(funds.source).toBe("fixture");
  });

  it("asks for one packet, which carries its own totals", async () => {
    const calls = serve(FIXTURE_PACKET);
    const { loadPacket } = await seam("https://api.example.com");
    const packet = await loadPacket("fund_i", "fund_i_fy2024");
    expect(calls).toEqual(["https://api.example.com/funds/fund_i/periods/fund_i_fy2024/packet"]);
    expect(packet.totals.kind).toBe("held_at_date_reported");
  });

  it("asks /holdings/{id} for the evidence", async () => {
    const calls = serve(HOLDING_WITH_EVIDENCE);
    const { loadHolding } = await seam("https://api.example.com");
    const holding = await loadHolding("poolside");
    expect(calls).toEqual(["https://api.example.com/holdings/poolside"]);
    expect(holding.evidence).toHaveLength(2);
  });

  it("fails loudly on a non-2xx response instead of rendering an empty packet", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })),
    );
    const { loadPacket } = await seam("https://api.example.com");
    await expect(loadPacket("fund_ii", "fund_ii_25q4")).rejects.toThrow(/request failed: 503/);
  });

  it("names the fields a drifted packet is missing rather than blanking them", async () => {
    serve({ fund_id: "fund_ii", source: "ledger" });
    const { loadPacket } = await seam("https://api.example.com");
    await expect(loadPacket("fund_ii", "fund_ii_25q4")).rejects.toThrow(
      /packet is missing: period, rows, schema_version, policy_version, generated_at, totals/,
    );
  });

  /**
   * `totals` is the field most worth asserting on: it used to be a separate
   * request, and a response that silently stopped carrying it would leave the
   * dashboard rendering a packet with no total rather than failing.
   */
  it("rejects a packet that has lost its embedded totals", async () => {
    serve(Object.fromEntries(Object.entries(FIXTURE_PACKET).filter(([k]) => k !== "totals")));
    const { loadPacket } = await seam("https://api.example.com");
    await expect(loadPacket("fund_ii", "fund_ii_25q4")).rejects.toThrow(
      /packet is missing: totals/,
    );
  });

  it("names what a drifted holding response is missing", async () => {
    serve({ source: "ledger" });
    const { loadHolding } = await seam("https://api.example.com");
    await expect(loadHolding("poolside")).rejects.toThrow(
      /holding is missing: holding_id, company_name, evidence/,
    );
  });

  it("rejects a response that is not an object at all", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, json: async () => null })),
    );
    const { loadFunds } = await seam("https://api.example.com");
    await expect(loadFunds()).rejects.toThrow(/funds is missing:/);
  });
});

describe("failureDetail", () => {
  it("reads an Error's message", () => {
    expect(failureDetail(new Error("NetworkError"))).toBe("NetworkError");
  });

  it("still produces words for a rejection that is not an Error", () => {
    expect(failureDetail("upstream said no")).toBe("upstream said no");
  });
});
