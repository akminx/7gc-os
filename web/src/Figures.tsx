import type { Claim, RequirementCode } from "./contracts";
import { EXECUTION_STATUS, FACT_STATE, REQUIREMENT, SOURCE_CLASS } from "./labels";
import type { EvidenceFact } from "./responses";

/**
 * The middle pane's figure lists, and the two-part shape they are in.
 *
 * Split out of `Trail.tsx` because that file now holds two things: the rail and
 * the orchestration on one side, and the figure rendering on the other. They
 * change for different reasons — one when a requirement's presentation moves,
 * the other when what a figure IS on screen moves.
 *
 * The two lists here are not variants of each other. The first is the figures
 * that answer the request in focus, ordered by how directly they answer it. The
 * second is everything else the same documents state, behind one click — the
 * ledger binds a CLAIM to a requirement, so a stock purchase agreement relied
 * upon for existence AND fair value states figures for both, and showing all of
 * them under both is what made clicking R1 and R2 give the same window.
 *
 * Followed, not dropped. The document really does state them; they answer a
 * different question. Hiding them would be this pane deciding what an auditor
 * may read next to the sentence, which is the one thing the passage pane's own
 * docstring says it must not do.
 */

/** One extracted figure, with the claim whose authority it inherits. */
export interface Figure {
  claim: Claim;
  fact: EvidenceFact;
}

export function factKey(figure: Figure): string {
  return `${figure.claim.id}:${figure.fact.id}`;
}

/**
 * Which requests a figure answers, in the auditor's own labels.
 *
 * Shown only in the "also states" list, where the reader's question is "then
 * what is this doing here" and the answer is the other request's name. In the
 * answering list every row would carry the heading's own label, which is noise.
 */
function AnswersElsewhere({ fact }: { fact: EvidenceFact }) {
  if (fact.answers_requirements.length === 0) {
    return (
      <span
        className="figrow__answers figrow__answers--none"
        title="Reviewed and declared as answering none of the client's four requests — it describes the filing rather than the position. Not an omission: a figure whose relevance is undecided is refused at ingestion."
      >
        answers no request
      </span>
    );
  }
  return (
    <span className="figrow__answers">
      {fact.answers_requirements
        .map((code) => REQUIREMENT[code].label.split(" · ")[1] ?? code)
        .join(" · ")}
    </span>
  );
}

/** One extracted figure, as a control that opens its passage. */
function FigureButton({
  figure,
  on,
  onChoose,
  showAnswers = false,
}: {
  figure: Figure;
  on: boolean;
  onChoose: () => void;
  showAnswers?: boolean;
}) {
  const state = FACT_STATE[figure.fact.state];
  return (
    <li>
      <button
        type="button"
        className={on ? "figrow figrow--on" : "figrow"}
        aria-current={on}
        onClick={onChoose}
      >
        <code className="figrow__field">{figure.fact.field_name}</code>
        <span className="figrow__value">{figure.fact.value_text}</span>
        {showAnswers && <AnswersElsewhere fact={figure.fact} />}
        <span className="figrow__state" title={state.meaning}>
          {state.label}
        </span>
        <span className="figrow__where">
          chars {figure.fact.citation.span_start}–{figure.fact.citation.span_end}
        </span>
      </button>
    </li>
  );
}

export function ClaimHead({ claim }: { claim: Claim }) {
  return (
    <p className="trail__claim">
      <span className="trail__claim-key">{claim.claim_key}</span>
      <span
        className="tag tag--authority"
        title="Whose word this is. One document can carry statements of different authority, so this describes the assertion rather than the file."
      >
        {SOURCE_CLASS[claim.source_class]}
      </span>
      <span
        className="tag tag--exec"
        title="Whether the document is signed, proposed, or refers to a closing set held elsewhere."
      >
        {EXECUTION_STATUS[claim.execution_status]}
      </span>
    </p>
  );
}

/**
 * The figures, grouped under the claim that states them.
 *
 * Grouped rather than flat because a figure with no claim above it is a number
 * with no authority attached, and authority is half of what an auditor is
 * judging (INV-15).
 */
export function Figures({
  figures,
  active,
  onChoose,
  showAnswers = false,
}: {
  figures: Figure[];
  active: Figure | undefined;
  onChoose: (key: string) => void;
  showAnswers?: boolean;
}) {
  const claimIds = [...new Set(figures.map((figure) => figure.claim.id))];
  return (
    <>
      {claimIds.map((claimId) => {
        const mine = figures.filter((figure) => figure.claim.id === claimId);
        const head = mine.at(0);
        if (head === undefined) return null;
        return (
          <div key={claimId} className="trail__group">
            <ClaimHead claim={head.claim} />
            <ul className="figrows">
              {mine.map((figure) => (
                <FigureButton
                  key={factKey(figure)}
                  figure={figure}
                  on={active !== undefined && factKey(active) === factKey(figure)}
                  onChoose={() => {
                    onChoose(factKey(figure));
                  }}
                  showAnswers={showAnswers}
                />
              ))}
            </ul>
          </div>
        );
      })}
    </>
  );
}

/**
 * The rest of what the cited documents state, behind one click.
 *
 * Open by default when nothing answers the request in focus, because then it is
 * the only content there is and a collapsed panel would read as an empty pane.
 */
export function OtherFigures({
  figures,
  active,
  onChoose,
  code,
  answeringCount,
}: {
  figures: Figure[];
  active: Figure | undefined;
  onChoose: (key: string) => void;
  code: RequirementCode;
  answeringCount: number;
}) {
  const label = REQUIREMENT[code].label;
  return (
    <details className="trail__other" open={answeringCount === 0}>
      <summary className="trail__other-summary">
        {figures.length} further {figures.length === 1 ? "figure" : "figures"} in the same
        documents, answering something other than {label}
      </summary>
      <p className="trail__other-note">
        The same documents state these. They are on screen because a document nobody may read past
        is not evidence an auditor can check — but they are not what {label} rests on.
      </p>
      <Figures figures={figures} active={active} onChoose={onChoose} showAnswers />
    </details>
  );
}
