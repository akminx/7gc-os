import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PassagesResponse } from "./responses";

afterEach(cleanup);

const PASSAGE = {
  claim_id: "fund_ii_moonfare:fy2024_fx_remeasurement",
  claim_key: "fy2024_fx_remeasurement",
  holding_id: "fund_ii_moonfare",
  document_version_id: "dv_1",
  filename: "Moonfare - FX Re-measurement Memo - FY2024.pdf",
  source_class: "fund_internal_record" as const,
  execution_status: "not_applicable" as const,
  issued_date: "2024-12-31",
  page: 1,
  quote: "the Fund's EUR-denominated interest in Moonfare GmbH",
  span_start: 137,
  span_end: 189,
  matched: ["eur", "moonfar"],
};

const FOUND: PassagesResponse = {
  source: "ledger",
  query: { text: "euro denomination", supplied: true, requirement: "R2", on: "2024-12-31" },
  outcome: "found",
  passages: [PASSAGE],
};

/** Loaded per test so each can stub `data.ts` differently. */
type Stub = (...args: never[]) => Promise<unknown>;

async function mount(passages: Stub, explain: Stub): Promise<void> {
  vi.resetModules();
  vi.doMock("./data", () => ({ findPassages: passages, explainRow: explain }));
  const { AssistStrip } = await import("./Assist");
  render(<AssistStrip holdingId="fund_ii_moonfare" measurementDate="2024-12-31" />);
}

const NEVER = () => new Promise<never>(() => {});

/** Both panes are inert until asked, so every test has to ask. */
const search = () => fireEvent.click(screen.getByRole("button", { name: "Search" }));
const writeOut = () => fireEvent.click(screen.getByRole("button", { name: "Write it out" }));

const EXPLAINED = {
  source: "ledger",
  row: { verdict: "missing" },
  outcome: "explained",
  text: "The valuation memo states the period it may be relied on, and this date falls outside it.",
  refusal: null,
  model: "anthropic/claude-haiku-4.5",
};

describe("asking the documents", () => {
  it("renders the passage as a quotation with the page it sits on", async () => {
    await mount(async () => FOUND, NEVER);
    search();
    await waitFor(() => expect(screen.getByText(/EUR-denominated interest/)).toBeDefined());
    expect(screen.getByText(/page 1/)).toBeDefined();
    expect(screen.getByText(/Moonfare - FX Re-measurement Memo/)).toBeDefined();
    // WHY this passage came back. A ranked list with no account of its own
    // relevance is an ordering the reader has to take on faith.
    expect(screen.getByText(/matched on eur, moonfar/)).toBeDefined();
  });

  /**
   * The distinction the `outcome` field exists for. An empty list rendered as
   * an empty list is indistinguishable from a pane that failed to load, and
   * this pane can legitimately return nothing.
   */
  it("says the documents address it nowhere rather than showing an empty list", async () => {
    await mount(async () => ({ ...FOUND, outcome: "none_matched", passages: [] }), NEVER);
    search();
    await waitFor(() => expect(screen.getByText(/matches that, for this date/)).toBeDefined());
    // And it names the reason a document a reader knows exists might be absent,
    // rather than letting them conclude the fund does not hold it.
    expect(screen.getByText(/stated reliance period/)).toBeDefined();
  });

  it("keeps a failed request apart from a finding of no evidence", async () => {
    await mount(async () => {
      throw new Error("passage search failed: 503");
    }, NEVER);
    search();
    await waitFor(() => expect(screen.getByText(/did not run/)).toBeDefined());
    expect(screen.getByText(/not a finding that the/)).toBeDefined();
  });

  it("tells the reader when the question searched was not theirs", async () => {
    await mount(async () => ({ ...FOUND, query: { ...FOUND.query, supplied: false } }), NEVER);
    search();
    await waitFor(() => expect(screen.getByText(/Nothing was typed/)).toBeDefined());
  });

  it("sends the reader's words when they submit", async () => {
    const spy = vi.fn(async (_h: string, _d: string, _r: string, _q: string) => FOUND);
    await mount(spy, NEVER);
    fireEvent.change(screen.getByLabelText(/Ask the documents/), {
      target: { value: "euro denomination" },
    });
    search();
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith("fund_ii_moonfare", "2024-12-31", "R2", "euro denomination"),
    );
  });
});

describe("the plain-English window", () => {
  it("shows the paragraph and says a machine wrote it and what was checked", async () => {
    await mount(NEVER, async () => EXPLAINED);
    writeOut();
    await waitFor(() => expect(screen.getByText(/period it may be relied on/)).toBeDefined());
    const provenance = screen.getByText(/then checked/);
    expect(provenance.textContent).toContain("anthropic/claude-haiku-4.5");
    expect(provenance.textContent).toContain("adds no fact of its own");
  });

  /**
   * A refusal is rendered, not hidden. The guard rejecting a restatement is the
   * system working, and a reader shown a blank box learns that the feature is
   * broken instead.
   */
  it("renders the refusal in the guard's own words", async () => {
    await mount(NEVER, async () => ({
      ...EXPLAINED,
      outcome: "refused",
      text: null,
      refusal: "the restatement states 9.99, which the row does not contain.",
    }));
    writeOut();
    await waitFor(() => expect(screen.getByText(/did not pass its check/)).toBeDefined());
    expect(screen.getByText(/9\.99/)).toBeDefined();
    expect(screen.getByText(/complete and unaffected/)).toBeDefined();
  });

  it("never renders a refused restatement's text", async () => {
    // The failure this guards against is a pane that shows `text` whatever the
    // outcome says — which would render exactly the sentence the guard threw
    // away, and render it as though it had passed.
    await mount(NEVER, async () => ({
      ...EXPLAINED,
      outcome: "refused",
      text: "The shares are worth $9.99 each.",
      refusal: "the restatement states 9.99, which the row does not contain.",
    }));
    writeOut();
    await waitFor(() => expect(screen.getByText(/did not pass its check/)).toBeDefined());
    expect(screen.queryByText(/The shares are worth/)).toBeNull();
  });
});

describe("the requirement picker", () => {
  it("moves both windows together, so they cannot describe different requests", async () => {
    const ask = vi.fn(async (_h: string, _d: string, _r: string, _q: string) => FOUND);
    const explain = vi.fn(async (_h: string, _d: string, _r: string) => EXPLAINED);
    await mount(ask, explain);
    search();
    writeOut();
    await waitFor(() => expect(ask).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /existence and cost/ }));
    search();
    await waitFor(() => expect(ask.mock.calls.at(-1)?.[2]).toBe("R1"));
    // The restatement resets to unasked when the selection moves, rather than
    // leaving a paragraph about the previous requirement standing under a new
    // tab. So it is asked again, and it is asked about R1.
    writeOut();
    await waitFor(() => expect(explain.mock.calls.at(-1)?.[2]).toBe("R1"));
  });
});
