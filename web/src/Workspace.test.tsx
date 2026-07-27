import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { HoldingRow } from "./contracts";
import { FIXTURE_ROW } from "./fixture";
import { POOLSIDE_ROW, REALISED_ROW, SWAY_ROW } from "./testdata";
import { Workspace } from "./Workspace";

afterEach(cleanup);

function show(row: HoldingRow) {
  return render(<Workspace row={row} />);
}

/** The value under one meta label, read out of its own row. */
function metaValue(scope: Element, label: string): string | undefined {
  const row = [...scope.querySelectorAll(".meta > div")].find(
    (item) => item.querySelector("dt")?.textContent === label,
  );
  return row?.querySelector("dd")?.textContent ?? undefined;
}

function held(container: HTMLElement): string | undefined {
  return metaValue(container, "held at measurement date");
}

describe("the mark", () => {
  it("presents reported, stored, recomputed and support as four facts", () => {
    const { container } = show(FIXTURE_ROW);
    expect(screen.getByText("The mark", { selector: "h2" })).toBeDefined();
    expect(screen.getByText("Reported — tracker")).toBeDefined();
    // "Validated — confirmed and stored", not "independently derived": the
    // recomputed column is what derives independently, and two captions
    // claiming the same job — one of them empty on every row in this fund —
    // is the collapse the four-way split exists to prevent.
    expect(screen.getByText("Validated — confirmed and stored")).toBeDefined();
    // The fourth: what the cited evidence derives when the page is READ. It is
    // neither the tracker's figure nor a stored confirmation, and merging it
    // into either would be the collapse the caption exists to prevent.
    expect(screen.getByText(/Recomputed from the evidence/)).toBeDefined();
    expect(screen.getByText("Support — evidence verdicts")).toBeDefined();
    // Four captions carry the distinction; INV-13's argument for it is on the
    // mark beside the heading rather than in a paragraph under it.
    expect(container.querySelector(".section__head .why")?.getAttribute("title")).toMatch(
      /Four facts, not one/,
    );
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
    expect(container.querySelector(".support__reasons")?.textContent).toBe(
      "R1 missingR2 insufficient",
    );
    expect(container.querySelector(".figure--support .sub")?.getAttribute("title")).toMatch(
      /Decided by the API/,
    );
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
    // The lineage leaf and the evidence workspace render a SourceFact through
    // one component, so a cited input names the field it fills here too.
    expect(screen.getByText("price_per_share")).toBeDefined();
    expect(screen.getByText("characters 120–152")).toBeDefined();
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
    const { container } = show(FIXTURE_ROW);
    expect(held(container)).toBe("yes");
    cleanup();
    show(SWAY_ROW);
    expect(screen.getByText(/not an input to the held-at-date total/)).toBeDefined();
  });

  /**
   * A realised position carries no mark, and the oracle says so:
   * `evals/oracle/derived.json` has Jackpocket at 2024-12-31 with
   * `reported_amount: null`. The absence has to be rendered AS an absence — the
   * failure being prevented is a zero, or a blank that reads as one, or the
   * previous mark carried forward into a date it does not speak for.
   */
  it("states that a realised row has no mark instead of showing a figure", () => {
    const { container } = show(REALISED_ROW);
    expect(container.querySelectorAll(".no-mark")).toHaveLength(2);
    expect(screen.getByText("Reported and stored — neither exists")).toBeDefined();
    expect(screen.getAllByText(/Not zero, and not the last mark carried forward/).length).toBe(1);
    expect(screen.queryByText("Reported — tracker")).toBeNull();
    expect(container.querySelector(".figure--validated")).toBeNull();
    // No amount of any kind reaches the screen, so there is nothing to mistake
    // for a mark of zero.
    expect(container.textContent).not.toContain("USD");
  });

  /**
   * Support is a judgement about evidence, not about a mark, so it is still
   * answerable for a row that has none — and the meta block drops the three
   * fields that are properties of a mark rather than rendering them empty.
   */
  it("still reports support for a row with no mark, and drops the mark's own fields", () => {
    const { container } = show(REALISED_ROW);
    expect(container.querySelector(".support--unsupported")).not.toBeNull();
    expect(container.querySelector(".support__reasons")?.textContent).toBe(
      "R1 not assessedR2 not assessed",
    );
    const labels = [...container.querySelectorAll(".meta dt")].map((dt) => dt.textContent);
    expect(labels).toEqual(["position type", "held at measurement date", "mark"]);
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

  /**
   * The four uncited requirements on this row are not one finding. R1 arises and
   * is short; R3 and R4 do not arise; R5 is met from the execution status of the
   * claims cited at R2 and cites nothing of its own (INV-4). One sentence for all
   * four read as four omissions, three of which are not.
   */
  it("separates a short requirement from one not required and one met uncited", () => {
    const { container } = show(FIXTURE_ROW);
    expect(container.querySelectorAll(".uncited")).toHaveLength(1);
    expect(screen.getByText("No claim is cited, and this requirement is short.")).toBeDefined();
    expect(screen.getAllByText("No citation is required here.")).toHaveLength(2);
    const met = screen.getByText(/Met without a citation/);
    expect(met.title).toMatch(/labelling requirement/);
    // And the requirement that does cite claims lists them.
    expect(screen.getByText("dream_b_cap")).toBeDefined();
    expect(screen.getByText("dream_close_email")).toBeDefined();
  });

  /**
   * INV-2 · `not_applicable` and an unmet requirement are opposite findings, so
   * the applicability the API sends is rendered in words rather than left for a
   * reader to infer from the verdict chip beside it.
   */
  it("states applicability from the field the API sends, both ways round", () => {
    const { container } = show(FIXTURE_ROW);
    const applicable = [...container.querySelectorAll(".check")].map((check) =>
      metaValue(check, "applicable"),
    );
    expect(applicable).toEqual([
      "yes",
      "yes",
      "no · does not arise here",
      "no · does not arise here",
      "yes",
    ]);
    // INV-2 · why the two are opposite findings rather than degrees of one.
    expect(container.querySelector(".check .meta dt[title]")?.getAttribute("title")).toBeDefined();
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

  // Named "without offering an approve action" while the workspace had grown
  // one. What it actually pins is that the control is absent when the
  // deployment names NO ACTORS — `show()` passes none — which is the mechanism
  // keeping the public demo read-only. Under the old name the test read as
  // proof that no approve action exists anywhere, which is the opposite of
  // true, and a reader trusting it would not have looked for `api/decisions.py`.
  it("renders approval state, and offers no control when no actor is configured", () => {
    const { container } = show(SWAY_ROW);
    expect(screen.getByText(/valuation approval · approved/)).toBeDefined();
    expect(screen.getByText("counts as approved fair value")).toBeDefined();
    // Decision controls specifically, not every button on the page. This
    // counted ALL buttons, which held only while nothing else on the surface
    // was interactive — the `?` disclosures made it fail without the property
    // it guards having changed. A test whose subject is wider than its claim
    // goes red for the wrong reason, and the temptation is then to widen the
    // claim to match.
    expect(container.querySelectorAll(".decide__act")).toHaveLength(0);
  });

  it("reports the absence of an approval as a fact", () => {
    show(FIXTURE_ROW);
    expect(screen.getByText("no approval recorded")).toBeDefined();
    expect(screen.getByText("not an approved fair value")).toBeDefined();
  });
});
