import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { GapObservation, RequirementAssessment } from "./contracts";
import { GapAction, openRequirements } from "./Gap";

afterEach(cleanup);

const BASE: RequirementAssessment = {
  requirement: "R2",
  verdict: "missing",
  reason_codes: [],
  next_actions: [],
  evidence: [],
  pro_forma: false,
  tracker_label: null,
  policy_version: "v1",
  applicable: true,
};

/**
 * The two rows this whole component exists to keep apart, transcribed from
 * `GET /funds/fund_ii/periods/fund_ii_25q4/packet`: Moonfare's R2 and Because
 * Market's R2. Same verdict word, opposite findings, different letters.
 */
const EXPIRED: RequirementAssessment = {
  ...BASE,
  reason_codes: ["SUPPORT_OUTSIDE_ITS_OWN_RELIANCE_WINDOW"],
  next_actions: ["REQUEST_UPDATED_VALUATION"],
};

const NEVER_LOCATED: RequirementAssessment = {
  ...BASE,
  reason_codes: ["NO_APPLICABLE_SUPPORT_NOT_LOCATED"],
  next_actions: ["REQUEST_FROM_COMPANY"],
};

const WITH_COUNSEL: RequirementAssessment = {
  ...BASE,
  requirement: "R1",
  verdict: "partial",
  reason_codes: ["DOCUMENT_WITH_COUNSEL"],
  next_actions: ["REQUEST_FROM_COUNSEL"],
};

const COUNSEL_QUOTE =
  "The executed Series A-1 Stock Purchase Agreement and final closing capitalization table are on file with company counsel and have not been located in the Fund's document repository.";

const OBSERVATION: GapObservation = {
  id: 1,
  holding_id: "fund_ii_lucra",
  requirement: "R1",
  security_class: "series_a1",
  missing_document: "Series A-1 SPA",
  kind: "with_counsel",
  source_quote: COUNSEL_QUOTE,
  remediation: "open",
};

/** The three labels, in the order they were rendered. */
function lines(container: HTMLElement): string[] {
  return [...container.querySelectorAll(".gaw__label")].map((el) => el.textContent ?? "");
}

describe("the gap, the action and the why", () => {
  it("always renders the same three lines in the same order", () => {
    const { container } = render(<GapAction assessment={EXPIRED} gaps={[]} />);
    expect(lines(container)).toEqual(["missing", "action", "why"]);
    cleanup();
    // A gap observation, a different verdict, a different kind: still three
    // lines, still that order. The shape is the argument.
    const withQuote = render(<GapAction assessment={WITH_COUNSEL} gaps={[OBSERVATION]} />);
    expect(lines(withQuote.container)).toEqual(["partial", "action", "why"]);
  });

  /**
   * The one the brief names, and the one a redesign is most likely to undo.
   * `SUPPORT_OUTSIDE_ITS_OWN_RELIANCE_WINDOW` and `NO_APPLICABLE_SUPPORT_*` are
   * both verdict `missing`; one is a memo on file whose window has closed and
   * the other is a document nobody has ever found. The letters go to different
   * people, so nothing about the two blocks may render identically.
   */
  it("never renders expired support and absent support the same way", () => {
    const expired = render(<GapAction assessment={EXPIRED} gaps={[]} />);
    const expiredOrigin = expired.container.querySelector(".origin");
    const expiredAction = expired.container.querySelector(".gaw__to");
    expect(expiredOrigin?.className).toContain("origin--expired");
    expect(expiredOrigin?.textContent).toMatch(/existed and expired/);
    expect(expiredAction?.textContent).toMatch(/valuer/);
    cleanup();

    const absent = render(<GapAction assessment={NEVER_LOCATED} gaps={[]} />);
    const absentOrigin = absent.container.querySelector(".origin");
    const absentAction = absent.container.querySelector(".gaw__to");
    expect(absentOrigin?.className).toContain("origin--never_located");
    expect(absentOrigin?.className).not.toBe(expiredOrigin?.className);
    expect(absentOrigin?.textContent).not.toBe(expiredOrigin?.textContent);
    expect(absentAction?.textContent).not.toBe(expiredAction?.textContent);
    expect(absentAction?.textContent).toMatch(/portfolio company/);
  });

  /**
   * A document held by counsel EXISTS. Filing it under "nothing has ever been
   * located" is wrong on the facts and addresses the letter to a company that
   * is not holding the document, so it gets a third treatment rather than
   * sharing one with either neighbour.
   */
  it("separates a document held elsewhere from one never located", () => {
    const counsel = render(<GapAction assessment={WITH_COUNSEL} gaps={[OBSERVATION]} />);
    const origin = counsel.container.querySelector(".origin");
    expect(origin?.className).toContain("origin--held_elsewhere");
    expect(origin?.textContent).toMatch(/exists, and the fund does not hold it/);
    expect(counsel.container.querySelector(".gaw__to")?.textContent).toMatch(/counsel/);
  });

  it("sets the why as the fund's own sentence, verbatim and attributed", () => {
    const { container } = render(<GapAction assessment={WITH_COUNSEL} gaps={[OBSERVATION]} />);
    // Character for character. An ellipsis or a tightened phrase would turn the
    // fund's admission into this application's paraphrase of it.
    expect(container.querySelector(".verbatim")?.textContent).toBe(COUNSEL_QUOTE);
    expect(screen.getByText(/the fund's own record/)).toBeDefined();
    expect(screen.getByText("Series A-1 SPA")).toBeDefined();
    expect(screen.getByText("with counsel")).toBeDefined();
  });

  /**
   * The third line stays even when there is nothing to quote. A block that
   * silently loses a line teaches the reader that two lines is the normal shape
   * and that the quotation is decoration.
   */
  it("keeps the why line when no gap observation is recorded", () => {
    const { container } = render(<GapAction assessment={EXPIRED} gaps={[]} />);
    expect(lines(container)).toContain("why");
    expect(container.querySelector(".verbatim")).toBeNull();
    expect(screen.getByText(/No gap observation is recorded/)).toBeDefined();
  });

  it("matches the observation to its own requirement and not to another", () => {
    // The observation above is R1; this assessment is R2. Quoting it here would
    // attach a counsel letter about the SPA to a fair-value finding.
    const { container } = render(<GapAction assessment={NEVER_LOCATED} gaps={[OBSERVATION]} />);
    expect(container.querySelector(".verbatim")).toBeNull();
  });

  /**
   * `reason_codes` is an open vocabulary the policy owns. An unknown code is
   * rendered as the code rather than swallowed, because a lookup with a
   * friendly fallback is how an unrecognised finding becomes a reassuring
   * blank.
   */
  it("renders a code it has no gloss for, rather than dropping it", () => {
    const { container } = render(
      <GapAction
        assessment={{
          ...BASE,
          reason_codes: ["A_CODE_INVENTED_LATER"],
          next_actions: ["AN_ACTION_INVENTED_LATER"],
        }}
        gaps={[]}
      />,
    );
    expect(screen.getByText("A_CODE_INVENTED_LATER")).toBeDefined();
    expect(screen.getByText("AN_ACTION_INVENTED_LATER")).toBeDefined();
    // The code appears once, as the code. A gloss that repeats its own key
    // reads as a translation that happened to match rather than one that is
    // absent, so the gloss says the gloss is absent.
    expect([...container.querySelectorAll(".gaw__gloss")].map((el) => el.textContent)).toEqual([
      "no gloss is recorded for this code",
      "no gloss is recorded for this action",
    ]);
  });

  it("says so when the API recorded no reason and no action at all", () => {
    render(<GapAction assessment={BASE} gaps={[]} />);
    expect(screen.getByText(/records no reason code/)).toBeDefined();
    expect(screen.getByText(/No next action is recorded/)).toBeDefined();
  });
});

describe("which requirements are open", () => {
  /**
   * Two API fields decide it and nothing here does: a requirement that does not
   * arise is not a gap (INV-2), and a sufficient one has nothing outstanding.
   */
  it("excludes the inapplicable and the sufficient, and keeps the rest", () => {
    const open = openRequirements([
      { ...BASE, requirement: "R1", verdict: "sufficient" },
      { ...BASE, requirement: "R2", verdict: "missing" },
      { ...BASE, requirement: "R3", verdict: "partial" },
      { ...BASE, requirement: "R4", verdict: "not_applicable", applicable: false },
      { ...BASE, requirement: "R5", verdict: "not_assessed" },
    ]);
    expect(open.map((a) => a.requirement)).toEqual(["R2", "R3", "R5"]);
  });
});
