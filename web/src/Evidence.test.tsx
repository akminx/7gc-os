import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ClaimCard, EvidencePanel } from "./Evidence";
import {
  CITED_CLAIM,
  HOLDING_WITH_EVIDENCE,
  HOLDING_WITHOUT_EVIDENCE,
  UNCITED_CLAIM,
} from "./testdata";

afterEach(cleanup);

describe("ClaimCard", () => {
  /**
   * The point of `field_name`: an auditor needs to know which citation supports
   * which number. Read pairwise off the rendered facts, because asserting that
   * a field label and a quote each appear SOMEWHERE cannot tell a correct
   * pairing from a shuffled one — and the route was changed from a detached
   * citation list to labelled facts precisely to make the pairing sayable.
   */
  it("puts every figure under the claim that states it, beside the field it fills", () => {
    const { container } = render(
      <ul>
        <ClaimCard claim={CITED_CLAIM} />
      </ul>,
    );
    const facts = [...container.querySelectorAll(".fact")].map((fact) => ({
      field: fact.querySelector(".fact__field")?.textContent,
      value: fact.querySelector(".fact__value")?.textContent,
      numeric: fact.querySelector(".fact__numeric")?.textContent,
      state: fact.querySelector(".tag--state")?.textContent,
      quote: fact.querySelector(".citation__quote")?.textContent,
      where: fact.querySelector(".citation__where")?.textContent,
    }));
    expect(facts).toEqual([
      {
        field: "price_per_share",
        value: "$2.50",
        numeric: "parsed · 2.500000",
        state: "fact · canonical",
        quote: "the Purchase Price shall be $2.50 per share of Series B Preferred Stock",
        where: "dv_poolside_spacharacters 4821–4891",
      },
      {
        field: "security_class",
        value: "Series B Preferred Stock",
        // Not every extracted value is a number. The slot is absent rather than
        // rendered empty, so nothing reads as a figure of zero.
        numeric: undefined,
        state: "fact · candidate",
        quote: "1,000,000 shares of Series B Preferred Stock",
        where: "dv_poolside_spacharacters 5102–5146",
      },
    ]);
    // The claim's own facts travel with it: authority and artifact state are
    // two separate questions about the same document (INV-15, INV-4).
    expect(screen.getByText(/authority · executed transaction doc/)).toBeDefined();
    expect(screen.getByText(/artifact · executed/)).toBeDefined();
  });

  /**
   * The quote is the product. Any edit to it — truncation, an ellipsis, a
   * highlighted "relevant" span — breaks the one thing it is for, which is that
   * an auditor can re-verify it against the stored text character for character.
   */
  it("renders each passage verbatim, with the offsets that locate it", () => {
    const fact = CITED_CLAIM.facts[0];
    if (fact === undefined) throw new Error("the cited claim has no fact");
    const { container } = render(
      <ul>
        <ClaimCard claim={CITED_CLAIM} />
      </ul>,
    );
    expect(container.querySelector(".citation__quote")?.textContent).toBe(fact.citation.quote);
    expect(screen.getAllByText("dv_poolside_spa").length).toBeGreaterThan(0);
    expect(screen.getByText("characters 4821–4891")).toBeDefined();
  });

  /**
   * A claim on file with no fact attached is a real state — the claim row
   * exists, the extraction that pins its figures to text has not run — and it is
   * not the same as a claim whose facts say nothing. An empty area would merge
   * them.
   */
  it("states an unextracted claim rather than leaving space where the figures go", () => {
    const { container } = render(
      <ul>
        <ClaimCard claim={UNCITED_CLAIM} />
      </ul>,
    );
    expect(container.querySelectorAll(".fact")).toHaveLength(0);
    expect(screen.getByText(/No extracted fact is attached to this claim/)).toBeDefined();
  });
});

describe("EvidencePanel", () => {
  it("lists every claim about the holding, and says which store answered", () => {
    const { container } = render(<EvidencePanel holding={HOLDING_WITH_EVIDENCE} />);
    expect(container.querySelectorAll(".claim")).toHaveLength(2);
    expect(screen.getByText(/source · ledger/)).toBeDefined();
    expect(screen.getByText("poolside")).toBeDefined();
  });

  /**
   * For most of this fund, empty is the TRUE answer, and stating it is the
   * deliverable. A blank panel reports the same holding as "no information
   * available", which is a weaker and different claim than "we looked, and the
   * corpus has nothing".
   */
  it("renders no evidence as a finding, not as an empty panel", () => {
    const { container } = render(<EvidencePanel holding={HOLDING_WITHOUT_EVIDENCE} />);
    expect(container.querySelectorAll(".claim")).toHaveLength(0);
    expect(screen.getByText(/No evidence in the corpus for this holding/)).toBeDefined();
    expect(screen.getByText(/That is a finding, not a loading state/)).toBeDefined();
  });
});
