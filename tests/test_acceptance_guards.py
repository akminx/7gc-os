"""The acceptance report's own guards, proved by breaking what each one watches.

`scripts/acceptance.py` exists because nothing measured this system against the
client's letter, and ¶1's third limb — "and settlement of funds" — went
unanswered until two reviewers found it from opposite directions. A report that
would not have caught that is worse than no report, because it would have said
the letter was answered.

So the first test here is that exact regression, run against the vocabulary the
ledger had before the settlement claims were bound. The rest defend the two
things that could quietly stop the report from checking anything: a quotation
that no longer appears in the letter, and a limb that asks for nothing.

Then five that defend what the report SAYS rather than what it checks, because
a report can measure honestly and still describe itself dishonestly:

* three limbs the ledger cannot tell apart must be one finding, not three;
* a Fund I position must not be counted into a Fund II letter unnamed;
* ¶2's denominator must admit it is the wrong denominator;
* ¶4's head noun — proceeds received — must have a limb at all;
* and the pro-forma aside must not read as a deficiency when there is nothing
  to identify.

No database. Every fixture below is a hand-built `Evidence`, because what is
under test is the report's reasoning rather than the corpus it reads.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# Through `importlib` for the same reason `tests/test_gate_guards.py` does it:
# the path insert has to run first, and a module-level import after a statement
# is E402. The gate holds inline suppressions at zero.
acceptance = importlib.import_module("acceptance")

LIMBS = {limb.key: limb for limb in acceptance.LIMBS}

#: The letter's own words, as `scripts/acceptance.py` quotes them, so a test
#: that does not need the private PDF still checks against real sentences. The
#: fund is here because the report resolves that against the letter too: which
#: positions the client asked about is a claim about the letter, and an
#: unchecked claim about the letter is what this mechanism exists to prevent.
LETTER_ENOUGH = (
    "In connection with our audits of 7GC Fund II, L.P. for the fiscal years ended "
    "December 31, 2023: "
    "1. Existence and cost. Executed transaction documents supporting the Fund's "
    "acquisition of each position, including share counts, price per share, and "
    "settlement of funds. "
    "4. Realized investments. Merger consideration statements, distribution notices, "
    "or other support for proceeds received, including per-share consideration and "
    "share counts."
)


def evidence(**vocabulary: frozenset[str]) -> Any:
    """An `Evidence` carrying only the vocabularies a test is about."""
    ev = acceptance.Evidence()
    for name, value in vocabulary.items():
        setattr(ev, name, value)
    return ev


def everything_the_letter_asks_for() -> Any:
    """A ledger whose vocabulary can record every artefact the letter names.

    Built FROM the limb map, so a limb added later is recordable here by
    construction. The point of these fixtures is what the report says about a
    ledger that lacks nothing, and a fixture listing enum values by hand would
    turn every new limb into a false `NOT EXPRESSIBLE`.
    """
    return evidence(
        known_classes=frozenset().union(*(limb.classes for limb in acceptance.LIMBS)),
        known_fields=frozenset().union(*(limb.fields for limb in acceptance.LIMBS)),
        known_decisions=frozenset().union(*(limb.decisions for limb in acceptance.LIMBS)),
        known_statuses=frozenset().union(*(limb.statuses for limb in acceptance.LIMBS)),
    )


def two_funds(**held_evidence: object) -> Any:
    """One Fund II position and one Fund I position, both held at one date.

    The letter is Fund II's and `docs/SPEC.md` measures Fund I anyway, so this
    is the shape the real ledger has: a denominator spanning two funds, only one
    of which the client asked about.
    """
    ev = everything_the_letter_asks_for()
    ev.holdings = {"fund_ii_poolside": "poolside", "fund_i_capsule": "capsule"}
    ev.funds = {"fund_ii_poolside": "fund_ii", "fund_i_capsule": "fund_i"}
    ev.dates = ("2025-12-31",)
    ev.held = {("fund_ii_poolside", "2025-12-31"), ("fund_i_capsule", "2025-12-31")}
    ev.marks_total = 2
    for name, value in held_evidence.items():
        getattr(ev, name).update(value)
    return ev


def section(lines: list[str], header: str) -> list[str]:
    """The lines under one heading of the closing summary."""
    out: list[str] = []
    inside = False
    for line in lines:
        if line.startswith(("UNANSWERABLE", "UNANSWERED")):
            inside = line.startswith(header)
        elif "limbs go unanswered" in line:
            inside = False
        elif inside:
            out.append(line)
    return out


# ── the regression this file exists for ──────────────────────────────────
def test_the_settlement_limb_is_unanswerable_before_the_ledger_can_record_it() -> None:
    """¶1(d), against the field vocabulary as it stood when the limb went missing.

    Nothing wrote `settlement_amount_received`, so no position could answer
    "settlement of funds" and none ever would have — and R1 still read
    `sufficient`, because the document was there and the clause was not
    represented by anything that could be absent.

    A limb the ledger has no vocabulary for is the one state this report exits
    non-zero on, and this is why.
    """
    before = evidence(
        known_fields=frozenset({"fund_shares", "fund_price_per_share", "agreement_date"}),
        known_classes=frozenset({"executed_transaction_doc"}),
        known_decisions=frozenset({"valuation"}),
        known_statuses=frozenset({"executed"}),
    )
    missing = acceptance.missing_vocabulary(LIMBS["1d"], before)
    assert missing == ["settlement_amount_received", "settlement_date", "settlement_reference"], (
        "the settlement limb read as answerable against a ledger that could not record it"
    )


def test_the_settlement_limb_is_answerable_once_the_ledger_records_it() -> None:
    """The control. Without it the assertion above is satisfied by a check that
    calls every limb unanswerable, which is the other way to stop measuring."""
    after = evidence(
        known_fields=frozenset(LIMBS["1d"].fields),
        known_classes=frozenset(),
        known_decisions=frozenset(),
        known_statuses=frozenset(),
    )
    assert acceptance.missing_vocabulary(LIMBS["1d"], after) == []


def test_a_management_assessment_is_a_decision_the_ledger_can_already_record() -> None:
    """¶3(b) is NOT a system gap, and the first version of this report said it was.

    A management assessment is not a source document — nobody sends it to the
    fund. It is a `review_decision` of type `management_assessment` bound to the
    mark it concerns, the schema has carried that since 0001, and the corpus
    holds none. "The fund has not written one" and "there is nowhere to put one"
    are different answers to the client, and only the second is ours to fix.
    """
    ledger_as_it_is = evidence(
        known_classes=frozenset({"executed_transaction_doc", "third_party_valuation_memo"}),
        known_fields=frozenset(),
        known_decisions=frozenset(
            {"transcription", "valuation", "management_assessment", "packet"}
        ),
        known_statuses=frozenset(),
    )
    for key in ("2d", "3b", "6"):
        assert acceptance.missing_vocabulary(LIMBS[key], ledger_as_it_is) == [], (
            f"limb {key} reported as unrecordable; the ledger records it as a decision"
        )


# ── one decision type, three different documents ─────────────────────────
def test_the_three_management_assessment_limbs_cannot_be_told_apart() -> None:
    """The version of the test above that this file used to end at asserted all
    three limbs were RECORDABLE, and it passed because they are the same limb.

    ¶2's memo describing the basis of the mark, ¶3(b)'s assessment that a last
    round price remains representative, and the closing paragraph's calibration
    are three documents management would write for three reasons.
    `review_decision.decision_type` has one value for all three, `answered`
    reads nothing else, and so the three rows are one query run three times.
    Three `0/34`s printed as three findings is the report agreeing with the
    collapse instead of reporting it.
    """
    for key, others in (("2d", ["3b", "6"]), ("3b", ["2d", "6"]), ("6", ["2d", "3b"])):
        assert acceptance.indistinguishable(LIMBS[key], acceptance.LIMBS) == others
        reasons = acceptance.unspeakable(LIMBS[key], everything_the_letter_asks_for())
        assert reasons, f"limb {key} reported as answerable when it shares its predicate"
        assert "cannot tell this apart" in reasons[0]


def test_a_limb_with_its_own_decision_type_is_not_reported_as_collapsed() -> None:
    """The control, and the one that matters: a check calling every limb
    indistinguishable would satisfy the test above and measure nothing.

    This is also what the fix upstream looks like. Give the three artefacts
    three `decision_type` values and the report stops flagging them, without a
    line of this file changing.
    """
    separated = tuple(
        acceptance.Limb(
            key,
            "management writes one of these",
            "management's memo describing the basis of the mark",
            acceptance.BY_POSITION_DATE,
            decisions=frozenset({kind}),
        )
        for key, kind in (("2d", "basis_memo"), ("3b", "representativeness"), ("6", "calibration"))
    )
    ledger = evidence(
        known_decisions=frozenset({"basis_memo", "representativeness", "calibration"})
    )
    for limb in separated:
        assert acceptance.indistinguishable(limb, separated) == []
        assert acceptance.unspeakable(limb, ledger, separated) == []


def test_two_limbs_asking_the_same_thing_of_different_scopes_are_not_collapsed() -> None:
    """`answered` is asked about a POSITION or about a position AT a date, and
    the answers differ. Collapsing on the evidence alone would report ¶1 and ¶2
    as indistinguishable wherever they name the same document class, which is
    most of the letter."""
    same_evidence = tuple(
        acceptance.Limb(
            key,
            "the round's executed documents",
            "the documentation of that most recent round",
            scope,
            classes=frozenset({"executed_transaction_doc"}),
        )
        for key, scope in (("x", acceptance.BY_POSITION), ("y", acceptance.BY_POSITION_DATE))
    )
    for limb in same_evidence:
        assert acceptance.indistinguishable(limb, same_evidence) == []


def test_the_collapsed_limbs_are_reported_once_as_a_defect_not_three_times() -> None:
    """The whole point of the finding, at the level a reader acts on.

    Under the collapse the three limbs must appear as UNANSWERABLE — a
    limitation of this system, which no document the fund sends can lift — and
    never as three separate UNANSWERED rows, which would read as three requests
    the fund has failed to answer.
    """
    ev = two_funds()
    lines, code = acceptance.closing(acceptance.assess(ev), strict=False)
    unanswerable = " ".join(section(lines, "UNANSWERABLE"))
    unanswered = " ".join(section(lines, "UNANSWERED"))
    for key in ("2d", "3b", "6"):
        assert f"  {key:4}" in unanswerable, f"{key} is not reported as a limitation of the system"
        assert f"  {key:4}" not in unanswered, f"{key} is reported as the fund's records saying no"
    assert "are ONE finding and not 3" in " ".join(lines)
    assert "1 distinct" in " ".join(lines), "three rows counted as three defects"
    assert code == 1, "a clause of the letter with nowhere to land does not fail the report"


# ── the letter is one fund's ─────────────────────────────────────────────
def test_a_positions_fund_survives_into_every_name_the_report_prints() -> None:
    """`short` used to strip `fund_i_` and `fund_ii_` alike, so `capsule` and
    `anthropic` sat in one column of a report headed by a Fund II audit. Five of
    the fourteen positions are not in the engagement and nothing said so."""
    assert acceptance.short("fund_i_capsule", "fund_i") == "Fund I · capsule"
    assert acceptance.short("fund_ii_poolside", "fund_ii") == "Fund II · poolside"
    # A fund the report has never heard of prints as itself rather than being
    # folded into one it has.
    assert acceptance.short("fund_iii_x", "fund_iii") == "fund_iii · x"
    # And a holding with no fund recorded keeps its whole id: a name this report
    # cannot place is the one worth seeing whole.
    assert acceptance.short("fund_i_capsule", None) == "fund_i_capsule"


def test_a_limbs_denominator_states_which_fund_it_counts() -> None:
    """`4/14` is a count over two funds and the client asked about one."""
    ev = two_funds(classes_by_position={"fund_ii_poolside": {"executed_transaction_doc"}})
    printed = acceptance.report(ev, acceptance.assess(ev))
    line = next(x for x in printed if "1a " in x)
    body = printed[printed.index(line) + 1]
    assert body.strip() == "answered for 1/2 · Fund II 1/1 · Fund I 0/1", body
    assert any("(Fund II 1, Fund I 1)" in x for x in printed), "the ledger line hides the split"
    assert any("no evidence · Fund I: capsule" in x for x in printed)


def test_the_report_refuses_a_ledger_holding_nothing_for_the_letters_fund() -> None:
    """`LETTER_FUND` is the one name resolved against neither the letter nor a
    column. An id rename would otherwise print `Fund II 0/0` beside every limb,
    which reads as a fund with no support rather than a report pointed at
    nothing."""
    ev = two_funds()
    ev.funds = {"fund_i_capsule": "fund_i"}
    with pytest.raises(acceptance.AcceptanceError, match="no holding in this ledger belongs"):
        acceptance.check_fund_scope(ev)
    acceptance.check_fund_scope(two_funds())


# ── ¶2's branches are conditional and nothing records the condition ──────
def test_paragraph_2_says_its_denominator_is_larger_than_the_letters() -> None:
    """ "For marks based on a financing round: … For marks based on other
    information: …" — and `mark.basis` is NULL for every mark, so all four limbs
    are scored against every position rather than the subset each branch
    governs. The report has to say that where the numbers are; inferring each
    mark's basis from the evidence on file, and then using it to decide which
    evidence is required, would be circular."""
    ev = two_funds()
    ev.marks_total, ev.marks_with_basis = 72, 0
    caveat = " ".join(acceptance.basis_caveat(ev))
    assert "recorded for 0 of 72 marks" in caveat
    assert "every denominator is larger than the letter's" in caveat
    assert "circular" in caveat
    printed = acceptance.report(ev, acceptance.assess(ev))
    where = printed.index(next(x for x in printed if x.startswith("¶2 ·")))
    assert "recorded for 0 of 72 marks" in " ".join(printed[where : where + 10]), (
        "the caveat is not printed where ¶2's numbers are"
    )


def test_the_caveat_goes_when_every_mark_records_what_it_is_based_on() -> None:
    """The control. A caveat that prints unconditionally is an apology, not a
    measurement, and it would survive the fix that makes it false."""
    ev = two_funds()
    ev.marks_total, ev.marks_with_basis = 72, 72
    assert acceptance.basis_caveat(ev) == []


# ── ¶4 asks for the proceeds, not only for what is included in them ──────
def test_proceeds_received_has_a_limb_of_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "…or other support for **proceeds received**, including per-share
    consideration and share counts." The document, the per-share figure and the
    share count each had a limb; the thing they are support FOR had none — ¶1's
    settlement limb one paragraph along. `field_requirements.py` declares
    `gross_consideration` and `net_payment` under R4, so the ledger answers it
    and nothing was asking."""
    para_4 = next(limbs for code, _, limbs in acceptance.REQUESTS if code == "¶4")
    asked = frozenset().union(*(limb.fields for limb in para_4))
    assert {"gross_consideration", "net_payment"} <= asked, (
        "¶4 checks what is included in the proceeds and never the proceeds"
    )
    proceeds = next(limb for limb in para_4 if "gross_consideration" in limb.fields)
    assert proceeds.scope == acceptance.BY_REALISATION
    # And it quotes the letter, on the same terms every other limb does: ¶4 as
    # the client wrote it, with the new fragment resolving in it exactly once.
    monkeypatch.setattr(acceptance, "LIMBS", para_4)
    acceptance.resolve_fragments(LETTER_ENOUGH)


# ── the pro-forma aside is a census, not a coverage fraction ─────────────
def test_a_non_binding_term_sheet_does_not_make_a_position_pro_forma() -> None:
    """¶5 used to be asked of `executed_docs_pending`, `executed_docs_location`
    and `closing_set_status`, and `executed_docs_location` alone satisfied it.
    `ingest/documents/extract_term_sheet.py` emits that field for The Mom
    Project's summary of terms — `non_binding`, with the executed agreement on
    file with company counsel — and a document that is not pro forma cannot make
    a mark pro forma. `claim.execution_status` is where the fact lives."""
    ev = two_funds()
    ev.fields_by_date[("fund_i_the_mom_project", "2025-12-31")] = {"executed_docs_location"}
    ev.statuses_by_date[("fund_i_the_mom_project", "2025-12-31")] = {"non_binding"}
    assert not acceptance.answered(LIMBS["5"], ev, "fund_i_the_mom_project", "2025-12-31")


def test_a_pro_forma_claim_identifies_the_position() -> None:
    """The control, and the letter's actual request: the three positions whose
    marks rest on a pro forma cap table are the answer to it."""
    ev = two_funds()
    ev.statuses_by_date[("fund_ii_dream", "2025-12-31")] = {"pro_forma", "executed"}
    assert acceptance.answered(LIMBS["5"], ev, "fund_ii_dream", "2025-12-31")


def test_a_fund_with_no_pro_forma_marks_is_not_reported_as_owing_an_answer() -> None:
    """Every other limb means "the fund owes the auditor this". ¶5 means "tell
    us which subset applies", and a fund whose marks all rest on executed
    documents answers it with `none`. Rendered like the others it read `0/34`
    under "what the auditor is owed an answer about", which is backwards: a
    clean record printed as a deficiency."""
    ev = two_funds()
    assert not any(acceptance.answered(LIMBS["5"], ev, h, d) for h, d in ev.held)
    lines, _ = acceptance.closing(acceptance.assess(ev), strict=True)
    assert "  5   " not in " ".join(section(lines, "UNANSWERED"))
    printed = " ".join(acceptance.report(ev, acceptance.assess(ev)))
    assert "identifies 0 of 2 held position-dates" in printed
    assert "no position is marked on a pro forma basis" in printed


# ── a quotation that drifted is not a quotation ──────────────────────────
def test_a_fragment_that_no_longer_appears_in_the_letter_refuses_the_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A limb still checked, still printed, and no longer describing anything the
    client wrote. `ingest/policy_seed.py` refuses on the same condition."""
    drifted = acceptance.Limb(
        "1d",
        "settlement of funds",
        "and settlement of monies",
        acceptance.BY_POSITION,
        fields=frozenset({"settlement_date"}),
    )
    monkeypatch.setattr(acceptance, "LIMBS", (drifted,))
    with pytest.raises(acceptance.AcceptanceError, match="no longer resolve"):
        acceptance.resolve_fragments(LETTER_ENOUGH)


def test_the_fund_the_letter_names_is_resolved_against_it_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Which fund the report is about is a claim about the letter, and it is
    checked the way every other claim about the letter is. A letter that turned
    out to be Fund III's would refuse rather than count Fund II's positions
    under it."""
    monkeypatch.setattr(acceptance, "LIMBS", ())
    acceptance.resolve_fragments(LETTER_ENOUGH)
    with pytest.raises(acceptance.AcceptanceError, match="fund:"):
        acceptance.resolve_fragments("In connection with our audits of 7GC Fund III, L.P.")


def test_a_fragment_matching_more_than_once_is_refused_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambiguity is the other failure. A fragment matching two sentences pins
    neither, and the limb would survive the deletion of the one it meant."""
    ambiguous = acceptance.Limb(
        "1x", "cost", "cost", acceptance.BY_POSITION, fields=frozenset({"settlement_date"})
    )
    monkeypatch.setattr(acceptance, "LIMBS", (ambiguous,))
    with pytest.raises(acceptance.AcceptanceError, match="no longer resolve"):
        acceptance.resolve_fragments(LETTER_ENOUGH + " The cost is the cost.")


def test_the_letters_own_wrapping_does_not_drop_a_limb(monkeypatch: pytest.MonkeyPatch) -> None:
    """`pdftotext` wraps the letter at the page width, so the clause this report
    was built for is split across two lines in the file. Compared as written it
    matches nothing, and every limb would refuse for a reason that is about
    typography."""
    monkeypatch.setattr(acceptance, "LIMBS", (LIMBS["1c"], LIMBS["1d"]))
    acceptance.resolve_fragments(
        "our audits of 7GC Fund II, L.P.\nincluding share counts, price\nper share,"
        " and settlement of funds."
    )


# ── a limb that asks for nothing is answered by everything ───────────────
def test_a_limb_declaring_no_evidence_at_all_is_refused_at_construction() -> None:
    with pytest.raises(acceptance.AcceptanceError, match="declares no evidence"):
        acceptance.Limb("zz", "asks for nothing", "Existence and cost", acceptance.BY_POSITION)


def test_every_declared_limb_asks_for_something() -> None:
    """The real map, not a fixture. `__post_init__` enforces it at import, so
    this is the assertion that the enforcement is still wired to the real
    limbs rather than only to the ones a test builds."""
    assert acceptance.LIMBS
    for limb in acceptance.LIMBS:
        assert limb.classes or limb.fields or limb.decisions or limb.statuses, limb.key


def test_answered_reads_the_predicate_and_nothing_else() -> None:
    """What makes `indistinguishable` a fact rather than a guess.

    If `answered` grew a dimension `predicate` does not carry, two limbs could
    differ in it and still be reported as the same — the collapse hidden by the
    check written to find it. `zip(strict=True)` makes that a crash; this is
    the assertion that the two are still the same length.
    """
    limb = LIMBS["2b"]
    assert acceptance.predicate(limb) == (
        limb.scope,
        limb.classes,
        limb.fields,
        limb.decisions,
        limb.statuses,
    )
    acceptance.answered(limb, acceptance.Evidence(), "h", "2025-12-31")
    acceptance.answered(limb, acceptance.Evidence(), "h", None)


# ── the dimensions are a conjunction ─────────────────────────────────────
def test_a_pro_forma_table_without_a_price_per_share_does_not_answer_2b() -> None:
    """¶2 conditions the disjunct on "evidencing price per share", so the
    qualifier is load-bearing: the class alone is not the limb."""
    limb = LIMBS["2b"]
    ev = acceptance.Evidence()
    ev.classes_by_date[("h", "2025-12-31")] = set(limb.classes)
    assert not acceptance.answered(limb, ev, "h", "2025-12-31")
    ev.fields_by_date[("h", "2025-12-31")] = {next(iter(limb.fields))}
    assert acceptance.answered(limb, ev, "h", "2025-12-31")


def test_a_price_per_share_from_the_wrong_kind_of_document_does_not_answer_2b() -> None:
    """The other half of the conjunction, and the reason this is not a field
    check: a term sheet states a price per share and is not a cap table."""
    limb = LIMBS["2b"]
    ev = acceptance.Evidence()
    ev.classes_by_date[("h", "2025-12-31")] = {"company_communication"}
    ev.fields_by_date[("h", "2025-12-31")] = set(limb.fields)
    assert not acceptance.answered(limb, ev, "h", "2025-12-31")


# ── against the real letter, when it is here ─────────────────────────────
@pytest.mark.skipif(
    not acceptance.LETTER.exists(),
    reason="case-study document is not in the repository",
)
def test_every_fragment_resolves_against_the_letter_itself() -> None:
    """The whole map against the client's actual file. Everything above tests
    the machinery; this tests that the machinery is pointed at the letter."""
    acceptance.resolve_fragments(acceptance.letter_text())
