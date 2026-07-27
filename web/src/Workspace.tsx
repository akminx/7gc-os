import { useState } from "react";

import type {
  Approval,
  DecisionStatus,
  DecisionType,
  DerivedFigure,
  HoldingRow,
  Mark,
  RequirementAssessment,
} from "./contracts";
import { failureDetail, namedActors, recordDecision } from "./data";
import { formatMoney } from "./format";
import { citationState, MET_UNCITED } from "./Gap";
import {
  DECISION_STATUS,
  DECISION_TYPE,
  DERIVATION_STATUS,
  POSITION_TYPE,
  REQUIREMENT,
  VALUATION_BASIS,
} from "./labels";
import type { MetaItem } from "./ui";
import {
  ApprovalState,
  CodeList,
  EvidenceItem,
  Figure,
  GapItem,
  Meta,
  NO_MARK_MEANING,
  NoMark,
  Section,
  SourceFactItem,
  SupportState,
  VerdictChip,
  Why,
} from "./ui";

/**
 * SPEC §12.2 · the company evidence workspace.
 *
 * The organising rule of this screen is INV-13: reported, validated and
 * supported are three facts, and the corpus contains a holding that reproduces
 * its arithmetic perfectly and has no evidence at all. Any layout that shows one
 * number is incapable of saying that, so the three sit side by side and none of
 * them is presented as the mark.
 */

function LineageNode({ figure }: { figure: DerivedFigure }) {
  return (
    <li className="lineage">
      <div className="lineage__head">
        <strong>{figure.label}</strong>
        <code>{figure.operator}</code>
        <span className="num">{formatMoney(figure.value)}</span>
      </div>
      <ul>
        {figure.inputs.map((input) => (
          <li key={input.ordinal} className="lineage__input">
            {input.fact !== null && <SourceFactItem fact={input.fact} />}
            {input.child !== null && (
              <ul>
                <LineageNode figure={input.child} />
              </ul>
            )}
          </li>
        ))}
      </ul>
    </li>
  );
}

/**
 * One requirement, and — when it cites nothing — which of the three reasons that
 * is. They used to share the sentence "No claim is cited for this requirement",
 * which reads as an omission under a requirement that does not arise and under
 * one that is met.
 */
function Assessment({ assessment }: { assessment: RequirementAssessment }) {
  const requirement = REQUIREMENT[assessment.requirement];
  const cited = citationState(assessment);
  return (
    <li className="check">
      <div className="check__head">
        <strong title={requirement.meaning}>{requirement.label}</strong>
        <VerdictChip verdict={assessment.verdict} />
        {assessment.pro_forma && (
          <span
            className="tag tag--exec"
            title="The mark relies on figures from a pro-forma document, one that anticipates a closing rather than recording it."
          >
            pro forma
          </span>
        )}
      </div>
      <CodeList label="reason codes" codes={assessment.reason_codes} />
      <CodeList label="next actions" codes={assessment.next_actions} />
      <Meta
        items={[
          { label: "policy version", value: assessment.policy_version },
          { label: "tracker label", value: assessment.tracker_label ?? "—" },
          {
            label: "applicable",
            value: assessment.applicable ? "yes" : "no · does not arise here",
            hint: "Not applicable and unsatisfied are opposite findings. The first means the question does not arise here; the second means it does and the evidence falls short.",
          },
        ]}
      />
      {cited === "not_required" && <p className="note">No citation is required here.</p>}
      {cited === "met" && (
        <p className="note" title={MET_UNCITED}>
          Met without a citation, from the execution status of the R2 claims.
        </p>
      )}
      {cited === "short" && (
        <p className="uncited">No claim is cited, and this requirement is short.</p>
      )}
      {cited === "cited" && (
        <ul className="evidence-list">
          {assessment.evidence.map((citation) => (
            <EvidenceItem key={citation.claim.id} citation={citation} />
          ))}
        </ul>
      )}
    </li>
  );
}

/**
 * Reported and validated, or the statement that neither exists.
 *
 * Support is deliberately outside this: it is a judgement about evidence and is
 * answerable for a row with no mark at all, which is why the third panel sits
 * beside this one rather than inside it.
 */
function MarkFigures({ mark }: { mark: Mark | null }) {
  if (mark === null) {
    return (
      <div className="figure figure--no-mark">
        <span className="figure__caption">Reported and validated — neither exists</span>
        <span className="figure__amount">
          <NoMark />
        </span>
        <span className="sub" title={NO_MARK_MEANING}>
          Not zero, and not the last mark carried forward.
        </span>
      </div>
    );
  }
  const derivation = DERIVATION_STATUS[mark.derivation_status];
  return (
    <>
      <Figure caption="Reported — tracker" money={mark.reported} tone="reported" />
      <div className="figure figure--validated">
        <span className="figure__caption">Validated — independently derived</span>
        <span className="figure__amount">
          {mark.validated === null ? "none" : formatMoney(mark.validated)}
        </span>
        <span className="sub" title={derivation.meaning}>
          {derivation.label} · {mark.derivation_reason}
        </span>
      </div>
    </>
  );
}

/** What the last decision this screen sent came back as. */
type Outcome =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "recorded"; decision: Approval }
  | { kind: "refused"; detail: string };

/**
 * SPEC §6.3 · the two decisions whose subject this screen actually holds.
 *
 * A transcription approval binds a source fact and a packet approval binds a
 * packet version; neither is a mark, so neither is offered here. That is not a
 * gap in the control — it is the point of §6.3. A row-level "approve" that
 * quietly covered all four would be exactly the collapse INV-18 names, and the
 * one that would let Anthropic's press-derived $8,000,000 be approved as fair
 * value by someone who meant only that it was transcribed faithfully.
 */
const MARK_DECISIONS: DecisionType[] = ["valuation", "management_assessment"];

const NOT_OFFERED_HERE =
  "A transcription approval applies to one extracted figure and a packet approval applies to a whole packet, so neither is offered on a screen whose subject is a single mark. None of the four decisions implies any of the others.";

/**
 * SPEC §3.1 · approve and reject, on the deployment that names its actors.
 *
 * Nothing here decides whether the decision is allowed. The request is sent, and
 * the ledger's answer is rendered verbatim — including its refusal, which is the
 * screen this product exists for: a valuation approval of a mark whose evidence
 * is a press article comes back naming the invariant, the trigger and the
 * requirement that is short. Restating that judgement in the browser would give
 * an auditor two opinions free to drift apart.
 */
function Decide({ row, actors }: { row: HoldingRow; actors: string[] }) {
  const [decisionType, setDecisionType] = useState<DecisionType>("valuation");
  const [actor, setActor] = useState<string>(actors[0] ?? "");
  const [reason, setReason] = useState<string>("");
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });

  const mark = row.mark;
  if (mark === null)
    return (
      <p className="note" title={NOT_OFFERED_HERE}>
        No mark at this measurement date, so there is no mark revision for a valuation or
        management-assessment decision to bind.
      </p>
    );

  const stated = reason.trim();
  const decide = (status: DecisionStatus) => {
    setOutcome({ kind: "sending" });
    recordDecision(
      {
        decision_type: decisionType,
        status,
        subject_id: String(mark.id),
        // The API stamps the policy version it computes verdicts at. A version
        // read off this screen and sent back would be the browser participating
        // in a binding it does not own (SPEC §5.3, INV-10).
        policy_version: null,
        reason: stated === "" ? null : stated,
      },
      actor,
    )
      .then((decision) => {
        setOutcome({ kind: "recorded", decision });
      })
      .catch((error: unknown) => {
        setOutcome({ kind: "refused", detail: failureDetail(error) });
      });
  };

  const busy = outcome.kind === "sending";
  const term = DECISION_TYPE[decisionType];
  return (
    <div className="decide">
      <label className="picker">
        <span>Decision type</span>
        <select
          value={decisionType}
          onChange={(event) => {
            setDecisionType(event.target.value as DecisionType);
          }}
        >
          {MARK_DECISIONS.map((type) => (
            <option key={type} value={type}>
              {DECISION_TYPE[type].label}
            </option>
          ))}
        </select>
      </label>
      <p className="note">{term.meaning}</p>

      <label className="picker">
        <span>Acting as</span>
        <select
          value={actor}
          onChange={(event) => {
            setActor(event.target.value);
          }}
        >
          {actors.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>

      <label className="picker">
        <span>Stated reason</span>
        <textarea
          className="decide__reason"
          rows={3}
          value={reason}
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />
      </label>
      <p
        className="note"
        title="A rejection with no stated reason records that a human said no, and nothing about what would change the answer."
      >
        Required to reject.
      </p>

      <div className="decide__actions">
        <button
          type="button"
          className="decide__act"
          disabled={busy}
          onClick={() => {
            decide("approved");
          }}
        >
          Approve — {term.label}
        </button>
        <button
          type="button"
          className="decide__act"
          disabled={busy || stated === ""}
          onClick={() => {
            decide("rejected");
          }}
        >
          Reject — {term.label}
        </button>
      </div>

      {outcome.kind === "sending" && <p className="note">Recording the decision…</p>}
      {outcome.kind === "recorded" && (
        <p
          className="decide__outcome"
          title="Decisions are append-only, so changing this answer means recording another one, never editing this."
        >
          Recorded: {DECISION_TYPE[outcome.decision.decision_type].label} ·{" "}
          {DECISION_STATUS[outcome.decision.status]} · {outcome.decision.actor_id} ·{" "}
          {outcome.decision.decided_at}
        </p>
      )}
      {outcome.kind === "refused" && (
        <p className="error">
          The ledger refused this decision: {outcome.detail} Nothing was recorded.
        </p>
      )}
      <p className="note">
        Transcription and packet approvals are not offered here. <Why text={NOT_OFFERED_HERE} />
      </p>
    </div>
  );
}

export function Workspace({ row, actors = namedActors() }: { row: HoldingRow; actors?: string[] }) {
  const mark = row.mark;
  const markItems: MetaItem[] =
    mark === null
      ? [{ label: "mark", value: <NoMark />, hint: NO_MARK_MEANING }]
      : [
          { label: "period", value: mark.period_id },
          { label: "mark revision", value: mark.revision },
          {
            label: "valuation basis",
            value: mark.basis === null ? "none declared" : VALUATION_BASIS[mark.basis],
          },
        ];
  return (
    <>
      <Section title={`${row.company_name} · ${row.holding_id}`}>
        <Meta
          items={[
            { label: "position type", value: POSITION_TYPE[row.position_type] },
            {
              label: "held at measurement date",
              value: row.held_at_date ? "yes" : "no — not an input to the held-at-date total",
            },
            ...markItems,
          ]}
        />
      </Section>

      <Section
        title="The mark"
        hint="Three facts, not one. Reported is what the tracker says. Validated is what the evidence independently derives. Support is a separate judgement entirely: a mark can be perfectly derivable and wholly unsupported."
      >
        <div className="triptych">
          <MarkFigures mark={mark} />
          <div className="figure figure--support">
            <span className="figure__caption">Support — evidence verdicts</span>
            <span className="figure__amount">
              <SupportState supported={row.supported} reasons={row.unsupported_reasons} />
            </span>
            <span
              className="sub"
              title="Decided by the API from the verdicts in the checklist below, never re-derived here."
            >
              from the verdicts below
            </span>
          </div>
        </div>
        {mark !== null && mark.lineage.length > 0 && (
          <ul className="lineage-list">
            {mark.lineage.map((figure) => (
              <LineageNode key={figure.id} figure={figure} />
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="PBC checklist"
        hint="One verdict per requirement, from a closed vocabulary of seven. An adverse verdict always carries a reason code."
      >
        <ul className="checklist">
          {row.assessments.map((assessment) => (
            <Assessment key={assessment.requirement} assessment={assessment} />
          ))}
        </ul>
      </Section>

      <Section
        title="Gap observations"
        hint="Why a document is absent decides what the auditor does next, so the kind travels with the gap. Hover a kind for what it means and who the letter goes to."
      >
        {row.gaps.length === 0 ? (
          <p className="note">No gap observation is recorded for this holding.</p>
        ) : (
          <ul className="gap-list">
            {row.gaps.map((gap) => (
              <GapItem key={gap.id} gap={gap} heading={<code>{gap.holding_id}</code>} />
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Approval state"
        note={
          actors.length === 0
            ? "Read-only: this deployment reports decisions and takes none."
            : undefined
        }
        hint={
          actors.length === 0
            ? "Four kinds of decision are recorded separately: approving a transcribed figure, approving a valuation, approving a packet, and rejecting any of them. Approving a figure as correctly transcribed says nothing about whether the valuation is right, so the kind of decision is named before its status."
            : "Four kinds of decision are recorded separately: approving a transcribed figure, approving a valuation, approving a packet, and rejecting any of them. Approving a figure as correctly transcribed says nothing about whether the valuation is right, so the kind of decision is named before its status. This deployment names people who may decide, so a decision can be recorded here. Whether it is allowed to be recorded is decided by the ledger, not by this screen."
        }
      >
        <ApprovalState approval={row.approval} approved={row.approved} />
        {actors.length > 0 && <Decide row={row} actors={actors} />}
      </Section>
    </>
  );
}
