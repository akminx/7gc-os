import { useState } from "react";

import type { Claim, GapObservation, RequirementAssessment, RequirementCode } from "./contracts";
import { readTrail, trailHref, updateTrail } from "./deeplink";
import type { Figure } from "./Figures";
import { ClaimHead, Figures, factKey, OtherFigures } from "./Figures";
import type { CitationState } from "./Gap";
import { citationState, GapAction, MET_UNCITED, openRequirements } from "./Gap";
import { REQUIREMENT, VERDICT } from "./labels";
import { PassagePane } from "./Passage";
import type { EvidenceClaim, EvidenceFact } from "./responses";

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
 *
 * The middle pane is in TWO parts and they are not the same evidence. The
 * ledger binds a CLAIM to a requirement, so Fluidstack's Series A purchase
 * agreement — legitimately relied upon for existence and for fair value — put
 * all twelve of its cited figures under both, and clicking R1 then R2 showed
 * the same window twice. The API now says per FIGURE which requests it answers,
 * so the figures that answer THIS request lead, and the rest of what the same
 * documents state follows under its own heading.
 *
 * Followed, not dropped. The document really does state them; they answer a
 * different question. Hiding them would be this pane deciding what an auditor
 * may read next to the sentence, which is the one thing the passage pane's own
 * docstring says it must not do.
 */

const CODES: RequirementCode[] = ["R1", "R2", "R3", "R4", "R5"];

const UNCITED = "uncited";
type Focus = RequirementCode | typeof UNCITED;

function factsOf(claims: EvidenceClaim[], claimId: string): EvidenceFact[] {
  return claims.find((claim) => claim.id === claimId)?.facts ?? [];
}

/** Every figure the requirement's cited claims state, in the order they arrive. */
function figuresFor(assessment: RequirementAssessment, claims: EvidenceClaim[]): Figure[] {
  return assessment.evidence.flatMap((citation) =>
    factsOf(claims, citation.claim.id).map((fact) => ({ claim: citation.claim, fact })),
  );
}

/**
 * Most direct answer first, then the order the documents state them.
 *
 * Ordering only. `answer_rank` is supplied by the API — which figure most
 * directly answers a request is a statement about evidence — and the comparison
 * below is `<`/`>` rather than a subtraction, because §5.3 permits ordering a
 * display and forbids arithmetic on a value the API owns. The sort is stable, so
 * equal ranks stay in arrival order — the document's own order, and the right
 * tiebreak for figures nobody has ranked. Sorted on a COPY, because the array is
 * the packet's own and reordering it in place would move figures under a
 * requirement nobody chose.
 */
function byDirectness(figures: Figure[], code: RequirementCode): Figure[] {
  const rank = (figure: Figure): number => figure.fact.answer_rank[code] ?? UNRANKED;
  return [...figures].sort((a: Figure, b: Figure) =>
    rank(a) < rank(b) ? -1 : rank(a) > rank(b) ? 1 : 0,
  );
}

/**
 * A figure the API sent no rank for, which on a well-formed response cannot
 * happen: a rank arrives for every request a figure answers. Ranked last rather
 * than first, so a missing key can never promote something to the top of the
 * pane.
 */
const UNRANKED = Number.MAX_SAFE_INTEGER;

/**
 * The cited claims' figures, split by whether they answer the request in focus.
 *
 * `answers_requirements` is the API's judgement and is only READ here — a
 * component that decided `fund_shares` is about existence would be writing
 * evidence policy in TypeScript, which `scripts/check-web-arch.mjs` refuses and
 * is right to.
 *
 * The answering half is ordered by how directly each figure answers the request,
 * so opening a requirement lands on the figure that IS the answer: the fund's
 * aggregate purchase price under existence and cost, the round's price per share
 * under fair value, the gross consideration under realisation. The other half
 * keeps arrival order — it is grouped under the document that states it, and
 * re-ranking figures against a request they do not answer would be a claim
 * nobody made.
 */
function splitByRequirement(
  figures: Figure[],
  code: RequirementCode,
): { answering: Figure[]; other: Figure[] } {
  return {
    answering: byDirectness(
      figures.filter((figure) => figure.fact.answers_requirements.includes(code)),
      code,
    ),
    other: figures.filter((figure) => !figure.fact.answers_requirements.includes(code)),
  };
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

function Middle({
  assessment,
  answering,
  other,
  active,
  onChoose,
  citedClaims,
}: {
  assessment: RequirementAssessment | undefined;
  answering: Figure[];
  other: Figure[];
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
  const figures = [...answering, ...other];
  return (
    <>
      {answering.length > 0 && <Figures figures={answering} active={active} onChoose={onChoose} />}
      {/* A claim relied upon for this request, none of whose figures is
          declared as answering it. Said out loud: the alternative renders as an
          empty pane under a cited document, which reads as a page that failed
          to load rather than as a finding about the evidence. */}
      {answering.length === 0 && other.length > 0 && (
        <p className="trail__none">
          The documents cited here state {other.length} {other.length === 1 ? "figure" : "figures"},
          and none of them is declared as answering {REQUIREMENT[assessment.requirement].label}.
          They are below.
        </p>
      )}
      {other.length > 0 && (
        <OtherFigures
          figures={other}
          active={active}
          onChoose={onChoose}
          code={assessment.requirement}
          answeringCount={answering.length}
        />
      )}
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

/**
 * The link to this exact passage, ready to send.
 *
 * The whole point of putting the trail in the URL: a partner who has found the
 * sentence supporting a mark can send an auditor THE SENTENCE rather than
 * directions to it. Directions are a set of clicks the recipient can take
 * wrongly, and only the sender ever sees them work.
 *
 * The URL is shown as well as copied, because a clipboard write can be refused
 * — an insecure origin, a browser that does not implement it, a permission the
 * viewer has denied — and a button that silently does nothing is worse than one
 * that hands over the text to copy by hand.
 */
function CopyTrailLink() {
  const [state, setState] = useState<"idle" | "copied" | "manual">("idle");
  const href = trailHref(readTrail());
  return (
    <p className="trail__share">
      <button
        type="button"
        className="linkish"
        onClick={() => {
          navigator.clipboard
            ?.writeText(href)
            .then(() => {
              setState("copied");
            })
            .catch(() => {
              setState("manual");
            }) ?? setState("manual");
        }}
      >
        {state === "copied" ? "Link copied" : "Copy a link to this passage"}
      </button>
      <span
        className="trail__share-note"
        title="The link names the fund-period, the company, the requirement and the figure, so it opens on this passage rather than on the dashboard."
      >
        opens here, not on the dashboard
      </span>
      {state === "manual" && <code className="trail__share-url">{href}</code>}
    </p>
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
  // Opened from the address bar when a link names a requirement and a figure,
  // so a partner can send the PASSAGE rather than directions to it. Read once,
  // at mount; after that the reader's clicks own the URL.
  const [focus, setFocus] = useState<Focus>(() => readTrail().requirement ?? "R1");
  const [chosenFact, setChosenFact] = useState<string | null>(() => readTrail().fact ?? null);

  const chooseFocus = (next: Focus) => {
    setFocus(next);
    // The unused-documents row is not a requirement and there is no code to put
    // in the URL for it, so that segment and everything after it is dropped
    // rather than left naming the requirement the reader has just left.
    updateTrail(
      next === UNCITED
        ? { requirement: undefined, fact: undefined }
        : { requirement: next, fact: undefined },
    );
  };

  const chooseFact = (key: string) => {
    setChosenFact(key);
    updateTrail({ fact: key });
  };

  const assessment =
    focus === UNCITED ? undefined : assessments.find((a) => a.requirement === focus);
  const cited =
    focus === UNCITED
      ? uncitedFigures(claims, assessments)
      : assessment === undefined
        ? []
        : figuresFor(assessment, claims);

  // Split only when a requirement is in focus. The unused-documents row is not
  // a requirement, so there is nothing for a figure to answer or not answer
  // there and every figure leads.
  const { answering, other } =
    assessment === undefined
      ? { answering: cited, other: [] as Figure[] }
      : splitByRequirement(cited, assessment.requirement);

  // The chosen figure, or the first one that ANSWERS the request in focus.
  // Derived rather than stored, so moving between requirements lands on
  // something real instead of on a blank third pane — and the default now lands
  // on the figure this request rests on rather than on whichever figure the
  // shared document happened to state first, which is what made R1 and R2 open
  // the same passage.
  const figures = [...answering, ...other];
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
        <Rail assessments={assessments} claims={claims} focus={focus} onFocus={chooseFocus} />

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
                <Figures figures={figures} active={active} onChoose={chooseFact} />
              )}
            </>
          ) : (
            <Middle
              assessment={assessment}
              answering={answering}
              other={other}
              active={active}
              onChoose={chooseFact}
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
            <CopyTrailLink />
          </div>
        )}
      </div>

      {/* Under the three panes, at full width, because it is the CONCLUSION
          about the requirement above rather than a fourth column of it — and
          because the third line is a quotation, which needs a line length a
          reader can hold. In a 22rem column the fund's own sentence broke every
          four words and read as a caption. */}
      {openAssessment !== undefined && (
        <GapAction assessment={openAssessment} gaps={gaps} row={assessments} />
      )}
    </>
  );
}
