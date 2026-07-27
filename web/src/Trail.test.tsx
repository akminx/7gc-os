import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { GapObservation, RequirementAssessment } from "./contracts";
import type { EvidenceClaim } from "./responses";
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
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("the evidence trail", () => {
  it("opens on the first requirement and lists the figures its evidence states", async () => {
    const { container } = await mount([CITES_R1, R2_MISSING], [CITED_CLAIM]);
    expect(container.querySelector(".rail__item--on")?.textContent).toMatch(/R1/);
    const figures = [...container.querySelectorAll(".figrow__field")].map((el) => el.textContent);
    expect(figures).toEqual(["price_per_share", "security_class"]);
    // The first figure is open, so the passage pane is showing something.
    await waitFor(() => {
      expect(container.querySelector(".passage")).not.toBeNull();
    });
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

  it("reports a requirement the packet has no assessment for", async () => {
    const { container } = await mount([CITES_R1], [CITED_CLAIM]);
    screen.getByRole("button", { name: /R4/ }).click();
    await waitFor(() => {
      expect(screen.getByText(/carries no assessment for this requirement/)).toBeDefined();
    });
    expect(container.querySelector(".gaw")).toBeNull();
  });
});
