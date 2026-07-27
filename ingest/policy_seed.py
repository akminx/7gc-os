"""The three policy inputs that are judgements, written into the ledger.

    .venv/bin/python -m ingest.policy_seed --schema demo            # dry run
    .venv/bin/python -m ingest.policy_seed --schema demo --commit   # write

`claim_requirement`, `document_gap` and `valuation_component` all record a
decision a person made. None can be computed from the rows already in the
ledger — SPEC §15 keeps contentious judgements as reviewed inputs and derives
only their consequences, and that is what these are.

Two rules keep the judgements honest rather than merely declared:

* **A gap quotes the source, and the quote is resolved rather than typed.**
  Each entry declares a fragment; the full sentence is looked up in the
  workbook line containing it, and a fragment that matches no line — or more
  than one — refuses the whole seed. So a gap cannot outlive the sentence it
  rests on, and X3 holds: a gap quotes a document *saying* something is
  missing, never a document that does not exist.
* **Support is bound to an artefact.** A component's support names a claim or a
  lot, and `0010`'s trigger refuses a date that artefact does not carry.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import psycopg

from ingest.documents.reliance import RELIANCE
from ingest.trackers.read import SheetNote, read_master_notes
from packages.contracts.enums import GapKind, RequirementCode

Conn = psycopg.Connection[tuple[object, ...]]

MASTER = Path(
    "7GC Audit Case Study/01_Internal Trackers/"
    "Master Investment Breakdown - Funds I & II (Case Study).xlsx"
)


class SeedError(Exception):
    """A declared judgement does not match the ledger or the source."""


@dataclass(frozen=True)
class GapDecl:
    """A missing document, and the fragment of the line that reports it absent.

    `fragment` is matched against the workbook's own prose. It is short on
    purpose — long enough to be unique, short enough that reformatting the cell
    does not silently drop the gap.
    """

    holding_id: str
    requirement: RequirementCode
    security_class: str | None
    missing_document: str
    kind: GapKind
    fragment: str


R1 = RequirementCode.R1
R2 = RequirementCode.R2

#: The eleven absences the workbooks report, plus the two the cap table reports,
#: plus the three the enumerated supporting-documentation lists report by
#: omission. `kind` is the reviewed reading of the wording, and it decides the
#: verdict: with counsel is `partial` and asks the lawyers, an unlocatable
#: document is `missing` and asks the company, and a reference with no stated
#: location is `insufficient` because nobody knows who to ask.
GAPS: tuple[GapDecl, ...] = (
    GapDecl(
        "fund_ii_lucra",
        R1,
        "series_a1",
        "Series A-1 SPA",
        GapKind.WITH_COUNSEL,
        # The term sheet, not the workbook. The workbook's only counsel sentence
        # is about Series A-2, and quoting it here cited a different security
        # class as evidence for this one.
        "Series A-1 Stock Purchase Agreement",
    ),
    GapDecl(
        "fund_ii_fluidstack",
        R1,
        "series_a2",
        "Series A-2 executed docs",
        GapKind.WITH_COUNSEL,
        "executed docs on file with counsel",
    ),
    GapDecl(
        "fund_ii_sway",
        R1,
        "series_a",
        "Series A SPA (Oct 2023)",
        GapKind.WITH_COUNSEL,
        "Original Series A SPA (Oct 2023) on file with counsel",
    ),
    GapDecl(
        "fund_i_banzai",
        R1,
        "common",
        "pre-listing 2021 SPA",
        GapKind.WITH_COUNSEL,
        "Pre-listing 2021 SPA on file with counsel",
    ),
    GapDecl(
        "fund_ii_anthropic",
        R1,
        "unstated",
        "Feb 2024 subscription docs",
        GapKind.REFERENCED_LOCATION_UNSPECIFIED,
        "Entry: executed subscription docs on file (Feb 2024).",
    ),
    GapDecl(
        "fund_ii_because_market",
        R1,
        "series_b1",
        "Series B-1 SPA",
        GapKind.NOT_LOCATED,
        "SPA referenced above not yet located in Drive",
    ),
    GapDecl(
        "fund_i_capsule",
        R1,
        "series_b",
        "2019 Series B SPA",
        GapKind.NOT_LOCATED,
        "Original 2019 Series B SPA not located in Drive.",
    ),
    GapDecl(
        "fund_ii_jackpocket",
        R1,
        "series_b",
        "2021 SPA",
        GapKind.NOT_LOCATED,
        "Original 2021 SPA not yet located in Drive",
    ),
    GapDecl(
        "fund_i_the_mom_project",
        R1,
        "series_b",
        "2020 Series B SPA",
        GapKind.NOT_LOCATED,
        "2020 Series B SPA not located in Drive.",
    ),
    GapDecl(
        "fund_i_the_mom_project",
        R1,
        "conv_note",
        "2023 Note Purchase Agreement",
        GapKind.NOT_LOCATED,
        "2023 Note Purchase Agreement referenced in prior records",
    ),
    # Reported by omission: the sheet enumerates its supporting documentation
    # and no executed acquisition document is among it. The quote is the list
    # itself, because that list IS the evidence of the absence — inventing a
    # sentence saying "no document exists" would be citing a document that does
    # not exist, which X3 forbids.
    GapDecl(
        "fund_ii_dream",
        R1,
        "series_a1",
        "Series A-1 acquisition docs",
        GapKind.NOT_LOCATED,
        "Dream - Series B - Pro Forma Capitalization Table (November 14, 2025) — $8.00 PPS",
    ),
    GapDecl(
        "fund_ii_moonfare",
        R1,
        "fund_interest",
        "March 2023 acquisition docs",
        GapKind.NOT_LOCATED,
        "Moonfare - Third-Party Valuation Memorandum - FY2023 (December 31, 2023)",
    ),
    # ── R2 · the mark is carried at a price whose support is absent ──────
    GapDecl(
        "fund_ii_because_market",
        R2,
        "series_b1",
        "any fair value support",
        GapKind.NOT_LOCATED,
        "SPA referenced above not yet located in Drive",
    ),
    GapDecl(
        "fund_ii_sway",
        R2,
        "series_a",
        "Series A SPA (Oct 2023)",
        GapKind.WITH_COUNSEL,
        "Original Series A SPA (Oct 2023) on file with counsel",
    ),
    GapDecl(
        "fund_ii_jackpocket",
        R2,
        "series_b",
        "2021 SPA",
        GapKind.NOT_LOCATED,
        "Original 2021 SPA not yet located in Drive",
    ),
    GapDecl(
        "fund_ii_anthropic",
        R2,
        "unstated",
        "Feb 2024 subscription docs",
        GapKind.REFERENCED_LOCATION_UNSPECIFIED,
        "Entry: executed subscription docs on file (Feb 2024).",
    ),
)


@dataclass(frozen=True)
class ComponentDecl:
    """A material component of a mark, and the artefacts that date its support.

    `support` names claims by id and lots by id. An empty tuple is the finding,
    not an omission: SPEC §7.2 counts absent dated support as stale, so Because
    Market — which has no evidence of any kind — must read as stale rather than
    as satisfied.
    """

    holding_id: str
    component: str
    rationale: str
    claims: tuple[str, ...] = ()
    lots: tuple[str, ...] = ()


#: What each mark is made of. Where a mark rests on one thing, one component;
#: where it rests on two that can age independently, two. Moonfare and The Mom
#: Project are the two that split, and both split for the same reason: a fresh
#: half must not rescue a stale half (SPEC §7.2 limb (b) is "at least one").
COMPONENTS: tuple[ComponentDecl, ...] = (
    ComponentDecl(
        "fund_ii_because_market",
        "valuation",
        "one equity position; no evidence of any kind exists for it",
    ),
    ComponentDecl(
        "fund_ii_moonfare",
        "underlying_valuation",
        "the EUR value of the fund interest, which ages on its own clock",
        lots=("fund_ii_moonfare_1",),
    ),
    ComponentDecl(
        "fund_ii_moonfare",
        "fx_rate",
        "the EUR/USD rate applied to it. Re-dated annually while the underlying "
        "valuation is not, so combining them would let the fresh rate rescue a "
        "33-month-old valuation",
        claims=(
            "fund_ii_moonfare:fy2023_third_party_valuation",
            "fund_ii_moonfare:fy2024_fx_remeasurement",
        ),
    ),
    ComponentDecl(
        "fund_ii_sway",
        "valuation",
        "one equity position, repriced by the recap",
        claims=("fund_ii_sway:series_a3_recap_pro_forma",),
        lots=("fund_ii_sway_1",),
    ),
    ComponentDecl(
        "fund_ii_anthropic",
        "valuation",
        "one equity position. The press report is not qualifying support — a "
        "financing round, a valuation memo, an administrator statement or a market "
        "quote, and press is none of them",
        lots=("fund_ii_anthropic_1",),
    ),
    ComponentDecl(
        "fund_ii_lucra",
        "valuation",
        "one equity position, priced by term sheet",
        claims=("fund_ii_lucra:series_a1_price", "fund_ii_lucra:series_a2_price"),
    ),
    ComponentDecl(
        "fund_ii_poolside",
        "valuation",
        "one equity position held at its last round; the records note is what "
        "establishes that round is still the most recent",
        claims=("fund_ii_poolside:series_b_price", "fund_ii_poolside:series_b_fund_records"),
    ),
    ComponentDecl(
        "fund_ii_fluidstack",
        "valuation",
        "two equity tranches and a later round",
        claims=("fund_ii_fluidstack:series_a_price", "fund_ii_fluidstack:series_b_pro_forma"),
        lots=("fund_ii_fluidstack_2",),
    ),
    ComponentDecl(
        "fund_ii_dream",
        "valuation",
        "one equity position priced by the cap table",
        claims=("fund_ii_dream:series_b_pro_forma",),
    ),
    ComponentDecl(
        "fund_ii_jackpocket",
        "valuation",
        "one equity position; realised, and never independently valued while held",
    ),
    ComponentDecl(
        "fund_i_capsule",
        "valuation",
        "one equity position, last valued by the FY2022 memo",
        claims=("fund_i_capsule:fy2022_third_party_valuation",),
    ),
    ComponentDecl(
        "fund_i_the_mom_project",
        "equity_valuation",
        "the Series B and C shares, marked at the Series C price",
        claims=("fund_i_the_mom_project:series_c_term_sheet",),
    ),
    ComponentDecl(
        "fund_i_the_mom_project",
        "note_valuation",
        "the 2023 convertible note, held at cost with no valuation of any kind. "
        "Separate from the equity because it can be stale while the equity is not",
    ),
    ComponentDecl(
        "fund_i_roofstock",
        "valuation",
        "one equity position held at its last round; the records note is what "
        "establishes that round is still the most recent",
        claims=("fund_i_roofstock:series_e_price", "fund_i_roofstock:series_e_fund_records"),
    ),
    ComponentDecl(
        "fund_i_jio_indirect",
        "valuation",
        "the feeder's capital account, re-stated annually by the administrator",
        claims=(
            "fund_i_jio_indirect:fy2023_capital_account",
            "fund_i_jio_indirect:fy2024_capital_account",
            "fund_i_jio_indirect:fy2025_capital_account",
        ),
    ),
    ComponentDecl(
        "fund_i_banzai",
        "valuation",
        "the listed shares, quoted at each year end",
        claims=(
            "fund_i_banzai:fy2023_close",
            "fund_i_banzai:fy2024_close",
            "fund_i_banzai:fy2025_close",
        ),
    ),
)


def _sentences(text: str) -> list[str]:
    """A document's canonical text as sentences, with layout whitespace closed up.

    `pdftotext -layout` wraps a sentence across lines and pads it with the
    column spacing it preserved, so a gap sentence quoted straight out of the
    text arrives full of newlines and runs of spaces. The quote an auditor reads
    should be the sentence, not the page geometry around it.
    """
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z(])", flat) if s.strip()]


def _resolve(fragment: str, notes: Iterable[SheetNote], conn: Conn | None = None) -> str:
    """The one source sentence containing `fragment`, verbatim.

    Searches the workbooks **and** the stored document text. It searched only
    the workbooks, and that produced a false citation: Lucra's A-1 SPA absence
    is reported by the term sheet — "*The executed Series A-1 Stock Purchase
    Agreement and final closing capitalization table are on file with company
    counsel and have not been located in the Fund's document repository*" — and
    with only the workbook in scope the fragment matched the one workbook line
    mentioning counsel, which is about Series **A-2**.

    So the gap for a missing A-1 agreement cited a sentence about a different
    security class, and every check passed: the citation resolved, the verdict
    was right, and the oracle comparison checks verdicts rather than the
    passages behind them. A gap that quotes the wrong sentence is the failure
    this system exists to make impossible, so the search now covers every place
    the corpus can report an absence.
    """
    hits = {n.text for n in notes if fragment in n.text}
    if conn is not None:
        for (text,) in conn.execute("select canonical_text from document_version").fetchall():
            hits.update(s for s in _sentences(str(text)) if fragment in s)
    found = sorted(hits)
    if len(found) != 1:
        raise SeedError(
            f"the fragment {fragment!r} matches {len(found)} sentences across the workbooks "
            f"and the stored documents. A gap must quote the sentence that reports it, and a "
            f"fragment matching none has outlived its source while one matching several "
            f"cannot say which: {found[:3]}"
        )
    return found[0]


def seed_claim_requirements(conn: Conn) -> int:
    """Write `claim_requirement`, refusing any claim this file does not mention.

    Scoped to the holdings this file speaks for, not to every claim in the
    schema. `public` accumulates seed graphs from the one schema test that must
    commit to fire its deferred triggers, and those uuid-suffixed claims are
    nobody's evidence — comparing against them made this refuse a correct
    corpus. A new claim on a REAL holding is still caught, which is the case
    that matters: it is how a document gets read, classified, and then relied
    upon for nothing without anyone deciding that.
    """
    mine = {claim_id.split(":", 1)[0] for claim_id in RELIANCE}
    stored = {
        r[0]
        for r in conn.execute(
            "select id from claim where holding_id = any(%s)", (sorted(mine),)
        ).fetchall()
    }
    declared = set(RELIANCE)
    if stored != declared:
        raise SeedError(
            f"reliance is declared for {len(declared)} claims and the ledger holds "
            f"{len(stored)}. Undeclared: {sorted(stored - declared)}. Declared but absent: "
            f"{sorted(declared - stored)}. A claim relied upon for nothing must say so."
        )
    written = 0
    for claim_id, requirements in RELIANCE.items():
        for requirement in sorted(requirements):
            conn.execute(
                "insert into claim_requirement (claim_id, requirement) values (%s, %s)",
                (claim_id, requirement.value),
            )
            written += 1
    return written


def seed_document_gaps(conn: Conn, notes: list[SheetNote]) -> int:
    for gap in GAPS:
        conn.execute(
            "insert into document_gap (holding_id, requirement, security_class,"
            " missing_document, kind, source_quote) values (%s, %s, %s, %s, %s, %s)",
            (
                gap.holding_id,
                gap.requirement.value,
                gap.security_class,
                gap.missing_document,
                gap.kind.value,
                _resolve(gap.fragment, notes, conn),
            ),
        )
    return len(GAPS)


def seed_components(conn: Conn) -> tuple[int, int]:
    supports = 0
    for decl in COMPONENTS:
        row = conn.execute(
            "insert into valuation_component (holding_id, component, rationale)"
            " values (%s, %s, %s) returning id",
            (decl.holding_id, decl.component, decl.rationale),
        ).fetchone()
        assert row is not None
        component_id = row[0]
        for claim_id in decl.claims:
            # The as-of date is what a statement or memo supports: an
            # administrator's FY2025 capital account supports 12/31/2025 even
            # though it arrived in January. Delivery is a separate fact and
            # already drives `is_subsequent`.
            found = conn.execute(
                "select coalesce(as_of_date, issued_date) from claim where id = %s", (claim_id,)
            ).fetchone()
            if found is None:
                raise SeedError(f"component {decl.component} cites unknown claim {claim_id!r}")
            conn.execute(
                "insert into valuation_component_support (component_id, holding_id, claim_id,"
                " supported_on) values (%s, %s, %s, %s)",
                (component_id, decl.holding_id, claim_id, found[0]),
            )
            supports += 1
        for lot_id in decl.lots:
            found = conn.execute(
                "select acquired_date from lot where id = %s", (lot_id,)
            ).fetchone()
            if found is None:
                raise SeedError(f"component {decl.component} cites unknown lot {lot_id!r}")
            conn.execute(
                "insert into valuation_component_support (component_id, holding_id, lot_id,"
                " supported_on) values (%s, %s, %s, %s)",
                (component_id, decl.holding_id, lot_id, found[0]),
            )
            supports += 1
    return len(COMPONENTS), supports


#: SPEC §6.3. The version an approval is bound to; an assessment at a different
#: version does not satisfy the approval prerequisite, which is the point.
POLICY_VERSION = "v1"


def seed_assessments(conn: Conn) -> tuple[int, int, int]:
    """Materialise the five requirement verdicts per packet row.

    Unlike the three seeds above, **nothing here is a judgement** — every value
    is `assess_row()`'s output, written down. It is in this loader anyway because
    it is the same "the ledger must carry it before anything can read it" step,
    and because `0003`'s approval prerequisites join these tables: without them
    EVERY valuation approval is refused with `INV-10: valuation approval N names
    no evidence set`. That is a real Postgres refusal and it is plumbing, not the
    audit finding — it makes an ACCEPTED approval unreachable and hides the
    refusal the walkthrough is actually about.

    Three rows the schema will not let us store, each skipped deliberately:

    * **A holding with no mark at the date.** `evidence_assessment.mark_id` is
      `not null` and bound to `mark (id, holding_id, period_id)`. Jackpocket at
      24Q4 is realised and has no mark, so its R4 verdict cannot be stored beside
      a mark that does not exist. It still reaches the packet — `api/ledger.py`
      assesses live — so this is a limit on the STORED prerequisite set, not on
      what the auditor sees.
    * **A row whose R1 or R2 is `not_applicable`.** `0001`'s
      `always_applicable_requirements_are_applicable` refuses it, because a
      holding with no existence-and-cost evidence reading as fully supported is
      the defect that constraint exists for.
    * **Lineage-only periods.** `requirement_is_packet_scope` refuses them
      (INV-20).

    `pbc_requirement` and `evidence_assessment` are append-only by design — the
    schema refuses a DELETE — so this is written once into a freshly built
    schema. `scripts/localdb.sh` drops and rebuilds, and the Supabase reload does
    the same; there is no in-place re-run and there should not be one, because a
    second assessment of the same mark revision is what `unique (requirement_id,
    mark_id, revision)` exists to refuse.
    """
    from packages.contracts.enums import AuditScope, RequirementVerdict
    from policy.from_ledger import load as load_policy
    from policy.requirements import assess_row

    ledger = load_policy(conn)
    requirements = assessments = links = 0
    out_of_window: list[str] = []

    periods = sorted(
        (p for p in ledger.periods.values() if p.audit_scope is AuditScope.PACKET),
        key=lambda p: (p.fund_id, p.period_date),
    )
    for period in periods:
        for holding_id, holding in sorted(ledger.holdings.items()):
            if holding.fund_id != period.fund_id:
                continue
            found = conn.execute(
                "select id from mark where holding_id = %s and period_id = %s"
                " order by revision desc limit 1",
                (holding_id, period.id),
            ).fetchone()
            if found is None:
                continue
            mark_id = found[0]

            row = assess_row(ledger, holding_id, period.period_date)
            always = (RequirementCode.R1, RequirementCode.R2)
            if any(row.outcomes[c].verdict is RequirementVerdict.NOT_APPLICABLE for c in always):
                continue

            for code in sorted(row.outcomes):
                outcome = row.outcomes[code]
                applicable = outcome.verdict is not RequirementVerdict.NOT_APPLICABLE
                got = conn.execute(
                    "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
                    " values (%s, %s, %s, %s) returning id",
                    (holding_id, period.id, code.value, applicable),
                ).fetchone()
                assert got is not None
                requirement_id = got[0]
                requirements += 1

                got = conn.execute(
                    "insert into evidence_assessment (requirement_id, mark_id, holding_id,"
                    " period_id, verdict, reason_codes, next_actions, pro_forma, policy_version)"
                    " values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
                    (
                        requirement_id,
                        mark_id,
                        holding_id,
                        period.id,
                        outcome.verdict.value,
                        list(outcome.reasons),
                        list(outcome.next_actions),
                        outcome.pro_forma,
                        POLICY_VERSION,
                    ),
                ).fetchone()
                assert got is not None
                assessment_id = got[0]
                assessments += 1

                stored = 0
                for claim_id in outcome.relied_on:
                    claim = next((c for c in ledger.claims if c.id == claim_id), None)
                    if claim is None:
                        continue
                    # `0002`'s `check_link_applicability` enforces INV-16's
                    # window on EVERY link. `policy/requirements.py` applies it
                    # to R2 only (`WINDOWED`), because INV-5 says an acquisition
                    # does not un-happen: R1 keeps relying on a document after
                    # the date its valuation reliance closes.
                    #
                    # The two rules disagree, and only for a claim that has a
                    # CLOSED window and is also relied upon for R1 — which in
                    # this corpus is Jio's administrator statements, accepted as
                    # the existence-and-cost equivalent for a feeder interest by
                    # the matrix's owner determination. Nothing had ever written
                    # an `evidence_link` outside the tests, so the combination
                    # was unreachable and the disagreement invisible.
                    #
                    # Skipped rather than forced: widening the trigger is an
                    # invariant change and belongs to the owner, and writing the
                    # link anyway is not available — the database refuses it.
                    # The verdict, its reasons and its actions are unaffected;
                    # only the STORED citation set is narrower than
                    # `outcome.relied_on`, and the count is printed so the
                    # divergence is reported rather than absorbed.
                    if period.period_date < claim.applicable_from or (
                        claim.applicable_to is not None and period.period_date > claim.applicable_to
                    ):
                        out_of_window.append(f"{code.value} {holding_id}@{period.id} {claim_id}")
                        continue
                    # INV-3 · verified against the dates by `0004`'s trigger, not
                    # trusted. Computed the same way `api/ledger.py` computes it,
                    # from the claim's effective date rather than its issue date,
                    # so a January-delivered December statement is labelled.
                    conn.execute(
                        "insert into evidence_link (assessment_id, claim_id, is_subsequent)"
                        " values (%s, %s, %s)",
                        (assessment_id, claim_id, claim.effective_date > period.period_date),
                    )
                    stored += 1
                    links += 1

                # `0003` refuses an approval citing a `sufficient` R1 or R2 that
                # links no claim. Caught here rather than at approval time: a row
                # stored now and refused during the demo is the same defect with
                # a worse audience.
                if (
                    code in always
                    and outcome.verdict is RequirementVerdict.SUFFICIENT
                    and stored == 0
                ):
                    raise SeedError(
                        f"{code.value} for {holding_id} at {period.id} is sufficient but every "
                        f"claim it relies on is outside its own reliance window, so no evidence "
                        f"link can be stored. `0003` would refuse any approval citing it."
                    )

    if out_of_window:
        print(
            f"  note: {len(out_of_window)} relied-upon claims were NOT stored as evidence "
            f"links — outside their own reliance window, which `0002` enforces on every "
            f"link while `policy/` enforces it for R2 only:"
        )
        for entry in out_of_window:
            print(f"    {entry}")
    return requirements, assessments, links


def main(argv: list[str] | None = None) -> int:
    from api.config import dsn, ledger_schema

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="write; otherwise roll back")
    parser.add_argument("--schema", default=None)
    args = parser.parse_args(argv)

    url = dsn("MIGRATION_DATABASE_URL") or dsn("DATABASE_URL")
    if not url:
        print("MIGRATION_DATABASE_URL is not set", file=sys.stderr)
        return 1
    schema = args.schema or ledger_schema()

    # psycopg's OUTERMOST `transaction()` block COMMITS on exit; only a nested
    # one is a savepoint. Without this explicit outer block the dry run writes
    # and `--commit` is decorative — which has happened twice on this project,
    # in two different loaders, on the same day. The two `with` clauses are one
    # statement rather than nested because they are one thing: a connection
    # whose work is discarded unless asked for.
    with (
        psycopg.connect(url, options=f"-c search_path={schema}") as conn,
        conn.transaction() as outer,
    ):
        links = seed_claim_requirements(conn)
        gaps = seed_document_gaps(conn, read_master_notes(MASTER))
        components, supports = seed_components(conn)
        # Last: it reads the ledger the three seeds above have just written.
        reqs, assessed, cited = seed_assessments(conn)
        print(
            f"{links} claim-requirement links, {gaps} document gaps, "
            f"{components} components with {supports} support observations"
        )
        print(f"{reqs} pbc requirements, {assessed} assessments, {cited} evidence links")
        if not args.commit:
            print("dry run — rolling back; pass --commit to write")
            raise psycopg.Rollback(outer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
