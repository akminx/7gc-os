import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { HoldingRow } from "./contracts";
import { FIXTURE_ROW } from "./fixture";
import { POOLSIDE_ROW, SWAY_ROW } from "./testdata";
import { Workspace } from "./Workspace";

afterEach(cleanup);

function show(row: HoldingRow) {
  return render(<Workspace row={row} />);
}

describe("the mark", () => {
  it("presents reported, validated and support as three facts", () => {
    show(FIXTURE_ROW);
    expect(screen.getByText("The mark — three facts, not one")).toBeDefined();
    expect(screen.getByText("Reported — tracker")).toBeDefined();
    expect(screen.getByText("Validated — independently derived")).toBeDefined();
    expect(screen.getByText("Support — evidence verdicts")).toBeDefined();
  });

  it("states the reported amount and the reason no validated amount exists", () => {
    show(FIXTURE_ROW);
    expect(screen.getByText("5,000,000 USD")).toBeDefined();
    expect(screen.getByText("none")).toBeDefined();
    expect(screen.getByText(/not derivable · NO_PRICE_FOR_CLASS:series_a1/)).toBeDefined();
  });

  /**
   * INV-13 · reported, validated and supported are three facts. The third is
   * the API's verdict, rendered with the reasons it gave, and it is deliberately
   * possible for a row to be perfectly derivable and wholly unsupported.
   */
  it("renders the API's support verdict as the third fact, with its reasons", () => {
    const { container } = show(FIXTURE_ROW);
    expect(screen.getByText("unsupported")).toBeDefined();
    expect(container.querySelector(".support__reasons")?.textContent).toBe("R1 missingR2 partial");
    expect(screen.getByText(/decided by the API/)).toBeDefined();
  });

  it("renders a supported row as supported, with no reasons attached", () => {
    const { container } = show(POOLSIDE_ROW);
    expect(container.querySelector(".support--supported")).not.toBeNull();
    expect(container.querySelector(".support__reasons")).toBeNull();
  });

  it("renders a validated amount and its computation lineage when both exist", () => {
    show(SWAY_ROW);
    // once as the validated figure, once as the cited claim's stated amount.
    expect(screen.getAllByText("1,234,567.8900 USD")).toHaveLength(2);
    expect(screen.getByText("shares × PPS")).toBeDefined();
    expect(screen.getByText("multiply")).toBeDefined();
    expect(screen.getByText(/Series B price per share/)).toBeDefined();
    expect(screen.getByText(/offsets 120/)).toBeDefined();
    expect(screen.getByText("share count")).toBeDefined();
  });

  it("names the valuation basis, or says none was declared", () => {
    show(SWAY_ROW);
    expect(screen.getByText("quoted price")).toBeDefined();
    cleanup();
    show(FIXTURE_ROW);
    expect(screen.getByText("none declared")).toBeDefined();
  });

  it("says whether the position was held at the measurement date", () => {
    show(FIXTURE_ROW);
    expect(screen.getByText("yes")).toBeDefined();
    cleanup();
    show(SWAY_ROW);
    expect(screen.getByText(/not an input to the held-at-date total/)).toBeDefined();
  });
});

describe("PBC checklist", () => {
  it("renders one entry per requirement with its verdict and reason codes", () => {
    const { container } = show(FIXTURE_ROW);
    expect(container.querySelectorAll(".check")).toHaveLength(5);
    expect(screen.getByText("R1 · existence and cost")).toBeDefined();
    expect(screen.getByText("ACQUISITION_DOCS_NOT_LOCATED")).toBeDefined();
    expect(screen.getByText("REQUEST_FROM_COMPANY")).toBeDefined();
    expect(screen.getAllByText(/not applicable/).length).toBeGreaterThan(0);
  });

  it("flags a pro-forma assessment separately from its verdict", () => {
    show(FIXTURE_ROW);
    // The same word about two different things: the assessment relies on
    // pro-forma inputs, and one cited artifact IS pro forma. The second is
    // prefixed "artifact ·" so the two never read as one statement.
    expect(screen.getByText("pro forma")).toBeDefined();
    expect(screen.getByText(/artifact · pro forma/)).toBeDefined();
  });

  it("says when a requirement cites no claim, and lists the claims when it does", () => {
    show(FIXTURE_ROW);
    expect(screen.getAllByText("No claim is cited for this requirement.").length).toBe(4);
    expect(screen.getByText("dream_b_cap")).toBeDefined();
    expect(screen.getByText("dream_close_email")).toBeDefined();
  });

  /**
   * INV-2 · `not_applicable` and an unmet requirement are opposite findings, so
   * the applicability the API sends is rendered in words rather than left for a
   * reader to infer from the verdict chip beside it.
   */
  it("states applicability from the field the API sends, both ways round", () => {
    show(FIXTURE_ROW);
    expect(screen.getAllByText("yes — this requirement arises here")).toHaveLength(3);
    expect(
      screen.getAllByText("no — this requirement does not arise for this position at this date"),
    ).toHaveLength(2);
  });

  it("renders a tracker label when one is supplied, and a dash when it is not", () => {
    show(SWAY_ROW);
    expect(screen.getByText("unchanged since FY2024")).toBeDefined();
    cleanup();
    show(FIXTURE_ROW);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});

describe("gaps and approval", () => {
  it("renders each gap with its kind", () => {
    show(SWAY_ROW);
    expect(screen.getByText("with counsel")).toBeDefined();
    expect(screen.getByText("referenced, location unspecified")).toBeDefined();
  });

  it("says when no gap observation is recorded", () => {
    show({ ...FIXTURE_ROW, gaps: [] });
    expect(screen.getByText("No gap observation is recorded for this holding.")).toBeDefined();
  });

  it("renders approval state without offering an approve action", () => {
    const { container } = show(SWAY_ROW);
    expect(screen.getByText(/valuation approval · approved/)).toBeDefined();
    expect(screen.getByText("counts as approved fair value")).toBeDefined();
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });

  it("reports the absence of an approval as a fact", () => {
    show(FIXTURE_ROW);
    expect(screen.getByText("no approval recorded")).toBeDefined();
    expect(screen.getByText("not an approved fair value")).toBeDefined();
  });
});
