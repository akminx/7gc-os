import { afterEach, describe, expect, it } from "vitest";

import { formatTrail, readTrail, trailHref, updateTrail } from "./deeplink";

/**
 * The link a partner sends an auditor instead of directions to a passage.
 *
 * Every case here is about a link a RECIPIENT opens. The sender always sees
 * theirs work — they are already on the page — so the failures worth guarding
 * are the ones only the other person meets: a truncated link, a hand-edited
 * one, a segment naming something the vocabulary does not contain.
 */

afterEach(() => {
  window.location.hash = "";
});

describe("the evidence-trail link", () => {
  it("carries the whole path from fund-period to figure", () => {
    const trail = {
      fundId: "fund_ii",
      periodId: "fund_ii_25q4",
      surface: "company" as const,
      holdingId: "fund_ii_fluidstack",
      requirement: "R2" as const,
      fact: "fund_ii_fluidstack:series_a_price:17",
    };
    const hash = formatTrail(trail);
    expect(hash).toBe(
      "#/fund_ii/fund_ii_25q4/company/fund_ii_fluidstack/R2/" +
        encodeURIComponent("fund_ii_fluidstack:series_a_price:17"),
    );
    expect(readTrail(hash)).toEqual(trail);
  });

  /**
   * A fact key is `claimId:factId`, and a colon in a path segment is a segment
   * separator waiting to happen. Encoded on the way out and decoded on the way
   * back, so the round trip is the identity rather than nearly it.
   */
  it("survives a figure key containing the separator", () => {
    const fact = "fund_ii_lucra:series_a1_price:4";
    expect(readTrail(formatTrail({ fundId: "f", fact }))).not.toHaveProperty("fact");
    const full = formatTrail({
      fundId: "fund_ii",
      periodId: "p",
      surface: "company",
      holdingId: "h",
      requirement: "R1",
      fact,
    });
    expect(readTrail(full).fact).toBe(fact);
  });

  /**
   * Positional, so a missing middle segment truncates rather than shifting: a
   * figure with no requirement above it would land in the requirement's slot
   * and be read as one.
   */
  it("stops at the first segment it does not carry, rather than shifting the rest up", () => {
    expect(formatTrail({ fundId: "fund_ii", periodId: "p", holdingId: "h" })).toBe("#/fund_ii/p");
    expect(formatTrail({})).toBe("#/");
    expect(readTrail("#/")).toEqual({});
  });

  /**
   * A hand-edited or truncated link has to land somewhere real. A `surface` of
   * "compnay" must not reach the app as a surface — a blank page with no
   * explanation is what a cast would produce.
   */
  it("ignores a segment the closed vocabulary does not contain", () => {
    const trail = readTrail("#/fund_ii/p/compnay/h/R9/x");
    expect(trail.fundId).toBe("fund_ii");
    expect(trail.surface).toBeUndefined();
    // And everything after an unrecognised segment is still read, because the
    // positions are fixed: dropping the rest would lose a holding the link
    // names over a typo in a different field.
    expect(trail.holdingId).toBe("h");
    expect(trail.requirement).toBeUndefined();
  });

  /**
   * An absent segment stays absent. Filling in R1 here would make "open this
   * company" and "open this company at R1" indistinguishable, including to the
   * reader, who would have no way to tell which one they were sent.
   */
  it("does not invent a default for a segment the link omits", () => {
    const trail = readTrail("#/fund_ii/fund_ii_25q4/company/fund_ii_lucra");
    expect(trail.holdingId).toBe("fund_ii_lucra");
    expect(trail.requirement).toBeUndefined();
    expect(trail.fact).toBeUndefined();
  });

  /**
   * Two components own different segments of one path. A module holding its own
   * copy is how one of them overwrites the other's segment with a value it read
   * before the other moved, so every update re-reads the address bar.
   */
  it("merges a patch into whatever the address bar currently says", () => {
    updateTrail({ fundId: "fund_ii", periodId: "fund_ii_25q4", surface: "company" });
    updateTrail({ holdingId: "fund_ii_lucra" });
    updateTrail({ requirement: "R2" });
    expect(readTrail()).toEqual({
      fundId: "fund_ii",
      periodId: "fund_ii_25q4",
      surface: "company",
      holdingId: "fund_ii_lucra",
      requirement: "R2",
    });
  });

  it("clears the segments below one that is explicitly dropped", () => {
    updateTrail({
      fundId: "fund_ii",
      periodId: "p",
      surface: "company",
      holdingId: "h",
      requirement: "R2",
      fact: "c:1",
    });
    updateTrail({ requirement: "R4", fact: undefined });
    expect(readTrail().requirement).toBe("R4");
    expect(readTrail().fact).toBeUndefined();
  });

  it("offers an absolute link, not a fragment", () => {
    updateTrail({ fundId: "fund_ii", periodId: "p" });
    const href = trailHref(readTrail());
    expect(href.startsWith("http")).toBe(true);
    expect(href.endsWith("#/fund_ii/p")).toBe(true);
  });
});
