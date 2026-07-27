import type { HoldingRow, Mark, PacketTotals, RequirementCode } from "./contracts";
import { formatDate, formatMoney } from "./format";
import { AUDIT_SCOPE, DERIVATION_STATUS, POSITION_TYPE, REQUIREMENT, TOTAL_KIND } from "./labels";
import type { PacketResponse } from "./responses";
import {
  ApprovalState,
  Figure,
  Meta,
  NoMark,
  Section,
  SourceBadge,
  SupportState,
  VerdictChip,
  Why,
} from "./ui";

const CODES: RequirementCode[] = ["R1", "R2", "R3", "R4", "R5"];

/**
 * SPEC §12.1 · the dual-fund dashboard.
 *
 * Every figure on this screen arrives from the API already computed. The rows
 * are rendered in the order the packet supplies them; nothing here sums,
 * counts, ranks or scores.
 */

/**
 * INV-19 · a total that says what it is a total OF, or it does not go on the
 * screen. The kind sits ABOVE the number and the label is the figure's own
 * caption, because the failure being prevented is someone reading the figure
 * and not the caveat.
 *
 * The label used to be rendered twice and glossed a third time in a paragraph
 * under it. It is stated once now, on the figure it qualifies; what the kind
 * means is on the kind.
 *
 * Three counts, all supplied by the API. They are not additive, which is the
 * one thing about them a reader cannot infer, so that stays on the page and the
 * paragraph explaining it does not.
 */
const NOT_ADDITIVE =
  "Packet gap positions is a superset of unsupported positions: it counts rows that were not held at this measurement date and are therefore not inputs to the total above. Their difference is the third count.";

export function Totals({ totals }: { totals: PacketTotals }) {
  const kind = TOTAL_KIND[totals.kind];
  return (
    <div className="totals">
      <div className="totals__head">
        <span className={`total-kind total-kind--${totals.kind}`} title={kind.meaning}>
          {kind.label}
        </span>
      </div>
      <p
        className={
          totals.contains_unsupported_inputs
            ? "qualified qualified--yes"
            : "qualified qualified--no"
        }
      >
        {totals.contains_unsupported_inputs
          ? "This total contains unsupported inputs."
          : "This total contains no unsupported input."}
      </p>
      <div className="totals__figures">
        <Figure caption={totals.label} money={totals.amount} />
        <Figure
          caption="of which nothing supports — unsupported subtotal"
          money={totals.unsupported_amount}
          tone="unsupported"
        />
      </div>
      <Meta
        items={[
          {
            label: "unsupported positions held at this date",
            value: <strong>{totals.unsupported_positions}</strong>,
            hint: "Inputs to the total above, and nothing supports them.",
          },
          {
            label: "packet gap positions (held or not)",
            value: <strong>{totals.packet_gap_positions}</strong>,
            hint: NOT_ADDITIVE,
          },
          {
            label: "unsupported but not held at this date",
            value: <strong>{totals.unheld_gap_positions}</strong>,
            hint: "Gaps in the packet, and not inputs to the total above.",
          },
        ]}
      />
      <p className="note">
        The three counts are not additive. <Why text={NOT_ADDITIVE} />
      </p>
    </div>
  );
}

function AssessmentCell({ row, code }: { row: HoldingRow; code: RequirementCode }) {
  const assessment = row.assessments.find((a) => a.requirement === code);
  if (assessment === undefined) {
    return (
      <td
        className="cell--absent"
        title="No assessment for this requirement is present in the packet."
      >
        absent
      </td>
    );
  }
  return (
    <td className="cell--verdict">
      <VerdictChip verdict={assessment.verdict} compact />
    </td>
  );
}

/**
 * The reported and validated columns, or the statement that there is no mark.
 *
 * One cell spanning both when the mark is absent, rather than two cells that
 * happen to be empty: an auditor reading down a column of amounts reads a blank
 * as nothing owed, and "there is no mark at this date" is a different finding.
 */
function MarkCells({ mark }: { mark: Mark | null }) {
  if (mark === null) {
    return (
      <td className="cell--no-mark" colSpan={2}>
        <NoMark />
      </td>
    );
  }
  return (
    <>
      <td className="num">{formatMoney(mark.reported)}</td>
      <td className="num">
        {mark.validated === null ? (
          // One text node, wrapped and set small by the stylesheet. Set on a
          // single line this is the longest string in the table and eight
          // identical copies of it are what the eye lands on instead of the
          // verdicts — but the reason is not abbreviated, softened or moved into
          // a tooltip, because it is what an auditor asks next.
          <span className="absent" title={DERIVATION_STATUS[mark.derivation_status].meaning}>
            none · {mark.derivation_reason}
          </span>
        ) : (
          formatMoney(mark.validated)
        )}
      </td>
    </>
  );
}

/**
 * One position.
 *
 * The row is clickable and the company name is a real button inside it, rather
 * than the row being the only target: a `tr` with a click handler is unreachable
 * from a keyboard, and the pre-flight for this screen is that a partner can
 * reach a company and open its trail without a mouse.
 */
function Row({ row, onOpen }: { row: HoldingRow; onOpen: (holdingId: string) => void }) {
  return (
    <tr
      className="hrow"
      onClick={() => {
        onOpen(row.holding_id);
      }}
    >
      <th scope="row">
        <button type="button" className="linkish" onClick={() => onOpen(row.holding_id)}>
          {row.company_name}
        </button>
        <span className="sub">{POSITION_TYPE[row.position_type]}</span>
      </th>
      <td className="cell--held">
        <span className={row.held_at_date ? "held held--yes" : "held held--no"}>
          {row.held_at_date ? "held at date" : "not held at date"}
        </span>
      </td>
      <MarkCells mark={row.mark} />
      {CODES.map((code) => (
        <AssessmentCell key={code} row={row} code={code} />
      ))}
      <td>
        <SupportState supported={row.supported} reasons={row.unsupported_reasons} />
      </td>
      <td>
        <ApprovalState approval={row.approval} approved={row.approved} />
      </td>
    </tr>
  );
}

export function Dashboard({
  packet,
  onOpenCompany,
}: {
  packet: PacketResponse;
  onOpenCompany: (holdingId: string) => void;
}) {
  const scope = AUDIT_SCOPE[packet.period.audit_scope];
  return (
    <>
      <Section title={`${packet.fund_id} · ${packet.period.label}`}>
        <p className="note">
          <SourceBadge source={packet.source} />
        </p>
        <Meta
          items={[
            { label: "measurement date", value: formatDate(packet.period.period_date) },
            { label: "audit scope", value: `${scope.label} — ${scope.meaning}` },
            { label: "schema version", value: packet.schema_version },
            { label: "policy version", value: packet.policy_version },
            { label: "generated at", value: packet.generated_at },
          ]}
        />
        <Totals totals={packet.totals} />
      </Section>

      <Section
        title="Holdings"
        hint="Reported is what the tracker says. Validated is what the evidence independently derives. Support is a separate judgement about the evidence. A mark can be perfectly derivable and still unsupported, so the three are never merged into one column. The five verdicts are shown individually rather than as a score, because a ratio hides which requirement is short."
      >
        <div className="scroller">
          <table>
            <thead>
              <tr>
                <th scope="col">Company</th>
                <th scope="col">Held at date</th>
                <th scope="col" className="num">
                  Reported (tracker)
                </th>
                <th scope="col" className="num">
                  Validated (derived)
                </th>
                {CODES.map((code) => (
                  <th
                    key={code}
                    scope="col"
                    className="rcol"
                    title={`${REQUIREMENT[code].label} · ${REQUIREMENT[code].meaning}`}
                  >
                    {code}
                  </th>
                ))}
                <th scope="col" className="col-support">
                  Row support
                </th>
                <th scope="col" className="col-approval">
                  Approval
                </th>
              </tr>
            </thead>
            <tbody>
              {packet.rows.map((row) => (
                <Row key={row.holding_id} row={row} onOpen={onOpenCompany} />
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}
