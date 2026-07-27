import type { PacketTotals } from "./contracts";
import { formatDate, formatMoney } from "./format";
import { AUDIT_SCOPE, TOTAL_KIND } from "./labels";
import type { ScorecardCounts, ScorecardLine, ScorecardResponse } from "./reconcile.contracts";
import { Figure, Meta, Section, SourceBadge } from "./ui";

/**
 * SPEC §12.1 · the completeness scorecard — one line per fund-period.
 *
 * The thing a partner reads first, and the reason every number on it is the
 * API's. "0 of 8 positions fully supported" is two integers the API counted,
 * interpolated into a sentence; SPEC §5.3 forbids this surface deriving the
 * ratio, and a scorecard is exactly where a plausible wrong denominator would
 * survive review.
 */

/**
 * The line itself.
 *
 * Four separate facts, kept separate: how many positions the packet holds, how
 * many are fully supported, how many carry an open gap, and how many rest on a
 * pro forma artifact. The last is INV-4 — a mark labelled pro forma is resting
 * on a document nobody has signed, and labelling it correctly is not support.
 */
function Sentence({ counts }: { counts: ScorecardCounts }) {
  return (
    <p>
      <strong>
        {counts.fully_supported} of {counts.positions}
      </strong>{" "}
      {counts.positions === 1 ? "position" : "positions"} fully supported,{" "}
      <strong>{counts.open_gap_positions}</strong> with open gaps,{" "}
      <strong>{counts.pro_forma_positions}</strong> marked pro forma pending executed documentation.
    </p>
  );
}

/**
 * INV-19 · the total says what it is a total OF, on the same line as the counts.
 *
 * The kind and the qualification sit with the figure rather than in a field
 * nobody rendered, because the failure this prevents is a partner reading
 * 25,648,515 as the fund's audited value.
 */
function LineTotal({ totals }: { totals: PacketTotals }) {
  const kind = TOTAL_KIND[totals.kind];
  return (
    <div className="totals">
      <Figure caption={kind.label} money={totals.amount} tone="reported" />
      <p
        className={
          totals.contains_unsupported_inputs
            ? "qualified qualified--yes"
            : "qualified qualified--no"
        }
      >
        {totals.contains_unsupported_inputs
          ? "Unsupported value is inside this figure."
          : "Nothing unsupported is inside this figure."}
      </p>
      <Meta
        items={[
          { label: "what this figure is a total of", value: totals.label, hint: kind.meaning },
          {
            label: "unsupported subtotal inside it",
            value: formatMoney(totals.unsupported_amount),
          },
          {
            label: "unsupported positions that are inputs to it",
            value: <strong>{totals.unsupported_positions}</strong>,
            hint: "Held at the measurement date, and therefore summed into the figure above.",
          },
        ]}
      />
    </div>
  );
}

function Counts({ counts }: { counts: ScorecardCounts }) {
  return (
    <Meta
      items={[
        { label: "positions in the packet", value: <strong>{counts.positions}</strong> },
        { label: "fully supported", value: <strong>{counts.fully_supported}</strong> },
        {
          label: "with open gaps",
          value: <strong>{counts.open_gap_positions}</strong>,
          hint: "Rows where some applicable requirement is not sufficient.",
        },
        { label: "marked pro forma", value: <strong>{counts.pro_forma_positions}</strong> },
        { label: "held at the measurement date", value: <strong>{counts.held_at_date}</strong> },
        {
          label: "not held at the measurement date",
          value: <strong>{counts.not_held_at_date}</strong>,
          hint: "In the packet because the audit letter asks for realised investments, and not an input to the total, because the position was not held at this date.",
        },
      ]}
    />
  );
}

function Line({ line }: { line: ScorecardLine }) {
  return (
    <li className="check">
      <p className="check__head">
        <strong>
          {line.fund_id} · {line.label}
        </strong>
        {line.period_date !== null && <span className="sub">{formatDate(line.period_date)}</span>}
        {line.audit_scope !== null && (
          <span className="tag" title={AUDIT_SCOPE[line.audit_scope].meaning}>
            {AUDIT_SCOPE[line.audit_scope].label}
          </span>
        )}
      </p>
      {line.counts === null ? (
        <p className="absent">
          {line.absent_reason ?? "No packet could be assembled for this fund-period."}
        </p>
      ) : (
        <>
          <Sentence counts={line.counts} />
          <Counts counts={line.counts} />
        </>
      )}
      {line.counts !== null && line.totals === null && (
        <p className="absent">
          No total at this date: the ledger holds no mark for any position in this packet. Not zero
          — there is no figure.
        </p>
      )}
      {line.totals !== null && <LineTotal totals={line.totals} />}
    </li>
  );
}

export function Scorecard({ scorecard }: { scorecard: ScorecardResponse }) {
  return (
    <Section
      title="Completeness scorecard"
      note="One line per fund-period, in the order the API lists them. Every count is computed by the API from the packet; this surface formats and orders, and derives nothing."
    >
      <p className="note">
        <SourceBadge source={scorecard.source} />
      </p>
      {scorecard.periods.length === 0 ? (
        <p className="note">
          The API lists no fund-period a packet can be built for. That is an empty ledger, not an
          empty screen.
        </p>
      ) : (
        <ul className="checklist">
          {scorecard.periods.map((line) => (
            <Line key={`${line.fund_id}/${line.period_id}`} line={line} />
          ))}
        </ul>
      )}
      <p className="note">
        "0 of 8" is two counts the ledger supplied, side by side. Nothing on this screen divides one
        by the other: a percentage would read as a grade, and a position either has the evidence it
        needs or it does not.
      </p>
    </Section>
  );
}
