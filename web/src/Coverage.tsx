import type { Claim, RequirementAssessment, RequirementCode } from "./contracts";
import { formatDate } from "./format";
import { citationState, MET_UNCITED } from "./Gap";
import { EXECUTION_STATUS, REQUIREMENT, SOURCE_CLASS, VERDICT } from "./labels";
import type { EvidenceClaim } from "./responses";

/**
 * The coverage map: which document answers which requirement, for one holding.
 *
 * It is a matrix because the two things it has to expose are the two things a
 * list cannot show, and a table shows without being asked:
 *
 * * a **column with no mark** — a requirement nothing on file speaks to. The
 *   gap.
 * * a **row with no mark** — a document on file that no requirement relies on.
 *   The unused claim. There are seven in this fund, and one of them is a
 *   third-party valuation memo whose reliance window closed two years before the
 *   measurement date, sitting beside a mark that nothing supports.
 *
 * Deliberately small and deliberately without a single number on it. Presence
 * is the whole content: a mark or no mark, per pair. A count of unused claims
 * would be an aggregate over rows, which SPEC §5.3 assigns to the API — and it
 * would also be worse, because "one of these four rows is unused" is a thing to
 * look at and "1 unused" is a thing to read past.
 *
 * A requirement that does not ARISE is not a gap (INV-2). Its column is marked
 * as not applicable, quietly, and never as a hole.
 */

const CODES: RequirementCode[] = ["R1", "R2", "R3", "R4", "R5"];

/** Every claim in the picture: on file for this holding, or cited by an assessment. */
function claimsInvolved(
  onFile: EvidenceClaim[],
  assessments: RequirementAssessment[],
): { claim: Claim; onFile: boolean }[] {
  const seen = new Map<string, { claim: Claim; onFile: boolean }>();
  for (const claim of onFile) seen.set(claim.id, { claim, onFile: true });
  for (const assessment of assessments) {
    for (const citation of assessment.evidence) {
      // A cited claim the holding route did not list still belongs on the map.
      // Dropping it would hide a citation pointing at something not on file,
      // which is a stronger finding than either of the two this map is for.
      if (!seen.has(citation.claim.id))
        seen.set(citation.claim.id, { claim: citation.claim, onFile: false });
    }
  }
  return [...seen.values()];
}

function assessmentFor(assessments: RequirementAssessment[], code: RequirementCode) {
  return assessments.find((a) => a.requirement === code);
}

function citationOf(assessment: RequirementAssessment | undefined, claimId: string) {
  return assessment?.evidence.find((citation) => citation.claim.id === claimId);
}

/** True when no assessment cites this claim: evidence pointing at nothing. */
function isUnused(assessments: RequirementAssessment[], claimId: string): boolean {
  return (
    assessments.find((a) => a.evidence.find((c) => c.claim.id === claimId) !== undefined) ===
    undefined
  );
}

function HeaderCell({
  assessment,
  code,
}: {
  assessment: RequirementAssessment | undefined;
  code: RequirementCode;
}) {
  const requirement = REQUIREMENT[code];
  if (assessment === undefined) {
    return (
      <th
        scope="col"
        className="cov__req cov__req--absent"
        title="No assessment for this requirement is present in the packet."
      >
        {code}
      </th>
    );
  }
  const verdict = VERDICT[assessment.verdict];
  return (
    <th
      scope="col"
      className={`cov__req cov__req--${assessment.verdict}`}
      title={`${requirement.label} · ${verdict.label}. ${verdict.meaning}`}
    >
      {code}
      <span aria-hidden="true" className="cov__glyph">
        {verdict.glyph}
      </span>
      <span className="vh">{verdict.label}</span>
    </th>
  );
}

/**
 * A requirement's column foot: what the absence of marks above it means.
 *
 * Four findings, four marks. An empty column is a gap only when the requirement
 * arises AND is unmet — a requirement that does not arise is not a hole, and one
 * that is met with nothing of its own to cite is not one either. The column that
 * carried a green tick in its head and the word "gap" at its foot was saying
 * both at once.
 */
function FootCell({ assessment }: { assessment: RequirementAssessment | undefined }) {
  if (assessment === undefined) return <td className="cov__foot cov__foot--absent">—</td>;
  const state = citationState(assessment);
  if (state === "not_required")
    return (
      <td
        className="cov__foot cov__foot--na"
        title="This requirement does not arise for this position at this date. That is not a gap."
      >
        n/a
      </td>
    );
  if (state === "met")
    return (
      <td className="cov__foot cov__foot--met" title={MET_UNCITED}>
        met
      </td>
    );
  if (state === "short")
    return (
      <td
        className="cov__foot cov__foot--gap"
        title="The requirement arises, it is not met, and no claim on file is cited for it."
      >
        gap
      </td>
    );
  return (
    <td
      className="cov__foot cov__foot--cited"
      title="At least one claim is cited for this requirement."
    >
      cited
    </td>
  );
}

function Cell({
  assessment,
  claimId,
}: {
  assessment: RequirementAssessment | undefined;
  claimId: string;
}) {
  const citation = citationOf(assessment, claimId);
  if (citation === undefined)
    return (
      <td className="cov__cell">
        <span aria-hidden="true">·</span>
        <span className="vh">not cited</span>
      </td>
    );
  return (
    <td
      className={
        citation.is_subsequent ? "cov__cell cov__cell--subsequent" : "cov__cell cov__cell--on"
      }
    >
      <span aria-hidden="true">{citation.is_subsequent ? "◇" : "●"}</span>
      <span className="vh">
        {citation.is_subsequent ? "cited, dated after the measurement date" : "cited"}
      </span>
    </td>
  );
}

export function CoverageMap({
  claims,
  assessments,
}: {
  claims: EvidenceClaim[];
  assessments: RequirementAssessment[];
}) {
  const rows = claimsInvolved(claims, assessments);
  if (rows.length === 0) {
    return (
      <p
        className="cov__empty"
        title="Every applicable requirement below is a gap of the same kind: nothing to cite, rather than something that fails."
      >
        No document on file names this holding, so no row can be drawn.
      </p>
    );
  }
  return (
    <div className="cov">
      <table className="cov__grid">
        <caption className="vh">
          Documents on file for this holding against the five requirements, marked where a
          requirement cites the document.
        </caption>
        <thead>
          <tr>
            <th scope="col" className="cov__corner">
              document on file
            </th>
            {CODES.map((code) => (
              <HeaderCell key={code} code={code} assessment={assessmentFor(assessments, code)} />
            ))}
            <th scope="col" className="cov__corner cov__corner--end">
              use
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ claim, onFile }) => {
            const unused = isUnused(assessments, claim.id);
            return (
              <tr key={claim.id} className={unused ? "cov__row cov__row--unused" : "cov__row"}>
                <th scope="row" className="cov__claim">
                  <span className="cov__key">{claim.claim_key}</span>
                  <span className="cov__meta">
                    {SOURCE_CLASS[claim.source_class]} · {EXECUTION_STATUS[claim.execution_status]}
                    {" · relied on "}
                    {formatDate(claim.applicable_from)} →{" "}
                    {claim.applicable_to === null ? "open" : formatDate(claim.applicable_to)}
                  </span>
                  {!onFile && (
                    <span
                      className="cov__offfile"
                      title="An assessment cites this claim and the holding's document list does not contain it."
                    >
                      cited, not on the holding's list
                    </span>
                  )}
                </th>
                {CODES.map((code) => (
                  <Cell
                    key={code}
                    claimId={claim.id}
                    assessment={assessmentFor(assessments, code)}
                  />
                ))}
                <td className={unused ? "cov__use cov__use--unused" : "cov__use"}>
                  {unused ? "unused" : "in use"}
                </td>
              </tr>
            );
          })}
          <tr className="cov__feet">
            <th scope="row" className="cov__corner">
              evidence for it
            </th>
            {CODES.map((code) => (
              <FootCell key={code} assessment={assessmentFor(assessments, code)} />
            ))}
            <td />
          </tr>
        </tbody>
      </table>
      <p className="cov__legend">
        {/* The swatches carry their own classes. Sharing the cell classes made
            the legend indistinguishable from the grid to anything counting
            marks — including the guard that checks the grid has any. */}
        <span className="cov__legend-item">
          <span aria-hidden="true" className="cov__swatch cov__swatch--on">
            ●
          </span>{" "}
          cited
        </span>
        <span className="cov__legend-item">
          <span aria-hidden="true" className="cov__swatch cov__swatch--subsequent">
            ◇
          </span>{" "}
          cited, dated after the measurement date
        </span>
        <span className="cov__legend-item">
          <strong>gap</strong> a requirement that arises and nothing on file speaks to
        </span>
        <span className="cov__legend-item">
          <strong>unused</strong> a document on file that no requirement relies on
        </span>
      </p>
    </div>
  );
}
