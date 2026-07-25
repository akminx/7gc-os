"""Every schema guard must REJECT its violation.

A constraint that cannot fail is not a guard — it reads as coverage and provides
none. Each test here attempts the exact mutation the invariant forbids and
asserts the database refuses it, naming the constraint that did the refusing.

Assertions match a specific constraint name. An earlier version of
`test_canonical_fact_requires_a_promoting_decision` accepted either the check
constraint *or* a foreign-key error, and referenced a claim that did not exist —
so deleting the constraint it was named after would have left it green. Any
`or "foreign key" in err` disjunct here is a bug, not a convenience.

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

Conn = psycopg.Connection[tuple[object, ...]]


@pytest.fixture
def conn() -> Iterator[Conn]:
    """Each test runs in a transaction that is always rolled back."""
    assert DSN is not None  # guarded by the module-level skipif
    with psycopg.connect(DSN, connect_timeout=30) as c:
        yield c
        c.rollback()


@pytest.fixture
def seed(conn: Conn) -> dict[str, str]:
    """A complete, valid graph — so every rejection below is caused by the
    constraint under test rather than by a dangling reference."""
    u = uuid.uuid4().hex[:8]
    i = {k: f"{k}_{u}" for k in ("fund", "co", "h", "sf", "dv", "cl", "p", "lp", "lot")}
    stmts: list[tuple[str, tuple[object, ...]]] = [
        ("insert into fund values (%s, 'Test Fund')", (i["fund"],)),
        ("insert into company values (%s, 'Test Co')", (i["co"],)),
        (
            "insert into holding (id, fund_id, company_id, position_type, currency)"
            " values (%s, %s, %s, 'direct_equity', 'USD')",
            (i["h"], i["fund"], i["co"]),
        ),
        (
            "insert into source_file (id, filename, content_hash, byte_size, bytes)"
            " values (%s, 'f.pdf', %s, 1, '\\x00')",
            (i["sf"], f"hash_{u}"),
        ),
        (
            "insert into document_version"
            " (id, source_file_id, canonical_text, extractor, text_hash, page_count)"
            " values (%s, %s, 'text', 'pdftotext@1', %s, 1)",
            (i["dv"], i["sf"], f"th_{u}"),
        ),
        (
            "insert into claim (id, document_version_id, holding_id, claim_key,"
            " source_class, execution_status, issued_date, applicable_from, applicable_to)"
            " values (%s, %s, %s, 'k', 'company_communication', 'executed',"
            " '2025-06-30', '2025-01-01', '2026-12-31')",
            (i["cl"], i["dv"], i["h"]),
        ),
        (
            "insert into reporting_period values (%s, %s, '2025-12-31', 'packet', 'FY2025')",
            (i["p"], i["fund"]),
        ),
        (
            "insert into reporting_period values (%s, %s, '2025-06-30', 'lineage_only', 'H1')",
            (i["lp"], i["fund"]),
        ),
        (
            "insert into lot (id, holding_id, security_class, shares, entry_pps,"
            " cost_amount, cost_currency, acquired_date)"
            " values (%s, %s, 'series_a', 1000, 2.00, 2000, 'USD', '2024-01-01')",
            (i["lot"], i["h"]),
        ),
    ]
    for sql, params in stmts:
        conn.execute(sql, params)
    return i


def _rejects(conn: Conn, sql: str, params: tuple[object, ...] = ()) -> str:
    """Assert the statement is refused; return the error text."""
    with pytest.raises(psycopg.Error) as exc:
        conn.execute(sql, params)
    conn.rollback()
    return str(exc.value)


def _returned_id(conn: Conn, sql: str, params: tuple[object, ...] = ()) -> int:
    """Run an INSERT ... RETURNING id and hand back the id, typed."""
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    new_id = row[0]
    assert isinstance(new_id, int)
    return new_id


def _mark(conn: Conn, seed: dict[str, str], cross_class: bool = False) -> int:
    return _returned_id(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " derivation_status, derivation_reason, cross_class)"
        " values (%s, %s, 1000000, 'USD', 'not_derivable', 'x', %s) returning id",
        (seed["h"], seed["p"], cross_class),
    )


# ── INV-7 · lots are immutable ───────────────────────────────────────────
def test_lot_cannot_be_updated(conn: Conn, seed: dict[str, str]) -> None:
    """Rewriting an acquisition date would silently move a position across a
    measurement-date boundary under an already-approved mark."""
    assert "append-only" in _rejects(
        conn, "update lot set shares = 5 where id = %s", (seed["lot"],)
    )


def test_lot_cannot_be_deleted(conn: Conn, seed: dict[str, str]) -> None:
    assert "append-only" in _rejects(conn, "delete from lot where id = %s", (seed["lot"],))


# ── INV-10 · an approval binds immutable rows, not strings ───────────────
def test_valuation_approval_must_reference_a_real_mark(conn: Conn, seed: dict[str, str]) -> None:
    """The first schema accepted three arbitrary strings as a "fingerprint", so
    an approval bound nothing at all."""
    assert "valuation_approval_binds_mark" in _rejects(
        conn,
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " policy_version, actor_id) values ('valuation', 'approved', 'mark', 'x', 'v1', 'a')",
    )


def test_approved_mark_cannot_be_rewritten_underneath_its_approval(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The defect that made the fingerprint decorative: approve, then edit the
    number. The approval row still read `approved`."""
    mid = _mark(conn, seed)
    assert "append-only" in _rejects(
        conn, "update mark set reported_amount = 9999999999 where id = %s", (mid,)
    )


def test_valuation_approval_must_name_its_evidence_set(conn: Conn, seed: dict[str, str]) -> None:
    """An approval that names no evidence approves nothing in particular."""
    mid = _mark(conn, seed)
    conn.execute(
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " mark_id, policy_version, actor_id)"
        " values ('valuation', 'approved', 'mark', %s, %s, 'v1', 'a')",
        (str(mid), mid),
    )
    with pytest.raises(psycopg.Error) as exc:
        conn.commit()  # deferred: fires at commit, not at insert
    conn.rollback()
    assert "names no evidence set" in str(exc.value)


def test_management_assessment_approval_must_bind_a_mark(conn: Conn, seed: dict[str, str]) -> None:
    """SPEC V12: R3 closes only on an assessment bound to the mark revision."""
    assert "management_assessment_binds_mark" in _rejects(
        conn,
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " actor_id) values ('management_assessment', 'approved', 'assessment', 'x', 'a')",
    )


def test_review_decision_cannot_be_updated(conn: Conn, seed: dict[str, str]) -> None:
    conn.execute(
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " actor_id) values ('transcription', 'approved', 'fact', 'x', 'a')"
    )
    assert "append-only" in _rejects(conn, "update review_decision set status = 'rejected'")


# ── INV-11 · money carries a currency; shares are integers ───────────────
def test_validated_amount_requires_currency(conn: Conn, seed: dict[str, str]) -> None:
    """An exact Decimal in an unstated currency is exactly wrong."""
    assert "validated_currency_together" in _rejects(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " validated_amount, derivation_status, derivation_reason)"
        " values (%s, %s, 100, 'USD', 100, 'derivable', 'x')",
        (seed["h"], seed["p"]),
    )


def test_derivable_mark_must_carry_the_derived_amount(conn: Conn, seed: dict[str, str]) -> None:
    assert "derivable_has_amount" in _rejects(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " derivation_status, derivation_reason) values (%s, %s, 100, 'USD', 'derivable', 'x')",
        (seed["h"], seed["p"]),
    )


def test_fractional_shares_are_rejected_not_rounded(conn: Conn, seed: dict[str, str]) -> None:
    """INV-11 / SPEC V13: a fractional share count is a REJECTION.

    This test failed against the first schema, which typed shares as `bigint`:
    Postgres silently rounded 100.5 to 101 — a plausible number nobody asked
    for, which is the precise failure mode the invariant exists to prevent.
    """
    assert "shares_whole" in _rejects(
        conn,
        "insert into lot (id, holding_id, security_class, shares, entry_pps,"
        " cost_amount, cost_currency, acquired_date)"
        " values ('frac', %s, 'sa', 100.5, 1.00, 100, 'USD', '2024-01-01')",
        (seed["h"],),
    )


def test_whole_share_counts_are_accepted(conn: Conn, seed: dict[str, str]) -> None:
    conn.execute(
        "insert into lot (id, holding_id, security_class, shares, entry_pps,"
        " cost_amount, cost_currency, acquired_date)"
        " values ('whole', %s, 'sa', 875000, 0.40, 350000, 'USD', '2025-09-30')",
        (seed["h"],),
    )
    conn.rollback()


def test_fractional_recap_result_is_rejected(conn: Conn, seed: dict[str, str]) -> None:
    """Sway: 800,000 x 1.09375 = 875,000 exactly. A ratio producing a fraction
    must fail rather than round into a plausible post-recap share count."""
    assert "shares_whole" in _rejects(
        conn,
        "insert into lot_conversion values (%s, '2025-09-30', 'series_a3', 875000.5, 1.09375)",
        (seed["lot"],),
    )


# ── INV-13 · reported ≠ validated ────────────────────────────────────────
def test_non_derivable_mark_keeps_its_reported_amount(conn: Conn, seed: dict[str, str]) -> None:
    """Moonfare FY2025 and Anthropic FY2025: the tracker figure is retained as
    reported while no validated amount exists."""
    conn.execute(
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " derivation_status, derivation_reason)"
        " values (%s, %s, 1048515, 'USD', 'not_derivable', 'NO_APPLICABLE_EVIDENCE')",
        (seed["h"], seed["p"]),
    )
    row = conn.execute(
        "select reported_amount, validated_amount from mark where holding_id = %s", (seed["h"],)
    ).fetchone()
    assert row == (1048515, None)
    conn.rollback()


# ── INV-5 · one mark per holding per period per revision ─────────────────
def test_mark_is_unique_per_holding_period_revision(conn: Conn, seed: dict[str, str]) -> None:
    _mark(conn, seed)
    err = _rejects(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " derivation_status, derivation_reason) values (%s, %s, 100, 'USD', 'not_derivable', 'x')",
        (seed["h"], seed["p"]),
    )
    assert "duplicate key" in err or "unique" in err.lower()


def test_assessment_cannot_bind_a_mark_from_another_period(
    conn: Conn, seed: dict[str, str]
) -> None:
    """A 2025 requirement attached to a 2024 mark: both FKs valid on their own,
    the pair incoherent. Enforced by composite FK rather than convention."""
    mid = _mark(conn, seed)
    row = conn.execute(
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R1', true) returning id",
        (seed["h"], seed["p"]),
    ).fetchone()
    assert row is not None
    assert "evidence_assessment" in _rejects(
        conn,
        "insert into evidence_assessment (requirement_id, mark_id, holding_id, period_id,"
        " verdict, policy_version) values (%s, %s, %s, 'ghost_period', 'sufficient', 'v1')",
        (row[0], mid, seed["h"]),
    )


# ── INV-8 · a derived figure input is a fact OR a child, never neither ───
def test_derived_figure_input_needs_exactly_one_source(conn: Conn) -> None:
    conn.execute(
        "insert into derived_figure (id, label, operator, amount, currency, unit)"
        " values (9001, 'total', 'sum', 10, 'USD', 'money')"
    )
    assert "exactly_one_source" in _rejects(
        conn, "insert into derived_figure_input (figure_id, ordinal) values (9001, 1)"
    )


def test_derived_figure_cannot_rest_on_an_unpromoted_candidate(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The back door: leave facts as candidates, sum them, and write the total
    to a mark. AI-proposed numbers become validated with no human disposal."""
    row = conn.execute(
        "insert into extracted_fact (claim_id, field_name, value_text,"
        " citation_quote, span_start, span_end) values (%s, 'pps', '8.00', 'q', 0, 1)"
        " returning id",
        (seed["cl"],),
    ).fetchone()
    assert row is not None
    conn.execute(
        "insert into derived_figure (id, label, operator, amount, currency, unit)"
        " values (9002, 'total', 'sum', 10, 'USD', 'money')"
    )
    assert "input_fact_is_promoted" in _rejects(
        conn,
        "insert into derived_figure_input (figure_id, fact_id, fact_state, ordinal)"
        " values (9002, %s, 'candidate', 1)",
        (row[0],),
    )


# ── INV-14 · a promoted fact must name an APPROVED TRANSCRIPTION ─────────
def test_canonical_fact_requires_a_promoting_decision(conn: Conn, seed: dict[str, str]) -> None:
    """The claim is real and every FK resolves, so only the named check can be
    what rejects this. The earlier version referenced a non-existent claim and
    accepted a foreign-key error, and so would have passed with the constraint
    deleted."""
    assert "fact_promoted_requires_decision" in _rejects(
        conn,
        "insert into extracted_fact (claim_id, state, field_name, value_text,"
        " citation_quote, span_start, span_end) values (%s, 'canonical', 'pps', '8.00', 'q', 0, 1)",
        (seed["cl"],),
    )


def test_promotion_requires_a_transcription_not_just_any_decision(
    conn: Conn, seed: dict[str, str]
) -> None:
    """A rejected packet decision promoted a fact to canonical in the first
    schema — `promoted_by` was an untyped FK to the whole decision table."""
    row = conn.execute(
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " actor_id) values ('packet', 'rejected', 'fact', 'x', 'a') returning id"
    ).fetchone()
    assert row is not None
    assert "fact_promoter_is_approved_transcription" in _rejects(
        conn,
        "insert into extracted_fact (claim_id, state, field_name, value_text, citation_quote,"
        " span_start, span_end, promoted_by, promoted_by_type, promoted_by_status)"
        " values (%s, 'canonical', 'pps', '8.00', 'q', 0, 1, %s, 'packet', 'rejected')",
        (seed["cl"], row[0]),
    )


def test_an_approved_transcription_does_promote(conn: Conn, seed: dict[str, str]) -> None:
    """The positive path — without it the constraint could be unsatisfiable and
    every negative test above would still pass."""
    row = conn.execute(
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " actor_id) values ('transcription', 'approved', 'fact', 'x', 'a') returning id"
    ).fetchone()
    assert row is not None
    conn.execute(
        "insert into extracted_fact (claim_id, state, field_name, value_text, citation_quote,"
        " span_start, span_end, promoted_by, promoted_by_type, promoted_by_status)"
        " values (%s, 'canonical', 'pps', '8.00', 'q', 0, 1, %s, 'transcription', 'approved')",
        (seed["cl"], row[0]),
    )
    conn.rollback()


# ── INV-20 · lineage-only never becomes packet-shaped ────────────────────
def test_lineage_only_period_cannot_carry_a_requirement(conn: Conn, seed: dict[str, str]) -> None:
    assert "pbc_requirement_period" in _rejects(
        conn,
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R1', true)",
        (seed["h"], seed["lp"]),
    )


def test_lineage_only_period_cannot_be_packeted(conn: Conn, seed: dict[str, str]) -> None:
    assert "packet_version_period" in _rejects(
        conn,
        "insert into packet_version (id, fund_id, period_id, state, schema_version,"
        " policy_version, generator_ref) values ('pk', %s, %s, 'draft', '1', 'v1', 'g')",
        (seed["fund"], seed["lp"]),
    )


# ── INV-12 · a gap observation is immutable ──────────────────────────────
def test_gap_observation_cannot_be_overwritten(conn: Conn, seed: dict[str, str]) -> None:
    """Rewriting with_counsel to not_located is INV-12's cheapest collapse:
    the gap looks resolved and the original observation is gone."""
    row = conn.execute(
        "insert into document_gap (holding_id, requirement, missing_document, kind, source_quote)"
        " values (%s, 'R1', 'doc', 'with_counsel', 'q') returning id",
        (seed["h"],),
    ).fetchone()
    assert row is not None
    assert "append-only" in _rejects(
        conn, "update document_gap set kind = 'not_located' where id = %s", (row[0],)
    )
