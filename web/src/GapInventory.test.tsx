import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FIXTURE_PACKET } from "./fixture";
import { GapInventory } from "./GapInventory";
import { TWO_ROW_PACKET } from "./testdata";

afterEach(cleanup);

describe("GapInventory", () => {
  it("keeps the three kinds apart instead of collapsing them to missing", () => {
    render(<GapInventory packet={TWO_ROW_PACKET} />);
    expect(screen.getAllByText("with counsel").length).toBeGreaterThan(0);
    expect(screen.getAllByText("referenced, location unspecified").length).toBeGreaterThan(0);
    expect(screen.getAllByText("not located").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Request from counsel/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Establish custody before requesting/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Request from the company/).length).toBeGreaterThan(0);
  });

  it("renders every gap in the packet, attributed to its company", () => {
    render(<GapInventory packet={TWO_ROW_PACKET} />);
    expect(screen.getByText("Series A-1 acquisition docs")).toBeDefined();
    expect(screen.getByText("Series A purchase agreement")).toBeDefined();
    expect(screen.getByText("board consent")).toBeDefined();
    expect(screen.getAllByText("Sway").length).toBe(2);
    expect(screen.getByText("Dream")).toBeDefined();
  });

  it("still shows a kind with no observations, rather than dropping the heading", () => {
    render(<GapInventory packet={FIXTURE_PACKET} />);
    expect(
      screen.getAllByText("No observation of this kind is recorded in this packet."),
    ).toHaveLength(2);
    expect(screen.getByText("Series A-1 acquisition docs")).toBeDefined();
  });

  /**
   * Three counts, all from the API, and all in units of POSITIONS rather than
   * observations. The third used to be described here as a subtraction the
   * screen was not allowed to do; the API sends it now, so it is rendered.
   */
  it("takes its position counts from the API and says they count positions, not observations", () => {
    render(<GapInventory packet={TWO_ROW_PACKET} />);
    expect(screen.getByText("unsupported positions held at this date (API)")).toBeDefined();
    expect(screen.getByText("packet gap positions, held or not (API)")).toBeDefined();
    expect(screen.getByText("unsupported but not held at this date (API)")).toBeDefined();
    expect(screen.getByText(/not a count of the observations below/)).toBeDefined();
  });

  it("says which store the gaps came from", () => {
    render(<GapInventory packet={TWO_ROW_PACKET} />);
    expect(screen.getByText(/source · fixture — not the fund/)).toBeDefined();
  });
});
