import { useState } from "react";

import type {
  Claim,
  GapObservation,
  RequirementAssessment,
  RequirementCode,
  SourceFact,
} from "./contracts";
import type { CitationState } from "./Gap";
import { citationState, GapAction, MET_UNCITED, openRequirements } from "./Gap";
import { EXECUTION_STATUS, FACT_STATE, REQUIREMENT, SOURCE_CLASS, VERDICT } from "./labels";
import { PassagePane } from "./Passage";
import type { EvidenceClaim } from "./responses";

/**
 * The evidence trail: requirement → claim and figure → source passage.
 *
 * Three panes, left to right, in the order an auditor asks the questions. What
 * does the requirement ask. What did we rely on for it. Where does that document
 * actually say so. The third pane is the answer and the other two exist to reach
 * it, which is why they are narrow and quiet and it is wide and loud.
 *
 * The middle pane has two contents and they are not variants of each other. When
 * a requirement cites evidence it lists the figures extracted from that
 * evidence, each one a handle onto its passage. When it cites none — which for
 * most of this fund is the true answer — it shows the gap, the action and the
 * fund's own words about it. A pane that rendered the second case as an empty
 * version of the first would report "nothing to show" where the deliverable is
 * "here is what is missing, here is who to write to, here is the fund saying
 * so".
 *
 * The last row of the first pane is not a requirement. It is the documents on
 * file that NO requirement cites — the unused claims. They are reachable
 * because an uncited document is where a discrepancy hides: it is on file, it
 * looks like support, and nothing in the packet depends on it.
 */

const CODES: RequirementCode[] = ["R1", "R2", "R3", "R4", "R5"];

const UNCITED = "uncited";
type Focus = RequirementCode | typeof UNCITED;

interface Figure {
  claim: Claim;
  fact: SourceFact;
}

function factKey(figure: Figure): string {
  return `${figure.claim.id}:${figure.fact.id}`;
}

function factsOf(claims: EvidenceClaim[], claimId: string): SourceFact[] {
  return claims.find((claim) => claim.id === claimId)?.facts ?? [];
}

/** Every figure the requirement's cited claims state, in the order they arrive. */
function figuresFor(assessment: RequirementAssessment, claims: EvidenceClaim[]): Figure[] {
  return assessment.evidence.flatMap((citation) =>
    factsOf(claims, citation.claim.id).map((fact) => ({ claim: citation.claim, fact })),
  );
}

function isCited(assessments: RequirementAssessment[], claimId: string): boolean {
  return (
    assessments.find((a) => a.evidence.find((c) => c.claim.id === claimId) !== undefined) !==
    undefined
  );
}

function uncitedFigures(claims: EvidenceClaim[], assessments: RequirementAssessment[]): Figure[] {
  return claims
    .filter((claim) => !isCited(assessments, claim.id))
    .flatMap((claim) => claim.facts.map((fact) => ({ claim, fact })));
}

function uncitedClaims(claims: EvidenceClaim[], assessments: RequirementAssessment[]) {
  return claims.filter((claim) => !isCited(assessments, claim.id));
}

/**
 * What the rail says about a requirement's citations, in four words or so.
 *
 * "no claim cited" sat under a met requirement and under an inapplicable one and
 * under a real shortfall, and only the third is a finding. A reader scanning the
 * rail for what is wrong was reading the same phrase three times.
 */
const RAIL_DETAIL: Record<CitationState, string> = {
  cited: "cited evidence below, with its passages",
  not_required: "no citation required here",
  met: "met without a citation",
  short: "nothing cited",
};

/** One row of the requirement rail. */
function RailButton({
  label,
  detail,
  detailTone,
  chip,
  on,
  onChoose,
}: {
  label: string;
  detail: string;
  detailTone?: CitationState;
  chip: React.ReactNode;
  on: boolean;
  onChoose: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        className={on ? "rail__item rail__item--on" : "rail__item"}
        aria-current={on}
        onClick={onChoose}
      >
        <span className="rail__label">{label}</span>
        {chip}
        <span
          className={
            detailTone === undefined ? "rail__detail" : `rail__detail rail__detail--${detailTone}`
          }
          title={detailTone === "met" ? MET_UNCITED : undefined}
        >
          {detail}
        </span>
      </button>
    </li>
  );
}

function Rail({
  assessments,
  claims,
  focus,
  onFocus,
}: {
  assessments: RequirementAssessment[];
  claims: EvidenceClaim[];
  focus: Focus;
  onFocus: (focus: Focus) => void;
}) {
  const orphans = uncitedClaims(claims, assessments);
  return (
    <nav className="rail" aria-label="requirements">
      <ul>
        {CODES.map((code) => {
          const assessment = assessments.find((a) => a.requirement === code);
          if (assessment === undefined) {
            return (
              <RailButton
                key={code}
                label={code}
                detail="no assessment in the packet"
                chip={<span className="rail__chip rail__chip--absent">absent</span>}
                on={focus === code}
                onChoose={() => {
                  onFocus(code);
                }}
              />
            );
          }
          const verdict = VERDICT[assessment.verdict];
          const cited = citationState(assessment);
          return (
            <RailButton
              key={code}
              label={REQUIREMENT[code].label}
              detail={RAIL_DETAIL[cited]}
              detailTone={cited}
              chip={
                <span className={`verdict verdict--${assessment.verdict}`} title={verdict.meaning}>
                  <span aria-hidden="true">{verdict.glyph}</span> {verdict.label}
                </span>
              }
              on={focus === code}
              onChoose={() => {
                onFocus(code);
              }}
            />
          );
        })}
        {orphans.length > 0 && (
          <RailButton
            label="documents no requirement cites"
            detail="on file, and nothing in the packet relies on them"
            chip={<span className="rail__chip rail__chip--unused">unused</span>}
            on={focus === UNCITED}
            onChoose={() => {
              onFocus(UNCITED);
            }}
          />
        )}
      </ul>
    </nav>
  );
}

/** One extracted figure, as a control that opens its passage. */
function FigureButton({
  figure,
  on,
  onChoose,
}: {
  figure: Figure;
  on: boolean;
  onChoose: () => void;
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

function ClaimHead({ claim }: { claim: Claim }) {
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
function Figures({
  figures,
  active,
  onChoose,
}: {
  figures: Figure[];
  active: Figure | undefined;
  onChoose: (key: string) => void;
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
                />
              ))}
            </ul>
          </div>
        );
      })}
    </>
  );
}

function Middle({
  assessment,
  figures,
  active,
  onChoose,
  citedClaims,
}: {
  assessment: RequirementAssessment | undefined;
  figures: Figure[];
  active: Figure | undefined;
  onChoose: (key: string) => void;
  citedClaims: Claim[];
}) {
  if (assessment === undefined)
    return (
      <p
        className="trail__none"
        title="Nobody has looked, which is not a finding that the requirement is met or that it fails."
      >
        The packet carries no assessment for this requirement.
      </p>
    );
  const cited = citationState(assessment);
  return (
    <>
      {figures.length > 0 && <Figures figures={figures} active={active} onChoose={onChoose} />}
      {figures.length === 0 && citedClaims.length > 0 && (
        <div className="trail__group">
          {citedClaims.map((claim) => (
            <ClaimHead key={claim.id} claim={claim} />
          ))}
          <p
            className="trail__none"
            title="The claim is recorded; the extraction that pins its figures to text is not."
          >
            Cited, and no figure has been extracted from them yet.
          </p>
        </div>
      )}
      {/* The common case for this fund, and the one that must not render as a
          void between two panes. It says what the emptiness means and where the
          answer is, rather than leaving the reader to conclude the screen
          failed to load. */}
      {figures.length === 0 && citedClaims.length === 0 && cited === "short" && (
        <p className="trail__none">
          No claim on file is cited for this requirement. What is short, and who has to be written
          to, is below.
        </p>
      )}
      {figures.length === 0 && citedClaims.length === 0 && cited === "met" && (
        <p className="trail__none" title={MET_UNCITED}>
          Met without a citation, so there is no passage to open.
        </p>
      )}
      {!assessment.applicable && (
        <p className="trail__na" title="Nor is it evidence of anything being met.">
          {VERDICT.not_applicable.meaning} Not a gap.
        </p>
      )}
    </>
  );
}

export function EvidenceTrail({
  assessments,
  claims,
  gaps,
}: {
  assessments: RequirementAssessment[];
  claims: EvidenceClaim[];
  gaps: GapObservation[];
}) {
  const [focus, setFocus] = useState<Focus>("R1");
  const [chosenFact, setChosenFact] = useState<string | null>(null);

  const assessment =
    focus === UNCITED ? undefined : assessments.find((a) => a.requirement === focus);
  const figures =
    focus === UNCITED
      ? uncitedFigures(claims, assessments)
      : assessment === undefined
        ? []
        : figuresFor(assessment, claims);

  // The chosen figure, or the first one on offer. Derived rather than stored, so
  // moving to a requirement whose figures do not include the previous choice
  // lands on something real instead of on a blank third pane.
  const active = figures.find((figure) => factKey(figure) === chosenFact) ?? figures.at(0);

  const citedClaims = assessment === undefined ? [] : assessment.evidence.map((e) => e.claim);

  // Which requirements have a gap to state is decided in one place, by
  // `openRequirements`, rather than by this condition and that one drifting.
  const openAssessment =
    assessment === undefined ? undefined : openRequirements([assessment]).at(0);

  return (
    <>
      {/* Two columns when there is no passage to show. Most of this fund has no
          evidence for most requirements, so an empty third pane is the common
          case rather than the exception, and a third of the screen saying
          "nothing here" is a third of the screen. */}
      <div className={active === undefined ? "trail trail--no-passage" : "trail"}>
        <Rail assessments={assessments} claims={claims} focus={focus} onFocus={setFocus} />

        <div className="trail__middle">
          {focus === UNCITED ? (
            <>
              <p
                className="trail__orphan-note"
                title="A document nothing depends on is where a discrepancy survives review: it looks like support and no figure rests on it."
              >
                On file, cited by no requirement in this packet.
              </p>
              {figures.length === 0 ? (
                <p className="trail__none">
                  No figure has been extracted from these claims, so none can be opened to a
                  passage.
                </p>
              ) : (
                <Figures figures={figures} active={active} onChoose={setChosenFact} />
              )}
            </>
          ) : (
            <Middle
              assessment={assessment}
              figures={figures}
              active={active}
              onChoose={setChosenFact}
              citedClaims={citedClaims}
            />
          )}
        </div>

        {/* No pane at all when nothing is open, rather than a pane holding a box
            that explains its own emptiness. The middle column already says why
            there is no passage, and two statements of one absence read as a
            layout that failed to load. */}
        {active !== undefined && (
          <div className="trail__passage">
            <PassagePane
              citation={active.fact.citation}
              caption={`${active.fact.field_name} · ${active.fact.value_text}`}
            />
          </div>
        )}
      </div>

      {/* Under the three panes, at full width, because it is the CONCLUSION
          about the requirement above rather than a fourth column of it — and
          because the third line is a quotation, which needs a line length a
          reader can hold. In a 22rem column the fund's own sentence broke every
          four words and read as a caption. */}
      {openAssessment !== undefined && <GapAction assessment={openAssessment} gaps={gaps} />}
    </>
  );
}
