import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { GapObservation, RequirementAssessment } from "./contracts";
import type { EvidenceClaim, EvidenceFact } from "./responses";
import { CITED_CLAIM, UNCITED_CLAIM } from "./testdata";

async function mount(
  assessments: RequirementAssessment[],
  claims: EvidenceClaim[],
  gaps: GapObservation[] = [],
) {
  vi.stubEnv("VITE_API_BASE_URL", "");
  vi.resetModules();
  const { EvidenceTrail } = await import("./Trail");
  return render(<EvidenceTrail assessments={assessments} claims={claims} gaps={gaps} />);
}

/**
 * One R1 figure at a declared directness, cited to a distinct span.
 *
 * The span is derived from the id so no two figures share one: the pane keys
 * its scroll on the span, and two figures at the same offsets would make "the
 * pane followed the click" indistinguishable from "the pane did not move".
 */
function rankedFact(id: number, fieldName: string, value: string, rank: number): EvidenceFact {
  const first = CITED_CLAIM.facts[0];
  if (first === undefined) throw new Error("the cited claim states a figure");
  return {
    ...first,
    id,
    field_name: fieldName,
    value_text: value,
    answers_requirements: ["R1"],
    answer_rank: { R1: rank },
    citation: { ...first.citation, span_start: id, span_end: id + 10 },
  };
}

const BASE: RequirementAssessment = {
  requirement: "R1",
  verdict: "sufficient",
  reason_codes: [],
  next_actions: [],
  evidence: [],
  pro_forma: false,
  tracker_label: null,
  policy_version: "v1",
  applicable: true,
};

const CITES_R1: RequirementAssessment = {
  ...BASE,
  evidence: [{ claim: CITED_CLAIM, is_subsequent: false }],
};

const R2_MISSING: RequirementAssessment = {
  ...BASE,
  requirement: "R2",
  verdict: "missing",
  reason_codes: ["NO_APPLICABLE_SUPPORT_NOT_LOCATED"],
  next_actions: ["REQUEST_FROM_COMPANY"],
};

beforeEach(() => {
  vi.unstubAllEnvs();
  Element.prototype.scrollIntoView = vi.fn();
  // jsdom keeps ONE location per test file, so a case that navigated the trail
  // leaves its link in the hash and the next mount opens where the last one
  // finished. Right in a browser, wrong as a starting state for a test.
  window.location.hash = "";
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("the evidence trail", () => {
  it("opens on the first requirement and leads with the figures that answer it", async () => {
    const { container } = await mount([CITES_R1, R2_MISSING], [CITED_CLAIM]);
    expect(container.querySelector(".rail__item--on")?.textContent).toMatch(/R1/);
    // `security_class` answers R1 and `price_per_share` answers R2. Both are on
    // the cited claim and both are reachable; the R1 one leads and the R2 one
    // is under the disclosure, which is the whole change.
    const leading = [...container.querySelectorAll(".trail__group .figrow__field")]
      .filter((el) => el.closest(".trail__other") === null)
      .map((el) => el.textContent);
    expect(leading).toEqual(["security_class"]);
    const behind = [...container.querySelectorAll(".trail__other .figrow__field")].map(
      (el) => el.textContent,
    );
    expect(behind).toEqual(["price_per_share"]);
    // The first ANSWERING figure is open, so the passage pane opens on the
    // sentence R1 rests on rather than on whichever figure the shared document
    // happened to state first.
    await waitFor(() => {
      expect(container.querySelector(".passage")).not.toBeNull();
    });
    const answering = CITED_CLAIM.facts.find((f) => f.field_name === "security_class");
    if (answering === undefined) throw new Error("the cited claim states an R1 figure");
    expect(container.querySelector(".offsets")?.textContent).toBe(
      `chars ${answering.citation.span_start}–${answering.citation.span_end}`,
    );
  });

  /**
   * The defect the owner found by using the product: the ledger binds a CLAIM
   * to a requirement, so one agreement relied upon for two requests rendered
   * every one of its figures under both and opened the same passage twice.
   *
   * Asserted as a DIFFERENCE between the two requirements rather than as two
   * fixed lists, because a map that declared everything for everything would
   * satisfy two fixed lists and fail this.
   */
  it("shows a different passage for two requirements citing the same document", async () => {
    const citesBoth: RequirementAssessment = {
      ...BASE,
      requirement: "R2",
      evidence: [{ claim: CITED_CLAIM, is_subsequent: false }],
    };
    const { container } = await mount([CITES_R1, citesBoth], [CITED_CLAIM]);
    const openedOnR1 = container.querySelector(".offsets")?.textContent;
    screen.getByRole("button", { name: /R2/ }).click();
    await waitFor(() => {
      expect(container.querySelector(".rail__item--on")?.textContent).toMatch(/R2/);
    });
    const openedOnR2 = container.querySelector(".offsets")?.textContent;
    expect(openedOnR1).toBeDefined();
    expect(openedOnR2).not.toBe(openedOnR1);
  });

  /**
   * A figure that answers none of the four requests is a DECLARED judgement —
   * `requirements_for` raises on a field nobody has ruled on rather than
   * returning an empty set — so it is labelled as reviewed, not as unknown.
   */
  it("says of a figure that answers no request that it answers no request", async () => {
    const answersNothing: EvidenceClaim = {
      ...CITED_CLAIM,
      facts: CITED_CLAIM.facts.map((fact) => ({ ...fact, answers_requirements: [] })),
    };
    const cites: RequirementAssessment = {
      ...BASE,
      evidence: [{ claim: answersNothing, is_subsequent: false }],
    };
    const { container } = await mount([cites], [answersNothing]);
    expect(screen.getByText(/none of them is declared as answering/)).toBeDefined();
    expect(container.querySelectorAll(".figrow__answers--none")).toHaveLength(2);
  });

  /**
   * The pane opens on the figure that IS the answer, not on whichever one the
   * extractor happened to emit first. Fluidstack's purchase agreement answers
   * existence and cost with ten figures and only one of them answers "what did
   * the fund pay"; landing on `agreement_date` when the question is about money
   * is not a judgement, it is the absence of one.
   *
   * The three below are deliberately in the WRONG arrival order, so a pane that
   * dropped the ordering would open on the date and this would go red.
   */
  it("opens on the figure that most directly answers the requirement", async () => {
    const ranked: EvidenceClaim = {
      ...CITED_CLAIM,
      facts: [
        rankedFact(31, "agreement_date", "October 10, 2024", 16),
        rankedFact(32, "fund_aggregate_purchase_price", "$1,000,000.00", 0),
        rankedFact(33, "fund_shares", "100,000", 1),
      ],
    };
    const cites: RequirementAssessment = {
      ...BASE,
      evidence: [{ claim: ranked, is_subsequent: false }],
    };
    const { container } = await mount([cites], [ranked]);
    const order = [...container.querySelectorAll(".figrow__field")].map((el) => el.textContent);
    expect(order).toEqual(["fund_aggregate_purchase_price", "fund_shares", "agreement_date"]);
    await waitFor(() => {
      expect(container.querySelector(".figrow--on")?.textContent).toMatch(
        /fund_aggregate_purchase_price/,
      );
    });
  });

  /**
   * A rank arrives for every request a figure answers, so an absent one cannot
   * happen on a well-formed response. It must sort LAST anyway: a missing key
   * that read as rank zero would promote whatever the API failed to describe to
   * the top of the pane, which is the worst available place for it.
   */
  it("sorts a figure the API sent no rank for last, never first", async () => {
    const unranked: EvidenceClaim = {
      ...CITED_CLAIM,
      facts: [
        { ...rankedFact(41, "signature_block", "/s/", 0), answer_rank: {} },
        rankedFact(42, "fund_aggregate_purchase_price", "$1,000,000.00", 0),
      ],
    };
    const cites: RequirementAssessment = {
      ...BASE,
      evidence: [{ claim: unranked, is_subsequent: false }],
    };
    const { container } = await mount([cites], [unranked]);
    const order = [...container.querySelectorAll(".figrow__field")].map((el) => el.textContent);
    expect(order).toEqual(["fund_aggregate_purchase_price", "signature_block"]);
  });

  it("moves to another requirement when its rail entry is chosen", async () => {
    const { container } = await mount([CITES_R1, R2_MISSING], [CITED_CLAIM]);
    screen.getByRole("button", { name: /R2/ }).click();
    await waitFor(() => {
      expect(container.querySelector(".rail__item--on")?.textContent).toMatch(/R2/);
    });
    // R2 cites nothing, so there are no figures and no passage — and the gap
    // block takes their place rather than the pane going empty.
    expect(container.querySelectorAll(".figrow")).toHaveLength(0);
    expect(container.querySelector(".passage")).toBeNull();
    expect(container.querySelector(".gaw")).not.toBeNull();
    expect(screen.getByText("REQUEST_FROM_COMPANY")).toBeDefined();
  });

  /**
   * The connection between a figure and its sentence has to be made by clicking
   * the figure, or the trail is three lists that happen to be beside each other.
   */
  it("opens the chosen figure's own passage", async () => {
    const { container } = await mount([CITES_R1], [CITED_CLAIM]);
    const second = CITED_CLAIM.facts[1];
    if (second === undefined) throw new Error("the cited claim has two facts");
    screen.getByRole("button", { name: /security_class/ }).click();
    await waitFor(() => {
      expect(container.querySelector(".figrow--on")?.textContent).toMatch(/security_class/);
    });
    // Read off the passage header specifically. The figure row states the same
    // offsets, and asserting the string appears somewhere cannot tell the pane
    // that followed the click from the row that was clicked.
    expect(container.querySelector(".offsets")?.textContent).toBe(
      `chars ${second.citation.span_start}–${second.citation.span_end}`,
    );
  });

  /**
   * An uncited document is where a discrepancy survives review: it is on file,
   * it looks like support, and no figure in the packet rests on it. So it is
   * reachable, and only when there is one.
   */
  it("offers the documents no requirement cites, and only when there are some", async () => {
    const { container } = await mount([CITES_R1], [CITED_CLAIM, UNCITED_CLAIM]);
    expect(screen.getByRole("button", { name: /documents no requirement cites/ })).toBeDefined();
    cleanup();
    const allCited = await mount([CITES_R1], [CITED_CLAIM]);
    expect(allCited.queryByText(/documents no requirement cites/)).toBeNull();
    expect(container).toBeDefined();
  });

  it("says a requirement that does not arise is not a gap", async () => {
    const { container } = await mount(
      [{ ...BASE, verdict: "not_applicable", applicable: false }],
      [],
    );
    expect(screen.getByText(/Not a gap/)).toBeDefined();
    expect(container.querySelector(".gaw")).toBeNull();
  });

  /**
   * "no claim cited" said three different things, and only one of them is a
   * finding. A partner scanning the rail for what is wrong was reading the same
   * phrase under a met requirement, an inapplicable one and a real shortfall.
   */
  it("distinguishes not required, met without a citation, and a real shortfall", async () => {
    const { container } = await mount(
      [
        { ...BASE, requirement: "R1", verdict: "missing", applicable: true },
        { ...BASE, requirement: "R3", verdict: "not_applicable", applicable: false },
        { ...BASE, requirement: "R5", verdict: "sufficient", applicable: true },
      ],
      [],
    );
    const details = [...container.querySelectorAll(".rail__detail")].map((el) => ({
      text: el.textContent,
      className: el.className,
    }));
    expect(details).toEqual([
      { text: "nothing cited", className: "rail__detail rail__detail--short" },
      { text: "no assessment in the packet", className: "rail__detail" },
      { text: "no citation required here", className: "rail__detail rail__detail--not_required" },
      { text: "no assessment in the packet", className: "rail__detail" },
      { text: "met without a citation", className: "rail__detail rail__detail--met" },
    ]);
    // Why R5 cites nothing survives, one hover away.
    expect(container.querySelector(".rail__detail--met")?.getAttribute("title")).toMatch(
      /labelling requirement/,
    );
  });

  it("says a sufficient requirement has no gap block", async () => {
    const { container } = await mount([CITES_R1], [CITED_CLAIM]);
    expect(container.querySelector(".gaw")).toBeNull();
  });

  /**
   * The common state for this fund, and the one that must not read as a screen
   * that failed to load.
   */
  it("states an empty middle column instead of leaving a void", async () => {
    await mount([{ ...R2_MISSING, requirement: "R1" }], []);
    expect(screen.getByText(/No claim on file is cited for this requirement/)).toBeDefined();
  });

  /**
   * The point of the whole deep link: a partner sends the PASSAGE, not
   * directions to it. Every step in "open the app, pick 25Q4, click Fluidstack,
   * click fair value, click the price" is a step a recipient can take wrongly,
   * and only the sender ever sees them work.
   */
  it("opens on the requirement and the figure a link names", async () => {
    const second = CITED_CLAIM.facts[1];
    if (second === undefined) throw new Error("the cited claim has two facts");
    const citesR2: RequirementAssessment = {
      ...BASE,
      requirement: "R2",
      evidence: [{ claim: CITED_CLAIM, is_subsequent: false }],
    };
    window.location.hash = `#/fund_ii/fund_ii_25q4/company/poolside/R2/${encodeURIComponent(
      `${CITED_CLAIM.id}:${second.id}`,
    )}`;
    const { container } = await mount([CITES_R1, citesR2], [CITED_CLAIM]);
    await waitFor(() => {
      expect(container.querySelector(".rail__item--on")?.textContent).toMatch(/R2/);
    });
    // The named figure, not the first one R2 happens to answer.
    expect(container.querySelector(".figrow--on")?.textContent).toMatch(/security_class/);
    expect(container.querySelector(".offsets")?.textContent).toBe(
      `chars ${second.citation.span_start}–${second.citation.span_end}`,
    );
  });

  /**
   * The path is POSITIONAL, so this pane can only fill in its own segments once
   * the ones above it exist — which in the app they do, because `App` writes the
   * fund-period and `Surfaces` writes the surface and the holding before this
   * component is ever mounted. Set up here for the same reason.
   */
  it("writes the requirement it is showing into the address bar", async () => {
    window.location.hash = "#/fund_ii/fund_ii_25q4/company/poolside";
    await mount([CITES_R1, R2_MISSING], [CITED_CLAIM]);
    screen.getByRole("button", { name: /R2/ }).click();
    await waitFor(() => {
      expect(window.location.hash).toBe("#/fund_ii/fund_ii_25q4/company/poolside/R2");
    });
  });

  it("offers the link to copy, and shows it when the clipboard refuses", async () => {
    // Only the clipboard. Replacing the whole `navigator` takes jsdom's and
    // React's out with it, and the test then measures a render that never
    // happened rather than a refusal that did.
    Object.defineProperty(window.navigator, "clipboard", {
      value: undefined,
      configurable: true,
    });
    const { container } = await mount([CITES_R1], [CITED_CLAIM]);
    await waitFor(() => {
      expect(container.querySelector(".trail__share")).not.toBeNull();
    });
    screen.getByRole("button", { name: /Copy a link to this passage/ }).click();
    // A button that silently does nothing is worse than one that hands over the
    // text: a clipboard write can be refused by the origin, the browser or the
    // viewer, and none of those is visible to the person clicking.
    await waitFor(() => {
      expect(container.querySelector(".trail__share-url")).not.toBeNull();
    });
  });

  it("reports a requirement the packet has no assessment for", async () => {
    const { container } = await mount([CITES_R1], [CITED_CLAIM]);
    screen.getByRole("button", { name: /R4/ }).click();
    await waitFor(() => {
      expect(screen.getByText(/carries no assessment for this requirement/)).toBeDefined();
    });
    expect(container.querySelector(".gaw")).toBeNull();
  });
});
