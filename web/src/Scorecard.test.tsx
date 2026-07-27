import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { PacketTotals } from "./contracts";
import type { ScorecardLine, ScorecardResponse } from "./reconcile.contracts";
import { Scorecard } from "./Scorecard";

/**
 * The line a partner reads first. Every number on it is the API's, and the
 * cases below are mostly about the screen refusing to invent one: the ratio it
 * does not divide, the counts it does not fill in with zeros when they are
 * absent, and the total it does not print when there is none.
 */

afterEach(cleanup);

function totals(overrides: Partial<PacketTotals> = {}): PacketTotals {
  return {
    kind: "held_at_date_reported",
    label: "Tracker-reported amounts for positions held at this date, unaudited",
    amount: { amount: "25648515.0000", currency: "USD" },
    unsupported_amount: { amount: "25648515.0000", currency: "USD" },
    unsupported_positions: 8,
    packet_gap_positions: 8,
    contains_unsupported_inputs: true,
    unheld_gap_positions: 0,
    ...overrides,
  };
}

/** Fund II at 25Q4, as the real ledger reports it: nothing supported, of eight. */
const F2_25Q4: ScorecardLine = {
  fund_id: "fund_ii",
  period_id: "fund_ii_25q4",
  label: "25Q4",
  period_date: "2025-12-31",
  audit_scope: "packet",
  counts: {
    positions: 8,
    fully_supported: 0,
    open_gap_positions: 8,
    pro_forma_positions: 3,
    held_at_date: 8,
    not_held_at_date: 0,
  },
  totals: totals(),
  absent_reason: null,
};

/** 24Q4 · Jackpocket was realised in May, so it is a position and not an input. */
const F2_24Q4: ScorecardLine = {
  fund_id: "fund_ii",
  period_id: "fund_ii_24q4",
  label: "24Q4",
  period_date: "2024-12-31",
  audit_scope: "packet",
  counts: {
    positions: 8,
    fully_supported: 2,
    open_gap_positions: 6,
    pro_forma_positions: 0,
    held_at_date: 7,
    not_held_at_date: 1,
  },
  totals: totals({
    amount: { amount: "10548515.0000", currency: "USD" },
    unsupported_amount: { amount: "7548515.0000", currency: "USD" },
    unsupported_positions: 5,
    packet_gap_positions: 6,
    unheld_gap_positions: 1,
  }),
  absent_reason: null,
};

const SCORECARD: ScorecardResponse = {
  source: "ledger",
  periods: [F2_24Q4, F2_25Q4],
};

function show(scorecard: ScorecardResponse = SCORECARD) {
  return render(<Scorecard scorecard={scorecard} />);
}

function lines(container: HTMLElement): string[] {
  return [...container.querySelectorAll(".check__head")].map((head) => head.textContent ?? "");
}

/** The partner's sentence: the second direct paragraph, after the heading line. */
function sentence(container: HTMLElement): string {
  return [...container.querySelectorAll(".check > p")][1]?.textContent ?? "";
}

describe("the partner's line", () => {
  /**
   * "0 of 8" is two integers the API counted, printed beside each other. SPEC
   * §5.3 forbids this surface dividing one by the other, and a scorecard is
   * exactly where a plausible wrong denominator would survive a review.
   */
  it("states supported and total as two supplied numbers, never as a ratio", () => {
    show();
    expect(screen.getByText("0 of 8")).toBeDefined();
    expect(screen.getByText("2 of 8")).toBeDefined();
    expect(screen.queryByText("0%")).toBeNull();
    expect(screen.getByText(/Nothing on this screen divides one by the other/)).toBeDefined();
  });

  it("names the open gaps and the pro forma marks as their own counts", () => {
    const { container } = show({ source: "ledger", periods: [F2_25Q4] });
    expect(sentence(container)).toBe(
      "0 of 8 positions fully supported, 8 with open gaps, 3 marked pro forma pending executed documentation.",
    );
  });

  it("renders one line per fund-period, in the order the API supplied them", () => {
    const { container } = show();
    expect(lines(container)).toEqual([
      "fund_ii · 24Q42024-12-31packet",
      "fund_ii · 25Q42025-12-31packet",
    ]);
  });

  it("pins every count to its own label", () => {
    const { container } = show({ source: "ledger", periods: [F2_24Q4] });
    const counts = [...container.querySelectorAll(".check .meta > div")].map((item) => ({
      label: item.querySelector("dt")?.textContent,
      value: item.querySelector("dd")?.textContent,
    }));
    expect(counts.slice(0, 6)).toEqual([
      { label: "positions in the packet", value: "8" },
      { label: "fully supported", value: "2" },
      { label: "with open gaps", value: "6" },
      { label: "marked pro forma", value: "0" },
      { label: "held at the measurement date", value: "7" },
      { label: "not held at the measurement date", value: "1" },
    ]);
  });

  /**
   * INV-7 · a position realised during the period is one of the packet's eight
   * and is not an input to the total beside it. The scorecard shows both counts,
   * because a line that reported only held positions would drop the row the
   * audit letter asks for by name.
   */
  it("keeps positions in the packet apart from positions held at the date", () => {
    show({ source: "ledger", periods: [F2_24Q4] });
    expect(screen.getByText("held at the measurement date")).toBeDefined();
    expect(screen.getByText("not held at the measurement date")).toBeDefined();
  });

  it("says one position in the singular", () => {
    const single: ScorecardLine = {
      ...F2_25Q4,
      counts: {
        positions: 1,
        fully_supported: 0,
        open_gap_positions: 1,
        pro_forma_positions: 1,
        held_at_date: 1,
        not_held_at_date: 0,
      },
    };
    const { container } = show({ source: "fixture", periods: [single] });
    expect(sentence(container)).toContain("0 of 1 position fully supported");
  });
});

describe("the total on the line", () => {
  /** INV-19 · the kind and the qualification travel with the figure. */
  it("never prints a bare figure: the kind and the caveat are beside it", () => {
    const { container } = show({ source: "ledger", periods: [F2_25Q4] });
    const figure = container.querySelector(".figure");
    expect(figure?.querySelector(".figure__caption")?.textContent).toBe("held at date · reported");
    expect(figure?.querySelector(".figure__amount")?.textContent).toBe("25,648,515.0000 USD");
    expect(screen.getByText("Unsupported value is inside this figure.")).toBeDefined();
    expect(
      screen.getByText("Tracker-reported amounts for positions held at this date, unaudited"),
    ).toBeDefined();
  });

  it("states when a figure contains nothing unsupported", () => {
    show({
      source: "ledger",
      periods: [{ ...F2_25Q4, totals: totals({ contains_unsupported_inputs: false }) }],
    });
    expect(screen.getByText("Nothing unsupported is inside this figure.")).toBeDefined();
  });

  /**
   * A packet whose rows carry no mark has counts and no total. A blank where a
   * figure belongs reads as zero, and zero is a figure the ledger does not hold.
   */
  it("says there is no total rather than printing an empty one", () => {
    show({ source: "ledger", periods: [{ ...F2_25Q4, totals: null }] });
    expect(screen.getByText(/No total at this date/)).toBeDefined();
    expect(screen.queryByText("25,648,515.0000 USD")).toBeNull();
  });
});

describe("what the scorecard will not fill in", () => {
  /**
   * "Zero of zero positions supported" is a finding about the fund. "No packet
   * could be assembled" is a finding about the ledger. They must not render the
   * same way, so the counts are absent rather than zero.
   */
  it("reports an unassemblable fund-period as absent, not as a row of zeros", () => {
    const absent: ScorecardLine = {
      fund_id: "fund_i",
      period_id: "fund_i_fy2021",
      label: "FY2021",
      period_date: null,
      audit_scope: null,
      counts: null,
      totals: null,
      absent_reason: "the ledger lists this fund-period but holds no position for it",
    };
    const { container } = show({ source: "ledger", periods: [absent] });
    expect(
      screen.getByText("the ledger lists this fund-period but holds no position for it"),
    ).toBeDefined();
    expect(container.querySelectorAll(".check .meta")).toHaveLength(0);
    expect(screen.queryByText(/of 0/)).toBeNull();
  });

  it("says which store answered, because a stub under the fund's name is untraceable", () => {
    show({ source: "fixture", periods: [F2_25Q4] });
    expect(screen.getByText(/source · fixture — not the fund/)).toBeDefined();
  });

  it("distinguishes an empty ledger from an empty screen", () => {
    show({ source: "ledger", periods: [] });
    expect(screen.getByText(/That is an empty ledger, not an empty screen/)).toBeDefined();
  });
});
