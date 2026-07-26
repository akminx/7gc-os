import type { DerivedFigure, HoldingRow, RequirementAssessment } from "./contracts";
import { formatMoney } from "./format";
import { DERIVATION_STATUS, POSITION_TYPE, REQUIREMENT, VALUATION_BASIS } from "./labels";
import {
  ApprovalState,
  CodeList,
  EvidenceItem,
  Figure,
  GapItem,
  Meta,
  Section,
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
            {input.fact !== null && (
              <div>
                <code>{input.fact.field_name}</code> = {input.fact.value_text}{" "}
                <span className="tag">{input.fact.state}</span>
                <blockquote>{input.fact.citation.quote}</blockquote>
                <span className="sub">
                  {input.fact.citation.document_version_id} · offsets{" "}
                  {input.fact.citation.span_start}–{input.fact.citation.span_end}
                </span>
              </div>
            )}
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

export function Workspace({ row }: { row: HoldingRow }) {
  const derivation = DERIVATION_STATUS[row.mark.derivation_status];
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
            { label: "period", value: row.mark.period_id },
            { label: "mark revision", value: row.mark.revision },
            {
              label: "valuation basis",
              value: row.mark.basis === null ? "none declared" : VALUATION_BASIS[row.mark.basis],
            },
          ]}
        />
      </Section>

      <Section
        title="The mark — three facts, not one"
        note="Reported is what the tracker says. Validated is what the evidence independently derives. Support is a separate judgement entirely: a mark can be perfectly derivable and wholly unsupported."
      >
        <div className="triptych">
          <Figure caption="Reported — tracker" money={row.mark.reported} tone="reported" />
          <div className="figure figure--validated">
            <span className="figure__caption">Validated — independently derived</span>
            <span className="figure__amount">
              {row.mark.validated === null ? "none" : formatMoney(row.mark.validated)}
            </span>
            <span className="sub">
              {derivation.label} · {row.mark.derivation_reason}
            </span>
          </div>
          <div className="figure figure--support">
            <span className="figure__caption">Support — evidence verdicts</span>
            <span className="figure__amount">
              <SupportState supported={row.supported} reasons={row.unsupported_reasons} />
            </span>
            <span className="sub">decided by the API from the verdicts in the checklist below</span>
          </div>
        </div>
        <p className="note">{derivation.meaning}</p>
        {row.mark.lineage.length > 0 && (
          <ul className="lineage-list">
            {row.mark.lineage.map((figure) => (
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
