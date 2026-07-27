import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { RecomputedCell, RecomputedMark } from "./Recomputation";
import {
  CIRCULAR_RECOMPUTATION,
  DISAGREEING_RECOMPUTATION,
  SILENT_RECOMPUTATION,
} from "./testdata";

/**
 * The screen for the finding SPEC §8's validators produce and nothing served.
 *
 * Every assertion here is about a WORD as much as a number. "Derived 2,500,000
 * against a reported 6,000,000" is a finding; "validated: 2,500,000" is a claim
 * this system has not earned, and the difference between the two is the only
 * thing standing between an independent check and an unearned assurance.
 */

afterEach(cleanup);

describe("the recomputation", () => {
  it("shows the derived figure, the reported one, and the distance between them", () => {
    render(<RecomputedMark recomputation={DISAGREEING_RECOMPUTATION} />);
    expect(screen.getByText("2,500,000.0000 USD")).toBeDefined();
    expect(screen.getByText(/3,500,000.0000 USD apart from the reported figure/)).toBeDefined();
    expect(screen.getByText(/disagrees with the reported figure/)).toBeDefined();
  });

  /**
   * The label carries as much weight as the number. Nothing has approved this,
   * it is recomputed on every read, and `mark.validated_amount` is deliberately
   * still empty — so the surface must not use the word that would say otherwise.
   */
  it("never calls a recomputed figure validated, verified or approved", () => {
    const { container } = render(<RecomputedMark recomputation={DISAGREEING_RECOMPUTATION} />);
    // The LABELS, not the prose. The explanation behind the `?` is allowed —
    // and required — to say what this is NOT; what must never appear is a
    // caption or a verdict that calls a read-time derivation a confirmed one.
    // So the explanation is removed before reading, rather than the assertion
    // being weakened until both pass.
    const copy = container.cloneNode(true) as HTMLElement;
    for (const why of copy.querySelectorAll(".why-wrap")) why.remove();
    const labels = [
      ...copy.querySelectorAll(".figure__caption, .figure__amount, .sub, .recheck__delta"),
    ]
      .map((el) => el.textContent ?? "")
      .join(" ");
    expect(labels).toMatch(/Recomputed from the evidence/);
    for (const forbidden of [/\bvalidat/i, /\bverified\b/i, /\bapproved\b/i, /\bcorrect\b/i]) {
      expect(labels).not.toMatch(forbidden);
    }
  });

  /**
   * Fluidstack's finding is only legible per class: the reported 6,000,000 is
   * 200,000 shares at the $30.00 Series B price applied to every class, and one
   * total hides which half is wrong.
   */
  it("shows the per-class working rather than one total", () => {
    const { container } = render(<RecomputedMark recomputation={DISAGREEING_RECOMPUTATION} />);
    const working = [...container.querySelectorAll(".recheck-working li")].map(
      (li) => li.textContent,
    );
    expect(working).toHaveLength(2);
    expect(working[0]).toMatch(/100,000 series_a at 10.000000/);
    expect(working[1]).toMatch(/100,000 series_a2 at 15.000000/);
  });

  /**
   * Moonfare FY2024. The evidence is not silent — it is the fund speaking about
   * its own position, and `pass` is what that circularity produces if nothing
   * stops it. The word for it exists in SPEC §8 and had never reached a screen.
   */
  it("says of a circular figure that the fund is the author of both", () => {
    render(<RecomputedMark recomputation={CIRCULAR_RECOMPUTATION} />);
    expect(screen.getByText(/the fund is the author of both/)).toBeDefined();
    expect(screen.getByText("1,048,515.0000 USD")).toBeDefined();
    // Equal figures, and NOT reported as agreement.
    expect(screen.queryByText(/agrees with the reported figure/)).toBeNull();
  });

  it("distinguishes evidence that is silent from a check nobody ran", () => {
    const { container } = render(<RecomputedMark recomputation={SILENT_RECOMPUTATION} />);
    expect(screen.getByText(/the evidence does not say/)).toBeDefined();
    expect(screen.getByText("no figure")).toBeDefined();
    cleanup();
    // No recomputation at all is a MISSING RESPONSE and says so, rather than
    // rendering as a finding that the mark could not be checked.
    render(<RecomputedMark recomputation={undefined} />);
    expect(screen.getByText("not supplied by API")).toBeDefined();
    expect(container).toBeDefined();
  });

  /**
   * A reader scanning eight rows for what is wrong is looking for a number that
   * should not be there, so the compact form leads with the difference — and
   * only ever where there is one.
   */
  it("carries the difference into the dashboard cell, and only where there is one", () => {
    render(<RecomputedCell recomputation={DISAGREEING_RECOMPUTATION} />);
    expect(screen.getByText(/off by 3,500,000.0000 USD/)).toBeDefined();
    cleanup();
    // Moonfare's figures are equal and its outcome is not `fail`; a delta of
    // zero on that row would read as a check that passed.
    render(<RecomputedCell recomputation={CIRCULAR_RECOMPUTATION} />);
    expect(screen.queryByText(/off by/)).toBeNull();
  });

  it("gives an outcome the API has no gloss for the API's own word, not a blank", () => {
    render(<RecomputedCell recomputation={{ ...SILENT_RECOMPUTATION, outcome: "invented" }} />);
    expect(screen.getByText(/no gloss is recorded for this outcome/)).toBeDefined();
  });
});
