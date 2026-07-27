import { derivationGloss, outcomeGloss } from "./derivation.labels";
import { formatAmount, formatMoney } from "./format";
import type { Recomputation } from "./responses";
import { Why } from "./ui";

/**
 * The system's own recomputation of a mark, beside the figure that was reported.
 *
 * SPEC §8's validators ran in the test suite and in the oracle and reached no
 * screen: nothing in `api/` imported `v2_mark`, and all 72 `mark` rows carry
 * `validated_amount = null` because the tracker loader writes it as a literal.
 * So the packet reported what the tracker said, and never what the evidence
 * derives — while the two disagree on two rows:
 *
 *     Lucra FY2025        reported 2,250,000    derived 1,500,000
 *     Fluidstack 25Q4     reported 6,000,000    derived 2,500,000
 *
 * Those are the moments the whole product is an argument about. A wrong number
 * in fund valuation is plausible: it renders, it reconciles to itself, and it
 * passes every type check. The only thing that catches it is a second, independent
 * derivation from the cited evidence — and until now nobody could see one.
 *
 * **The label carries as much weight as the number.** "Derived 2,500,000 against
 * a reported 6,000,000" is a finding. "Validated: 2,500,000" is a claim this
 * system has not earned: nothing has approved anything, the figure is computed
 * fresh on every read, and `mark.validated_amount` is deliberately still null.
 * So every string here says "derived", "recomputed" or "the evidence says", and
 * none of them says "validated", "verified" or "correct".
 *
 * **Neither figure is asserted to be the right one.** The difference is the
 * finding; which side is wrong is an auditor's judgement and not this screen's.
 */

/** A one-word answer with its glyph, hue and the sentence behind it. */
export function OutcomeChip({ outcome }: { outcome: string }) {
  const gloss = outcomeGloss(outcome);
  return (
    <span className={`recheck-chip recheck-chip--${outcome}`} title={gloss.meaning}>
      <span aria-hidden="true">{gloss.glyph}</span> {gloss.label}
    </span>
  );
}

/**
 * The compact form, for one row of the dashboard.
 *
 * Leads with the DIFFERENCE where there is one, because a reader scanning eight
 * rows for what is wrong is looking for a number that should not be there. Where
 * there is none, the outcome alone is the answer.
 */
export function RecomputedCell({ recomputation }: { recomputation: Recomputation | undefined }) {
  if (recomputation === undefined) {
    return (
      <span
        className="recheck-none"
        title="No recomputation arrived for this row. That is a missing response, not a finding that the mark could not be checked."
      >
        not supplied by API
      </span>
    );
  }
  return (
    <span className="recheck">
      <OutcomeChip outcome={recomputation.outcome} />
      {recomputation.derived !== null && (
        <span className="recheck__derived">{formatMoney(recomputation.derived)}</span>
      )}
      {recomputation.difference !== null && recomputation.outcome === "fail" && (
        <span className="recheck__delta">off by {formatMoney(recomputation.difference)}</span>
      )}
    </span>
  );
}

const NOT_AN_APPROVAL =
  "Computed fresh from the cited evidence each time this page is read, and stored nowhere. It is not an approved value and it is not `mark.validated_amount`, which is still empty for every row in this fund. SPEC §6.3 binds an approval to a mark revision, an evidence set and a policy version precisely so that an approved total cannot follow a figure that moves.";

const CROSS_CLASS =
  "The price used for this class came from a class the fund does not hold at this date. Pricing one class off another's evidence is a valuation-policy act (INV-17), and this recomputation flags it rather than performing it silently.";

/**
 * The full form, for the company workspace.
 *
 * The per-class working is on screen and not folded away. Fluidstack's finding
 * is only legible as 100,000 Series A at $10.00 plus 100,000 Series A-2 at
 * $15.00 — the reported 6,000,000 is 200,000 shares at the $30.00 Series B
 * price applied to every class, and one total hides which half is wrong.
 */
export function RecomputedMark({ recomputation }: { recomputation: Recomputation | undefined }) {
  if (recomputation === undefined) {
    return (
      <div className="figure figure--recheck">
        <span className="figure__caption">Recomputed from the evidence</span>
        <span className="figure__amount">
          <span className="recheck-none">not supplied by API</span>
        </span>
        <span className="sub">
          The packet carried no recomputation for this holding. A missing response, not a finding.
        </span>
      </div>
    );
  }
  const gloss = outcomeGloss(recomputation.outcome);
  return (
    <div className={`figure figure--recheck figure--recheck-${recomputation.outcome}`}>
      <span className="figure__caption">
        Recomputed from the evidence <Why text={NOT_AN_APPROVAL} />
      </span>
      <span className="figure__amount">
        {recomputation.derived === null ? "no figure" : formatMoney(recomputation.derived)}
      </span>
      <span className="sub" title={gloss.meaning}>
        {gloss.glyph} {gloss.label}
      </span>
      <span className="sub sub--how">{derivationGloss(recomputation.reason)}</span>
      {recomputation.difference !== null && recomputation.outcome === "fail" && (
        <span className="recheck__delta recheck__delta--large">
          {formatMoney(recomputation.difference)} apart from the reported figure
        </span>
      )}
      {recomputation.per_class.length > 0 && (
        <ul className="recheck-working">
          {recomputation.per_class.map((part) => (
            <li key={part.lot_id} className={part.cross_class ? "recheck-working--cross" : ""}>
              <span className="recheck-working__terms">
                {formatAmount(`${part.shares}`)} {part.security_class} at{" "}
                {formatAmount(part.price_per_share)}
              </span>
              <span className="recheck-working__amount">{formatMoney(part.amount)}</span>
              {part.cross_class && (
                <span className="recheck-working__flag" title={CROSS_CLASS}>
                  priced off a class the fund does not hold
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {recomputation.evidence_claim_ids.length > 0 && (
        <p className="recheck__from">
          from{" "}
          {recomputation.evidence_claim_ids.map((id) => (
            <code key={id}>{id}</code>
          ))}
        </p>
      )}
    </div>
  );
}
