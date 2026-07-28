import type { GapObservation, RequirementAssessment } from "./contracts";
import {
  actionGloss,
  GAP_KIND,
  REQUIREMENT,
  reasonGloss,
  SHORTFALL_ORIGIN,
  VERDICT,
} from "./labels";

/**
 * Gap → action → why. Three lines, always the same three, always in this order.
 *
 * The shape is the argument. A finding stated as one sentence — "R2 is missing"
 * — is something the application asserts. Split into what is short, what to do,
 * and the fund's own words about it, the third line is no longer the app's
 * claim: it is the record admitting the gap, quoted verbatim. That is the
 * difference between a screen an auditor reads and a screen an auditor checks.
 *
 * WHY is therefore never paraphrased, never truncated, never given an ellipsis.
 * When no quote is recorded the line says so and stays on the page, because a
 * block that silently loses its third line teaches the reader that two lines is
 * the normal shape and that the quote is decoration.
 *
 * ── The distinction this component exists to protect ─────────────────────
 *
 * `SUPPORT_OUTSIDE_ITS_OWN_RELIANCE_WINDOW` and `NO_APPLICABLE_SUPPORT_*` are
 * both verdict `missing`. One means a valuation memo is on file and its own
 * stated window has closed; the other means nothing was ever located. The
 * letters go to different people — a re-issue request to the valuer, a document
 * request to the company — and the verdict word cannot tell them apart.
 *
 * So the ORIGIN of the shortfall is rendered on its own line beside the code,
 * out of `labels.ts`, and the recipient is rendered beside the action. Neither
 * is derived here: both are a label attached to a code the API supplied, the
 * same way a verdict gets a glyph.
 */

/** "R1 · existence and cost and R4 · realization support", without index arithmetic. */
const NAMES = new Intl.ListFormat("en", { style: "long", type: "conjunction" });

/** The gap observation recorded against one requirement, or none. */
function observationFor(
  gaps: GapObservation[],
  assessment: RequirementAssessment,
): GapObservation | undefined {
  return gaps.find((gap) => gap.requirement === assessment.requirement);
}

/**
 * Which requirements have something to say here.
 *
 * Two API fields decide it and nothing else: `applicable`, which is the API's
 * answer to whether the requirement arises at all, and the verdict. A
 * requirement that does not arise is not a gap — INV-2 exists to keep those
 * apart — and a sufficient one has no action outstanding.
 */
export function openRequirements(assessments: RequirementAssessment[]): RequirementAssessment[] {
  return assessments.filter((a) => a.applicable && a.verdict !== "sufficient");
}

/**
 * Why a requirement cites no claim. Three answers wore one sentence — "no claim
 * cited" — and only one of them is a finding.
 *
 * `not_required` is a requirement that does not arise (INV-2), and reads as an
 * omission when it means nothing is owed. `met` is R5: a LABELLING requirement,
 * satisfied from the execution status of the claims cited at R2, so it is
 * sufficient with nothing of its own to cite (INV-4). `short` is the one that
 * has to stay loud: the requirement arises, it is not met, and nothing is
 * cited. The same three fields the API sent decide it; nothing here judges.
 */
export type CitationState = "cited" | "not_required" | "met" | "short";

export const MET_UNCITED =
  "This is a labelling requirement. It is satisfied by whether the documents behind the fair-value evidence are signed or still pro forma, so it cites no document of its own. Nothing is missing.";

export function citationState(assessment: RequirementAssessment): CitationState {
  if (assessment.evidence.length > 0) return "cited";
  if (!assessment.applicable) return "not_required";
  if (assessment.verdict === "sufficient") return "met";
  return "short";
}

function GapLine({
  assessment,
  observation,
}: {
  assessment: RequirementAssessment;
  observation: GapObservation | undefined;
}) {
  const verdict = VERDICT[assessment.verdict];
  return (
    <div className={`gaw__line gaw__line--${assessment.verdict}`}>
      <dt className="gaw__label" title={verdict.meaning}>
        {verdict.label}
      </dt>
      <dd className="gaw__body">
        <p className="gaw__subject">
          <span className="gaw__req" title={REQUIREMENT[assessment.requirement].meaning}>
            {REQUIREMENT[assessment.requirement].label}
          </span>
          {observation !== undefined && (
            <>
              <span className="gaw__doc">{observation.missing_document}</span>
              <span
                className={`gap-kind gap-kind--${observation.kind}`}
                title={`${GAP_KIND[observation.kind].meaning} ${GAP_KIND[observation.kind].next}`}
              >
                {GAP_KIND[observation.kind].label}
              </span>
            </>
          )}
        </p>
        {assessment.reason_codes.length === 0 ? (
          <p className="gaw__none">
            The API records no reason code for this requirement, so nothing here states what is
            short. That is a finding about the assessment, not about the position.
          </p>
        ) : (
          <ul className="gaw__reasons">
            {assessment.reason_codes.map((code) => {
              const reason = reasonGloss(code);
              const origin = SHORTFALL_ORIGIN[reason.origin];
              return (
                <li key={code}>
                  <code className="gaw__code">{code}</code>
                  <span className="gaw__gloss">{reason.label}</span>
                  <span
                    className={`origin origin--${reason.origin}`}
                    title={`${origin.meaning} ${reason.meaning}`}
                  >
                    {origin.label}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </dd>
    </div>
  );
}

/**
 * Which OTHER requirements for this holding carry a request.
 *
 * A requirement with nothing to ask for is not the same as a holding nobody has
 * asked about, and for four measurement dates this component said it was.
 * Lucra at FY2024 is the case: its fair-value support rests on a non-binding
 * term sheet, which the policy table answers with a reason and no action —
 * because the fix is the executed Series A-1 agreement, and existence-and-cost
 * is already asking for exactly that. One document, one request, filed once.
 *
 * So the sentence read "Nobody has been asked for anything yet" beside an open
 * request with company counsel. Scoped to the requirement it was true; read as
 * English it was false, and it is the kind of false that makes a reader stop
 * chasing something that is still outstanding.
 */
export function askedElsewhere(
  row: RequirementAssessment[],
  assessment: RequirementAssessment,
): RequirementAssessment[] {
  return row.filter((a) => a.requirement !== assessment.requirement && a.next_actions.length > 0);
}

function ActionLine({
  assessment,
  row,
}: {
  assessment: RequirementAssessment;
  row: RequirementAssessment[] | undefined;
}) {
  //: Three states, not two. `undefined` is a caller that did not supply the
  //: rest of the row, and the honest answer there is the scoped fact alone —
  //: guessing at siblings we were not given is how the first version got it
  //: wrong in the other direction.
  const elsewhere = row === undefined ? undefined : askedElsewhere(row, assessment);
  return (
    <div className="gaw__line gaw__line--action">
      <dt className="gaw__label">action</dt>
      <dd className="gaw__body">
        {assessment.next_actions.length === 0 ? (
          <p className="gaw__none">
            {elsewhere === undefined ? (
              <>Nothing is being requested under this requirement.</>
            ) : elsewhere.length === 0 ? (
              <>
                Nothing is being requested under this requirement, and nothing is being requested
                under any other one for this holding at this date. Nobody has been asked for
                anything yet.
              </>
            ) : (
              <>
                Nothing is being requested under this requirement, because the request is filed
                under{" "}
                {/* Joined by `Intl.ListFormat` rather than by index arithmetic.
                    The first version placed its separators with
                    `i === elsewhere.length - 1`, which the §5.3 boundary check
                    reads — correctly, since it cannot see intent — as the page
                    computing on a number the API owns. */}
                <strong>
                  {NAMES.format(elsewhere.map((a) => REQUIREMENT[a.requirement].label))}
                </strong>
                . One missing document is asked for once. Check there before treating this as
                unasked.
              </>
            )}
          </p>
        ) : (
          <ul className="gaw__actions">
            {assessment.next_actions.map((code) => {
              const action = actionGloss(code);
              return (
                <li key={code}>
                  <code className="gaw__code">{code}</code>
                  <span className="gaw__gloss">{action.label}</span>
                  <span className="gaw__to" title={action.meaning}>
                    to {action.recipient}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </dd>
    </div>
  );
}

/**
 * The fund's own words, verbatim.
 *
 * `source_quote` is transcribed from the fund's records — a tracker note, a
 * memo line, a filename. It is set as a quotation and attributed, so a reader
 * can see that the sentence is the fund's and not this application's.
 */
function WhyLine({ observation }: { observation: GapObservation | undefined }) {
  return (
    <div className="gaw__line gaw__line--why">
      <dt className="gaw__label">why</dt>
      <dd className="gaw__body">
        {observation === undefined ? (
          <p className="gaw__none">
            No gap observation is recorded against this requirement, so the fund's records are not
            quoted here. The finding rests on the reason code above alone.
          </p>
        ) : (
          <figure className="gaw__quote">
            <blockquote className="verbatim">{observation.source_quote}</blockquote>
            <figcaption>
              the fund's own record · gap observation {observation.id} · remediation{" "}
              {observation.remediation}
            </figcaption>
          </figure>
        )}
      </dd>
    </div>
  );
}

export function GapAction({
  assessment,
  gaps,
  row,
}: {
  assessment: RequirementAssessment;
  gaps: GapObservation[];
  /**
   * Every requirement assessed for this holding at this date, including the
   * open one. Optional because the action line degrades to a scoped statement
   * without it rather than to a wrong one.
   */
  row?: RequirementAssessment[];
}) {
  const observation = observationFor(gaps, assessment);
  return (
    <dl className="gaw">
      <GapLine assessment={assessment} observation={observation} />
      <ActionLine assessment={assessment} row={row} />
      <WhyLine observation={observation} />
    </dl>
  );
}
