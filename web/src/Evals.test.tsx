import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EVALS } from "./testdata";

async function mount(apiBase: string) {
  vi.stubEnv("VITE_API_BASE_URL", apiBase);
  vi.resetModules();
  const { Evals } = await import("./Evals");
  return render(<Evals />);
}

function serve(body: unknown, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok, status: ok ? 200 : 500, json: async () => body })),
  );
}

beforeEach(() => {
  vi.unstubAllEnvs();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("the evaluation page", () => {
  /**
   * The condition that makes the page worth building. Seven green hundreds is
   * marketing and a reader discounts all of it; volunteering the weak number is
   * what makes the strong ones credible.
   */
  it("leads with the blind figure, not the flattering one", async () => {
    serve(EVALS);
    const { container } = await mount("https://api.example.com");
    await waitFor(() => {
      expect(container.querySelector(".recall--lead")).not.toBeNull();
    });
    const lead = container.querySelector(".recall--lead")?.textContent ?? "";
    expect(lead).toMatch(/entity filter removed/);
    expect(lead).toMatch(/24 of 40/);
    // And the flattering one is present, not deleted — with the reason it is
    // flattering one hover away.
    const blocks = [...container.querySelectorAll(".recall")].map((el) => el.textContent ?? "");
    expect(blocks.some((text) => text.includes("40 of 40"))).toBe(true);
  });

  /**
   * §5.3 · a count is auditable and a percentage is a conclusion. The API sends
   * both numbers and this page renders both; it computes neither.
   */
  it("renders every rate as its two counts and never as a percentage", async () => {
    serve(EVALS);
    const { container } = await mount("https://api.example.com");
    await waitFor(() => {
      expect(container.querySelectorAll(".count").length).toBeGreaterThan(0);
    });
    expect(container.textContent).not.toMatch(/\d%/);
    for (const count of container.querySelectorAll(".count")) {
      expect(count.textContent).toMatch(/\d+ of \d+/);
    }
  });

  it("names every miss rather than counting them", async () => {
    serve(EVALS);
    const { container } = await mount("https://api.example.com");
    await waitFor(() => {
      expect(container.querySelectorAll(".miss").length).toBe(EVALS.retrieval.misses.length);
    });
    // Lucra appears in the per-holding table too, so the assertion is scoped to
    // the miss itself. `getByText` matching two elements is a test that would
    // pass on the wrong one.
    expect(container.querySelector(".miss__where")?.textContent).toMatch(/Lucra/);
    expect(container.querySelector(".miss__detail")?.textContent).toMatch(/relies on/);
  });

  it("shows the extraction refusals with their reasons", async () => {
    serve(EVALS);
    const { container } = await mount("https://api.example.com");
    await waitFor(() => {
      expect(container.querySelectorAll(".refusals li").length).toBe(1);
    });
    expect(screen.getByText(/price_per_share/)).toBeDefined();
    // The API's OWN sentence, read off the list rather than off the page's gloss
    // of it — the paragraph below the list says the same thing in other words,
    // and asserting the string appears somewhere cannot tell them apart.
    expect(container.querySelector(".refusals__why")?.textContent).toMatch(
      /as a figure in its own right/,
    );
  });

  it("puts the worst holding on the page rather than hiding it", async () => {
    await mountServed();
    expect(screen.getByText("Because Market")).toBeDefined();
  });

  async function mountServed() {
    serve(EVALS);
    const rendered = await mount("https://api.example.com");
    await waitFor(() => {
      expect(rendered.container.querySelector("table")).not.toBeNull();
    });
    return rendered;
  }

  it("states what it does not measure, with where each gap is measured", async () => {
    const { container } = await mountServed();
    expect(container.querySelectorAll(".blindspots li").length).toBe(EVALS.not_measured.length);
    expect(screen.getByText(/RIGHT passage/)).toBeDefined();
    expect(screen.getByText(/pytest/)).toBeDefined();
  });

  /**
   * 7a's acceptance criterion: "The page renders honestly when the API is
   * unreachable: no numbers, and a sentence saying so. A zero here would read as
   * a measurement."
   *
   * That is not a general principle about error states — several of these
   * figures could legitimately BE zero, so a zero rendered on failure is
   * indistinguishable from a real finding.
   */
  it("shows no numbers at all when nothing could be measured", async () => {
    serve({ detail: "ledger unavailable" }, false);
    const { container } = await mount("https://api.example.com");
    await waitFor(() => {
      expect(container.querySelector(".error")).not.toBeNull();
    });
    expect(container.querySelectorAll(".count")).toHaveLength(0);
    expect(container.querySelectorAll("table")).toHaveLength(0);
    expect(container.textContent).toMatch(/would read as a measurement/);
  });

  /**
   * There is no fixture branch, and that is the point of the route. Every figure
   * here is a measurement OF A LEDGER; the bundled one-holding stub would
   * produce real-looking numbers about a corpus that is not the fund.
   */
  it("refuses to measure the bundled fixture", async () => {
    const { container } = await mount("");
    await waitFor(() => {
      expect(container.querySelector(".error")).not.toBeNull();
    });
    expect(container.textContent).toMatch(/not the fund|one-holding/);
    expect(container.querySelectorAll(".count")).toHaveLength(0);
  });
});
