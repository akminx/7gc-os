"""Read the packet out of the ledger. The demo's other half.

Until now `api/routes.py` served `packages/contracts/fixtures/dream.py` — one
holding, 5,000,000 — against a real Fund II 25Q4 of eight holdings and
25,648,515. The fixture proved the contract path before ingestion existed. This
replaces the source and keeps the shape, which is what the fixture was for.

Two things are read rather than recomputed, because the database already owns
them and a second derivation is a second answer:

* **held-at-date comes from `lot`** (INV-7), never from a flag on the holding. A
  holding with a lot acquired after the measurement date, or realised before it,
  is not held then — and that decides whether its mark enters the fund total.
* **the evidence is whatever `claim` holds**, with its citations. No assessment
  layer exists yet, so no requirement verdicts are invented: `assessments` is
  empty and every row therefore reads `not assessed` rather than `sufficient`.
  That is the honest state and the packet says so.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg

from packages.contracts.base import MONEY_SCALE, PPS_SCALE
from packages.contracts.citations import from_stored
from packages.contracts.enums import (
    AuditScope,
    DerivationStatus,
    ExecutionStatus,
    FactState,
    PositionType,
    SourceClass,
)
from packages.contracts.models import (
    Claim,
    HoldingRow,
    Mark,
    Money,
    Packet,
    Period,
    SourceFact,
)

Conn = psycopg.Connection[tuple[object, ...]]


# psycopg hands every column back as `object`. The alternative to narrowing is a
# suppression comment on each one, and the gate holds the suppression ceiling at
# zero — because suppressions are how a type check quietly stops checking.
def _s(v: object) -> str:
    assert isinstance(v, str)
    return v


def _i(v: object) -> int:
    assert isinstance(v, int)
    return v


def _date(v: object) -> date:
    assert isinstance(v, date)
    return v


def _opt_date(v: object) -> date | None:
    assert v is None or isinstance(v, date)
    return v


def _dec(v: object) -> Decimal:
    assert isinstance(v, Decimal | int | str)
    return Decimal(str(v))


def _money(amount: object, currency: object) -> Money:
    """A stored amount, back in its canonical scale.

    Money columns are `numeric(26,12)` while the canonical scale is 4 — declared
    wider on purpose, so an over-precise figure survives to be *rejected* by a
    CHECK instead of being silently rounded before any constraint can see it
    (SPEC §15). Postgres therefore hands back `8000000.000000000000`, and
    `Money` refuses it, because a value carrying more than four places is
    exactly what that guard exists to catch.

    Nothing had ever read money out of the database into the contract before, so
    the two sides had never met. Trailing zeros carry no information and are
    dropped; anything else is a figure the CHECK should have refused, and it
    raises rather than rounding — rounding here would be the silent
    re-quantisation the whole decimal policy exists to prevent.
    """
    return Money(amount=_at_scale(amount, MONEY_SCALE, "amount"), currency=_s(currency))


def _at_scale(value: object, scale: int, what: str) -> Decimal:
    """A stored figure, back in its canonical scale.

    Money is `numeric(26,12)` against a canonical scale of 4, and price per share
    the same column type against 6 — declared wider on purpose so an over-precise
    figure survives to be *rejected* by a CHECK instead of being silently rounded
    before any constraint can see it (SPEC §15). Postgres therefore returns
    `8.000000000000` for an $8.00 price and the contract refuses it.

    Trailing zeros carry no information and are dropped. Anything else is a
    figure the CHECK should have refused, and it raises rather than rounding —
    rounding here is the silent re-quantisation the decimal policy exists to
    prevent, and it would happen on the read path where nobody is looking.
    """
    raw = _dec(value)
    trimmed = raw.quantize(Decimal(1).scaleb(-scale))
    if trimmed != raw:
        raise ValueError(
            f"stored {what} {raw} carries more than {scale} significant decimal places; "
            "the database CHECK should have refused it"
        )
    return trimmed


SCHEMA_VERSION = "0.1.0"
POLICY_VERSION = "v1"


def _period(conn: Conn, fund_id: str, period_id: str) -> Period | None:
    row = conn.execute(
        "select id, fund_id, period_date, audit_scope, label from reporting_period"
        " where id = %s and fund_id = %s",
        (period_id, fund_id),
    ).fetchone()
    if row is None:
        return None
    return Period(
        id=_s(row[0]),
        fund_id=_s(row[1]),
        period_date=_date(row[2]),
        audit_scope=AuditScope(_s(row[3])),
        label=_s(row[4]),
    )


def claims_for(conn: Conn, holding_id: str) -> list[tuple[Claim, list[SourceFact]]]:
    """Every claim about this holding, with the citations its facts resolve to.

    The citation is what makes this an audit-support tool rather than a
    spreadsheet: an auditor following `span_start`/`span_end` into the stored
    `canonical_text` lands on the exact passage stating the figure, and
    `0008_citations_resolve.sql` is what guarantees they will.

    Facts, not bare citations. This returned a detached list of quotes, so the
    Anthropic article arrived as five passages with no way to tell which figure
    each one supported — and no value, no number and no state beside any of
    them. SPEC §6 models the chain as `claim → source_fact → citation`; sending
    only the ends of it leaves an auditor with quotations and no arithmetic.
    """
    rows = conn.execute(
        "select c.id, c.document_version_id, c.holding_id, c.claim_key, c.source_class,"
        " c.execution_status, c.issued_date, c.as_of_date, c.received_date, c.applicable_from,"
        " c.applicable_to, c.priced_class, c.price_per_share, c.stated_amount,"
        " c.stated_currency, c.supersedes_claim_id"
        " from claim c where c.holding_id = %s order by c.issued_date, c.id",
        (holding_id,),
    ).fetchall()
    out: list[tuple[Claim, list[SourceFact]]] = []
    for r in rows:
        claim = Claim(
            id=_s(r[0]),
            document_version_id=_s(r[1]),
            holding_id=_s(r[2]),
            claim_key=_s(r[3]),
            source_class=SourceClass(_s(r[4])),
            execution_status=ExecutionStatus(_s(r[5])),
            issued_date=_date(r[6]),
            as_of_date=_opt_date(r[7]),
            received_date=_opt_date(r[8]),
            applicable_from=_date(r[9]),
            applicable_to=_opt_date(r[10]),
            priced_class=None if r[11] is None else _s(r[11]),
            price_per_share=None if r[12] is None else _at_scale(r[12], PPS_SCALE, "price"),
            # The claim-level amount and the supersession link. Both are columns
            # on `claim` and both were missing from this SELECT, so the workspace
            # rendered "—" for a figure the ledger was holding.
            stated=None if r[13] is None else _money(r[13], r[14]),
            supersedes_claim_id=None if r[15] is None else _s(r[15]),
        )
        facts = conn.execute(
            "select id, field_name, value_text, value_numeric, state,"
            " citation_quote, span_start, span_end from extracted_fact"
            " where claim_id = %s order by field_name, id",
            (claim.id,),
        ).fetchall()
        out.append(
            (
                claim,
                [
                    SourceFact(
                        id=_i(f[0]),
                        claim_id=claim.id,
                        field_name=_s(f[1]),
                        value_text=_s(f[2]),
                        value_numeric=None if f[3] is None else _dec(f[3]),
                        state=FactState(_s(f[4])),
                        citation=from_stored(
                            document_version_id=claim.document_version_id,
                            quote=_s(f[5]),
                            span=(_i(f[6]), _i(f[7])),
                        ),
                    )
                    for f in facts
                ],
            )
        )
    return out


def packet(conn: Conn, fund_id: str, period_id: str) -> Packet | None:
    """The packet for one fund-period, assembled from the ledger."""
    period = _period(conn, fund_id, period_id)
    if period is None:
        return None

    # Membership comes from the LOTS, not from the marks. Anchoring on marks
    # dropped every realised position — the one class of row the audit letter
    # asks for by name (request 4, realised investments) — because a position
    # sold in May has no mark at the December measurement date. Jackpocket
    # vanished from Fund II FY2024 entirely, and `derived.json` says it belongs
    # there with `held_at_date: false` and no amount.
    #
    # A row is in the packet if it was held at the date, or if it was realised
    # during the period under audit ending at that date. `prior` is the previous
    # packet date for the fund, so a realisation is counted once, in the period
    # it happened, and does not follow the packet around forever.
    #
    # `distinct on (holding_id) ... order by revision desc` picks ONE mark. Two
    # revisions of the same mark previously produced two rows and summed both, so
    # correcting a valuation from 10 to 20 gave a total of 30.
    rows = conn.execute(
        "with bounds as ("
        "  select %s::date as measured,"
        "         (select max(rp.period_date) from reporting_period rp"
        "           where rp.fund_id = %s and rp.audit_scope = 'packet'"
        "             and rp.period_date < %s::date) as prior),"
        " positions as ("
        "  select h.id as holding_id, c.display_name, h.position_type,"
        "         coalesce(bool_or(l.acquired_date <= b.measured"
        "             and (l.realized_date is null or l.realized_date > b.measured)), false)"
        "           as held,"
        "         coalesce(bool_or(l.realized_date is not null"
        "             and l.realized_date <= b.measured"
        "             and (b.prior is null or l.realized_date > b.prior)), false)"
        "           as realised_in_period,"
        "         count(l.id) > 0 as has_lots"
        "    from holding h"
        "    join company c on c.id = h.company_id"
        "    left join lot l on l.holding_id = h.id"
        "    cross join bounds b"
        "   where h.fund_id = %s"
        "   group by h.id, c.display_name, h.position_type),"
        " current_mark as ("
        "  select distinct on (m.holding_id) m.holding_id, m.id, m.revision,"
        "         m.reported_amount, m.reported_currency, m.validated_amount,"
        "         m.validated_currency, m.derivation_status, m.derivation_reason"
        "    from mark m where m.period_id = %s"
        "   order by m.holding_id, m.revision desc)"
        " select p.holding_id, p.display_name, p.position_type,"
        # held-at-date comes from the lots (INV-7). Jio has none: its
        # acquisition cell reads `7/2020`, a month, and the mapper refuses to
        # invent the day that would decide this. With no lots to ask, the
        # presence of a mark AT THIS DATE is the tracker asserting the
        # position was held then — weaker evidence, and the only evidence
        # there is. Treating unknown as "not held" instead silently drops a
        # $1,000,000 position, which is precisely how Jio went missing from
        # every Fund I total once before.
        "        (p.held or (not p.has_lots and cm.id is not null)) as held,"
        "        cm.id, cm.revision, cm.reported_amount, cm.reported_currency,"
        "        cm.validated_amount, cm.validated_currency, cm.derivation_status,"
        "        cm.derivation_reason"
        "   from positions p left join current_mark cm on cm.holding_id = p.holding_id"
        "  where p.held or p.realised_in_period or cm.id is not null"
        "  order by p.display_name",
        (period.period_date, fund_id, period.period_date, fund_id, period_id),
    ).fetchall()

    built: list[HoldingRow] = []
    for r in rows:
        mark = None
        if r[4] is not None:
            # `validated_currency` is its own column. Reusing `reported_currency`
            # for it returned a EUR validated amount labelled USD — INV-11
            # breached in transit, with nothing on either side to notice.
            validated = None if r[8] is None else _money(r[8], r[9])
            mark = Mark(
                id=_i(r[4]),
                holding_id=_s(r[0]),
                period_id=period_id,
                revision=_i(r[5]),
                reported=_money(r[6], r[7]),
                validated=validated,
                derivation_status=DerivationStatus(_s(r[10])),
                derivation_reason=_s(r[11]),
            )
        built.append(
            HoldingRow(
                holding_id=_s(r[0]),
                company_name=_s(r[1]),
                position_type=PositionType(_s(r[2])),
                held_at_date=bool(r[3]),
                mark=mark,
                # No policy layer yet, so no verdicts are invented. Every row
                # reads `not assessed`, which is what it is.
                assessments=[],
                gaps=[],
            )
        )

    if not built:
        return None
    return Packet(
        fund_id=fund_id,
        period=period,
        rows=built,
        schema_version=SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        generated_at=datetime.now(UTC),
    )


def packet_periods(conn: Conn) -> list[tuple[str, str, str]]:
    """Every packet-scope fund-period, for the UI's own navigation.

    The dashboard hard-coded a fund and a period because no route listed them,
    which made a "dual-fund" screen single-fund in practice.
    """
    # Only fund-periods that a packet version was generated for. The dev
    # database also holds several hundred uuid-suffixed rows left behind by the
    # one schema test that must commit to fire the deferred triggers, and a bare
    # `audit_scope = 'packet'` listed all of them — 403 periods on a screen that
    # should show six.
    rows = conn.execute(
        "select rp.fund_id, rp.id, rp.label from reporting_period rp"
        " join packet_version pv on pv.period_id = rp.id"
        " where rp.audit_scope = 'packet'"
        " order by rp.fund_id, rp.period_date"
    ).fetchall()
    return [(_s(r[0]), _s(r[1]), _s(r[2])) for r in rows]
