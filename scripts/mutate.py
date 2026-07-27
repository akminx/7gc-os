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
LOTS = ROOT / "ingest/trackers/to_lots.py"
CLASSIFY = ROOT / "ingest/trackers/classify.py"
TUPLES = ROOT / "policy/valid_tuples.py"
VALIDATORS = ROOT / "policy/validators.py"
API_EVALS = ROOT / "api/evals.py"
DOC_LOAD = ROOT / "ingest/documents/load.py"
CAP_TABLE = ROOT / "ingest/documents/extract_cap_table.py"
REDUCER = ROOT / "policy/reducer.py"
REQS = ROOT / "policy/requirements.py"
SEED = ROOT / "ingest/policy_seed.py"
MODELS = ROOT / "packages/contracts/models.py"
#: Step 2's document pipeline. The citation guards land here with the first
#: extractor that writes one, so they are mutated from the day they exist rather
#: than being added to this list later — which is when a guard quietly becomes
#: prose.
PARSE = ROOT / "ingest/documents/parse.py"
CITATIONS = ROOT / "packages/contracts/citations.py"
CLAIMS = ROOT / "ingest/documents/claims.py"
#: Hosts for the G7 probes at the end of the list, and the only reason these two
#: files appear in this harness. Each is simply a module inside a directory the
#: answer-key guard claims to scan; nothing about their contents matters.
API_LEDGER = ROOT / "api/ledger.py"
PACKET_MANIFEST = ROOT / "packet/manifest.py"
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
    # The policy layer. Omitting these made every one of its twelve mutations
    # report STILL GREEN on a first run — the guards were defended, by tests
    # this list did not name. That is the harness reporting a false negative
    # about itself, which is one level worse than the defect it hunts: it would
    # have sent someone to write tests that already existed.
    #
    # `test_policy_vs_oracle.py` needs both a DSN and the workbooks and skips
    # without them, so under `--ci` the matrix, the reducer and the injected
    # branches in `test_policy_guards.py` are what hold the line — which is the
    # point of splitting the pure rules from the ledger adapter.
    "tests/test_policy_matrix.py",
    "tests/test_policy_guards.py",
    "tests/test_policy_vs_oracle.py",
]
CASE_STUDY = ROOT / "7GC Audit Case Study"

#: What this harness does NOT cover, stated because an unstated boundary reads
#: as full coverage — which is the defect this file exists to find, one level up.
#: The database guards in `supabase/migrations/` are mutation-tested by hand
#: against a live schema (drop the object, run the schema suites, restore); the
#: results are recorded in `.captain/review/triage/`. The oracle is checked by
#: `evals/oracle/anchors.py`, which is a different instrument again.
NOT_MUTATED_HERE = (
    "supabase/migrations (mutated by hand — see .captain/review/triage/)",
    "evals/oracle (checked by evals/oracle/anchors.py)",
)

#: Directories whose Python can move a figure an auditor reads.
#:
#: COMPUTED, never listed by hand, and that is the whole point. This line used
#: to be a hand-written string, and it went stale exactly the way everything
#: hand-maintained in this repository has: it named two directories while ELEVEN
#: figure-producing modules joined the repo behind it — `policy/validators.py`,
#: `packet/recompute.py`, `api/evals.py` and the rest — and the guard count
#: printed beside it read as full coverage of all of them.
#:
#: A boundary that is derived from the mutation list cannot drift from it. Add a
#: module that can move a figure and it appears in the uncovered list the next
#: time this runs, without anyone remembering to say so.
FIGURE_ROOTS = ("api", "evidence", "ingest", "packages/contracts", "packet", "policy")

#: Modules inside those roots that genuinely need no mutation, each with the
#: reason. Present so an exemption can be argued with rather than assumed; an
#: entry here is a claim, not a silence.
NO_FIGURE = {
    "api/config.py": "reads environment, produces no figure",
    "api/main.py": "app wiring",
    "packages/contracts/enums.py": "vocabulary only",
}


def uncovered_modules() -> list[str]:
    """Figure-producing modules with no mutation in this file."""
    covered = {m.path for m in MUTATIONS}
    out = []
    for root in FIGURE_ROOTS:
        for path in sorted((ROOT / root).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if path.name == "__init__.py" or rel in NO_FIGURE or path in covered:
                continue
            out.append(rel)
    return out


@dataclass(frozen=True)
class Mutation:
    """One guard, and the edit that removes it."""

    name: str
    path: Path
    before: str
    after: str = ""


MUTATIONS: list[Mutation] = [
    # ── whose word a stated figure is (found by a cross-family pass) ─────
    # Both of these were live defects until this round, in a file the harness
    # did not cover at all — `policy/validators.py` was one of 32 modules that
    # can move a reported figure and carried no mutation. They are first in the
    # list because they are the newest and the least defended.
    Mutation(
        "derive_mark: authority gives way to whichever claim is oldest",
        VALIDATORS,
        "    with_amount.sort(key=lambda pair: (rank[pair[0].source_class], pair[0].issued_date))",
    ),
    Mutation(
        "V7: any holding's rate will do, so long as the date matches",
        VALIDATORS,
        " and directed_and_cited(r)",
    ),
    Mutation(
        "V7: the rate's currency pair goes unchecked",
        VALIDATORS,
        '        return claim.fact_text.get("currency_pair") == f"{rate.base}/{rate.quote}"',
        "        return True",
    ),
    # ── the manifest: a citation can be verbatim and still be wrong ──────
    # Both of these were undefended until `tests/test_corpus_manifest.py`
    # landed. Nothing else in the repository compares a citation to an
    # independent reading of where the figure actually sits — every other check
    # proves the offsets and the quote agree WITH EACH OTHER, which a wrong
    # passage satisfies perfectly.
    Mutation(
        "documents: a source file is loaded against the wrong holding",
        DOC_LOAD,
        '            (extract_spa.ROOFSTOCK, "fund_i_roofstock"),',
        '            (extract_spa.ROOFSTOCK, "fund_ii_poolside"),',
    ),
    # The A-2 share count read off the Series A row. Both rows state 100,000 on
    # the real document, so the VALUE agrees and only the position disagrees —
    # `tests/test_extract_cap_table.py` uses a synthetic table whose two rows
    # differ, so it cannot see this at all.
    Mutation(
        "cap table: the A-2 share count is read off the Series A row",
        CAP_TABLE,
        r'        r"7GC Fund II, L\.P\.\s+Series A-2\s+(?P<value>[\d,]+)\s+\$[\d.]+"',
        r'        r"7GC Fund II, L\.P\.\s+Series A(?!-)\s+(?P<value>[\d,]+)\s+\$[\d.]+"',
    ),
    Mutation(
        "R1: a signed agreement answers for settlement of funds too",
        REQS,
        "        if outcome is _SUFFICIENT and (gaps := _acquisition_gaps(covering, lot)):",
        "        if False:",
    ),
    Mutation(
        "R1: settlement anywhere on the holding clears every lot",
        REQS,
        "_acquisition_gaps(covering, lot)",
        "_acquisition_gaps(claims, lot)",
    ),
    Mutation(
        "R1: only settlement is required, not the share terms beside it",
        REQS,
        "applicable = _ACQUISITION_FIGURES if lot.shares",
        "applicable = _ACQUISITION_FIGURES[-1:] or _ACQUISITION_FIGURES if lot.shares",
    ),
    Mutation(
        "R1: a fund interest is asked for a price per share it cannot have",
        REQS,
        "if lot.shares is not None else _ACQUISITION_FIGURES[-1:]",
        "if True else _ACQUISITION_FIGURES[-1:]",
    ),
    Mutation(
        "R4: no figures at all reads as partial rather than insufficient",
        REQS,
        "_INSUFFICIENT if len(absent) == len(_REALIZATION_FIGURES) else _PARTIAL",
        "_PARTIAL",
    ),
    Mutation(
        "R1: a contribution of zero counts as money having moved",
        REQS,
        "        if value is not None and value > 0",
        "        if True",
    ),
    Mutation(
        "R4: figures from any claim on the holding complete a lot",
        REQS,
        "            stated = {name for c in covering for name in c.facts}",
        "            stated = {name for c in claims for name in c.facts}",
    ),
    Mutation(
        "R1: settlement is only what a stock purchase agreement calls it",
        REQS,
        ', "contributed_capital", "acquisition_consideration_usd"',
    ),
    Mutation(
        "R4: a realisation notice answers on its letterhead alone",
        REQS,
        "for missing, needed in _REALIZATION_FIGURES if not (needed & stated)",
        "for missing, needed in _REALIZATION_FIGURES[:0] if not (needed & stated)",
    ),
    # ── what the evaluation page publishes to an auditor ─────────────────
    Mutation(
        "evals: a circular derivation is published as a disagreement of zero",
        API_EVALS,
        "            if got.outcome is Outcome.FAIL and None not in (",
        "            if got.outcome in (Outcome.FAIL, Outcome.NOT_COMPARABLE) and None not in (",
    ),
    Mutation(
        "evals: failing citations are attributed by id shape, not by owner",
        API_EVALS,
        '                "facts_with_a_failing_citation": failing_by_holding.get(holding_id, 0),',
        '                "facts_with_a_failing_citation": sum(\n'
        '                    1 for f in citations["failures"]'
        ' if str(f["claim_id"]).startswith(holding_id)\n                ),',
    ),
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
        'return bool(re.search(r"\\bfund\\b", self.kind, re.I)) and not self.is_exit',
        'return bool(re.search(r"\\bfund\\b", self.kind, re.I)) or True',
    ),
    Mutation(
        # The narrowing that lost Jio: `Indirect Fund` does not START with
        # "fund", so a live $1,000,000 feeder subscription became no lot at
        # all, held-at-date had nothing to ask, and the position's membership
        # in every Fund I total rested on a fallback.
        "reader: only a kind STARTING with 'fund' is an investment again",
        READ,
        'return bool(re.search(r"\\bfund\\b", self.kind, re.I)) and not self.is_exit',
        'return self.kind.strip().lower().startswith("fund")',
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
        LOTS,
        "    if len(exits) == 1 and sold >= held and held > 0 and when is not None:",
        "    if len(exits) == 1 and len(purchases) == 1 and sold == held and when is not None:",
    ),
    Mutation(
        # The invented day only matters where a measurement date falls inside
        # the range. Accepting every range fabricates the day that decides
        # held-at-date (INV-7); refusing every range is what lost Jio's lot.
        "mapper: an imprecise acquisition date is accepted however wide the range",
        LOTS,
        "    straddled = sorted(d for d in measured if start <= d < end)",
        "    straddled = []",
    ),
    Mutation(
        "mapper: the recapitalisation is dropped, so class-at-date never changes",
        LOTS,
        "    recap = classify.recapitalisation(notes)",
        "    recap = None",
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
    Mutation(
        # The defect this restores was real and deployed: `packet_gap_positions`
        # read 6 against the oracle's 5 because R1 and R2 were demanded on a
        # position sold in May. It survived 175 requirement comparisons and 92
        # mutations, because the requirement VERDICTS agreed on both sides and
        # only the contract's derivation from them did not.
        "support: demand existence and cost on a position that was not held",
        MODELS,
        "        if self.held_at_date:\n            for code in sorted(ALWAYS_APPLICABLE):",
        "        if True:\n            for code in sorted(ALWAYS_APPLICABLE):",
    ),
    Mutation(
        # And the over-correction in the other direction: skipping the loop
        # without saying anything makes an unexamined row read as clean.
        "support: an unheld row with nothing assessed is silently supported",
        MODELS,
        "        elif not any(a.applicable for a in self.assessments):\n"
        '            # And an unheld row with NOTHING applicable is not "clean", it is',
        "        elif False:\n"
        '            # And an unheld row with NOTHING applicable is not "clean", it is',
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
    # ── the policy layer (SPEC 7) ────────────────────────────────────────
    Mutation(
        # The mechanism by which the corpus is allowed to grow. A default files
        # a new kind of evidence under whatever the neighbouring cell says.
        "policy: an unenumerated tuple defaults instead of raising",
        TUPLES,
        "    result = MATRIX.get(key)\n    if result is None:",
        "    result = MATRIX.get(key, PolicyResult(verdict=_SUFFICIENT))\n    if result is None:",
    ),
    # ── the audit letter's ¶2, both branches (owner rulings, 2026-07-26) ──
    Mutation(
        # ¶2 branch A says "executed documents OR pro forma capitalization table
        # evidencing price per share". Capping the disjunct at `partial` is
        # stricter than the client asked, and it double-counts a disclosure
        # obligation R5 already carries.
        "policy: a pro forma cap table cannot satisfy branch A on its own",
        TUPLES,
        "    ): PolicyResult(\n        verdict=_SUFFICIENT,\n"
        "        without_price_per_share=PolicyResult(\n"
        "            verdict=_PARTIAL,\n"
        '            reason_code="PRO_FORMA_WITHOUT_PRICE_PER_SHARE",',
        "    ): PolicyResult(\n        verdict=_PARTIAL,\n"
        "        without_price_per_share=PolicyResult(\n"
        "            verdict=_PARTIAL,\n"
        '            reason_code="PRO_FORMA_WITHOUT_PRICE_PER_SHARE",',
    ),
    Mutation(
        # "evidencing price per share" is a condition the letter attaches to the
        # disjunct, so a table stating no price is not what ¶2 accepts. Dropping
        # the qualifier is the cheapest way to collapse this cell to green.
        "policy: the pro-forma qualifier stops being load-bearing",
        REQS,
        "        if cell.without_price_per_share is not None and claim.price_per_share is None:\n"
        "            cell = cell.without_price_per_share\n",
    ),
    # ¶2 branch B is an AND — "the underlying source and management's memo
    # describing the basis of the mark" — and no management memo exists in this
    # corpus. `sufficient` here is the packet claiming more support than the
    # letter allows, which is the only over-reporting defect the review found.
    #
    # One mutation per cell, deliberately. The two cells are byte-identical apart
    # from the position type, and `apply` replaces the FIRST occurrence only, so
    # a single mutation would revert the feeder cell and leave the direct-equity
    # one standing — reporting STILL GREEN for a guard that is in fact defended.
    # The corpus case (Moonfare) is the fx one; the injected case is the other.
    Mutation(
        "policy: a third-party memo alone satisfies branch B — fx interest",
        TUPLES,
        "        PositionType.FX_DENOMINATED_INTEREST,\n    ): PolicyResult(\n"
        "        verdict=_PARTIAL,\n"
        '        reason_code="NO_MANAGEMENT_BASIS_MEMO",\n'
        '        next_actions=("REQUEST_MANAGEMENT_BASIS_MEMO",),\n    ),',
        "        PositionType.FX_DENOMINATED_INTEREST,\n    ): PolicyResult(verdict=_SUFFICIENT),",
    ),
    Mutation(
        "policy: a third-party memo alone satisfies branch B — direct equity",
        TUPLES,
        "        PositionType.DIRECT_EQUITY,\n    ): PolicyResult(\n"
        "        verdict=_PARTIAL,\n"
        '        reason_code="NO_MANAGEMENT_BASIS_MEMO",\n'
        '        next_actions=("REQUEST_MANAGEMENT_BASIS_MEMO",),\n    ),',
        "        PositionType.DIRECT_EQUITY,\n    ): PolicyResult(verdict=_SUFFICIENT),",
    ),
    Mutation(
        # INV-17, and the letter is SILENT on it. Lucra's R2 rose from
        # `insufficient` to `partial` on a CEO email about a class the fund does
        # not hold. The cross-class cap below cannot catch this: it only lowers
        # `sufficient`, so it never observes the raise happening beneath it.
        "policy: off-class evidence raises the verdict again",
        REQS,
        "        if (\n"
        "            claim.priced_class is not None\n"
        "            and claim.priced_class not in held_classes\n"
        "            and not authorized\n"
        "        ):\n"
        "            off_class.append(claim.priced_class)\n"
        "            continue\n",
    ),
    Mutation(
        # The gate is the RECORDED decision. Letting any claim through makes the
        # exclusion decorative.
        "policy: off-class evidence counts without a recorded decision",
        REQS,
        "            and not authorized\n        ):\n"
        "            off_class.append(claim.priced_class)\n",
        "        ):\n            off_class.append(claim.priced_class)\n",
    ),
    Mutation(
        "policy: two partials compose to sufficient",
        REDUCER,
        "    ranked = sorted(verdicts, key=_rank)\n    if not ranked:\n"
        '        raise ReducerError("best() of nothing has no answer;'
        ' decide the empty case at the caller")\n    return ranked[-1]',
        "    ranked = sorted(verdicts, key=_rank)\n"
        "    if ranked.count(RequirementVerdict.PARTIAL) > 1:\n"
        "        return RequirementVerdict.SUFFICIENT\n    return ranked[-1]",
    ),
    Mutation(
        "policy: conflicting stops dominating and reduces on the severity scale",
        REDUCER,
        "    if contradicted:\n        return RequirementVerdict.CONFLICTING",
        "    if contradicted and not verdicts:\n        return RequirementVerdict.CONFLICTING",
    ),
    Mutation(
        "policy: not_applicable is ordered into the row reduction",
        REDUCER,
        "    applicable = [\n        v\n        for v in seen\n"
        "        if v not in (RequirementVerdict.NOT_APPLICABLE, RequirementVerdict.NOT_ASSESSED)\n"
        "    ]",
        "    applicable = [v for v in seen if v is not RequirementVerdict.NOT_ASSESSED]",
    ),
    Mutation(
        # Capsule FY2023: a memo dated 12/31/2022 read at 12/31/2023 is exactly
        # twelve months old and R3 must NOT fire. One character.
        "policy: exactly twelve months counts as stale",
        REQS,
        "        if latest is None or latest < threshold:",
        "        if latest is None or latest <= threshold:",
    ),
    Mutation(
        # r2 had `every`, and Moonfare's fresh FX rate rescued its 33-month-old
        # underlying valuation, so R3 did not fire at all.
        "policy: R3 needs EVERY component stale, not at least one",
        REQS,
        "    if not stale:",
        "    if len(stale) < len(components):",
    ),
    Mutation(
        # Limb (a) said "audit measurement date" through r4, which made R3
        # structurally unable to fire at a fund's first packet date — Roofstock
        # escaped calibration at FY2023, the exact position the letter addresses.
        "policy: R3's predecessor must be a packet date, not any observation",
        REQS,
        "    prior = [(d, amount) for d, amount in ledger.mark_observations(holding_id, fund_id)"
        " if d < on]",
        "    prior = [(d, amount) for d, amount in ledger.mark_observations(holding_id, fund_id)"
        " if d < on and ledger.period_at(fund_id, d) is not None"
        " and ledger.period_at(fund_id, d).audit_scope.value == 'packet']",
    ),
    Mutation(
        # Set EQUALITY. Both one-way tests were wrong on this corpus: asking
        # only "is every held class covered" misses Lucra pricing A-1 shares at
        # the A-2 price; asking only "is the priced class held" misses B shares
        # marked at the C price.
        "policy: cross-class becomes a one-way test again",
        REQS,
        "    cross_class = bool(priced_classes) and held_classes != priced_classes",
        "    cross_class = bool(priced_classes) and not (priced_classes <= held_classes)",
    ),
    Mutation(
        "policy: INV-16's reliance window stops closing",
        REQS,
        "            if claim.applicable_to is not None and claim.applicable_to < on:\n"
        "                continue",
        "            if False:\n                continue",
    ),
    Mutation(
        # Inferring supersession from dates drops Dream's cap table in favour of
        # its closing notice, taking the pro_forma label with it.
        "policy: supersession is inferred from dates rather than recorded",
        REQS,
        "    replaced = {c.supersedes_claim_id for c in claims if c.supersedes_claim_id}",
        "    replaced = {c.id for c in claims"
        " if any(o.priced_class == c.priced_class and o.issued_date > c.issued_date"
        " for o in claims)}",
    ),
    Mutation(
        # Omission used to fail OPEN: a holding with no components returned
        # "all components have support" and R3 silently never fired.
        "policy: a holding with no recorded components reads as nothing stale",
        REQS,
        "    stale = _stale(ledger.components_for(holding_id), on)",
        "    stale = _stale(tuple(x for x in ledger.components if x.holding_id == holding_id), on)",
    ),
    Mutation(
        "policy: R1 stops scoping a gap to the lot it affects",
        REQS,
        "        for gap in ledger.gaps_for(holding_id, RequirementCode.R1, lot.security_class):",
        "        for gap in ledger.gaps_for(holding_id, RequirementCode.R1):",
    ),
    Mutation(
        "seed: a claim relied upon for nothing no longer has to say so",
        SEED,
        "    if stored != declared:",
        "    if stored - declared and False:",
    ),
    Mutation(
        "classify: two position-type signals resolve by order instead of raising",
        CLASSIFY,
        "    if len(hits) > 1:",
        "    if False:",
    ),
    Mutation(
        "classify: two dated lines naming two classes resolve to the first",
        CLASSIFY,
        "        if len(named) > 1:\n            return None",
        "        if len(named) > 1:\n            note, match = named[0]\n"
        "            return Reading(_slug_class(match.group(1)), note.text, note.source_sheet)",
    ),
    # ── G7: the product cannot reach its own answer key ──────────────────
    #
    # These three run the other way round. Every mutation above DELETES a guard
    # and expects the suite to notice the absence; the guard here IS a test, so
    # deleting it leaves a tree that violates nothing and the suite stays green
    # whether the guard works or not. What proves this one is planting the
    # defect it is supposed to catch.
    #
    # The defect is specific. `test_the_product_does_not_import_its_own_answer_
    # key` walked the syntax tree for `Import` and `ImportFrom` nodes, so
    # `Path("evals/oracle/derived.json").read_text()` was a file read rather
    # than an import and passed — while satisfying every fixed-corpus comparison
    # in the suite by reading the answers off disk. A cross-family review found
    # it and it went untriaged for a day.
    #
    # One per directory the guard claims to cover, because "the check reaches
    # policy/, api/ and packet/" is three claims. The scan's directory filter is
    # a glob character class, `[apolicyngest]*`, which is not readable enough to
    # verify by eye — and its previous version excluded nothing at all for the
    # same reason.
    *[
        Mutation(
            f"G7: {label} reads the answer key off disk instead of importing it",
            path,
            "from __future__ import annotations",
            'from __future__ import annotations\n\n_SNAPSHOT = "evals/oracle/derived.json"',
        )
        for label, path in (("policy", REQS), ("api", API_LEDGER), ("packet", PACKET_MANIFEST))
    ],
]


#: Which suites can possibly defend a guard in each file. Running all ten for
#: all ninety-two mutations spent most of its wall clock in pytest collection,
#: re-collecting suites that could not fail whatever the mutation did.
#:
#: Narrowing is safe in one direction only, and it is the loud one: a RED
#: requires a test to actually fail, so no narrowing can invent one. Too narrow
#: a list can only turn a true RED into a STILL GREEN — which reports work to
#: do rather than work already done, and gets investigated. An unmapped file
#: falls back to every suite, so adding a mutation in a new file is slow rather
#: than silently under-checked.
FILE_SUITES: dict[Path, list[str]] = {
    # The four tracker modules share their defenders: `findings.py`'s fund key
    # and materiality decide what `reconcile()` emits, `mark_facts.py` decides
    # what it compares, and the assertions live across all three tracker suites
    # plus the end-to-end one. Narrowing these lost NINE reds on a first run —
    # every one a guard that IS defended, reported as undefended. So they get
    # the whole tracker set, which is also the cheap one.
    **{
        f: [
            "tests/test_tracker_ingest.py",
            "tests/test_tracker_marks.py",
            "tests/test_tracker_mark_sentences.py",
            "tests/test_real_data_end_to_end.py",
        ]
        for f in (FINDINGS, MARKS, FACTS, RECONCILE)
    },
    READ: [
        "tests/test_tracker_ingest.py",
        "tests/test_tracker_marks.py",
        "tests/test_real_data_end_to_end.py",
    ],
    # The validators are pure and their suite is DB-free, so this stays cheap
    # and still runs under `--ci`.
    VALIDATORS: ["tests/test_validators.py"],
    API_EVALS: ["tests/test_evals.py"],
    # The manifest comparison is the only reader that can tell a right-shaped
    # citation on the wrong passage from a right one, so it defends both of
    # these alone. It needs the corpus and no database.
    DOC_LOAD: ["tests/test_corpus_manifest.py", "tests/test_document_load.py"],
    CAP_TABLE: ["tests/test_corpus_manifest.py", "tests/test_extract_cap_table.py"],
    MAPPER: ["tests/test_real_data_end_to_end.py", "tests/test_contracts.py"],
    LOTS: ["tests/test_real_data_end_to_end.py"],
    CLASSIFY: ["tests/test_real_data_end_to_end.py", "tests/test_policy_guards.py"],
    MODELS: [
        "tests/test_contracts.py",
        "tests/test_real_data_end_to_end.py",
        "tests/test_policy_vs_oracle.py",
    ],
    PARSE: ["tests/test_document_parse.py", "tests/test_document_end_to_end.py"],
    CITATIONS: ["tests/test_citations.py", "tests/test_document_store.py"],
    CLAIMS: ["tests/test_document_store.py", "tests/test_document_end_to_end.py"],
    TUPLES: ["tests/test_policy_matrix.py", "tests/test_policy_guards.py"],
    REDUCER: ["tests/test_policy_matrix.py", "tests/test_policy_guards.py"],
    REQS: [
        "tests/test_policy_guards.py",
        "tests/test_policy_matrix.py",
        "tests/test_policy_vs_oracle.py",
    ],
    SEED: ["tests/test_policy_guards.py", "tests/test_policy_vs_oracle.py"],
    # The G7 probes plant an inert module-level string. It changes no behaviour,
    # so no behavioural suite can possibly notice it and naming one would be
    # decoration — the answer-key scan is the only thing that can see it at all.
    #
    # That reasoning is what makes a one-file list correct here rather than a
    # shortcut, and it stops being true the moment a behavioural mutation is
    # added for either file. Whoever adds one adds its suites here.
    API_LEDGER: ["tests/test_policy_vs_oracle.py"],
    PACKET_MANIFEST: ["tests/test_policy_vs_oracle.py"],
}


def run_suite(python: str, target: Path | None = None) -> bool:
    """True when the suites that could defend `target` pass.

    `-n0` overrides the `-n 4` in `addopts`: spinning up four xdist workers
    costs more than it saves on one or two files, and this runs ninety-two
    times.
    """
    suites = FILE_SUITES.get(target, SUITES) if target is not None else SUITES
    proc = subprocess.run(
        [python, "-m", "pytest", *suites, "-q", "-x", "--no-header", "-n0", "-p", "no:randomly"],
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
                if run_suite(python, m.path):
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
    for what in NOT_MUTATED_HERE:
        print(f"  Not covered here: {what}.")
    # Printed in full rather than counted. A count is a number a reader rounds
    # to "mostly covered"; a list of module names is a decision about each one.
    absent = uncovered_modules()
    if absent:
        print(f"\n  {len(absent)} figure-producing module(s) carry no mutation here:")
        for rel in absent:
            print(f"    {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
