#!/usr/bin/env python3
"""Delete each guard in turn. The suite must go red.

A test suite that stays green while the thing it names is removed is not
coverage — it reads as coverage and provides none. This project has shipped that
five times: `check_tranche_arithmetic` and `check_stated_cost_total` could be
dropped from `reconcile()` entirely, the ambiguity branch could be disabled, and
the test named for the period-column binding asserted something else.

Each entry below names one guard and the smallest edit that removes it. The run
applies the edit, runs the tests, restores the file, and reports. Three outcomes:

    RED         the guard is defended — a test noticed
    STILL GREEN nothing defends it; write a test before shipping
    NO-OP       the edit did not apply, so this mutation tested nothing

NO-OP is a failure, not a skip. A mutation whose anchor has drifted silently
stops checking anything, which is the same shape as the defect this file exists
to catch.

    python scripts/mutate.py              # workbooks as they are
    python scripts/mutate.py --ci         # workbooks hidden, as CI sees it
    python scripts/mutate.py -k fund      # only mutations matching a substring

The workbooks are the fund's private case-study material and are gitignored, so
`--ci` reproduces the condition every guard actually has to hold under.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FINDINGS = ROOT / "ingest/trackers/findings.py"
MARKS = ROOT / "ingest/trackers/marks.py"
#: The fact layer, split out of marks.py at the file-size budget. A split is
#: exactly when a mutation anchor goes stale, and a stale anchor is a NO-OP
#: that silently tests nothing — which is the defect this file exists to find.
FACTS = ROOT / "ingest/trackers/mark_facts.py"
RECONCILE = ROOT / "ingest/trackers/reconcile.py"
READ = ROOT / "ingest/trackers/read.py"
MAPPER = ROOT / "ingest/trackers/to_contracts.py"
MODELS = ROOT / "packages/contracts/models.py"
#: Step 2's document pipeline. The citation guards land here with the first
#: extractor that writes one, so they are mutated from the day they exist rather
#: than being added to this list later — which is when a guard quietly becomes
#: prose.
PARSE = ROOT / "ingest/documents/parse.py"
CITATIONS = ROOT / "packages/contracts/citations.py"
CLAIMS = ROOT / "ingest/documents/claims.py"
SUITES = [
    "tests/test_tracker_marks.py",
    "tests/test_tracker_mark_sentences.py",
    "tests/test_tracker_ingest.py",
    # The mapper and the contract it maps into. Both were outside this file
    # entirely while three defects lived in them — held-at-date read off the
    # lots that survived rather than the rows the source states, a full exit
    # that left every lot reading as held, and a master-side key collision that
    # attached one company's cost to another's holding. A harness that reports
    # "every guard goes red" while never touching the layer that assembles the
    # packet is the same false green it exists to catch.
    "tests/test_real_data_end_to_end.py",
    "tests/test_contracts.py",
    # The document pipeline. `test_document_store.py` is database-gated but NOT
    # corpus-gated, so every write-path guard is still defended under `--ci`
    # where the documents are hidden. `test_document_end_to_end.py` skips there,
    # which is exactly why it is not the only thing defending them.
    "tests/test_document_parse.py",
    "tests/test_citations.py",
    "tests/test_document_store.py",
    "tests/test_document_end_to_end.py",
]
CASE_STUDY = ROOT / "7GC Audit Case Study"

#: What this harness does NOT cover, stated because an unstated boundary reads
#: as full coverage — which is the defect this file exists to find, one level up.
#: The database guards in `supabase/migrations/` are mutation-tested by hand
#: against a live schema (drop the object, run the schema suites, restore); the
#: results are recorded in `.captain/review/triage/`. The oracle is checked by
#: `evals/oracle/anchors.py`, which is a different instrument again.
UNCOVERED = "supabase/migrations (mutated by hand — see .captain/review/triage/), evals/oracle"


@dataclass(frozen=True)
class Mutation:
    """One guard, and the edit that removes it."""

    name: str
    path: Path
    before: str
    after: str = ""


MUTATIONS: list[Mutation] = [
    # ── the two key normalisations ───────────────────────────────────────
    Mutation(
        "fund key: match by prefix again",
        FINDINGS,
        "    match = _FUND_LABEL.match(text)",
        '    match = None\n    for _n in ("Fund II", "Fund I"):\n'
        "        if text.startswith(_n):\n            return _n",
    ),
    Mutation(
        "fund key: guess the first of several funds",
        FINDINGS,
        "    if _MULTI_FUND.search(text):\n        return text\n",
    ),
    Mutation(
        "period end: accept any quarter digit",
        FINDINGS,
        'text[3] in "1234"',
        "text[3].isdigit()",
    ),
    Mutation(
        # Anchored on the line above, because a bare `    return None` also
        # occurs inside `Finding.difference` with deeper indentation and the
        # first match won there — a mutation that silently tested the wrong
        # function and reported the guard undefended.
        "period end: an unreadable label becomes a real date",
        FINDINGS,
        "- timedelta(days=1)\n    return None",
        "- timedelta(days=1)\n    return date(2000, 1, 1)",
    ),
    # ── materiality ──────────────────────────────────────────────────────
    Mutation(
        "materiality: relative only, no absolute floor",
        FINDINGS,
        "threshold = min(abs(reference) * _MATERIALITY_RELATIVE, _MATERIALITY_ABSOLUTE)",
        "threshold = abs(reference) * _MATERIALITY_RELATIVE",
    ),
    Mutation(
        "materiality: absolute only, no relative test",
        FINDINGS,
        "threshold = min(abs(reference) * _MATERIALITY_RELATIVE, _MATERIALITY_ABSOLUTE)",
        "threshold = _MATERIALITY_ABSOLUTE",
    ),
    # ── the fund-keyed joins ─────────────────────────────────────────────
    Mutation(
        "positions: drop the fund from the key",
        FACTS,
        "out.setdefault((_fund_of(t.fund), company_key(t.company)), []).append(t)",
        "out.setdefault((None, company_key(t.company)), []).append(t)",
    ),
    Mutation(
        "sheet lookup: match every sheet regardless of fund",
        FACTS,
        "return [s for s in sheets if _fund_of(s.fund_label) == fund]",
        "return list(sheets)",
    ),
    # ── the fact layer ───────────────────────────────────────────────────
    Mutation(
        "cost: sum the priced lots only",
        FACTS,
        "cost=sum((t.investment for t in held), Decimal(0)),",
        "cost=sum((t.investment for t in priced_held), Decimal(0)),",
    ),
    Mutation(
        "implied: drop the unpriced lots from the figure",
        FACTS,
        "(t, shares * (t.share_price or Decimal(0)) + unpriced_cost) for t in candidates",
        "(t, shares * (t.share_price or Decimal(0))) for t in candidates",
    ),
    Mutation(
        "repriced: a synthesised figure buys silence again",
        FACTS,
        "repriced=len({t.share_price for t in priced_held}) > 1,",
        "repriced=False,",
    ),
    Mutation(
        "facts: skip a position whose lots are all unpriced",
        FACTS,
        "    if not held:\n        return None",
        "    if not held or not [t for t in held if _is_priced(t)]:\n        return None",
    ),
    Mutation(
        # Round 6 asked for exactly this: the undated-exit distinction was
        # covered by a test and by no mutation, so nothing proved the test
        # could fail.
        "realised: only a definitely-past exit blocks",
        FACTS,
        "realised = [t for t in lots if t.is_exit and t.held_by(on) is not False]",
        "realised = [t for t in lots if t.is_exit and t.held_by(on) is True]",
    ),
    Mutation(
        "held_at: treat an undecidable date as held",
        FACTS,
        "undecidable = [t for t in lots if t.held_by(on) is None]",
        "undecidable = []",
    ),
    Mutation(
        "latest candidates: let an undated lot be ordered anyway",
        FACTS,
        "return ra is not None and rb is not None and ra[0] > rb[1]",
        "return ra is None or rb is None or ra[0] > rb[1]",
    ),
    # ── the mark checks' decision rules ──────────────────────────────────
    Mutation(
        "ambiguity: report whenever candidates tie, ignoring price",
        MARKS,
        "if len(candidates) < 2 or len({t.share_price for t in candidates}) < 2:",
        "if len(candidates) < 2:",
    ),
    Mutation(
        "at-cost: report under one ordering instead of all",
        MARKS,
        "            if not all(_is_material(gap, value) for _t, value, gap in gaps):",
        "            if not any(_is_material(gap, value) for _t, value, gap in gaps):",
    ),
    Mutation(
        "at-cost: remove the empty-candidate guard (crash)",
        MARKS,
        "            if not gaps:\n                continue\n",
    ),
    Mutation(
        "at-cost: require exact equality with cost",
        MARKS,
        "            if _is_material(amount - facts.cost, facts.cost):\n                continue",
        "            if amount != facts.cost:\n                continue",
    ),
    Mutation(
        "basis: drop the at-cost materiality gate",
        MARKS,
        "            if not _is_material(amount - facts.cost, facts.cost):\n"
        "                continue",
        "            if amount == facts.cost:\n                continue",
    ),
    Mutation(
        "basis: let repriced override the ordering rule too",
        MARKS,
        "if gaps and len(gaps) == 1 and facts.repriced:",
        "if gaps and facts.repriced:",
    ),
    Mutation(
        "basis: restore the two-lot scope gate",
        MARKS,
        "        # Deliberately NOT gated on `_has_comparable_purchases`.",
        "        if not _has_comparable_purchases(lots):\n            continue\n        #",
    ),
    # ── every check, unwired from the one pass ───────────────────────────
    *[
        Mutation(f"unwire {name}", MARKS, f"    {name},\n")
        for name in (
            "check_marks_reach_a_position",
            "check_latest_purchase_is_decidable",
            "check_realisations_are_allocatable",
            "check_holding_dates_are_decidable",
            "check_period_labels_are_readable",
            "check_marks_held_at_cost",
            "check_mark_basis_is_in_the_workbooks",
        )
    ],
    *[
        Mutation(f"unwire {name}", RECONCILE, f"    findings += {name}({args})\n")
        for name, args in (
            ("check_recognised_kinds", "tranches"),
            ("check_tranche_arithmetic", "tranches"),
            ("check_cost_basis_across_workbooks", "sheets, tranches"),
        )
    ],
    *[
        Mutation(f"unwire {name}", RECONCILE, f"        findings += {name}(sheet)\n")
        for name in ("check_stated_totals", "check_stated_cost_total")
    ],
    # ── the reader ───────────────────────────────────────────────────────
    Mutation(
        "reader: infer the period columns from an offset",
        READ,
        "period_at = {str(c): i for i, c in enumerate(header) if c and i >= 3}",
        "_ps = [str(c) for c in header if c][1:]\n"
        "        period_at = {p: len(header) - len(_ps) + n for n, p in enumerate(_ps)}",
    ),
    Mutation(
        "reader: collapse a month range to its first day",
        READ,
        "last = date(m.year + m.month // 12, m.month % 12 + 1, 1) - timedelta(days=1)",
        "last = m",
    ),
    Mutation(
        "reader: an exit row counts as an investment",
        READ,
        'return self.kind.strip().lower().startswith("fund")',
        "return not self.is_exit or True",
    ),
    Mutation(
        "reader: numbers stored as text are dropped",
        READ,
        "            return Decimal(cleaned)",
        "            return None",
    ),
    # ── held-at-date, read from the source rows ──────────────────────────
    Mutation(
        "held at date: a full exit no longer ends the holding",
        READ,
        "    return total_sold < total_bought",
        "    return True",
    ),
    Mutation(
        "held at date: an unplaceable sale is treated as no sale",
        READ,
        "    if any(t.held_by(on) is None for t in exits):\n        return None\n",
    ),
    Mutation(
        "held at date: a sale of unstated size is treated as leaving shares",
        READ,
        "        return None\n    total_sold = sum(",
        "        return True\n    total_sold = sum(",
    ),
    Mutation(
        "held at date: an undecidable acquisition becomes a definite no",
        READ,
        "        return None if any(t.held_by(on) is None for t in inflow) else False",
        "        return False",
    ),
    # ── the mapper ───────────────────────────────────────────────────────
    Mutation(
        "mapper: held-at-date read off the surviving lots again",
        MAPPER,
        "            held_at_date=position_held_at(own, period.period_date) is not False,",
        "            held_at_date=any(lot.held_at(period.period_date) for lot in out.lots"
        "\n                            if lot.holding_id == holding.id) or not out.lots,",
    ),
    Mutation(
        "mapper: a full exit across several lots is refused again",
        MAPPER,
        "    if len(exits) == 1 and sold >= held and held > 0 and when is not None:",
        "    if len(exits) == 1 and len(purchases) == 1 and sold == held and when is not None:",
    ),
    Mutation(
        "mapper: master-side key collisions merge silently again",
        MAPPER,
        "        if len({t.source_sheet for t in rows_for if t.source_sheet}) > 1",
        "        if False",
    ),
    Mutation(
        "mapper: the tracker-side key collision guard, removed",
        MAPPER,
        "            if len({c for c in sheet.companies if company_key(c) == key}) > 1",
        "            if False",
    ),
    # ── the contract the packet is published through ─────────────────────
    Mutation(
        "totals: sum every row, held at the date or not",
        MODELS,
        "            if not row.held_at_date:\n                continue\n",
    ),
    Mutation(
        "totals: call a held-at-date subtotal the tracker's own total",
        MODELS,
        "            kind=TotalKind.HELD_AT_DATE_REPORTED,",
        "            kind=TotalKind.TRACKER_REPORTED,",
    ),
    Mutation(
        "totals: count unheld rows as unsupported INPUTS",
        MODELS,
        "            unsupported_positions=sum(1 for r in self.rows"
        " if r.held_at_date and not r.supported),",
        "            unsupported_positions=sum(1 for r in self.rows if not r.supported),",
    ),
    # ── the parse layer: what a citation resolves against ────────────────
    Mutation(
        "pages: count the trailing form feed as an extra page",
        PARSE,
        "    if start < len(canonical_text):",
        "    if start <= len(canonical_text):",
    ),
    Mutation(
        "pages: attribute an out-of-range offset to the last page",
        PARSE,
        '        raise ValueError(\n            f"offset {offset} lies outside every page',
        "        return self.pages[-1].number\n        raise ValueError(\n"
        '            f"offset {offset} lies outside every page',
    ),
    Mutation(
        "text hash: drop the separator between extractor and text",
        PARSE,
        '    digest.update(b"\\x00")\n',
    ),
    Mutation(
        "text hash: identify the text without the extractor that produced it",
        PARSE,
        '    digest.update(extractor.encode("utf-8"))\n',
    ),
    Mutation(
        "plain text: normalise newlines after extraction",
        PARSE,
        '    return raw.decode("utf-8"), "utf8-verbatim@1"',
        '    return raw.decode("utf-8").replace("\\r\\n", "\\n"), "utf8-verbatim@1"',
    ),
    Mutation(
        "parse: accept an empty extraction",
        PARSE,
        "    if not canonical_text.strip():",
        "    if False:",
    ),
    # ── citations: the span is computed, and it binds ────────────────────
    Mutation(
        "locate: resolve an ambiguous quote to its first match",
        CITATIONS,
        "        if len(starts) > 1:",
        "        if False:",
    ),
    Mutation(
        "locate: search for the quote as a pattern, not a literal",
        CITATIONS,
        "re.escape(quote)",
        "quote",
    ),
    Mutation(
        "locate_pattern: take the first of several matching passages",
        CITATIONS,
        "    if len(matches) > 1:",
        "    if False:",
    ),
    Mutation(
        "resolves_in: trust the slice and skip the length check",
        CITATIONS,
        "    if citation.span_end > len(canonical_text):\n        return False\n",
    ),
    Mutation(
        "cited_numeral: read a figure out of any text at all",
        CITATIONS,
        "    if _FIGURE.fullmatch(value_text) is None:\n        return None\n",
    ),
    Mutation(
        "cited_numeral: use Unicode whitespace, diverging from Postgres",
        CITATIONS,
        r'_WS = r"[ \t\n\r\f\v]"',
        r'_WS = r"\s"',
    ),
    Mutation(
        "supports_value: accept a quote that does not contain the figure",
        CITATIONS,
        "    return value_token_occurrences(quote, value_text) == 1",
        "    return bool(value_text)",
    ),
    Mutation(
        # The defect a cross-family review found by executing it: `625` cited to
        # a row stating `625,000` satisfied all three bindings and stored.
        "supports_value: containment again, not a whole figure",
        CITATIONS,
        "    return value_token_occurrences(quote, value_text) == 1",
        "    return bool(value_text) and value_text in quote",
    ),
    Mutation(
        # The anchor this replaces went stale when the boundary rule grew sign
        # and exponent cases — and a stale anchor tests nothing while reporting
        # nothing, which is the defect this whole file exists to find.
        "token count: nothing continues a figure any more",
        CITATIONS,
        "        if not continues:",
        "        if True:",
    ),
    Mutation(
        "token count: a leading minus is no longer a sign ('-8.00' -> +8.00)",
        CITATIONS,
        '            or before == "-"\n',
    ),
    Mutation(
        "token count: an exponent no longer continues the figure ('8e3' -> 8)",
        CITATIONS,
        '            or (after in ("e", "E") and (beyond.isdigit() or beyond in ("+", "-")))\n',
    ),
    Mutation(
        # Two independent cross-family reviews found this on the same day, from
        # opposite ends: a claim reading 800 beside a citation reading $8.00.
        "store_claim: a claim price need not be a figure any fact cites",
        CLAIMS,
        "    if draft.price_per_share is not None and draft.price_per_share not in cited:",
        "    if False:",
    ),
    Mutation(
        "figure grammar: any run of digits and commas again ('8,00' -> 800)",
        CITATIONS,
        r'_INT = r"(?:0|[1-9][0-9]{0,2}(?:,[0-9]{3})+|[1-9][0-9]*)"',
        r'_INT = r"[0-9][0-9,]*"',
    ),
    Mutation(
        "store_claim: stop checking that the passage states the figure",
        CLAIMS,
        "        if not supports_value(fact.citation.quote, fact.value_text):",
        "        if False:",
    ),
    Mutation(
        "store_claim: stop checking the number against its text",
        CLAIMS,
        "        if cited_numeral(fact.value_text) != fact.value_numeric:",
        "        if False:",
    ),
    # ── the write path ───────────────────────────────────────────────────
    Mutation(
        "cited_fact: store a value captured outside its own citation",
        CLAIMS,
        "    if not supports_value(citation.quote, value_text):",
        "    if False:",
    ),
    Mutation(
        "store_document: treat any existing row as a successful re-ingest",
        CLAIMS,
        "    if (stored_text, stored_extractor, stored_pages) != (",
        "    if False and (stored_text, stored_extractor, stored_pages) != (",
    ),
    Mutation(
        "store_claim: insert without re-resolving the citations",
        CLAIMS,
        "        verify(fact.citation, canonical_text)\n",
    ),
    Mutation(
        "store_claim: store a fact cited into a different document version",
        CLAIMS,
        "        if fact.citation.document_version_id != version_id:",
        "        if False:",
    ),
]


def run_suite(python: str) -> bool:
    """True when the suite passes."""
    proc = subprocess.run(
        [python, "-m", "pytest", *SUITES, "-q", "-x", "--no-header"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ci", action="store_true", help="hide the workbooks, as CI sees them")
    ap.add_argument("-k", metavar="SUBSTRING", help="only mutations whose name contains this")
    args = ap.parse_args()

    python = str(ROOT / ".venv/bin/python")
    if not Path(python).exists():
        print("✗ .venv/bin/python not found — a bare interpreter can pass vacuously")
        return 1

    selected = [m for m in MUTATIONS if not args.k or args.k in m.name]
    if not selected:
        print(f"no mutation matches {args.k!r}")
        return 1

    hidden = None
    if args.ci and CASE_STUDY.exists():
        hidden = Path(tempfile.mkdtemp()) / "case-study"
        shutil.move(str(CASE_STUDY), str(hidden))

    originals = {p: p.read_text() for p in {m.path for m in selected}}
    where = "workbooks hidden (CI)" if args.ci else "workbooks present"
    print(f"mutation run · {len(selected)} guards · {where}\n")

    red, green, noop = [], [], []
    try:
        if run_suite(python):
            pass
        else:
            print("✗ the suite is already red before any mutation — fix that first")
            return 1

        for m in selected:
            source = originals[m.path]
            if m.before not in source:
                noop.append(m.name)
                print(f"  !! NO-OP        {m.name}")
                continue
            m.path.write_text(source.replace(m.before, m.after, 1))
            try:
                if run_suite(python):
                    green.append(m.name)
                    print(f"  XX STILL GREEN  {m.name}")
                else:
                    red.append(m.name)
                    print(f"  ok RED          {m.name}")
            finally:
                m.path.write_text(source)
    finally:
        for path, text in originals.items():
            path.write_text(text)
        if hidden is not None:
            shutil.move(str(hidden), str(CASE_STUDY))

    print(f"\n  red {len(red)}   still green {len(green)}   no-op {len(noop)}")
    if green:
        print("\n✗ undefended — nothing fails when these are removed:")
        for n in green:
            print(f"    {n}")
    if noop:
        print("\n✗ stale anchors — these mutations tested nothing:")
        for n in noop:
            print(f"    {n}")
    if green or noop:
        return 1
    print(f"\n✓ all {len(red)} guards below go red when removed.")
    print(f"  Not covered here: {UNCOVERED}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
