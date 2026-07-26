import type { Citation } from "./contracts";
import type { EvidenceClaim, HoldingResponse } from "./responses";
import { ClaimFacts, Section, SourceBadge } from "./ui";

/**
 * The screen this product exists for.
 *
 * The case study's chosen function is "documenting which evidence supports each
 * change in valuation for each holding", and the debrief asks for "how specific
 * outputs trace back to source data". That is this: for one holding, every claim
 * made about it, and under each claim the VERBATIM passage from the source
 * document that states the figure, with the character offsets that let an
 * auditor find it again in the stored text.
 *
 * The quote is rendered monospace and unmodified. No ellipsis, no truncation, no
 * highlighting of the "relevant" part — a citation an auditor cannot re-verify
 * against a re-extracted text is not a citation, and every one of those edits
 * makes it one.
 */

/**
 * One passage, exactly as the document states it.
 *
 * The offsets are on screen rather than in a tooltip because they are the
 * re-verification handle: `canonical_text[span_start:span_end]` in the stored
 * document version must equal this quote, and `0008_citations_resolve.sql` is
 * the constraint that keeps that true. A reader who cannot see the offsets
 * cannot check the claim that they resolve.
 */
export function CitationQuote({ citation }: { citation: Citation }) {
  return (
    <li className="citation">
      <blockquote className="citation__quote">{citation.quote}</blockquote>
      <p className="citation__where">
        <code>{citation.document_version_id}</code>
        <span className="sub">
          characters {citation.span_start}–{citation.span_end}
        </span>
      </p>
    </li>
  );
}

/**
 * One claim, and the passages it resolves to.
 *
 * A claim with no citations is stated as such. It is a real state — the claim
 * row exists, the extraction that would attach passages to it has not run — and
 * it is NOT the same as a claim whose passages say nothing useful. Rendering it
 * as an empty area would merge the two.
 */
export function ClaimCard({ claim }: { claim: EvidenceClaim }) {
  return (
    <li className="claim">
      <ClaimFacts claim={claim} />
      {claim.citations.length === 0 ? (
        <p className="note claim__uncited">
          No stored passage is attached to this claim, so nothing here can be traced to a document
          yet. The claim is recorded; the extraction that pins it to text is not.
        </p>
      ) : (
        <ul className="citation-list">
          {claim.citations.map((citation) => (
            <CitationQuote
              key={`${citation.document_version_id}:${citation.span_start}`}
              citation={citation}
            />
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
      title="Evidence — the passages behind the mark"
      note="Each claim is one assertion made by one document version. Under it is the exact text that asserts it, with the offsets an auditor re-verifies against."
    >
      <p className="note">
        <SourceBadge source={holding.source} /> · holding <code>{holding.holding_id}</code>
      </p>
      {holding.evidence.length === 0 ? (
        <p className="empty-evidence">
          No evidence in the corpus for this holding. Nothing on file states this company's price,
          share count or transaction terms, so the mark below rests on the tracker figure alone.
          That is a finding, not a loading state.
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
