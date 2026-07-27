import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Citation } from "./contracts";
import type { DocumentResponse } from "./responses";

/**
 * `VITE_API_BASE_URL` is read at module scope in the data seam, so each case
 * re-imports the pane after stubbing the environment.
 */
async function mount(apiBase: string, citation: Citation, caption = "fund_shares · 50,000") {
  vi.stubEnv("VITE_API_BASE_URL", apiBase);
  vi.resetModules();
  const { PassagePane } = await import("./Passage");
  return render(<PassagePane citation={citation} caption={caption} />);
}

const TEXT = "Section 1 — Purchase and Sale\n7GC Fund II, L.P.   50,000   $40.00\nSection 2";
const QUOTE = "7GC Fund II, L.P.   50,000   $40.00";

const CITATION: Citation = {
  document_version_id: "dv_a1dd056c9536fa4090fc087f",
  quote: QUOTE,
  span_start: TEXT.indexOf(QUOTE),
  span_end: TEXT.indexOf(QUOTE) + QUOTE.length,
};

const DOCUMENT: DocumentResponse = {
  source: "ledger",
  document_version_id: CITATION.document_version_id,
  filename: "Poolside - Series B - Stock Purchase Agreement Excerpt (August 1, 2024).pdf",
  extractor: "pdftotext -layout -enc UTF-8 -eol unix@26.03.0",
  // A SHA-1 of the extracted text, not a credential.
  text_hash: "a1dd056c9536fa4090fc087f58a310383caa8df0", // pragma: allowlist secret
  page_count: 1,
  text_length: TEXT.length,
  text: TEXT,
};

function serve(body: unknown, ok = true): string[] {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      return { ok, status: ok ? 200 : 404, json: async () => body };
    }),
  );
  return calls;
}

beforeEach(() => {
  vi.unstubAllEnvs();
  // jsdom implements no scrolling, and the pane calls this on mount.
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("the passage pane", () => {
  it("marks the cited span inside the stored document, and names the file", async () => {
    const calls = serve(DOCUMENT);
    const { container } = await mount("https://api.example.com", CITATION);
    await waitFor(() => {
      expect(container.querySelector(".cited")).not.toBeNull();
    });
    expect(calls).toEqual(["https://api.example.com/documents/dv_a1dd056c9536fa4090fc087f"]);
    // The highlight is exactly the stored quote, and the surrounding document is
    // still on screen either side of it — the whole point of fetching the text
    // rather than rendering the quote alone.
    expect(container.querySelector(".cited")?.textContent).toBe(QUOTE);
    expect(container.querySelector(".paper__body")?.textContent).toBe(TEXT);
    expect(screen.getByText(DOCUMENT.filename)).toBeDefined();
  });

  /**
   * Not debug output. The offsets are the auditor's instruction for finding the
   * passage again by hand, so they are on screen rather than in a tooltip.
   */
  it("shows the offsets and the extraction they belong to", async () => {
    serve(DOCUMENT);
    await mount("https://api.example.com", CITATION);
    await waitFor(() => {
      expect(screen.getByText(/pdftotext/)).toBeDefined();
    });
    expect(screen.getByText(`chars ${CITATION.span_start}–${CITATION.span_end}`)).toBeDefined();
  });

  /**
   * `0008_citations_resolve.sql` enforces `substring(canonical_text, span) =
   * quote`. This pane checks it again where a human can see the result: a
   * citation that has drifted one character has no other detector in the
   * browser, and highlighting the wrong sentence confidently is worse than
   * highlighting nothing.
   */
  it("refuses to present a span that does not select the stored quote", async () => {
    serve({ ...DOCUMENT, text: `PREFIX${TEXT}` });
    const { container } = await mount("https://api.example.com", CITATION);
    await waitFor(() => {
      expect(screen.getByText(/do not select the stored quote/)).toBeDefined();
    });
    expect(container.querySelector(".cited--unresolved")).not.toBeNull();
    expect(container.querySelector(".cited")?.textContent).not.toBe(QUOTE);
  });

  /**
   * A failed document request is not a finding about the evidence. The quote is
   * still verbatim and the offsets still on screen; what the pane loses is the
   * surrounding page, and it says which of the two it is showing.
   */
  it("falls back to the stored quote and states why, rather than going blank", async () => {
    serve({ detail: "no document version" }, false);
    const { container } = await mount("https://api.example.com", CITATION);
    await waitFor(() => {
      expect(container.querySelector(".paper--quote-only")).not.toBeNull();
    });
    expect(container.querySelector(".cited")?.textContent).toBe(QUOTE);
    expect(screen.getByText(/document request failed: 404/)).toBeDefined();
  });

  it("says the bundled fixture carries no document text", async () => {
    const { container } = await mount("", CITATION);
    await waitFor(() => {
      expect(screen.getByText(/carries no document text/)).toBeDefined();
    });
    expect(container.querySelector(".cited")?.textContent).toBe(QUOTE);
  });

  /**
   * The owner's finding, from using the product: the pane rendered the ENTIRE
   * document around a 62-character highlight. Fluidstack's cap table is 3,730
   * characters of columnar `pdftotext` output and one highlighted line inside it
   * is indistinguishable from the rest, scrolled to or not.
   */
  describe("around a document too long to read", () => {
    // A cap table shaped like the real ones: the cited figure is part of a ROW,
    // and the row is the unit of meaning.
    const ROW = "  7GC Fund II, L.P.        Series A-2      100,000       $15.00";
    const CITED_ROW_FRAGMENT = "100,000       $15.00";
    const LONG = [
      "FLUIDSTACK, INC.",
      "PRO FORMA CAPITALIZATION — SERIES B",
      "",
      "Holder                     Class            Shares        PPS",
      "  Founders                 Common        20,000,000        —",
      "  Seed Investors           Series Seed    5,000,000     $1.00",
      ROW,
      "  Other Holders            Series A       900,000       $10.00",
      "  Series B Investors       Series B       5,000,000     $30.00",
      "",
      "Fully diluted: 50,000,000 shares",
      "Executed documents on file with company counsel.",
    ].join("\n");
    const LONG_CITATION: Citation = {
      document_version_id: "dv_long",
      quote: CITED_ROW_FRAGMENT,
      span_start: LONG.indexOf(CITED_ROW_FRAGMENT),
      span_end: LONG.indexOf(CITED_ROW_FRAGMENT) + CITED_ROW_FRAGMENT.length,
    };
    const LONG_DOCUMENT: DocumentResponse = {
      ...DOCUMENT,
      document_version_id: "dv_long",
      filename: "Fluidstack - Series B - Pro Forma Capitalization Table Excerpt.pdf",
      text_length: LONG.length,
      text: LONG,
    };

    it("shows the cited lines rather than the whole page, and says what it is holding back", async () => {
      serve(LONG_DOCUMENT);
      const { container } = await mount("https://api.example.com", LONG_CITATION);
      await waitFor(() => {
        expect(container.querySelector(".cited")).not.toBeNull();
      });
      const body = container.querySelector(".paper__body")?.textContent ?? "";
      expect(body).not.toBe(LONG);
      expect(body.length).toBeLessThan(LONG.length);
      // Two lines either side, and nothing from beyond them.
      expect(body).toContain("Seed Investors");
      expect(body).toContain("Series B Investors");
      expect(body).not.toContain("FLUIDSTACK, INC.");
      expect(body).not.toContain("Executed documents on file");
      expect(screen.getByText(/4 lines above and 3 below are not on screen/)).toBeDefined();
    });

    /**
     * Line-scoped, not character-scoped. A cap table's unit of meaning is the
     * ROW, and ±300 characters cuts it mid-row — which reads as a different
     * number against a different holder.
     */
    it("keeps the cited row whole rather than cutting it at the span", async () => {
      serve(LONG_DOCUMENT);
      const { container } = await mount("https://api.example.com", LONG_CITATION);
      await waitFor(() => {
        expect(container.querySelector(".cited")).not.toBeNull();
      });
      expect(container.querySelector(".paper__body")?.textContent).toContain(ROW);
      expect(container.querySelector(".cited")?.textContent).toBe(CITED_ROW_FRAGMENT);
    });

    it("offers the whole document, and takes it back", async () => {
      serve(LONG_DOCUMENT);
      const { container } = await mount("https://api.example.com", LONG_CITATION);
      await waitFor(() => {
        expect(container.querySelector(".cited")).not.toBeNull();
      });
      screen.getByRole("button", { name: /Show the whole document/ }).click();
      await waitFor(() => {
        expect(container.querySelector(".paper__body")?.textContent).toBe(LONG);
      });
      expect(screen.getByText(new RegExp(`${LONG.length} characters`))).toBeDefined();
      screen.getByRole("button", { name: /Show just the cited lines/ }).click();
      await waitFor(() => {
        expect(container.querySelector(".paper__body")?.textContent).not.toBe(LONG);
      });
    });

    /**
     * The pane's refusal to highlight when the offsets do not select the stored
     * quote is load-bearing and had to survive the change. It compares the slice
     * of the WHOLE stored text, so narrowing what is displayed cannot make a
     * drifted citation resolve.
     */
    it("still refuses a drifted span inside a narrowed window", async () => {
      serve({ ...LONG_DOCUMENT, text: `PREFIX${LONG}` });
      const { container } = await mount("https://api.example.com", LONG_CITATION);
      await waitFor(() => {
        expect(screen.getByText(/do not select the stored quote/)).toBeDefined();
      });
      expect(container.querySelector(".cited--unresolved")).not.toBeNull();
      expect(container.querySelector(".cited")?.textContent).not.toBe(CITED_ROW_FRAGMENT);
    });

    /**
     * A document that fits is not narrowed, and does not claim to be. A reader
     * has to be able to tell "this is the whole file" from "this has been cut".
     */
    it("says nothing about a window on a document short enough to show entire", async () => {
      serve(DOCUMENT);
      const { container } = await mount("https://api.example.com", CITATION);
      await waitFor(() => {
        expect(container.querySelector(".cited")).not.toBeNull();
      });
      expect(container.querySelector(".paper__window")).toBeNull();
      expect(container.querySelector(".paper__body")?.textContent).toBe(TEXT);
    });
  });

  it("shows a skeleton of the page while the document is in flight", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
    const { container } = await mount("https://api.example.com", CITATION);
    expect(container.querySelector(".paper--loading")).not.toBeNull();
    expect(container.querySelectorAll(".skeleton").length).toBeGreaterThan(0);
  });
});
