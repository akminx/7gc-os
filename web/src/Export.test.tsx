import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ExportResponse } from "./responses";

async function mount(apiBase: string) {
  vi.stubEnv("VITE_API_BASE_URL", apiBase);
  vi.resetModules();
  const { ExportPacket } = await import("./Export");
  return render(<ExportPacket fundId="fund_ii" periodId="fund_ii_25q4" />);
}

const WRITTEN: ExportResponse = {
  source: "ledger",
  fund_id: "fund_ii",
  period_id: "fund_ii_25q4",
  packet_id: "pkx_fund_ii_25q4_20260726T220833Z",
  root: "/srv/out/packets/fund_ii_25q4",
  // A SHA-256 of packet contents, not a credential.
  manifest_hash: "f9aa03f05c18ec049c06afa95d777fdd5b8f2b12a81b4b541d4feb3e7fac866a", // pragma: allowlist secret
  schema_version: "0.1.0",
  policy_version: "v1",
  file_count: 31,
  files: ["README.md", "Valuation_Support.xlsx"],
  recorded_in_ledger: false,
};

beforeEach(() => {
  vi.unstubAllEnvs();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("exporting the auditor packet", () => {
  it("names its action and the fund-period it will act on", async () => {
    await mount("https://api.example.com");
    expect(screen.getByRole("button", { name: "Export auditor packet" })).toBeDefined();
    expect(screen.getByText(/fund_ii_25q4/)).toBeDefined();
  });

  it("asks the API for the period on screen and reports what was written", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        return { ok: true, status: 200, json: async () => WRITTEN };
      }),
    );
    await mount("https://api.example.com");
    screen.getByRole("button", { name: "Export auditor packet" }).click();
    await waitFor(() => {
      expect(screen.getByText(/31 files/)).toBeDefined();
    });
    expect(calls).toEqual(["https://api.example.com/funds/fund_ii/periods/fund_ii_25q4/export"]);
    expect(screen.getByText(WRITTEN.manifest_hash)).toBeDefined();
    expect(screen.getByText(WRITTEN.root)).toBeDefined();
  });

  /**
   * SPEC §6.3 · "a packet was generated" and "a packet version was registered"
   * are different facts, and the second is what permits an export to be relied
   * on. The screen says which one happened rather than letting a green line
   * imply the stronger claim.
   */
  it("says a generated packet is not a recorded one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, json: async () => WRITTEN })),
    );
    await mount("https://api.example.com");
    screen.getByRole("button", { name: "Export auditor packet" }).click();
    await waitFor(() => {
      expect(screen.getByText(/no · generated only, no packet version/)).toBeDefined();
    });
    expect(screen.getByText(/Nothing was downloaded to this browser/)).toBeDefined();
  });

  it("reports it is working, and refuses a second click while it does", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
    await mount("https://api.example.com");
    screen.getByRole("button", { name: "Export auditor packet" }).click();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Building the packet/ })).toBeDefined();
    });
    expect(
      screen.getByRole("button", { name: /Building the packet/ }).hasAttribute("disabled"),
    ).toBe(true);
  });

  /**
   * The exporter REFUSES rather than fails: an unresolved citation or an
   * approved-but-unsupported position is a finding, and the sentence naming it
   * is the deliverable. "Export failed" keeps the failure and throws away the
   * finding.
   */
  it("renders the exporter's own refusal, and says nothing was written", async () => {
    const detail = "citation for fund_ii_dream does not resolve in dv_f492f3c2 at 212–262";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 409, json: async () => ({ detail }) })),
    );
    await mount("https://api.example.com");
    screen.getByRole("button", { name: "Export auditor packet" }).click();
    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain(detail);
    });
    // The problem AND the recovery, which is what an error owes the reader.
    expect(screen.getByText(/Nothing was written\./)).toBeDefined();
    expect(screen.getByText(/then export again/)).toBeDefined();
  });

  it("declines to pretend a fixture can be exported", async () => {
    await mount("");
    screen.getByRole("button", { name: "Export auditor packet" }).click();
    await waitFor(() => {
      expect(screen.getByText(/no ledger to export a packet from/)).toBeDefined();
    });
  });
});
