import type { HoldingRow, PacketTotals, RequirementCode } from "./contracts";
import { formatDate, formatMoney } from "./format";
import { AUDIT_SCOPE, DERIVATION_STATUS, POSITION_TYPE, REQUIREMENT, TOTAL_KIND } from "./labels";
import type { PacketResponse } from "./responses";
import { ApprovalState, Figure, Meta, Section, SourceBadge, SupportState, VerdictChip } from "./ui";

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
 * screen. The kind and the label sit ABOVE the number rather than beside it,
 * because the failure being prevented is someone reading the figure and not the
 * caveat.
 *
 * Three counts, all supplied. The third — unheld gaps — used to be described
 * here as "the difference of the two, which belongs to the API", because it did.
 * The API now sends it, so the screen shows it instead of explaining why it
 * cannot.
 */
export function Totals({ totals }: { totals: PacketTotals }) {
  const kind = TOTAL_KIND[totals.kind];
  return (
    <div className="totals">
      <div className="totals__head">
        <span className={`total-kind total-kind--${totals.kind}`}>{kind.label}</span>
        <span className="totals__label">{totals.label}</span>
      </div>
      <p className="note">{kind.meaning}</p>
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
          },
          {
            label: "packet gap positions (held or not)",
            value: <strong>{totals.packet_gap_positions}</strong>,
          },
          {
            label: "unsupported but not held at this date",
            value: <strong>{totals.unheld_gap_positions}</strong>,
            hint: "Rows that are gaps in the packet but are not inputs to the total above.",
          },
        ]}
      />
      <p className="note">
        Packet gap positions is a <em>superset</em> of unsupported positions: it counts rows that
        were not held at this date and are therefore not inputs to the total above. The two are not
        additive. Their difference — the unheld gaps — is the third count, supplied by the API
        rather than subtracted here.
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
    <td>
      <VerdictChip verdict={assessment.verdict} />
    </td>
  );
}

function Row({ row, onOpen }: { row: HoldingRow; onOpen: (holdingId: string) => void }) {
  return (
    <tr>
      <th scope="row">
        <button type="button" className="linkish" onClick={() => onOpen(row.holding_id)}>
          {row.company_name}
        </button>
        <span className="sub">{POSITION_TYPE[row.position_type]}</span>
      </th>
      <td>{row.held_at_date ? "held at date" : "not held at date"}</td>
      <td className="num">{formatMoney(row.mark.reported)}</td>
      <td className="num">
        {row.mark.validated === null ? (
          <span className="absent" title={DERIVATION_STATUS[row.mark.derivation_status].meaning}>
            none · {row.mark.derivation_reason}
          </span>
        ) : (
          formatMoney(row.mark.validated)
        )}
      </td>
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
        note="Reported, validated and support are three separate facts about a mark (INV-13). They are three separate columns here and are never merged into one."
      >
        <div className="scroller">
          <table>
            <thead>
              <tr>
                <th scope="col">Company</th>
                <th scope="col">Held at date</th>
                <th scope="col">Reported (tracker)</th>
                <th scope="col">Validated (derived)</th>
                {CODES.map((code) => (
                  <th key={code} scope="col" title={REQUIREMENT[code].meaning}>
                    {code}
                  </th>
                ))}
                <th scope="col">Row support</th>
                <th scope="col">Approval</th>
              </tr>
            </thead>
            <tbody>
              {packet.rows.map((row) => (
                <Row key={row.holding_id} row={row} onOpen={onOpenCompany} />
              ))}
            </tbody>
          </table>
        </div>
        <p className="note">
          SPEC §7.1 asks the dashboard for <code>sufficient / applicable</code> per row.
          Applicability is now on the wire, per assessment — but the fraction is a count over rows,
          and counting rows is an aggregate §5.3 assigns to the API. So the five verdicts are shown
          individually rather than reduced to a ratio this screen is not allowed to compute.
        </p>
      </Section>
    </>
  );
}
