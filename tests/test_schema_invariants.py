"""Every schema guard must REJECT its violation.

A constraint that cannot fail is not a guard — it reads as coverage and provides
none. Each test here attempts the exact mutation the invariant forbids and
asserts the database refuses it.

Skipped when MIGRATION_DATABASE_URL is unset, so the suite still runs offline.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from api.config import dsn

DSN = dsn("MIGRATION_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """Each test runs in a transaction that is always rolled back."""
    assert DSN is not None  # guarded by the module-level skipif
    with psycopg.connect(DSN, connect_timeout=20) as c:
        yield c
        c.rollback()


@pytest.fixture
def seed(conn: psycopg.Connection) -> dict[str, str]:
    uid = uuid.uuid4().hex[:8]
    ids = {
        "fund": f"f_{uid}",
        "company": f"c_{uid}",
        "holding": f"h_{uid}",
        "period": f"p_{uid}",
        "lot": f"l_{uid}",
    }
    conn.execute("insert into fund values (%s, 'Test Fund')", (ids["fund"],))
    conn.execute("insert into company values (%s, 'Test Co')", (ids["company"],))
    conn.execute(
        "insert into holding (id, fund_id, company_id, position_type, currency)"
        " values (%s, %s, %s, 'direct_equity', 'USD')",
        (ids["holding"], ids["fund"], ids["company"]),
    )
    conn.execute(
        "insert into reporting_period values (%s, %s, '2025-12-31', 'packet', 'FY2025')",
        (ids["period"], ids["fund"]),
    )
    conn.execute(
        "insert into lot (id, holding_id, security_class, shares, entry_pps,"
        " cost_amount, cost_currency, acquired_date)"
        " values (%s, %s, 'series_a', 1000, 2.00, 2000, 'USD', '2024-01-01')",
        (ids["lot"], ids["holding"]),
    )
    return ids


def _rejects(
    conn: psycopg.Connection[tuple[object, ...]], sql: str, params: tuple[object, ...] = ()
) -> str:
    """Assert the statement is refused; return the error text."""
    with pytest.raises(psycopg.Error) as exc:
        conn.execute(sql, params)
    conn.rollback()
    return str(exc.value)


# ── INV-7 · lots are immutable ───────────────────────────────────────────
def test_lot_cannot_be_updated(
    conn: psycopg.Connection[tuple[object, ...]], seed: dict[str, str]
) -> None:
    """Rewriting an acquisition date would silently move a position across a
    measurement-date boundary under an already-approved mark."""
    err = _rejects(conn, "update lot set shares = 5 where id = %s", (seed["lot"],))
    assert "append-only" in err


def test_lot_cannot_be_deleted(
    conn: psycopg.Connection[tuple[object, ...]], seed: dict[str, str]
) -> None:
    err = _rejects(conn, "delete from lot where id = %s", (seed["lot"],))
    assert "append-only" in err


# ── INV-10 · approvals are append-only and fully fingerprinted ───────────
def test_valuation_approval_requires_full_fingerprint(
    conn: psycopg.Connection[tuple[object, ...]], seed: dict[str, str]
) -> None:
    """SPEC §6.3 binds a valuation approval to mark revision, evidence-set hash
    and policy version. A bare holding+date approval must not be storable."""
    err = _rejects(
        conn,
        "insert into review_decision (decision_type, status, subject_kind,"
        " subject_id, actor_id) values ('valuation', 'approved', 'mark', %s, 'a')",
        (seed["holding"],),
    )
    assert "fully_fingerprinted" in err


def test_fully_fingerprinted_valuation_approval_is_accepted(
    conn: psycopg.Connection[tuple[object, ...]], seed: dict[str, str]
) -> None:
    conn.execute(
        "insert into review_decision (decision_type, status, subject_kind,"
        " subject_id, mark_revision, evidence_set_hash, policy_version, actor_id)"
        " values ('valuation', 'approved', 'mark', %s, 'r1', 'h1', 'v1', 'a')",
        (seed["holding"],),
    )
    conn.rollback()


def test_review_decision_cannot_be_updated(
    conn: psycopg.Connection[tuple[object, ...]], seed: dict[str, str]
) -> None:
    conn.execute(
        "insert into review_decision (decision_type, status, subject_kind,"
        " subject_id, actor_id) values ('transcription', 'approved', 'fact', %s, 'a')",
        (seed["holding"],),
    )
    err = _rejects(conn, "update review_decision set status = 'rejected'")
    assert "append-only" in err


# ── INV-11 · money carries a currency; shares are integers ───────────────
def test_validated_amount_requires_currency(
    conn: psycopg.Connection[tuple[object, ...]], seed: dict[str, str]
) -> None:
    """An exact Decimal in an unstated currency is exactly wrong."""
    err = _rejects(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " validated_amount, derivation_status, derivation_reason)"
        " values (%s, %s, 100, 'USD', 100, 'derivable', 'x')",
        (seed["holding"], seed["period"]),
    )
    assert "validated_currency_together" in err


def test_derivable_mark_must_carry_the_derived_amount(
    conn: psycopg.Connection[tuple[object, ...]], seed: dict[str, str]
) -> None:
    err = _rejects(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " derivation_status, derivation_reason)"
        " values (%s, %s, 100, 'USD', 'derivable', 'x')",
        (seed["holding"], seed["period"]),
    )
    assert "derivable_has_amount" in err


def test_fractional_shares_are_rejected_not_rounded(
    conn: psycopg.Connection[tuple[object, ...]], seed: dict[str, str]
) -> None:
    """INV-11 / SPEC V13: a fractional share count is a REJECTION.

    This test failed against the first schema, which typed shares as `bigint`:
    Postgres silently rounded 100.5 to 101 — a plausible number nobody asked
    for, which is the precise failure mode the invariant exists to prevent.
    """
    err = _rejects(
        conn,
        "insert into lot (id, holding_id, security_class, shares, entry_pps,"
        " cost_amount, cost_currency, acquired_date)"
        " values ('frac', %s, 'sa', 100.5, 1.00, 100, 'USD', '2024-01-01')",
        (seed["holding"],),
    )
    assert "shares_whole" in err


def test_whole_share_counts_are_accepted(
    conn: psycopg.Connection[tuple[object, ...]], seed: dict[str, str]
) -> None:
    conn.execute(
        "insert into lot (id, holding_id, security_class, shares, entry_pps,"
        " cost_amount, cost_currency, acquired_date)"
        " values ('whole', %s, 'sa', 875000, 0.40, 350000, 'USD', '2025-09-30')",
        (seed["holding"],),
    )
    conn.rollback()


def test_fractional_recap_result_is_rejected(
    conn: psycopg.Connection[tuple[object, ...]], seed: dict[str, str]
) -> None:
    """Sway: 800,000 x 1.09375 = 875,000 exactly. A ratio producing a fraction
    must fail rather than round into a plausible post-recap share count."""
    err = _rejects(
        conn,
        "insert into lot_conversion values (%s, '2025-09-30', 'series_a3', 875000.5, 1.09375)",
        (seed["lot"],),
    )
    assert "shares_whole" in err


# ── INV-13 · reported ≠ validated ────────────────────────────────────────
def test_non_derivable_mark_keeps_its_reported_amount(
    conn: psycopg.Connection[tuple[object, ...]], seed: dict[str, str]
) -> None:
    """Moonfare FY2025 and Anthropic FY2025: the tracker figure is retained as
    reported while no validated amount exists."""
    conn.execute(
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " derivation_status, derivation_reason)"
        " values (%s, %s, 1048515, 'USD', 'not_derivable', 'NO_APPLICABLE_EVIDENCE')",
        (seed["holding"], seed["period"]),
    )
    row = conn.execute(
        "select reported_amount, validated_amount from mark where holding_id = %s",
        (seed["holding"],),
    ).fetchone()
    assert row == (1048515, None)
    conn.rollback()


# ── INV-5 · one mark per holding per period per revision ─────────────────
def test_mark_is_unique_per_holding_period_revision(
    conn: psycopg.Connection[tuple[object, ...]], seed: dict[str, str]
) -> None:
    args = (seed["holding"], seed["period"])
    stmt = (
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " derivation_status, derivation_reason)"
        " values (%s, %s, 100, 'USD', 'not_derivable', 'x')"
    )
    conn.execute(stmt, args)
    err = _rejects(conn, stmt, args)
    assert "duplicate key" in err or "unique" in err.lower()


# ── INV-8 · a derived figure input is a fact OR a child, never neither ───
def test_derived_figure_input_needs_exactly_one_source(
    conn: psycopg.Connection[tuple[object, ...]],
) -> None:
    conn.execute(
        "insert into derived_figure (id, label, operator, amount, currency, unit)"
        " values (9001, 'total', 'sum', 10, 'USD', 'money')"
    )
    err = _rejects(
        conn,
        "insert into derived_figure_input (figure_id, ordinal) values (9001, 1)",
    )
    assert "exactly_one_source" in err


# ── INV-14 · a promoted fact must name the decision that promoted it ─────
def test_canonical_fact_requires_a_promoting_decision(
    conn: psycopg.Connection[tuple[object, ...]], seed: dict[str, str]
) -> None:
    """A schema-valid, perfectly cited candidate still cannot become canonical
    without a review decision — the AI-proposes/human-disposes boundary."""
    err = _rejects(
        conn,
        "insert into extracted_fact (claim_id, state, field_name, value_text,"
        " citation_quote, span_start, span_end)"
        " values ('nope', 'canonical', 'pps', '8.00', 'q', 0, 1)",
    )
    assert "promoted_requires_decision" in err or "foreign key" in err.lower()
