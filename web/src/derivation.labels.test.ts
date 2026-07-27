import { describe, expect, it } from "vitest";

import { derivationGloss, outcomeGloss, RECOMPUTATION_OUTCOME } from "./derivation.labels";

/**
 * The words the recomputation is read in, which until now nothing checked.
 *
 * This module had no test file. `Recomputation.test.tsx` reaches
 * `derivationGloss` twice and both times through a reason that is a plain key in
 * the map, so the one branch that carries a SUBJECT could be deleted whole and
 * the suite stayed green: `NO_PRICE_FOR_CLASS:series_a1` names the class the
 * fund holds and no document prices, and that class name is the entire content
 * of the finding. Without it Dream's refusal and Fluidstack's are the same
 * sentence on screen, and the two are about different classes of different
 * companies.
 *
 * The other property asserted here is what the module's own docstring claims and
 * nothing enforced: a reason names the DERIVATION and never the verdict. A gloss
 * that said "matched" or "failed" would let a reader take pass/fail out of a
 * string that is stated identically in both cases.
 */

/** SPEC §8's six, transcribed rather than read back out of the map under test. */
const OUTCOMES = [
  "blocked_incomplete",
  "fail",
  "not_applicable",
  "not_comparable",
  "pass",
  "unconfirmable",
];

/** Every reason `derivationGloss` claims to know, minus the one that carries a class. */
const REASONS = [
  "PER_CLASS_SHARES_X_PPS",
  "SHARES_X_ENTRY_PPS",
  "THIRD_PARTY_CONCLUSION",
  "ADMINISTRATOR_NAV",
  "MANAGEMENT_CARRYING_VALUE",
  "NO_APPLICABLE_EVIDENCE",
  "NO_PRICE_IN_EVIDENCE",
  "COMPONENT_WITHOUT_SHARE_COUNT",
  "NO_VALUE_FIELD_CITED",
  "NO_STATED_FIGURE_TO_COMPARE",
  "NOT_HELD_AT_MEASUREMENT_DATE",
];

const NO_GLOSS = "no gloss is recorded for this derivation";

describe("outcomeGloss", () => {
  it("carries a label, a glyph and a sentence for each of SPEC §8's six outcomes", () => {
    expect(Object.keys(RECOMPUTATION_OUTCOME).sort()).toEqual(OUTCOMES);
    for (const code of OUTCOMES) {
      const gloss = outcomeGloss(code);
      expect(gloss).toBe(RECOMPUTATION_OUTCOME[code]);
      expect(gloss.label).not.toBe("");
      expect(gloss.glyph).not.toBe("");
      expect(gloss.meaning).not.toBe("");
    }
  });

  /**
   * Six outcomes rendering as fewer than six distinct labels or glyphs would put
   * two different findings on screen as the same one, which is the failure the
   * vocabulary exists to prevent — and a reader scanning a column of rows is
   * reading the glyph, not the sentence behind it.
   */
  it("says something different for every one of them", () => {
    const glosses = OUTCOMES.map((code) => outcomeGloss(code));
    expect(new Set(glosses.map((g) => g.label)).size).toBe(OUTCOMES.length);
    expect(new Set(glosses.map((g) => g.glyph)).size).toBe(OUTCOMES.length);
  });

  /**
   * The two kinds of cannot-run are opposite findings that send different
   * letters. `unconfirmable` means the evidence does not say and the next step
   * is to ask the company; `blocked_incomplete` means the evidence says it and
   * this ledger has no field for its shape, so the next step is to load the
   * figure. Collapsing them would send a request for a document to a company
   * that already provided it.
   */
  it("keeps the two kinds of cannot-run apart, because they send different letters", () => {
    expect(outcomeGloss("unconfirmable").meaning).toMatch(/request evidence from the company/);
    expect(outcomeGloss("blocked_incomplete").meaning).toMatch(/load the figure/);
    expect(outcomeGloss("unconfirmable").label).not.toBe(outcomeGloss("blocked_incomplete").label);
  });

  /**
   * Moonfare FY2024. A real cited figure the fund wrote about its own position:
   * `pass` is what that circularity produces if nothing stops it, so the word on
   * screen must not be a confirmation.
   */
  it("never reads a circular figure as agreement", () => {
    const gloss = outcomeGloss("not_comparable");
    expect(gloss.label).toMatch(/the fund is the author of both/);
    expect(gloss.label).not.toMatch(/\bagrees?\b/i);
    expect(gloss.meaning).toMatch(/circular/);
  });

  /**
   * The policy owns this vocabulary and adds to it, so an outcome with no gloss
   * is a state this map will really meet. It renders as a stated absence rather
   * than as a blank, which on this screen would read as nothing to report.
   */
  it("states that it has no gloss rather than inventing a reassuring one", () => {
    const gloss = outcomeGloss("invented");
    expect(gloss.label).toBe("no gloss is recorded for this outcome");
    expect(gloss.glyph).toBe("·");
    expect(gloss.meaning).toMatch(/this display carries no gloss/);
  });
});

describe("derivationGloss", () => {
  /**
   * The branch this whole file exists for. `NO_PRICE_FOR_CLASS:series_a1` is not
   * a code with a fixed sentence behind it — it names the class, and the class
   * is the finding. A gloss that dropped it would report Dream's refusal and
   * Fluidstack's as the same fact, so the two are asserted to differ rather than
   * each being asserted against a fixed string a shared constant could satisfy.
   */
  it("names the class the fund holds and cannot price", () => {
    const a1 = derivationGloss("NO_PRICE_FOR_CLASS:series_a1");
    expect(a1).toMatch(/series_a1/);
    expect(a1).toBe("the fund holds series_a1 and no document on file prices that class");
    const a2 = derivationGloss("NO_PRICE_FOR_CLASS:series_a2");
    expect(a2).toMatch(/series_a2/);
    expect(a2).not.toBe(a1);
    expect(a1).not.toBe(NO_GLOSS);
    expect(a2).not.toBe(NO_GLOSS);
  });

  /**
   * `policy/validators.py` joins every uncovered class into one reason, so the
   * subject can be a list. Carrying only the first would understate the finding
   * on exactly the holdings where it is largest.
   */
  it("carries every class through when the evidence prices none of several", () => {
    const gloss = derivationGloss("NO_PRICE_FOR_CLASS:series_a,series_a2");
    expect(gloss).toMatch(/series_a,series_a2/);
  });

  /**
   * The prefix is the code AND its colon. A bare `NO_PRICE_FOR_CLASS` names no
   * class, so it is not the class-carrying reason and must not render as one
   * holding a class called nothing.
   */
  it("does not read a code with no class after it as naming a class", () => {
    expect(derivationGloss("NO_PRICE_FOR_CLASS")).toBe(NO_GLOSS);
  });

  it("glosses every reason it claims to know", () => {
    for (const reason of REASONS) {
      const gloss = derivationGloss(reason);
      expect(gloss, reason).not.toBe(NO_GLOSS);
      expect(gloss, reason).not.toBe("");
    }
  });

  /**
   * The module's own claim, and the one nothing enforced: the reason names HOW
   * the figure was reached and never whether it agreed. `PER_CLASS_SHARES_X_PPS`
   * is stated identically whether the two figures matched or not, and a gloss
   * carrying a verdict word would let a reader take pass/fail out of a string
   * that says the same thing in both cases.
   */
  it("names the derivation and never the verdict", () => {
    const verdicts = [
      /\bpass(es|ed)?\b/i,
      /\bfail(s|ed|ure)?\b/i,
      /\bagrees?\b/i,
      /\bdisagrees?\b/i,
      /\bmatch(es|ed)?\b/i,
      /\bcorrect\b/i,
      /\bvalidat/i,
      /\bverified\b/i,
    ];
    const glosses = [...REASONS, "NO_PRICE_FOR_CLASS:series_a1"].map((r) => derivationGloss(r));
    for (const gloss of glosses) {
      for (const verdict of verdicts) expect(gloss, gloss).not.toMatch(verdict);
    }
  });

  /**
   * The map is partial by design — the policy owns the vocabulary and adds to
   * it. An unglossed reason says so, because a friendly fallback would turn an
   * unrecognised finding into a reassuring blank.
   */
  it("states that it has no gloss for a reason it does not know", () => {
    expect(derivationGloss("INVENTED_REASON")).toBe(NO_GLOSS);
    expect(derivationGloss("")).toBe(NO_GLOSS);
  });
});
