import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CitationQuote, ClaimCard, EvidencePanel } from "./Evidence";
import {
  CITED_CLAIM,
  HOLDING_WITH_EVIDENCE,
  HOLDING_WITHOUT_EVIDENCE,
  UNCITED_CLAIM,
} from "./testdata";

afterEach(cleanup);

describe("CitationQuote", () => {
  /**
   * The quote is the product. Any edit to it — truncation, an ellipsis, a
   * highlighted "relevant" span — breaks the one thing it is for, which is that
   * an auditor can re-verify it against the stored text character for character.
   */
  it("renders the passage verbatim, with the offsets that locate it", () => {
    const citation = CITED_CLAIM.citations[0];
    if (citation === undefined) throw new Error("the cited claim has no citation");
    const { container } = render(
      <ul>
        <CitationQuote citation={citation} />
      </ul>,
    );
    const quote = container.querySelector(".citation__quote");
    expect(quote?.textContent).toBe(citation.quote);
    expect(screen.getByText("dv_poolside_spa")).toBeDefined();
    expect(screen.getByText("characters 4821–4891")).toBeDefined();
  });
});

describe("ClaimCard", () => {
  it("puts every passage under the claim that cites it", () => {
    const { container } = render(
      <ul>
        <ClaimCard claim={CITED_CLAIM} />
      </ul>,
    );
    expect(container.querySelectorAll(".citation")).toHaveLength(2);
    expect(screen.getByText(/the Purchase Price shall be \$2\.50 per share/)).toBeDefined();
    expect(screen.getByText(/1,000,000 shares of Series B Preferred Stock/)).toBeDefined();
    // The claim's own facts travel with it: authority and artifact state are
    // two separate questions about the same document (INV-15, INV-4).
    expect(screen.getByText(/authority · executed transaction doc/)).toBeDefined();
    expect(screen.getByText(/artifact · executed/)).toBeDefined();
  });

  /**
   * A claim on file with no passage attached is a real state — the claim row
   * exists, the extraction that pins it to text has not run — and it is not the
   * same as a claim whose passages say nothing. An empty area would merge them.
   */
  it("states an uncited claim rather than leaving space where the quote goes", () => {
    const { container } = render(
      <ul>
        <ClaimCard claim={UNCITED_CLAIM} />
      </ul>,
    );
    expect(container.querySelectorAll(".citation")).toHaveLength(0);
    expect(screen.getByText(/No stored passage is attached to this claim/)).toBeDefined();
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
