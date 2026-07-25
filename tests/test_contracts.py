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

from packages.contracts.enums import PG_ENUMS
from packages.contracts.models import (
    ALWAYS_APPLICABLE,
    AuditScope,
    DerivationStatus,
    HoldingRow,
    Lot,
    Money,
    Packet,
    PacketTotals,
    Period,
    PositionType,
    RequirementAssessment,
    RequirementCode,
    RequirementVerdict,
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
        applicable=True,
        verdict=verdict,
        reason_codes=["X"] if adverse else [],
        policy_version="v1",
    )


def _row(assessments: list[RequirementAssessment], amount: str = "1000") -> HoldingRow:
    return HoldingRow(
        holding_id="h",
        company_name="Test Co",
        position_type=PositionType.DIRECT_EQUITY,
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
    bad: dict[str, object] = {"amount": 0.1 + 0.2, "currency": "USD"}
    with pytest.raises(ValidationError, match="must not be constructed from a float"):
        Money(**bad)


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
    assert row.unassessed_requirements == {RequirementCode.R2}


def test_a_row_with_every_always_applicable_requirement_sufficient_is_supported() -> None:
    row = _row([_assessment(c, RequirementVerdict.SUFFICIENT) for c in sorted(ALWAYS_APPLICABLE)])
    assert row.supported is True
    assert row.unassessed_requirements == set()


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
            applicable=True,
            verdict=RequirementVerdict.PARTIAL,
            policy_version="v1",
        )


def test_applicability_and_verdict_cannot_contradict() -> None:
    with pytest.raises(ValidationError, match="cannot be verdict not_applicable"):
        RequirementAssessment(
            requirement=RequirementCode.R3,
            applicable=True,
            verdict=RequirementVerdict.NOT_APPLICABLE,
            policy_version="v1",
        )
    with pytest.raises(ValidationError, match="must be verdict not_applicable"):
        RequirementAssessment(
            requirement=RequirementCode.R3,
            applicable=False,
            verdict=RequirementVerdict.SUFFICIENT,
            policy_version="v1",
        )


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
    assert totals.kind is TotalKind.TRACKER_REPORTED
    assert totals.amount == _usd("1000")
    assert totals.unsupported_amount == _usd("400")
    assert totals.unsupported_positions == 1
    assert totals.contains_unsupported_inputs is True


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
