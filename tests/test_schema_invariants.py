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

import psycopg
import pytest

from tests.schema_helpers import CITED, DSN, Conn, make_mark, rejects, returned_id

pytestmark = pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")


# ── INV-7 · lots are immutable ───────────────────────────────────────────
def test_lot_cannot_be_updated(conn: Conn, seed: dict[str, str]) -> None:
    """Rewriting an acquisition date would silently move a position across a
    measurement-date boundary under an already-approved mark."""
    assert "append-only" in rejects(conn, "update lot set shares = 5 where id = %s", (seed["lot"],))


def test_lot_cannot_be_deleted(conn: Conn, seed: dict[str, str]) -> None:
    assert "append-only" in rejects(conn, "delete from lot where id = %s", (seed["lot"],))


# ── INV-10 · an approval binds immutable rows, not strings ───────────────
def test_valuation_approval_must_reference_a_realmake_mark(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The first schema accepted three arbitrary strings as a "fingerprint", so
    an approval bound nothing at all."""
    assert "valuation_approval_binds_mark" in rejects(
        conn,
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " policy_version, actor_id) values ('valuation', 'approved', 'mark', 'x', 'v1', 'a')",
    )


def test_approved_mark_cannot_be_rewritten_underneath_its_approval(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The defect that made the fingerprint decorative: approve, then edit the
    number. The approval row still read `approved`."""
    mid = make_mark(conn, seed)
    assert "append-only" in rejects(
        conn, "update mark set reported_amount = 9999999999 where id = %s", (mid,)
    )


def test_valuation_approval_must_name_its_evidence_set(conn: Conn, seed: dict[str, str]) -> None:
    """An approval that names no evidence approves nothing in particular."""
    mid = make_mark(conn, seed)
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


def test_management_assessment_approval_must_bind_amake_mark(
    conn: Conn, seed: dict[str, str]
) -> None:
    """SPEC V12: R3 closes only on an assessment bound to the mark revision."""
    assert "management_assessment_binds_mark" in rejects(
        conn,
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " actor_id) values ('management_assessment', 'approved', 'assessment', 'x', 'a')",
    )


def test_review_decision_cannot_be_updated(conn: Conn, seed: dict[str, str]) -> None:
    conn.execute(
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " actor_id) values ('transcription', 'approved', 'fact', 'x', 'a')"
    )
    assert "append-only" in rejects(conn, "update review_decision set status = 'rejected'")


# ── INV-11 · money carries a currency; shares are integers ───────────────
def test_validated_amount_requires_currency(conn: Conn, seed: dict[str, str]) -> None:
    """An exact Decimal in an unstated currency is exactly wrong."""
    assert "validated_currency_together" in rejects(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " validated_amount, derivation_status, derivation_reason)"
        " values (%s, %s, 100, 'USD', 100, 'derivable', 'x')",
        (seed["h"], seed["p"]),
    )


def test_derivable_mark_must_carry_the_derived_amount(conn: Conn, seed: dict[str, str]) -> None:
    assert "derivable_has_amount" in rejects(
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
    assert "shares_whole" in rejects(
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
    assert "shares_whole" in rejects(
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
    make_mark(conn, seed)
    err = rejects(
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
    mid = make_mark(conn, seed)
    row = conn.execute(
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R1', true) returning id",
        (seed["h"], seed["p"]),
    ).fetchone()
    assert row is not None
    assert "evidence_assessment" in rejects(
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
    assert "exactly_one_source" in rejects(
        conn, "insert into derived_figure_input (figure_id, ordinal) values (9001, 1)"
    )


def test_derived_figure_cannot_rest_on_an_unpromoted_candidate(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The back door: leave facts as candidates, sum them, and write the total
    to a mark. AI-proposed numbers become validated with no human disposal."""
    row = conn.execute(
        "insert into extracted_fact (claim_id, field_name, value_text,"
        " value_numeric, citation_quote, span_start, span_end)"
        " values (%s, 'pps', %s, %s, %s, %s, %s) returning id",
        (seed["cl"], *CITED),
    ).fetchone()
    assert row is not None
    conn.execute(
        "insert into derived_figure (id, label, operator, amount, currency, unit)"
        " values (9002, 'total', 'sum', 10, 'USD', 'money')"
    )
    assert "input_fact_is_promoted" in rejects(
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
    assert "fact_promoted_requires_decision" in rejects(
        conn,
        "insert into extracted_fact (claim_id, state, field_name, value_text,"
        " value_numeric, citation_quote, span_start, span_end)"
        " values (%s, 'canonical', 'pps', %s, %s, %s, %s, %s)",
        (seed["cl"], *CITED),
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
    assert "fact_promoter_is_approved_transcription" in rejects(
        conn,
        "insert into extracted_fact (claim_id, state, field_name, value_text, value_numeric,"
        " citation_quote, span_start, span_end, promoted_by, promoted_by_type, promoted_by_status)"
        " values (%s, 'canonical', 'pps', %s, %s, %s, %s, %s, %s, 'packet', 'rejected')",
        (seed["cl"], *CITED, row[0]),
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
        "insert into extracted_fact (claim_id, state, field_name, value_text, value_numeric,"
        " citation_quote, span_start, span_end, promoted_by, promoted_by_type, promoted_by_status)"
        " values (%s, 'canonical', 'pps', %s, %s, %s, %s, %s, %s, 'transcription', 'approved')",
        (seed["cl"], *CITED, row[0]),
    )
    conn.rollback()


# ── INV-20 · lineage-only never becomes packet-shaped ────────────────────
def test_lineage_only_period_cannot_carry_a_requirement(conn: Conn, seed: dict[str, str]) -> None:
    assert "pbc_requirement_period" in rejects(
        conn,
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R1', true)",
        (seed["h"], seed["lp"]),
    )


def test_lineage_only_period_cannot_be_packeted(conn: Conn, seed: dict[str, str]) -> None:
    assert "packet_version_period" in rejects(
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
    assert "append-only" in rejects(
        conn, "update document_gap set kind = 'not_located' where id = %s", (row[0],)
    )


def test_gap_remediation_is_append_only_history(conn: Conn, seed: dict[str, str]) -> None:
    """Once the observation was frozen, editing the remediation row became the
    new cheapest collapse — the gap reads `received` with no record of the
    request that preceded it."""
    gap = returned_id(
        conn,
        "insert into document_gap (holding_id, requirement, missing_document, kind,"
        " source_quote) values (%s, 'R1', 'doc', 'with_counsel', 'q') returning id",
        (seed["h"],),
    )
    rem = returned_id(
        conn,
        "insert into document_gap_remediation (gap_id, state) values (%s, 'requested')"
        " returning id",
        (gap,),
    )
    assert "append-only" in rejects(
        conn, "update document_gap_remediation set state = 'received' where id = %s", (rem,)
    )


# ── INV-11 · storage must refuse what it cannot represent exactly ────────
def test_over_precise_money_is_rejected_not_quantised(conn: Conn, seed: dict[str, str]) -> None:
    """`numeric(20,4)` rounded 1109.999889 to 1109.9999 with nothing objecting —
    the same silent coercion as the old `bigint` shares column, one layer down.

    A CHECK on a narrow column cannot catch this: Postgres coerces to the column
    scale BEFORE the constraint runs, so the check only ever sees the already
    rounded value. The column is therefore wide enough for the bad value to
    survive to be judged, exactly as `shares` became numeric rather than bigint.
    """
    assert "reported_amount_scale" in rejects(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " derivation_status, derivation_reason)"
        " values (%s, %s, 1109.999889, 'USD', 'not_derivable', 'x')",
        (seed["h"], seed["p"]),
    )


def test_money_at_its_declared_scale_is_accepted(conn: Conn, seed: dict[str, str]) -> None:
    conn.execute(
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " derivation_status, derivation_reason)"
        " values (%s, %s, 1109.9999, 'USD', 'not_derivable', 'x')",
        (seed["h"], seed["p"]),
    )
    conn.rollback()


def test_over_precise_price_per_share_is_rejected(conn: Conn, seed: dict[str, str]) -> None:
    """PPS is declared at six places; a seventh must fail rather than round into
    a price that was never quoted."""
    assert "price_per_share_scale" in rejects(
        conn,
        "insert into claim (id, document_version_id, holding_id, claim_key, source_class,"
        " execution_status, issued_date, applicable_from, price_per_share)"
        " values ('overprecise', %s, %s, 'k', 'company_cap_table', 'executed',"
        " '2025-06-30', '2025-01-01', 3.3333333)",
        (seed["dv"], seed["h"]),
    )


def test_always_applicable_requirement_cannot_be_stored_as_inapplicable(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The contract layer made this unrepresentable; the database still stored
    it. An assembler reading `applicable` would then skip R1 entirely, and a
    holding with no existence-and-cost evidence would read as fully supported."""
    assert "always_applicable_requirements_are_applicable" in rejects(
        conn,
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R1', false)",
        (seed["h"], seed["p"]),
    )


def test_conditional_requirement_may_be_stored_as_inapplicable(
    conn: Conn, seed: dict[str, str]
) -> None:
    conn.execute(
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R4', false)",
        (seed["h"], seed["p"]),
    )
    conn.rollback()


def test_always_applicable_requirement_cannot_be_assessed_not_applicable(
    conn: Conn, seed: dict[str, str]
) -> None:
    mid = make_mark(conn, seed)
    req = returned_id(
        conn,
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R2', true) returning id",
        (seed["h"], seed["p"]),
    )
    assert "always applicable" in rejects(
        conn,
        "insert into evidence_assessment (requirement_id, mark_id, holding_id, period_id,"
        " verdict, policy_version) values (%s, %s, %s, %s, 'not_applicable', 'v1')",
        (req, mid, seed["h"], seed["p"]),
    )
