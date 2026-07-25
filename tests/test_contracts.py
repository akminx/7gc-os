"""The contract layer must refuse what the schema refuses.

`enums.py` claimed in its own docstring that this file verified enum parity
against the live database. It did not exist. A stated guard that isn't real is
worse than no guard: it reads as coverage and nobody looks again. This is that
file, written after a cross-family review pointed out the claim was false.

Parity is checked in **both** directions, because a one-way check passes while
the schema quietly grows a label the contract cannot represent.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest
from pydantic import ValidationError

from packages.contracts.enums import (
    PG_ENUMS,
    AuditScope,
    DerivationStatus,
    PositionType,
    RequirementCode,
    RequirementVerdict,
)
from packages.contracts.models import (
    ALWAYS_APPLICABLE,
    HoldingRow,
    Lot,
    Money,
    Packet,
    PacketTotals,
    Period,
    RequirementAssessment,
    TotalKind,
)
from packages.contracts.models import Mark as MarkModel
from tests.schema_helpers import DSN


def _usd(v: str) -> Money:
    return Money(amount=Decimal(v), currency="USD")


def _mark(amount: str = "1000") -> MarkModel:
    return MarkModel(
        id=1,
        holding_id="h",
        period_id="p",
        reported=_usd(amount),
        derivation_status=DerivationStatus.NOT_DERIVABLE,
        derivation_reason="NO_APPLICABLE_EVIDENCE",
    )


def _assessment(code: RequirementCode, verdict: RequirementVerdict) -> RequirementAssessment:
    adverse = verdict is not RequirementVerdict.SUFFICIENT
    return RequirementAssessment(
        requirement=code,
        verdict=verdict,
        reason_codes=["X"] if adverse else [],
        policy_version="v1",
    )


def _row(
    assessments: list[RequirementAssessment], amount: str = "1000", held: bool = True
) -> HoldingRow:
    return HoldingRow(
        holding_id="h",
        company_name="Test Co",
        position_type=PositionType.DIRECT_EQUITY,
        held_at_date=held,
        mark=_mark(amount),
        assessments=assessments,
    )


# ── enum parity with the live schema ─────────────────────────────────────
@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_python_enums_match_the_postgres_types_in_both_directions() -> None:
    """A label added on either side must fail this test, not surface later as an
    unrepresentable value or a branch nothing reaches."""
    assert DSN is not None
    with psycopg.connect(DSN, connect_timeout=30) as conn:
        rows = conn.execute(
            "select t.typname, e.enumlabel from pg_type t"
            " join pg_enum e on e.enumtypid = t.oid"
            " join pg_namespace n on n.oid = t.typnamespace"
            " where n.nspname = 'public'"
        ).fetchall()
    db: dict[str, set[str]] = {}
    for typname, label in rows:
        db.setdefault(str(typname), set()).add(str(label))

    assert set(db) == set(PG_ENUMS), (
        f"enum types differ — only in DB: {set(db) - set(PG_ENUMS)}; "
        f"only in contracts: {set(PG_ENUMS) - set(db)}"
    )
    for name, enum_cls in PG_ENUMS.items():
        assert {m.value for m in enum_cls} == db[name], f"labels differ for {name}"


# ── INV-11 · money and shares ────────────────────────────────────────────
def test_money_refuses_a_float() -> None:
    """0.1 + 0.2 is already 0.30000000000000004 before it reaches the model."""
    bad = {"amount": 0.1 + 0.2, "currency": "USD"}
    with pytest.raises(ValidationError, match="must not be constructed from a float"):
        Money.model_validate(bad)


def test_money_refuses_cross_currency_addition() -> None:
    with pytest.raises(ValueError, match="refusing to add"):
        _ = _usd("1") + Money(amount=Decimal("1"), currency="EUR")


def test_lot_refuses_a_fractional_share_count() -> None:
    """Mirrors the DB `lot_shares_whole` CHECK, which the wire model previously
    did not, so the browser could carry a count the ledger calls impossible."""
    with pytest.raises(ValidationError, match="whole numbers"):
        Lot(
            id="l",
            holding_id="h",
            security_class="series_a",
            shares=Decimal("100.5"),
            entry_pps=Decimal("1"),
            cost=_usd("100"),
            acquired_date=date(2024, 1, 1),
        )


# ── SPEC §7.1–7.2 · supported means every applicable requirement ─────────
def test_a_row_missing_an_always_applicable_requirement_is_not_supported() -> None:
    """The defect: R1 sufficient, R2 absent, and the row read as supported —
    dropping an under-assessed mark out of the unsupported subtotal."""
    row = _row([_assessment(RequirementCode.R1, RequirementVerdict.SUFFICIENT)])
    assert row.supported is False
    assert set(row.unsupported_reasons) == {RequirementCode.R2}


def test_a_row_with_every_always_applicable_requirement_sufficient_is_supported() -> None:
    row = _row([_assessment(c, RequirementVerdict.SUFFICIENT) for c in sorted(ALWAYS_APPLICABLE)])
    assert row.supported is True
    assert row.unsupported_reasons == {}


def test_one_adverse_verdict_makes_a_row_unsupported() -> None:
    row = _row(
        [
            _assessment(RequirementCode.R1, RequirementVerdict.SUFFICIENT),
            _assessment(RequirementCode.R2, RequirementVerdict.MISSING),
        ]
    )
    assert row.supported is False


def test_an_empty_assessment_set_is_not_supported() -> None:
    assert _row([]).supported is False


def test_adverse_verdicts_must_carry_a_reason_code() -> None:
    with pytest.raises(ValidationError, match="at least one reason code"):
        RequirementAssessment(
            requirement=RequirementCode.R2,
            verdict=RequirementVerdict.PARTIAL,
            policy_version="v1",
        )


def test_an_always_applicable_code_cannot_be_not_applicable() -> None:
    """The contradiction that used to need a validator pair is now expressed in
    one field, so only this rule remains."""
    with pytest.raises(ValidationError, match="always applicable"):
        RequirementAssessment(
            requirement=RequirementCode.R1,
            verdict=RequirementVerdict.NOT_APPLICABLE,
            policy_version="v1",
        )


def test_a_conditional_requirement_may_be_not_applicable() -> None:
    a = RequirementAssessment(
        requirement=RequirementCode.R4,
        verdict=RequirementVerdict.NOT_APPLICABLE,
        policy_version="v1",
    )
    assert a.applicable is False


# ── INV-19 · a total states what it is a total of ────────────────────────
def _packet(rows: list[HoldingRow]) -> Packet:
    return Packet(
        fund_id="fund_ii",
        period=Period(
            id="p",
            fund_id="fund_ii",
            period_date=date(2025, 12, 31),
            audit_scope=AuditScope.PACKET,
            label="FY2025",
        ),
        rows=rows,
        schema_version="1",
        policy_version="v1",
        generated_at=datetime.now(UTC),
    )


def test_totals_are_typed_and_carry_their_unsupported_subtotal() -> None:
    supported = _row(
        [_assessment(c, RequirementVerdict.SUFFICIENT) for c in sorted(ALWAYS_APPLICABLE)], "600"
    )
    under_assessed = _row([_assessment(RequirementCode.R1, RequirementVerdict.SUFFICIENT)], "400")
    totals = _packet([supported, under_assessed]).totals()
    assert totals.kind is TotalKind.HELD_AT_DATE_REPORTED
    assert totals.amount == _usd("1000")
    assert totals.unsupported_amount == _usd("400")
    assert totals.unsupported_positions == 1
    assert totals.contains_unsupported_inputs is True


def test_an_unheld_row_is_a_packet_gap_and_not_an_input_to_the_total() -> None:
    """INV-7 / INV-19 · the two counts answer different questions.

    A position realised before the measurement date belongs in the packet — its
    evidence can still be incomplete — but it is not an input to a held-at-date
    total, so counting it among the unsupported INPUTS overstates how much of
    the figure is unsupported. `packet_gap_positions` is the superset that keeps
    it visible; `unsupported_positions` counts only what the number beside it is
    actually made of. A reader who adds the two double counts every held gap.
    """
    held_gap = _row([], "400")
    realised_gap = _row([], "999", held=False)
    totals = _packet([held_gap, realised_gap]).totals()
    assert totals.amount == _usd("400")
    assert totals.unsupported_amount == _usd("400")
    assert totals.unsupported_positions == 1
    assert totals.packet_gap_positions == 2


def test_an_approved_fair_value_total_cannot_contain_unsupported_inputs() -> None:
    """The contradiction the packet exists to refuse."""
    with pytest.raises(ValidationError, match="cannot include unsupported positions"):
        PacketTotals(
            kind=TotalKind.APPROVED_FAIR_VALUE,
            label="Approved fair value",
            amount=_usd("1000"),
            unsupported_amount=_usd("400"),
            unsupported_positions=1,
        )


def test_a_packet_with_no_rows_has_no_total() -> None:
    with pytest.raises(ValueError, match="no meaningful total"):
        _packet([]).totals()


def test_a_lineage_only_period_cannot_be_packeted() -> None:
    """INV-20 · it may serve as an R3 predecessor and never enter a packet."""
    with pytest.raises(ValidationError, match="cannot be packeted"):
        Packet(
            fund_id="fund_ii",
            period=Period(
                id="p",
                fund_id="fund_ii",
                period_date=date(2025, 6, 30),
                audit_scope=AuditScope.LINEAGE_ONLY,
                label="H1",
            ),
            rows=[],
            schema_version="1",
            policy_version="v1",
            generated_at=datetime.now(UTC),
        )


# ── the second round's own defects ───────────────────────────────────────
def test_an_always_applicable_requirement_cannot_be_marked_inapplicable() -> None:
    """The previous fix created this hole. Making `applicable=False` legal gave
    a route to mark R1 not-applicable, which the presence check accepted and the
    applicable filter then skipped — so nothing ever tested its verdict."""
    with pytest.raises(ValidationError, match="always applicable"):
        RequirementAssessment(
            requirement=RequirementCode.R1,
            verdict=RequirementVerdict.NOT_APPLICABLE,
            policy_version="v1",
        )


def test_supported_requires_applicability_not_mere_presence() -> None:
    """Two layers, both checked.

    A `RequirementAssessment` marking R1 inapplicable cannot even enter a
    `HoldingRow` — pydantic re-validates on nesting. And the `supported`
    predicate is independently correct: bypassing both validators with
    `model_construct` still yields `False`, so the guard is not merely
    unreachable.
    """
    r1_na = RequirementAssessment.model_construct(
        requirement=RequirementCode.R1,
        verdict=RequirementVerdict.NOT_APPLICABLE,
        reason_codes=[],
        next_actions=[],
        evidence=[],
        pro_forma=False,
        tracker_label=None,
        policy_version="v1",
    )
    r2 = _assessment(RequirementCode.R2, RequirementVerdict.SUFFICIENT)

    with pytest.raises(ValidationError, match="always applicable"):
        _row([r1_na, r2])

    row = HoldingRow.model_construct(
        holding_id="h",
        company_name="Test Co",
        position_type=PositionType.DIRECT_EQUITY,
        mark=_mark(),
        assessments=[r1_na, r2],
        gaps=[],
        approval=None,
    )
    assert row.supported is False
    assert RequirementCode.R1 in row.unsupported_reasons


def test_model_copy_cannot_smuggle_a_float_into_money() -> None:
    """`model_copy(update=...)` writes straight past every validator, so a guard
    that only runs at construction is not a guard."""
    with pytest.raises(ValidationError, match="must not be constructed from a float"):
        _usd("1").model_copy(update={"amount": 0.1 + 0.2})


def test_model_copy_cannot_make_an_approved_total_contain_unsupported_inputs() -> None:
    totals = PacketTotals(
        kind=TotalKind.TRACKER_REPORTED,
        label="Tracker-reported total, unaudited",
        amount=_usd("1000"),
        unsupported_amount=_usd("400"),
        unsupported_positions=1,
    )
    with pytest.raises(ValidationError, match="cannot include unsupported positions"):
        totals.model_copy(update={"kind": TotalKind.APPROVED_FAIR_VALUE})


def test_model_copy_without_updates_still_works() -> None:
    """The re-validation must not break the ordinary copy path."""
    m = _usd("1000")
    assert m.model_copy() == m
    assert m.model_copy(update={"amount": Decimal("2000")}).amount == Decimal("2000")


def test_supported_and_its_reasons_cannot_disagree() -> None:
    """Both derive from one function now. A previous version computed them
    separately and they disagreed about a present-but-inapplicable requirement.

    `model_construct` bypasses the validator on purpose: the predicate must be
    correct on its own, not merely unreachable.
    """
    r1_na = RequirementAssessment.model_construct(
        requirement=RequirementCode.R1,
        verdict=RequirementVerdict.NOT_APPLICABLE,
        reason_codes=[],
        next_actions=[],
        evidence=[],
        pro_forma=False,
        tracker_label=None,
        policy_version="v1",
    )
    row = HoldingRow.model_construct(
        holding_id="h",
        company_name="Test Co",
        position_type=PositionType.DIRECT_EQUITY,
        mark=_mark(),
        assessments=[r1_na, _assessment(RequirementCode.R2, RequirementVerdict.SUFFICIENT)],
        gaps=[],
        approval=None,
    )
    assert row.supported is False
    assert RequirementCode.R1 in row.unsupported_reasons
    assert bool(row.unsupported_reasons) is not row.supported


def test_an_adverse_conditional_requirement_also_makes_a_row_unsupported() -> None:
    """R1 and R2 are checked by name; every OTHER applicable requirement is
    checked by the sweep beside it. Mutation testing showed no test reached that
    sweep — every existing case failed on R1 or R2 first, so the branch could
    have been deleted silently."""
    row = _row(
        [
            _assessment(RequirementCode.R1, RequirementVerdict.SUFFICIENT),
            _assessment(RequirementCode.R2, RequirementVerdict.SUFFICIENT),
            _assessment(RequirementCode.R5, RequirementVerdict.INSUFFICIENT),
        ]
    )
    assert row.supported is False
    assert row.unsupported_reasons == {RequirementCode.R5: "insufficient"}


def test_not_assessed_blocks_support_and_is_not_read_as_inapplicable() -> None:
    """`not_assessed` sits outside the severity order (SPEC 6.2.1). Now that
    applicability is derived from the verdict, it must still count as applicable
    — otherwise an unassessed requirement would silently drop out of the support
    test, which is the failure the `applicable` field caused before it was
    removed."""
    a = RequirementAssessment(
        requirement=RequirementCode.R1,
        verdict=RequirementVerdict.NOT_ASSESSED,
        reason_codes=[],
        policy_version="v1",
    )
    assert a.applicable is True
    row = _row([a, _assessment(RequirementCode.R2, RequirementVerdict.SUFFICIENT)])
    assert row.supported is False
    assert row.unsupported_reasons[RequirementCode.R1] == "not_assessed"


def test_wire_money_refuses_what_the_database_refuses() -> None:
    """The database rejected 1109.999889 while this model still built it, so the
    residue could reach a packet total without touching a column. An invariant
    enforced on one side only is not enforced."""
    with pytest.raises(ValidationError, match="more than 4 decimal places"):
        Money(amount=Decimal("1109.999889"), currency="USD")
    assert Money(amount=Decimal("1109.9999"), currency="USD").amount == Decimal("1109.9999")
