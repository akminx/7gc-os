import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HoldingRow } from "./contracts";
import { Dashboard } from "./Dashboard";
import { FIXTURE_ROW } from "./fixture";
import type { PacketResponse } from "./responses";
import {
  FOUR_ROW_PACKET,
  POOLSIDE_ROW,
  REALISED_ROW,
  SWAY_ROW,
  THREE_ROW_PACKET,
  THREE_ROW_TOTALS,
} from "./testdata";

afterEach(cleanup);

function show(packet: PacketResponse = THREE_ROW_PACKET, onOpen: (id: string) => void = () => {}) {
  return render(<Dashboard packet={packet} onOpenCompany={onOpen} />);
}

describe("totals", () => {
  it("never renders a bare total: the kind and the label travel with the number", () => {
    show();
    expect(screen.getByText("held at date · reported")).toBeDefined();
    expect(
      screen.getAllByText("Tracker-reported amounts for positions held at this date, unaudited")
        .length,
    ).toBeGreaterThan(0);
  });

  /**
   * Asserting that a figure appears SOMEWHERE cannot tell the total from the
   * subtotal beside it. It did not: rendering `unsupported_amount` in the
   * total's place survived this suite until these two cases existed, because
   * the fixture's four figures were pairwise equal. Each number is now read out
   * of the element its own caption labels.
   */
  it("pins the total and the unsupported subtotal to their own captions", () => {
    const { container } = show();
    const figures = [...container.querySelectorAll(".totals__figures .figure")].map((figure) => ({
      caption: figure.querySelector(".figure__caption")?.textContent,
      amount: figure.querySelector(".figure__amount")?.textContent,
    }));
    expect(figures).toEqual([
      { caption: THREE_ROW_TOTALS.label, amount: "7,500,000 USD" },
      { caption: "of which nothing supports — unsupported subtotal", amount: "5,000,000 USD" },
    ]);
  });

  it("pins each position count to its own label, and states they are not additive", () => {
    const { container } = show();
    const counts = [...container.querySelectorAll(".totals .meta > div")].map((item) => ({
      label: item.querySelector("dt")?.textContent,
      value: item.querySelector("dd")?.textContent,
    }));
    expect(counts).toEqual([
      { label: "unsupported positions held at this date", value: "1" },
      { label: "packet gap positions (held or not)", value: "2" },
      { label: "unsupported but not held at this date", value: "1" },
    ]);
    expect(screen.getByText(/superset/)).toBeDefined();
    expect(screen.getByText(/not additive/)).toBeDefined();
  });

  /**
   * INV-19 · the qualification is rendered beside the figure, not left in a
   * field. It is not a restatement of the subtotal being non-zero: the API sets
   * it when EITHER the unsupported amount or the unsupported count is non-zero.
   */
  it("says on the face of the total whether it contains unsupported inputs", () => {
    show();
    expect(screen.getByText("This total contains unsupported inputs.")).toBeDefined();
    cleanup();
    show({
      ...THREE_ROW_PACKET,
      totals: { ...THREE_ROW_TOTALS, contains_unsupported_inputs: false },
    });
    expect(screen.getByText("This total contains no unsupported input.")).toBeDefined();
  });
});

describe("holding rows", () => {
  it("keeps reported, validated and support in three separate columns", () => {
    show();
    expect(screen.getByText("Reported (tracker)")).toBeDefined();
    expect(screen.getByText("Validated (derived)")).toBeDefined();
    expect(screen.getByText("Row support")).toBeDefined();
  });

  it("states why a validated amount is absent instead of leaving the cell blank", () => {
    show();
    expect(screen.getByText(/none · NO_PRICE_FOR_CLASS:series_a1/)).toBeDefined();
  });

  it("renders a validated amount when the mark carries one", () => {
    show();
    expect(screen.getByText("1,234,567.8900 USD")).toBeDefined();
  });

  /**
   * A realised position has no mark at all — `evals/oracle/derived.json` states
   * Jackpocket at 2024-12-31 as `reported_amount: null`. The row still belongs
   * in the packet, and its two money columns say the mark is absent rather than
   * going blank: read down a column of amounts, a blank cell is a zero.
   */
  it("states that a row with no mark has none, in place of both money columns", () => {
    const { container } = show(FOUR_ROW_PACKET);
    const cells = [...container.querySelectorAll("tbody tr")].map((tr) => ({
      company: tr.querySelector("th button")?.textContent,
      mark: tr.querySelector(".cell--no-mark")?.textContent,
      span: tr.querySelector(".cell--no-mark")?.getAttribute("colspan"),
      amounts: [...tr.querySelectorAll("td.num")].map((td) => td.textContent),
    }));
    expect(cells).toEqual([
      {
        company: "Dream",
        mark: undefined,
        span: undefined,
        amounts: ["5,000,000 USD", "none · NO_PRICE_FOR_CLASS:series_a1"],
      },
      {
        company: "Sway",
        mark: undefined,
        span: undefined,
        amounts: ["2,500,000 USD", "1,234,567.8900 USD"],
      },
      {
        company: "Poolside",
        mark: undefined,
        span: undefined,
        amounts: ["2,500,000 USD", "2,500,000 USD"],
      },
      { company: "Jackpocket", mark: "no mark at this date", span: "2", amounts: [] },
    ]);
  });

  /**
   * The row still counts. A markless row is a packet gap and is not an input to
   * the held-at-date total, so the two money figures do not move and the two
   * gap counts do — all four supplied by the API, none of them computed here.
   */
  it("keeps a markless row out of the total and inside the gap counts", () => {
    const { container } = show(FOUR_ROW_PACKET);
    expect(container.querySelectorAll("tbody tr")).toHaveLength(4);
    const counts = [...container.querySelectorAll(".totals .meta > div")].map(
      (item) => item.querySelector("dd")?.textContent,
    );
    expect(counts).toEqual(["1", "3", "2"]);
    const figures = [...container.querySelectorAll(".totals__figures .figure__amount")].map(
      (figure) => figure.textContent,
    );
    expect(figures).toEqual(["7,500,000 USD", "5,000,000 USD"]);
    expect(REALISED_ROW.mark).toBeNull();
  });

  it("distinguishes a row held at the date from one that is not", () => {
    show();
    expect(screen.getAllByText("held at date")).toHaveLength(2);
    expect(screen.getByText("not held at date")).toBeDefined();
  });

  /**
   * Support is now on the wire and is rendered as the API decided it. Poolside
   * satisfies R1 and R2 and reads supported; Dream and Sway do not and each
   * carries its own reasons, keyed by the requirement that failed.
   */
  it("renders the API's support verdict per row, with the reasons behind it", () => {
    const { container } = show();
    expect(container.querySelectorAll(".support--supported")).toHaveLength(1);
    expect(container.querySelectorAll(".support--unsupported")).toHaveLength(2);
    const reasons = [...container.querySelectorAll("tbody .support__reasons")].map(
      (list) => list.textContent,
    );
    expect(reasons).toEqual([
      "R1 missingR2 partial",
      "R1 not assessedR2 not assessedR3 insufficient",
    ]);
  });

  it("opens the company workspace when a company is clicked", async () => {
    const onOpen = vi.fn();
    show(THREE_ROW_PACKET, onOpen);
    screen.getByRole("button", { name: "Dream" }).click();
    expect(onOpen).toHaveBeenCalledWith("dream");
  });

  it("says a requirement is absent from the packet rather than inventing a verdict", () => {
    // SWAY_ROW carries only R3, so R1, R2, R4 and R5 have no assessment at all.
    show();
    expect(screen.getAllByText("absent").length).toBe(4);
  });

  it("declines to compute the sufficient / applicable fraction SPEC 7.1 asks for", () => {
    show();
    expect(screen.getByText(/counting rows is an aggregate/)).toBeDefined();
  });

  /**
   * The pair that makes a generic "Approved" badge wrong: Sway is unsupported
   * and IS an approved fair value; Poolside is supported and is NOT, because a
   * transcription approval is a different decision (SPEC §6.3, INV-10).
   */
  it("renders the approval record and the fair-value flag as separate facts", () => {
    show();
    expect(screen.getByText(/valuation approval · approved/)).toBeDefined();
    expect(screen.getByText(/transcription approval · draft/)).toBeDefined();
    expect(screen.getByText("no approval recorded")).toBeDefined();
    expect(screen.getAllByText("counts as approved fair value")).toHaveLength(1);
    expect(screen.getAllByText("not an approved fair value")).toHaveLength(2);
  });

  it("renders the packet header and says which store answered", () => {
    show();
    expect(screen.getByText("fund_ii · FY2025 Q4")).toBeDefined();
    expect(screen.getByText("2025-12-31")).toBeDefined();
    expect(screen.getByText(/packet — An audit measurement date/)).toBeDefined();
    expect(screen.getByText(/source · fixture — not the fund/)).toBeDefined();
  });

  it("renders one row per holding the packet supplies", () => {
    const { container } = show();
    expect(container.querySelectorAll("tbody tr")).toHaveLength(3);
    const rows: HoldingRow[] = [FIXTURE_ROW, SWAY_ROW, POOLSIDE_ROW];
    for (const row of rows) {
      expect(screen.getByRole("button", { name: row.company_name })).toBeDefined();
    }
  });
});
