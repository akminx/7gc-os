import { formatAmount } from "./format";
import type { Term } from "./labels";
import type {
  Finding,
  FindingScope,
  ReconciliationResponse,
  ScopeBucket,
} from "./reconcile.contracts";
import { Meta, Section } from "./ui";

/**
 * SPEC §12.4 · the reconciliation report.
 *
 * The client's stated core pain, made visible: two workbooks, thirty-two places
 * where they disagree with each other. Every figure arrives already computed —
 * the counts, and the delta between each pair — because SPEC §5.3 assigns all
 * of them to the API. Nothing here adds, subtracts or divides.
 *
 * Two separations are structural rather than stylistic, and both are the shape
 * of the data rather than a rule someone has to remember:
 *
 * * **Scope.** The API sends three buckets, not one list with a scope column, so
 *   there is no flat array to render by accident. A disagreement about 6/30/2025
 *   is not a disagreement about a measurement date the auditor asked about, and
 *   the two never appear in the same list or the same count.
 * * **Stated against computed.** They are two facts about one column and get two
 *   captions and two boxes. Merging them, or showing only the delta, loses which
 *   number the workbook actually prints.
 */

/**
 * SPEC §2 · the three audit scopes, deliberately unequal in emphasis.
 *
 * `packet` is the only one the audit letter asks about and is coloured as the
 * finding it is. `unscoped` is not a residue or an error: the cost-basis column
 * is stated once for the whole workbook and belongs to no measurement date.
 */
const SCOPE: Record<FindingScope, Term & { tone: string }> = {
  packet: {
    label: "packet scope",
    tone: "unsupported",
    meaning:
      "One of the six measurement dates the auditor's packet closes at. These are the disagreements the audit letter asks about.",
  },
  lineage_only: {
    label: "lineage only",
    tone: "validated",
    meaning:
      "One of the other six tracker periods, kept for history. It is not one of the three audited measurement dates, so it never counts toward packet completeness and must not be read as a finding about a measurement date.",
  },
  unscoped: {
    label: "no measurement date",
    tone: "support",
    meaning:
      "Stated once for the whole workbook rather than for a period — the fund-wide cost-basis column. Filing it under a date would assert something the workbook does not say.",
  },
};

/**
 * One of a finding's two figures, or the statement that it has none.
 *
 * No currency, because the workbook cells state none and inventing USD here
 * would be inventing a fact. The digits are grouped by `formatAmount`, which is
 * value-preserving: nothing is rounded, padded or reordered on the way to the
 * screen.
 */
function AmountBox({
  caption,
  amount,
  tone,
}: {
  caption: string;
  amount: string | null;
  tone: string;
}) {
  return (
    <div className={`figure figure--${tone}`}>
      <span className="figure__caption">{caption}</span>
      <span className="figure__amount">
        {amount === null ? (
          <span className="absent" title="This finding states no figure for this side.">
            none stated
          </span>
        ) : (
          formatAmount(amount)
        )}
      </span>
    </div>
  );
}

/**
 * One disagreement.
 *
 * `kind` is rendered verbatim as the code it is. The reconciler writes one
 * sentence per finding — `detail` — and that sentence, not a gloss invented in
 * the display layer, is what says which figures are being compared and why they
 * differ.
 */
function FindingItem({ finding }: { finding: Finding }) {
  return (
    <li className="gap">
      <div className="gap__head">
        <strong>{finding.subject}</strong>
        <code className="gap-kind">{finding.kind}</code>
        <span className="tag" title={SCOPE[finding.scope].meaning}>
          {SCOPE[finding.scope].label}
        </span>
      </div>
      <div className="triptych">
        <AmountBox caption="stated in the workbook" amount={finding.stated} tone="reported" />
        <AmountBox
          caption="computed from the workbook's own figures"
          amount={finding.computed}
          tone="validated"
        />
        <AmountBox
          caption="delta · computed − stated"
          amount={finding.delta_computed_minus_stated}
          tone="unsupported"
        />
      </div>
      <p className="note">{finding.detail}</p>
    </li>
  );
}

/**
 * One scope's findings, with its own count and its own kind breakdown.
 *
 * An empty bucket still renders, with its zero stated. A section that vanishes
 * when it holds nothing is indistinguishable from a section nobody built, and
 * on a reconciliation report the absence of a heading reads as agreement.
 */
function Bucket({ bucket }: { bucket: ScopeBucket }) {
  const scope = SCOPE[bucket.scope];
  return (
    <Section title={`Findings · ${scope.label}`} note={scope.meaning}>
      <p className="note">
        <strong>{bucket.finding_count}</strong> findings in this scope.
      </p>
      {bucket.by_kind.length > 0 && (
        <p className="codes">
          <span className="codes__label">by kind</span>
          {bucket.by_kind.map((entry) => (
            <code key={entry.kind}>
              {entry.kind} · {entry.count}
            </code>
          ))}
        </p>
      )}
      {bucket.findings.length === 0 ? (
        <p className="note">
          The reconciler found nothing in this scope. That is a result, not an empty screen.
        </p>
      ) : (
        <ul className="gap-list">
          {bucket.findings.map((finding) => (
            <FindingItem key={`${finding.kind}/${finding.subject}`} finding={finding} />
          ))}
        </ul>
      )}
    </Section>
  );
}

export function Reconciliation({ report }: { report: ReconciliationResponse }) {
  return (
    <>
      <Section
        title="Reconciliation — where the two workbooks disagree"
        note="Deterministic matching between the valuation tracker and the master investment breakdown. Neither workbook silently overwrites the other, and an unresolved disagreement is reported rather than blocking the packet."
      >
        <p className="note">
          <span
            className="source"
            title="Read from the committed output of the reconciler run against the fund's two workbooks. The workbooks themselves are private and are not republished."
          >
            source · committed tracker snapshot
          </span>
        </p>
        <div className="triptych">
          {report.scopes.map((bucket) => (
            <div key={bucket.scope} className={`figure figure--${SCOPE[bucket.scope].tone}`}>
              <span className="figure__caption">{SCOPE[bucket.scope].label}</span>
              <span className="figure__amount">{bucket.finding_count}</span>
              <span className="sub">{SCOPE[bucket.scope].meaning}</span>
            </div>
          ))}
        </div>
        <p className="note">
          These three counts are <em>not</em> interchangeable and are never added into one headline.
          A finding about a lineage-only period is not a finding about a measurement date the
          auditor asked about, and a report that showed one number could not tell you which kind you
          were reading.
        </p>
        <Meta
          items={[
            { label: "snapshot", value: <code>{report.snapshot}</code> },
            { label: "positions read", value: <strong>{report.positions}</strong> },
            { label: "tranches read", value: <strong>{report.tranches}</strong> },
            { label: "fund-periods read", value: <strong>{report.fund_periods}</strong> },
            {
              label: "findings in total",
              value: <strong>{report.finding_count}</strong>,
              hint: "Every finding the reconciler produced, across all twelve tracker fund-periods. Not a packet figure.",
            },
          ]}
        />
      </Section>

      {report.scopes.map((bucket) => (
        <Bucket key={bucket.scope} bucket={bucket} />
      ))}
    </>
  );
}
