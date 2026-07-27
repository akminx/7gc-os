import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Claim, ExecutionStatus, SourceClass } from "./contracts";
import type { Figure } from "./Figures";
import { ClaimHead, Figures } from "./Figures";
import { EXECUTION_STATUS, REQUIREMENT, SOURCE_CLASS } from "./labels";
import type { EvidenceFact } from "./responses";
import { CITED_CLAIM } from "./testdata";

/**
 * The authority a figure inherits, which nothing asserted.
 *
 * `Figures.tsx` had no test file. It is reached through `Trail.test.tsx`, and
 * every assertion there is about which figures appear, in what order, and which
 * passage a click opens — none of them reads the claim head. So
 * `SOURCE_CLASS[claim.source_class]` could be replaced by `claim.source_class`
 * and the whole suite stayed green, while the screen said
 * `third_party_valuation_memo` where an auditor is meant to read "third-party
 * valuation memo". The component's own docstring calls this half of what an
 * auditor is judging (INV-15): a number with no authority attached is not
 * evidence, and a raw enum is authority the reader has to already know the
 * vocabulary to decode.
 *
 * `AnswersElsewhere` is the same defect one line over. `REQUIREMENT[code].label`
 * is "R2 · fair-value support" and the component takes the half after the dot;
 * taking the half before it renders a column of "R1 · R2" under a heading that
 * already says which request is in focus, which answers the reader's actual
 * question — "then what is this doing here" — with the thing they already knew.
 */

afterEach(cleanup);

function figureOf(claim: Claim, fact: EvidenceFact): Figure {
  return { claim, fact };
}

function firstFact(): EvidenceFact {
  const fact = CITED_CLAIM.facts[0];
  if (fact === undefined) throw new Error("the cited claim states a figure");
  return fact;
}

const FACT = firstFact();

function claimWith(id: string, source: SourceClass, execution: ExecutionStatus) {
  return { ...CITED_CLAIM, id, source_class: source, execution_status: execution };
}

function answering(codes: EvidenceFact["answers_requirements"]): EvidenceFact {
  return { ...FACT, answers_requirements: codes };
}

describe("the claim head", () => {
  /**
   * Read as literals rather than through the same map the component reads, so
   * that a component rendering the raw enum cannot be agreed with by a test that
   * looks the raw enum up too.
   */
  it("names whose word this is in the auditor's words, not the ledger's", () => {
    const { container } = render(
      <ClaimHead
        claim={claimWith("memo", "third_party_valuation_memo", "unexecuted_referenced")}
      />,
    );
    expect(container.querySelector(".tag--authority")?.textContent).toBe(
      "third-party valuation memo",
    );
    expect(container.querySelector(".tag--exec")?.textContent).toBe("unexecuted, referenced");
    expect(container.textContent).not.toMatch(/third_party_valuation_memo/);
    expect(container.textContent).not.toMatch(/unexecuted_referenced/);
    expect(container.querySelector(".trail__claim-key")?.textContent).toBe(CITED_CLAIM.claim_key);
  });

  /**
   * Every member, because one glossed class and eight raw ones is the state this
   * check exists to catch and a single case cannot see it. The raw value is
   * asserted absent only where it differs from its label — `executed` is its own
   * label, and demanding it be missing would ask the tag to say nothing.
   */
  it("glosses every source class and every execution status the contract allows", () => {
    for (const source of Object.keys(SOURCE_CLASS) as SourceClass[]) {
      for (const execution of Object.keys(EXECUTION_STATUS) as ExecutionStatus[]) {
        const { container } = render(<ClaimHead claim={claimWith("c", source, execution)} />);
        expect(container.querySelector(".tag--authority")?.textContent, source).toBe(
          SOURCE_CLASS[source],
        );
        expect(container.querySelector(".tag--exec")?.textContent, execution).toBe(
          EXECUTION_STATUS[execution],
        );
        if (SOURCE_CLASS[source] !== source) {
          expect(container.textContent, source).not.toMatch(source);
        }
        if (EXECUTION_STATUS[execution] !== execution) {
          expect(container.textContent, execution).not.toMatch(execution);
        }
        cleanup();
      }
    }
  });

  /**
   * One document can carry statements of different authority, so the tag
   * describes the assertion rather than the file — and the hover is where that
   * distinction is stated to a reader who would otherwise read the tag as a
   * property of the PDF.
   */
  it("says on hover that the tag describes the assertion and not the file", () => {
    const { container } = render(
      <ClaimHead claim={claimWith("c", "company_cap_table", "not_applicable")} />,
    );
    expect(container.querySelector(".tag--authority")?.getAttribute("title")).toMatch(
      /describes the assertion rather than the file/,
    );
    expect(container.querySelector(".tag--exec")?.getAttribute("title")).toMatch(
      /signed, proposed, or refers to a closing set/,
    );
  });
});

describe("the figures", () => {
  /**
   * A figure with no claim above it is a number with no authority attached
   * (INV-15). Two claims stating one figure each must therefore produce two
   * heads, not one head and two rows underneath it.
   */
  it("puts a claim head over every group and never a figure without one", () => {
    const { container } = render(
      <Figures
        figures={[
          figureOf(claimWith("spa", "executed_transaction_doc", "executed"), FACT),
          figureOf(claimWith("deck", "company_communication", "non_binding"), {
            ...FACT,
            id: 99,
          }),
        ]}
        active={undefined}
        onChoose={() => {}}
      />,
    );
    const groups = [...container.querySelectorAll(".trail__group")];
    expect(groups).toHaveLength(2);
    for (const group of groups) {
      expect(group.querySelectorAll(".trail__claim")).toHaveLength(1);
    }
    expect([...container.querySelectorAll(".tag--authority")].map((el) => el.textContent)).toEqual([
      "executed transaction doc",
      "company communication",
    ]);
    expect([...container.querySelectorAll(".tag--exec")].map((el) => el.textContent)).toEqual([
      "executed",
      "non-binding",
    ]);
  });

  /**
   * The reader's question in this list is "then what is this doing here", and
   * the answer is the OTHER request's name. "R2" is not that answer — it is the
   * label of the thing they are already looking at, restated as a code they then
   * have to look up.
   */
  it("says which other request a figure answers, in words rather than in codes", () => {
    const { container } = render(
      <Figures
        figures={[figureOf(CITED_CLAIM, answering(["R2"]))]}
        active={undefined}
        onChoose={() => {}}
        showAnswers
      />,
    );
    const answers = container.querySelector(".figrow__answers");
    expect(answers?.textContent).toBe("fair-value support");
    expect(answers?.textContent).not.toMatch(/R2/);
    expect(REQUIREMENT.R2.label).toBe("R2 · fair-value support");
  });

  it("names every request a figure answers when it answers more than one", () => {
    const { container } = render(
      <Figures
        figures={[figureOf(CITED_CLAIM, answering(["R1", "R2"]))]}
        active={undefined}
        onChoose={() => {}}
        showAnswers
      />,
    );
    expect(container.querySelector(".figrow__answers")?.textContent).toBe(
      "existence and cost · fair-value support",
    );
  });

  /**
   * Answering none of the four is a DECLARED judgement — the API raises on a
   * field nobody has ruled on rather than returning an empty set — so it is
   * labelled as reviewed, and the hover says so rather than leaving the row
   * looking like a lookup that failed.
   */
  it("labels a figure that answers no request as reviewed, not as unknown", () => {
    const { container } = render(
      <Figures
        figures={[figureOf(CITED_CLAIM, answering([]))]}
        active={undefined}
        onChoose={() => {}}
        showAnswers
      />,
    );
    const none = container.querySelector(".figrow__answers--none");
    expect(none?.textContent).toBe("answers no request");
    expect(none?.getAttribute("title")).toMatch(/Reviewed and declared as answering none/);
  });

  /**
   * The answering list is under a heading that already names the request, so
   * repeating it on every row is noise. Withheld by default and shown only where
   * the question arises.
   */
  it("withholds the request names where the heading already states them", () => {
    const { container } = render(
      <Figures
        figures={[figureOf(CITED_CLAIM, answering(["R2"]))]}
        active={undefined}
        onChoose={() => {}}
      />,
    );
    expect(container.querySelector(".figrow__answers")).toBeNull();
  });

  it("opens the figure that is clicked and marks the active one as current", () => {
    const chosen: string[] = [];
    const figure = figureOf(CITED_CLAIM, FACT);
    const { container } = render(
      <Figures
        figures={[figure]}
        active={figure}
        onChoose={(key) => {
          chosen.push(key);
        }}
      />,
    );
    expect(container.querySelector(".figrow--on")).not.toBeNull();
    screen.getByRole("button", { name: /price_per_share/ }).click();
    expect(chosen).toEqual([`${CITED_CLAIM.id}:${FACT.id}`]);
  });
});
