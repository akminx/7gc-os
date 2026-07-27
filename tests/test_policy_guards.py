"""The branches the corpus cannot reach, exercised deliberately.

Every guard here refuses something. None of them fires on the fund's own data —
no document contradicts another, no sheet claims two position types, no
recapitalisation is missing its class. A guard that only runs on data nobody
has is a guard nobody has proved, and this project has found seven checks that
passed because they could not run.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from ingest.trackers.classify import (
    ClassificationError,
    Reading,
    position_type,
    recapitalisation,
    security_class,
)
from ingest.trackers.read import SheetNote, Tranche
from packages.contracts.enums import (
    AuditScope,
    ExecutionStatus,
    GapKind,
    PositionType,
    RequirementCode,
    RequirementVerdict,
    SourceClass,
)
from policy.inputs import (
    ClaimResolution,
    EvidenceClaim,
    Gap,
    Holding,
    Ledger,
    LedgerError,
    Lot,
    MarkObservation,
    MaterialComponent,
    Period,
    PolicyDecision,
    SupportObservation,
)
from policy.reducer import ReducerError, best, worst
from policy.requirements import assess_row, minus_months, r1, r2, r3
from tests.schema_helpers import DSN
from tests.tracker_helpers import needs_workbooks

PERIOD = Period("p", "f", date(2025, 12, 31), AuditScope.PACKET)
PRIOR = Period("p0", "f", date(2024, 12, 31), AuditScope.PACKET)


def _note(text: str, cells: tuple[object, ...] = ()) -> SheetNote:
    return SheetNote(
        company="X", fund="Fund II", text=text, source_sheet="X", ordinal=0, cells=cells
    )


def _tranche(kind: str = "Fund", acquired: date | None = date(2024, 1, 1)) -> Tranche:
    return Tranche(
        company="X",
        fund="Fund II",
        kind=kind,
        investment=Decimal(1000),
        entry_valuation=None,
        share_price=Decimal(1),
        share_count=Decimal(1000),
        acquired=acquired,
        acquired_text=None if acquired is None else acquired.isoformat(),
        acquired_range=None if acquired is None else (acquired, acquired),
        source_sheet="X",
    )


def _ledger(**over: Any) -> Ledger:
    """One holding, one lot, one component — the smallest ledger a rule needs.

    `Any` rather than `object` on the overrides, because every field of `Ledger`
    has a different type and a keyword-splat of `dict[str, object]` cannot be
    checked against them. The alternative was a suppression comment, and the
    gate holds that ceiling at zero for the reason this file exists: a
    suppressed check is a check that stopped checking.
    """
    base: dict[str, Any] = {
        "holdings": {"h": Holding("h", "f", PositionType.DIRECT_EQUITY)},
        "periods": {"p": PERIOD, "p0": PRIOR},
        "lots": (
            Lot("l", "h", "series_a", 100, Decimal(1), Decimal(100), "USD", date(2020, 1, 1)),
        ),
        "claims": (),
        "gaps": (),
        "marks": (
            MarkObservation("h", "p", Decimal(100)),
            MarkObservation("h", "p0", Decimal(100)),
        ),
        "components": (MaterialComponent("h", "valuation"),),
    }
    base.update(over)
    return Ledger(**base)


def _claim(claim_id: str, priced: str | None, pps: str | None, **over: Any) -> EvidenceClaim:
    fields: dict[str, Any] = {
        "id": claim_id,
        "holding_id": "h",
        "source_class": SourceClass.EXECUTED_TRANSACTION_DOC,
        "execution_status": ExecutionStatus.EXECUTED,
        "issued_date": date(2025, 1, 1),
        "applicable_from": date(2025, 1, 1),
        "requirements": frozenset({RequirementCode.R2}),
        "priced_class": priced,
        "price_per_share": None if pps is None else Decimal(pps),
    }
    fields.update(over)
    return EvidenceClaim(**fields)


# ── the corpus contains no contradiction, so it is injected ──────────────
def test_two_prices_for_one_class_make_the_requirement_conflicting() -> None:
    """SPEC §7.4 rule 1. `conflicting` dominates and is off the severity scale,
    so it survives beside a `sufficient` link rather than losing to it."""
    ledger = _ledger(
        claims=(_claim("a", "series_a", "10.00"), _claim("b", "series_a", "12.00")),
    )
    outcome = r2(ledger, "h", date(2025, 12, 31))
    assert outcome.verdict is RequirementVerdict.CONFLICTING
    assert outcome.reasons == ("CONTRADICTORY_CLAIMS",)
    assert outcome.next_actions == ("RESOLVE_CONTRADICTION",)


def test_a_recorded_resolution_clears_the_contradiction_it_names() -> None:
    """And only the one it names. `conflicting` does not decay with time; it
    persists until a person says which claim supersedes which."""
    claims = (_claim("a", "series_a", "10.00"), _claim("b", "series_a", "12.00"))
    unresolved = r2(_ledger(claims=claims), "h", date(2025, 12, 31))
    resolved = r2(
        _ledger(claims=claims, resolutions=(ClaimResolution("h", "series_a", "b"),)),
        "h",
        date(2025, 12, 31),
    )
    assert unresolved.verdict is RequirementVerdict.CONFLICTING
    assert resolved.verdict is not RequirementVerdict.CONFLICTING


def test_two_prices_for_two_classes_are_two_facts_not_a_contradiction() -> None:
    """Lucra holds A-1 at $2.00 and hears about A-2 at $3.00. Treating any two
    prices as contradictory would make every multi-class holding conflicting."""
    ledger = _ledger(claims=(_claim("a", "series_a", "10.00"), _claim("b", "series_b", "12.00")))
    assert r2(ledger, "h", date(2025, 12, 31)).verdict is not RequirementVerdict.CONFLICTING


def test_a_scoped_policy_decision_clears_cross_class_for_that_holding_only() -> None:
    """INV-17 · a decision recorded for one position must not clear another."""
    ledger = _ledger(claims=(_claim("a", "series_b", "10.00"),))
    without = r2(ledger, "h", date(2025, 12, 31))
    assert without.cross_class is True
    assert "CROSS_CLASS_POLICY_DECISION_REQUIRED" in without.reasons

    decided = _ledger(
        claims=(_claim("a", "series_b", "10.00"),),
        decisions=(PolicyDecision("h", date(2025, 12, 31), "series_b->series_a", "q"),),
    )
    outcome = r2(decided, "h", date(2025, 12, 31))
    assert outcome.cross_class is True, "the fact is still true and still recorded"
    assert "CROSS_CLASS_POLICY_DECISION_REQUIRED" not in outcome.reasons

    elsewhere = _ledger(
        claims=(_claim("a", "series_b", "10.00"),),
        decisions=(PolicyDecision("other", date(2025, 12, 31), "x", "q"),),
    )
    assert "CROSS_CLASS_POLICY_DECISION_REQUIRED" in r2(elsewhere, "h", date(2025, 12, 31)).reasons


def test_a_requirement_with_no_evidence_and_no_gap_is_missing_not_silent() -> None:
    """`gap_result(None)` — no document, and no observation explaining why."""
    outcome = r1(_ledger(), "h", date(2025, 12, 31))
    assert outcome.verdict is RequirementVerdict.MISSING
    assert outcome.reasons == ("NO_DOCUMENT_AND_NO_GAP_RECORDED",)
    assert outcome.next_actions == ("REQUEST_FROM_COMPANY",)


def test_a_gap_scoped_to_another_class_does_not_answer_this_lot() -> None:
    """Gaps are scoped to the lot they affect, so a holding with one documented
    lot and one undocumented lot resolves to `partial`, never `sufficient`."""
    gap = Gap("h", RequirementCode.R1, GapKind.WITH_COUNSEL, "SPA", "quote", "series_zzz")
    outcome = r1(_ledger(gaps=(gap,)), "h", date(2025, 12, 31))
    assert outcome.verdict is RequirementVerdict.MISSING


def test_a_holding_with_no_recorded_components_refuses_rather_than_passing() -> None:
    """Omission used to fail OPEN: a holding absent from the component list
    returned "all components have support" and R3 silently never fired."""
    ledger = _ledger(components=())
    with pytest.raises(LedgerError, match="no material components"):
        r3(ledger, "h", date(2025, 12, 31))


def test_r3_needs_a_preceding_observation_and_an_unchanged_value() -> None:
    changed = _ledger(
        marks=(MarkObservation("h", "p", Decimal(100)), MarkObservation("h", "p0", Decimal(90)))
    )
    assert r3(changed, "h", date(2025, 12, 31)).note == "value changed since 2024-12-31"

    first = _ledger(marks=(MarkObservation("h", "p", Decimal(100)),))
    assert r3(first, "h", date(2025, 12, 31)).note == "no preceding mark observation"

    unmarked = _ledger(marks=())
    assert r3(unmarked, "h", date(2025, 12, 31)).note == "no mark at this date"


def test_an_approved_management_assessment_closes_the_calibration_gap() -> None:
    """V12 · and only an APPROVED one. A draft leaves it open, which is the
    distinction PBC ¶3 turns on: the auditor asks for management's conclusion,
    not for its intention to reach one."""
    from policy.inputs import ManagementAssessment

    draft = _ledger(assessments=(ManagementAssessment("h", date(2025, 12, 31), "draft"),))
    approved = _ledger(assessments=(ManagementAssessment("h", date(2025, 12, 31), "approved"),))
    assert r3(draft, "h", date(2025, 12, 31)).verdict is RequirementVerdict.MISSING
    assert r3(approved, "h", date(2025, 12, 31)).verdict is RequirementVerdict.SUFFICIENT


def test_a_row_whose_every_requirement_is_inapplicable_is_not_invented_as_missing() -> None:
    ledger = _ledger(lots=(), marks=())
    assert assess_row(ledger, "h", date(2025, 12, 31)).verdict is RequirementVerdict.NOT_APPLICABLE


def test_month_arithmetic_clamps_the_day_rather_than_overflowing() -> None:
    """31 March minus one month is 28 February, not 31 February."""
    assert minus_months(date(2025, 3, 31), 1) == date(2025, 2, 28)
    assert minus_months(date(2025, 1, 15), 12) == date(2024, 1, 15)
    assert minus_months(date(2024, 2, 29), 12) == date(2023, 2, 28)


def test_reducing_an_empty_verdict_list_refuses() -> None:
    with pytest.raises(ReducerError):
        worst([])
    with pytest.raises(ReducerError):
        best([])


def test_support_before_the_measurement_date_is_the_only_support_counted() -> None:
    """A memo dated after the date under audit cannot make a mark current at it."""
    component = MaterialComponent(
        "h",
        "valuation",
        support=(SupportObservation(date(2026, 6, 1), claim_id="future"),),
    )
    assert component.latest_on_or_before(date(2025, 12, 31)) is None
    assert component.latest_on_or_before(date(2026, 12, 31)) == date(2026, 6, 1)


# ── classification, where the workbook is ambiguous ──────────────────────
def test_two_position_type_signals_on_one_sheet_refuse() -> None:
    """A position is one kind. Two signals is a contradiction in the source, not
    a precedence question to settle by ordering the patterns."""
    notes = [_note("Indirect exposure via feeder vehicle"), _note("since public listing")]
    with pytest.raises(ClassificationError, match="more than one position type"):
        position_type(notes, [_tranche()])


def test_a_sheet_with_no_signal_reads_as_direct_equity_and_says_why() -> None:
    read = position_type([_note("Supporting documentation:")], [_tranche()])
    assert read.value == PositionType.DIRECT_EQUITY.value
    assert "no line names a feeder" in read.source_text


def test_two_lines_naming_two_classes_for_one_tranche_refuse_to_choose() -> None:
    """Picking the first would be a coin flip recorded as a fact."""
    notes = [_note("Series A - SPA (January 2024)"), _note("Series B - SPA (January 2024)")]
    read = security_class(_tranche(acquired=date(2024, 1, 1)), notes)
    assert read.value == "unstated"


def test_a_recapitalisation_without_a_named_class_refuses() -> None:
    """The shares would reach the ledger as a class nobody named, and INV-17
    compares the class HELD against the class PRICED."""
    recap = _note("Post-Recap", ("Post-Recap", None, "$10M", 0.4, 875000, "9/30/2025"))
    with pytest.raises(ClassificationError, match="names the class converted into"):
        recapitalisation([recap])


def test_a_recapitalisation_missing_its_figures_refuses() -> None:
    recap = _note("Post-Recap", ("Post-Recap", None, "$10M", None, None, None))
    with pytest.raises(ClassificationError, match="not recordable"):
        recapitalisation([recap])


def test_a_sheet_with_no_recapitalisation_row_yields_none() -> None:
    assert recapitalisation([_note("Supporting documentation:")]) is None


def test_a_recapitalisation_row_too_short_to_read_is_skipped() -> None:
    assert recapitalisation([_note("Post-Recap", ("Post-Recap",))]) is None


def test_an_instrument_named_by_its_type_cell_wins_over_a_dated_line() -> None:
    """The Mom Project's third row IS a convertible note; a Series C line dated
    the same year does not make it equity."""
    read = security_class(
        _tranche(kind="Fund (Conv. Note)"), [_note("Series C - Term Sheet (2024)")]
    )
    assert read.value == "conv_note"


def test_a_listed_position_holds_common_stock() -> None:
    read = security_class(
        _tranche(),
        [_note("Marked at quoted closing price at each measurement date")],
        PositionType.PUBLIC_LISTED,
    )
    assert read.value == "common"


def test_a_class_stated_only_by_an_executed_document_is_taken_from_it() -> None:
    read = security_class(_tranche(), [], from_documents={"X": "series_b"})
    assert read == Reading("series_b", "executed transaction document", "")


# ── the seeder refuses rather than half-writing ─────────────────────────
@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_seeder_refuses_a_ledger_whose_claims_it_cannot_account_for() -> None:
    """Every claim about a holding this file speaks for must be declared —
    including the seven relied upon for nothing.

    That is the whole point of the completeness check: a document can be read,
    classified and stored, and then relied upon for no requirement without
    anyone deciding that. Silence would look identical to a decision.

    Run against an empty schema, where nothing is declared, so the refusal is
    observed rather than assumed. It also proves the dry run writes nothing:
    the error leaves the transaction rolled back with no partial seed behind
    it, which is the failure psycopg's committing-outermost-block caused twice
    in two other loaders on the same day.
    """
    import psycopg

    from ingest import policy_seed

    with psycopg.connect(str(DSN)) as conn:
        conn.execute("set search_path to public")
        before = conn.execute("select count(*) from claim_requirement").fetchone()
    with pytest.raises(policy_seed.SeedError, match="relied upon for nothing must say so"):
        policy_seed.main(["--schema", "public"])
    with psycopg.connect(str(DSN)) as conn:
        conn.execute("set search_path to public")
        after = conn.execute("select count(*) from claim_requirement").fetchone()
    assert before is not None and after is not None
    assert after[0] == before[0], "a refused seed left rows behind"


def test_the_seeder_reports_a_missing_dsn_rather_than_connecting_to_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingest import policy_seed

    monkeypatch.setenv("MIGRATION_DATABASE_URL", "")
    monkeypatch.setenv("DATABASE_URL", "")
    assert policy_seed.main([]) == 1


@needs_workbooks
def test_the_findings_snapshot_regenerates_to_what_is_committed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--check` is how a change in the reconciler's reach shows up in CI.

    Run through `main` rather than through `build`, because the drift report is
    the part that has to work: a snapshot guard that cannot say "stale" is a
    guard that always passes. Both verdicts are exercised — the committed file,
    and a deliberately corrupted one."""
    import json

    from ingest.trackers import snapshot

    assert snapshot.build() == json.loads(snapshot.SNAPSHOT.read_text())

    monkeypatch.setattr("sys.argv", ["snapshot", "--check"])
    assert snapshot.main() == 0

    drifted = tmp = snapshot.SNAPSHOT.parent / "real_findings.drifted.json"
    drifted.write_text('{"finding_count": 0}\n')
    try:
        monkeypatch.setattr(snapshot, "SNAPSHOT", drifted)
        assert snapshot.main() == 1, "a drifted snapshot must report stale"
        monkeypatch.setattr(snapshot, "SNAPSHOT", drifted.parent / "absent.json")
        assert snapshot.main() == 1, "an absent snapshot must not read as agreement"
    finally:
        tmp.unlink(missing_ok=True)


def test_the_snapshot_does_nothing_where_the_workbooks_are_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fund's private material will never be in CI, so absence is correct
    rather than a failure — the one skip this project allows."""
    from ingest.trackers import snapshot

    monkeypatch.setattr(snapshot, "workbooks_present", lambda: False)
    monkeypatch.setattr("sys.argv", ["snapshot"])
    assert snapshot.main() == 0


# ── R3 and INV-16, without the corpus ────────────────────────────────────
#
# These five rules are exercised on the fund's real positions by
# `test_policy_vs_oracle.py`, which needs both a DSN and the workbooks and
# therefore skips in CI. A guard that only runs where the private material
# lives has not been proved — Step 2 made that a written rule after finding it
# seven times — so each also has a synthetic case here.
def _r3_ledger(support: date | None, *, prior_scope: AuditScope = AuditScope.PACKET) -> Ledger:
    """One holding, unchanged at 100, with its single component last supported
    on `support` (or never)."""
    prior = Period("p0", "f", date(2024, 12, 31), prior_scope)
    observations = () if support is None else (SupportObservation(support, claim_id="c"),)
    return _ledger(
        periods={"p": PERIOD, "p0": prior},
        components=(MaterialComponent("h", "valuation", support=observations),),
    )


def test_support_exactly_twelve_months_old_is_not_stale() -> None:
    """The boundary is strict, and it is one character: `<`, not `<=`.

    Capsule is the corpus case — a memo dated 12/31/2022 read at 12/31/2023 is
    exactly twelve months old and R3 must not fire. A day older and it must.
    """
    on = date(2025, 12, 31)
    assert r3(_r3_ledger(date(2024, 12, 31)), "h", on).stale_components == ()
    assert r3(_r3_ledger(date(2024, 12, 30)), "h", on).stale_components != ()
    assert r3(_r3_ledger(None), "h", on).stale_components != (), "absent support counts as stale"


def test_a_lineage_only_observation_may_prove_a_mark_did_not_move() -> None:
    """Limb (a) is the immediately preceding mark OBSERVATION, which may fall in
    a lineage-only period.

    It read "audit measurement date" through r4, which made R3 structurally
    unable to fire at a fund's FIRST packet date — so Roofstock, flat at the
    same mark since November 2021, escaped calibration at FY2023, which is
    exactly the position the letter's ¶3 addresses. Whether a date is in packet
    scope and whether a prior observation proves the mark did not move are two
    questions, and they were one field.
    """
    outcome = r3(_r3_ledger(None, prior_scope=AuditScope.LINEAGE_ONLY), "h", date(2025, 12, 31))
    assert outcome.unchanged_since == date(2024, 12, 31)
    assert outcome.verdict is RequirementVerdict.MISSING


def test_a_memos_own_reliance_window_closes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """INV-16 outranks the matrix. A third-party memo is `sufficient` only
    within the window its own text states — Capsule's forbids later reliance in
    a sentence that is itself a cited fact, so the boundary is traceable to the
    source rather than to a setting."""
    memo = _claim(
        "memo",
        None,
        None,
        source_class=SourceClass.THIRD_PARTY_VALUATION_MEMO,
        execution_status=ExecutionStatus.NOT_APPLICABLE,
        issued_date=date(2024, 12, 31),
        applicable_from=date(2024, 12, 31),
        applicable_to=date(2024, 12, 31),
    )
    ledger = _ledger(claims=(memo,))
    assert r2(ledger, "h", date(2024, 12, 31)).verdict is RequirementVerdict.SUFFICIENT
    later = r2(ledger, "h", date(2025, 12, 31))
    assert later.relied_on == (), "the memo forbids reliance after its own date"
    assert later.verdict is RequirementVerdict.MISSING


def test_supersession_is_recorded_and_never_inferred_from_dates() -> None:
    """Dream is the corpus case: a pro forma cap table (11/14) and the CFO's
    closing notice (11/17), both about the same Series B.

    Inferring supersession within a priced class would drop the cap table and
    take the `pro_forma` label with it. Two claims about one round are usually
    corroboration; only the fund knows when one replaces another, and when it
    does it says so with `supersedes_claim_id`."""
    early = _claim("early", "series_a", "10.00", issued_date=date(2025, 1, 1))
    late = _claim("late", "series_a", "10.00", issued_date=date(2025, 6, 1))
    both = r2(_ledger(claims=(early, late)), "h", date(2025, 12, 31))
    assert both.relied_on == ("early", "late")

    replacing = _claim(
        "late", "series_a", "10.00", issued_date=date(2025, 6, 1), supersedes_claim_id="early"
    )
    assert r2(_ledger(claims=(early, replacing)), "h", date(2025, 12, 31)).relied_on == ("late",)


def test_cross_class_is_symmetric_and_catches_the_held_minus_priced_direction() -> None:
    """INV-17 · the test is set EQUALITY, and both one-way versions were wrong.

    Here two classes are held and one claim prices one of them. Asking only "is
    the priced class held?" answers yes — while the other class's shares are
    being marked at a price established for something else. That is the exact
    case the invariant was written for."""
    two_lots = (
        Lot("a", "h", "series_a", 100, Decimal(1), Decimal(100), "USD", date(2020, 1, 1)),
        Lot("b", "h", "series_b", 100, Decimal(1), Decimal(100), "USD", date(2020, 1, 1)),
    )
    outcome = r2(
        _ledger(lots=two_lots, claims=(_claim("a", "series_a", "10.00"),)), "h", date(2025, 12, 31)
    )
    assert outcome.cross_class is True
    assert "CROSS_CLASS_POLICY_DECISION_REQUIRED" in outcome.reasons


def test_expired_support_is_not_reported_as_never_having_existed(policy_ledger: Ledger) -> None:
    """Two holdings read `R2 = missing` at 25Q4 and mean opposite things.

    Because Market has no portfolio document of any kind. Moonfare has two, and
    its FY2023 memo closes its own window in its own words — "should not be
    relied upon for subsequent measurement dates without update" (INV-16).

    Both rendered as `missing` with `REQUEST_FROM_COMPANY` beside them, which
    tells an auditor to go and find something for a fund that already holds the
    thing and needs it REFRESHED. The verdict is right in both cases and is not
    what this pins: `missing` is correct because an expired memo is not weaker
    support, it is no support. What must differ is the reason and the action,
    because they are letters to different people.
    """
    on = date(2025, 12, 31)
    moonfare = _r2(policy_ledger, "fund_ii_moonfare", on)
    because = _r2(policy_ledger, "fund_ii_because_market", on)

    assert moonfare.verdict is because.verdict is RequirementVerdict.MISSING

    assert "SUPPORT_OUTSIDE_ITS_OWN_RELIANCE_WINDOW" in moonfare.reasons
    assert "REQUEST_UPDATED_VALUATION" in moonfare.next_actions

    assert "SUPPORT_OUTSIDE_ITS_OWN_RELIANCE_WINDOW" not in because.reasons
    assert "REQUEST_UPDATED_VALUATION" not in because.next_actions
    assert "REQUEST_FROM_COMPANY" in because.next_actions

    # The distinction must be earned by the evidence, not by the holding's name.
    assert any(
        c.holding_id == "fund_ii_moonfare"
        and RequirementCode.R2 in c.requirements
        and c.applicable_to is not None
        and c.applicable_to < on
        for c in policy_ledger.claims
    ), "Moonfare must actually hold expired R2 support for this test to mean anything"
    assert not any(c.holding_id == "fund_ii_because_market" for c in policy_ledger.claims), (
        "Because Market must actually hold no claims at all"
    )


def _r2(ledger: Ledger, holding_id: str, on: date) -> object:
    outcome = assess_row(ledger, holding_id, on)
    return next(o for code, o in outcome.outcomes.items() if code is RequirementCode.R2)
