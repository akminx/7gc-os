import type { Term } from "./labels";
/**
 * SPEC §8's six outcomes, for the recomputation the API now runs on every mark.
 *
 * Deliberately unordered and deliberately not a boolean. `not_comparable` is
 * not a soft fail and `unconfirmable` is not a weak pass — and the two kinds of
 * cannot-run are opposite findings that send different letters: `unconfirmable`
 * means the EVIDENCE does not say and the auditor requests a document,
 * `blocked_incomplete` means the evidence says it and THIS SYSTEM does not carry
 * the figure, so the action is to load it rather than to chase the client.
 *
 * `not_comparable` is the one worth reading twice. Moonfare's FY2024 carrying
 * value is a real cited figure of 1,048,515 that confirms nothing, because the
 * fund wrote the memo about its own position: comparing it against the mark the
 * fund took FROM it is the circularity, and `pass` is what that circularity
 * produces if nothing stops it. `mark.derivation_status` has no word for this —
 * it is `derivable | not_derivable` — which is why the packet described it as
 * "not derivable · no validated amount could be derived from the evidence"
 * while the evidence had spoken, in the voice under audit.
 */
export const RECOMPUTATION_OUTCOME: Record<string, Term & { glyph: string }> = {
  pass: {
    label: "agrees with the reported figure",
    glyph: "✓",
    meaning:
      "The cited evidence independently reproduces the amount the tracker reported. It says nothing about whether the evidence is sufficient — support is a separate judgement.",
  },
  fail: {
    label: "disagrees with the reported figure",
    glyph: "✕",
    meaning:
      "The cited evidence derives a different amount from the one reported. Neither figure is asserted to be correct here; the difference is the finding.",
  },
  not_applicable: {
    label: "does not arise",
    glyph: "∅",
    meaning: "The position was not held at this measurement date, so there is no mark to check.",
  },
  not_comparable: {
    label: "cannot confirm — the fund is the author of both",
    glyph: "⇄",
    meaning:
      "A real cited figure, read off a document the fund wrote about its own position. Comparing it against the mark taken from it is circular, so it is reported and not treated as a confirmation.",
  },
  unconfirmable: {
    label: "the evidence does not say",
    glyph: "?",
    meaning:
      "Nothing on file states a figure this check could derive. The next step is to request evidence from the company or its counsel.",
  },
  blocked_incomplete: {
    label: "the evidence says it and this system does not carry it",
    glyph: "▲",
    meaning:
      "The document states the figure and this ledger has no field for its shape. The next step is to load the figure, not to write to the client.",
  },
};

export function outcomeGloss(code: string): Term & { glyph: string } {
  return (
    RECOMPUTATION_OUTCOME[code] ?? {
      label: "no gloss is recorded for this outcome",
      glyph: "·",
      meaning: "The policy states this outcome and this display carries no gloss for it.",
    }
  );
}

/**
 * HOW a figure was reached, or the named reason there is none.
 *
 * The reason names the derivation and never the verdict —
 * `PER_CLASS_SHARES_X_PPS` reads the same whether the two figures matched or
 * not, which makes reading pass/fail out of this string impossible. That is
 * deliberate in the policy and is preserved here.
 *
 * Partial by design, like `reasonGloss`: an unglossed reason renders as the
 * API's own word for it and says no gloss is recorded, rather than as a
 * reassuring blank.
 */
const DERIVATION_REASON: Record<string, string> = {
  PER_CLASS_SHARES_X_PPS:
    "shares held of each class, at the price for that same class — never one class's price applied to another",
  SHARES_X_ENTRY_PPS: "shares acquired at the entry price stated in the purchase agreement",
  THIRD_PARTY_CONCLUSION: "an independent valuer's concluded value, taken as concluded",
  ADMINISTRATOR_NAV: "the administrator's stated net asset value",
  MANAGEMENT_CARRYING_VALUE: "the fund's own carrying value, from a document the fund prepared",
  NO_APPLICABLE_EVIDENCE: "no document on file is relied upon for fair value at this date",
  NO_PRICE_IN_EVIDENCE: "the documents on file state no price per share",
  COMPONENT_WITHOUT_SHARE_COUNT:
    "the document states a commitment with no share count, so a per-share identity has an input the ledger has no field for",
  NO_VALUE_FIELD_CITED:
    "the document is of a kind that states a value, and no figure on it is declared as that value",
  NO_STATED_FIGURE_TO_COMPARE: "a figure was derived and the ledger holds no reported mark for it",
  NOT_HELD_AT_MEASUREMENT_DATE: "the position was not held at this date",
};

const NO_PRICE_FOR_CLASS = "NO_PRICE_FOR_CLASS:";

export function derivationGloss(reason: string): string {
  // The one reason that carries its subject. `NO_PRICE_FOR_CLASS:series_a1`
  // names the class the fund holds and has no price for, and that class is the
  // whole content of the finding — a gloss that dropped it would report Dream's
  // and Fluidstack's identical-looking refusals as the same fact.
  if (reason.startsWith(NO_PRICE_FOR_CLASS))
    return `the fund holds ${reason.slice(NO_PRICE_FOR_CLASS.length)} and no document on file prices that class`;
  return DERIVATION_REASON[reason] ?? "no gloss is recorded for this derivation";
}
