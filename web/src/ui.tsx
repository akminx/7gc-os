import type { ReactNode } from "react";
import { useState } from "react";

import type {
  Approval,
  Claim,
  EvidenceCitation,
  GapObservation,
  Money,
  RequirementCode,
  RequirementVerdict,
  SourceFact,
} from "./contracts";
import { formatDate, formatMoney } from "./format";
import {
  DECISION_STATUS,
  DECISION_TYPE,
  EXECUTION_STATUS,
  FACT_STATE,
  GAP_KIND,
  SOURCE,
  SOURCE_CLASS,
  VERDICT,
} from "./labels";
import type { Source } from "./responses";

/** Shared display primitives. None of them decides anything. */

/**
 * The paragraph, one hover away instead of in the reading path.
 *
 * The distinctions this product is built on each need a paragraph, and a
 * paragraph under every heading buries the figure the reader came for. The text
 * stays in the DOM — announced, searchable, quotable — and leaves the scan.
 */
export function Why({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="why-wrap">
      <button
        type="button"
        className="why"
        aria-expanded={open}
        aria-label={open ? "Hide the explanation" : "Explain this"}
        title={text}
        onClick={() => {
          setOpen((was) => !was);
        }}
      >
        <span aria-hidden="true">?</span>
      </button>
      {open && <span className="why__body">{text}</span>}
      <span className="vh">{text}</span>
    </span>
  );
}

/**
 * `note` is one line the reader needs. `hint` is the reasoning behind it, which
 * lives on the mark beside the heading. The affordance sits outside the `h2` so
 * the heading's text is still only its title.
 */
export function Section({
  title,
  note,
  hint,
  children,
}: {
  title: string;
  note?: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="section">
      <div className="section__head">
        <h2>{title}</h2>
        {hint !== undefined && <Why text={hint} />}
      </div>
      {note !== undefined && <p className="note">{note}</p>}
      {children}
    </section>
  );
}

export interface MetaItem {
  label: string;
  value: ReactNode;
  hint?: string;
}

export function Meta({ items }: { items: MetaItem[] }) {
  return (
    <dl className="meta">
      {items.map((item) => (
        <div key={item.label}>
          <dt title={item.hint}>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Which store answered, on screen rather than in a log.
 *
 * The API falls back to a one-holding, 5,000,000 stub when no DSN is configured.
 * That fallback is deliberate and honest at the API; it becomes dishonest the
 * moment a screen renders it under the fund's name without saying so. Every
 * surface that shows a figure shows this beside it.
 */
export function SourceBadge({ source }: { source: Source }) {
  const term = SOURCE[source];
  return (
    <span className={`source source--${source}`} title={term.meaning}>
      source · {term.label}
    </span>
  );
}

/**
 * A figure is never rendered alone. INV-19 is about totals, but the same
 * failure is available one row down: a number with its qualification left in a
 * field nobody rendered. So the caption is a required prop.
 */
export function Figure({ caption, money, tone }: { caption: string; money: Money; tone?: string }) {
  return (
    <div className={tone === undefined ? "figure" : `figure figure--${tone}`}>
      <span className="figure__caption">{caption}</span>
      <span className="figure__amount">{formatMoney(money)}</span>
    </div>
  );
}

export const NO_MARK_MEANING =
  "The ledger holds no mark for this holding at this measurement date. Not zero, and not the last mark carried forward.";

/**
 * A holding the ledger holds no mark for at this date.
 *
 * A realised position is in the packet because the audit letter asks for
 * realised investments, and it has no mark at the measurement date because it
 * was not held then — `evals/oracle/derived.json` states Jackpocket at
 * 2024-12-31 as `reported_amount: null`. The absence is a sentence rather than
 * an empty cell: on a screen of amounts a blank reads as zero, and zero is a
 * figure the oracle says does not exist.
 */
export function NoMark() {
  return (
    <span className="no-mark" title={NO_MARK_MEANING}>
      no mark at this date
    </span>
  );
}

/**
 * One extracted figure, with the field it fills and the passage that states it.
 *
 * The single renderer for a `SourceFact`, used by the evidence workspace and by
 * the computation lineage, so the two cannot describe the same fact
 * differently. `field_name` leads, because a quote whose figure nobody can
 * place is a quotation and not evidence: an auditor's question is which
 * citation supports which number.
 *
 * The quote is verbatim and the offsets are on screen rather than in a tooltip,
 * because together they are the re-verification handle —
 * `canonical_text[span_start:span_end]` in the stored document version must
 * equal this quote, and `0008_citations_resolve.sql` is the constraint that
 * keeps that true. No ellipsis, no truncation, no highlighting of the
 * "relevant" part; every one of those edits makes it unverifiable.
 *
 * `value_text` and `value_numeric` are both shown when both exist. The first is
 * what the page says, the second is what was parsed out of it, and a
 * transcription question an auditor cannot see is one they cannot raise.
 */
export function SourceFactItem({ fact }: { fact: SourceFact }) {
  const state = FACT_STATE[fact.state];
  return (
    <div className="fact">
      <p className="fact__head">
        <code className="fact__field">{fact.field_name}</code>
        <span className="fact__value">{fact.value_text}</span>
        {fact.value_numeric !== null && (
          <span className="fact__numeric" title="The value as parsed, in canonical form.">
            parsed · {fact.value_numeric}
          </span>
        )}
        <span className="tag tag--state" title={state.meaning}>
          fact · {state.label}
        </span>
      </p>
      <blockquote className="citation__quote">{fact.citation.quote}</blockquote>
      <p className="citation__where">
        <code>{fact.citation.document_version_id}</code>
        <span className="sub">
          characters {fact.citation.span_start}–{fact.citation.span_end}
        </span>
      </p>
    </div>
  );
}

/**
 * INV-2 · one visible treatment per verdict, seven of them, no shared "not ok".
 * The glyph carries the same distinction as the colour so the seven stay
 * distinguishable without it.
 *
 * `compact` takes the label out of the reading order and leaves it in the
 * accessibility tree. It is for the holdings table, where five verdicts sit in
 * five columns under headings that already say R1 to R5, and where a partner is
 * scanning eight rows for the one in trouble rather than reading seven words per
 * row. The label is still in the DOM, still in the tooltip, and still announced.
 *
 * The seven remain distinguishable without colour in either form, because the
 * glyph is what carries the distinction and the glyph never leaves.
 */
export function VerdictChip({
  verdict,
  compact,
}: {
  verdict: RequirementVerdict;
  compact?: boolean;
}) {
  const term = VERDICT[verdict];
  const classes =
    compact === true
      ? `verdict verdict--${verdict} verdict--compact`
      : `verdict verdict--${verdict}`;
  return (
    <span className={classes} title={`${term.label} — ${term.meaning}`}>
      <span aria-hidden="true">{term.glyph}</span>{" "}
      <span className={compact === true ? "vh" : undefined}>{term.label}</span>
    </span>
  );
}

/**
 * SPEC §7.1–7.2 · whether this row's evidence supports its mark, as the API
 * decided it.
 *
 * Both halves are the API's: `supported` and the per-requirement reasons behind
 * it are `@property` on the Python model, attached to the wire by
 * `api/serialize.py`. Nothing here re-derives either, and the flag is never
 * shown without the reasons — "unsupported" with no statement of what is missing
 * is the finding an auditor cannot act on.
 */
export function SupportState({
  supported,
  reasons,
}: {
  supported: boolean;
  reasons: Partial<Record<RequirementCode, string>>;
}) {
  const entries = Object.entries(reasons);
  if (supported) {
    return (
      <span
        className="support support--supported"
        title="Every applicable requirement is sufficient, and the always-applicable ones were assessed."
      >
        supported
      </span>
    );
  }
  return (
    <span className="support support--unsupported">
      <span className="support__flag">unsupported</span>
      {entries.length === 0 ? (
        <span
          className="sub"
          title="The API reports this row unsupported and sent no reason for it: a disagreement between two fields it computes, not a state this screen can resolve."
        >
          no reason supplied · a disagreement between two fields the API computes
        </span>
      ) : (
        <ul className="support__reasons">
          {entries.map(([code, reason]) => (
            <li key={code}>
              <code>{code}</code> {reason}
            </li>
          ))}
        </ul>
      )}
    </span>
  );
}

export function CodeList({ label, codes }: { label: string; codes: string[] }) {
  if (codes.length === 0) return null;
  return (
    <p className="codes">
      <span className="codes__label">{label}</span>
      {codes.map((code) => (
        <code key={code}>{code}</code>
      ))}
    </p>
  );
}

/**
 * SPEC §6.3 · four independent decisions, and a UI action must name its target
 * type. There is no generic "Approved" badge here: the type is rendered before
 * the status, and a row with no approval says which decision is absent rather
 * than showing nothing.
 *
 * `approved` is a separate question from `approval !== null`, and is rendered as
 * a separate line. INV-10 · it is true only for a recorded VALUATION approval
 * that cites the assessments it rests on, so a row can carry a transcription
 * approval in good standing and still not count as an approved fair value.
 */
export function ApprovalState({
  approval,
  approved,
}: {
  approval: Approval | null;
  approved: boolean;
}) {
  const fairValue = (
    <span
      className={approved ? "approval__fv approval__fv--yes" : "approval__fv approval__fv--no"}
      title="Only a recorded valuation approval that names the evidence it relied on creates this."
    >
      {approved ? "counts as approved fair value" : "not an approved fair value"}
    </span>
  );
  if (approval === null) {
    return (
      <span
        className="approval approval--none"
        title="An approval is something a person recorded. Nothing unsupported becomes approved by having no objections."
      >
        no approval recorded
        {fairValue}
      </span>
    );
  }
  const term = DECISION_TYPE[approval.decision_type];
  return (
    <span className={`approval approval--${approval.status}`} title={term.meaning}>
      {term.label} · {DECISION_STATUS[approval.status]}
      <span className="approval__actor">
        {approval.actor_id} · {approval.decided_at}
      </span>
      {fairValue}
    </span>
  );
}

/**
 * Everything one claim asserts, with the distinctions kept apart.
 *
 * The single renderer for a claim, used by the PBC checklist and by the evidence
 * workspace, so the two cannot describe the same claim differently. Four
 * separations are structural here:
 *
 * * **authority ≠ execution status** (INV-15, INV-4). An executed transaction
 *   document and a press report are different authority; executed and pro forma
 *   are different states of the artifact. An auditor asks both questions.
 * * **three instants** (INV-3). Issued, as-of and received are never one date:
 *   a cap table issued in January can be as-of December and received in March.
 * * **the reliance window is the SOURCE's own claim** about the period it speaks
 *   for, not a window someone here chose.
 * * **priced class ≠ held class.** The class a document prices is frequently not
 *   the class the fund holds, and that gap is where cross-class inference —
 *   the thing a valuation policy has to decide — begins.
 */
export function ClaimFacts({ claim }: { claim: Claim }) {
  return (
    <>
      <div className="evidence__head">
        <code>{claim.id}</code>
        <span
          className="tag tag--authority"
          title="Whose word this is. One document can carry statements of different authority, so this describes the assertion rather than the file."
        >
          authority · {SOURCE_CLASS[claim.source_class]}
        </span>
        <span
          className="tag tag--exec"
          title="Whether the document is signed, proposed, or refers to a closing set held elsewhere."
        >
          artifact · {EXECUTION_STATUS[claim.execution_status]}
        </span>
      </div>
      <Meta
        items={[
          { label: "document version", value: <code>{claim.document_version_id}</code> },
          { label: "claim key", value: <code>{claim.claim_key}</code> },
          {
            label: "issued",
            value: formatDate(claim.issued_date),
            hint: "When the document was written.",
          },
          {
            label: "as of",
            value: claim.as_of_date === null ? "—" : formatDate(claim.as_of_date),
            hint: "The date the document's own figures speak for.",
          },
          {
            label: "received",
            value: claim.received_date === null ? "—" : formatDate(claim.received_date),
            hint: "When the fund got it. Bears on subsequent-events treatment.",
          },
          {
            label: "reliance window",
            value: `${formatDate(claim.applicable_from)} → ${
              claim.applicable_to === null ? "open" : formatDate(claim.applicable_to)
            }`,
            hint: "The period the source itself states it may be relied on for.",
          },
          {
            label: "priced class",
            value: claim.priced_class ?? "—",
            hint: "The class this document prices — often not the class the fund holds.",
          },
          { label: "price per share", value: claim.price_per_share ?? "—" },
          {
            label: "stated amount",
            value: claim.stated === null ? "—" : formatMoney(claim.stated),
          },
          { label: "supersedes", value: claim.supersedes_claim_id ?? "—" },
        ]}
      />
    </>
  );
}

/** A cited claim, with the label that says whether it post-dates the mark. */
export function EvidenceItem({ citation }: { citation: EvidenceCitation }) {
  return (
    <li className="evidence">
      <p className="evidence__when">
        <span
          className={citation.is_subsequent ? "tag tag--subsequent" : "tag tag--contemporaneous"}
        >
          {citation.is_subsequent
            ? "subsequent evidence — dated after the measurement date"
            : "not subsequent evidence"}
        </span>
      </p>
      <ClaimFacts claim={citation.claim} />
    </li>
  );
}

/** INV-12 · the kind travels with the gap, and never collapses to "missing". */
export function GapItem({ gap, heading }: { gap: GapObservation; heading: ReactNode }) {
  const kind = GAP_KIND[gap.kind];
  return (
    <li className={`gap gap--${gap.kind}`}>
      <div className="gap__head">
        {heading}
        <span className={`gap-kind gap-kind--${gap.kind}`} title={`${kind.meaning} ${kind.next}`}>
          {kind.label}
        </span>
        <span className="tag">remediation · {gap.remediation}</span>
      </div>
      <p className="gap__doc">{gap.missing_document}</p>
      <blockquote>{gap.source_quote}</blockquote>
      <Meta
        items={[
          { label: "requirement", value: gap.requirement },
          { label: "security class", value: gap.security_class ?? "—" },
        ]}
      />
    </li>
  );
}
