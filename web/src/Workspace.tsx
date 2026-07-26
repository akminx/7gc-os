import type { DerivedFigure, HoldingRow, Mark, RequirementAssessment } from "./contracts";
import { formatMoney } from "./format";
import { DERIVATION_STATUS, POSITION_TYPE, REQUIREMENT, VALUATION_BASIS } from "./labels";
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

function Assessment({ assessment }: { assessment: RequirementAssessment }) {
  const requirement = REQUIREMENT[assessment.requirement];
  return (
    <li className="check">
      <div className="check__head">
        <strong>{requirement.label}</strong>
        <VerdictChip verdict={assessment.verdict} />
        {assessment.pro_forma && (
          <span className="tag tag--exec" title="INV-4 · the mark relies on pro-forma inputs">
            pro forma
          </span>
        )}
      </div>
      <p className="note">{requirement.meaning}</p>
      <CodeList label="reason codes" codes={assessment.reason_codes} />
      <CodeList label="next actions" codes={assessment.next_actions} />
      <Meta
        items={[
          { label: "policy version", value: assessment.policy_version },
          { label: "tracker label", value: assessment.tracker_label ?? "—" },
          {
            label: "applicable",
            value: assessment.applicable
              ? "yes — this requirement arises here"
              : "no — this requirement does not arise for this position at this date",
            hint: "Supplied by the API. Not applicable and unsatisfied are opposite findings (INV-2).",
          },
        ]}
      />
      {assessment.evidence.length === 0 ? (
        <p className="note">No claim is cited for this requirement.</p>
      ) : (
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
        <span className="sub">{NO_MARK_MEANING}</span>
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
        <span className="sub">
          {derivation.label} · {mark.derivation_reason}
        </span>
      </div>
    </>
  );
}

export function Workspace({ row }: { row: HoldingRow }) {
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
        title="The mark — three facts, not one"
        note="Reported is what the tracker says. Validated is what the evidence independently derives. Support is a separate judgement entirely: a mark can be perfectly derivable and wholly unsupported."
      >
        <div className="triptych">
          <MarkFigures mark={mark} />
          <div className="figure figure--support">
            <span className="figure__caption">Support — evidence verdicts</span>
            <span className="figure__amount">
              <SupportState supported={row.supported} reasons={row.unsupported_reasons} />
            </span>
            <span className="sub">decided by the API from the verdicts in the checklist below</span>
          </div>
        </div>
        {mark !== null && (
          <p className="note">{DERIVATION_STATUS[mark.derivation_status].meaning}</p>
        )}
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
        note="One verdict per requirement, from a closed vocabulary of seven. An adverse verdict always carries a reason code."
      >
        <ul className="checklist">
          {row.assessments.map((assessment) => (
            <Assessment key={assessment.requirement} assessment={assessment} />
          ))}
        </ul>
      </Section>

      <Section
        title="Gap observations"
        note="Why a document is absent decides what the auditor does next, so the kind travels with the gap."
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
        note="Four independent decisions (SPEC §6.3). A transcription approval is not a fair-value approval, so the type is named before the status. This surface is read-only: it reports decisions and takes none."
      >
        <ApprovalState approval={row.approval} approved={row.approved} />
      </Section>
    </>
  );
}
