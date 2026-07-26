import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { RequirementVerdict } from "./contracts";
import { FIXTURE_ROW } from "./fixture";
import { VERDICT } from "./labels";
import { APPROVAL, COUNSEL_GAP, SUBSEQUENT_EVIDENCE, TRANSCRIPTION_APPROVAL } from "./testdata";
import {
  ApprovalState,
  ClaimFacts,
  CodeList,
  EvidenceItem,
  Figure,
  GapItem,
  Meta,
  Section,
  SourceBadge,
  SupportState,
  VerdictChip,
} from "./ui";

afterEach(cleanup);

const ALL_VERDICTS: RequirementVerdict[] = [
  "not_assessed",
  "not_applicable",
  "missing",
  "insufficient",
  "partial",
  "conflicting",
  "sufficient",
];

describe("VerdictChip", () => {
  it("gives every one of the seven verdicts its own label, glyph and class", () => {
    const { container } = render(
      <div>
        {ALL_VERDICTS.map((verdict) => (
          <VerdictChip key={verdict} verdict={verdict} />
        ))}
      </div>,
    );
    const chips = [...container.querySelectorAll(".verdict")];
    expect(chips).toHaveLength(ALL_VERDICTS.length);
    const classes = chips.map((chip) => chip.className);
    expect(new Set(classes).size).toBe(ALL_VERDICTS.length);
    const glyphs = ALL_VERDICTS.map((verdict) => VERDICT[verdict].glyph);
    expect(new Set(glyphs).size).toBe(ALL_VERDICTS.length);
    // Read out of the DOM, not out of the labels table. Asserting that the
    // seven glyphs in `labels.ts` are distinct says nothing about whether any
    // of them was rendered: deleting the glyph span entirely left this case
    // green, which puts the seven verdicts back on colour alone.
    chips.forEach((chip, i) => {
      expect(chip.textContent).toContain(glyphs[i]);
    });
  });

  it("does not give missing and not_applicable a shared treatment", () => {
    const { container } = render(
      <div>
        <VerdictChip verdict="missing" />
        <VerdictChip verdict="not_applicable" />
      </div>,
    );
    const [missing, notApplicable] = [...container.querySelectorAll(".verdict")];
    expect(missing?.className).not.toBe(notApplicable?.className);
    expect(missing?.textContent).not.toBe(notApplicable?.textContent);
    expect(screen.getByText(/missing/)).toBeDefined();
    expect(screen.getByText(/not applicable/)).toBeDefined();
  });
});

describe("SourceBadge", () => {
  /**
   * The one thing a viewer must not have to guess. A fixture-sourced screen and
   * a ledger-sourced screen are laid out identically and differ by a factor of
   * five in the fund total.
   */
  it("distinguishes the ledger from the demo fixture, in words and in class", () => {
    const { container } = render(
      <div>
        <SourceBadge source="ledger" />
        <SourceBadge source="fixture" />
      </div>,
    );
    expect(screen.getByText(/source · ledger/)).toBeDefined();
    expect(screen.getByText(/source · fixture — not the fund/)).toBeDefined();
    expect(container.querySelector(".source--ledger")).not.toBeNull();
    expect(container.querySelector(".source--fixture")).not.toBeNull();
  });
});

describe("Section and Meta", () => {
  it("renders a note only when one is given", () => {
    const { container } = render(
      <Section title="With note" note="explanatory">
        <p>body</p>
      </Section>,
    );
    expect(container.querySelectorAll(".note")).toHaveLength(1);
    cleanup();
    const bare = render(
      <Section title="No note">
        <p>body</p>
      </Section>,
    );
    expect(bare.container.querySelectorAll(".note")).toHaveLength(0);
  });

  it("renders each label with its value, and its hint when one is given", () => {
    render(
      <Meta
        items={[
          { label: "policy version", value: "v1" },
          { label: "applicable", value: "yes", hint: "supplied by the API" },
        ]}
      />,
    );
    expect(screen.getByText("policy version")).toBeDefined();
    expect(screen.getByText("v1")).toBeDefined();
    expect(screen.getByText("applicable").title).toBe("supplied by the API");
  });
});

describe("Figure", () => {
  it("always renders a caption beside the amount", () => {
    render(<Figure caption="Reported" money={{ amount: "5000000", currency: "USD" }} />);
    expect(screen.getByText("Reported")).toBeDefined();
    expect(screen.getByText("5,000,000 USD")).toBeDefined();
  });

  it("takes an optional tone class", () => {
    const { container } = render(
      <Figure caption="Unsupported" money={{ amount: "1", currency: "USD" }} tone="unsupported" />,
    );
    expect(container.querySelector(".figure--unsupported")).not.toBeNull();
  });
});

describe("SupportState", () => {
  it("says supported, with no reasons, when the API says so", () => {
    const { container } = render(<SupportState supported={true} reasons={{}} />);
    expect(screen.getByText("supported")).toBeDefined();
    expect(container.querySelector(".support__reasons")).toBeNull();
  });

  /**
   * "Unsupported" alone is a finding nobody can act on. The reasons are the
   * actionable half and are keyed by requirement, so the reader knows which
   * question failed rather than that some question did.
   */
  it("never states unsupported without the per-requirement reasons behind it", () => {
    render(<SupportState supported={false} reasons={{ R1: "not assessed", R2: "insufficient" }} />);
    expect(screen.getByText("unsupported")).toBeDefined();
    expect(screen.getByText("R1")).toBeDefined();
    expect(screen.getByText(/not assessed/)).toBeDefined();
    expect(screen.getByText("R2")).toBeDefined();
    expect(screen.getByText(/insufficient/)).toBeDefined();
  });

  it("reports an unsupported row with no reasons as the contradiction it is", () => {
    render(<SupportState supported={false} reasons={{}} />);
    expect(screen.getByText(/disagreement between two fields it computes/)).toBeDefined();
  });
});

describe("CodeList", () => {
  it("renders nothing for an empty code list, and the codes otherwise", () => {
    const empty = render(<CodeList label="reason codes" codes={[]} />);
    expect(empty.container.querySelector(".codes")).toBeNull();
    cleanup();
    render(<CodeList label="reason codes" codes={["CLOSING_SET_PENDING"]} />);
    expect(screen.getByText("CLOSING_SET_PENDING")).toBeDefined();
  });
});

describe("ApprovalState", () => {
  it("says which decision is absent rather than showing nothing", () => {
    render(<ApprovalState approval={null} approved={false} />);
    expect(screen.getByText("no approval recorded")).toBeDefined();
    expect(screen.getByText("not an approved fair value")).toBeDefined();
  });

  it("names the decision type, never a bare Approved badge", () => {
    render(<ApprovalState approval={APPROVAL} approved={true} />);
    expect(screen.getByText(/valuation approval · approved/)).toBeDefined();
    expect(screen.getByText(/reviewer_a/)).toBeDefined();
    expect(screen.getByText("counts as approved fair value")).toBeDefined();
  });

  /**
   * SPEC §6.3 · the four decisions are independent. A transcription approval is
   * a real, recorded approval and creates no fair value, so the two lines must
   * be able to disagree — which is exactly what a single "Approved" badge
   * cannot express.
   */
  it("distinguishes a recorded approval from an approved fair value", () => {
    render(<ApprovalState approval={TRANSCRIPTION_APPROVAL} approved={false} />);
    expect(screen.getByText(/transcription approval · draft/)).toBeDefined();
    expect(screen.queryByText(/valuation approval/)).toBeNull();
    expect(screen.getByText("not an approved fair value")).toBeDefined();
  });
});

describe("ClaimFacts", () => {
  it("keeps authority and execution status as two questions, not one", () => {
    render(<ClaimFacts claim={SUBSEQUENT_EVIDENCE.claim} />);
    expect(screen.getByText(/authority · public market quote/)).toBeDefined();
    expect(screen.getByText(/artifact · not applicable/)).toBeDefined();
  });

  it("renders the three instants and the reliance window separately", () => {
    render(<ClaimFacts claim={SUBSEQUENT_EVIDENCE.claim} />);
    expect(screen.getByText("issued")).toBeDefined();
    expect(screen.getByText("2026-01-04")).toBeDefined();
    expect(screen.getByText("as of")).toBeDefined();
    expect(screen.getByText("2025-12-29")).toBeDefined();
    expect(screen.getByText("received")).toBeDefined();
    expect(screen.getByText("2026-01-05")).toBeDefined();
    expect(screen.getByText("2025-12-29 → 2026-03-31")).toBeDefined();
  });

  it("names the class the document prices, which is not always the class held", () => {
    render(<ClaimFacts claim={SUBSEQUENT_EVIDENCE.claim} />);
    expect(screen.getByText("priced class").title).toMatch(/often not the class the fund holds/);
    expect(screen.getByText("common")).toBeDefined();
    expect(screen.getByText("1,234,567.8900 USD")).toBeDefined();
    expect(screen.getByText("banzai_quote_prior")).toBeDefined();
  });

  it("renders an absent optional field as a dash, never as a blank", () => {
    const claim = FIXTURE_ROW.assessments[1]?.evidence[0]?.claim;
    if (claim === undefined) throw new Error("fixture has no cited evidence");
    render(<ClaimFacts claim={claim} />);
    expect(screen.getByText("2025-11-14 → open")).toBeDefined();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    cleanup();
    // A claim that prices nothing — a gap letter, a board consent — still has to
    // say so rather than leave the cell empty, which reads as "same as held".
    render(<ClaimFacts claim={{ ...claim, priced_class: null, price_per_share: null }} />);
    expect(screen.getAllByText("—").length).toBeGreaterThan(2);
  });
});

describe("EvidenceItem", () => {
  it("labels evidence dated after the measurement date", () => {
    render(
      <ul>
        <EvidenceItem citation={SUBSEQUENT_EVIDENCE} />
      </ul>,
    );
    expect(screen.getByText(/subsequent evidence/)).toBeDefined();
  });

  it("says so when evidence is contemporaneous", () => {
    const citation = FIXTURE_ROW.assessments[1]?.evidence[0];
    if (citation === undefined) throw new Error("fixture has no cited evidence");
    render(
      <ul>
        <EvidenceItem citation={citation} />
      </ul>,
    );
    expect(screen.getByText("not subsequent evidence")).toBeDefined();
    expect(screen.getByText(/authority · company cap table/)).toBeDefined();
    expect(screen.getByText(/artifact · pro forma/)).toBeDefined();
  });
});

describe("GapItem", () => {
  it("carries the kind and its next action, never a bare missing", () => {
    render(
      <ul>
        <GapItem gap={COUNSEL_GAP} heading={<strong>Sway</strong>} />
      </ul>,
    );
    expect(screen.getByText("with counsel")).toBeDefined();
    expect(screen.getByText(/Request from counsel/)).toBeDefined();
    expect(screen.getByText("Series A purchase agreement")).toBeDefined();
    expect(screen.getByText("remediation · requested")).toBeDefined();
    expect(screen.getByText("—")).toBeDefined();
  });

  it("renders a security class when the observation carries one", () => {
    const gap = FIXTURE_ROW.gaps[0];
    if (gap === undefined) throw new Error("fixture has no gap");
    render(
      <ul>
        <GapItem gap={gap} heading={<code>dream</code>} />
      </ul>,
    );
    expect(screen.getByText("series_a1")).toBeDefined();
    expect(screen.getByText("not located")).toBeDefined();
  });
});
