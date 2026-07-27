import type { EvidenceClaim, HoldingResponse } from "./responses";
import { ClaimFacts, Section, SourceBadge, SourceFactItem } from "./ui";

/**
 * The screen this product exists for.
 *
 * The case study's chosen function is "documenting which evidence supports each
 * change in valuation for each holding", and the debrief asks for "how specific
 * outputs trace back to source data". That is this: for one holding, every claim
 * made about it, and under each claim every figure extracted from it — the field
 * that figure fills, the value, and the VERBATIM passage stating it, with the
 * character offsets that let an auditor find it again in the stored text.
 *
 * Labelled facts rather than a detached list of quotes, because the auditor's
 * question is which citation supports which number. A panel of five passages
 * with no field beside any of them answers a question nobody asked.
 */

/**
 * One claim, and the figures extracted from it.
 *
 * A claim with no facts is stated as such. It is a real state — the claim row
 * exists, the extraction that would pin its figures to passages has not run —
 * and it is NOT the same as a claim whose facts say nothing useful. Rendering it
 * as an empty area would merge the two.
 */
export function ClaimCard({ claim }: { claim: EvidenceClaim }) {
  return (
    <li className="claim">
      <ClaimFacts claim={claim} />
      {claim.facts.length === 0 ? (
        <p
          className="note claim__uncited"
          title="The claim is recorded; the extraction that pins its figures to text is not."
        >
          No extracted fact is attached to this claim, so nothing here traces to a document yet.
        </p>
      ) : (
        <ul className="fact-list">
          {claim.facts.map((fact) => (
            <li key={fact.id} className="fact-entry">
              <SourceFactItem fact={fact} />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

/**
 * Every claim about one holding.
 *
 * An empty list gets a sentence, not a blank panel. For this fund empty is
 * frequently the TRUE answer — the corpus contains no document stating the mark
 * — and saying so is the deliverable. A panel that renders nothing reports the
 * same holding as "no information available", which is a different and weaker
 * claim than "we looked, and the corpus has nothing".
 */
export function EvidencePanel({ holding }: { holding: HoldingResponse }) {
  return (
    <Section
      title="Evidence"
      hint="Each claim is one assertion made by one document version. Under it is every figure extracted from it, each naming the field it fills beside the exact text that states it and the offsets an auditor re-verifies against."
    >
      <p className="note">
        <SourceBadge source={holding.source} /> · holding <code>{holding.holding_id}</code>
      </p>
      {holding.evidence.length === 0 ? (
        <p
          className="empty-evidence"
          title="Nothing on file states this company's price, share count or transaction terms, so the mark below rests on the tracker figure alone."
        >
          No evidence in the corpus for this holding. That is a finding, not a loading state.
        </p>
      ) : (
        <ul className="claim-list">
          {holding.evidence.map((claim) => (
            <ClaimCard key={claim.id} claim={claim} />
          ))}
        </ul>
      )}
    </Section>
  );
}
