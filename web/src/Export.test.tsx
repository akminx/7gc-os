import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ExportResponse } from "./responses";

async function mount(apiBase: string) {
  vi.stubEnv("VITE_API_BASE_URL", apiBase);
  vi.resetModules();
  const { ExportPacket } = await import("./Export");
  return render(<ExportPacket fundId="fund_ii" periodId="fund_ii_25q4" />);
}

async function mountCompany(apiBase: string) {
  vi.stubEnv("VITE_API_BASE_URL", apiBase);
  vi.resetModules();
  const { ExportCompanyEvidence } = await import("./Export");
  return render(
    <ExportCompanyEvidence
      fundId="fund_ii"
      periodId="fund_ii_25q4"
      holdingId="fund_ii_fluidstack"
      companyName="Fluidstack"
    />,
  );
}

/**
 * What the browser hands to the operating system, captured instead of performed.
 *
 * The click is intercepted on the prototype rather than the download stubbed
 * out of the component, so the assertions below run over the real anchor the
 * real code built — its `download` attribute is the filename the reader ends up
 * with, and a save path that quietly did nothing would show up here as an empty
 * list rather than as a green test.
 */
const saved: { href: string; download: string }[] = [];

function captureSaves(): void {
  saved.length = 0;
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    saved.push({ href: this.href, download: this.download });
  });
  const objectUrls = { made: 0, revoked: 0 };
  URL.createObjectURL = vi.fn(() => {
    objectUrls.made += 1;
    return `blob:packet-${objectUrls.made}`;
  });
  URL.revokeObjectURL = vi.fn(() => {
    objectUrls.revoked += 1;
  });
}

/** A zip response, with the headers the API actually sets on one. */
function archiveResponse(overrides: Record<string, string> = {}): unknown {
  return {
    ok: true,
    status: 200,
    headers: new Headers({
      "content-disposition": 'attachment; filename="fund_ii-fund_ii_25q4.zip"',
      "x-packet-id": "pkx_fund_ii_25q4_20260726T220833Z",
      // A SHA-256 over packet contents, not a credential.
      "x-manifest-hash": "f9aa03f05c18ec049c06afa95d777fdd5b8f2b12a81b4b541d4feb3e7fac866a", // pragma: allowlist secret
      "x-file-count": "31",
      "x-withheld-file-count": "0",
      "x-recorded-in-ledger": "false",
      ...overrides,
    }),
    blob: async () => new Blob(["PK"], { type: "application/zip" }),
  };
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
    //: Scoped to THIS action, which is what makes it still true beside a
    //: download button. It used to read "nothing was downloaded to this
    //: browser" as a statement about the surface, and wiring up `export.zip`
    //: turned it into the opposite of what the screen does.
    expect(
      screen.getByText(/This build wrote to the API host and downloaded nothing/),
    ).toBeDefined();
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

/**
 * The packet has been the deliverable since the first line of the spec, and
 * until this it was only ever written to the API host's disk — which on a free
 * instance is ephemeral and unreachable, so the thing the project exists to
 * produce could not be obtained by the person it is for.
 */
describe("downloading the auditor packet", () => {
  beforeEach(() => {
    captureSaves();
  });

  it("asks for the archive and saves it under the name the API chose", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        return archiveResponse();
      }),
    );
    await mount("https://api.example.com");
    screen.getByRole("button", { name: "Download packet (.zip)" }).click();
    await waitFor(() => {
      expect(screen.getByText(/31 packet files/)).toBeDefined();
    });
    expect(calls).toEqual([
      "https://api.example.com/funds/fund_ii/periods/fund_ii_25q4/export.zip",
    ]);
    //: The file actually reached the browser's download machinery. Without
    //: this the screen could report a packet it never handed over.
    expect(saved).toEqual([{ href: "blob:packet-1", download: "fund_ii-fund_ii_25q4.zip" }]);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:packet-1");
  });

  it("says a downloaded packet is still not a recorded one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => archiveResponse()),
    );
    await mount("https://api.example.com");
    screen.getByRole("button", { name: "Download packet (.zip)" }).click();
    await waitFor(() => {
      expect(screen.getByText(/no · generated only, no packet version/)).toBeDefined();
    });
    expect(screen.getByText(/none · this is the whole packet/)).toBeDefined();
  });

  /**
   * The refusal is the deliverable. `export_packet` refuses a packet whose
   * citation does not resolve or whose approved position is unsupported, and
   * names which one — and a download that simply does not arrive, or that says
   * "Export failed", keeps the failure and throws the finding away.
   */
  it("renders the exporter's own refusal instead of a failed download", async () => {
    const detail =
      "citation for fund_ii_fluidstack fact #12 does not resolve in the exported text " +
      "companies/Fluidstack/spa.pdf.canonical.txt: span [212, 262) does not hold '$8.00 per share'";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 409,
        json: async () => ({ detail }),
      })),
    );
    await mount("https://api.example.com");
    screen.getByRole("button", { name: "Download packet (.zip)" }).click();
    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain(detail);
    });
    expect(saved).toEqual([]);
  });

  /**
   * A response that arrives without the headers describing it is a build talking
   * to an API that has moved. Rendering the blanks would put an empty string
   * where a packet id belongs, which reads as "this packet has no id" rather
   * than as a broken contract.
   */
  it("refuses to describe an archive whose response describes nothing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers({}),
        blob: async () => new Blob(["PK"]),
      })),
    );
    await mount("https://api.example.com");
    screen.getByRole("button", { name: "Download packet (.zip)" }).click();
    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("x-packet-id");
    });
    expect(saved).toEqual([]);
  });

  it("declines to pretend a fixture can be downloaded", async () => {
    await mount("");
    screen.getByRole("button", { name: "Download packet (.zip)" }).click();
    await waitFor(() => {
      expect(screen.getByText(/no ledger to export a packet from/)).toBeDefined();
    });
    expect(saved).toEqual([]);
  });
});

/**
 * The engagement letter closes: "We would appreciate receiving the support
 * organized by portfolio company." The export has been organised that way from
 * the start; this is the half that lets one of those folders be taken away
 * without the other seven.
 */
describe("downloading one company's evidence", () => {
  beforeEach(() => {
    captureSaves();
  });

  it("asks for that company's archive and names the company on the button", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        return archiveResponse({
          "content-disposition":
            'attachment; filename="fund_ii-fund_ii_25q4-fund_ii_fluidstack.zip"',
          "x-file-count": "13",
          "x-withheld-file-count": "17",
        });
      }),
    );
    await mountCompany("https://api.example.com");
    screen.getByRole("button", { name: "Download Fluidstack evidence (.zip)" }).click();
    await waitFor(() => {
      expect(screen.getByText(/13 packet files/)).toBeDefined();
    });
    expect(calls).toEqual([
      "https://api.example.com/funds/fund_ii/periods/fund_ii_25q4/companies/fund_ii_fluidstack/export.zip",
    ]);
    expect(saved).toEqual([
      { href: "blob:packet-1", download: "fund_ii-fund_ii_25q4-fund_ii_fluidstack.zip" },
    ]);
  });

  /**
   * The archive is the whole packet minus the other companies' documents, and
   * the screen says so. A reader who is not told would reasonably assume the
   * tables were cut to the company they asked for — and would then read the gap
   * report as this company's gaps, when it is the fund's.
   */
  it("states what the archive withheld and that the tables are the packet's own", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => archiveResponse({ "x-file-count": "13", "x-withheld-file-count": "17" })),
    );
    await mountCompany("https://api.example.com");
    screen.getByRole("button", { name: "Download Fluidstack evidence (.zip)" }).click();
    await waitFor(() => {
      expect(screen.getByText(/17 · other companies' source documents/)).toBeDefined();
    });
    expect(screen.getByText(/COMPANY_SCOPE.txt inside the archive/)).toBeDefined();
    expect(
      screen.getByText(/Every table, the workbook and the manifest are the full/),
    ).toBeDefined();
  });

  it("renders the API's own refusal for a company it will not export", async () => {
    const detail =
      "no position 'fund_ii_ghost' in the fund_ii_25q4 packet for fund_ii. " +
      "It holds: fund_ii_anthropic, fund_ii_fluidstack";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 404, json: async () => ({ detail }) })),
    );
    await mountCompany("https://api.example.com");
    screen.getByRole("button", { name: "Download Fluidstack evidence (.zip)" }).click();
    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain(detail);
    });
    expect(saved).toEqual([]);
  });

  it("declines to pretend a fixture holds a company's evidence", async () => {
    await mountCompany("");
    screen.getByRole("button", { name: "Download Fluidstack evidence (.zip)" }).click();
    await waitFor(() => {
      expect(screen.getByText(/no ledger to export this company's evidence from/)).toBeDefined();
    });
    expect(saved).toEqual([]);
  });
});
