import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { CoverageMap } from "./Coverage";
import type { RequirementAssessment } from "./contracts";
import type { EvidenceClaim } from "./responses";
import { CITED_CLAIM, SUBSEQUENT_EVIDENCE, UNCITED_CLAIM } from "./testdata";

afterEach(cleanup);

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

const CITES: RequirementAssessment = {
  ...BASE,
  evidence: [{ claim: CITED_CLAIM, is_subsequent: false }],
};

const CLAIMS: EvidenceClaim[] = [CITED_CLAIM, UNCITED_CLAIM];

const ASSESSMENTS: RequirementAssessment[] = [
  { ...CITES, requirement: "R1" },
  { ...CITES, requirement: "R2" },
  { ...BASE, requirement: "R3", verdict: "missing" },
  { ...BASE, requirement: "R4", verdict: "not_applicable", applicable: false },
  { ...BASE, requirement: "R5", verdict: "not_applicable", applicable: false },
];

/** Each requirement column's foot mark, left to right. */
function feet(container: HTMLElement): string[] {
  return [...container.querySelectorAll(".cov__foot")].map((el) => el.textContent ?? "");
}

/** Each document row's use mark, top to bottom. */
function uses(container: HTMLElement): string[] {
  return [...container.querySelectorAll(".cov__use")].map((el) => el.textContent ?? "");
}

describe("the coverage map", () => {
  /**
   * The two things a list cannot show and a matrix shows without being asked: a
   * requirement nothing points at, and a document nothing points from.
   */
  it("marks a requirement with no cited claim as a gap", () => {
    const { container } = render(<CoverageMap claims={CLAIMS} assessments={ASSESSMENTS} />);
    expect(feet(container)).toEqual(["cited", "cited", "gap", "n/a", "n/a"]);
  });

  it("marks a claim no requirement cites as unused", () => {
    const { container } = render(<CoverageMap claims={CLAIMS} assessments={ASSESSMENTS} />);
    expect(uses(container)).toEqual(["in use", "unused"]);
    expect(container.querySelectorAll(".cov__row--unused")).toHaveLength(1);
  });

  /**
   * INV-2 · a requirement that does not arise is not a hole. R3 above is a gap
   * and R4 is not, and both columns are empty; only the foot tells them apart,
   * so it must never give them one mark.
   */
  it("never renders a requirement that does not arise as a gap", () => {
    const { container } = render(<CoverageMap claims={CLAIMS} assessments={ASSESSMENTS} />);
    const marks = [...container.querySelectorAll(".cov__foot")];
    const gap = marks.at(2);
    const na = marks.at(3);
    expect(gap?.textContent).not.toBe(na?.textContent);
    expect(gap?.className).not.toBe(na?.className);
    expect(na?.className).toContain("cov__foot--na");
  });

  /**
   * R5 is a labelling requirement: it is satisfied from the execution status of
   * the claims cited at R2, so it is sufficient and cites nothing of its own
   * (INV-4). Its column carried a ✓ in the head and the word "gap" at its foot,
   * which is the matrix saying both at once. Three live rows in fund_ii 25Q4 are
   * in this state.
   */
  it("never marks a requirement met without a citation as a gap", () => {
    const met: RequirementAssessment[] = [
      { ...BASE, requirement: "R1", verdict: "missing" },
      { ...BASE, requirement: "R5", verdict: "sufficient" },
    ];
    const { container } = render(<CoverageMap claims={[CITED_CLAIM]} assessments={met} />);
    const marks = [...container.querySelectorAll(".cov__foot")];
    expect(marks.map((el) => el.textContent)).toEqual(["gap", "—", "—", "—", "met"]);
    const gap = marks.at(0);
    const satisfied = marks.at(4);
    expect(gap?.className).not.toBe(satisfied?.className);
    expect(satisfied?.getAttribute("title")).toMatch(/labelling requirement/);
  });

  it("puts a mark only where a requirement actually cites the document", () => {
    const { container } = render(<CoverageMap claims={CLAIMS} assessments={ASSESSMENTS} />);
    const rows = [...container.querySelectorAll("tbody .cov__row")];
    const cited = rows.at(0);
    expect(cited?.querySelectorAll(".cov__cell--on")).toHaveLength(2);
    expect(rows.at(1)?.querySelectorAll(".cov__cell--on")).toHaveLength(0);
  });

  it("distinguishes evidence dated after the measurement date", () => {
    const subsequent: RequirementAssessment = {
      ...BASE,
      evidence: [{ ...SUBSEQUENT_EVIDENCE, claim: CITED_CLAIM, is_subsequent: true }],
    };
    const { container } = render(<CoverageMap claims={[CITED_CLAIM]} assessments={[subsequent]} />);
    expect(container.querySelectorAll(".cov__cell--subsequent")).toHaveLength(1);
    expect(container.querySelectorAll(".cov__cell--on")).toHaveLength(0);
  });

  /**
   * A citation pointing at a claim the holding route did not list is a stronger
   * finding than either of the two this map is for, so it is never dropped.
   */
  it("keeps a cited claim the holding's document list does not contain", () => {
    const { container } = render(<CoverageMap claims={[]} assessments={[CITES]} />);
    expect(container.querySelectorAll("tbody .cov__row")).toHaveLength(1);
    expect(screen.getByText(/not on the holding's list/)).toBeDefined();
  });

  /**
   * Because Market: eight figures in the packet and not one document naming it.
   * The map has no row to draw, and says which kind of nothing that is.
   */
  it("states a holding with no document on file, instead of drawing an empty grid", () => {
    // Nothing on file AND nothing cited: there is no row to draw at all.
    const bare = ASSESSMENTS.map((a) => ({ ...a, verdict: "missing" as const, evidence: [] }));
    const { container } = render(<CoverageMap claims={[]} assessments={bare} />);
    expect(container.querySelector(".cov__grid")).toBeNull();
    expect(screen.getByText(/No document on file names this holding/)).toBeDefined();
  });

  /** Presence, never counts. An aggregate over rows belongs to the API (§5.3). */
  it("renders the reliance window each claim states for itself", () => {
    render(<CoverageMap claims={CLAIMS} assessments={ASSESSMENTS} />);
    expect(screen.getAllByText(/relied on 2025-12-29 → 2026-03-31/).length).toBeGreaterThan(0);
  });
});
