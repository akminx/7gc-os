"""Build a `policy.inputs.Ledger` out of Postgres.

The only module in `policy/` that knows SQL. Everything else is a pure function
of the values this produces, which is what lets §7's rules be exercised without
a database — and what stops the rules and the reader from being tested as one
thing, where a defect in either reads as agreement.

Nothing here decides anything. Every judgement was recorded when the rows were
written: which requirement a claim answers (`claim_requirement`), why a document
is absent (`document_gap.kind`), what a mark is made of
(`valuation_component`). This reads them back.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import psycopg

from packages.contracts.enums import (
    AuditScope,
    ExecutionStatus,
    GapKind,
    PositionType,
    RequirementCode,
    SourceClass,
)
from policy.inputs import (
    Conversion,
    EvidenceClaim,
    Gap,
    Holding,
    Ledger,
    Lot,
    ManagementAssessment,
    MarkObservation,
    MaterialComponent,
    Period,
    PolicyDecision,
    SupportObservation,
)

Conn = psycopg.Connection[tuple[object, ...]]


def _s(v: object) -> str:
    assert isinstance(v, str)
    return v


def _d(v: object) -> date:
    assert isinstance(v, date)
    return v


def _od(v: object) -> date | None:
    assert v is None or isinstance(v, date)
    return v


def _dec(v: object) -> Decimal:
    assert isinstance(v, Decimal | int | str)
    return Decimal(str(v))


def _odec(v: object) -> Decimal | None:
    return None if v is None else _dec(v)


def _oint(v: object) -> int | None:
    if v is None:
        return None
    number = _dec(v)
    assert number == number.to_integral_value(), f"share count {number} is not whole"
    return int(number)


def load(conn: Conn) -> Ledger:
    """Everything the policy layer reads, in one pass per table."""
    holdings = {
        _s(r[0]): Holding(_s(r[0]), _s(r[1]), PositionType(_s(r[2])))
        for r in conn.execute("select id, fund_id, position_type from holding").fetchall()
    }
    periods = {
        _s(r[0]): Period(_s(r[0]), _s(r[1]), _d(r[2]), AuditScope(_s(r[3])))
        for r in conn.execute(
            "select id, fund_id, period_date, audit_scope from reporting_period"
        ).fetchall()
    }

    conversions = {
        _s(r[0]): Conversion(_d(r[1]), _s(r[2]), int(_dec(r[3])), _dec(r[4]))
        for r in conn.execute(
            "select lot_id, effective_date, to_security_class, to_shares, exchange_ratio"
            " from lot_conversion"
        ).fetchall()
    }
    lots = tuple(
        Lot(
            id=_s(r[0]),
            holding_id=_s(r[1]),
            security_class=_s(r[2]),
            shares=_oint(r[3]),
            entry_pps=_odec(r[4]),
            cost_amount=_dec(r[5]),
            cost_currency=_s(r[6]),
            acquired_date=_d(r[7]),
            realized_date=_od(r[8]),
            conversion=conversions.get(_s(r[0])),
        )
        for r in conn.execute(
            "select id, holding_id, security_class, shares, entry_pps, cost_amount,"
            " cost_currency, acquired_date, realized_date from lot order by id"
        ).fetchall()
    )

    # A claim relied upon for nothing still loads, with an empty requirement
    # set. It is evidence the fund holds and the workspace shows it; what it
    # does not do is answer a PBC requirement, and those are different facts.
    reliance: dict[str, set[RequirementCode]] = {}
    for r in conn.execute("select claim_id, requirement from claim_requirement").fetchall():
        reliance.setdefault(_s(r[0]), set()).add(RequirementCode(_s(r[1])))

    claims = tuple(
        EvidenceClaim(
            id=_s(r[0]),
            holding_id=_s(r[1]),
            source_class=SourceClass(_s(r[2])),
            execution_status=ExecutionStatus(_s(r[3])),
            issued_date=_d(r[4]),
            applicable_from=_d(r[5]),
            applicable_to=_od(r[6]),
            received_date=_od(r[7]),
            priced_class=None if r[8] is None else _s(r[8]),
            price_per_share=_odec(r[9]),
            stated_amount=_odec(r[10]),
            stated_currency=None if r[11] is None else _s(r[11]),
            supersedes_claim_id=None if r[12] is None else _s(r[12]),
            requirements=frozenset(reliance.get(_s(r[0]), set())),
        )
        for r in conn.execute(
            "select id, holding_id, source_class, execution_status, issued_date,"
            " applicable_from, applicable_to, received_date, priced_class, price_per_share,"
            " stated_amount, stated_currency, supersedes_claim_id from claim order by id"
        ).fetchall()
    )

    gaps = tuple(
        Gap(
            holding_id=_s(r[0]),
            requirement=RequirementCode(_s(r[1])),
            kind=GapKind(_s(r[3])),
            missing_document=_s(r[4]),
            source_quote=_s(r[5]),
            security_class=None if r[2] is None else _s(r[2]),
        )
        for r in conn.execute(
            "select holding_id, requirement, security_class, kind, missing_document,"
            " source_quote from document_gap order by id"
        ).fetchall()
    )

    # One mark per (holding, period): the LATEST revision. Two revisions of the
    # same mark previously produced two observations, so a correction from 10 to
    # 20 read as a change and as no change at once, depending on which the
    # comparison picked up.
    marks = tuple(
        MarkObservation(_s(r[0]), _s(r[1]), _dec(r[2]))
        for r in conn.execute(
            "select distinct on (holding_id, period_id) holding_id, period_id, reported_amount"
            " from mark order by holding_id, period_id, revision desc"
        ).fetchall()
    )

    support: dict[int, list[SupportObservation]] = {}
    for r in conn.execute(
        "select component_id, claim_id, lot_id, supported_on from valuation_component_support"
        " order by supported_on, id"
    ).fetchall():
        support.setdefault(int(_dec(r[0])), []).append(
            SupportObservation(
                supported_on=_d(r[3]),
                claim_id=None if r[1] is None else _s(r[1]),
                lot_id=None if r[2] is None else _s(r[2]),
            )
        )
    components = tuple(
        MaterialComponent(
            holding_id=_s(r[1]),
            name=_s(r[2]),
            support=tuple(support.get(int(_dec(r[0])), ())),
        )
        for r in conn.execute(
            "select id, holding_id, component from valuation_component"
            " order by holding_id, component"
        ).fetchall()
    )

    # Only a management-assessment decision closes R3, and only an approved one
    # (V12). A packet decision or a transcription approval is an approval and is
    # not this one — an earlier schema accepted any decision at all.
    # Bound through the MARK it was decided against, not by holding and date.
    # INV-5 · every mark revision needs its own dated assessment, so an
    # assessment that names only a holding and a date would survive a
    # re-marking of the very figure it assessed.
    assessments = tuple(
        ManagementAssessment(
            holding_id=_s(r[0]),
            measurement_date=_d(r[1]),
            status=_s(r[2]),
            mark_revision=f"{_s(r[0])}@{_d(r[1]).isoformat()}#r{int(_dec(r[3]))}",
            evidence_set_hash=None if r[4] is None else _s(r[4]),
        )
        for r in conn.execute(
            "select m.holding_id, rp.period_date, d.status, m.revision, d.policy_version"
            " from review_decision d"
            " join mark m on m.id = d.mark_id"
            " join reporting_period rp on rp.id = m.period_id"
            " where d.decision_type = 'management_assessment'"
        ).fetchall()
    )

    decisions = tuple(
        PolicyDecision(
            holding_id=_s(r[0]),
            measurement_date=_d(r[1]),
            method=f"{_s(r[2])}->{_s(r[3])}",
            citation=_s(r[4]),
        )
        for r in conn.execute(
            "select d.holding_id, rp.period_date, d.from_class, d.to_class, d.citation_quote"
            " from valuation_policy_decision d"
            " join reporting_period rp on rp.id = d.period_id"
        ).fetchall()
    )

    return Ledger(
        holdings=holdings,
        periods=periods,
        lots=lots,
        claims=claims,
        gaps=gaps,
        marks=marks,
        components=components,
        assessments=assessments,
        decisions=decisions,
    )
